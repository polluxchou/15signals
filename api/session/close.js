// =============================================================================
// Vercel Serverless Function · POST /api/session/close
// =============================================================================
// 关闭一段对话并生成结构化复盘（rubric-v0.2 文明病/媒介批判 15 信号）。
//
// 流程：
//   1. 校验 Authorization 头里的 Supabase access_token（必须登录）
//   2. 调 DeepSeek 生成复盘 JSON
//   3. 校验、归一化、聚合（6 维度 / 整体强度 / Top 1-3 信号 / moments 引用）
//   4. 用 service-role 客户端在 Supabase 里 upsert sessions.summary（best-effort）
//   5. 返回完整复盘给前端
//
// Vercel 环境变量（Project Settings → Environment Variables）：
//   - DEEPSEEK_API_KEY                  DeepSeek key（sk-...）
//   - DEEPSEEK_BASE_URL                 默认 https://api.deepseek.com
//   - DEEPSEEK_MODEL_SCORER             默认 deepseek-chat
//   - SUPABASE_URL                      https://msvcnuvduivlzggncmej.supabase.co
//   - SUPABASE_ANON_KEY                 anon key（用于校验用户 JWT）
//   - SUPABASE_SERVICE_ROLE_KEY         service-role key（绕 RLS 写 sessions 表）
//
// 与本地 backend/main.py 共享同一 API 契约，只是运行时不同：
// 本地开发：FastAPI @ 127.0.0.1:3459
// 生产：本文件 @ /api/session/close
// =============================================================================

import { createClient } from '@supabase/supabase-js';

// ─────────────────────────────────────────────────────────
// 15 信号元数据（与 backend/signals_meta.py / migrations/002 保持一致）
// ─────────────────────────────────────────────────────────
const SIGNALS = [
  // [name, dimension, display_zh, display_en, order]
  ['cognitive_decay',        'cognitive',     '认知退化',     'Cognitive Decay',         1],
  ['attention_scatter',      'cognitive',     '注意力涣散',   'Attention Scatter',       2],
  ['reality_blur',           'cognitive',     '真实感模糊',   'Reality Blur',            3],
  ['emotional_numbness',     'emotional',     '情感麻木',     'Emotional Numbness',      4],
  ['burnout',                'emotional',     '倦怠耗竭',     'Burnout',                 5],
  ['anxiety_panic',          'emotional',     '焦虑恐慌',     'Anxiety / Panic',         6],
  ['meaning_loss',           'existential',   '意义丧失',     'Meaning Loss',            7],
  ['identity_lost',          'existential',   '身份迷失',     'Identity Lost',           8],
  ['existential_loneliness', 'existential',   '存在性孤独',   'Existential Loneliness',  9],
  ['relational_alienation',  'relational',    '关系异化',     'Relational Alienation',  10],
  ['community_collapse',     'relational',    '共同体瓦解',   'Community Collapse',     11],
  ['bodily_alienation',      'embodied',      '身体异化',     'Bodily Alienation',      12],
  ['sensory_numbness',       'embodied',      '感知钝化',     'Sensory Numbness',       13],
  ['autonomy_loss',          'autonomy_tech', '自主性丧失',   'Autonomy Loss',          14],
  ['tech_alienation',        'autonomy_tech', '技术异化',     'Tech Alienation',        15],
];
const SIGNAL_NAMES = SIGNALS.map(s => s[0]);
const SIGNAL_META = Object.fromEntries(SIGNALS.map(s => [s[0], {
  signal_name: s[0], dimension: s[1],
  display_name_zh: s[2], display_name_en: s[3], sort_order: s[4]
}]));

const DIMENSIONS = ['cognitive', 'emotional', 'existential', 'relational', 'embodied', 'autonomy_tech'];
const DIMENSION_TO_SIGNALS = Object.fromEntries(DIMENSIONS.map(d => [d, []]));
for (const [name, dim] of SIGNALS) DIMENSION_TO_SIGNALS[dim].push(name);

