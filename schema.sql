-- =============================================================================
-- 15 Signals · 数据库 Schema (v0.1)
-- 目标数据库：PostgreSQL 15+ with pgvector extension
-- =============================================================================
--
-- 表分组：
--   A. 用户与导师关系  (users, user_mentor_state)
--   B. 会话与对话      (sessions, turns)
--   C. 信号系统        (signal_scores, signal_trajectory)
--   D. 记忆系统        (episodic_memories, user_semantic_profile, semantic_facts)
--   E. 导师知识库      (mentor_kb_chunks)
--
-- 命名约定：
--   - 表名：snake_case 复数
--   - 时间字段：统一 timestamptz
--   - 主键：bigserial id 或 业务主键
--   - 软删除：用 deleted_at 而非物理删除（涉及用户记忆的表必须支持）
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- 文本检索辅助

-- =============================================================================
-- A. 用户与导师关系
-- =============================================================================

CREATE TABLE users (
    id              bigserial PRIMARY KEY,
    email           text UNIQUE NOT NULL,
    display_name    text,
    timezone        text NOT NULL DEFAULT 'Asia/Shanghai',  -- IANA 时区，用于 8:00 跨日判定
    created_at      timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz                              -- 软删除
);

-- 用户与每位导师的关系状态：选择历史、累计会话数、最近活跃
CREATE TABLE user_mentor_state (
    user_id             bigint NOT NULL REFERENCES users(id),
    mentor_id           text NOT NULL,                       -- 'freud' | 'weber' | 'marx'
    first_chosen_at     timestamptz NOT NULL DEFAULT now(),
    total_sessions      int NOT NULL DEFAULT 0,
    total_turns         int NOT NULL DEFAULT 0,
    last_session_at     timestamptz,
    PRIMARY KEY (user_id, mentor_id)
);

-- =============================================================================
-- B. 会话与对话
-- =============================================================================

-- 一次完整对话（用户主动结束 或 8:00 跨日强制结束）
CREATE TABLE sessions (
    id                      bigserial PRIMARY KEY,
    user_id                 bigint NOT NULL REFERENCES users(id),
    mentor_id               text NOT NULL,
    started_at              timestamptz NOT NULL DEFAULT now(),
    last_active_at          timestamptz NOT NULL DEFAULT now(),
    status                  text NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'closed_by_user', 'closed_by_rollover')),
    closed_at               timestamptz,
    summary                 jsonb,            -- 见 spec §9.6 的 JSON 结构
    summary_generated_at    timestamptz,
    current_themes          jsonb NOT NULL DEFAULT '[]'::jsonb,
                            -- [{keyword, confidence, first_seen_turn, last_reinforced_turn}, ...]
    turn_count              int NOT NULL DEFAULT 0
);

CREATE INDEX idx_sessions_user_status ON sessions(user_id, status, last_active_at DESC);
CREATE INDEX idx_sessions_active_rollover ON sessions(status, last_active_at)
    WHERE status = 'active';

-- 单轮对话（一条用户输入 或 一条导师回应）
CREATE TABLE turns (
    id              bigserial PRIMARY KEY,
    session_id      bigint NOT NULL REFERENCES sessions(id),
    turn_index      int NOT NULL,                        -- 会话内序号，从 1 开始
    role            text NOT NULL CHECK (role IN ('user', 'mentor')),
    content         text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    -- 仅 mentor 轮：生成元数据
    mentor_meta     jsonb,                               -- {kb_chunks_used, memories_recalled, latency_ms}
    UNIQUE (session_id, turn_index)
);

CREATE INDEX idx_turns_session ON turns(session_id, turn_index);

-- =============================================================================
-- C. 信号系统
-- =============================================================================

