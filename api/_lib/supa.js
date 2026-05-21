// =============================================================================
// 内部工具：Supabase 客户端 + 鉴权辅助
// =============================================================================
// 用法：
//   const auth = await requireUser(req, res);
//   if (!auth) return;        // requireUser 已发 401
//   const supa = auth.client; // RLS 自动按当前用户隔离行
// =============================================================================

import { createClient } from '@supabase/supabase-js';

const SUPA_URL = process.env.SUPABASE_URL;
const ANON_KEY = process.env.SUPABASE_ANON_KEY;

export function anonClient() {
    return createClient(SUPA_URL, ANON_KEY, {
        auth: { persistSession: false, autoRefreshToken: false }
    });
}

export function userClient(token) {
    return createClient(SUPA_URL, ANON_KEY, {
        auth: { persistSession: false, autoRefreshToken: false },
        global: { headers: { Authorization: `Bearer ${token}` } }
    });
}

/**
 * 校验请求里的 Bearer token；通过返回 { user, token, client }，失败发 401 并返回 null
 */
export async function requireUser(req, res) {
    const authHeader = req.headers.authorization || '';
    const token = authHeader.startsWith('Bearer ') ? authHeader.slice(7) : '';
    if (!token) {
        res.status(401).json({ error: 'Missing auth token' });
        return null;
    }
    const anon = anonClient();
    const { data: { user }, error } = await anon.auth.getUser(token);
    if (error || !user) {
        res.status(401).json({ error: 'Invalid auth token' });
        return null;
    }
    return { user, token, client: userClient(token) };
}

export function methodNotAllowed(res, allow) {
    res.setHeader('Allow', allow);
    return res.status(405).json({ error: 'Method not allowed' });
}