// Mentor × 信号 · 高敏度（与 signals_meta.py 一致）
const MENTOR_SENSITIVITY = {
  freud: ['attention_scatter', 'emotional_numbness', 'anxiety_panic', 'identity_lost',
          'existential_loneliness', 'relational_alienation', 'bodily_alienation', 'sensory_numbness'],
  weber: ['cognitive_decay', 'reality_blur', 'burnout', 'meaning_loss', 'identity_lost',
          'existential_loneliness', 'community_collapse', 'autonomy_loss', 'tech_alienation'],
  marx:  ['cognitive_decay', 'attention_scatter', 'emotional_numbness', 'burnout', 'meaning_loss',
          'relational_alienation', 'community_collapse', 'bodily_alienation', 'autonomy_loss', 'tech_alienation'],
};

const MENTOR_VOICE = {
  freud: {
    name: '西格蒙德·弗洛伊德',
    lens: '从潜意识、防御机制、欲望与压抑的角度解读。看见用户说出来的话背后没说出口的部分。',
    voice_traits: '克制、隐喻、提问而非断言、欧式长句、对童年与梦境敏感。',
  },
  weber: {
    name: '马克斯·韦伯',
    lens: '从理性化、祛魅、天职伦理、意义系统的角度解读。看见用户的疲惫与无意义感是如何由现代结构生产出来的。',
    voice_traits: '沉静、知识分子式克制、长句、关心制度与个人的张力。',
  },
  marx: {
    name: '卡尔·马克思',
    lens: '从异化、劳动、被结构推着走、技术反客为主的角度解读。把个人感受还原到结构条件中。',
    voice_traits: '尖锐、犀利、有怒气但不暴烈、敢于命名结构。',
  },
};

// ─────────────────────────────────────────────────────────
// Prompts
// ─────────────────────────────────────────────────────────
function signalsBlock() {
  return SIGNALS.map(([name, dim, zh]) => `  - \`${name}\` (${zh}) [维度: ${dim}]`).join('\n');
}

function buildSystemPrompt(mentorId) {
  const mentor = MENTOR_VOICE[mentorId] || MENTOR_VOICE.freud;
  const highSens = MENTOR_SENSITIVITY[mentorId] || [];

  return `你是「15 Signals」的复盘生成器。用户刚刚结束了一段与${mentor.name}的对话。
你的任务是用${mentor.name}的视角，为用户生成一份**结构化复盘**——既是数据，也是回声。

# 你的"声音"
- 视角：${mentor.lens}
- 风格：${mentor.voice_traits}
- 永远以对话语言、问句或观察呈现，**绝不是数据报告**
- emotional_summary 是给用户自己看的回声，第一人称对话感，1-2 段；不要列要点

# 15 信号 · 6 维度（rubric-v0.2）
你必须对这 15 个信号每一个都打一个 0.0–1.0 的强度分。
${signalsBlock()}

# ${mentor.name} 的"高敏信号"（生成 moments 时优先聚焦）
${highSens.length ? highSens.join(', ') : '（无特别高敏）'}

# 评分原则
- 仅基于本段对话文本判断，不外推
- 缺席 ≠ 0：未涉及就给 0.0
- 强度对应：0.0–0.2 极弱 / 0.3–0.5 触及未主导 / 0.6–0.8 清晰主题 / 0.9–1.0 强烈贯穿

# 输出（严格 JSON，不要解释，不要 markdown 代码块）
{
  "title": "一句话标题，≤ 18 字，捕捉这段对话的核心 mood（不要写'对话复盘'之类的元词）",
  "signal_scores": {
    "cognitive_decay": 0.0, "attention_scatter": 0.0, "reality_blur": 0.0,
    "emotional_numbness": 0.0, "burnout": 0.0, "anxiety_panic": 0.0,
    "meaning_loss": 0.0, "identity_lost": 0.0, "existential_loneliness": 0.0,
    "relational_alienation": 0.0, "community_collapse": 0.0,
    "bodily_alienation": 0.0, "sensory_numbness": 0.0,
    "autonomy_loss": 0.0, "tech_alienation": 0.0
  },
  "emotional_summary": "一两段诗意的回声，用第二人称'你'，${mentor.name}的视角",
  "moments": [
    {
      "signal_name": "<必须是上面 15 个之一>",
      "quotes": [
        {"speaker": "user" | "mentor", "text": "对话原文中的一句话（≤ 40 字）"}
      ],
      "echo": "用 ${mentor.name} 的视角解读这个 moment 为什么击中了这个信号（≤ 60 字）"
    }
  ]
}

# 严格要求
1. signal_scores 必须包含全部 15 个字段，每个值在 [0.0, 1.0]
2. moments 数量在 1 到 3 之间；moments[i].signal_name 必须在 15 信号清单内
3. moments[i].quotes[j].text **必须是对话原文中实际出现过的句子**，不要改写、不要捏造
4. 全部字段必须输出，不要省略
5. 只输出 JSON 本体，第一个字符是 \`{\`，最后一个字符是 \`}\``;
}

