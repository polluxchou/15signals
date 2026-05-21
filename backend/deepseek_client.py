"""
DeepSeek API client（OpenAI 兼容协议）。

为什么不直接复用 proxy.py？
- proxy.py 是无脑透传，不解析响应、不重试、不做 JSON 校验
- 这里需要 server 端调用 DeepSeek 拿结构化输出 → 用官方 SDK 更稳
"""

import json
import logging
import os
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)


class DeepSeekError(Exception):
    pass


def get_client() -> OpenAI:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise DeepSeekError("DEEPSEEK_API_KEY not set in environment")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    return OpenAI(api_key=api_key, base_url=base_url)


def get_model_scorer() -> str:
    return os.environ.get("DEEPSEEK_MODEL_SCORER", "deepseek-chat")


def get_model_mentor() -> str:
    return os.environ.get("DEEPSEEK_MODEL_MENTOR", "deepseek-chat")


def call_mentor_response(
    system_prompt: str,
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 600,
) -> str:
    """
    调 DeepSeek 生成导师回应（自由文本，非 JSON）。

    Args:
        system_prompt: build_mentor_response_system_prompt() 的输出
        messages: build_mentor_response_messages() 的输出（user/assistant 交替）
        temperature: 主对话用 0.6–0.8，比 summary 略高，允许文学性发挥
        max_tokens: 600 足够 3–6 句中文回应

    Returns:
        导师回应文本（已 strip）。
    """
    client = get_client()
    model = get_model_mentor()

    full_messages: list[dict] = [{"role": "system", "content": system_prompt}]
    full_messages.extend(messages)

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=full_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,  # P1 先不上 streaming，后续改 stream=True
        )
        text = (resp.choices[0].message.content or "").strip()
        if not text:
            raise DeepSeekError("DeepSeek returned empty response")
        return text
    except Exception as e:
        if isinstance(e, DeepSeekError):
            raise
        raise DeepSeekError(f"call_mentor_response failed: {type(e).__name__}: {e}") from e


def call_summary(system_prompt: str, user_message: str, max_retries: int = 2) -> dict[str, Any]:
    """
    调 DeepSeek 生成复盘 JSON。

    使用 response_format=json_object 强制 JSON 输出。
    DeepSeek 兼容 OpenAI 的此参数（仅对 deepseek-chat 模型生效）。
    """
    client = get_client()
    model = get_model_scorer()

    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.4,           # 略带文学性但保持稳定
                max_tokens=2000,
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content or ""
            data = json.loads(content)
            return data
        except json.JSONDecodeError as e:
            last_err = e
            logger.warning("DeepSeek returned non-JSON on attempt %d: %s", attempt + 1, content[:200])
        except Exception as e:
            last_err = e
            logger.warning("DeepSeek call failed on attempt %d: %s", attempt + 1, e)

    raise DeepSeekError(f"call_summary failed after {max_retries + 1} attempts: {last_err}")
