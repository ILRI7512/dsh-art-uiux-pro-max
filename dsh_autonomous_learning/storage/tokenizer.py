"""文本切词与 BM25 关键词检索。

为什么自己写而不用 SQLite FTS5：
- FTS5 的 unicode61 分词器不会切分中文，中文检索几乎不可用；
- 我们只需要一个确定性的关键词通道与向量通道做混合检索，
  自己维护 token 倒排表反而更可控、可测试、可解释。

分词策略：
- 英文/数字：按 ``[a-z0-9_+#./-]+`` 取词，保留 ``c++``、``node.js`` 这类术语；
- 中文：按连续汉字段切分，生成二元组（bigram），长度为 1 时保留单字；
  二元组能在无分词词典的情况下获得可用的中文召回。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Set, Tuple

_LATIN_RE = re.compile(r"[a-zA-Z0-9_+#./\u2014-]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "with", "is",
    "are", "was", "were", "be", "been", "it", "this", "that", "as", "by", "at",
    "的", "了", "和", "与", "是", "在", "有", "对", "把", "被", "为", "从", "就",
    "都", "也", "而", "及", "或", "一个", "我们", "可以", "这个", "那个",
}


def tokenize(text: str) -> List[str]:
    """把文本切成检索 token（保留顺序用于短语加权）。"""

    if not text:
        return []
    lowered = text.lower()
    tokens: List[str] = []
    for match in _LATIN_RE.finditer(lowered):
        word = match.group().strip("._-/")
        if len(word) >= 2 and word not in _STOPWORDS:
            tokens.append(word)
    for match in _CJK_RE.finditer(text):
        run = match.group()
        if len(run) == 1:
            if run not in _STOPWORDS:
                tokens.append(run)
            continue
        for i in range(len(run) - 1):
            bigram = run[i : i + 2]
            if bigram not in _STOPWORDS:
                tokens.append(bigram)
    return tokens


def term_frequencies(text: str) -> Dict[str, int]:
    return dict(Counter(tokenize(text)))


@dataclass
class BM25Params:
    k1: float = 1.5
    b: float = 0.75


def bm25_scores(
    query_tokens: Sequence[str],
    docs: Dict[str, Dict[str, int]],
    doc_lengths: Dict[str, int],
    total_docs: int,
    avg_length: float,
    params: BM25Params | None = None,
) -> Dict[str, float]:
    """纯 Python 的 BM25 实现（用于单测与小型语料）。

    生产路径走 SQL 版本（见 metadata_store.bm25_search），二者公式一致。
    """

    params = params or BM25Params()
    q = [t for t in dict.fromkeys(query_tokens) if t]
    if not q or total_docs <= 0:
        return {}
    df = {t: sum(1 for freqs in docs.values() if t in freqs) for t in q}
    avgdl = avg_length or 1.0
    scores: Dict[str, float] = {}
    for doc_id, freqs in docs.items():
        dl = doc_lengths.get(doc_id, sum(freqs.values())) or 1
        score = 0.0
        for term in q:
            tf = freqs.get(term, 0)
            if not tf:
                continue
            n = df.get(term, 0)
            idf = math.log(1 + (total_docs - n + 0.5) / (n + 0.5))
            denom = tf + params.k1 * (1 - params.b + params.b * dl / avgdl)
            score += idf * (tf * (params.k1 + 1)) / denom
        if score > 0:
            scores[doc_id] = score
    return scores


def expand_query(query: str) -> List[str]:
    """检索用 token：原词 + 去重。"""

    return list(dict.fromkeys(tokenize(query)))


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


__all__ = [
    "BM25Params",
    "bm25_scores",
    "expand_query",
    "jaccard",
    "term_frequencies",
    "tokenize",
]
