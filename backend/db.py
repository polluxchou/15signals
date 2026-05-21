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


# ═════════════════════════════════════════════════════════════════════════════
# P1 · 状态化对话：session / turn / user 解析
# ═════════════════════════════════════════════════════════════════════════════
#
# 规则（与 direction_merged_spec.md §9.2 一致）：
#   - 同一 (user, mentor) 24h 内未关闭的 session → 续接
#   - 否则新建一个 active session，并把上一次 closed 的 summary 一并返回
#     作为"跨会话开场参考"


def get_user_id_by_email(email: str) -> int | None:
    """通过 email 查 public.users.id。"""
    if not db_enabled():
        return None
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email = %s LIMIT 1", (email,))
            row = cur.fetchone()
            return row[0] if row else None


def get_or_create_active_session(
    user_id: int,
    mentor_id: str,
    activity_window_hours: int = 24,
) -> dict:
    """
    找到或新建一个 active session。

    Returns:
        {
          "session_id": int,
          "is_new": bool,
          "turn_count": int,                    # 续接时 > 0
          "last_closed_summary": dict | None,   # 仅新建时填，用于跨会话开场
        }
    """
    with _conn() as conn:
        with conn.cursor() as cur:
            # 1. 找最近一个 active 且在窗口内的 session
            cur.execute(
                """
                SELECT id, turn_count
                FROM sessions
                WHERE user_id = %s
                  AND mentor_id = %s
                  AND status = 'active'
                  AND last_active_at > now() - make_interval(hours => %s)
                ORDER BY last_active_at DESC
                LIMIT 1
                """,
                (user_id, mentor_id, activity_window_hours),
            )
            row = cur.fetchone()
            if row is not None:
                return {
                    "session_id": row[0],
                    "is_new": False,
                    "turn_count": row[1],
                    "last_closed_summary": None,
                }

            # 2. 新建之前，查最近一个 closed session 的 summary（作为跨会话参考）
            cur.execute(
                """
                SELECT summary
                FROM sessions
                WHERE user_id = %s
                  AND mentor_id = %s
                  AND status IN ('closed_by_user', 'closed_by_rollover')
                  AND summary IS NOT NULL
                ORDER BY closed_at DESC NULLS LAST, last_active_at DESC
                LIMIT 1
                """,
                (user_id, mentor_id),
            )
            row = cur.fetchone()
            last_summary = row[0] if row else None

            # 3. 新建 session
            cur.execute(
                """
                INSERT INTO sessions (user_id, mentor_id, started_at, last_active_at, status)
                VALUES (%s, %s, now(), now(), 'active')
                RETURNING id
                """,
                (user_id, mentor_id),
            )
            new_id = cur.fetchone()[0]
            conn.commit()

            return {
                "session_id": new_id,
                "is_new": True,
                "turn_count": 0,
                "last_closed_summary": last_summary,
            }


def insert_turn(
    session_id: int,
    role: str,
    content: str,
    mentor_meta: dict | None = None,
) -> int:
    """写入一条 turn，同步更新 session 的 last_active_at 和 turn_count。

    role: 'user' | 'mentor'
    Returns: turn_id
    """
    if role not in ("user", "mentor"):
        raise ValueError(f"invalid role: {role}")

    with _conn() as conn:
        with conn.cursor() as cur:
            # 1. 取当前 session 的 turn_count，决定新 turn 的 turn_index
            cur.execute(
                "SELECT turn_count FROM sessions WHERE id = %s FOR UPDATE",
                (session_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"session {session_id} not found")
            current_count = row[0]
            new_index = current_count + 1

            # 2. INSERT turn
            cur.execute(
                """
                INSERT INTO turns (session_id, turn_index, role, content, mentor_meta)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                RETURNING id
                """,
                (
                    session_id, new_index, role, content,
                    json.dumps(mentor_meta, ensure_ascii=False) if mentor_meta else None,
                ),
            )
            turn_id = cur.fetchone()[0]

            # 3. UPDATE session.last_active_at + turn_count
            cur.execute(
                """
                UPDATE sessions
                SET last_active_at = now(), turn_count = %s
                WHERE id = %s
                """,
                (new_index, session_id),
            )
            conn.commit()
            return turn_id


def get_session_turns(session_id: int) -> list[dict]:
    """读 session 的所有 turns，按 turn_index 升序。

    Returns: [{turn_id, turn_index, role, content, created_at}, ...]
    """
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, turn_index, role, content, created_at
                FROM turns
                WHERE session_id = %s
                ORDER BY turn_index ASC
                """,
                (session_id,),
            )
            return [
                {
                    "turn_id": r[0],
                    "turn_index": r[1],
                    "role": r[2],
                    "content": r[3],
                    "created_at": r[4],
                }
                for r in cur.fetchall()
            ]


def get_session_meta(session_id: int) -> dict | None:
    """读一个 session 的元数据（状态、主题、计数）。"""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, mentor_id, status,
                       started_at, last_active_at, closed_at,
                       turn_count, current_themes, summary
                FROM sessions
                WHERE id = %s
                """,
                (session_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "user_id": row[1],
                "mentor_id": row[2],
                "status": row[3],
                "started_at": row[4],
                "last_active_at": row[5],
                "closed_at": row[6],
                "turn_count": row[7],
                "current_themes": row[8],
                "summary": row[9],
            }


def mark_session_closed(session_id: int, reason: str = "closed_by_user") -> None:
    """手动关闭 session（用户主动 /end 或 rollover）。

    summary 由 /session/close 端点单独写入（已实现）。
    这里只动 status / closed_at。
    """
    if reason not in ("closed_by_user", "closed_by_rollover"):
        raise ValueError(f"invalid reason: {reason}")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sessions
                SET status = %s, closed_at = COALESCE(closed_at, now())
                WHERE id = %s AND status = 'active'
                """,
                (reason, session_id),
            )
            conn.commit()
