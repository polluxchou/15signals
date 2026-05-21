"""
KB 检索 + 用户输入嵌入。

为什么独立成模块：
- 主对话和复盘可能都用 RAG，但触发条件不同，分开便于参数微调
- 嵌入模型 / 维度 / TopK 等参数集中在这里调
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# 嵌入
# ─────────────────────────────────────────────────────────

def embed_query(text: str) -> list[float]:
    """用 Voyage 给一段用户输入生成嵌入。"""
    import voyageai  # 惰性导入

    client = voyageai.Client()  # 读 VOYAGE_API_KEY
    model = os.getenv("VOYAGE_MODEL", "voyage-3")
    result = client.embed(
        [text],
        model=model,
        input_type="query",
    )
    return result.embeddings[0]


# ─────────────────────────────────────────────────────────
# DB connection (与 db.py 一致风格，但独立的连接管理以免循环依赖)
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


# ─────────────────────────────────────────────────────────
# KB 检索
# ─────────────────────────────────────────────────────────

def retrieve_mentor_kb(
    mentor_id: str,
    query_embedding: list[float],
    top_k_concepts: int = 5,
    top_k_voice: int = 3,
    include_all_forbidden: bool = True,
) -> dict[str, list[dict]]:
    """
    检索某位导师的 KB chunks，分类型返回。

    Returns:
        {
          "concepts":         [{title, content, related_signals, sim}, ...],
          "voice_examples":   [...],
          "forbidden_moves":  [...]  (无 sim，按 title 排序)
        }
    """
    with _conn() as conn:
        with conn.cursor() as cur:
            def fetch_topk(chunk_type: str, k: int) -> list[dict]:
                cur.execute(
                    """
                    SELECT title, content, related_signals,
                           1 - (embedding <=> %s::vector) AS sim
                    FROM mentor_kb_chunks
                    WHERE mentor_id = %s
                      AND chunk_type = %s
                      AND deleted_at IS NULL
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (query_embedding, mentor_id, chunk_type, query_embedding, k),
                )
                return [
                    {"title": r[0], "content": r[1], "related_signals": r[2], "sim": float(r[3])}
                    for r in cur.fetchall()
                ]

            def fetch_all(chunk_type: str) -> list[dict]:
                cur.execute(
                    """
                    SELECT title, content, related_signals
                    FROM mentor_kb_chunks
                    WHERE mentor_id = %s
                      AND chunk_type = %s
                      AND deleted_at IS NULL
                    ORDER BY title
                    """,
                    (mentor_id, chunk_type),
                )
                return [
                    {"title": r[0], "content": r[1], "related_signals": r[2], "sim": None}
                    for r in cur.fetchall()
                ]

            return {
                "concepts": fetch_topk("concept", top_k_concepts),
                "voice_examples": fetch_topk("voice_example", top_k_voice),
                "forbidden_moves": fetch_all("forbidden_move") if include_all_forbidden
                                   else fetch_topk("forbidden_move", 2),
            }


def retrieve_opening_template(
    mentor_id: str,
    query_embedding: list[float] | None = None,
    has_memory: bool = False,
) -> dict | None:
    """
    检索一条开场白模板。

    - has_memory=False: 用户初次对话（前 3 次），找无记忆模板
    - has_memory=True:  已有会话历史，找有记忆模板
    - 若提供 query_embedding，按语义相似度排序；否则随机一条

    Returns: 单个 chunk dict 或 None
    """
    with _conn() as conn:
        with conn.cursor() as cur:
            base_where = """
                FROM mentor_kb_chunks
                WHERE mentor_id = %s
                  AND chunk_type = 'opening_template'
                  AND deleted_at IS NULL
                  AND (template_meta->>'has_memory')::bool = %s
            """
            if query_embedding is not None:
                cur.execute(
                    f"""
                    SELECT title, content, related_signals, template_meta,
                           1 - (embedding <=> %s::vector) AS sim
                    {base_where}
                    ORDER BY embedding <=> %s::vector
                    LIMIT 1
                    """,
                    (query_embedding, mentor_id, has_memory, query_embedding),
                )
            else:
                cur.execute(
                    f"""
                    SELECT title, content, related_signals, template_meta, NULL AS sim
                    {base_where}
                    ORDER BY random()
                    LIMIT 1
                    """,
                    (mentor_id, has_memory),
                )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "title": row[0],
                "content": row[1],
                "related_signals": row[2],
                "template_meta": row[3],
                "sim": float(row[4]) if row[4] is not None else None,
            }
