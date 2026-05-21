-- =============================================================================
-- 15 Signals · Migration 002: 切换到 rubric-v0.2 新 15 信号体系
-- 日期：2026-05-21
-- 适用：Supabase SQL Editor 或本地 psql
-- =============================================================================
--
-- 本次切换：
--   旧体系 (rubric-v0.1)：临床/精神分析口径，15 字段
--     anxiety, depressive_low, anger, fear, identity_disturbance,
--     self_worth_doubt, emptiness, loss_of_control, desire_longing,
--     repression, unconscious_material, work_burnout, alienation,
--     relational_tension, meaning_crisis
--   新体系 (rubric-v0.2)：文明病/媒介批判口径，15 字段，分 6 维度
--     [认知] cognitive_decay, attention_scatter, reality_blur
--     [情感] emotional_numbness, burnout, anxiety_panic
--     [存在] meaning_loss, identity_lost, existential_loneliness
--     [关系] relational_alienation, community_collapse
--     [身体] bodily_alienation, sensory_numbness
--     [自主/技术] autonomy_loss, tech_alienation
--
-- 数据策略：
--   ⚠️ signal_scores 中已有的旧字段数据无法 1:1 映射到新字段
--      （信号语义不同，强行映射会污染评分）。
--   因此本 migration **不保留旧评分数据**：
--      1. 把 signal_scores 重命名为 signal_scores_v01_archive（软备份）
--      2. 用新字段重建 signal_scores
--      3. signal_trajectory 同步重置（依赖 signal_name 字符串）
--
--   若担心数据：先在 Supabase 里把 signal_scores_v01_archive 导出再跑本迁移。
-- =============================================================================

BEGIN;

-- ----- 1. 归档旧 signal_scores -----
ALTER TABLE IF EXISTS signal_scores
    RENAME TO signal_scores_v01_archive;

-- 注释存档，方便后续追溯
COMMENT ON TABLE signal_scores_v01_archive IS
    '归档：rubric-v0.1（临床口径）信号评分。被 migration 002 替换。';

-- 旧索引会跟随 rename，但起名带新名比较乱，先 drop（再建时不存在了）
-- 这里手动 drop 旧索引以释放名字空间
DROP INDEX IF EXISTS idx_signal_scores_user_time;

-- ----- 2. 创建新 signal_scores (rubric-v0.2) -----
CREATE TABLE signal_scores (
    turn_id         bigint PRIMARY KEY REFERENCES turns(id),
    user_id         bigint NOT NULL REFERENCES users(id),

    -- ===== 6 维度 × 15 信号，0.0–1.0 =====

    -- [认知维度]
    cognitive_decay         real NOT NULL,
    attention_scatter       real NOT NULL,
    reality_blur            real NOT NULL,

    -- [情感维度]
    emotional_numbness      real NOT NULL,
    burnout                 real NOT NULL,
    anxiety_panic           real NOT NULL,

    -- [存在维度]
    meaning_loss            real NOT NULL,
    identity_lost           real NOT NULL,
    existential_loneliness  real NOT NULL,

    -- [关系维度]
    relational_alienation   real NOT NULL,
    community_collapse      real NOT NULL,

    -- [身体维度]
    bodily_alienation       real NOT NULL,
    sensory_numbness        real NOT NULL,

    -- [自主/技术维度]
    autonomy_loss           real NOT NULL,
    tech_alienation         real NOT NULL,

    -- ===== 元数据 =====
    scorer_model            text NOT NULL,
    scorer_version          text NOT NULL DEFAULT 'rubric-v0.2',
    scored_at               timestamptz NOT NULL DEFAULT now(),

    -- 值域约束（每个信号必须在 [0, 1]）
    CONSTRAINT signal_scores_v02_range CHECK (
        cognitive_decay BETWEEN 0 AND 1 AND
        attention_scatter BETWEEN 0 AND 1 AND
        reality_blur BETWEEN 0 AND 1 AND
        emotional_numbness BETWEEN 0 AND 1 AND
        burnout BETWEEN 0 AND 1 AND
        anxiety_panic BETWEEN 0 AND 1 AND
        meaning_loss BETWEEN 0 AND 1 AND
        identity_lost BETWEEN 0 AND 1 AND
        existential_loneliness BETWEEN 0 AND 1 AND
        relational_alienation BETWEEN 0 AND 1 AND
        community_collapse BETWEEN 0 AND 1 AND
        bodily_alienation BETWEEN 0 AND 1 AND
        sensory_numbness BETWEEN 0 AND 1 AND
        autonomy_loss BETWEEN 0 AND 1 AND
        tech_alienation BETWEEN 0 AND 1
    )
);

CREATE INDEX idx_signal_scores_user_time
    ON signal_scores(user_id, scored_at DESC);

COMMENT ON TABLE signal_scores IS
    '15 信号评分（rubric-v0.2 文明病/媒介批判口径，分 6 维度）。每条用户输入一行，异步生成。';

-- ----- 3. signal_trajectory 重置 -----
-- signal_name 是字符串字段，旧名（如 'anxiety'）不再有意义。
-- 把已有趋势数据归档后清空，让新体系从今天开始累计。
ALTER TABLE IF EXISTS signal_trajectory
    RENAME TO signal_trajectory_v01_archive;

DROP INDEX IF EXISTS idx_trajectory_user_signal;

