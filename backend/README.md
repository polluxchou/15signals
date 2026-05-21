# 15 Signals · Backend (Phase 2)

FastAPI 服务，目前只提供"结束对话 → 生成结构化复盘"的端点。
后续会逐步把 spec 里的其余异步任务（信号评分、主题重评、记忆抽取等）搬进来。

## 端点

| Method | 路径 | 用途 |
|---|---|---|
| `GET` | `/health` | 健康检查 + 配置自检 |
| `GET` | `/signals/meta` | 15 信号元数据（名/中文名/维度归属/排序），前端可缓存 |
| `POST` | `/session/close` | 关闭对话 + 调 DeepSeek 生成复盘 + 可选写库 |

## 运行

```bash
cd ~/Code/15Signals
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt

# 复用项目根目录的 .env（DEEPSEEK_API_KEY 必填；DATABASE_URL 可选）
python -m uvicorn backend.main:app --host 127.0.0.1 --port 3459 --reload
```

启动后：
- `curl http://127.0.0.1:3459/health` 应该返回 `{"ok": true, ...}`
- `curl http://127.0.0.1:3459/signals/meta | jq` 看 15 信号

## /session/close 调用示例

```bash
curl -X POST http://127.0.0.1:3459/session/close \
  -H "Content-Type: application/json" \
  -d '{
    "mentor_id": "weber",
    "messages": [
      {"role": "user", "content": "我感觉最近什么都没意思，做什么都提不起劲"},
      {"role": "assistant", "content": "你说的这种'没意思'——它是什么时候开始的？"},
      {"role": "user", "content": "应该有几个月了。每天上班就是机械地完成任务，回家就是刷手机到半夜"},
      {"role": "assistant", "content": "你描述的节奏，让我想起一种被理性化吞没的生活..."}
    ],
    "user_id": null,
    "session_id": null
  }' | jq
```

返回结构：

```json
{
  "title": "...",
  "overall_intensity": 67,
  "dimension_scores": {
    "cognitive": 0.43,
    "emotional": 0.71,
    "existential": 0.80,
    "relational": 0.20,
    "embodied": 0.10,
    "autonomy_tech": 0.55
  },
  "signal_scores": { "cognitive_decay": 0.4, ...全部 15 ... },
  "top_signals": [
    { "signal_name": "meaning_loss", "intensity": 0.85, "dimension": "existential", "display_name_zh": "意义丧失", ... },
    ...
  ],
  "emotional_summary": "...",
  "moments": [
    {
      "signal_name": "meaning_loss",
      "quotes": [{"speaker": "user", "text": "我感觉最近什么都没意思..."}],
      "echo": "...",
      "display_name_zh": "意义丧失",
      "dimension": "existential"
    }
  ],
  "mentor_id": "weber",
  "persisted": false,
  "session_id": null,
  "persistence_note": "DATABASE_URL not configured; returning summary without persisting"
}
```

## 与 proxy.py 的关系

- `proxy.py` 端口 3458：纯 CORS 转发，给浏览器直连 DeepSeek 用（不解析、不重试）
- 本服务 3459：服务端调 DeepSeek 拿结构化输出（response_format=json_object）+ 校验 + 聚合 + 可选持久化

两者各司其职，不互相替代。前端"在对话中聊天"还是走 3458；前端"结束对话拿复盘"走 3459。

## 持久化行为

- 若 `.env` 没有 `DATABASE_URL` → 直接 noop，返回 `persisted: false`，复盘内容照常返回前端
- 若有 `DATABASE_URL` 且请求带 `session_id` → UPDATE `sessions.summary`、status 改 `closed_by_user`
- 若有 `DATABASE_URL` 且请求带 `user_id` 但无 `session_id` → INSERT 一个新 `sessions` 行
- 写库失败 → 不抛错，返回 `persisted: false` + `persistence_note`

这样设计的原因：复盘是用户体感优先的功能，DB 不可用时也不能让 UI 转圈。

## 已知限制 (Phase 2 v0)

- LLM 输出的 quote 要求**必须**是原文子串；如果 DeepSeek 改写了 quote，那条 moment 会被默默丢弃。这是反捏造的保险，但偶尔会让 moments 数量比预期少。
- 暂未实现 streaming 响应；前端拿到响应可能要等 5-15 秒
- 暂未接入异步评分（schema 的 `signal_scores` 表此次不写入）；本端点是"一站式"现场生成，不依赖之前的 per-turn 评分。后续接入异步评分后会复用已有分数。
