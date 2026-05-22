"""
P? · 主题关键词（spec §9.5）

每 3 轮对话后，对最近 5 轮重评一次"当前会话的主题"。
不是替换——是合并：已有主题的 confidence 升降，新主题加入候选池。

数据结构（存在 sessions.current_themes JSONB）：
[
  {
    "keyword": "母亲",
    "confidence": 0.78,
    "first_seen_turn": 5,
    "last_reinforced_turn": 11
  },
  ...  // 最多 3 条，按 confidence 降序
]
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

from .deepseek_client import DeepSeekError, get_client, get_model_scorer

logger = logging.getLogger(__name__)

# 触发条件
TURNS_BETWEEN_REEVAL = 3       # 每 3 轮 user 输入触发一次（即每 6 个 turn）
LOOKBACK_TURNS = 5             # 重评时读最近 N 条 turns
TOP_K = 3                      # 保留 Top-K 主题
NEW_THEME_CONFIDENCE_FLOOR = 0.55  # 新主题至少要这个 confidence 才被纳入
SEMANTIC_OVERLAP_THRESHOLD = 0.7   # confidence 加权时，候选 vs 现有的字面/语义重叠判定（简化为字符串相似）
DECAY_PER_INACTIVE = 0.85      # 每"未被强化的一轮"，confidence 衰减乘数
DROP_BELOW = 0.25              # 衰减到此值以下从 current_themes 移除


# ─────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────

@contextmanager
def _conn() -> Iterator[Any]:
    import psycopg
    url = os.environ["DATABASE_URL"]
    conn = psycopg.connect(url, autocommit=False)
    try:
        yield conn
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────
# 触发判定
# ─────────────────────────────────────────────────────────

def should_reevaluate_themes(turn_count_after_this_user_turn: int) -> bool:
    """
    在 /session/turn 写完两条 turn 后调用。
    turn_count_after_this_user_turn 是 user turn 自己的 turn_index（不包括 mentor 回应）。

    简化策略：每隔 TURNS_BETWEEN_REEVAL 次 user 输入触发一次。
    """
    if turn_count_after_this_user_turn <= 0:
        return False
    # user turn 的 turn_index 都是奇数（1, 3, 5, ...）
    # 触发：turn_index == 1, 7, 13, ... (即 user_count = 1, 4, 7, ... → 每 3 次 user)
    if turn_count_after_this_user_turn % 2 == 1:
        user_count = (turn_count_after_this_user_turn + 1) // 2
        return user_count == 1 or (user_count - 1) % TURNS_BETWEEN_REEVAL == 0
    return False


# ─────────────────────────────────────────────────────────
# LLM 抽取
# ─────────────────────────────────────────────────────────

def _build_themes_prompt(
    recent_turns: list[dict],
    existing_themes: list[dict],
) -> tuple[str, str]:
    """构建主题抽取 prompt。"""
    sys = """你是对话主题观察员。给你一段最近的对话，请抽出**用户当下反复触及的 2-3 个主题**。

输出 JSON：
{
  "candidates": [
    {"keyword": "短语，2-6字", "confidence": 0.0-1.0},
    ...  // 0-5 条
  ]
}

# 抽取规则
1. **keyword 必须是用户语言里真实出现/紧贴的概念**，不要用"焦虑"、"抑郁"等诊断术语
   ✅ "母亲" "凌晨醒来" "工作意义" "身份漂移"
   ❌ "情感隔离" "精神焦虑" "存在危机"（太学术）

2. **confidence 反映这个主题在最近对话中的密度**：
   - 0.8+：主题占据多数轮次
   - 0.5-0.7：明确出现至少 2 次
   - 0.3-0.5：触及但未展开
   - < 0.3：不要输出

3. **只看用户真实说过的内容**，不要从导师的提问里反推。

4. 主题应该是**用户当下在谈什么**，不是"用户的整体画像"。

