"""检索指标：IR 标准口径的最小实现，全部可单测。

定义：
- relevance grade: 2 = 直接回答查询，1 = 相关但部分，0 = 不相关
- P@k       : 前 k 条中 grade>=1 的比例
- Recall@k  : 前 k 条覆盖了多少比例的 grade>=1 目标
- MRR@k     : 第一个 grade>=2 的排名倒数
- nDCG@k    : 增益 2^g - 1，折损 1/log2(i+1)，按理想排序归一
- bootstrap : 对查询做有放回重采样，给出均值差的 95% 区间（不假设正态）
"""

from __future__ import annotations

import math
import random
from typing import Dict, Iterable, List, Optional, Sequence


def precision_at_k(ranked: Sequence[str], rel: Dict[str, int], k: int) -> float:
    top = ranked[:k]
    if not top:
        return 0.0
    return sum(1 for d in top if rel.get(d, 0) >= 1) / len(top)


def recall_at_k(ranked: Sequence[str], rel: Dict[str, int], k: int) -> float:
    targets = {d for d, g in rel.items() if g >= 1}
    if not targets:
        return float("nan")
    got = {d for d in ranked[:k] if d in targets}
    return len(got) / len(targets)


def mrr_at_k(ranked: Sequence[str], rel: Dict[str, int], k: int) -> float:
    for i, doc in enumerate(ranked[:k], start=1):
        if rel.get(doc, 0) >= 2:
            return 1.0 / i
    return 0.0


def _dcg(gains: Sequence[float]) -> float:
    return sum((2 ** g - 1) / math.log2(i + 1) for i, g in enumerate(gains, start=1))


def ndcg_at_k(ranked: Sequence[str], rel: Dict[str, int], k: int) -> float:
    gains = [rel.get(d, 0) for d in ranked[:k]]
    ideal = sorted(rel.values(), reverse=True)[:k]
    idcg = _dcg(ideal)
    if idcg == 0:
        return float("nan")
    return _dcg(gains) / idcg


def category_purity(ranked_docs: Sequence[dict], expected_topic: str, k: int) -> float:
    top = ranked_docs[:k]
    if not top:
        return 0.0
    return sum(1 for d in top if d.get("topic") == expected_topic) / len(top)


def bootstrap_diff(a: Sequence[float], b: Sequence[float], *, iters: int = 2000,
                   seed: int = 7) -> Dict[str, float]:
    """配对 bootstrap：a 与 b 是同一批查询上的逐条指标（a - b 的均值区间）。"""

    pairs = [(x, y) for x, y in zip(a, b) if not (math.isnan(x) or math.isnan(y))]
    if not pairs:
        return {"mean_diff": 0.0, "lo": 0.0, "hi": 0.0, "n": 0}
    rng = random.Random(seed)
    diffs = []
    n = len(pairs)
    for _ in range(iters):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        diffs.append(sum(x - y for x, y in sample) / n)
    diffs.sort()
    return {
        "mean_diff": sum(x - y for x, y in pairs) / n,
        "lo": diffs[int(0.025 * iters)],
        "hi": diffs[int(0.975 * iters) - 1],
        "n": n,
    }


def mean(values: Iterable[float]) -> float:
    vals = [v for v in values if not math.isnan(v)]
    return sum(vals) / len(vals) if vals else float("nan")
