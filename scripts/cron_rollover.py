"""
cron_rollover.py — 每小时跑一次。

找出所有"用户本地时间已过 8:00 且 session 跨日"的 active session，
强制关闭 + 生成 summary + 抽取记忆。

Usage:
    python scripts/cron_rollover.py [--dry-run] [--grace-minutes N]

Crontab 示例（每小时 5 分跑）：
    5 * * * * cd /path/to/project && .venv/bin/python scripts/cron_rollover.py
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# 项目根加入 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from backend.jobs import run_rollover


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="只扫描不关闭")
    p.add_argument("--grace-minutes", type=int, default=5, help="距 last_active_at 的宽限分钟数（默认 5）")
    args = p.parse_args()

    result = run_rollover(grace_minutes=args.grace_minutes, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("errors", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
