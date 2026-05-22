"""
P2 · 单轮信号评分（rubric-v0.2）。

在 /session/turn 处理完用户输入后，异步触发本模块给那条 user turn 打 15 维分。
写入 signal_scores 表。失败不阻塞主流程。
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

from .deepseek_client import DeepSeekError, get_client, get_model_scorer
from .signals_meta import SIGNALS, SIGNAL_NAMES

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# Prompt
# ─────────────────────────────────────────────────────────

def _build_scoring_system_prompt() -> str:
    """生成评分 system prompt——压缩版 rubric，每个信号一句定义。"""
    # 简化的 rubric：定义 + 0.5 锚点，足以让 LLM 校准
    rubric_lines = []
    one_line = {
        "cognitive_decay":         "深度思考能力退化，看不进书、想不清楚、'变笨'",
        "attention_scatter":       "无法专注，不断切换任务、刷新信息、手机不离手",
        "reality_blur":            "虚实混淆，真实感模糊，'像在演'、'像梦里'",
        "emotional_numbness":      "心像被茧包住，'没感觉'、'波澜不惊'，对他人痛苦也无动于衷",
        "burnout":                 "存在性疲劳，'活着累'、'起床都费劲'、不想做任何事",
        "anxiety_panic":           "弥散无对象的警报感，心慌、失眠、'总觉得有坏事要发生'",
        "meaning_loss":            "'为什么活'的答案丢失，认知层的虚无，'有什么意义'",
        "identity_lost":           "'哪个是真的我'，多重角色无内核，自我碎片",
        "existential_loneliness":  "存在论层的被遗弃感，'没人懂'、社交后更孤独",
        "relational_alienation":   "连接很多但都浅，关系商品化、表演化、'已读不回'",
        "community_collapse":      "原子化生存，没有'我们'，没有归属的整体",
        "bodily_alienation":       "把身体当工具/机器/数据，'我的身体'（强调距离）",
        "sensory_numbness":        "感官钝化，吃不出味、看不见自然、屏幕外没意思",
        "autonomy_loss":           "被推着走，'被卷'、'没办法'，选择不像真选择",
        "tech_alienation":         "技术反客为主，被算法/通知/推送主宰",
    }
    for name, dim, zh, _, _ in SIGNALS:
        rubric_lines.append(f"  - `{name}` ({zh}, {dim}): {one_line.get(name, '')}")

    return f"""你是 15 信号评分员（rubric-v0.2）。

对接下来给你的**一句**用户输入，按下面 15 个信号各给出 0.0–1.0 的强度分。

# 15 信号清单
{chr(10).join(rubric_lines)}

# 评分原则
- 0.0–0.2：未涉及 / 极弱
- 0.3–0.5：明确触及但不主导
- 0.6–0.8：清晰的主要主题
- 0.9–1.0：强烈且贯穿整句

# 对短输入的特别说明（**很重要**）
即使用户只说了几个字，**也不要把所有信号都打 0**。短句往往**情绪密度极高**：
- "今天又想到她了" → 关系异化 / 关系反复回到，至少 0.3-0.5
- "心里堵得很" → 焦虑恐慌 + 情感麻木的对抗，至少 0.3 起评
- "活着累" → 倦怠耗竭至少 0.6
- "没意思" → 意义丧失至少 0.4

**判断方法**：把这句话放进它可能的最大语境里——
如果一个人**只说出了这一句**就停了，他到底在说什么？哪 2-3 个信号最相关？
给那 2-3 个信号合理的非零分（0.3-0.6），其他保持 0。

不要因为信息不全就一律打 0——零分意味着"完全未涉及"，而短句通常是某种**强烈情绪的浓缩**。

# 输出
只输出 JSON。15 个字段必须齐全，每个 [0.0, 1.0]。例：
{{"cognitive_decay": 0.0, "attention_scatter": 0.3, "reality_blur": 0.0, ...全部 15 ...}}"""


_SCORING_SYSTEM_PROMPT_CACHE: str | None = None
_SCORING_PROMPT_VERSION = "v0.2.1"  # 改 prompt 时 bump，缓存失效

def get_scoring_system_prompt() -> str:
    global _SCORING_SYSTEM_PROMPT_CACHE
    if _SCORING_SYSTEM_PROMPT_CACHE is None:
        _SCORING_SYSTEM_PROMPT_CACHE = _build_scoring_system_prompt()
    return _SCORING_SYSTEM_PROMPT_CACHE


# ─────────────────────────────────────────────────────────
# DeepSeek call
# ─────────────────────────────────────────────────────────

def call_signal_scoring(user_text: str, max_retries: int = 2) -> dict[str, float]:
    """调 DeepSeek 给一段用户文字打 15 维分。返回 {signal_name: float}。"""
    client = get_client()
    model = get_model_scorer()
    sys_prompt = get_scoring_system_prompt()

    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_text},
                ],
                temperature=0.1,  # 信号评分需要一致性
                max_tokens=400,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or "{}"
            data = json.loads(raw)
            # 归一化
            out: dict[str, float] = {}
            for name in SIGNAL_NAMES:
                v = data.get(name, 0.0)
                try:
                    f = float(v)
                except (TypeError, ValueError):
                    f = 0.0
                out[name] = max(0.0, min(1.0, f))
            return out
        except Exception as e:
            last_err = e
            logger.warning("call_signal_scoring attempt %d failed: %s", attempt + 1, e)

    raise DeepSeekError(f"call_signal_scoring failed after {max_retries + 1}: {last_err}")


# ─────────────────────────────────────────────────────────
# DB
# ─────────────────────────────────────────────────────────

@contextmanager
def _conn() -> Iterator[Any]:
    import psycopg
    url = os.environ["DATABASE_URL"]
    conn = psycopg.connect(url, autocommit=False)
    try:
        yield conn
    finally:
        conn.close()


SCORER_VERSION = "rubric-v0.2"


def persist_signal_scores(turn_id: int, user_id: int, scores: dict[str, float]) -> None:
    """把 15 维分写入 signal_scores。一行一个 turn。"""
    cols = SIGNAL_NAMES
    values = [scores.get(c, 0.0) for c in cols]
    placeholders = ", ".join(["%s"] * (len(cols) + 4))   # +4: turn_id, user_id, scorer_model, scorer_version
    col_list = ", ".join(cols)

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO signal_scores (
                    turn_id, user_id,
                    {col_list},
                    scorer_model, scorer_version
                ) VALUES (
                    %s, %s,
                    {", ".join(["%s"] * len(cols))},
                    %s, %s
                )
                ON CONFLICT (turn_id) DO NOTHING
                """,
                [turn_id, user_id] + values + [
                    get_model_scorer(), SCORER_VERSION,
                ],
            )
            conn.commit()


# ─────────────────────────────────────────────────────────
# 顶层任务函数（供 FastAPI BackgroundTasks 调用）
# ─────────────────────────────────────────────────────────

def score_and_persist_turn(turn_id: int, user_id: int, user_text: str) -> None:
    """供后台任务调用：评分 + 入库，失败只记日志不抛。"""
    try:
        scores = call_signal_scoring(user_text)
        persist_signal_scores(turn_id, user_id, scores)
        # 简单 log 一下 top 3 信号，便于人肉观察
        top3 = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
        top3_str = ", ".join(f"{k}={v:.2f}" for k, v in top3)
        logger.info("scored turn %d (user=%d): top3 → %s", turn_id, user_id, top3_str)
    except Exception as e:
        logger.exception("score_and_persist_turn failed for turn=%d: %s", turn_id, e)
