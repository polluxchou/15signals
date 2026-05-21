// =============================================================================
// POST /api/session/start
// =============================================================================
// 拿当前登录用户与指定导师的"活跃会话"；若没有则建一个。
//
// Request:  { mentor_id: 'freud' | 'weber' | 'marx' }
// Response: { session_id, resumed, started_at, last_active_at, turn_count, mentor_id }
// =============================================================================

import { requireUser, methodNotAllowed } from '../_lib/supa.js';

const ALLOWED_MENTORS = new Set(['freud', 'weber', 'marx']);

export default async function handler(req, res) {
    if (req.method !== 'POST') return methodNotAllowed(res, 'POST');

    const auth = await requireUser(req, res);
    if (!auth) return;

    const { mentor_id } = req.body || {};
    if (!mentor_id || !ALLOWED_MENTORS.has(mentor_id)) {
        return res.status(400).json({ error: 'Invalid mentor_id' });
    }

    const supa = auth.client;

    // 1) 查找活跃会话
    const { data: active, error: selErr } = await supa
        .from('sessions')
        .select('id, started_at, last_active_at, turn_count, mentor_id')
        .eq('mentor_id', mentor_id)
        .eq('status', 'active')
        .order('last_active_at', { ascending: false })
        .limit(1)
        .maybeSingle();

    if (selErr) {
        console.error('[session/start] select failed', selErr);
        return res.status(500).json({ error: 'DB select failed', detail: selErr.message });
    }

    if (active) {
        return res.status(200).json({
            session_id:     active.id,
            resumed:        true,
            started_at:     active.started_at,
            last_active_at: active.last_active_at,
            turn_count:     active.turn_count,
            mentor_id:      active.mentor_id,
        });
    }

    // 2) 新建会话；user_id 由 INSERT 自己填 —— 我们用 client 里的 access_token，
    //    所以 user_id 必须等于 current_public_user_id()，RLS check 会强制这一点
    //    通过 RPC 拿一下，避免再绕一圈
    const { data: pubId, error: idErr } = await supa.rpc('current_public_user_id');
    if (idErr || !pubId) {
        console.error('[session/start] cannot resolve public user id', idErr);
        return res.status(500).json({ error: 'Cannot resolve user id' });
    }

    const { data: inserted, error: insErr } = await supa
        .from('sessions')
        .insert({
            user_id:   pubId,
            mentor_id: mentor_id,
            status:    'active',
        })
        .select('id, started_at, last_active_at, turn_count, mentor_id')
        .single();

    if (insErr) {
        console.error('[session/start] insert failed', insErr);
        return res.status(500).json({ error: 'DB insert failed', detail: insErr.message });
    }

    return res.status(200).json({
        session_id:     inserted.id,
        resumed:        false,
        started_at:     inserted.started_at,
        last_active_at: inserted.last_active_at,
        turn_count:     inserted.turn_count,
        mentor_id:      inserted.mentor_id,
    });
}
