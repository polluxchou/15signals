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
    close_reason: str = "closed_by_user",
) -> dict[str, Any]:
    """
    把复盘结果写入 sessions.summary。

    Args:
        close_reason: 'closed_by_user' | 'closed_by_rollover'
                     仅当 session 当前 status='active' 时才会写入此值；
                     若已经是 closed 状态，则保持原值不变。

    Returns:
        {"persisted": True, "session_id": <id>}  — 成功
        {"persisted": False, "reason": "..."}    — 跳过/失败（不抛异常）
    """
    if close_reason not in ("closed_by_user", "closed_by_rollover"):
        return {"persisted": False, "reason": f"invalid close_reason: {close_reason}"}
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
                                WHEN status = 'active' THEN %s
                                ELSE status
                            END,
                            closed_at = COALESCE(closed_at, now())
                        WHERE id = %s
                        RETURNING id
                        """,
                        (payload_json, close_reason, session_id),
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
                                %s, now(),
                                %s::jsonb, now(), %s)
                        RETURNING id
                        """,
                        (user_id, mentor_id, close_reason, payload_json, turn_count),
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


def get_user_semantic_profile(user_id: int) -> dict | None:
    """读用户的稳定语义画像（由 consolidate cron 维护）。"""
    if not db_enabled():
        return None
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT profile, version, last_consolidated_at FROM user_semantic_profile WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "profile": row[0],
                "version": row[1],
                "last_consolidated_at": row[2],
            }


# ─────────────────────────────────────────────────────────
# P2 (前端接入) · 列表 / 历史 / 导入
# ─────────────────────────────────────────────────────────

def list_user_sessions(user_id: int, limit: int = 500) -> list[dict]:
    """列出该用户所有 session，按 last_active_at 降序。

    返回 summary_pretty（标题字符串）便于前端列表渲染，不返回完整 summary（前端按需拉）。
    """
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id, mentor_id, started_at, last_active_at,
                    status, turn_count,
                    summary IS NOT NULL AS has_summary,
                    summary->>'title' AS summary_title,
                    summary->>'emotional_summary' AS summary_emo
                FROM sessions
                WHERE user_id = %s
                ORDER BY last_active_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
            return [
                {
                    "id": r[0],
                    "mentor_id": r[1],
                    "started_at": r[2].isoformat() if r[2] else None,
                    "last_active_at": r[3].isoformat() if r[3] else None,
                    "status": r[4],
                    "turn_count": r[5],
                    "has_summary": r[6],
                    # summary_pretty: 前端列表的一行字
                    "summary_pretty": r[7] or (r[8][:80] if r[8] else None),
                }
                for r in cur.fetchall()
            ]


def get_session_with_turns(session_id: int, user_id: int | None = None) -> dict | None:
    """读 session 元数据 + 所有 turns。

    user_id 提供时校验所有权（防越权）。
    """
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, mentor_id, started_at, last_active_at,
                       status, turn_count, summary, current_themes
                FROM sessions WHERE id = %s
                """,
                (session_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            session = {
                "id": row[0],
                "user_id": row[1],
                "mentor_id": row[2],
                "started_at": row[3].isoformat() if row[3] else None,
                "last_active_at": row[4].isoformat() if row[4] else None,
                "status": row[5],
                "turn_count": row[6],
                "summary": row[7],
                "current_themes": row[8],
            }
            if user_id is not None and session["user_id"] != user_id:
                return None  # 不属于该用户

            cur.execute(
                """
                SELECT id, turn_index, role, content, created_at
                FROM turns WHERE session_id = %s ORDER BY turn_index ASC
                """,
                (session_id,),
            )
            turns = [
                {
                    "id": r[0],
                    "turn_index": r[1],
                    "role": r[2],
                    "content": r[3],
                    "created_at": r[4].isoformat() if r[4] else None,
                }
                for r in cur.fetchall()
            ]
            return {"session": session, "turns": turns}


def import_user_sessions(user_id: int, sessions: list[dict]) -> dict:
    """批量导入历史 session（来自 localStorage 等本地缓存）。

    每个 session 形如：
      {
        mentor_id, started_at, last_active_at, closed_at,
        summary?,   # dict 或 null
        turns: [{role: 'user'|'mentor', content}, ...]
      }

    幂等策略：
      - 用 (user_id, mentor_id, started_at) 做去重 key
      - 已存在的 (user, mentor, started_at) 跳过

    Returns: {imported, skipped, error}
    """
    stats = {"imported": 0, "skipped": 0, "errors": 0, "session_ids": []}

    with _conn() as conn:
        with conn.cursor() as cur:
            for s in sessions:
                try:
                    mentor_id = s.get("mentor_id")
                    started_at = s.get("started_at")
                    if not mentor_id or not started_at:
                        stats["errors"] += 1
                        continue

                    # 去重：同 user + mentor + started_at 的 session 已存在则跳过
                    cur.execute(
                        """
                        SELECT id FROM sessions
                        WHERE user_id = %s AND mentor_id = %s AND started_at = %s
                        """,
                        (user_id, mentor_id, started_at),
                    )
                    if cur.fetchone():
                        stats["skipped"] += 1
                        continue

                    turns = s.get("turns") or []
                    if len(turns) < 1:
                        stats["skipped"] += 1
                        continue

                    summary = s.get("summary")
                    closed_at = s.get("closed_at") or s.get("last_active_at") or started_at
                    last_active_at = s.get("last_active_at") or closed_at
                    has_summary = bool(summary)
                    status = "closed_by_user" if has_summary or closed_at else "active"

                    # 插入 session
                    cur.execute(
                        """
                        INSERT INTO sessions (
                            user_id, mentor_id, started_at, last_active_at, status,
                            closed_at, summary, summary_generated_at, turn_count
                        ) VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s::jsonb, %s, %s
                        )
                        RETURNING id
                        """,
                        (
                            user_id, mentor_id, started_at, last_active_at, status,
                            closed_at if has_summary else None,
                            json.dumps(summary, ensure_ascii=False) if has_summary else None,
                            closed_at if has_summary else None,
                            len(turns),
                        ),
                    )
                    new_sid = cur.fetchone()[0]

                    # 插入 turns
                    for i, t in enumerate(turns, 1):
                        role = t.get("role")
                        if role == "assistant":
                            role = "mentor"
                        if role not in ("user", "mentor"):
                            continue
                        content = (t.get("content") or "").strip()
                        if not content:
                            continue
                        cur.execute(
                            """
                            INSERT INTO turns (session_id, turn_index, role, content)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (new_sid, i, role, content),
                        )

                    stats["imported"] += 1
                    stats["session_ids"].append(new_sid)
                except Exception as e:
                    logger.warning("import session failed: %s | data=%r", e, s)
                    stats["errors"] += 1
            conn.commit()

    return stats


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
