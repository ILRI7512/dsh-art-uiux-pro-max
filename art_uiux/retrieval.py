"""检索重排层：在引擎混合检索（向量+BM25+RRF）之后，按「查询→分类亲和度」做一次可解释重排。

为什么需要：
- 引擎默认 embedder 是离线特征哈希（512 维），语义能力有限；
- 查询常常同时命中多个分类，但落库时每条知识已有唯一主分类；
- 因此用 taxonomy 的关键词做一次确定性亲和度计算，比调参更可解释、可复现。

规则：
1. 先取 top_k*3 候选（扩大召回）；
2. 用 taxonomy 关键词给每个分类算查询亲和度（归一化到 0..1）；
3. 最终分 = 原分 × (1 + 0.35 × 亲和度)，仅对「该条知识主分类亲和度」加成；
4. 若调用方显式给了分类，则直接按分类过滤，不做额外加成。
结果里保留 rerank 明细，方便复核为什么排到第一。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from .taxonomy import CATEGORIES

STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "for", "with", "on",
        "how", "what", "best", "good", "use", "using", "should", "minimum"}


def _tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z\u4e00-\u9fff]{2,}", (text or "").lower()) if w not in STOP}


def category_affinity(query: str) -> Dict[str, float]:
    """查询对各分类的亲和度：关键词命中数 / 该分类关键词总数，取最大值归一化。"""

    tokens = _tokens(query)
    low = (query or "").lower()
    raw: Dict[str, float] = {}
    for key, cat in CATEGORIES.items():
        hits = 0.0
        for kw in cat.keywords:
            k = kw.lower()
            if k in low or any(t in k or k in t for t in tokens):
                hits += 1.0
        # 分类描述里的词也算弱信号
        hits += 0.25 * sum(1 for w in _tokens(cat.description) if w in tokens)
        if hits:
            raw[key] = hits
    if not raw:
        return {}
    top = max(raw.values())
    return {k: round(v / top, 3) for k, v in raw.items()}


def search(rt, query: str, *, top_k: int = 5, categories: Optional[Sequence[str]] = None,
           expand: int = 3, bilingual: bool = False, rerank: str = "rules",
           rerank_pool: int = 12) -> Dict[str, Any]:
    from dsh_autonomous_learning.storage.metadata_store import ChunkFilter

    filters = ChunkFilter(project_id="prj_art_uiux")
    if categories:
        filters.topics = list(categories)

    search_query, bilingual_hits = (query, [])
    if bilingual:
        from .bilingual import expand as _expand

        search_query, bilingual_hits = _expand(query)

    res = rt.store.search(search_query, top_k=max(top_k * expand, top_k), filters=filters, include_content=True)
    hits: List[Dict[str, Any]] = list(res.get("results") or [])

    affinity = {} if categories else category_affinity(query)
    q_tokens = _tokens(query) | _tokens(search_query)
    ranked = []
    for hit in hits:
        topic = hit.get("topic") or ""
        aff = float(affinity.get(topic, 0.0))
        base = float(hit.get("score") or 0.0)
        body = ((hit.get("title") or "") + " " + (hit.get("content") or "") + " " + (hit.get("summary") or "")).lower()
        overlap = (len(q_tokens & _tokens(body)) / len(q_tokens)) if q_tokens else 0.0
        final = base * (1.0 + 0.35 * aff) * (1.0 + 0.6 * overlap)
        item = dict(hit)
        item["base_score"] = round(base, 4)
        item["category_affinity"] = aff
        item["lexical_overlap"] = round(overlap, 3)
        item["final_score"] = round(final, 4)
        ranked.append(item)

    ranked.sort(key=lambda h: h["final_score"], reverse=True)

    meta: Dict[str, Any] = {}
    if rerank == "ce":
        from .rerank import rerank as ce_rerank

        ce = ce_rerank(query, ranked[: max(rerank_pool, top_k)], top_k=top_k)
        top = ce["results"]
        meta["cross_encoder"] = {"model": ce["model"], "latency_ms": ce["latency_ms"],
                                 "reranked": ce["reranked"], "blend": ce["blend"]}
    else:
        top = ranked[:top_k]
    return {
        "query": query,
        "rerank_mode": rerank,
        **meta,
        "count": len(top),
        "candidates": len(hits),
        "rerank": {"applied": bool(affinity), "affinity": affinity},
        "bilingual": {"applied": bool(bilingual_hits), "hits": bilingual_hits,
                      "expanded_query": search_query if bilingual_hits else ""},
        "evidence_sufficient": bool(top),
        "results": top,
    }
