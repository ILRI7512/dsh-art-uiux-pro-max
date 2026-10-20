"""知识状态机与学习等级计算。

这是"规则 3：严格区分知识状态与知识可靠性"的落地点：

1. 知识处理状态（discovered ... superseded）只能沿白名单迁移。
2. ``verified`` 是受保护状态：必须存在合格的核验记录（方法匹配知识类型、
   结果 pass、证据可追溯），且满足知识类型对应的最低证据要求。
3. LLM 自评、被总结、被向量化、被重复检索 —— 都不能提升状态或置信度。
4. 学习等级 L0-L5 由系统根据证据确定性推导，模型无权直接指定。

所有判定都是纯函数，便于单测与审计重放。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .models import (
    Chunk,
    KnowledgeStatus,
    KnowledgeType,
    LearningLevel,
    VerificationMethod,
    VerificationRecord,
    VerificationResult,
)

# --------------------------------------------------------------------------- #
# 状态迁移白名单
# --------------------------------------------------------------------------- #
ALLOWED_TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    KnowledgeStatus.DISCOVERED.value: (
        KnowledgeStatus.EXTRACTED.value,
        KnowledgeStatus.REJECTED.value,
        KnowledgeStatus.STALE.value,
    ),
    KnowledgeStatus.EXTRACTED.value: (
        KnowledgeStatus.PENDING_VERIFICATION.value,
        KnowledgeStatus.DISPUTED.value,
        KnowledgeStatus.REJECTED.value,
        KnowledgeStatus.SUPERSEDED.value,
        KnowledgeStatus.STALE.value,
    ),
    KnowledgeStatus.PENDING_VERIFICATION.value: (
        KnowledgeStatus.VERIFIED.value,
        KnowledgeStatus.DISPUTED.value,
        KnowledgeStatus.REJECTED.value,
        KnowledgeStatus.STALE.value,
        KnowledgeStatus.SUPERSEDED.value,
        # 允许退回提取阶段修正（例如分类错误需要重新提取）
        KnowledgeStatus.EXTRACTED.value,
    ),
    KnowledgeStatus.VERIFIED.value: (
        KnowledgeStatus.PRACTICED.value,
        KnowledgeStatus.DISPUTED.value,
        KnowledgeStatus.STALE.value,
        KnowledgeStatus.SUPERSEDED.value,
        KnowledgeStatus.REJECTED.value,
    ),
    KnowledgeStatus.PRACTICED.value: (
        KnowledgeStatus.EVALUATED.value,
        KnowledgeStatus.DISPUTED.value,
        KnowledgeStatus.STALE.value,
        KnowledgeStatus.SUPERSEDED.value,
    ),
    KnowledgeStatus.EVALUATED.value: (
        KnowledgeStatus.STALE.value,
        KnowledgeStatus.DISPUTED.value,
        KnowledgeStatus.SUPERSEDED.value,
    ),
    KnowledgeStatus.STALE.value: (
        KnowledgeStatus.PENDING_VERIFICATION.value,
        KnowledgeStatus.SUPERSEDED.value,
        KnowledgeStatus.REJECTED.value,
    ),
    KnowledgeStatus.DISPUTED.value: (
        KnowledgeStatus.PENDING_VERIFICATION.value,
        KnowledgeStatus.VERIFIED.value,
        KnowledgeStatus.REJECTED.value,
        KnowledgeStatus.SUPERSEDED.value,
    ),
    KnowledgeStatus.REJECTED.value: (
        KnowledgeStatus.PENDING_VERIFICATION.value,  # 允许复审翻案，但要重新核验
    ),
    KnowledgeStatus.SUPERSEDED.value: (),
}

#: 允许作为"已核验"依据的核验方法（按知识类型）
VERIFICATION_METHODS: Dict[str, Tuple[str, ...]] = {
    KnowledgeType.DEFINITION.value: (
        VerificationMethod.OFFICIAL_DOC_CHECK.value,
        VerificationMethod.SOURCE_CHECK.value,
        VerificationMethod.CROSS_SOURCE.value,
    ),
    KnowledgeType.FACT.value: (
        VerificationMethod.SOURCE_CHECK.value,
        VerificationMethod.CROSS_SOURCE.value,
        VerificationMethod.OFFICIAL_DOC_CHECK.value,
        VerificationMethod.EXPERIMENT.value,
    ),
    KnowledgeType.CONCEPT.value: (
        VerificationMethod.SOURCE_CHECK.value,
        VerificationMethod.CROSS_SOURCE.value,
        VerificationMethod.OFFICIAL_DOC_CHECK.value,
        VerificationMethod.MANUAL_REVIEW.value,
    ),
    KnowledgeType.PRINCIPLE.value: (
        VerificationMethod.SOURCE_CHECK.value,
        VerificationMethod.CROSS_SOURCE.value,
        VerificationMethod.OFFICIAL_DOC_CHECK.value,
        VerificationMethod.EXPERIMENT.value,
        VerificationMethod.FORMULA_RECOMPUTE.value,
    ),
    KnowledgeType.PROCEDURE.value: (
        VerificationMethod.OFFICIAL_DOC_CHECK.value,
        VerificationMethod.CROSS_SOURCE.value,
        VerificationMethod.CODE_TEST.value,
        VerificationMethod.EXPERIMENT.value,
    ),
    KnowledgeType.FORMULA.value: (
        VerificationMethod.FORMULA_RECOMPUTE.value,
        VerificationMethod.CODE_TEST.value,
        VerificationMethod.OFFICIAL_DOC_CHECK.value,
    ),
    KnowledgeType.CODE_EXAMPLE.value: (
        VerificationMethod.CODE_TEST.value,
        VerificationMethod.STATIC_ANALYSIS.value,
    ),
    KnowledgeType.BEST_PRACTICE.value: (
        VerificationMethod.CROSS_SOURCE.value,
        VerificationMethod.OFFICIAL_DOC_CHECK.value,
        VerificationMethod.USABILITY_TEST.value,
        VerificationMethod.MANUAL_REVIEW.value,
    ),
    KnowledgeType.CASE_STUDY.value: (
        VerificationMethod.SOURCE_CHECK.value,
        VerificationMethod.CROSS_SOURCE.value,
        VerificationMethod.MANUAL_REVIEW.value,
    ),
    KnowledgeType.HYPOTHESIS.value: (),  # 假设不可被"验证为事实"
    KnowledgeType.OPINION.value: (),  # 观点不可被"验证为事实"
    KnowledgeType.WARNING.value: (
        VerificationMethod.OFFICIAL_DOC_CHECK.value,
        VerificationMethod.SOURCE_CHECK.value,
        VerificationMethod.EXPERIMENT.value,
    ),
    KnowledgeType.UNRESOLVED_QUESTION.value: (),  # 未解决问题不进入已核验
    KnowledgeType.EXPERIMENTAL_RESULT.value: (
        VerificationMethod.EXPERIMENT.value,
        VerificationMethod.CODE_TEST.value,
    ),
}

#: 不可声明为外部事实/不可升级为 verified 的知识类型
NON_VERIFIABLE_TYPES = {
    KnowledgeType.HYPOTHESIS.value,
    KnowledgeType.OPINION.value,
    KnowledgeType.UNRESOLVED_QUESTION.value,
}

#: 各知识类型的最低证据要求：(最少证据条数, 最少独立证据数, 最低来源质量)
EVIDENCE_REQUIREMENTS: Dict[str, Tuple[int, int, float]] = {
    KnowledgeType.DEFINITION.value: (1, 1, 0.80),
    KnowledgeType.FACT.value: (2, 2, 0.55),
    KnowledgeType.CONCEPT.value: (1, 1, 0.65),
    KnowledgeType.PRINCIPLE.value: (2, 1, 0.70),
    KnowledgeType.PROCEDURE.value: (1, 1, 0.75),
    KnowledgeType.FORMULA.value: (1, 1, 0.60),
    KnowledgeType.CODE_EXAMPLE.value: (1, 1, 0.50),
    KnowledgeType.BEST_PRACTICE.value: (1, 1, 0.65),
    KnowledgeType.CASE_STUDY.value: (1, 1, 0.55),
    KnowledgeType.WARNING.value: (1, 1, 0.60),
    KnowledgeType.EXPERIMENTAL_RESULT.value: (1, 1, 0.50),
}


@dataclass
class TransitionDecision:
    allowed: bool
    target: str
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "allowed": self.allowed,
            "target": self.target,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
        }


def allowed_methods(knowledge_type: str) -> Tuple[str, ...]:
    return VERIFICATION_METHODS.get(knowledge_type, ())


def is_non_verifiable(knowledge_type: str) -> bool:
    return knowledge_type in NON_VERIFIABLE_TYPES


def evidence_requirements(knowledge_type: str) -> Tuple[int, int, float]:
    return EVIDENCE_REQUIREMENTS.get(knowledge_type, (1, 1, 0.60))


def effective_requirements(
    knowledge_type: str,
    source_type: str,
    records: Sequence[VerificationRecord] = (),
) -> Tuple[int, int, float]:
    """结合来源类型给出实际生效的证据门槛。

    官方文档/标准本身是权威来源：当存在通过的 ``official_doc_check`` 记录时，
    单来源即可满足最低证据要求；其余情况按知识类型的一般门槛执行。
    """

    min_count, min_independent, min_quality = evidence_requirements(knowledge_type)
    official = any(
        r.result == VerificationResult.PASS.value
        and r.method == VerificationMethod.OFFICIAL_DOC_CHECK.value
        for r in records
    )
    if official and source_type in {"official_doc", "standard"}:
        return 1, 1, min_quality
    return min_count, min_independent, min_quality


def evaluate_transition(
    chunk: Chunk,
    target: str,
    records: Optional[Sequence[VerificationRecord]] = None,
    *,
    reason: str = "",
) -> TransitionDecision:
    """判定是否允许把知识迁移到目标状态。

    ``reason`` 仅用于审计记录，不影响判定。
    """

    target = KnowledgeStatus.parse(target, "target_status").value
    current = chunk.status
    reasons: List[str] = []
    warnings: List[str] = []

    if current == target:
        return TransitionDecision(True, target, ["状态未变化（幂等）"])

    if target not in ALLOWED_TRANSITIONS.get(current, ()):  # pragma: no cover - 防御
        return TransitionDecision(
            False,
            target,
            [f"不允许从 {current} 迁移到 {target}"],
        )

    if target == KnowledgeStatus.VERIFIED.value:
        ok, why = _verify_guard(chunk, records or [])
        if not ok:
            return TransitionDecision(False, target, why)
        reasons.extend(why)

    if target == KnowledgeStatus.PRACTICED.value:
        practiced = [
            r
            for r in (records or [])
            if r.method
            in {
                VerificationMethod.CODE_TEST.value,
                VerificationMethod.EXPERIMENT.value,
                VerificationMethod.USABILITY_TEST.value,
                VerificationMethod.FORMULA_RECOMPUTE.value,
            }
            and r.result == VerificationResult.PASS.value
        ]
        if not practiced:
            return TransitionDecision(
                False,
                target,
                ["没有成功的实践/测试/实验记录，不能进入 practiced"],
            )
        reasons.append(f"存在 {len(practiced)} 条通过的实践证据")

    if target == KnowledgeStatus.EVALUATED.value:
        if chunk.status != KnowledgeStatus.PRACTICED.value and not chunk.metadata.get(
            "evaluation"
        ):
            return TransitionDecision(
                False, target, ["必须先完成实践或存在评估记录才能进入 evaluated"]
            )
        reasons.append("存在评估依据")

    if target == KnowledgeStatus.SUPERSEDED.value and not chunk.superseded_by:
        return TransitionDecision(
            False, target, ["标记 superseded 必须提供 superseded_by（新知识 ID）"]
        )

    if target == KnowledgeStatus.STALE.value:
        warnings.append("stale 只是时效标记，不代表知识错误")

    if is_non_verifiable(chunk.knowledge_type) and target in {
        KnowledgeStatus.VERIFIED.value,
        KnowledgeStatus.PRACTICED.value,
    }:
        return TransitionDecision(
            False,
            target,
            [f"{chunk.knowledge_type} 类型不允许升级为 {target}（规则 3.5）"],
        )

    return TransitionDecision(True, target, reasons, warnings)


def _verify_guard(chunk: Chunk, records: Sequence[VerificationRecord]) -> Tuple[bool, List[str]]:
    """verified 状态的硬性守卫。"""

    reasons: List[str] = []
    ktype = chunk.knowledge_type
    if is_non_verifiable(ktype):
        return False, [f"{ktype} 不能作为已验证事实（模型推断/观点必须保持标记）"]

    methods = allowed_methods(ktype)
    if not methods:
        return False, [f"{ktype} 没有定义任何可接受的核验方法"]

    passing = [
        r
        for r in records
        if r.result == VerificationResult.PASS.value and r.method in methods and r.evidence
    ]
    if not passing:
        return False, [
            "缺少合格的核验记录：方法必须属于 "
            + "/".join(methods)
            + "，结果必须是 pass 且包含证据"
        ]

    min_count, min_independent, min_quality = effective_requirements(ktype, chunk.source_type, records)
    independent_sources = {
        str(entry.get("source_id") or entry.get("publisher") or entry.get("url") or "")
        for record in passing
        for entry in (record.evidence or [])
    }
    independent_sources.discard("")
    evidence_count = sum(len(r.evidence or []) for r in passing)
    independence = max(len(independent_sources), chunk.evidence_independence)

    if evidence_count < min_count:
        return False, [f"{ktype} 至少需要 {min_count} 条通过证据，当前 {evidence_count} 条"]
    if independence < min_independent:
        return False, [
            f"{ktype} 至少需要 {min_independent} 个独立来源，当前 {independence} 个"
            + "（转载/镜像不算独立来源）"
        ]
    if chunk.source_quality < min_quality:
        return False, [
            f"来源质量 {chunk.source_quality:.2f} 低于 {ktype} 要求的 {min_quality:.2f}"
        ]

    reasons.append(f"核验方法 {', '.join(sorted({r.method for r in passing}))} 合格")
    reasons.append(f"独立证据 {independence} 条，来源质量 {chunk.source_quality:.2f}")
    return True, reasons


# --------------------------------------------------------------------------- #
# 学习等级推导
# --------------------------------------------------------------------------- #
_LEVEL_ORDER = [
    LearningLevel.L0,
    LearningLevel.L1,
    LearningLevel.L2,
    LearningLevel.L3,
    LearningLevel.L4,
    LearningLevel.L5,
]


def compute_level(chunk: Chunk, records: Optional[Sequence[VerificationRecord]] = None) -> str:
    """根据证据确定性推导 L0-L5，而不是让模型自报。"""

    records = list(records or [])
    status = chunk.status
    if status == KnowledgeStatus.DISCOVERED.value:
        base = LearningLevel.L1
    elif status in {
        KnowledgeStatus.EXTRACTED.value,
        KnowledgeStatus.PENDING_VERIFICATION.value,
    }:
        base = LearningLevel.L2
    elif status in {KnowledgeStatus.VERIFIED.value, KnowledgeStatus.STALE.value}:
        base = LearningLevel.L3
    elif status == KnowledgeStatus.PRACTICED.value:
        base = LearningLevel.L4
    elif status == KnowledgeStatus.EVALUATED.value:
        base = LearningLevel.L5
    elif status in {KnowledgeStatus.DISPUTED.value, KnowledgeStatus.REJECTED.value}:
        base = LearningLevel.L1 if chunk.evidence_count == 0 else LearningLevel.L2
    else:  # superseded
        base = _level_from_evidence(chunk, records)
    return base.value


def _level_from_evidence(chunk: Chunk, records: Sequence[VerificationRecord]) -> LearningLevel:
    passed = sum(1 for r in records if r.result == VerificationResult.PASS.value)
    if passed >= 2:
        return LearningLevel.L3
    if passed == 1:
        return LearningLevel.L2
    return LearningLevel.L1


def level_index(level: str) -> int:
    try:
        return _LEVEL_ORDER.index(LearningLevel(level))
    except ValueError:
        return 0


def max_level(*levels: str) -> str:
    best = LearningLevel.L0.value
    for lv in levels:
        if level_index(lv) > level_index(best):
            best = lv
    return best


def at_least(level: str, threshold: str) -> bool:
    return level_index(level) >= level_index(threshold)


# --------------------------------------------------------------------------- #
# 任务状态机
# --------------------------------------------------------------------------- #
TASK_TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    "pending": ("running", "cancelled", "blocked", "paused"),
    "running": ("completed", "failed", "paused", "blocked", "cancelled", "retrying"),
    "retrying": ("running", "failed", "cancelled", "blocked"),
    "paused": ("running", "cancelled", "pending"),
    "blocked": ("pending", "running", "cancelled"),
    "failed": ("retrying", "cancelled", "pending"),
    "completed": (),
    "cancelled": ("pending",),
}


def can_transition_task(current: str, target: str) -> bool:
    if current == target:
        return True
    return target in TASK_TRANSITIONS.get(current, ())


__all__ = [
    "ALLOWED_TRANSITIONS",
    "EVIDENCE_REQUIREMENTS",
    "NON_VERIFIABLE_TYPES",
    "TASK_TRANSITIONS",
    "TransitionDecision",
    "VERIFICATION_METHODS",
    "allowed_methods",
    "at_least",
    "can_transition_task",
    "compute_level",
    "effective_requirements",
    "evaluate_transition",
    "evidence_requirements",
    "is_non_verifiable",
    "level_index",
    "max_level",
]