-- 每条用户输入的 15 信号评分（异步生成）
CREATE TABLE signal_scores (
    turn_id         bigint PRIMARY KEY REFERENCES turns(id),
    user_id         bigint NOT NULL REFERENCES users(id),    -- 冗余以便快查
    -- 15 维评分，0.0–1.0
    anxiety                 real NOT NULL,
    depressive_low          real NOT NULL,
    anger                   real NOT NULL,
    fear                    real NOT NULL,
    identity_disturbance    real NOT NULL,
    self_worth_doubt        real NOT NULL,
    emptiness               real NOT NULL,
    loss_of_control         real NOT NULL,
    desire_longing          real NOT NULL,
    repression              real NOT NULL,
    unconscious_material    real NOT NULL,
    work_burnout            real NOT NULL,
    alienation              real NOT NULL,
    relational_tension      real NOT NULL,
    meaning_crisis          real NOT NULL,
    -- 元数据
    scorer_model            text NOT NULL,                   -- 用于版本回溯，如 'claude-sonnet-4.6'
    scorer_version          text NOT NULL,                   -- rubric 版本，如 'rubric-v0.1'
    scored_at               timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_signal_scores_user_time ON signal_scores(user_id, scored_at DESC);

-- 每用户每信号每日的预聚合统计（避免每次开场都跑窗口聚合）
-- 由每日 8:00 跨日 job 写入
CREATE TABLE signal_trajectory (
    user_id         bigint NOT NULL REFERENCES users(id),
    signal_name     text NOT NULL,                          -- 与 signal_scores 字段名对应
    date            date NOT NULL,                          -- 用户本地时区日期
    daily_avg       real NOT NULL,
    daily_max       real NOT NULL,
    sample_count    int NOT NULL,
    -- 滚动窗口预计算
    rolling_7d_avg  real,
    rolling_14d_avg real,
    slope_7d        real,                                    -- 7 天回归斜率，用于识别"上升趋势"
    PRIMARY KEY (user_id, signal_name, date)
);

CREATE INDEX idx_trajectory_user_signal ON signal_trajectory(user_id, signal_name, date DESC);

-- =============================================================================
-- D. 记忆系统
-- =============================================================================

-- 情景记忆：从对话中抽取的具体事件 / 引用 / 模式
-- 由 session 关闭时的总结任务生成，也可由实时观察生成
CREATE TABLE episodic_memories (
    id                          bigserial PRIMARY KEY,
    user_id                     bigint NOT NULL REFERENCES users(id),
    origin_session_id           bigint REFERENCES sessions(id),
    origin_turn_id              bigint REFERENCES turns(id),
    mentor_id                   text NOT NULL,                  -- 哪位导师视角下生成
    memory_type                 text NOT NULL
                                CHECK (memory_type IN ('event', 'quote', 'pattern', 'open_thread', 'fact')),
    content                     text NOT NULL,                  -- 叙述化的记忆文本，供 LLM 读取
    content_embedding           vector(1024),                   -- voyage-3 维度
    source_quote                text,                           -- 用户原话（如适用）
    related_signals             text[] NOT NULL DEFAULT '{}',   -- 关联的信号名
    -- 显著度系统
    base_salience               real NOT NULL DEFAULT 0.5,      -- 创建时的初始强度
    current_salience            real NOT NULL DEFAULT 0.5,      -- 衰减/强化后的当前值
    reinforcement_count         int NOT NULL DEFAULT 0,
    last_reinforced_at          timestamptz NOT NULL DEFAULT now(),
    emotional_intensity         real,                           -- 0–1，来源轮次的信号均值
    -- 巩固到语义画像
    consolidated_to_semantic    boolean NOT NULL DEFAULT false,
    consolidated_at             timestamptz,
    -- 生命周期
    created_at                  timestamptz NOT NULL DEFAULT now(),
    deleted_at                  timestamptz                     -- 用户可"遗忘"某条记忆
);

CREATE INDEX idx_episodic_user_salience ON episodic_memories(user_id, current_salience DESC)
    WHERE deleted_at IS NULL;
CREATE INDEX idx_episodic_user_recent ON episodic_memories(user_id, last_reinforced_at DESC)
    WHERE deleted_at IS NULL;
CREATE INDEX idx_episodic_embedding ON episodic_memories
    USING ivfflat (content_embedding vector_cosine_ops) WITH (lists = 100);

-- 用户语义画像：经过巩固的、稳定的用户理解，供导师每次对话开场读取
-- 一个用户一行，整体读写
CREATE TABLE user_semantic_profile (
    user_id             bigint PRIMARY KEY REFERENCES users(id),
    profile             jsonb NOT NULL DEFAULT '{}'::jsonb,
                        -- {
                        --   core_themes: ["职业倦怠", "母亲关系"],
                        --   self_narratives: ["把自己描述为'演员'"],
                        --   relational_map: {mother: "..", partner: ".."},
                        --   temporal_patterns: ["周日晚上焦虑高位"],
                        --   recurring_quotes: ["每天都在演戏"],
                        --   resolved_threads: [],
                        --   open_threads: []
                        -- }
    version             int NOT NULL DEFAULT 1,
    last_consolidated_at timestamptz NOT NULL DEFAULT now(),
    consolidation_count int NOT NULL DEFAULT 0
);

-- 原子化的语义事实表（可选，但强烈建议）：每条事实可独立检索 / 否证 / 追溯来源
CREATE TABLE semantic_facts (
    id                  bigserial PRIMARY KEY,
    user_id             bigint NOT NULL REFERENCES users(id),
    fact_text           text NOT NULL,                       -- "用户的母亲患有抑郁症"
    fact_type           text NOT NULL
                        CHECK (fact_type IN ('relationship', 'event_history',
                                              'self_concept', 'pattern', 'value', 'aspiration')),
    confidence          real NOT NULL DEFAULT 0.5,
    embedding           vector(1024),
    source_episodic_ids bigint[] NOT NULL DEFAULT '{}',      -- 出处的 episodic_memories
    source_session_ids  bigint[] NOT NULL DEFAULT '{}',
    first_observed_at   timestamptz NOT NULL DEFAULT now(),
    last_confirmed_at   timestamptz NOT NULL DEFAULT now(),
    contradicted_at     timestamptz,                          -- 用户后来否认了 → 标记不删除
    deleted_at          timestamptz
);

CREATE INDEX idx_facts_user ON semantic_facts(user_id)
    WHERE deleted_at IS NULL AND contradicted_at IS NULL;
CREATE INDEX idx_facts_embedding ON semantic_facts
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

-- =============================================================================
-- E. 导师知识库
-- =============================================================================

CREATE TABLE mentor_kb_chunks (
    id                  bigserial PRIMARY KEY,
    mentor_id           text NOT NULL,                        -- 'freud' | 'weber' | 'marx'
    chunk_type          text NOT NULL
                        CHECK (chunk_type IN (
                            'concept',           -- 理论概念卡（压抑、异化、祛魅）
                            'voice_example',     -- 语言风格范本
                            'opening_template',  -- 开场白模板
                            'signal_mapping',    -- 信号→理论映射
                            'forbidden_move',    -- 该导师绝不会说的话
                            'biographical'       -- 生平/著作背景
                        )),
    title               text NOT NULL,                        -- "Verdrängung (压抑)"
    content             text NOT NULL,
    embedding           vector(1024),
    -- 检索辅助
    tags                text[] NOT NULL DEFAULT '{}',         -- ['焦虑', '梦', '童年']
    related_signals     text[] NOT NULL DEFAULT '{}',         -- 该 chunk 适合解读哪些信号
    -- opening_template 专用
    template_meta       jsonb,                                -- {signal_combo: [...], has_memory: bool}
    -- 引用追溯
    source_citation     text,                                 -- "《释梦》第七章"
    -- 版本管理
    kb_version          text NOT NULL DEFAULT 'v0.1',
    created_at          timestamptz NOT NULL DEFAULT now(),
    deleted_at          timestamptz
);

CREATE INDEX idx_kb_mentor_type ON mentor_kb_chunks(mentor_id, chunk_type)
    WHERE deleted_at IS NULL;
CREATE INDEX idx_kb_embedding ON mentor_kb_chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_kb_signals ON mentor_kb_chunks USING gin (related_signals);

-- =============================================================================
-- 衍生视图（可选，便于查询）
-- =============================================================================

-- 用户当前应被回忆起的 Top-N 记忆：salience × recency 联合排序
CREATE OR REPLACE VIEW v_user_top_memories AS
SELECT
    user_id,
    id AS memory_id,
    content,
    current_salience,
    last_reinforced_at,
    related_signals,
    -- 综合排名：显著度为主，时近性为辅
    current_salience * exp(-extract(epoch from (now() - last_reinforced_at)) / (86400.0 * 14)) AS rank_score
FROM episodic_memories
WHERE deleted_at IS NULL
ORDER BY rank_score DESC;

-- =============================================================================
-- END OF SCHEMA
-- =============================================================================
