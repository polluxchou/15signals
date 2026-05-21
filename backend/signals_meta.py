"""
15 信号 + 6 维度元数据。与 signals_rubric.md v0.2 和 schema 的 signal_meta 表对齐。

保留在 Python 里而不是只查 DB，原因：
1. 复盘端点不强制要求 DB 连接（无 DATABASE_URL 时仍可工作）
2. 前端拿到响应后能用 signal_name 直接显示中文名，不需要二次查询
"""

# 6 维度 × 15 信号
DIMENSIONS = ["cognitive", "emotional", "existential", "relational", "embodied", "autonomy_tech"]

SIGNALS = [
    # (signal_name, dimension, display_zh, display_en, sort_order)
    ("cognitive_decay",        "cognitive",     "认知退化",     "Cognitive Decay",         1),
    ("attention_scatter",      "cognitive",     "注意力涣散",   "Attention Scatter",       2),
    ("reality_blur",           "cognitive",     "真实感模糊",   "Reality Blur",            3),
    ("emotional_numbness",     "emotional",     "情感麻木",     "Emotional Numbness",      4),
    ("burnout",                "emotional",     "倦怠耗竭",     "Burnout",                 5),
    ("anxiety_panic",          "emotional",     "焦虑恐慌",     "Anxiety / Panic",         6),
    ("meaning_loss",           "existential",   "意义丧失",     "Meaning Loss",            7),
    ("identity_lost",          "existential",   "身份迷失",     "Identity Lost",           8),
    ("existential_loneliness", "existential",   "存在性孤独",   "Existential Loneliness",  9),
    ("relational_alienation",  "relational",    "关系异化",     "Relational Alienation",  10),
    ("community_collapse",     "relational",    "共同体瓦解",   "Community Collapse",     11),
    ("bodily_alienation",      "embodied",      "身体异化",     "Bodily Alienation",      12),
    ("sensory_numbness",       "embodied",      "感知钝化",     "Sensory Numbness",       13),
    ("autonomy_loss",          "autonomy_tech", "自主性丧失",   "Autonomy Loss",          14),
    ("tech_alienation",        "autonomy_tech", "技术异化",     "Tech Alienation",        15),
]

SIGNAL_NAMES = [s[0] for s in SIGNALS]

# 维度 → [signal_name...] （聚合时用）
DIMENSION_TO_SIGNALS: dict[str, list[str]] = {d: [] for d in DIMENSIONS}
for name, dim, _, _, _ in SIGNALS:
    DIMENSION_TO_SIGNALS[dim].append(name)

# signal_name → 元数据 dict
SIGNAL_META: dict[str, dict] = {
    name: {
        "signal_name": name,
        "dimension": dim,
        "display_name_zh": zh,
        "display_name_en": en,
        "sort_order": order,
    }
    for name, dim, zh, en, order in SIGNALS
}

# Mentor × 信号 高敏度对照（与 signals_rubric.md 末尾表对齐）
MENTOR_SENSITIVITY: dict[str, list[str]] = {
    "freud": [
        "attention_scatter", "emotional_numbness", "anxiety_panic",
        "identity_lost", "existential_loneliness",
        "relational_alienation", "bodily_alienation", "sensory_numbness",
    ],
    "weber": [
        "cognitive_decay", "reality_blur", "burnout",
        "meaning_loss", "identity_lost", "existential_loneliness",
        "community_collapse", "autonomy_loss", "tech_alienation",
    ],
    "marx": [
        "cognitive_decay", "attention_scatter", "emotional_numbness", "burnout",
        "meaning_loss", "relational_alienation", "community_collapse",
        "bodily_alienation", "autonomy_loss", "tech_alienation",
    ],
}
