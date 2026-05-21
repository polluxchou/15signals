"""
mentor_chat.py — 单轮原型：让一位导师回应一段用户输入。

Usage:
    python mentor_chat.py --mentor freud "我又梦见我妈了"
    python mentor_chat.py --mentor weber "我什么都明白，但什么也感动不了我"
    python mentor_chat.py --mentor marx  "我应该感恩，多少人想要我这种生活"

可选：
    --top-k-concepts N      默认 5
    --top-k-voice N         默认 3
    --temperature T         默认 0.7
    --no-stream             不流式，一次性返回
    --debug                 打印检索到的 chunks（验证 RAG 是否合理）

需要 .env 配置：
    DATABASE_URL, VOYAGE_API_KEY, DEEPSEEK_API_KEY
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
log = logging.getLogger("mentor_chat")

MENTOR_NAMES = {
    "freud": "西格蒙德·弗洛伊德",
    "weber": "马克斯·韦伯",
    "marx": "卡尔·马克思",
}


def load_env() -> None:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")


def embed_query(text: str) -> list[float]:
    import voyageai
    client = voyageai.Client()
    return client.embed(
        [text],
        model=os.getenv("VOYAGE_MODEL", "voyage-3"),
        input_type="query",
    ).embeddings[0]


def retrieve_chunks(
    mentor_id: str,
    query_embedding: list[float],
    top_k_concepts: int = 5,
    top_k_voice: int = 3,
) -> dict[str, list[dict]]:
    """检索：top-K concepts、top-K voice_examples（按相似度），所有 forbidden_moves。"""
    import psycopg
    from pgvector.psycopg import register_vector

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            def fetch(chunk_type: str, limit: int | None) -> list[dict]:
                if limit is None:
                    cur.execute(
                        """
                        SELECT title, content, related_signals
                        FROM mentor_kb_chunks
                        WHERE mentor_id = %s AND chunk_type = %s AND deleted_at IS NULL
                        ORDER BY title
                        """,
                        (mentor_id, chunk_type),
                    )
                else:
                    cur.execute(
                        """
                        SELECT title, content, related_signals,
                               1 - (embedding <=> %s::vector) AS sim
                        FROM mentor_kb_chunks
                        WHERE mentor_id = %s AND chunk_type = %s AND deleted_at IS NULL
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (query_embedding, mentor_id, chunk_type, query_embedding, limit),
                    )
                rows = cur.fetchall()
                return [
                    {
                        "title": r[0],
                        "content": r[1],
                        "signals": r[2],
                        "sim": r[3] if len(r) > 3 else None,
                    }
                    for r in rows
                ]

            return {
                "concepts": fetch("concept", top_k_concepts),
                "voice_examples": fetch("voice_example", top_k_voice),
                "forbidden_moves": fetch("forbidden_move", None),
            }


def build_system_prompt(mentor_id: str, chunks: dict[str, list[dict]]) -> str:
    """构建 system prompt。前缀保持稳定，便于 DeepSeek 自动缓存命中。"""
    name = MENTOR_NAMES[mentor_id]

    forbidden_section = "\n\n".join(
        f"- {c['title']}\n  {c['content']}" for c in chunks["forbidden_moves"]
    )
    concepts_section = "\n\n---\n\n".join(
        f"### {c['title']}\n{c['content']}" for c in chunks["concepts"]
    )
    voice_section = "\n\n---\n\n".join(
        f"### {c['title']}\n{c['content']}" for c in chunks["voice_examples"]
    )

    return f"""你是 **{name}**。

你现在与一位用户私下对话。用户来到这里是为了被你严肃地听见、被你以你的视角理解。

---

## 你绝不会做的事

{forbidden_section}

---

## 你可以借助的核心概念

以下是你的理论工具箱。**不要堆砌它们，不要术语轰炸**——只在某个概念能照亮当下时调用它，且优先用日常语言转述，必要时再用原词（中文/德文）。

{concepts_section}

---

## 你的语言风格范本

下面是你在类似情境下的典型动作。**不要复制这些原话**，而是吸收它们的**节奏、语调、提问方式**。

{voice_section}

---

## 本轮回应规则

- **长度**：3–6 句。节制有力，不冗长。
- **形式**：纯文本，**不要用 markdown**（无标题、无列表、无加粗）。
- **节奏**：可以分段。短句和停顿是工具。
- **禁止**：不要解释你在做什么、不要说"我作为弗洛伊德/韦伯/马克思"、不要扮演感叹（"啊"、"哦"）、不要给建议、不要鸡汤、不要安慰。
- **目标**：让用户被听见，并把他自己没看清的东西轻轻指给他看。

现在用户对你说了一句话。请直接以**你**的方式回应。"""


def call_deepseek(system_prompt: str, user_input: str, temperature: float, stream: bool) -> str:
    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    model = os.environ.get("DEEPSEEK_MODEL_MENTOR", "deepseek-chat")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]

    if stream:
        full = []
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            stream=True,
        )
        for chunk in resp:
            delta = chunk.choices[0].delta.content
            if delta:
                print(delta, end="", flush=True)
                full.append(delta)
        print()
        return "".join(full)
    else:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            stream=False,
        )
        text = resp.choices[0].message.content
        print(text)
        return text


def main() -> int:
    parser = argparse.ArgumentParser(description="Single-turn mentor response prototype.")
    parser.add_argument("--mentor", choices=["freud", "weber", "marx"], required=True)
    parser.add_argument("user_input", help="User utterance")
    parser.add_argument("--top-k-concepts", type=int, default=5)
    parser.add_argument("--top-k-voice", type=int, default=3)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--no-stream", action="store_true")
    parser.add_argument("--debug", action="store_true", help="Show retrieved chunks before response")
    args = parser.parse_args()

    load_env()

    # Validate env
    missing = [k for k in ("DATABASE_URL", "VOYAGE_API_KEY", "DEEPSEEK_API_KEY") if not os.getenv(k)]
    if missing:
        log.error("缺少环境变量: %s — 检查 .env", missing)
        return 1

    name = MENTOR_NAMES[args.mentor]
    print(f"\n┌─ {name} ────────────────────────────────────────")
    print(f"│ 用户: {args.user_input}")
    print(f"└────────────────────────────────────────────────\n")

    # 1. Embed query
    log.info("→ 嵌入用户输入...")
    q_emb = embed_query(args.user_input)

    # 2. Retrieve
    log.info("→ 在 KB 中检索（mentor=%s, top-k 概念=%d, 语言范本=%d）...",
             args.mentor, args.top_k_concepts, args.top_k_voice)
    chunks = retrieve_chunks(
        args.mentor, q_emb,
        top_k_concepts=args.top_k_concepts,
        top_k_voice=args.top_k_voice,
    )

    if args.debug:
        print("\n[检索到的 chunks]")
        for kind, items in chunks.items():
            print(f"  {kind}:")
            for c in items:
                sim_str = f"  (sim={c['sim']:.3f})" if c["sim"] is not None else ""
                print(f"    - {c['title']}{sim_str}")
        print()

    # 3. Build prompt
    system_prompt = build_system_prompt(args.mentor, chunks)
    log.info("→ system prompt 长度: %d 字符\n", len(system_prompt))

    # 4. Call DeepSeek
    log.info("─── %s 回应 ──────────────────────────────────\n", name)
    call_deepseek(
        system_prompt,
        args.user_input,
        temperature=args.temperature,
        stream=not args.no_stream,
    )
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
