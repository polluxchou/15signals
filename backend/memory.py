"""
P2 · 记忆层：从结束的对话中抽取 episodic_memories，并在新对话中召回。

设计要点（与 direction_merged_spec.md §9.6 + schema.sql episodic_memories 一致）：
  - 一次会话关闭 → 0-N 条记忆产生（每个 moment.user_quote 一条 + emotional_summary 一条 pattern）
  - 召回排序：current_salience × (1 - cosine_distance)，再按显著度衰减时间窗筛
  - 注入 prompt 的格式必须像"导师的回忆"，不是"数据库查询结果"
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# DB connection (与 retrieval / db 一致风格)
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
# 抽取：从一次 closed session 的 summary 里产出 episodic_memories
# ═════════════════════════════════════════════════════════════════════════════

def extract_memories_from_summary(
    user_id: int,
    session_id: int,
    mentor_id: str,
    summary_payload: dict,
) -> int:
    """
    把 summary 里的 moments + emotional_summary 转成 episodic_memories，写入 DB。

    一个 session 产出：
      - 每个 moment 里每条 user 引用 → 1 条 memory_type='quote'
        - content = "用户在某次对话中说：'<原话>'。<echo 解读>"
        - source_quote = 原话
        - related_signals = [moment.signal_name]
        - base_salience = 0.65（LLM 已经筛过，比普通话有分量）
        - emotional_intensity = 该 signal 在 signal_scores 里的强度
      - emotional_summary 整体 → 1 条 memory_type='pattern'
        - content = emotional_summary（叙述本身）
        - related_signals = top_signals 前 3 个的 name
        - base_salience = 0.55

    Returns: 新增的记忆条数
    """
    # 把要写的"原文"都收集出来，先批量 embed 再批量写
    candidates: list[dict] = []

    moments = summary_payload.get("moments") or []
    signal_scores = summary_payload.get("signal_scores") or {}

    for m in moments:
        signal_name = m.get("signal_name")
        echo = (m.get("echo") or "").strip()
        if not signal_name:
            continue
        intensity = float(signal_scores.get(signal_name, 0.0))
        for q in (m.get("quotes") or []):
            if q.get("speaker") != "user":
                continue
            qt = (q.get("text") or "").strip()
            if not qt:
                continue
            # content：可供 LLM 读取的叙述化记忆
            content = f"用户在一次对话中说：「{qt}」"
            if echo:
                content += f"\n（当时的观察：{echo}）"
            candidates.append({
                "content": content,
                "source_quote": qt,
                "memory_type": "quote",
                "related_signals": [signal_name],
                "base_salience": 0.65,
                "emotional_intensity": intensity,
            })

    # pattern 记忆：整体的 emotional_summary
    emo = (summary_payload.get("emotional_summary") or "").strip()
    if emo:
        top = summary_payload.get("top_signals") or []
        top_names = [t.get("signal_name") for t in top[:3] if t.get("signal_name")]
        max_intensity = max((float(t.get("intensity", 0.0)) for t in top[:3]), default=0.5)
        candidates.append({
            "content": emo,
            "source_quote": None,
            "memory_type": "pattern",
            "related_signals": top_names,
            "base_salience": 0.55,
            "emotional_intensity": max_intensity,
        })

    if not candidates:
        logger.info("no extractable memories from session %d", session_id)
        return 0

    # 批量 embed
    try:
        embeddings = _batch_embed_documents([c["content"] for c in candidates])
    except Exception as e:
        logger.exception("embed during memory extraction failed; skipping memories: %s", e)
        return 0

    # 批量 insert
    with _conn() as conn:
        with conn.cursor() as cur:
            for c, emb in zip(candidates, embeddings):
                cur.execute(
                    """
                    INSERT INTO episodic_memories (
                        user_id, origin_session_id, origin_turn_id,
                        mentor_id, memory_type,
                        content, content_embedding, source_quote,
                        related_signals,
                        base_salience, current_salience, reinforcement_count,
                        last_reinforced_at, emotional_intensity
                    ) VALUES (
                        %s, %s, NULL,
                        %s, %s,
                        %s, %s::vector, %s,
                        %s,
                        %s, %s, 0,
                        now(), %s
                    )
                    """,
                    (
                        user_id, session_id,
                        mentor_id, c["memory_type"],
                        c["content"], emb, c["source_quote"],
                        c["related_signals"],
                        c["base_salience"], c["base_salience"],
                        c["emotional_intensity"],
                    ),
                )
            conn.commit()

    logger.info("extracted %d memories from session %d (user=%d)", len(candidates), session_id, user_id)
    return len(candidates)


def _batch_embed_documents(texts: list[str]) -> list[list[float]]:
    """批量给"待存储的记忆文本"做 embedding（input_type='document'）。"""
    import voyageai
    if not texts:
        return []
    client = voyageai.Client()
    model = os.getenv("VOYAGE_MODEL", "voyage-3")
    # Voyage 单次调用支持 ≤128 条，免费档限速；这里量小一次到位
    result = client.embed(texts, model=model, input_type="document")
    return list(result.embeddings)


# ═════════════════════════════════════════════════════════════════════════════
# 召回：在 /session/turn 中调用，按 salience × similarity 返回 Top-K
# ═════════════════════════════════════════════════════════════════════════════

def retrieve_user_memories(
    user_id: int,
    query_embedding: list[float],
    mentor_id: str | None = None,
    top_k: int = 3,
    min_salience: float = 0.1,
    min_similarity: float = 0.35,
) -> list[dict]:
    """
    召回该用户的 episodic_memories，按综合得分排序。

    排序：sqrt(current_salience) × similarity
    （salience 用平方根，减弱"高显著度压倒一切"的效应——
     避免一条强化过头的记忆与任何输入都能"勾上"）

    阈值：
      - min_salience：低于此值的记忆已退出主检索池
      - min_similarity：与本轮输入相似度过低的记忆直接过滤
                        （0.35 是经验值——再低就是"硬塞"了）

    Args:
        mentor_id: 若提供，限定只看那位导师生成的记忆；None 则全部
                   （v1 建议不限——记忆是"用户的"，不是"导师的"）

    Returns: [
      {memory_id, content, source_quote, memory_type, related_signals,
       current_salience, similarity, days_ago, origin_session_id, rank_score}
    ]
    """
    with _conn() as conn:
        with conn.cursor() as cur:
            # SQL：先按向量距离取候选 (top_k*4)，再按 salience*similarity 取 top_k
            params: list = [query_embedding, user_id, min_salience]
            mentor_clause = ""
            if mentor_id:
                mentor_clause = "AND mentor_id = %s"
                params.append(mentor_id)
            params.extend([query_embedding, top_k * 4])

            cur.execute(
                f"""
                WITH candidates AS (
                    SELECT
                        id, content, source_quote, memory_type, related_signals,
                        current_salience, origin_session_id,
                        emotional_intensity, last_reinforced_at,
                        1 - (content_embedding <=> %s::vector) AS similarity
                    FROM episodic_memories
                    WHERE user_id = %s
                      AND deleted_at IS NULL
                      AND current_salience >= %s
                      {mentor_clause}
                    ORDER BY content_embedding <=> %s::vector
                    LIMIT %s
                )
                SELECT
                    id, content, source_quote, memory_type, related_signals,
                    current_salience, similarity,
                    origin_session_id,
                    emotional_intensity,
                    extract(epoch from (now() - last_reinforced_at)) / 86400.0 AS days_ago,
                    sqrt(current_salience) * similarity AS rank_score
                FROM candidates
                WHERE similarity >= %s
                ORDER BY rank_score DESC
                LIMIT %s
                """,
                params + [min_similarity, top_k],
            )

            rows = cur.fetchall()
            return [
                {
                    "memory_id": r[0],
                    "content": r[1],
                    "source_quote": r[2],
                    "memory_type": r[3],
                    "related_signals": r[4] or [],
                    "current_salience": float(r[5]),
                    "similarity": float(r[6]),
                    "origin_session_id": r[7],
                    "emotional_intensity": float(r[8]) if r[8] is not None else None,
                    "days_ago": float(r[9]),
                    "rank_score": float(r[10]),
                }
                for r in rows
            ]


def reinforce_memories(memory_ids: list[int], boost: float = 0.05) -> None:
    """
    被召回 + 用户语境匹配的记忆 → 强化（salience 增长 + reinforcement_count +1）。

    在 /session/turn 中，对最终被注入 prompt 的 memory 调用。
    boost 默认 0.05，避免一次召回让 salience 蹿到 1.0；累积 10 次才到 +0.5。
    """
    if not memory_ids:
        return
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE episodic_memories
                SET current_salience = LEAST(1.0, current_salience + %s),
                    reinforcement_count = reinforcement_count + 1,
                    last_reinforced_at = now()
                WHERE id = ANY(%s) AND deleted_at IS NULL
                """,
                (boost, memory_ids),
            )
            conn.commit()
