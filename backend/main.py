"""
15 Signals · Backend (FastAPI)

启动：
    cd backend
    pip install -r requirements.txt
    uvicorn backend.main:app --host 127.0.0.1 --port 3459 --reload

或者从项目根目录：
    python -m uvicorn backend.main:app --port 3459 --reload

端点：
    GET  /health         — 健康检查
    GET  /signals/meta   — 15 信号元数据（前端可缓存）
    POST /session/close  — 关闭对话 + 生成复盘
"""

from __future__ import annotations

import logging
import os
from typing import Literal

import anyio
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from .aggregation import aggregate_dimensions, overall_intensity, top_signals
from .db import (
    db_enabled,
    get_or_create_active_session,
    get_session_meta,
    get_session_turns,
    get_user_id_by_email,
    insert_turn,
    mark_session_closed,
    persist_summary,
)
from .deepseek_client import DeepSeekError, call_mentor_response, call_summary
from .prompts import (
    build_mentor_response_messages,
    build_mentor_response_system_prompt,
    build_summary_system_prompt,
    build_summary_user_message,
)
from .retrieval import embed_query, retrieve_mentor_kb
from .signals_meta import SIGNAL_META, SIGNAL_NAMES

# 项目根目录的 .env 也读一下（与 proxy.py 行为一致）
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("15signals.backend")


# ─────────────────────────────────────────────────────────
# Pydantic schemas
# ─────────────────────────────────────────────────────────

MentorId = Literal["freud", "weber", "marx"]


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class SessionCloseRequest(BaseModel):
    mentor_id: MentorId
    messages: list[Message] = Field(..., min_length=2)
    user_id: int | None = None
    session_id: int | None = None

    @field_validator("messages")
    @classmethod
    def must_have_user_turn(cls, v: list[Message]) -> list[Message]:
        if not any(m.role == "user" for m in v):
            raise ValueError("messages must contain at least one user turn")
        return v


class MomentQuote(BaseModel):
    speaker: Literal["user", "mentor"]
    text: str


class Moment(BaseModel):
    signal_name: str
    quotes: list[MomentQuote]
    echo: str
    display_name_zh: str | None = None
    dimension: str | None = None


class TopSignal(BaseModel):
    signal_name: str
    intensity: float
    dimension: str | None = None
    display_name_zh: str | None = None
    display_name_en: str | None = None


class SessionCloseResponse(BaseModel):
    title: str
    overall_intensity: int
    dimension_scores: dict[str, float]
    signal_scores: dict[str, float]
    top_signals: list[TopSignal]
    emotional_summary: str
    moments: list[Moment]
    mentor_id: MentorId
    persisted: bool
    session_id: int | None = None
    persistence_note: str | None = None


# ─────────────────────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────────────────────

app = FastAPI(title="15 Signals · Backend", version="0.1.0")

# 浏览器从 file:// 或 localhost 打开 15signals_web.html 都允许（与 proxy.py 同策略）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "db_enabled": db_enabled(),
        "rubric_version": "rubric-v0.2",
        "signal_count": len(SIGNAL_NAMES),
    }


@app.get("/signals/meta")
def signals_meta() -> dict:
    """前端拉一次缓存：15 信号 + 显示名 + 维度归属。"""
    return {
        "rubric_version": "rubric-v0.2",
        "signals": list(SIGNAL_META.values()),
    }


@app.post("/session/close", response_model=SessionCloseResponse)
async def session_close(req: SessionCloseRequest) -> SessionCloseResponse:
    """
    关闭对话 + 生成复盘。

    流程：
    1. 调 DeepSeek 生成 {title, signal_scores[15], emotional_summary, moments}
    2. 校验 LLM 输出（必须包含 15 信号、moments 引用必须来自原文）
    3. 在 server 端聚合 6 维度分数、整体强度、Top 1-3 信号
    4. 若提供了 user_id/session_id 且 DB 配置就绪，best-effort 写入 sessions.summary
    5. 返回完整结构给前端
    """
    sys_prompt = build_summary_system_prompt(req.mentor_id)
    user_msg = build_summary_user_message([m.model_dump() for m in req.messages])

    try:
        llm_out = await anyio.to_thread.run_sync(call_summary, sys_prompt, user_msg)
    except DeepSeekError as e:
        raise HTTPException(status_code=502, detail=f"DeepSeek error: {e}") from e

    # ─── 校验 + 归一化 LLM 输出 ───
    try:
        title = str(llm_out["title"]).strip()
        raw_scores = llm_out["signal_scores"]
        emotional_summary = str(llm_out["emotional_summary"]).strip()
        raw_moments = llm_out.get("moments") or []
    except (KeyError, TypeError) as e:
        logger.error("LLM output malformed: %s | raw=%r", e, llm_out)
        raise HTTPException(status_code=502, detail=f"LLM output malformed: missing {e}") from e

    # 15 字段都得有，缺的补 0.0；多余的丢掉；越界 clip
    signal_scores: dict[str, float] = {}
    for name in SIGNAL_NAMES:
        v = raw_scores.get(name, 0.0)
        try:
            f = float(v)
        except (TypeError, ValueError):
            f = 0.0
        signal_scores[name] = max(0.0, min(1.0, f))

    # moments 校验：signal_name 必须合法；quotes 文本必须出现在原对话里（防 LLM 编造）
    original_texts = [m.content for m in req.messages]
    moments: list[Moment] = []
    for m in raw_moments[:3]:  # 最多 3 条
        try:
            sig = m["signal_name"]
            if sig not in SIGNAL_META:
                continue
            quotes_raw = m.get("quotes") or []
            quotes: list[MomentQuote] = []
            for q in quotes_raw:
                qt = (q.get("text") or "").strip()
                if not qt:
                    continue
                # 校验：quote 必须是原文的子串（容错：去空白后比对）
                qt_norm = qt.replace(" ", "").replace("\n", "")
                in_original = any(
                    qt_norm in (orig.replace(" ", "").replace("\n", ""))
                    for orig in original_texts
                )
                if not in_original:
                    logger.info("moment quote not in original, skipped: %r", qt[:50])
                    continue
                speaker = q.get("speaker", "user")
                if speaker not in ("user", "mentor"):
                    speaker = "user"
                quotes.append(MomentQuote(speaker=speaker, text=qt))
            if not quotes:
                continue
            meta = SIGNAL_META[sig]
            moments.append(Moment(
                signal_name=sig,
                quotes=quotes,
                echo=str(m.get("echo", "")).strip(),
                display_name_zh=meta["display_name_zh"],
                dimension=meta["dimension"],
            ))
        except Exception as e:
            logger.warning("dropping invalid moment %r: %s", m, e)
            continue

    # ─── server 端聚合 ───
    dimension_scores = aggregate_dimensions(signal_scores)
    overall = overall_intensity(signal_scores)
    tops_raw = top_signals(signal_scores)
    tops = [TopSignal(**t) for t in tops_raw]

    # 构造可序列化 payload（用于 DB 写入与响应）
    summary_payload = {
        "title": title,
        "overall_intensity": overall,
        "dimension_scores": dimension_scores,
        "signal_scores": signal_scores,
        "top_signals": [t.model_dump() for t in tops],
        "emotional_summary": emotional_summary,
        "moments": [m.model_dump() for m in moments],
        "mentor_id": req.mentor_id,
        "rubric_version": "rubric-v0.2",
    }

    # ─── 可选 DB 持久化 ───
    persisted = False
    session_id_out: int | None = req.session_id
    persistence_note: str | None = None
    if not db_enabled():
        persistence_note = "DATABASE_URL not configured; returning summary without persisting"
    elif not (req.user_id or req.session_id):
        persistence_note = "no user_id or session_id provided; returning summary without persisting"
    else:
        result = await anyio.to_thread.run_sync(
            persist_summary,
            req.user_id, req.session_id, req.mentor_id,
            summary_payload, [m.model_dump() for m in req.messages],
        )
        persisted = bool(result.get("persisted"))
        session_id_out = result.get("session_id") or req.session_id
        if not persisted:
            persistence_note = result.get("reason")

    return SessionCloseResponse(
        title=title,
        overall_intensity=overall,
        dimension_scores=dimension_scores,
        signal_scores=signal_scores,
        top_signals=tops,
        emotional_summary=emotional_summary,
        moments=moments,
        mentor_id=req.mentor_id,
        persisted=persisted,
        session_id=session_id_out,
        persistence_note=persistence_note,
    )


# ═════════════════════════════════════════════════════════════════════════════
# P1 · 状态化对话端点
# ═════════════════════════════════════════════════════════════════════════════

class SessionStartRequest(BaseModel):
    user_email: str            # 例：'kexuejia@gmail.com'
    mentor_id: MentorId


class SessionHistoryItem(BaseModel):
    turn_index: int
    role: Literal["user", "mentor"]
    content: str


class SessionStartResponse(BaseModel):
    session_id: int
    is_new: bool
    turn_count: int
    user_id: int
    mentor_id: MentorId
    last_closed_summary_title: str | None = None
    history: list[SessionHistoryItem]


@app.post("/session/start", response_model=SessionStartResponse)
async def session_start(req: SessionStartRequest) -> SessionStartResponse:
    """
    开启一次对话。规则（spec §9.2）：
    - 同一 (user, mentor) 24h 内未关闭的 active session → 续接（返回历史）
    - 否则新建一个 active session；同时回传上一次 closed session 的标题作为引子
    """
    if not db_enabled():
        raise HTTPException(status_code=503, detail="DATABASE_URL not configured")

    # 解析 user
    user_id = await anyio.to_thread.run_sync(get_user_id_by_email, req.user_email)
    if user_id is None:
        raise HTTPException(status_code=404, detail=f"user not found: {req.user_email}")

    sess = await anyio.to_thread.run_sync(
        get_or_create_active_session, user_id, req.mentor_id,
    )

    history_raw = await anyio.to_thread.run_sync(
        get_session_turns, sess["session_id"],
    )
    history = [
        SessionHistoryItem(turn_index=t["turn_index"], role=t["role"], content=t["content"])
        for t in history_raw
    ]

    last_summary = sess.get("last_closed_summary")
    last_title = last_summary.get("title") if isinstance(last_summary, dict) else None

    return SessionStartResponse(
        session_id=sess["session_id"],
        is_new=sess["is_new"],
        turn_count=sess["turn_count"],
        user_id=user_id,
        mentor_id=req.mentor_id,
        last_closed_summary_title=last_title,
        history=history,
    )


class SessionTurnRequest(BaseModel):
    session_id: int
    user_input: str = Field(..., min_length=1)
    top_k_concepts: int = 5
    top_k_voice: int = 3
    temperature: float = 0.7
    debug: bool = False


class TurnRetrievalDebug(BaseModel):
    concepts: list[str]
    voice_examples: list[str]
    forbidden_moves: list[str]


class SessionTurnResponse(BaseModel):
    session_id: int
    turn_count_after: int
    user_turn_id: int
    mentor_turn_id: int
    mentor_response: str
    retrieval: TurnRetrievalDebug | None = None