function buildUserMessage(messages) {
  const lines = ['以下是用户与导师的完整对话（按时序）：\n'];
  messages.forEach((m, i) => {
    const role = m.role || '';
    const speaker = role === 'user' ? '用户' : (role === 'assistant' ? '导师' : role);
    const content = (m.content || '').trim();
    lines.push(`[${i + 1}] ${speaker}：${content}`);
  });
  lines.push('\n请按 system 中规定的 JSON 结构输出复盘。');
  return lines.join('\n');
}

// ─────────────────────────────────────────────────────────
// DeepSeek call
// ─────────────────────────────────────────────────────────
async function callDeepSeek(systemPrompt, userMessage) {
  const apiKey = process.env.DEEPSEEK_API_KEY;
  if (!apiKey) throw new Error('Server missing DEEPSEEK_API_KEY');
  const baseUrl = process.env.DEEPSEEK_BASE_URL || 'https://api.deepseek.com';
  const model = process.env.DEEPSEEK_MODEL_SCORER || 'deepseek-chat';

  const maxRetries = 2;
  let lastErr;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const resp = await fetch(`${baseUrl}/chat/completions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${apiKey}`,
        },
        body: JSON.stringify({
          model,
          messages: [
            { role: 'system', content: systemPrompt },
            { role: 'user', content: userMessage },
          ],
          temperature: 0.4,
          max_tokens: 2000,
          response_format: { type: 'json_object' },
        }),
      });
      if (!resp.ok) {
        const errBody = await resp.text();
        throw new Error(`DeepSeek HTTP ${resp.status}: ${errBody.slice(0, 200)}`);
      }
      const data = await resp.json();
      const content = data?.choices?.[0]?.message?.content || '';
      return JSON.parse(content);
    } catch (e) {
      lastErr = e;
      // 短退避：第 0 次失败立即重试，第 1 次等 500ms
      if (attempt < maxRetries) await new Promise(r => setTimeout(r, attempt * 500));
    }
  }
  throw new Error(`DeepSeek call failed after ${maxRetries + 1} attempts: ${lastErr?.message || lastErr}`);
}

// ─────────────────────────────────────────────────────────
// Validation + aggregation
// ─────────────────────────────────────────────────────────
function clip01(v) {
  const f = Number(v);
  if (!Number.isFinite(f)) return 0;
  return Math.max(0, Math.min(1, f));
}

function aggregateDimensions(signalScores) {
  const out = {};
  for (const dim of DIMENSIONS) {
    const names = DIMENSION_TO_SIGNALS[dim];
    const sum = names.reduce((acc, n) => acc + (signalScores[n] || 0), 0);
    out[dim] = names.length ? Math.round((sum / names.length) * 1000) / 1000 : 0;
  }
  return out;
}

