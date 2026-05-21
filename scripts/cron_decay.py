"""
cron_decay.py — 每日跑一次（建议 03:00）。

给所有"超过 grace_days 没被强化的记忆"应用乘法衰减。

Usage:
    python scripts/cron_decay.py [--grace-days N] [--daily-decay F] [--floor F]

Crontab 示例（每天凌晨 3 点）：
    0 3 * * * cd /path/to/project && .venv/bin/python scripts/cron_decay.py
"""

import argparse
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

from backend.jobs import run_decay


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--grace-days", type=int, default=7, help="多少天没被强化才开始衰减（默认 7）")
    p.add_argument("--daily-decay", type=float, default=0.95, help="每次衰减乘数（默认 0.95）")
    p.add_argument("--floor", type=float, default=0.05, help="低于此值视为退出主检索池")
    args = p.parse_args()

    result = run_decay(
        grace_days=args.grace_days,
        daily_decay=args.daily_decay,
        soft_floor=args.floor,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
