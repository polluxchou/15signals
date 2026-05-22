"""
P3 · 三个后台维护任务。

设计原则：
  - 每个函数返回一个统计 dict 便于日志 / HTTP 响应
  - 失败不抛——记日志，继续下一条
  - 都是可重入的（rerun 不会重复处理）
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

from .deepseek_client import DeepSeekError, call_summary, get_client, get_model_scorer
from .memory import extract_memories_from_summary
from .prompts import build_summary_system_prompt, build_summary_user_message
from .aggregation import aggregate_dimensions, overall_intensity, top_signals
from .db import persist_summary
from .signals_meta import SIGNAL_NAMES

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# DB connection helper
# ─────────────────────────────────────────────────────────

@contextmanager
def _conn() -> Iterator[Any]:
    import psycopg
    from pgvector.psycopg import register_vector
    url = os.environ["DATABASE_URL"]
    conn = psycopg.connect(url, autocommit=False)
    try:
        register_vector(conn)
        yield conn
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# 任务 1 · ROLLOVER · 跨日强制关闭
# ═════════════════════════════════════════════════════════════════════════════

def find_rollover_candidates(grace_minutes: int = 5) -> list[dict]:
    """
    找出需要被强制关闭的 active sessions（按用户时区判定 8:00 跨日）。

    规则（spec §9.4）：
      1. status = 'active'
      2. last_active_at < now() - grace_minutes（避免打断正在输入的用户）
      3. 用户本地时间已过 8:00
      4. session 的"开始日"在用户本地时区上已经是昨天或更早
    """
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    s.id, s.user_id, s.mentor_id, s.turn_count,
                    s.last_active_at, u.timezone, u.email
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.status = 'active'
                  AND s.last_active_at < now() - make_interval(mins => %s)
                  -- 用户当地时间已过 8:00
                  AND (now() AT TIME ZONE u.timezone)::time >= '08:00'
                  -- session 的开始日（用户当地时区）严格早于今天（当地时区）
                  AND date_trunc('day', s.started_at AT TIME ZONE u.timezone)
                      < date_trunc('day', now() AT TIME ZONE u.timezone)
                ORDER BY s.last_active_at ASC
                """,
                (grace_minutes,),
            )
            return [
                {
                    "session_id": r[0],
                    "user_id": r[1],
                    "mentor_id": r[2],
                    "turn_count": r[3],
                    "last_active_at": r[4],
                    "timezone": r[5],
                    "email": r[6],
                }
                for r in cur.fetchall()
            ]