function overallIntensity(signalScores) {
  const vals = Object.values(signalScores);
  if (!vals.length) return 0;
  const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
  return Math.round(avg * 100);
}

function topSignals(signalScores, threshold = 0.4, limit = 3) {
  const sorted = Object.entries(signalScores).sort((a, b) => b[1] - a[1]);
  let qualified = sorted.filter(([, v]) => v >= threshold).slice(0, limit);
  if (qualified.length === 0 && sorted.length > 0) qualified = [sorted[0]];
  return qualified.map(([name, intensity]) => {
    const meta = SIGNAL_META[name] || {};
    return {
      signal_name: name,
      intensity: Math.round(intensity * 1000) / 1000,
      dimension: meta.dimension || null,
      display_name_zh: meta.display_name_zh || null,
      display_name_en: meta.display_name_en || null,
    };
  });
}

function normalizeWhitespace(s) {
  return String(s || '').replace(/\s+/g, '');
}

function validateAndShape(llmOut, originalMessages) {
  if (!llmOut || typeof llmOut !== 'object') {
    throw new Error('LLM output is not an object');
  }
  const title = String(llmOut.title || '').trim() || '一次回声';
  const emotionalSummary = String(llmOut.emotional_summary || '').trim();
  const rawScores = llmOut.signal_scores || {};

  // 15 字段补齐 + clip
  const signalScores = {};
  for (const name of SIGNAL_NAMES) signalScores[name] = clip01(rawScores[name]);

  // moments：信号合法 + 引用必须来自原文（白空格归一比对）
  const originalNorm = originalMessages.map(m => normalizeWhitespace(m.content));
  const moments = [];
  const rawMoments = Array.isArray(llmOut.moments) ? llmOut.moments : [];
  for (const m of rawMoments.slice(0, 3)) {
    if (!m || typeof m !== 'object') continue;
    const sig = m.signal_name;
    if (!SIGNAL_META[sig]) continue;
    const rawQuotes = Array.isArray(m.quotes) ? m.quotes : [];
    const quotes = [];
    for (const q of rawQuotes) {
      const text = String(q?.text || '').trim();
      if (!text) continue;
      const norm = normalizeWhitespace(text);
      const hit = originalNorm.some(orig => orig.includes(norm));
      if (!hit) continue;
      const speaker = q?.speaker === 'mentor' ? 'mentor' : 'user';
      quotes.push({ speaker, text });
    }
    if (!quotes.length) continue;
    const meta = SIGNAL_META[sig];
    moments.push({
      signal_name: sig,
      quotes,
      echo: String(m.echo || '').trim(),
      display_name_zh: meta.display_name_zh,
      dimension: meta.dimension,
    });
  }

  const dimensionScores = aggregateDimensions(signalScores);
  const overall = overallIntensity(signalScores);
  const tops = topSignals(signalScores);

  return {
    title,
    overall_intensity: overall,
    dimension_scores: dimensionScores,
    signal_scores: signalScores,
    top_signals: tops,
    emotional_summary: emotionalSummary,
    moments,
  };
}

// ─────────────────────────────────────────────────────────
// Supabase clients
// ─────────────────────────────────────────────────────────
function getAuthClient() {
  return createClient(
    process.env.SUPABASE_URL,
    process.env.SUPABASE_ANON_KEY,
    { auth: { persistSession: false, autoRefreshToken: false } }
  );
}

function getAdminClient() {
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!key) return null;
  return createClient(
    process.env.SUPABASE_URL,
    key,
    { auth: { persistSession: false, autoRefreshToken: false } }
  );
}

