"""
test_walkthrough.py — P1-P3 全链路端到端验证。

不破坏现有数据；只在新建的 session 上演示，并把 cron 用安全参数跑一遍。

前置：
    1. backend 在跑：scripts/.venv/bin/python -m uvicorn backend.main:app --port 3459
    2. .env 配齐
    3. 用户 kexuejia@gmail.com 已存在

输出：每个步骤打印「期望/实际」，最后一行给总结。
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import psycopg

BASE = os.environ.get("BACKEND_URL", "http://127.0.0.1:3459")
USER_EMAIL = "kexuejia@gmail.com"


# ── 工具函数 ────────────────────────────────────────────────

def hdr(n: int, title: str) -> None:
    print(f"\n\033[1;36m━━━ STEP {n}: {title} ━━━\033[0m")

def note(s: str) -> None:
    print(f"  \033[2m{s}\033[0m")

def ok(s: str) -> None:
    print(f"  \033[32m✓ {s}\033[0m")

def err(s: str) -> None:
    print(f"  \033[31m✗ {s}\033[0m")

def post(path: str, payload: dict, timeout: float = 180) -> dict:
    r = httpx.post(f"{BASE}{path}", json=payload, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:400]}")
    return r.json()

def query(sql: str, params: tuple = ()) -> list:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


# ── 测试流程 ────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mentor", default="freud", choices=["freud", "weber", "marx"])
    args = parser.parse_args()
    mentor = args.mentor

    # ────────────────────────────────────────────────────────
    hdr(0, "环境检查 + 当前状态")
    h = httpx.get(f"{BASE}/health", timeout=5).json()
    if not h.get("db_enabled"):
        err("backend 没连 DB")
        return 1
    ok(f"backend 健康，rubric={h['rubric_version']}, signal_count={h['signal_count']}")

    state_before = {}
    for tbl in ['sessions', 'turns', 'signal_scores', 'episodic_memories', 'user_semantic_profile']:
        state_before[tbl] = query(f"SELECT COUNT(*) FROM {tbl}")[0][0]
    note(f"当前数据库状态: {state_before}")

    # ────────────────────────────────────────────────────────
    hdr(1, "P1.session_start · 新建/续接 session")
    sess = post("/session/start", {"user_email": USER_EMAIL, "mentor_id": mentor})
    sid = sess["session_id"]
    is_new = sess["is_new"]
    ok(f"session_id={sid} is_new={is_new} turn_count={sess['turn_count']}")
    if sess.get("last_closed_summary_title"):
        ok(f"上次 closed summary 标题: 「{sess['last_closed_summary_title']}」")

    # 关掉先前任何 active session（除了刚拿到的 sid）
    active_others = query("SELECT id FROM sessions WHERE status = 'active' AND id != %s", (sid,))
    if active_others:
        note(f"清理 {len(active_others)} 个旧的 active session（避免干扰）")
        for (other_id,) in active_others:
            post("/session/mark_closed", {"session_id": other_id})

    # ────────────────────────────────────────────────────────
    hdr(2, "P1.session_turn · 跑 3 轮对话（含 RAG 调试）")
    inputs = [
        "最近这周睡得不好，老是凌晨 4 点醒",
        "醒了之后就开始想各种事，越想越烦",
        "今天上班也是这样，脑子像浆糊"
    ]
    for i, line in enumerate(inputs, 1):
        note(f"  > 用户: {line}")
        t = post("/session/turn", {
            "session_id": sid,
            "user_input": line,
            "debug": True,
        })
        mentor_text = t["mentor_response"]
        # 取前 100 字
        preview = mentor_text[:120].replace("\n", " ")
        print(f"     \033[35m{mentor}\033[0m: {preview}...")
        if t.get("memories_recalled"):
            top = t["memories_recalled"][0]
            quote = (top.get("source_quote") or "(pattern)")[:50]
            print(f"     \033[2m  [RAG 召回] sim={top['similarity']:.2f}: 「{quote}」\033[0m")
        ok(f"turn {t['turn_count_after']} 已持久化 (user_turn_id={t['user_turn_id']}, mentor_turn_id={t['mentor_turn_id']})")

    # ────────────────────────────────────────────────────────
    hdr(3, "P1 持久化验证 · 查 DB")
    rows = query("SELECT turn_index, role FROM turns WHERE session_id = %s ORDER BY turn_index", (sid,))
    ok(f"session #{sid} 共 {len(rows)} 条 turn，user/mentor 交替: " + ",".join(r[1][0].upper() for r in rows[:8]))

    # ────────────────────────────────────────────────────────
    hdr(4, "P2.close · 生成 summary + 抽取 episodic_memories")
    history = query("SELECT role, content FROM turns WHERE session_id = %s ORDER BY turn_index", (sid,))
    messages = [{"role": ("assistant" if r[0] == "mentor" else "user"), "content": r[1]} for r in history]
    note(f"  调 /session/close，{len(messages)} 条消息（10-15s）...")
    closed = post("/session/close", {
        "mentor_id": mentor,
        "messages": messages,
        "user_id": 1,
        "session_id": sid,
    })
    ok(f"summary title: 「{closed.get('title')}」")
    ok(f"overall_intensity: {closed.get('overall_intensity')}")
    top = closed.get("top_signals") or []
    if top:
        ok("top signals: " + ", ".join(f"{t.get('display_name_zh')}({t['intensity']:.2f})" for t in top[:3]))
    moments = closed.get("moments") or []
    ok(f"moments: {len(moments)} 条")
    ok(f"persisted: {closed.get('persisted')}, note: {closed.get('persistence_note')}")

    mems_after_close = query("SELECT id, memory_type FROM episodic_memories WHERE origin_session_id = %s", (sid,))
    ok(f"本 session 产出 episodic_memories: {len(mems_after_close)} 条 ({', '.join(set(r[1] for r in mems_after_close))})")

    # ────────────────────────────────────────────────────────
    hdr(5, "P2.signal_scoring · 等 background scoring（~5s）")
    time.sleep(6)
    scores = query("""
        SELECT s.turn_id, s.burnout, s.meaning_loss, s.cognitive_decay, s.anxiety_panic, t.content
        FROM signal_scores s JOIN turns t ON t.id = s.turn_id
        WHERE t.session_id = %s ORDER BY s.turn_id
    """, (sid,))
    if scores:
        ok(f"本 session 的 signal_scores 行数: {len(scores)}")
        print(f"     {'turn':4}  {'倦怠':>5}  {'意义':>5}  {'认知':>5}  {'焦虑':>5}  content")
        for r in scores:
            print(f"     {r[0]:4d}  {r[1]:.2f}   {r[2]:.2f}   {r[3]:.2f}   {r[4]:.2f}   {r[5][:30]}")
    else:
        note("没有评分结果（可能 background 还没完成）")

    # ────────────────────────────────────────────────────────
    hdr(6, "P2.retrieve · 新 session 验证记忆召回")
    sess2 = post("/session/start", {"user_email": USER_EMAIL, "mentor_id": mentor})
    sid2 = sess2["session_id"]
    ok(f"新 session_id={sid2}, is_new={sess2['is_new']}")
    if sess2.get("last_closed_summary_title"):
        ok(f"会注入跨会话 summary: 「{sess2['last_closed_summary_title']}」")

    test_input = "今天又是凌晨醒来，脑子停不下来"
    note(f"  > 用户: {test_input}")
    t2 = post("/session/turn", {
        "session_id": sid2,
        "user_input": test_input,
        "debug": True,
    })
    preview = t2["mentor_response"][:200].replace("\n", " ")
    print(f"     \033[35m{mentor}\033[0m: {preview}...")
    recalled = t2.get("memories_recalled", [])
    ok(f"召回了 {len(recalled)} 条 episodic_memories（按 salience × similarity）:")
    for m in recalled[:5]:
        quote = (m.get("source_quote") or "(pattern)")[:60]
        print(f"        · sal={m['salience']:.2f} sim={m['similarity']:.2f}: 「{quote}」")

    # ────────────────────────────────────────────────────────
    hdr(7, "P3.decay · 跑衰减（grace_days=0 强制全量）")
    pre = query("SELECT id, current_salience FROM episodic_memories WHERE deleted_at IS NULL ORDER BY id")
    note(f"  decay 前 salience 分布: " + ", ".join(f"#{r[0]}={r[1]:.3f}" for r in pre[:5]) + ("..." if len(pre) > 5 else ""))

    from backend.jobs import run_decay
    decay_result = run_decay(grace_days=0, daily_decay=0.95, soft_floor=0.05)
    ok(f"decay 结果: decayed={decay_result['decayed']}, dropped={decay_result['dropped_below_floor']}, remaining={decay_result['remaining_active']}")
    post_q = query("SELECT id, current_salience FROM episodic_memories WHERE deleted_at IS NULL ORDER BY id")
    note(f"  decay 后 salience 分布: " + ", ".join(f"#{r[0]}={r[1]:.3f}" for r in post_q[:5]) + ("..." if len(post_q) > 5 else ""))

    # ────────────────────────────────────────────────────────
    hdr(8, "P3.consolidate · 把高强化记忆巩固到 semantic_profile")
    from backend.jobs import run_consolidate
    cons = run_consolidate()
    ok(f"users_processed={cons['users_processed']}, users_with_updates={cons['users_with_updates']}, memories_consolidated={cons['total_memories_consolidated']}")

    profile_row = query("SELECT version, profile FROM user_semantic_profile WHERE user_id = 1")
    if profile_row:
        v, p = profile_row[0]
        ok(f"user_semantic_profile.version = {v}")
        print(f"     \033[35mprofile JSON:\033[0m")
        print("     " + json.dumps(p, ensure_ascii=False, indent=2).replace("\n", "\n     "))

    # ────────────────────────────────────────────────────────
    hdr(9, "P3.rollover · dry-run 看候选")
    from backend.jobs import run_rollover
    ro = run_rollover(dry_run=True)
    ok(f"rollover 候选: {ro['scanned']} 个 session" + (f" (ids={ro['session_ids']})" if ro['scanned'] else ""))
    note("  （正常情况下：用户本地时区已过 8:00 且 session 跨日 才会被扫到）")

    # ────────────────────────────────────────────────────────
    hdr(10, "Final · 状态对比")
    state_after = {}
    for tbl in ['sessions', 'turns', 'signal_scores', 'episodic_memories', 'user_semantic_profile']:
        state_after[tbl] = query(f"SELECT COUNT(*) FROM {tbl}")[0][0]
    print(f"\n     {'表':30}  {'前':>5}  {'后':>5}  Δ")
    for k in state_before:
        delta = state_after[k] - state_before[k]
        print(f"     {k:30}  {state_before[k]:>5}  {state_after[k]:>5}  {'+' + str(delta) if delta > 0 else delta}")

    print("\n\033[1;32m━━━ 全部步骤完成 ━━━\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