def fetch_session_messages(session_id: int) -> list[dict]:
    """读 session 的所有 turns，转成 OpenAI 风格 messages 列表。"""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT role, content
                FROM turns
                WHERE session_id = %s
                ORDER BY turn_index ASC
                """,
                (session_id,),
            )
            return [
                {"role": ("assistant" if r[0] == "mentor" else "user"), "content": r[1]}
                for r in cur.fetchall()
            ]


def _generate_summary_payload(mentor_id: str, messages: list[dict]) -> dict | None:
    """Build prompt → 调 DeepSeek → 校验 → 聚合。返回 summary_payload 或 None（失败）。"""
    sys_prompt = build_summary_system_prompt(mentor_id)
    user_msg = build_summary_user_message(messages)

    try:
        llm_out = call_summary(sys_prompt, user_msg)
    except DeepSeekError as e:
        logger.warning("DeepSeek summary failed: %s", e)
        return None

    try:
        title = str(llm_out["title"]).strip()
        raw_scores = llm_out["signal_scores"]
        emotional_summary = str(llm_out["emotional_summary"]).strip()
        raw_moments = llm_out.get("moments") or []
    except (KeyError, TypeError) as e:
        logger.warning("LLM output malformed: %s", e)
        return None

    # 校验信号分
    signal_scores: dict[str, float] = {}
    for name in SIGNAL_NAMES:
        v = raw_scores.get(name, 0.0)
        try:
            f = float(v)
        except (TypeError, ValueError):
            f = 0.0
        signal_scores[name] = max(0.0, min(1.0, f))

    # 校验 moments（quote 必须来自原文）
    original_texts = [m["content"] for m in messages]
    moments = []
    for m in raw_moments[:3]:
        try:
            sig = m.get("signal_name")
            if sig not in SIGNAL_NAMES:
                continue
            quotes = []
            for q in (m.get("quotes") or []):
                qt = (q.get("text") or "").strip()
                if not qt:
                    continue
                qt_norm = qt.replace(" ", "").replace("\n", "")
                in_orig = any(qt_norm in orig.replace(" ", "").replace("\n", "") for orig in original_texts)
                if not in_orig:
                    continue
                sp = q.get("speaker", "user")
                if sp not in ("user", "mentor"):
                    sp = "user"
                quotes.append({"speaker": sp, "text": qt})
            if not quotes:
                continue
            moments.append({
                "signal_name": sig,
                "quotes": quotes,
                "echo": str(m.get("echo", "")).strip(),
            })
        except Exception:
            continue

    return {
        "title": title,
        "overall_intensity": overall_intensity(signal_scores),
        "dimension_scores": aggregate_dimensions(signal_scores),
        "signal_scores": signal_scores,
        "top_signals": top_signals(signal_scores),
        "emotional_summary": emotional_summary,
        "moments": moments,
        "mentor_id": mentor_id,
        "rubric_version": "rubric-v0.2",
    }


def run_rollover(grace_minutes: int = 5, dry_run: bool = False) -> dict:
    """
    扫描 + 关闭所有到点的 active sessions。

    流程（每个候选）：
      1. 读 turns
      2. 若 turns < 2 → 直接 mark closed_by_rollover，不生成 summary
      3. 否则 → 调 DeepSeek 生成 summary_payload → persist_summary(close_reason='closed_by_rollover')
      4. 抽取 episodic_memories
    """
    candidates = find_rollover_candidates(grace_minutes)
    stats = {
        "scanned": len(candidates),
        "closed_with_summary": 0,
        "closed_without_summary": 0,
        "memories_extracted": 0,
        "errors": 0,
        "session_ids": [c["session_id"] for c in candidates],
    }

    if dry_run:
        logger.info("[dry-run] would rollover %d sessions: %s", len(candidates), stats["session_ids"])
        return stats

    for c in candidates:
        sid = c["session_id"]
        uid = c["user_id"]
        mid = c["mentor_id"]
        try:
            messages = fetch_session_messages(sid)
            if len(messages) < 2:
                # 太短，没必要生成 summary
                with _conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE sessions SET status = 'closed_by_rollover', closed_at = COALESCE(closed_at, now()) WHERE id = %s",
                            (sid,),
                        )
                        conn.commit()
                stats["closed_without_summary"] += 1
                logger.info("rollover[%d] closed without summary (too short: %d msgs)", sid, len(messages))
                continue

            payload = _generate_summary_payload(mid, messages)
            if payload is None:
                # 生成失败也要关闭，否则下次还会扫到
                with _conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE sessions SET status = 'closed_by_rollover', closed_at = COALESCE(closed_at, now()) WHERE id = %s",
                            (sid,),
                        )
                        conn.commit()
                stats["closed_without_summary"] += 1
                stats["errors"] += 1
                logger.warning("rollover[%d] closed without summary (LLM failed)", sid)
                continue

            persist_result = persist_summary(
                user_id=uid, session_id=sid, mentor_id=mid,
                summary_payload=payload, raw_messages=messages,
                close_reason="closed_by_rollover",
            )

            if persist_result.get("persisted"):
                stats["closed_with_summary"] += 1
                # 抽取记忆
                try:
                    n = extract_memories_from_summary(uid, sid, mid, payload)
                    stats["memories_extracted"] += n
                except Exception as e:
                    logger.warning("rollover[%d] memory extraction failed: %s", sid, e)
                logger.info("rollover[%d] OK (msgs=%d, memories=%d)", sid, len(messages), n if "n" in dir() else 0)
            else:
                stats["errors"] += 1
                logger.warning("rollover[%d] persist_summary failed: %s", sid, persist_result.get("reason"))
        except Exception as e:
            logger.exception("rollover[%d] error: %s", sid, e)
            stats["errors"] += 1

    return stats


# ═════════════════════════════════════════════════════════════════════════════
# 任务 2 · DECAY · 显著度衰减
# ═════════════════════════════════════════════════════════════════════════════

def run_decay(
    grace_days: int = 7,
    daily_decay: float = 0.95,
    soft_floor: float = 0.05,
) -> dict:
    """
    给所有"超过 grace_days 没被强化的记忆"做一次衰减。

    应用乘法衰减：current_salience *= daily_decay
    （每日 cron 跑一次 = 5% 衰减；7 天没碰 → 衰减一次；之后每天都会再衰减一次）

    soft_floor: 衰到 < soft_floor 的记忆从主检索池退出（仍保留行，可恢复）

    Returns: {decayed, dropped_below_floor, remaining_active}
    """
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH updated AS (
                    UPDATE episodic_memories
                    SET current_salience = current_salience * %s
                    WHERE deleted_at IS NULL
                      AND last_reinforced_at < now() - make_interval(days => %s)
                      AND current_salience > %s
                    RETURNING id, current_salience
                )
                SELECT
                    count(*) AS decayed,
                    sum(CASE WHEN current_salience < %s THEN 1 ELSE 0 END) AS dropped
                FROM updated
                """,
                (daily_decay, grace_days, soft_floor, soft_floor),
            )
            row = cur.fetchone()
            decayed = row[0] or 0
            dropped = row[1] or 0

            cur.execute(
                "SELECT count(*) FROM episodic_memories WHERE deleted_at IS NULL AND current_salience >= %s",
                (soft_floor,),
            )
            active = cur.fetchone()[0]
            conn.commit()

    logger.info("decay: decayed=%d, dropped_below_floor=%d, remaining_active=%d",
                decayed, dropped, active)
    return {
        "decayed": decayed,
        "dropped_below_floor": dropped,
        "remaining_active": active,
        "grace_days": grace_days,
        "daily_decay": daily_decay,
    }


