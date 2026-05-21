// =============================================================================
// POST /api/session/turn
// =============================================================================
// 给会话追加 1-N 条 turn（通常一次发一对：user + mentor）。
// 服务端原子计算 turn_index，避免前端并发争用。
//
// Request:
//   {
//     session_id: number,
//     turns: [
//       { role: 'user'   | 'mentor', content: string, mentor_meta?: object },
//       ...
//     ]
//   }
// Response: { inserted: number, turn_count: number, last_active_at: string }
// =============================================================================

import { requireUser, methodNotAllowed } from '../_lib/supa.js';

const ALLOWED_ROLES = new Set(['user', 'mentor']);
const MAX_TURNS_PER_REQUEST = 4;

export default async function handler(req, res) {
    if (req.method !== 'POST') return methodNotAllowed(res, 'POST');

    const auth = await requireUser(req, res);
    if (!auth) return;

    const { session_id, turns } = req.body || {};
    if (!Number.isInteger(session_id)) {
        return res.status(400).json({ error: 'session_id required (integer)' });
    }
    if (!Array.isArray(turns) || turns.length === 0) {
        return res.status(400).json({ error: 'turns must be a non-empty array' });
    }
    if (turns.length > MAX_TURNS_PER_REQUEST) {
        return res.status(400).json({ error: `Too many turns (max ${MAX_TURNS_PER_REQUEST})` });
    }
    for (const t of turns) {
        if (!ALLOWED_ROLES.has(t.role)) {
            return res.status(400).json({ error: `Invalid role: ${t.role}` });
        }
        if (typeof t.content !== 'string' || !t.content.trim()) {
            return res.status(400).json({ error: 'turn.content must be non-empty string' });
        }
    }

    const supa = auth.client;

    // 1) 取当前 turn_count（RLS 已保证只能读到自己的会话）
    const { data: session, error: selErr } = await supa
        .from('sessions')
        .select('id, turn_count, status')
        .eq('id', session_id)
        .maybeSingle();

    if (selErr) {
        console.error('[session/turn] session select failed', selErr);
        return res.status(500).json({ error: 'DB select failed', detail: selErr.message });
    }
    if (!session) {
        return res.status(404).json({ error: 'Session not found or not owned by user' });
    }
    if (session.status !== 'active') {
        return res.status(409).json({ error: `Session is ${session.status}` });
    }

    // 2) 构造批量 turn 行（turn_index 连续递增）
    const startIdx = session.turn_count + 1;
    const rows = turns.map((t, i) => ({
        session_id:   session_id,
        turn_index:   startIdx + i,
        role:         t.role,
        content:      t.content,
        mentor_meta:  t.mentor_meta ?? null,
    }));

    const { error: insErr } = await supa.from('turns').insert(rows);
    if (insErr) {
        console.error('[session/turn] insert failed', insErr);
        return res.status(500).json({ error: 'DB insert failed', detail: insErr.message });
    }

    // 3) 更新 session 的 turn_count + last_active_at
    const newCount = session.turn_count + turns.length;
    const nowIso   = new Date().toISOString();
    const { data: updated, error: updErr } = await supa
        .from('sessions')
        .update({ turn_count: newCount, last_active_at: nowIso })
        .eq('id', session_id)
        .select('turn_count, last_active_at')
        .single();

    if (updErr) {
        console.error('[session/turn] session update failed', updErr);
        return res.status(500).json({ error: 'DB update failed', detail: updErr.message });
    }

    return res.status(200).json({
        inserted:       turns.length,
        turn_count:     updated.turn_count,
        last_active_at: updated.last_active_at,
    });
}
