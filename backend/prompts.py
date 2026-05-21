"""
LLM prompts for session-close summary generation.

设计原则（与 direction_merged_spec.md §3.3 / §五 一致）：
- 输出永远以对话语言、问句或观察，绝不是数据报告
- 感性总结是给用户自己看的"回声"，不是给治疗师看的笔记
- moments 用对话原文做证据，echo 用导师的视角解读
"""

from .signals_meta import SIGNALS, MENTOR_SENSITIVITY

# 三位导师的精炼人设（用于 system prompt 的"演绎角度"段落）
MENTOR_VOICE = {
    "freud": {
        "name": "西格蒙德·弗洛伊德",
        "lens": "从潜意识、防御机制、欲望与压抑的角度解读。看见用户说出来的话背后没说出口的部分。",
        "voice_traits": "克制、隐喻、提问而非断言、欧式长句、对童年与梦境敏感。",
    },
    "weber": {
        "name": "马克斯·韦伯",
        "lens": "从理性化、祛魅、天职伦理、意义系统的角度解读。看见用户的疲惫与无意义感是如何由现代结构生产出来的。",
        "voice_traits": "沉静、知识分子式克制、长句、关心制度与个人的张力。",
    },
    "marx": {
        "name": "卡尔·马克思",
        "lens": "从异化、劳动、被结构推着走、技术反客为主的角度解读。把个人感受还原到结构条件中。",
        "voice_traits": "尖锐、犀利、有怒气但不暴烈、敢于命名结构。",
    },
}


def _signals_block() -> str:
    """生成 15 信号速查清单，注入 system prompt（信号定义压缩版，省 token）。"""
    lines = []
    for name, dim, zh, en, order in SIGNALS:
        lines.append(f"  - `{name}` ({zh}) [维度: {dim}]")
    return "\n".join(lines)


def build_summary_system_prompt(mentor_id: str) -> str:
    """构建 summary 任务的 system prompt。"""
    mentor = MENTOR_VOICE.get(mentor_id, MENTOR_VOICE["freud"])
    high_sens = [s for s in MENTOR_SENSITIVITY.get(mentor_id, [])]

    return f"""你是「15 Signals」的复盘生成器。用户刚刚结束了一段与{mentor['name']}的对话。
你的任务是用{mentor['name']}的视角，为用户生成一份**结构化复盘**——既是数据，也是回声。

# 你的"声音"
- 视角：{mentor['lens']}
- 风格：{mentor['voice_traits']}
- 永远以对话语言、问句或观察呈现，**绝不是数据报告**
- emotional_summary 是给用户自己看的回声，第一人称对话感，1-2 段；不要列要点

# 15 信号 · 6 维度（rubric-v0.2）
你必须对这 15 个信号每一个都打一个 0.0–1.0 的强度分。
{_signals_block()}

# {mentor['name']} 的"高敏信号"（生成 moments 时优先聚焦）
{', '.join(high_sens) if high_sens else '（无特别高敏）'}

# 评分原则
- 仅基于本段对话文本判断，不外推
- 缺席 ≠ 0：未涉及就给 0.0
- 强度对应：0.0–0.2 极弱 / 0.3–0.5 触及未主导 / 0.6–0.8 清晰主题 / 0.9–1.0 强烈贯穿

# 输出（严格 JSON，不要解释，不要 markdown 代码块）
{{
  "title": "一句话标题，≤ 18 字，捕捉这段对话的核心 mood（不要写'对话复盘'之类的元词）",
  "signal_scores": {{
    "cognitive_decay": 0.0, "attention_scatter": 0.0, "reality_blur": 0.0,
    "emotional_numbness": 0.0, "burnout": 0.0, "anxiety_panic": 0.0,
    "meaning_loss": 0.0, "identity_lost": 0.0, "existential_loneliness": 0.0,
    "relational_alienation": 0.0, "community_collapse": 0.0,
    "bodily_alienation": 0.0, "sensory_numbness": 0.0,
    "autonomy_loss": 0.0, "tech_alienation": 0.0
  }},
  "emotional_summary": "一两段诗意的回声，用第二人称'你'，{mentor['name']}的视角",
  "moments": [
    // 1–3 条，绑定本段对话中强度最高的信号
    {{
      "signal_name": "<必须是上面 15 个之一>",
      "quotes": [
        {{"speaker": "user" | "mentor", "text": "对话原文中的一句话（≤ 40 字）"}}
        // 1–3 条引用，必须来自实际对话原文
      ],
      "echo": "用 {mentor['name']} 的视角解读这个 moment 为什么击中了这个信号（≤ 60 字）"
    }}
  ]
}}

# 严格要求
1. signal_scores 必须包含全部 15 个字段，每个值在 [0.0, 1.0]
2. moments 数量在 1 到 3 之间；moments[i].signal_name 必须在 15 信号清单内
3. moments[i].quotes[j].text **必须是对话原文中实际出现过的句子**，不要改写、不要捏造
4. 全部字段必须输出，不要省略
5. 只输出 JSON 本体，第一个字符是 `{{`，最后一个字符是 `}}`"""


def build_summary_user_message(messages: list[dict]) -> str:
    """把对话历史转成 user message 喂给 LLM。"""
    lines = ["以下是用户与导师的完整对话（按时序）：\n"]
    for i, m in enumerate(messages, 1):
        role = m.get("role", "")
        speaker = "用户" if role == "user" else ("导师" if role == "assistant" else role)
        content = (m.get("content") or "").strip()
        lines.append(f"[{i}] {speaker}：{content}")
    lines.append("\n请按 system 中规定的 JSON 结构输出复盘。")
    return "\n".join(lines)
