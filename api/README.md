# Vercel Serverless Functions

| 路径 | 文件 | 用途 |
|---|---|---|
| `POST /api/deepseek` | `api/deepseek.js` | 主对话的 DeepSeek 代理（带 Supabase JWT 校验） |
| `POST /api/session/close` | `api/session/close.js` | 结束对话 → 生成结构化复盘 + best-effort 写入 Supabase |

两个函数都是 Node.js (ESM)，运行在 Vercel Node Runtime。本地开发不要用它们——本地走 `backend/` 的 FastAPI（端口 3459），前端会自动检测域名切换端点。

## 必填环境变量（Vercel Project → Settings → Environment Variables）

| Key | 用途 | 必填? |
|---|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek 主 key | ✅ |
| `DEEPSEEK_BASE_URL` | 默认 `https://api.deepseek.com` | 可选 |
| `DEEPSEEK_MODEL_SCORER` | 默认 `deepseek-chat` | 可选 |
| `SUPABASE_URL` | `https://msvcnuvduivlzggncmej.supabase.co` | ✅ |
| `SUPABASE_ANON_KEY` | 与前端 `SUPA_ANON_KEY` 一致，用于校验用户 JWT | ✅ |
| `SUPABASE_SERVICE_ROLE_KEY` | service-role key，绕 RLS 写 `sessions.summary` | ✅ 要持久化就必填 |

⚠️ **`SUPABASE_SERVICE_ROLE_KEY` 是 admin 权限的 key**，绝不能写进任何前端文件或提交进仓库。只放在 Vercel 后台。如果忘了配，复盘仍能返回（前端正常显示），但不会写 DB——响应里 `persisted: false` + `persistence_note: "..."` 会告诉你原因。

## DB 写入路径

```
auth.users.id (uuid, 来自 JWT)
        ↓ SELECT id FROM public.users WHERE auth_user_id = $1
public.users.id (bigint)
        ↓ INSERT INTO sessions (user_id, mentor_id, summary, ...)
sessions.summary (jsonb)
```

`public.users` 行由 `migrations/001_auth_user_id.sql` 的 trigger 在用户注册时自动创建。如果用户已存在但 trigger 没跑过（migration 之前注册的用户），写入会失败并返回 `no public.users row for auth_user_id ...`——这种情况手动在 Supabase 里跑一条：

```sql
INSERT INTO public.users (email, auth_user_id)
SELECT email, id FROM auth.users WHERE id = '<the-uuid>';
```

## 验收清单

部署后跑这几个 curl 验证：

```bash
# 1. 健康路径（确认部署成功）
curl https://YOUR-DOMAIN.vercel.app/

# 2. 用现有账号登录拿 access_token 后调一次（用 supabase JS SDK 或 Postman）
curl -X POST https://YOUR-DOMAIN.vercel.app/api/session/close \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <SUPABASE_ACCESS_TOKEN>" \
  -d '{
    "mentor_id": "weber",
    "messages": [
      {"role":"user","content":"我感觉最近什么都没意思"},
      {"role":"assistant","content":"你说的没意思，什么时候开始的？"},
      {"role":"user","content":"几个月了。机械上班、刷手机到半夜"}
    ]
  }' | jq

# 3. 期望响应里：
#    - top_signals 至少 1 条
#    - emotional_summary 不为空
#    - persisted: true   ← 如果 service-role key 配好了
#    - 在 Supabase Table Editor 看 sessions 表，应该多了一行
```

## 与本地 FastAPI 的对齐

`api/session/close.js` 是 `backend/main.py` 的 Node 港版，**API 契约完全一致**。前端通过 `REVIEW_ENDPOINT` 自动切换：

```js
const isLocal = location.hostname === 'localhost'
             || location.hostname === '127.0.0.1'
             || location.protocol === 'file:';
return isLocal ? 'http://127.0.0.1:3459/session/close' : '/api/session/close';
```

如果某天要改 15 信号 / prompt / 聚合规则，**两个文件都要改**——这是当前选型的代价。后续可以考虑：
- 只保留 Vercel 函数，本地开发直接 `vercel dev` 跑
- 或者只保留 FastAPI，把它跑在某个长期服务器（Fly / Railway）上，Vercel 只放静态站