CREATE TABLE signal_trajectory (
    user_id         bigint NOT NULL REFERENCES users(id),
    signal_name     text NOT NULL,                          -- 与 signal_scores 列名对应
    date            date NOT NULL,
    daily_avg       real NOT NULL,
    daily_max       real NOT NULL,
    sample_count    int NOT NULL,
    rolling_7d_avg  real,
    rolling_14d_avg real,
    slope_7d        real,
    PRIMARY KEY (user_id, signal_name, date),
    -- 限制 signal_name 必须在新 15 个之内，防止脏数据
    CONSTRAINT signal_trajectory_v02_name CHECK (
        signal_name IN (
            'cognitive_decay', 'attention_scatter', 'reality_blur',
            'emotional_numbness', 'burnout', 'anxiety_panic',
            'meaning_loss', 'identity_lost', 'existential_loneliness',
            'relational_alienation', 'community_collapse',
            'bodily_alienation', 'sensory_numbness',
            'autonomy_loss', 'tech_alienation'
        )
    )
);

CREATE INDEX idx_trajectory_user_signal
    ON signal_trajectory(user_id, signal_name, date DESC);

COMMENT ON TABLE signal_trajectory_v01_archive IS
    '归档：rubric-v0.1 日聚合趋势数据。被 migration 002 替换。';

-- ----- 4. 信号维度元数据表（供前端查询展示用） -----
-- 把"维度↔信号"映射沉淀为数据，避免硬编码到代码里
CREATE TABLE IF NOT EXISTS signal_meta (
    signal_name         text PRIMARY KEY,
    dimension           text NOT NULL CHECK (dimension IN (
        'cognitive', 'emotional', 'existential',
        'relational', 'embodied', 'autonomy_tech'
    )),
    display_name_zh     text NOT NULL,    -- "认知退化"
    display_name_en     text NOT NULL,    -- "Cognitive Decay"
    sort_order          int NOT NULL,     -- 1..15，给前端固定顺序
    rubric_version      text NOT NULL DEFAULT 'rubric-v0.2'
);

INSERT INTO signal_meta (signal_name, dimension, display_name_zh, display_name_en, sort_order) VALUES
    -- 认知
    ('cognitive_decay',        'cognitive',     '认知退化',     'Cognitive Decay',          1),
    ('attention_scatter',      'cognitive',     '注意力涣散',   'Attention Scatter',        2),
    ('reality_blur',           'cognitive',     '真实感模糊',   'Reality Blur',             3),
    -- 情感
    ('emotional_numbness',     'emotional',     '情感麻木',     'Emotional Numbness',       4),
    ('burnout',                'emotional',     '倦怠耗竭',     'Burnout',                  5),
    ('anxiety_panic',          'emotional',     '焦虑恐慌',     'Anxiety / Panic',          6),
    -- 存在
    ('meaning_loss',           'existential',   '意义丧失',     'Meaning Loss',             7),
    ('identity_lost',          'existential',   '身份迷失',     'Identity Lost',            8),
    ('existential_loneliness', 'existential',   '存在性孤独',   'Existential Loneliness',   9),
    -- 关系
    ('relational_alienation',  'relational',    '关系异化',     'Relational Alienation',   10),
    ('community_collapse',     'relational',    '共同体瓦解',   'Community Collapse',      11),
    -- 身体
    ('bodily_alienation',      'embodied',      '身体异化',     'Bodily Alienation',       12),
    ('sensory_numbness',       'embodied',      '感知钝化',     'Sensory Numbness',        13),
    -- 自主/技术
    ('autonomy_loss',          'autonomy_tech', '自主性丧失',   'Autonomy Loss',           14),
    ('tech_alienation',        'autonomy_tech', '技术异化',     'Tech Alienation',         15)
ON CONFLICT (signal_name) DO UPDATE SET
    dimension       = EXCLUDED.dimension,
    display_name_zh = EXCLUDED.display_name_zh,
    display_name_en = EXCLUDED.display_name_en,
    sort_order      = EXCLUDED.sort_order,
    rubric_version  = EXCLUDED.rubric_version;

COMMENT ON TABLE signal_meta IS
    '15 信号的元数据：维度归属、显示名、排序。前端从这里读，不要硬编码。';

-- ----- 5. mentor_kb_chunks.related_signals 清理 -----
-- 旧的 related_signals 数组里还是 'anxiety' 等旧名，新 KB ingest 时会用新名覆盖。
-- 这里不动它（保留以便回滚），等下次 ingest_kb.py 跑完会刷新。
-- 但加一个提醒注释：
COMMENT ON COLUMN mentor_kb_chunks.related_signals IS
    '该 chunk 适合解读的信号名（数组）。注意：rubric-v0.2 起信号名已切换，需要重跑 ingest_kb.py 才会刷新到新名。';

-- ----- 6. episodic_memories.related_signals 同上 -----
COMMENT ON COLUMN episodic_memories.related_signals IS
    '该记忆关联的信号名（数组）。rubric-v0.2 起切换到新 15 信号名。已有记忆的旧信号名不会自动迁移，由总结任务重写时更新。';

COMMIT;

-- =============================================================================
-- 回滚（仅紧急情况，会丢失新评分数据）：
--
--   BEGIN;
--   DROP TABLE IF EXISTS signal_meta;
--   DROP TABLE IF EXISTS signal_scores;
--   DROP TABLE IF EXISTS signal_trajectory;
--   ALTER TABLE signal_scores_v01_archive RENAME TO signal_scores;
--   ALTER TABLE signal_trajectory_v01_archive RENAME TO signal_trajectory;
--   CREATE INDEX idx_signal_scores_user_time
--       ON signal_scores(user_id, scored_at DESC);
--   CREATE INDEX idx_trajectory_user_signal
--       ON signal_trajectory(user_id, signal_name, date DESC);
--   COMMIT;
-- =============================================================================
