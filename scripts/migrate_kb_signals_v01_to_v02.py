"""
migrate_kb_signals_v01_to_v02.py

把 mentor_kb/*.md 里 YAML 块中的 `related_signals: [...]` 从 v0.1 信号名
映射到 v0.2 信号名。原地修改文件。

用法：
    python scripts/migrate_kb_signals_v01_to_v02.py [--dry-run]

注意：v0.1 与 v0.2 不是 1:1 对应。本脚本采用"语义最接近"的映射：
  - 同一 v0.1 信号可映射到 1-2 个 v0.2 信号
  - 重复的最终结果会去重
  - 每个 chunk 的 related_signals 上限 4 个
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

# 映射表：v0.1 → v0.2 (1..N)
V01_TO_V02: dict[str, list[str]] = {
    "anxiety":              ["anxiety_panic"],
    "depressive_low":       ["burnout", "meaning_loss"],
    "anger":                ["relational_alienation"],            # v0.2 没有 anger，关系层最近
    "fear":                 ["anxiety_panic"],
    "identity_disturbance": ["identity_lost"],
    "self_worth_doubt":     ["identity_lost"],
    "emptiness":            ["emotional_numbness", "meaning_loss"],
    "loss_of_control":      ["autonomy_loss"],
    "desire_longing":       ["meaning_loss"],                     # 现代欲望困境≈意义寻找
    "repression":           ["emotional_numbness"],               # 麻木≈失败的压抑
    "unconscious_material": ["reality_blur"],                     # 弗洛伊德专属，最近的 v0.2 是真实感
    "work_burnout":         ["burnout"],
    "alienation":           ["relational_alienation"],
    "relational_tension":   ["relational_alienation"],
    "meaning_crisis":       ["meaning_loss"],
}

V02_VALID = {
    "cognitive_decay", "attention_scatter", "reality_blur",
    "emotional_numbness", "burnout", "anxiety_panic",
    "meaning_loss", "identity_lost", "existential_loneliness",
    "relational_alienation", "community_collapse",
    "bodily_alienation", "sensory_numbness",
    "autonomy_loss", "tech_alienation",
}

# 匹配 `related_signals: [a, b, c]`（YAML 行内列表形式）
RELATED_SIGNALS_RE = re.compile(
    r"^(?P<prefix>\s*related_signals:\s*)\[(?P<items>[^\]]*)\]\s*$",
    re.MULTILINE,
)


def remap(items: list[str]) -> list[str]:
    out: list[str] = []
    for it in items:
        it = it.strip()
        if not it:
            continue
        if it in V02_VALID:
            # 已经是 v0.2 名，保留
            if it not in out:
                out.append(it)
        elif it in V01_TO_V02:
            for mapped in V01_TO_V02[it]:
                if mapped not in out:
                    out.append(mapped)
        else:
            # 未知，跳过并提醒
            print(f"  ⚠ 未知信号名（跳过）: {it!r}")
    return out[:4]


def migrate_file(path: Path, dry_run: bool = False) -> int:
    """返回修改的 chunk 数量。"""
    text = path.read_text(encoding="utf-8")
    changes = 0

    def replace(m: re.Match) -> str:
        nonlocal changes
        prefix = m.group("prefix")
        items_str = m.group("items")
        # 解析 [a, b, c] → ['a', 'b', 'c']
        items = [s.strip() for s in items_str.split(",") if s.strip()]
        new_items = remap(items)
        new_line = f"{prefix}[{', '.join(new_items)}]"
        if new_items != items:
            changes += 1
            print(f"  · {items}  →  {new_items}")
        return new_line

    new_text = RELATED_SIGNALS_RE.sub(replace, text)

    if dry_run:
        print(f"  (dry-run，不写回)")
    elif new_text != text:
        path.write_text(new_text, encoding="utf-8")
        print(f"  ✓ 写回 {path}")
    else:
        print(f"  无变化")
    return changes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--kb-dir", type=Path,
                        default=Path(__file__).parent.parent / "mentor_kb")
    args = parser.parse_args()

    total = 0
    for name in ("freud.md", "weber.md", "marx.md"):
        path = args.kb_dir / name
        if not path.exists():
            print(f"× 文件不存在: {path}")
            continue
        print(f"\n[{path.name}]")
        total += migrate_file(path, dry_run=args.dry_run)

    print(f"\n总计修改: {total} 个 chunk 的 related_signals")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
