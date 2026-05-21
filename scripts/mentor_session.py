"""
mentor_session.py — 状态化 CLI 客户端，对接 backend 的 /session/start + /session/turn。

Usage:
    # 默认续接你最近的 active session（24h 内）；否则新建
    python scripts/mentor_session.py --user kexuejia@gmail.com --mentor freud

    # 用 debug 模式查看每轮 RAG 召回了哪些 chunks
    python scripts/mentor_session.py --user kexuejia@gmail.com --mentor freud --debug

    # 自定义 backend 地址
    BACKEND_URL=http://127.0.0.1:3459 python scripts/mentor_session.py ...

会话内命令：
    /end            主动结束本会话（不生成 summary，仅置 closed_by_user）
    /close          结束 + 生成复盘（调 /session/close）
    /history        显示当前 session 的全部历史
    /debug on|off   切换检索 debug 模式
    /quit           直接退出，不动 session 状态

前置：
    1. backend 在跑：cd ~/Code/15Signals && python -m uvicorn backend.main:app --port 3459
    2. .env 配齐：DATABASE_URL, VOYAGE_API_KEY, DEEPSEEK_API_KEY
    3. 数据库里有这位用户：migrations/003_seed_user_kexuejia.sql 已执行
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

MENTOR_NAMES = {
    "freud": "西格蒙德·弗洛伊德",
    "weber": "马克斯·韦伯",
    "marx":  "卡尔·马克思",
}

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:3459")
HTTP_TIMEOUT = 60.0


# ─────────────────────────────────────────────────────────
# Console helpers
# ─────────────────────────────────────────────────────────

def c_dim(s: str) -> str:    return f"\033[2m{s}\033[0m"
def c_bold(s: str) -> str:   return f"\033[1m{s}\033[0m"
def c_user(s: str) -> str:   return f"\033[36m{s}\033[0m"   # cyan
def c_mentor(s: str) -> str: return f"\033[35m{s}\033[0m"   # magenta
def c_sys(s: str) -> str:    return f"\033[33m{s}\033[0m"   # yellow
def c_err(s: str) -> str:    return f"\033[31m{s}\033[0m"   # red


def print_divider(title: str = "") -> None:
    line = "─" * 60
    if title:
        print(c_dim(f"{line}  {title}"))
    else:
        print(c_dim(line))


# ─────────────────────────────────────────────────────────
# HTTP calls
# ─────────────────────────────────────────────────────────

def http_post(path: str, payload: dict, timeout: float = HTTP_TIMEOUT) -> dict:
    url = f"{BACKEND_URL.rstrip('/')}{path}"
    try:
        r = httpx.post(url, json=payload, timeout=timeout)
    except httpx.RequestError as e:
        raise RuntimeError(f"backend 不可达 ({url}): {e}") from e
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise RuntimeError(f"{r.status_code} {detail}")
    return r.json()


def http_get(path: str) -> dict:
    url = f"{BACKEND_URL.rstrip('/')}{path}"
    r = httpx.get(url, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


# ─────────────────────────────────────────────────────────
# Session ops
# ─────────────────────────────────────────────────────────

def start_session(user_email: str, mentor_id: str) -> dict:
    return http_post("/session/start", {
        "user_email": user_email,
        "mentor_id": mentor_id,
    })


def send_turn(session_id: int, user_input: str, debug: bool, temperature: float) -> dict:
    return http_post("/session/turn", {
        "session_id": session_id,
        "user_input": user_input,
        "debug": debug,
        "temperature": temperature,
    }, timeout=120.0)


def mark_closed(session_id: int) -> dict:
    return http_post("/session/mark_closed", {"session_id": session_id})


def close_with_summary(session_id: int, mentor_id: str, history_msgs: list[dict],
                       user_id: int) -> dict:
    """/session/close 期望 OpenAI 风格 messages（user / assistant）。"""
    converted = []
    for m in history_msgs:
        role = "assistant" if m["role"] == "mentor" else m["role"]
        converted.append({"role": role, "content": m["content"]})
    return http_post("/session/close", {
        "mentor_id": mentor_id,
        "messages": converted,
        "user_id": user_id,
        "session_id": session_id,
    }, timeout=180.0)


# ─────────────────────────────────────────────────────────
# Render
# ─────────────────────────────────────────────────────────

def render_history(history: list[dict]) -> None:
    if not history:
        print(c_dim("  (空)"))
        return
    for t in history:
        role = t["role"]
        prefix = c_user("你") if role == "user" else c_mentor(MENTOR_NAMES.get("freud", "导师")[:3])
        print(f"  {prefix} [{t['turn_index']}]：{t['content']}")


def render_close_summary(data: dict) -> None:
    print()
    print_divider("复盘")
    print(f"  {c_bold('标题：')}{data.get('title', '')}")
    print(f"  {c_bold('整体强度：')}{data.get('overall_intensity', 0)}")

    tops = data.get("top_signals") or []
    if tops:
        print(f"  {c_bold('Top 信号：')}")
        for t in tops:
            zh = t.get("display_name_zh") or t.get("signal_name", "")
            print(f"    · {zh}  ({t.get('intensity', 0):.2f})  [{t.get('dimension', '')}]")

    emo = data.get("emotional_summary") or ""
    if emo:
        print(f"  {c_bold('情感回声：')}")
        for line in emo.split("\n"):
            print(f"    {line}")

    moments = data.get("moments") or []
    if moments:
        print(f"  {c_bold('Moments：')}")
        for m in moments:
            print(f"    · [{m.get('display_name_zh', m.get('signal_name'))}]")
            for q in (m.get("quotes") or []):
                sp = q.get("speaker", "?")
                print(f"        〈{sp}〉 {q.get('text', '')}")
            echo = m.get("echo", "")
            if echo:
                print(c_dim(f"        → {echo}"))

    persisted = data.get("persisted")
    note = data.get("persistence_note")
    if persisted:
        print(c_dim(f"  (已写入 session.summary)"))
    elif note:
        print(c_dim(f"  (未持久化: {note})"))


# ─────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────

def repl(args: argparse.Namespace) -> int:
    mentor_id = args.mentor
    mentor_name = MENTOR_NAMES[mentor_id]

    print()
    print(c_bold(f"  15 Signals · {mentor_name}"))
    print(c_dim(f"  user={args.user}  backend={BACKEND_URL}"))
    print_divider()

    # backend 健康检查
    try:
        h = http_get("/health")
        if not h.get("db_enabled"):
            print(c_err("× backend 启动了但 DATABASE_URL 没配 — 无法持久化"))
            return 1
    except Exception as e:
        print(c_err(f"× backend 不可达: {e}"))
        print(c_dim(f"  启动 backend: cd ~/Code/15Signals && python -m uvicorn backend.main:app --port 3459 --reload"))
        return 1

    # 开始 session
    try:
        sess = start_session(args.user, mentor_id)
    except Exception as e:
        print(c_err(f"× /session/start 失败: {e}"))
        return 1

    session_id = sess["session_id"]
    user_id = sess["user_id"]
    is_new = sess["is_new"]
    turn_count = sess["turn_count"]
    last_title = sess.get("last_closed_summary_title")

    if is_new:
        print(c_sys(f"  ⊕ 新建 session #{session_id}"))
        if last_title:
            print(c_dim(f"  上次对话主题：「{last_title}」 — 导师会在第一轮自然提及"))
    else:
        print(c_sys(f"  ↻ 续接 session #{session_id}（已有 {turn_count} 轮）"))

    history = sess.get("history") or []
    if history:
        print_divider("已有历史")
        for t in history:
            role = t["role"]
            prefix = c_user("你") if role == "user" else c_mentor(mentor_name[:3])
            print(f"  {prefix} [{t['turn_index']}]：{t['content']}")

    print_divider()
    print(c_dim("  输入消息回车发送；命令：/end /close /history /debug /quit"))
    print()

    debug = args.debug
    in_memory_history: list[dict] = list(history)  # 给 /close 用

    while True:
        try:
            line = input(c_user("你> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            print(c_dim("  (Ctrl+C → /quit；session 仍保持 active)"))
            return 0

        if not line:
            continue

        # ── 命令处理 ──
        if line in ("/quit", "/q"):
            print(c_dim("  退出（session 仍 active，下次进入可续接）"))
            return 0

        if line in ("/end",):
            try:
                mark_closed(session_id)
                print(c_sys(f"  ✓ session #{session_id} 已置 closed_by_user（未生成 summary）"))
            except Exception as e:
                print(c_err(f"  × mark_closed 失败: {e}"))
            return 0

        if line in ("/close",):
            if not in_memory_history:
                print(c_err("  × 还没说过话，无法生成复盘"))
                continue
            print(c_dim("  生成复盘中（5-15 秒）..."))
            try:
                data = close_with_summary(session_id, mentor_id, in_memory_history, user_id)
                render_close_summary(data)
            except Exception as e:
                print(c_err(f"  × /session/close 失败: {e}"))
            return 0

        if line == "/history":
            print_divider("历史")
            for t in in_memory_history:
                role = t["role"]
                prefix = c_user("你") if role == "user" else c_mentor(mentor_name[:3])
                print(f"  {prefix} [{t['turn_index']}]：{t['content']}")
            print_divider()
            continue

        if line.startswith("/debug"):
            parts = line.split()
            if len(parts) == 2 and parts[1] in ("on", "off"):
                debug = parts[1] == "on"
            else:
                debug = not debug
            print(c_dim(f"  debug = {debug}"))
            continue

        # ── 普通输入 → 触发一轮 ──
        print(c_dim("  ...导师思考中"))
        try:
            resp = send_turn(session_id, line, debug=debug, temperature=args.temperature)
        except Exception as e:
            print(c_err(f"  × /session/turn 失败: {e}"))
            continue

        # 更新内存历史
        in_memory_history.append({"turn_index": resp["turn_count_after"] - 1, "role": "user", "content": line})
        in_memory_history.append({"turn_index": resp["turn_count_after"], "role": "mentor", "content": resp["mentor_response"]})

        # 输出导师回应
        print()
        print(f"{c_mentor(mentor_name)}：")
        for para in resp["mentor_response"].split("\n"):
            print(f"  {para}")
        print()

        # debug 输出
        if debug and resp.get("retrieval"):
            r = resp["retrieval"]
            print(c_dim(f"  [RAG] concepts: {', '.join(r['concepts'])}"))
            print(c_dim(f"  [RAG] voice:    {', '.join(r['voice_examples'])}"))
            print()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--user", required=True, help="user email, e.g. kexuejia@gmail.com")
    p.add_argument("--mentor", required=True, choices=["freud", "weber", "marx"])
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--debug", action="store_true", help="show RAG retrieval per turn")
    args = p.parse_args()
    return repl(args)


if __name__ == "__main__":
    sys.exit(main())