# 输出
只输出 JSON。第一个字符 `{`，最后一个字符 `}`。"""

    user_lines = []

    if existing_themes:
        user_lines.append("【已经识别出的当前主题（仅供参考，不要硬性保留）】")
        for t in existing_themes:
            user_lines.append(f"  · {t['keyword']} (confidence={t.get('confidence', 0):.2f})")
        user_lines.append("")

    user_lines.append(f"【最近 {len(recent_turns)} 条对话】\n")
    for t in recent_turns:
        speaker = "用户" if t["role"] == "user" else "导师"
        content = (t["content"] or "").strip()
        user_lines.append(f"[{t['turn_index']}] {speaker}：{content}")

    user_lines.append("\n请按 system 中的规则输出 candidates。")
    return sys, "\n".join(user_lines)


def call_themes_extraction(recent_turns: list[dict], existing_themes: list[dict]) -> list[dict]:
    """调 DeepSeek 抽取候选主题。返回 [{keyword, confidence}, ...]"""
    client = get_client()
    model = get_model_scorer()
    sys, usr = _build_themes_prompt(recent_turns, existing_themes)

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": sys}, {"role": "user", "content": usr}],
            temperature=0.2,
            max_tokens=400,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        candidates = data.get("candidates") or []
        # 校验 + 归一化
        out: list[dict] = []
        for c in candidates:
            kw = (c.get("keyword") or "").strip()
            try:
                conf = float(c.get("confidence", 0))
            except (TypeError, ValueError):
                conf = 0.0
            if kw and 0.0 < conf <= 1.0:
                out.append({"keyword": kw, "confidence": max(0.0, min(1.0, conf))})
        return out
    except Exception as e:
        logger.warning("call_themes_extraction failed: %s", e)
        return []


# ─────────────────────────────────────────────────────────
# 合并 / 更新
# ─────────────────────────────────────────────────────────

def _is_similar(a: str, b: str) -> bool:
    """简化的主题相似判定：包含 / 被包含 / 字符重叠 >= 阈值。"""
    if a == b:
        return True
    if a in b or b in a:
        return True
    # 简单字符集交并比
    set_a, set_b = set(a), set(b)
    if not set_a or not set_b:
        return False
    overlap = len(set_a & set_b) / len(set_a | set_b)
    return overlap >= SEMANTIC_OVERLAP_THRESHOLD


def merge_themes(
    existing: list[dict],
    candidates: list[dict],
    current_user_turn_index: int,
) -> list[dict]:
    """
    合并算法：
      a) 候选与现有主题相近 → 提升现有主题的 confidence + 更新 last_reinforced_turn
      b) 候选为新主题且 confidence > floor → 加入
      c) 现有主题超过 4 轮未被强化 → confidence 乘 DECAY_PER_INACTIVE
      d) confidence < DROP_BELOW 的剔除
      e) 排序取 Top-K
    """
    existing = list(existing or [])
    candidates = list(candidates or [])

    matched_existing_idx: set[int] = set()

    # 步骤 1: 已有 vs 候选 → 匹配 / 强化
    for c in candidates:
        for i, e in enumerate(existing):
            if _is_similar(c["keyword"], e["keyword"]):
                matched_existing_idx.add(i)
                # 强化：confidence 用 max + 软增长
                old_conf = e.get("confidence", 0.0)
                new_conf = max(old_conf, c["confidence"])
                # 多次强化的小增量
                if c["confidence"] > old_conf:
                    new_conf = min(1.0, new_conf + 0.05)
                e["confidence"] = round(new_conf, 3)
                e["last_reinforced_turn"] = current_user_turn_index
                break

    # 步骤 2: 未被匹配的候选 → 视为新主题（若 confidence 过线）
    for c in candidates:
        is_new = True
        for e in existing:
            if _is_similar(c["keyword"], e["keyword"]):
                is_new = False
                break
        if is_new and c["confidence"] >= NEW_THEME_CONFIDENCE_FLOOR:
            existing.append({
                "keyword": c["keyword"],
                "confidence": round(c["confidence"], 3),
                "first_seen_turn": current_user_turn_index,
                "last_reinforced_turn": current_user_turn_index,
            })

    # 步骤 3: 现有主题如果"超过 N 轮没被强化" → 衰减
    for i, e in enumerate(existing):
        if i in matched_existing_idx:
            continue
        last = e.get("last_reinforced_turn", e.get("first_seen_turn", 0))
        # 用 user turn count 估算"未被强化的轮数"
        # 我们的 current_user_turn_index 是绝对 turn_index（u, m, u, m...）
        # user turns 间隔 2，所以 4 个 user turns = 8 个 turn_index
        gap_turns = (current_user_turn_index - last) / 2  # 大致换成 user 轮数
        if gap_turns >= 4:
            e["confidence"] = round(e.get("confidence", 0.0) * DECAY_PER_INACTIVE, 3)

    # 步骤 4: 剔除 confidence 过低的
    survived = [e for e in existing if e.get("confidence", 0.0) >= DROP_BELOW]

    # 步骤 5: 排序取 Top-K
    survived.sort(key=lambda x: x.get("confidence", 0.0), reverse=True)
    return survived[:TOP_K]


# ─────────────────────────────────────────────────────────
# 顶层任务：在 /session/turn 后台触发
# ─────────────────────────────────────────────────────────

def reevaluate_session_themes(session_id: int) -> dict:
    """
    供 BackgroundTasks 调用。读 session 历史，更新 sessions.current_themes。
    返回统计 dict（供日志）。
    """
    with _conn() as conn:
        with conn.cursor() as cur:
            # 读最近 LOOKBACK_TURNS 条 turns
            cur.execute(
                """
                SELECT id, turn_index, role, content
                FROM turns
                WHERE session_id = %s
                ORDER BY turn_index DESC
                LIMIT %s
                """,
                (session_id, LOOKBACK_TURNS),
            )
            recent = list(reversed([
                {"turn_id": r[0], "turn_index": r[1], "role": r[2], "content": r[3]}
                for r in cur.fetchall()
            ]))
            if not recent:
                return {"session_id": session_id, "skipped": True, "reason": "no turns"}

            current_turn_index = max(t["turn_index"] for t in recent)

            cur.execute(
                "SELECT current_themes FROM sessions WHERE id = %s",
                (session_id,),
            )
            row = cur.fetchone()
            existing = (row[0] if row else None) or []

    # 调 LLM 抽候选
    candidates = call_themes_extraction(recent, existing)
    merged = merge_themes(existing, candidates, current_turn_index)

    # 写回
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET current_themes = %s::jsonb WHERE id = %s",
                (json.dumps(merged, ensure_ascii=False), session_id),
            )
            conn.commit()

    logger.info(
        "themes[%d] reevaluated: %s",
        session_id,
        ", ".join(f"{t['keyword']}({t['confidence']:.2f})" for t in merged) or "(empty)",
    )
    return {
        "session_id": session_id,
        "candidates_count": len(candidates),
        "themes_after": merged,
    }
