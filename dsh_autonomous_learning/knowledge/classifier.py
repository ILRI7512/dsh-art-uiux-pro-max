"""知识分类。

两件事：
1. 判断知识类型（definition/fact/formula/...），决定后续采用哪种核验方法；
2. 判断所属逻辑分区（规则 1）。

实现是**可解释的规则打分**，不是黑箱模型：
每命中一个模式就加分并记录理由，最终返回理由列表，便于审计与调参。
当有可用模型时，模型只能对"低置信度"的分类给出建议，且建议必须写进
``classification_basis`` 留痕，不能直接覆盖规则结果。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

from ..core.models import KnowledgeType
from .partitions import PARTITION_SPECS, partition_for_domain

# --------------------------------------------------------------------------- #
# 知识类型规则
# --------------------------------------------------------------------------- #
_TYPE_PATTERNS: List[Tuple[str, float, Sequence[str]]] = [
    (
        KnowledgeType.DEFINITION.value,
        3.0,
        (r"是指", r"指的是", r"定义为", r"称为", r"\bis defined as\b", r"\brefers to\b", r"意味着"),
    ),
    (
        KnowledgeType.FORMULA.value,
        4.0,
        (
            r"\$[^$\n]{2,80}\$",
            r"\b[a-zA-Z_]\w*\s*=\s*[^=\n]{2,60}",
            r"[\u4e00-\u9fff]{2,12}\s*=\s*[^=\n]{2,60}",
            r"公式",
            r"\bformula\b",
        ),
    ),
    (
        KnowledgeType.CODE_EXAMPLE.value,
        3.5,
        (r"```", r"\bdef\s+\w+\(", r"\bfn\s+\w+\(", r"\bclass\s+\w+", r"import\s+\w+"),
    ),
    (
        KnowledgeType.PROCEDURE.value,
        2.6,
        (r"步骤", r"流程", r"第[一二三四五六七八九十]步", r"^\s*\d+\.\s", r"\bstep\s+\d", r"\bfirst\b.*\bthen\b"),
    ),
    (
        KnowledgeType.WARNING.value,
        2.8,
        (
            r"风险提示",
            r"存在风险",
            r"警告",
            r"注意[：:]",
            r"坑",
            r"不要",
            r"\bwarning\b",
            r"\bcaution\b",
            r"\bavoid\b",
            r"可能导致",
        ),
    ),
    (
        KnowledgeType.BEST_PRACTICE.value,
        2.4,
        (r"最佳实践", r"推荐做法", r"建议", r"\bbest practice\b", r"\bshould\b", r"\brecommend"),
    ),
    (
        KnowledgeType.CASE_STUDY.value,
        2.2,
        (r"案例", r"例如", r"举个", r"\bcase study\b", r"\bfor example\b"),
    ),
    (
        KnowledgeType.PRINCIPLE.value,
        2.3,
        (r"原理", r"机制", r"本质", r"因为", r"由于", r"\bprinciple\b", r"\bbecause\b", r"\bmechanism\b"),
    ),
    (
        KnowledgeType.HYPOTHESIS.value,
        3.0,
        (r"假设", r"假定", r"推测", r"\bhypothes", r"\bassume\b", r"\bsuppose\b", r"可能是"),
    ),
    (
        KnowledgeType.OPINION.value,
        3.0,
        (r"我认为", r"笔者", r"个人观点", r"\bi think\b", r"\bin my opinion\b", r"\barguably\b"),
    ),
    (
        KnowledgeType.UNRESOLVED_QUESTION.value,
        3.0,
        (r"未解决", r"尚未确定", r"待验证", r"开放问题", r"\bopen question\b", r"\bunresolved\b", r"\btodo\b"),
    ),
    (
        KnowledgeType.EXPERIMENTAL_RESULT.value,
        2.9,
        (r"实验结果", r"测试结果", r"实测", r"复现", r"\bbenchmark\b", r"\bmeasured\b", r"\bexperiment\b"),
    ),
    (
        KnowledgeType.CONCEPT.value,
        1.2,
        (r"概念", r"术语", r"范畴", r"\bconcept\b", r"\bterminology\b"),
    ),
    (
        KnowledgeType.FACT.value,
        1.0,
        (r"\d{4}年", r"\d+\s*(?:%|％|倍|个|次)", r"\baccording to\b", r"据.{0,6}(?:报道|统计|研究)"),
    ),
]


@dataclass
class Classification:
    knowledge_type: str
    partition: str
    domain: str
    scores: Dict[str, float] = field(default_factory=dict)
    basis: str = ""
    low_confidence: bool = False

    def to_dict(self) -> Dict[str, object]:
        return {
            "knowledge_type": self.knowledge_type,
            "partition": self.partition,
            "domain": self.domain,
            "scores": self.scores,
            "basis": self.basis,
            "low_confidence": self.low_confidence,
        }


def classify_knowledge_type(text: str, title: str = "") -> Tuple[str, Dict[str, float], str]:
    sample = f"{title}\n{text}"[:6000]
    lowered = sample.lower()
    scores: Dict[str, float] = {}
    hits: Dict[str, List[str]] = {}
    for ktype, weight, patterns in _TYPE_PATTERNS:
        score = 0.0
        matched: List[str] = []
        for pattern in patterns:
            if re.search(pattern, sample, re.I | re.M):
                score += weight
                matched.append(pattern)
        if score:
            scores[ktype] = round(score, 2)
            hits[ktype] = matched
    if not scores:
        return KnowledgeType.FACT.value, {}, "未命中任何类型模式，默认按 fact 处理（未经核验）"

    best = max(scores.items(), key=lambda kv: kv[1])[0]
    reasons = [f"{k}={v}" for k, v in sorted(scores.items(), key=lambda kv: -kv[1])]
    basis = "类型打分: " + "，".join(reasons)
    if len(scores) > 1:
        top_two = sorted(scores.values(), reverse=True)[:2]
        if top_two[0] - top_two[1] < 0.6:
            basis += "；前两名接近，分类可能不准确，建议交叉确认"
    return best, scores, basis


def classify_partition(text: str, domain: str = "", title: str = "") -> Tuple[str, str]:
    """按关键词密度选择分区；领域显式指定时以领域为准。"""

    if domain:
        mapped = partition_for_domain(domain)
        return mapped, f"按显式 domain={domain} 映射到 {mapped}"

    sample = f"{title}\n{text}"[:4000].lower()
    best_partition = partition_for_domain("general")
    best_score = 0.0
    detail: List[str] = []
    for key, spec in PARTITION_SPECS.items():
        if not spec.keywords:
            continue
        hits = sum(1 for kw in spec.keywords if kw.lower() in sample)
        if hits == 0:
            continue
        score = hits
        detail.append(f"{key}={hits}")
        if score > best_score:
            best_score = score
            best_partition = key
    basis = "分区关键词命中: " + ("，".join(detail) if detail else "无命中，落到通用分区")
    return best_partition, basis


def infer_domain(partition: str) -> str:
    spec = PARTITION_SPECS.get(partition)
    return spec.default_domain if spec else "general"


def classify(text: str, title: str = "", domain: str = "") -> Classification:
    ktype, scores, type_basis = classify_knowledge_type(text, title)
    partition, part_basis = classify_partition(text, domain, title)
    final_domain = domain or infer_domain(partition)
    basis = f"{type_basis}；{part_basis}"
    low_confidence = bool(scores) and max(scores.values()) < 2.0
    return Classification(
        knowledge_type=ktype,
        partition=partition,
        domain=final_domain,
        scores=scores,
        basis=basis,
        low_confidence=low_confidence,
    )


__all__ = [
    "Classification",
    "classify",
    "classify_knowledge_type",
    "classify_partition",
    "infer_domain",
]
