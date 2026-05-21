// =============================================================================
// GET /api/session/list
// =============================================================================
// 列出当前用户的会话，按 last_active_at 降序。可选过滤：
//
// Query params:
//   ?mentor=freud|weber|marx      可选
//   ?from=2026-05-01              可选，包含；按 last_active_at 比较（ISO date）
//   ?to=2026-05-31                可选，包含；当天 23:59:59
//   ?status=active|closed_by_user|closed_by_rollover   可选
//   ?limit=100                    默认 200，硬上限 500
//
// Response:
//   { sessions: [{
//       id, mentor_id, started_at, last_active_at, status,
//       turn_count, has_summary, summary_pretty?
//     }, ...] }
// =============================================================================

import { requireUser, methodNotAllowed } from '../_lib/supa.js';

const MAX_LIMIT     = 500;
const DEFAULT_LIMIT = 200;
const VALID_MENTORS = new Set(['freud', 'weber', 'marx']);
const VALID_STATUS  = new Set(['active', 'closed_by_user', 'closed_by_rollover']);

export default async function handler(req, res) {
    if (req.method !== 'GET') return methodNotAllowed(res, 'GET');

    const auth = await requireUser(req, res);
    if (!auth) return;

    const { mentor, from, to, status, limit: limitStr } = req.query || {};

    let limit = parseInt(limitStr, 10);
    if (!Number.isFinite(limit) || limit <= 0) limit = DEFAULT_LIMIT;
    if (limit > MAX_LIMIT) limit = MAX_LIMIT;

    let q = auth.client
        .from('sessions')
        .select('id, mentor_id, started_at, last_active_at, status, turn_count, summary')
        .order('last_active_at', { ascending: false })
        .limit(limit);

    if (mentor) {
        if (!VALID_MENTORS.has(mentor)) {
            return res.status(400).json({ error: 'Invalid mentor' });
        }
        q = q.eq('mentor_id', mentor);
    }
    if (status) {
        if (!VALID_STATUS.has(status)) {
            return res.status(400).json({ error: 'Invalid status' });
        }
        q = q.eq('status', status);
    }
    if (from) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(from)) {
            return res.status(400).json({ error: 'from must be YYYY-MM-DD' });
        }
        q = q.gte('last_active_at', `${from}T00:00:00Z`);
    }
    if (to) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(to)) {
            return res.status(400).json({ error: 'to must be YYYY-MM-DD' });
        }
        q = q.lte('last_active_at', `${to}T23:59:59.999Z`);
    }

    const { data, error } = await q;
    if (error) {
        console.error('[session/list] failed', error);
        return res.status(500).json({ error: 'DB select failed', detail: error.message });
    }

    const sessions = (data || []).map(s => ({
        id:             s.id,
        mentor_id:      s.mentor_id,
        started_at:     s.started_at,
        last_active_at: s.last_active_at,
        status:         s.status,
        turn_count:     s.turn_count,
        has_summary:    !!s.summary,
        // 仅给一个"展示摘要"字段，全量 summary 太重，到 detail 再拉
        summary_pretty: s.summary?.overall_text ?? null,
    }));

    res.setHeader('Cache-Control', 'no-store');
    return res.status(200).json({ sessions });
}
