// =============================================================================
// Vercel Serverless Function · DeepSeek API 代理
// =============================================================================
// 路径：/api/deepseek
// 流程：1) 校验 Authorization 头里的 Supabase access_token 是否对应已登录用户
//       2) 用服务端的 DEEPSEEK_API_KEY 转发 body 到 DeepSeek
//       3) 把上游响应原样返回浏览器
//
// 需要的 Vercel 环境变量（Project Settings → Environment Variables）：
//   - DEEPSEEK_API_KEY      你的 DeepSeek key（sk-...）
//   - SUPABASE_URL          https://msvcnuvduivlzggncmej.supabase.co
//   - SUPABASE_ANON_KEY     anon key（eyJ... 那串）
// =============================================================================

import { createClient } from '@supabase/supabase-js';

const supa = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_ANON_KEY,
  { auth: { persistSession: false, autoRefreshToken: false } }
);

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({ error: 'Method not allowed' });
  }

  // ----- 1. 校验 Supabase JWT -----
  const authHeader = req.headers.authorization || '';
  const token = authHeader.startsWith('Bearer ') ? authHeader.slice(7) : '';
  if (!token) {
    return res.status(401).json({ error: 'Missing auth token' });
  }

  const { data: { user }, error: authError } = await supa.auth.getUser(token);
  if (authError || !user) {
    return res.status(401).json({ error: 'Invalid auth token' });
  }

  // ----- 2. 转发到 DeepSeek -----
  const apiKey = process.env.DEEPSEEK_API_KEY;
  if (!apiKey) {
    return res.status(500).json({ error: 'Server missing DEEPSEEK_API_KEY' });
  }

  try {
    const upstream = await fetch('https://api.deepseek.com/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiKey}`,
      },
      body: JSON.stringify(req.body),
    });
    const text = await upstream.text();
    res.status(upstream.status);
    res.setHeader('Content-Type', 'application/json');
    return res.send(text);
  } catch (err) {
    console.error('[deepseek-proxy] upstream call failed', err);
    return res.status(502).json({ error: 'Upstream call failed', detail: String(err) });
  }
}
