"""交叉编码器重排（cross-encoder rerank）。

与双塔（bi-encoder）检索的分工：
- 检索用向量模型粗排，负责召回；
- 重排用 cross-encoder 把「查询 + 文档」拼在一起打分，能捕捉词面与否定的细粒度差异。

模型选多语言版：查询是中文、语料是英文，单语 reranker 不适用。

代价说明（本机 arm64 CPU 实测，不是估算）：
- 模型约 470 MB；
- 每次查询要对 N 个候选逐条前向，延迟随候选数线性增长；
- 因此只对前 `candidates` 条做重排，且延迟写进返回值里。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence

DEFAULT_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"

_model = None
_model_name = ""


def load(model_name: str = DEFAULT_MODEL):
    """进程内单例，避免每次查询都重新加载权重。"""

    global _model, _model_name
    if _model is not None and _model_name == model_name:
        return _model
    from sentence_transformers import CrossEncoder

    _model = CrossEncoder(model_name, max_length=512)
    _model_name = model_name
    return _model


def rerank(query: str, candidates: Sequence[Dict[str, Any]], *, top_k: int = 5,
           model_name: str = DEFAULT_MODEL, blend: float = 0.5) -> Dict[str, Any]:
    """对候选做重排。

    blend 是交叉编码器分数的权重：
    - 1.0 = 完全信任 CE
    - 0.5 = 与检索分各占一半（默认，避免 CE 把明显相关但表述不同的内容压掉）
    """

    started = time.perf_counter()
    if not candidates:
        return {"results": [], "model": model_name, "reranked": 0, "latency_ms": 0.0}

    model = load(model_name)
    pairs = [(query, (c.get("title") or "") + " " + (c.get("content") or c.get("summary") or ""))
             for c in candidates]
    scores = model.predict(pairs, show_progress_bar=False)

    # 检索分与本轮 CE 分都归一到 0..1，再做加权
    base = [float(c.get("final_score") or c.get("score") or 0.0) for c in candidates]
    bmin, bmax = min(base), max(base)
    smin, smax = float(min(scores)), float(max(scores))

    def norm(v: float, lo: float, hi: float) -> float:
        if hi - lo < 1e-9:
            return 1.0 if hi > 0 else 0.0
        return (v - lo) / (hi - lo)

    out: List[Dict[str, Any]] = []
    for cand, ce_score, base_score in zip(candidates, scores, base):
        ce_norm = norm(float(ce_score), smin, smax)
        base_norm = norm(base_score, bmin, bmax)
        item = dict(cand)
        item["ce_score"] = round(float(ce_score), 4)
        item["ce_norm"] = round(ce_norm, 4)
        item["blended"] = round(blend * ce_norm + (1 - blend) * base_norm, 4)
        out.append(item)

    out.sort(key=lambda x: x["blended"], reverse=True)
    return {
        "results": out[:top_k],
        "model": model_name,
        "reranked": len(out),
        "blend": blend,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }
