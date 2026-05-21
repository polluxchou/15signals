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
