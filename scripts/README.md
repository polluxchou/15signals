# Scripts

## ingest_kb.py · 导师知识库 ingest

把 `mentor_kb/{freud,weber,marx}.md` 解析、生成 Voyage embedding、写入 Postgres `mentor_kb_chunks` 表。

### 一次性准备

1. **建数据库 + 跑 schema**：
   ```bash
   # 假设 Postgres 已经装好（推荐 Supabase 或本地 Docker）
   psql "$DATABASE_URL" -f ../schema.sql
   ```

2. **创建虚拟环境 + 装依赖**：
   ```bash
   cd scripts
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **配置环境变量**：复制项目根目录的 `.env.example` 为 `.env`，填入：
   ```
   DATABASE_URL=postgres://user:pass@host:5432/dbname
   VOYAGE_API_KEY=pa-...
   VOYAGE_MODEL=voyage-3   # 可选，默认 voyage-3（1024 维，匹配 schema）
   ```

### 用法

```bash
# 默认：所有三位导师，完整流程（解析 → 嵌入 → 写库）
python ingest_kb.py

# 只 ingest 弗洛伊德
python ingest_kb.py --mentor freud

# 干跑：解析 + 嵌入，但不写库（验证文档格式 + API 连通）
python ingest_kb.py --dry-run

# 完全离线测试：只解析，不调 Voyage、不写库
python ingest_kb.py --dry-run --no-embed
```

### 幂等策略

脚本对每个 `(mentor_id, kb_version)` 组合：

1. 把现有同版本行**软删除**（`deleted_at = now()`）
2. 插入全新一批

意味着可以**反复运行**——每次都用最新 markdown 覆盖。历史版本被保留（带 `deleted_at` 标记），不会丢。

> 注意：每次运行都会生成新的 `id`。如果其他表（如 `turns.mentor_meta`）以 ID 引用了 KB chunk，那些引用会变成 stale。当前 schema 没有外键依赖 `mentor_kb_chunks`，所以 v0.1 可接受。

### 故障排查

| 现象 | 原因 | 处理 |
|------|------|------|
| `No chunk headers found` | markdown 文件缺少 `### [chunk_type] · Title` 结构 | 检查文件是否被误编辑 |
| `skip (no yaml block)` | 某条目的 `\`\`\`yaml ... \`\`\`` 缺失或被破坏 | 看日志定位是哪条 |
| `skip (invalid chunk_type)` | YAML 里的 `chunk_type` 字段不在白名单 | 见 `VALID_CHUNK_TYPES`；常见是拼写错误 |
| `Embedding error` | Voyage API 故障或限流 | 脚本会自动重试 3 次，仍失败再人工排查 |
| 写库报 CHECK 约束错 | `chunk_type` 不在 schema 的 enum 范围 | 同上 |
| `extension "vector" does not exist` | Postgres 没装 pgvector | Supabase 默认启用；本地 PG 需 `CREATE EXTENSION vector` |

### 后续可加

- `--purge-deleted` 物理删除 soft-deleted 行
- `--diff-only` 只 ingest 内容有变化的 chunk（用 fingerprint 比对）
- 增量 ingest：先比对 fingerprint，未变的不重新生成 embedding（省钱）
