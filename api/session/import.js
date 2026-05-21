// =============================================================================
// POST /api/session/import
// =============================================================================
// 一次性导入用户本地 localStorage 里的历史对话（每个 mentor 的 conv_* 和
// reviews_log）。每条历史会被建成一个 closed_by_user 的 session + N 条 turns。
//
// Request:
//   {
//     sessions: [{
//       mentor_id: 'freud' | 'weber' | 'marx',
//       started_at?: ISO string,
//       last_active_at?: ISO string,
//       closed_at?: ISO string,
//       summary?: object | null,
//       turns: [{ role: 'user' | 'mentor' | 'assistant', content: string }, ...]
//     }, ...]
//   }
//
// Response:
//   { imported: number, sessions: [{ source_idx, session_id, turn_count }] }
//
// 约束：
//   - 最多 50 个 session
//   - 每个 session 最多 200 条 turns
//   - role='assistant' 视为 'mentor' 别名
// =============================================================================

import { requireUser, methodNotAllowed } from '../_lib/supa.js';

const MAX_SESSIONS = 50;
const MAX_TURNS_PER_SESSION = 200;
const VALID_MENTORS = new Set(['freud', 'weber', 'marx']);

export default async function handler(req, res) {
    if (req.method !== 'POST') return methodNotAllowed(res, 'POST');

    const auth = await requireUser(req, res);
    if (!auth) return;

    const { sessions } = req.body || {};
    if (!Array.isArray(sessions) || sessions.length === 0) {
        return res.status(400).json({ error: 'sessions must be a non-empty array' });
    }
    if (sessions.length > MAX_SESSIONS) {
        return res.status(400).json({ error: `Too many sessions (max ${MAX_SESSIONS})` });
    }

    // 预校验
    for (let i = 0; i < sessions.length; i++) {
        const s = sessions[i];
        if (!VALID_MENTORS.has(s?.mentor_id)) {
            return res.status(400).json({ error: `sessions[${i}].mentor_id invalid` });
        }
        if (!Array.isArray(s.turns) || s.turns.length === 0) {
            return res.status(400).json({ error: `sessions[${i}].turns must be non-empty array` });
        }
        if (s.turns.length > MAX_TURNS_PER_SESSION) {
            return res.status(400).json({ error: `sessions[${i}].turns exceeds ${MAX_TURNS_PER_SESSION}` });
        }
        for (let j = 0; j < s.turns.length; j++) {
            const t = s.turns[j];
            const role = t.role === 'assistant' ? 'mentor' : t.role;
            if (role !== 'user' && role !== 'mentor') {
                return res.status(400).json({ error: `sessions[${i}].turns[${j}].role invalid` });
            }
            if (typeof t.content !== 'string' || !t.content.trim()) {
                return res.status(400).json({ error: `sessions[${i}].turns[${j}].content must be non-empty` });
            }
        }
    }

    const supa = auth.client;

    // 取 public.users.id
    const { data: pubId, error: idErr } = await supa.rpc('current_public_user_id');
    if (idErr || !pubId) {
        console.error('[session/import] cannot resolve public user id', idErr);
        return res.status(500).json({ error: 'Cannot resolve user id' });
    }

    const results = [];
    for (let i = 0; i < sessions.length; i++) {
        const s = sessions[i];
        const startedAt = s.started_at || new Date().toISOString();
        const lastActiveAt = s.last_active_at || startedAt;
        const closedAt = s.closed_at || lastActiveAt;

        // 1) 创建 session（一开始 status='active'，等 turns 写完再改 closed_by_user）
        const { data: sessionRow, error: sessErr } = await supa
            .from('sessions')
            .insert({
                user_id:        pubId,
                mentor_id:      s.mentor_id,
                started_at:     startedAt,
                last_active_at: lastActiveAt,
                status:         'active',
                turn_count:     0,
            })
            .select('id')
            .single();
        if (sessErr) {
            console.error('[session/import] session insert failed', sessErr);
            return res.status(500).json({ error: 'Session insert failed', detail: sessErr.message, partial: results });
        }
        const sessionId = sessionRow.id;

        // 2) 批量插 turns
        const turnRows = s.turns.map((t, idx) => ({
            session_id:  sessionId,
            turn_index:  idx + 1,
            role:        t.role === 'assistant' ? 'mentor' : t.role,
            content:     t.content,
        }));
        const { error: turnErr } = await supa.from('turns').insert(turnRows);
        if (turnErr) {
            console.error('[session/import] turns insert failed', turnErr);
            return res.status(500).json({ error: 'Turns insert failed', detail: turnErr.message, partial: results });
        }

        // 3) 把 session 收尾为 closed_by_user，写入 turn_count + summary（如果有）
        const updatePayload = {
            status:        'closed_by_user',
            closed_at:     closedAt,
            turn_count:    turnRows.length,
            last_active_at: lastActiveAt,
        };
        if (s.summary && typeof s.summary === 'object') {
            updatePayload.summary = s.summary;
            updatePayload.summary_generated_at = closedAt;
        }
        const { error: updErr } = await supa
            .from('sessions')
            .update(updatePayload)
            .eq('id', sessionId);
        if (updErr) {
            console.error('[session/import] session finalize failed', updErr);
            // 不要 return —— turns 已经写进去了，记一下让前端知道是哪条没收尾
        }

        results.push({
            source_idx: i,
            session_id: sessionId,
            turn_count: turnRows.length,
            finalized:  !updErr,
        });
    }

    return res.status(200).json({
        imported: results.length,
        sessions: results,
    });
}