# ═════════════════════════════════════════════════════════════════════════════
# 任务 3 · CONSOLIDATE · 巩固到语义画像
# ═════════════════════════════════════════════════════════════════════════════

CONSOLIDATION_THRESHOLD = 3  # reinforcement_count >= 此值时巩固


def find_consolidation_candidates() -> dict[int, list[dict]]:
    """按 user_id 分组，找出该用户中达到巩固阈值且未巩固的记忆。"""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    user_id, id, memory_type, source_quote, content,
                    related_signals, current_salience, reinforcement_count
                FROM episodic_memories
                WHERE deleted_at IS NULL
                  AND consolidated_to_semantic = false
                  AND reinforcement_count >= %s
                ORDER BY user_id, current_salience DESC
                """,
                (CONSOLIDATION_THRESHOLD,),
            )
            groups: dict[int, list[dict]] = {}
            for r in cur.fetchall():
                uid = r[0]
                groups.setdefault(uid, []).append({
                    "memory_id": r[1],
                    "memory_type": r[2],
                    "source_quote": r[3],
                    "content": r[4],
                    "related_signals": r[5] or [],
                    "salience": float(r[6]),
                    "reinforcement_count": r[7],
                })
            return groups


def _build_consolidation_prompt(
    memories: list[dict],
    existing_profile: dict | None = None,
) -> tuple[str, str]:
    """构建给 LLM 的提示：把新记忆**合并**进既有 profile，不是替换。

    当 existing_profile 存在时，prompt 强调"保留 + 增补"而不是重写。
    """
    has_existing = existing_profile is not None and any(
        existing_profile.get(k) for k in ("core_themes", "relational_map", "self_narratives", "recurring_concerns")
    )

    if not has_existing:
        # 首次巩固：从零生成
        sys = """你是一位长期观察这位用户的导师。下面是这位用户在多次对话中**反复出现**的话和模式。

请把它们提炼成几条**稳定的、关于这位用户的事实**——不是症状清单，而是导师对一个人的认知。

输出 JSON，结构：
{
  "core_themes": ["..."],                  // 3-5 个反复出现的主题（短语，不超过 8 字）
  "self_narratives": ["..."],              // 1-3 条用户对自己的典型描述
  "relational_map": {"母亲": "...", ...},  // key=人物角色，value=与该用户的关系性质（短描述）
  "recurring_concerns": ["..."]            // 1-3 个反复回到的具体担忧
}

要求：
- 只用对话语言，不用医学/心理术语
- 不要扩张未给出的信息，宁可少一项也别编
- 输出纯 JSON，第一个字符 `{`，最后一个字符 `}`"""
    else:
        # 增量巩固：合并模式
        sys = """你是一位长期观察这位用户的导师。你已经积累了对这位用户的一份**理解**，
