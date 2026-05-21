// =============================================================================
// GET /api/session/turns?session_id=123
// =============================================================================
// 拉某次会话的全部 turns，按 turn_index 升序。
// RLS 自动校验所有权，不属于当前用户的 session 会返回 0 行。
//
// Response: { session: {...}, turns: [{turn_index, role, content, created_at}, ...] }
// =============================================================================

import { requireUser, methodNotAllowed } from '../_lib/supa.js';

export default async function handler(req, res) {
    if (req.method !== 'GET') return methodNotAllowed(res, 'GET');

    const auth = await requireUser(req, res);
    if (!auth) return;

    const sessionId = parseInt(req.query.session_id, 10);
    if (!Number.isInteger(sessionId)) {
        return res.status(400).json({ error: 'session_id required' });
    }

    const supa = auth.client;

    // 1) 先取 session（顺便用作所有权 + 状态确认）
    const { data: session, error: sErr } = await supa
        .from('sessions')
        .select('id, mentor_id, started_at, last_active_at, status, turn_count, summary')
        .eq('id', sessionId)
        .maybeSingle();

    if (sErr) {
        console.error('[session/turns] session select failed', sErr);
        return res.status(500).json({ error: 'DB select failed', detail: sErr.message });
    }
    if (!session) {
        return res.status(404).json({ error: 'Session not found' });
    }

    // 2) 拉所有 turns
    const { data: turns, error: tErr } = await supa
        .from('turns')
        .select('turn_index, role, content, created_at, mentor_meta')
        .eq('session_id', sessionId)
        .order('turn_index', { ascending: true });

    if (tErr) {
        console.error('[session/turns] turns select failed', tErr);
        return res.status(500).json({ error: 'DB select failed', detail: tErr.message });
    }

    res.setHeader('Cache-Control', 'no-store');
    return res.status(200).json({
        session: {
            id:             session.id,
            mentor_id:      session.mentor_id,
            started_at:     session.started_at,
            last_active_at: session.last_active_at,
            status:         session.status,
            turn_count:     session.turn_count,
            summary:        session.summary,
        },
        turns: turns || [],
    });
}