@app.post("/session/turn", response_model=SessionTurnResponse)
async def session_turn(req: SessionTurnRequest) -> SessionTurnResponse:
    """
    单轮对话：
    1. 读 session 元数据 + 历史 turns
    2. embed 用户输入 → 检索 mentor KB
    3. 拼 system prompt（注入 KB + 跨会话记忆 if 新会话首轮）
    4. 调 DeepSeek 生成回应
    5. INSERT 用户 turn + 导师 turn
    6. 返回回应（+ 可选检索调试）

    注：步骤 5 在 LLM 成功后才写入，避免无效轮次污染历史。
    """
    if not db_enabled():
        raise HTTPException(status_code=503, detail="DATABASE_URL not configured")

    # 1. 读 session
    sess_meta = await anyio.to_thread.run_sync(get_session_meta, req.session_id)
    if sess_meta is None:
        raise HTTPException(status_code=404, detail=f"session {req.session_id} not found")
    if sess_meta["status"] != "active":
        raise HTTPException(
            status_code=409,
            detail=f"session {req.session_id} is {sess_meta['status']}, not active",
        )

    mentor_id = sess_meta["mentor_id"]
    user_id = sess_meta["user_id"]
    history = await anyio.to_thread.run_sync(get_session_turns, req.session_id)

    # 2. 检索
    try:
        q_emb = await anyio.to_thread.run_sync(embed_query, req.user_input)
    except Exception as e:
        logger.exception("embed_query failed")
        raise HTTPException(status_code=502, detail=f"embed error: {e}") from e

    kb_chunks = await anyio.to_thread.run_sync(
        retrieve_mentor_kb, mentor_id, q_emb, req.top_k_concepts, req.top_k_voice, True,
    )

    # 3. 决定是否注入跨会话记忆：仅当本 session 还没有 turns 时
    last_summary_for_prompt = None
    if sess_meta["turn_count"] == 0:
        # 重新拿一次 last_closed_summary（不通过 get_or_create_active_session，因为它在创建之后才返回）
        # 简化：使用 get_or_create_active_session 的返回路径——但本端点没拿到。
        # 直接查一下：
        from .db import _conn as _db_conn  # noqa: WPS437
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT summary FROM sessions
                    WHERE user_id = %s AND mentor_id = %s
                      AND status IN ('closed_by_user', 'closed_by_rollover')
                      AND summary IS NOT NULL
                    ORDER BY closed_at DESC NULLS LAST, last_active_at DESC
                    LIMIT 1
                    """,
                    (user_id, mentor_id),
                )
                row = cur.fetchone()
                last_summary_for_prompt = row[0] if row else None

    # 4. 拼 prompt + 调 LLM
    sys_prompt = build_mentor_response_system_prompt(
        mentor_id=mentor_id,
        kb_chunks=kb_chunks,
        last_closed_summary=last_summary_for_prompt,
        session_turn_count=sess_meta["turn_count"],
    )
    msgs = build_mentor_response_messages(history, req.user_input)

    try:
        mentor_text = await anyio.to_thread.run_sync(
            call_mentor_response, sys_prompt, msgs, req.temperature, 600,
        )
    except DeepSeekError as e:
        logger.exception("call_mentor_response failed")
        raise HTTPException(status_code=502, detail=f"DeepSeek error: {e}") from e

    # 5. 持久化两条 turn（先 user，再 mentor）
    user_turn_id = await anyio.to_thread.run_sync(
        insert_turn, req.session_id, "user", req.user_input, None,
    )

    mentor_meta = {
        "kb_concepts_used": [c["title"] for c in kb_chunks["concepts"]],
        "kb_voice_used": [c["title"] for c in kb_chunks["voice_examples"]],
        "had_cross_session_memory": last_summary_for_prompt is not None,
        "model": os.environ.get("DEEPSEEK_MODEL_MENTOR", "deepseek-chat"),
    }
    mentor_turn_id = await anyio.to_thread.run_sync(
        insert_turn, req.session_id, "mentor", mentor_text, mentor_meta,
    )

    return SessionTurnResponse(
        session_id=req.session_id,
        turn_count_after=sess_meta["turn_count"] + 2,
        user_turn_id=user_turn_id,
        mentor_turn_id=mentor_turn_id,
        mentor_response=mentor_text,
        retrieval=TurnRetrievalDebug(
            concepts=[c["title"] for c in kb_chunks["concepts"]],
            voice_examples=[c["title"] for c in kb_chunks["voice_examples"]],
            forbidden_moves=[c["title"] for c in kb_chunks["forbidden_moves"]],
        ) if req.debug else None,
    )


class SessionMarkClosedRequest(BaseModel):
    session_id: int


@app.post("/session/mark_closed")
async def session_mark_closed(req: SessionMarkClosedRequest) -> dict:
    """
    单纯把 session 标记为 closed（不生成 summary）。

    通常前端的"今日已尽"流程应该调 /session/close 顺便生成 summary。
    这个端点是兜底：用户已经离开 / 网络断开时，让前端能快速关掉。
    """
    if not db_enabled():
        raise HTTPException(status_code=503, detail="DATABASE_URL not configured")
    await anyio.to_thread.run_sync(mark_session_closed, req.session_id, "closed_by_user")
    return {"ok": True, "session_id": req.session_id}