现在又有一批**新强化的记忆**进入。你的任务不是**重写**这份理解——而是**让它继续生长**。

输出一份**合并后的** profile JSON，结构同已有 profile：
{
  "core_themes": [...],          // 主题数组，3-6 条
  "self_narratives": [...],      // 1-4 条
  "relational_map": {...},       // 人物 → 关系描述
  "recurring_concerns": [...]    // 1-4 条
}

**合并规则（极其重要）**：

1. **保留**：已有 profile 中的每一项，**默认都保留**。
   - 即使新记忆没有提到"母亲"，"母亲"主题如果之前在，仍然在。
   - 用户的某些主题是**稳定的**——童年、家人、工作核心矛盾——即使几周没谈也是这个人的一部分。

2. **精化**：如果新记忆**深化或修正**了已有主题 → 改写那一条让它更准。
   - 比如已有"睡眠问题"，新记忆是"凌晨 4 点醒"——可以精化为"凌晨四点早醒"。

3. **新增**：新记忆带来**已有 profile 完全没覆盖到**的方向 → 加入新条目。

4. **绝不**：因为新记忆没提到，就删掉已有的条目。

5. 数组保持精简：每个数组**最多 6 条**——如果合并后超出，淘汰**最不被反复强化**的那条。

6. relational_map 用合并而非替换：已有的人继续在；新出现的人加入。

输出纯 JSON，第一个字符 `{`，最后一个字符 `}`。"""

    user_parts = []

    if has_existing:
        user_parts.append("【你已有的 profile（绝对要保留主体结构）】\n")
        user_parts.append(json.dumps(existing_profile, ensure_ascii=False, indent=2))
        user_parts.append("\n\n【这批新强化的记忆】\n")
    else:
        user_parts.append("以下是这位用户的反复出现的话/模式：\n")

    for i, m in enumerate(memories, 1):
        sal = m["salience"]
        reinf = m["reinforcement_count"]
        sigs = ",".join(m.get("related_signals") or [])
        if m.get("source_quote"):
            user_parts.append(f"{i}. [原话, 显著度={sal:.2f}, 强化={reinf}次, 信号={sigs}]")
            user_parts.append(f"   「{m['source_quote']}」")
        else:
            user_parts.append(f"{i}. [模式总结, 显著度={sal:.2f}, 强化={reinf}次]")
            user_parts.append(f"   {m['content'][:200]}")

    if has_existing:
        user_parts.append("\n\n请按 system 中的合并规则，输出更新后的 profile（合并已有 + 新增）。")
    else:
        user_parts.append("\n请按 system 中规定的结构输出 profile。")

    return sys, "\n".join(user_parts)


def consolidate_user(user_id: int, memories: list[dict]) -> dict:
    """
    巩固单个用户的记忆：
      1. 读取既有 user_semantic_profile（如果有）
      2. LLM 把新记忆**合并**进既有 profile（不是替换）
      3. UPSERT user_semantic_profile
      4. mark episodic_memories.consolidated_to_semantic = true
    """
    if not memories:
        return {"user_id": user_id, "skipped": True, "reason": "no candidates"}

    # 读现有 profile（用于合并模式）
    existing_profile: dict | None = None
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT profile FROM user_semantic_profile WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if row and row[0]:
                existing_profile = row[0]

    sys, usr = _build_consolidation_prompt(memories, existing_profile=existing_profile)

    client = get_client()
    model = get_model_scorer()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": sys}, {"role": "user", "content": usr}],
            temperature=0.3,
            max_tokens=1000,  # 合并模式可能更长
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        profile = json.loads(raw)
    except Exception as e:
        logger.warning("consolidate user=%d LLM failed: %s", user_id, e)
        return {"user_id": user_id, "ok": False, "reason": str(e)}

    # 安全网：如果合并后的 profile 比既有的"缩水严重"，警告 + 保护性 merge
    if existing_profile:
        shrunk = _detect_shrinkage(existing_profile, profile)
        if shrunk:
            logger.warning("consolidate user=%d LLM 输出疑似丢失内容: %s", user_id, shrunk)
            profile = _safe_merge(existing_profile, profile)

    # UPSERT user_semantic_profile，并把 episodic memories 标记 consolidated
    memory_ids = [m["memory_id"] for m in memories]
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_semantic_profile (user_id, profile, version, last_consolidated_at, consolidation_count)
                VALUES (%s, %s::jsonb, 1, now(), 1)
                ON CONFLICT (user_id) DO UPDATE
                SET profile = EXCLUDED.profile,
                    version = user_semantic_profile.version + 1,
                    last_consolidated_at = now(),
                    consolidation_count = user_semantic_profile.consolidation_count + 1
                """,
                (user_id, json.dumps(profile, ensure_ascii=False)),
            )
            cur.execute(
                """
                UPDATE episodic_memories
                SET consolidated_to_semantic = true, consolidated_at = now()
                WHERE id = ANY(%s)
                """,
                (memory_ids,),
            )
            conn.commit()

    return {
        "user_id": user_id,
        "ok": True,
        "memories_consolidated": len(memory_ids),
        "profile_keys": list(profile.keys()),
        "merged_with_existing": existing_profile is not None,
    }


