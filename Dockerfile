# 15 Signals · Backend (FastAPI) 容器镜像
# 用于 Fly.io 部署。本地开发不需要这个文件。

FROM python:3.11-slim

WORKDIR /app

# 系统依赖：编译 psycopg 等所需
RUN apt-get update && apt-get install -y --no-install-recommends \
      gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖（让 docker 层缓存生效）
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# 复制代码
COPY backend/ /app/backend/

# Fly.io 期望容器监听 PORT 环境变量（默认 8080）
ENV PORT=8080
EXPOSE 8080

# Healthcheck（fly.toml 里也会用 /health）
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -fsS http://localhost:${PORT}/health || exit 1

# 启动 FastAPI
CMD uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}