// best-effort 写入 sessions.summary
async function persistSummary({ authUserId, mentorId, summaryPayload, messages }) {
  const admin = getAdminClient();
  if (!admin) {
    return { persisted: false, reason: 'SUPABASE_SERVICE_ROLE_KEY not configured' };
  }
  try {
    // 1. authUserId (uuid) → public.users.id (bigint)
    const { data: userRow, error: userErr } = await admin
      .from('users')
      .select('id')
      .eq('auth_user_id', authUserId)
      .maybeSingle();
    if (userErr) return { persisted: false, reason: `users lookup: ${userErr.message}` };
    if (!userRow) {
      return { persisted: false, reason: `no public.users row for auth_user_id ${authUserId}` };
    }
    const userId = userRow.id;

    // 2. INSERT a new session row（每次复盘当成一个独立 session 沉淀）
    const now = new Date().toISOString();
    const { data: sessionRow, error: sessErr } = await admin
      .from('sessions')
      .insert({
        user_id: userId,
        mentor_id: mentorId,
        started_at: now,
        last_active_at: now,
        status: 'closed_by_user',
        closed_at: now,
        summary: summaryPayload,
        summary_generated_at: now,
        turn_count: messages.length,
      })
      .select('id')
      .single();
    if (sessErr) return { persisted: false, reason: `sessions insert: ${sessErr.message}` };
    return { persisted: true, session_id: sessionRow?.id || null };
  } catch (e) {
    return { persisted: false, reason: `unexpected: ${e?.message || e}` };
  }
}

// ─────────────────────────────────────────────────────────
// Handler
// ─────────────────────────────────────────────────────────
export default async function handler(req, res) {
  if (req.method === 'OPTIONS') {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    return res.status(204).end();
  }
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({ error: 'Method not allowed' });
  }

  // ─── 1. 校验 Supabase JWT ───
  const authHeader = req.headers.authorization || '';
  const token = authHeader.startsWith('Bearer ') ? authHeader.slice(7) : '';
  if (!token) return res.status(401).json({ error: 'Missing auth token' });
  const supaAuth = getAuthClient();
  const { data: { user }, error: authError } = await supaAuth.auth.getUser(token);
  if (authError || !user) return res.status(401).json({ error: 'Invalid auth token' });

  // ─── 2. 读 body ───
  const body = typeof req.body === 'string' ? JSON.parse(req.body || '{}') : (req.body || {});
  const mentorId = body.mentor_id;
  const messages = body.messages;
  if (!MENTOR_VOICE[mentorId]) {
    return res.status(400).json({ error: `invalid mentor_id: ${mentorId}` });
  }
  if (!Array.isArray(messages) || messages.length < 2) {
    return res.status(400).json({ error: 'messages must be an array of at least 2 turns' });
  }
  if (!messages.some(m => m?.role === 'user')) {
    return res.status(400).json({ error: 'messages must contain at least one user turn' });
  }

  // ─── 3. 调 DeepSeek ───
  const systemPrompt = buildSystemPrompt(mentorId);
  const userMessage = buildUserMessage(messages);
  let llmOut;
  try {
    llmOut = await callDeepSeek(systemPrompt, userMessage);
  } catch (e) {
    return res.status(502).json({ error: 'DeepSeek error', detail: String(e?.message || e) });
  }

  // ─── 4. 校验 + 归一化 + 聚合 ───
  let shaped;
  try {
    shaped = validateAndShape(llmOut, messages);
  } catch (e) {
    return res.status(502).json({ error: 'LLM output malformed', detail: String(e?.message || e) });
  }

  // ─── 5. best-effort 持久化 ───
  const summaryPayload = {
    ...shaped,
    mentor_id: mentorId,
    rubric_version: 'rubric-v0.2',
  };
  const persistResult = await persistSummary({
    authUserId: user.id,
    mentorId,
    summaryPayload,
    messages,
  });

  // ─── 6. 返回 ───
  return res.status(200).json({
    ...shaped,
    mentor_id: mentorId,
    persisted: persistResult.persisted,
    session_id: persistResult.session_id || null,
    persistence_note: persistResult.persisted ? null : persistResult.reason,
  });
}
