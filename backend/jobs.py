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


def _build_consolidation_prompt(memories: list[dict]) -> tuple[str, str]:
    """构建给 LLM 的提示：从一组反复出现的记忆里，提炼稳定的"关于该用户的事实"。"""
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

    user_lines = ["以下是这位用户的反复出现的话/模式：\n"]
    for i, m in enumerate(memories, 1):
        kind = m["memory_type"]
        sal = m["salience"]
        reinf = m["reinforcement_count"]
        sigs = ",".join(m.get("related_signals") or [])
        if m.get("source_quote"):
            user_lines.append(f"{i}. [原话, 显著度={sal:.2f}, 强化={reinf}次, 信号={sigs}]")
            user_lines.append(f"   「{m['source_quote']}」")
        else:
            user_lines.append(f"{i}. [模式总结, 显著度={sal:.2f}, 强化={reinf}次]")
            user_lines.append(f"   {m['content'][:200]}")
    return sys, "\n".join(user_lines)


def consolidate_user(user_id: int, memories: list[dict]) -> dict:
    """
    巩固单个用户的记忆：
      1. LLM 提炼 profile
      2. UPSERT user_semantic_profile
      3. mark episodic_memories.consolidated_to_semantic = true
    """
    if not memories:
        return {"user_id": user_id, "skipped": True, "reason": "no candidates"}

    sys, usr = _build_consolidation_prompt(memories)

    client = get_client()
    model = get_model_scorer()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": sys}, {"role": "user", "content": usr}],
            temperature=0.3,
            max_tokens=800,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        profile = json.loads(raw)
    except Exception as e:
        logger.warning("consolidate user=%d LLM failed: %s", user_id, e)
        return {"user_id": user_id, "ok": False, "reason": str(e)}

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
    }


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