def _detect_shrinkage(old: dict, new: dict) -> dict | None:
    """检查合并后的 profile 是否疑似丢了内容。返回 {field: lost_items} 或 None。"""
    lost: dict[str, list] = {}

    # 数组字段：检查 old 里超过 1 个的，new 里少了几个
    for field in ("core_themes", "self_narratives", "recurring_concerns"):
        old_items = old.get(field) or []
        new_items = new.get(field) or []
        if len(old_items) > 1 and len(new_items) < max(1, len(old_items) - 1):
            # 丢了 ≥ 2 项
            lost[field] = old_items

    # relational_map：检查 key 是否丢失
    old_rel = old.get("relational_map") or {}
    new_rel = new.get("relational_map") or {}
    if isinstance(old_rel, dict) and isinstance(new_rel, dict):
        missing_keys = [k for k in old_rel if k not in new_rel]
        if missing_keys:
            lost["relational_map"] = missing_keys

    return lost if lost else None


def _safe_merge(old: dict, new: dict) -> dict:
    """保护性合并：如果 LLM 输出疑似丢了内容，把老的内容补回来。

    策略：
      - 数组字段：union 去重，新的在前（更鲜活），上限 6 条
      - relational_map：合并，新值优先
    """
    merged: dict = dict(new)  # 以新为基底

    for field in ("core_themes", "self_narratives", "recurring_concerns"):
        old_items = old.get(field) or []
        new_items = new.get(field) or []
        if not old_items and not new_items:
            continue
        # 新在前 + 老在后，去重后取前 6
        seen: set[str] = set()
        combined: list[str] = []
        for item in list(new_items) + list(old_items):
            if not isinstance(item, str):
                continue
            key = item.strip()
            if key and key not in seen:
                seen.add(key)
                combined.append(item)
            if len(combined) >= 6:
                break
        merged[field] = combined

    # relational_map：dict 合并，old 的 key 如果 new 没覆盖就保留
    old_rel = old.get("relational_map") or {}
    new_rel = new.get("relational_map") or {}
    if isinstance(old_rel, dict) and isinstance(new_rel, dict):
        rel = dict(old_rel)
        rel.update(new_rel)
        merged["relational_map"] = rel

    return merged


def run_consolidate() -> dict:
    """扫描所有用户，巩固达阈值的记忆。"""
    groups = find_consolidation_candidates()
    stats = {
        "users_processed": 0,
        "users_with_updates": 0,
        "total_memories_consolidated": 0,
        "errors": 0,
        "user_results": [],
    }
    if not groups:
        logger.info("consolidate: no candidates")
        return stats

    for uid, mems in groups.items():
        stats["users_processed"] += 1
        result = consolidate_user(uid, mems)
        stats["user_results"].append(result)
        if result.get("ok"):
            stats["users_with_updates"] += 1
            stats["total_memories_consolidated"] += result.get("memories_consolidated", 0)
        else:
            stats["errors"] += 1

    logger.info(
        "consolidate: processed=%d, updated=%d, memories=%d, errors=%d",
        stats["users_processed"], stats["users_with_updates"],
        stats["total_memories_consolidated"], stats["errors"],
    )
    return stats
