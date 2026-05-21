"""
cron_consolidate.py — 每日跑一次（建议 03:30，紧跟 decay）。

把每个用户中反复出现的 episodic_memories（reinforcement_count >= 3）
通过 LLM 提炼为 user_semantic_profile.profile JSON。

Usage:
    python scripts/cron_consolidate.py

Crontab 示例（每天凌晨 3:30）：
    30 3 * * * cd /path/to/project && .venv/bin/python scripts/cron_consolidate.py
"""

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from backend.jobs import run_consolidate


def main() -> int:
    result = run_consolidate()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("errors", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
