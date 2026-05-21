"""
从 LLM 输出的 signal_scores（15 个 0-1 浮点）聚合出：
- 6 维度均值
- 整体强度 0-100 整数
- Top 1-3 信号（强度 ≥ 0.4 才入选）
"""

from .signals_meta import DIMENSION_TO_SIGNALS, SIGNAL_META


def aggregate_dimensions(signal_scores: dict[str, float]) -> dict[str, float]:
    """6 维度均值，结果保留 3 位小数。"""
    out = {}
    for dim, names in DIMENSION_TO_SIGNALS.items():
        vals = [signal_scores.get(n, 0.0) for n in names]
        out[dim] = round(sum(vals) / len(vals), 3) if vals else 0.0
    return out


def overall_intensity(signal_scores: dict[str, float]) -> int:
    """全部 15 信号均值 × 100，结果 0–100 整数。"""
    if not signal_scores:
        return 0
    avg = sum(signal_scores.values()) / len(signal_scores)
    return int(round(avg * 100))


def top_signals(
    signal_scores: dict[str, float],
    threshold: float = 0.4,
    limit: int = 3,
) -> list[dict]:
    """
    取强度最高的 1–3 个信号（强度 ≥ threshold 才入选）。
    返回 [{signal_name, intensity, dimension, display_name_zh, display_name_en}, ...]
    若没有任何信号 ≥ threshold，仍返回 Top 1（确保至少有 1 个）——
    因为复盘界面如果什么都不显示会很突兀。
    """
    items = sorted(signal_scores.items(), key=lambda kv: kv[1], reverse=True)
    qualified = [(n, v) for n, v in items if v >= threshold][:limit]
    if not qualified and items:
        qualified = [items[0]]
    out = []
    for name, intensity in qualified:
        meta = SIGNAL_META.get(name, {})
        out.append({
            "signal_name": name,
            "intensity": round(float(intensity), 3),
            "dimension": meta.get("dimension"),
            "display_name_zh": meta.get("display_name_zh"),
            "display_name_en": meta.get("display_name_en"),
        })
    return out
