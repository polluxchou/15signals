"""
可选 DB 持久化层。

设计原则：
- 没配 DATABASE_URL 时不报错，直接 noop，复盘功能照常返回给前端
- 写入失败不阻断复盘（best-effort）——日志告警，但接口仍返回 200
- 用 psycopg3 同步 API（FastAPI 里用 anyio.to_thread.run_sync 包一下避免阻塞 loop）
"""

import json
import logging
import os
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)


def db_enabled() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


@contextmanager
def _conn():
    """惰性导入 psycopg，免得没配 DB 时启动也要装它。"""
    import psycopg  # noqa: WPS433
    url = os.environ["DATABASE_URL"]
    conn = psycopg.connect(url, autocommit=False)
    try:
        yield conn
    finally:
        conn.close()


def persist_summary(
    user_id: int | None,
    session_id: int | None,
    mentor_id: str,
    summary_payload: dict[str, Any],
    raw_messages: list[dict],
) -> dict[str, Any]:
    """
    把复盘结果写入 sessions.summary。

    Returns:
        {"persisted": True, "session_id": <id>}  — 成功
        {"persisted": False, "reason": "..."}    — 跳过/失败（不抛异常）

    行为：
    - 若 session_id 已存在 → UPDATE summary, summary_generated_at, status='closed_by_user'
    - 若 session_id 不存在但提供了 user_id → INSERT 一个新 session 并写入
    - 都没有 → 跳过（前端可以不传 user/session 也能拿到复盘）
    """
    if not db_enabled():
        return {"persisted": False, "reason": "DATABASE_URL not configured"}

    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                payload_json = json.dumps(summary_payload, ensure_ascii=False)

                if session_id is not None:
                    cur.execute(
                        """
                        UPDATE sessions
                        SET summary = %s::jsonb,
                            summary_generated_at = now(),
                            status = CASE
                                WHEN status = 'active' THEN 'closed_by_user'
                                ELSE status
                            END,
                            closed_at = COALESCE(closed_at, now())
                        WHERE id = %s
                        RETURNING id
                        """,
                        (payload_json, session_id),
                    )
                    row = cur.fetchone()
                    if row is None:
                        conn.rollback()
                        return {"persisted": False, "reason": f"session_id {session_id} not found"}
                    conn.commit()
                    return {"persisted": True, "session_id": row[0]}

                if user_id is not None:
                    turn_count = len(raw_messages)
                    cur.execute(
                        """
                        INSERT INTO sessions
                            (user_id, mentor_id, started_at, last_active_at,
                             status, closed_at,
                             summary, summary_generated_at, turn_count)
                        VALUES (%s, %s, now(), now(),
                                'closed_by_user', now(),
                                %s::jsonb, now(), %s)
                        RETURNING id
                        """,
                        (user_id, mentor_id, payload_json, turn_count),
                    )
                    row = cur.fetchone()
                    new_id = row[0] if row else None
                    conn.commit()
                    return {"persisted": True, "session_id": new_id}

                return {"persisted": False, "reason": "no user_id or session_id provided"}

    except Exception as e:
        logger.exception("persist_summary failed: %s", e)
        return {"persisted": False, "reason": f"db error: {type(e).__name__}: {e}"}
