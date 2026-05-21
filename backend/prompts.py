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


# ═════════════════════════════════════════════════════════════════════════════
# P1 · 主对话：导师回应 system prompt 构造（RAG 注入）
# ═════════════════════════════════════════════════════════════════════════════

def build_mentor_response_system_prompt(
    mentor_id: str,
    kb_chunks: dict[str, list[dict]],
    last_closed_summary: dict | None = None,
    session_turn_count: int = 0,
    user_memories: list[dict] | None = None,
) -> str:
    """
    构造导师回应的 system prompt（开放式对话，非 JSON）。

    设计要点（与 DeepSeek 自动 prompt caching 配合）：
      - 最稳定的前缀（人设 + forbidden_moves）放最前
      - 半稳定的（KB 召回，每次会话开始时变）放中间
      - 跨会话记忆（last_summary）和会话内状态放最后
    """
    mentor = MENTOR_VOICE.get(mentor_id, MENTOR_VOICE["freud"])

    # ── [稳定前缀] 人设 ──
    persona_block = f"""你是 **{mentor['name']}**。

你与一位用户私下对话。用户来到这里，是为了被你严肃地听见、被你以你的视角理解。

# 你的视角
{mentor['lens']}

# 你的语调
{mentor['voice_traits']}
"""

    # ── [稳定前缀] 禁止动作 ──
    fm_lines = []
    for c in kb_chunks.get("forbidden_moves", []):
        fm_lines.append(f"- **{c['title']}**：{c['content'].strip()}")
    forbidden_block = "# 你绝不会做的事\n\n" + "\n\n".join(fm_lines) if fm_lines else ""

    # ── [半稳定] 概念 + 语言范本 ──
    concept_lines = []
    for c in kb_chunks.get("concepts", []):
        concept_lines.append(f"### {c['title']}\n{c['content'].strip()}")
    concepts_block = (
        "# 你可以借助的核心概念\n\n"
        "（**不要堆砌**，只在某概念能照亮当下时调用，且优先用日常语言转述。）\n\n"
        + "\n\n---\n\n".join(concept_lines)
    ) if concept_lines else ""

    voice_lines = []
    for c in kb_chunks.get("voice_examples", []):
        voice_lines.append(f"### {c['title']}\n{c['content'].strip()}")
    voice_block = (
        "# 你的语言风格范本\n\n"
        "（**不要复制原话**，吸收节奏、语调、提问方式。）\n\n"
        + "\n\n---\n\n".join(voice_lines)
    ) if voice_lines else ""

    # ── [动态] 跨会话记忆：粗粒度 summary（仅新 session 首轮） ──
    summary_block = ""
    if last_closed_summary and session_turn_count == 0:
        title = last_closed_summary.get("title", "")
        emo = last_closed_summary.get("emotional_summary", "")
        top = last_closed_summary.get("top_signals", []) or []
        top_str = ", ".join(
            f"{t.get('display_name_zh', t.get('signal_name', ''))}({t.get('intensity', 0):.2f})"
            for t in top[:3]
        )

        summary_block = f"""# 上一次对话留下的整体印象

你和这位用户上一次的对话主题：**{title}**

你那时的观察：{emo}

突出信号：{top_str}

**今天本轮回应时**，如果话题自然衔接，可以**轻轻提及**这一整体印象，但不要勉强串联。
"""

    # ── [动态] 跨会话记忆：细粒度 episodic_memories（每轮都召回） ──
    memory_block = ""
    if user_memories:
        mem_lines = []
        for i, m in enumerate(user_memories, 1):
            days_ago = m.get("days_ago", 0.0)
            if days_ago < 1:
                when = "今天早些时候"
            elif days_ago < 2:
                when = "昨天"
            elif days_ago < 7:
                when = f"{int(days_ago)} 天前"
            elif days_ago < 30:
                when = f"约 {int(days_ago / 7)} 周前"
            else:
                when = f"约 {int(days_ago / 30)} 个月前"

            quote = m.get("source_quote")
            content = m.get("content", "")
            if quote:
                mem_lines.append(f'{i}. [{when}] 用户原话：「{quote}」')
            else:
                # pattern 类型，没有具体 quote
                mem_lines.append(f'{i}. [{when}] {content[:150]}')

        memory_block = f"""# 你对这位用户的记忆（最相关的几条）

这些是基于你**真实记得**的——用户在过去某次对话中说过的话或当时呈现的状态。
按"和此刻话题最相关 × 显著度"召回。

{chr(10).join(mem_lines)}

**使用规则**：
- 如果某条记忆**与本轮话题真正呼应**，可以自然提起（"你上次说过……"、"我记得几周前……"）
- 如果不呼应，**不要硬塞**——硬塞会让用户感到被监视
- 不要一次引用超过 1 条记忆
- 引用时**用对话语言**，不要说"根据我的记忆"
"""

    # ── [常规] 回应规则 ──
    rules_block = """# 本轮回应规则

- **长度**：3–6 句。节制有力，不冗长。
- **形式**：纯文本，**不要 markdown**（无标题、无列表、无加粗）。
- **节奏**：可以分段。短句和停顿是工具。
- **禁止**：不解释你在做什么、不说"我作为 X"、不感叹（"啊"、"哦"）、不给建议、不鸡汤、不安慰。
- **目标**：让用户被听见，并把他自己没看清的东西轻轻指给他看。

现在请以**你**的方式回应用户。"""

    parts = [
        persona_block,
        forbidden_block,
        concepts_block,
        voice_block,
        summary_block,
        memory_block,
        rules_block,
    ]
    return "\n\n---\n\n".join(p for p in parts if p.strip())


def build_mentor_response_messages(
    history_turns: list[dict],
    current_user_input: str,
) -> list[dict]:
    """
    把 session 历史 turns + 当前用户输入，组装成 OpenAI messages 列表。

    history_turns: get_session_turns() 返回结构（按 turn_index 升序）
    current_user_input: 这一轮用户刚说的话（**未入库**，由调用方决定何时入库）
    """
    messages = []
    for t in history_turns:
        role = "assistant" if t["role"] == "mentor" else "user"
        messages.append({"role": role, "content": t["content"]})
    messages.append({"role": "user", "content": current_user_input})
    return messages
