# 部署 Backend 到 Fly.io · 操作手册

把项目的 FastAPI 后端部署到 Fly.io，让 Vercel 上的主前端能跨域调用。

## 0. 一次性准备

```bash
# 安装 Fly CLI（macOS）
brew install flyctl

# 登录（会打开浏览器）
fly auth login

# 第一次会要求绑定信用卡——为了防滥用，正常使用免费额度不会扣
```

## 1. 创建应用（不部署，先注册名字）

⚠️ `signals-backend` 这个名字可能被占；你可以改 `fly.toml` 里的 `app = "..."` 成别的（如 `signals-backend-你的名字`）。

```bash
cd ~/Code/15Signals

# 用 fly.toml 里的配置创建 app（这一步只是注册，不部署）
fly apps create signals-backend
# 如果说被占用：fly apps create signals-backend-pollux （改个名）
# 注意改完后 fly.toml 里的 app 字段也要同步改
```

## 2. 配置密钥（不会进镜像，只在运行时注入）

把本地 `.env` 里的 3 个关键密钥同步到 Fly。**别提交 .env 到 git**：

```bash
# DeepSeek
fly secrets set DEEPSEEK_API_KEY="$(grep '^DEEPSEEK_API_KEY=' .env | cut -d= -f2-)"

# Voyage
fly secrets set VOYAGE_API_KEY="$(grep '^VOYAGE_API_KEY=' .env | cut -d= -f2-)"

# Supabase Postgres（连接串）
fly secrets set DATABASE_URL="$(grep '^DATABASE_URL=' .env | cut -d= -f2-)"

# 可选：保护 admin/jobs/* 端点（强烈建议在生产环境配）
# fly secrets set ADMIN_TOKEN="$(openssl rand -hex 32)"
```

验证：

```bash
fly secrets list
# 应该看到 DEEPSEEK_API_KEY / VOYAGE_API_KEY / DATABASE_URL 三个（值不显示，只显示 digest）
```

## 3. 部署

```bash
fly deploy
```

第一次部署会：
1. 用本地 Docker 构建镜像（如果没装 Docker，Fly 会用远端 builder）
2. 推到 Fly registry
3. 拉起一个机器实例
4. 跑 healthcheck（GET /health）

成功后会输出类似：

```
Visit your newly deployed app at https://signals-backend.fly.dev/
```

## 4. 验证

```bash
# 健康检查
curl https://signals-backend.fly.dev/health
# 期望：{"ok":true,"db_enabled":true,"rubric_version":"rubric-v0.2","signal_count":15}

# 测一下 list
curl "https://signals-backend.fly.dev/api/session/list?user_email=kexuejia@gmail.com&limit=2"
```

## 5. 让 Vercel 知道 backend 在哪

`vercel.json` 已经预填了 rewrite 规则——如果你 fly.toml 改了 app 名字，**也要同步改 vercel.json 里的 destination**：

```json
"destination": "https://你的-app-名字.fly.dev/api/session/:path*"
```

改完 commit + push：

```bash
git add vercel.json
git commit -m "Wire Vercel /api/session/* to fly.io backend"
git push
```

Vercel 自动重新部署后，**线上的 15signals_web.html 调 `/api/session/turn/stream` 就会被转发到 Fly 的 FastAPI**。

## 6. 日常运维

```bash
# 看运行日志（流式）
fly logs

# 看机器状态
fly status

# 触发重新部署
fly deploy

# 加资源（如果 512MB 不够）
# 改 fly.toml 里的 memory = "1gb"，然后 fly deploy

# 临时停机省钱
fly scale count 0       # 停
fly scale count 1       # 重启
```

## 注意点

| 项 | 说明 |
|---|---|
| **冷启动** | 配置了 auto_stop_machines = "stop"，闲置时机器关机；下次请求会自启动，需要 ~3-5 秒——SSE 流首请求可能略卡 |
| **CORS** | 后端 `app.add_middleware(CORSMiddleware, allow_origins=["*"])` 已经全开；Vercel 用 rewrite（同域）也行 |
| **SSE keepalive** | Fly proxy 默认 1 分钟无数据断流；DeepSeek 单次响应通常 < 10 秒，不会触发 |
| **scrubbing** | 任何密钥变更后跑 `fly deploy` 让新机器拿到 |
| **多区域** | `fly regions add nrt sin` 可以扩展到亚洲，让中国用户延迟更低 |
| **数据库** | DATABASE_URL 指向 Supabase（共享）；Fly 这边**没有自己的数据库**，只是计算层 |
| **cron 任务** | 当前 cron_rollover / decay / consolidate 还是本机跑；要部署 cron 需要单独配 [Fly Machines schedule](https://fly.io/docs/launch/cron/) 或在 Vercel cron 调 /api/admin/jobs/* |

## 出问题怎么 debug

```bash
# 看启动日志
fly logs --instance <machine-id>

# 远程 SSH 进容器
fly ssh console
# 容器里：
ls /app/backend
python -c "from backend import main"
```

常见错误：

| 报错 | 原因 |
|---|---|
| `pgvector extension not enabled` | Supabase 上的 vector 扩展没启用——在 dashboard 启用 |
| `password authentication failed` | DATABASE_URL 里的密码错（特别注意 URL 里的特殊字符要 encode） |
| `VOYAGE_API_KEY not set` | 密钥没同步到 fly；`fly secrets list` 确认 |
| Vercel rewrite 404 | vercel.json 里的 destination URL 不对，或 Fly app 名字不一致 |
