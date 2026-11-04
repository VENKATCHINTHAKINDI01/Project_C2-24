"""Metric definitions (plan §13.2). Pure functions; binary relevance; ranking = the ladder's own
order (rung order, then graph hits). Precision@k divides by k, the standard definition."""

from __future__ import annotations

import math
from collections.abc import Sequence


def recall_at(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    return len(set(ranked[:k]) & relevant) / len(relevant) if relevant else 1.0


def precision_at(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    return len(set(ranked[:k]) & relevant) / k


def reciprocal_rank(ranked: Sequence[str], relevant: set[str]) -> float:
    return next((1 / i for i, d in enumerate(ranked, 1) if d in relevant), 0.0)


def ndcg_at(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    dcg = sum(1 / math.log2(i + 1) for i, d in enumerate(ranked[:k], 1) if d in relevant)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 1.0


def prf(tp: int, fp: int, fn: int) -> dict[str, float | None]:
    """Precision / recall / F1; None where undefined (nothing predicted / nothing expected)."""
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p is not None and r is not None and p + r else None
    return {"precision": p, "recall": r, "f1": f}


def mean(xs: Sequence[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None
