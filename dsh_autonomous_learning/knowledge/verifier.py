"""知识核验器（规则 3 的核心实现）。

硬性纪律：
1. 没有证据的核验一律 fail/inconclusive，不允许"模型说对"就升级状态；
2. 核验方法必须与知识类型匹配（见 core/state_machine.VERIFICATION_METHODS）；
3. 转载/镜像不算独立来源：独立性按 source_id / 发布机构 / 域名去重；
4. 观点、假设、未解决问题永远不能被标记为 verified 事实；
5. 核验失败也保留记录，并把状态设为 disputed / pending_verification。

置信度由确定性公式计算，不是模型给的分数：
0.5*来源质量 + 0.2*证据达标 + 0.2*独立性 + 0.1*核验通过，上限 0.95。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urlparse

from ..core.models import (
    Chunk,
    KnowledgeStatus,
    VerificationMethod,
    VerificationRecord,
    VerificationResult,
    new_id,
    utcnow_iso,
)
from ..core.state_machine import (
    compute_level,
    effective_requirements,
    evaluate_transition,
    evidence_requirements,
    is_non_verifiable,
)
from ..security.execution_policy import FormulaError, safe_eval_expression
from ..storage.metadata_store import ChunkFilter, MetadataStore
from ..storage.vector_store import KnowledgeStore, KnowledgeStoreError

_CHUNK_FIELDS = set(Chunk.__dataclass_fields__.keys())


def chunk_from_dict(row: Mapping[str, Any]) -> Chunk:
    data = {k: v for k, v in row.items() if k in _CHUNK_FIELDS}
    data.setdefault("chunk_id", row.get("chunk_id", ""))
    data.setdefault("project_id", row.get("project_id", ""))
    return Chunk(**data)  # type: ignore[arg-type]


def estimate_confidence(
    chunk: Chunk, records: Sequence[VerificationRecord], independence: int, requirements_met: bool
) -> tuple[float, str]:
    passed = [r for r in records if r.result == VerificationResult.PASS.value]
    parts: List[str] = []
    value = 0.5 * float(chunk.source_quality or 0.0)
    parts.append(
        f"0.5*来源质量({chunk.source_quality:.2f})={0.5 * float(chunk.source_quality or 0.0):.3f}"
    )
    if requirements_met and passed:
        value += 0.2
        parts.append("+0.2 证据达标")
    if independence:
        bonus = min(0.2, 0.1 * independence)
        value += bonus
        parts.append(f"+{bonus:.2f} 独立来源={independence}")
    if passed:
        value += 0.1
        parts.append("+0.1 核验通过")
    if chunk.conflict_status == "confirmed":
        value -= 0.15
        parts.append("-0.15 存在确认冲突")
    value = max(0.05, min(0.95, round(value, 3)))
    parts.append(f"= {value}（上限 0.95，不允许 1.0）")
    return value, "；".join(parts)


@dataclass
class VerificationOutcome:
    chunk_id: str
    method: str
    result: str
    status_before: str
    status_after: str
    level: str
    confidence: float
    confidence_basis: str
    evidence_count: int
    independence: int
    record_id: str = ""
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "method": self.method,
            "result": self.result,
            "status_before": self.status_before,
            "status_after": self.status_after,
            "level": self.level,
            "confidence": self.confidence,
            "confidence_basis": self.confidence_basis,
            "evidence_count": self.evidence_count,
            "independence": self.independence,
            "record_id": self.record_id,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
        }


class KnowledgeVerifier:
    def __init__(self, store: KnowledgeStore, metadata: MetadataStore) -> None:
        self.store = store
        self.metadata = metadata

    # ------------------------------------------------------------------ #
    def auto_method(self, chunk: Mapping[str, Any]) -> str:
        ktype = chunk.get("knowledge_type")
        if ktype == "formula":
            return VerificationMethod.FORMULA_RECOMPUTE.value
        if ktype == "code_example":
            return VerificationMethod.CODE_TEST.value
        if ktype == "experimental_result":
            return VerificationMethod.EXPERIMENT.value
        if chunk.get("source_type") in {"official_doc", "standard"}:
            return VerificationMethod.OFFICIAL_DOC_CHECK.value
        return VerificationMethod.SOURCE_CHECK.value

    # ------------------------------------------------------------------ #
    def verify(
        self,
        chunk_id: str,
        *,
        method: Optional[str] = None,
        evidence: Optional[Sequence[Mapping[str, Any]]] = None,
        verifier: str = "system",
        expression: Optional[str] = None,
        variables: Optional[Mapping[str, float]] = None,
        expected: Optional[float] = None,
        tolerance: float = 1e-6,
        code_result: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        chunk_row = self.metadata.get_chunk(chunk_id)
        if not chunk_row:
            raise KnowledgeStoreError(f"知识片段不存在: {chunk_id}")
        chunk = chunk_from_dict(chunk_row)
        method = VerificationMethod.parse(method or self.auto_method(chunk_row), "method").value

        reasons: List[str] = []
        warnings: List[str] = []

        if is_non_verifiable(chunk.knowledge_type):
            return self._finish_non_verifiable(chunk, reasons)

        evidence_list = self._normalize_evidence(chunk_row, evidence or [])
        result = VerificationResult.INCONCLUSIVE.value
        independence = 0

        if method in {
            VerificationMethod.SOURCE_CHECK.value,
            VerificationMethod.OFFICIAL_DOC_CHECK.value,
            VerificationMethod.CROSS_SOURCE.value,
        }:
            evidence_list = self._enrich_evidence(chunk_row, evidence_list)
            independence = self._independence(chunk_row, evidence_list)
            result, why = self._judge_source(chunk, method, evidence_list, independence)
            reasons.extend(why)
        elif method == VerificationMethod.FORMULA_RECOMPUTE.value:
            result, extra_evidence, why = self._recompute_formula(
                chunk, expression, variables, expected, tolerance
            )
            evidence_list.extend(extra_evidence)
            reasons.extend(why)
            independence = 1
        elif method in {
            VerificationMethod.CODE_TEST.value,
            VerificationMethod.EXPERIMENT.value,
            VerificationMethod.USABILITY_TEST.value,
        }:
            result, extra_evidence, why = self._judge_practice(chunk, method, code_result, evidence_list)
            evidence_list.extend(extra_evidence)
            reasons.extend(why)
            independence = 1
        elif method == VerificationMethod.STATIC_ANALYSIS.value:
            result, why = self._judge_static(chunk)
            reasons.extend(why)
            independence = 1
        elif method == VerificationMethod.MANUAL_REVIEW.value:
            result = VerificationResult.PASS.value if evidence_list else VerificationResult.FAIL.value
            reasons.append("人工复核证据已提供" if evidence_list else "人工复核未提供任何证据")
            independence = self._independence(chunk_row, evidence_list)
        else:  # pragma: no cover - 枚举已覆盖
            warnings.append(f"未知核验方法 {method}，按无证据处理")
            independence = 0

        if not evidence_list:
            result = VerificationResult.FAIL.value
            reasons.append("核验未产生任何证据，按失败处理（规则 3：无证据不得升级）")

        # ---------------- 落库 ----------------
        record = VerificationRecord(
            record_id=new_id("vrf"),
            chunk_id=chunk_id,
            method=method,
            result=result,
            evidence=evidence_list,
            notes="；".join(reasons)[:2000],
            verifier=verifier,
        )
        self.metadata.add_verification(record.to_row())

        records = [
            VerificationRecord(**{k: r[k] for k in VerificationRecord.__dataclass_fields__ if k in r})
            for r in self.metadata.list_verifications(chunk_id)
        ]
        passed = [r for r in records if r.result == VerificationResult.PASS.value]
        independence_total = max(
            independence,
            len({e.get("source_id") for e in evidence_list if e.get("source_id")}),
        )

        chunk.evidence_count = sum(len(r.evidence or []) for r in passed) if passed else 0
        chunk.evidence_independence = independence_total
        chunk.verification_method = method
        chunk.verification_evidence = evidence_list
        min_count, min_indep, min_quality = effective_requirements(
            chunk.knowledge_type, chunk.source_type, records
        )
        requirements_met = (
            chunk.evidence_count >= min_count
            and independence_total >= min_indep
            and chunk.source_quality >= min_quality
        )
        confidence, basis = estimate_confidence(chunk, records, independence_total, requirements_met)
        chunk.confidence = confidence
        chunk.confidence_basis = basis

        status_before = chunk.status
        status_after = status_before
        if result == VerificationResult.PASS.value and requirements_met:
            chunk.verification_status = "verified"
            decision = evaluate_transition(chunk, KnowledgeStatus.VERIFIED.value, records)
            if decision.allowed:
                status_after = KnowledgeStatus.VERIFIED.value
                reasons.extend(decision.reasons)
            else:
                chunk.verification_status = "partial"
                warnings.extend(decision.reasons)
        elif result == VerificationResult.PASS.value:
            chunk.verification_status = "partial"
            warnings.append(
                f"核验通过但未达到 {chunk.knowledge_type} 的升级门槛"
                f"（需要证据 {min_count} 条/独立来源 {min_indep} 个/来源质量 {min_quality:.2f}）"
            )
        elif result == VerificationResult.PARTIAL.value:
            chunk.verification_status = "partial"
        elif result == VerificationResult.FAIL.value:
            chunk.verification_status = "failed"
            if chunk.status in {
                KnowledgeStatus.PENDING_VERIFICATION.value,
                KnowledgeStatus.VERIFIED.value,
            }:
                chunk.status = KnowledgeStatus.DISPUTED.value
                status_after = KnowledgeStatus.DISPUTED.value
                reasons.append("核验失败，按规则转入 disputed 而不是直接删除")
        else:
            chunk.verification_status = "unverified"

        chunk.status = status_after or chunk.status
        chunk.level = compute_level(chunk, records)
        chunk.updated_at = utcnow_iso()

        self.metadata.update_chunk(
            chunk_id,
            {
                "status": chunk.status,
                "level": chunk.level,
                "verification_status": chunk.verification_status,
                "verification_method": chunk.verification_method,
                "verification_evidence": chunk.verification_evidence,
                "evidence_count": chunk.evidence_count,
                "evidence_independence": chunk.evidence_independence,
                "confidence": chunk.confidence,
                "confidence_basis": chunk.confidence_basis,
                "updated_at": chunk.updated_at,
            },
        )

        return VerificationOutcome(
            chunk_id=chunk_id,
            method=method,
            result=result,
            status_before=status_before,
            status_after=chunk.status,
            level=chunk.level,
            confidence=chunk.confidence,
            confidence_basis=chunk.confidence_basis,
            evidence_count=chunk.evidence_count,
            independence=independence_total,
            record_id=record.record_id,
            reasons=reasons,
            warnings=warnings,
        ).to_dict()

    # ------------------------------------------------------------------ #
    def verify_formula(
        self,
        chunk_id: str,
        *,
        expression: Optional[str] = None,
        variables: Optional[Mapping[str, float]] = None,
        expected: Optional[float] = None,
        tolerance: float = 1e-6,
    ) -> Dict[str, Any]:
        return self.verify(
            chunk_id,
            method=VerificationMethod.FORMULA_RECOMPUTE.value,
            expression=expression,
            variables=variables,
            expected=expected,
            tolerance=tolerance,
        )

    # ------------------------------------------------------------------ #
    # 判定细节
    # ------------------------------------------------------------------ #
    def _normalize_evidence(
        self, chunk: Mapping[str, Any], extra: Sequence[Mapping[str, Any]]
    ) -> List[Dict[str, Any]]:
        evidence: List[Dict[str, Any]] = []
        if chunk.get("source_url") or chunk.get("source_id"):
            evidence.append(
                {
                    "kind": "source",
                    "source_id": chunk.get("source_id", ""),
                    "url": chunk.get("source_url", ""),
                    "title": chunk.get("source_title", ""),
                    "publisher": chunk.get("author_or_publisher", ""),
                    "published_at": chunk.get("published_at", ""),
                    "accessed_at": chunk.get("accessed_at", ""),
                    "snippet": (chunk.get("content") or "")[:300],
                }
            )
        for item in extra:
            entry = dict(item)
            entry.setdefault("kind", "manual")
            evidence.append(entry)
        return evidence

    def _enrich_evidence(
        self, chunk: Mapping[str, Any], evidence: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """补入**内容相近**的其他来源，用于交叉验证。

        注意：仅仅"同主题"不构成独立证据——同一主题下的不同结论不能互相印证。
        因此这里要求候选片段与目标片段的向量相似度达到阈值（同一说法），
        并且按来源去重（转载/镜像不算独立来源）。
        """

        topic = chunk.get("topic") or ""
        if not topic:
            return evidence
        similar = self.store.find_duplicates(
            chunk["chunk_id"],
            threshold=0.5,
            filters=ChunkFilter(project_id=chunk.get("project_id"), topics=[topic]),
            max_pairs=20,
        )
        seen = {e.get("source_id") or e.get("url") for e in evidence}
        for cand in similar:
            if len(evidence) >= 6:
                break
            row = self.metadata.get_chunk(cand["chunk_b"])
            if not row:
                continue
            key = row.get("source_id") or row.get("source_url")
            if not key or key in seen:
                continue
            seen.add(key)
            evidence.append(
                {
                    "kind": "cross_source",
                    "chunk_id": row["chunk_id"],
                    "source_id": row.get("source_id", ""),
                    "url": row.get("source_url", ""),
                    "title": row.get("source_title", ""),
                    "publisher": row.get("author_or_publisher", ""),
                    "similarity": cand.get("similarity", 0.0),
                    "snippet": (row.get("content") or "")[:200],
                }
            )
        return evidence

    def _independence(self, chunk: Mapping[str, Any], evidence: Sequence[Mapping[str, Any]]) -> int:
        keys = set()
        for item in evidence:
            key = (
                item.get("source_id")
                or item.get("publisher")
                or _host(item.get("url", ""))
                or item.get("kind")
            )
            if key:
                keys.add(str(key))
        return len(keys)

    def _judge_source(
        self,
        chunk: Chunk,
        method: str,
        evidence: Sequence[Mapping[str, Any]],
        independence: int,
    ) -> tuple[str, List[str]]:
        reasons: List[str] = []
        min_count, min_indep, min_quality = evidence_requirements(chunk.knowledge_type)
        if not evidence:
            return VerificationResult.FAIL.value, ["没有任何来源证据"]
        reasons.append(f"收集到 {len(evidence)} 条来源证据，独立来源 {independence} 个")

        if method == VerificationMethod.OFFICIAL_DOC_CHECK.value:
            official = [
                e
                for e in evidence
                if e.get("kind") == "source" and chunk.source_type in {"official_doc", "standard"}
            ]
            if not official:
                return VerificationResult.FAIL.value, reasons + [
                    "来源类型不是官方文档/标准，不适用官方文档核验"
                ]
            reasons.append("来源为官方文档/标准")
            return VerificationResult.PASS.value, reasons

        if independence < min_indep:
            return VerificationResult.PARTIAL.value, reasons + [
                f"独立来源 {independence} < 要求的 {min_indep}（转载/镜像不算独立来源）"
            ]
        if chunk.source_quality < min_quality:
            return VerificationResult.PARTIAL.value, reasons + [
                f"来源质量 {chunk.source_quality:.2f} < 要求的 {min_quality:.2f}"
            ]
        if len(evidence) < min_count:
            return VerificationResult.PARTIAL.value, reasons + [
                f"证据条数 {len(evidence)} < 要求的 {min_count}"
            ]
        reasons.append("来源质量与独立性满足该知识类型的门槛")
        return VerificationResult.PASS.value, reasons

    def _recompute_formula(
        self,
        chunk: Chunk,
        expression: Optional[str],
        variables: Optional[Mapping[str, float]],
        expected: Optional[float],
        tolerance: float,
    ) -> tuple[str, List[Dict[str, Any]], List[str]]:
        reasons: List[str] = []
        expr = expression
        if not expr:
            formulas = (chunk.metadata or {}).get("formulas") or []
            if formulas:
                expr = str(formulas[0].get("expression", ""))
        if not expr:
            return VerificationResult.INCONCLUSIVE.value, [], [
                "未提供公式表达式，也没有从提取结果中找到公式，无法重算"
            ]
        if expected is None:
            return VerificationResult.INCONCLUSIVE.value, [], [
                "未提供期望值 expected，无法判断公式计算结果是否正确"
            ]
        try:
            computed = safe_eval_expression(expr, variables or {})
        except FormulaError as exc:
            return (
                VerificationResult.FAIL.value,
                [
                    {
                        "kind": "formula_recompute",
                        "expression": expr,
                        "variables": dict(variables or {}),
                        "error": str(exc),
                    }
                ],
                [f"公式求值失败: {exc}"],
            )

        diff = abs(computed - float(expected))
        evidence = {
            "kind": "formula_recompute",
            "expression": expr,
            "variables": dict(variables or {}),
            "computed": computed,
            "expected": float(expected),
            "tolerance": tolerance,
            "abs_diff": diff,
        }
        if diff <= tolerance:
            reasons.append(f"重算结果 {computed} 与期望 {expected} 差异 {diff:.3e} ≤ 容差 {tolerance}")
            return VerificationResult.PASS.value, [evidence], reasons
        reasons.append(f"重算结果 {computed} 与期望 {expected} 差异 {diff:.6g} > 容差 {tolerance}")
        return VerificationResult.FAIL.value, [evidence], reasons

    def _judge_practice(
        self,
        chunk: Chunk,
        method: str,
        code_result: Optional[Mapping[str, Any]],
        evidence: List[Dict[str, Any]],
    ) -> tuple[str, List[Dict[str, Any]], List[str]]:
        if not code_result:
            return VerificationResult.INCONCLUSIVE.value, [], [
                "没有执行结果（code_result），不能声称代码/实验已通过"
            ]
        ok = bool(code_result.get("ok"))
        evidence_item = {
            "kind": method,
            "exit_code": code_result.get("exit_code"),
            "timed_out": bool(code_result.get("timed_out")),
            "duration_ms": code_result.get("duration_ms"),
            "environment": code_result.get("environment", {}),
            "stdout_head": str(code_result.get("stdout", ""))[:500],
            "stderr_head": str(code_result.get("stderr", ""))[:500],
            "isolation": code_result.get("isolation", "process"),
        }
        if ok:
            return (
                VerificationResult.PASS.value,
                [evidence_item],
                [f"{method} 执行成功（exit_code={code_result.get('exit_code')}）"],
            )
        return (
            VerificationResult.FAIL.value,
            [evidence_item],
            [
                f"{method} 执行失败（exit_code={code_result.get('exit_code')}, "
                f"timeout={bool(code_result.get('timed_out'))}）"
            ],
        )

    def _judge_static(self, chunk: Chunk) -> tuple[str, List[str]]:
        code = (chunk.metadata or {}).get("code_blocks") or []
        if not code:
            return VerificationResult.INCONCLUSIVE.value, ["没有可静态检查的代码块"]
        findings = []
        for block in code:
            source = str(block.get("code", ""))
            if re.search(r"\b(eval|exec)\s*\(", source):
                findings.append("代码包含 eval/exec，存在执行风险")
            if re.search(r"\bTODO\b|\bFIXME\b", source):
                findings.append("代码含 TODO/FIXME，可能未完成")
        if findings:
            return VerificationResult.PARTIAL.value, findings
        return (
            VerificationResult.PASS.value,
            ["静态检查未发现明显问题（这不等于代码正确，仍建议执行测试）"],
        )

    def _finish_non_verifiable(self, chunk: Chunk, reasons: List[str]) -> Dict[str, Any]:
        evidence_list = self._normalize_evidence(
            {
                "source_id": chunk.source_id,
                "source_url": chunk.source_url,
                "source_title": chunk.source_title,
                "author_or_publisher": chunk.author_or_publisher,
                "content": chunk.content,
            },
            [],
        )
        record = VerificationRecord(
            record_id=new_id("vrf"),
            chunk_id=chunk.chunk_id,
            method=VerificationMethod.MANUAL_REVIEW.value,
            result=VerificationResult.INCONCLUSIVE.value,
            evidence=evidence_list,
            notes=f"{chunk.knowledge_type} 类型不可核验为事实；已记录来源以便追溯",
            verifier="system",
        )
        self.metadata.add_verification(record.to_row())
        reasons.append(
            f"{chunk.knowledge_type} 属于观点/假设/未解决问题，系统不会把它标记为已验证事实"
        )
        self.metadata.update_chunk(
            chunk.chunk_id,
            {
                "verification_status": "unverifiable",
                "verification_method": VerificationMethod.MANUAL_REVIEW.value,
                "verification_evidence": evidence_list,
                "confidence": min(chunk.confidence, 0.4),
                "confidence_basis": "观点/假设类内容：只保留来源与论据，不判定为事实",
                "updated_at": utcnow_iso(),
            },
        )
        return VerificationOutcome(
            chunk_id=chunk.chunk_id,
            method=VerificationMethod.MANUAL_REVIEW.value,
            result=VerificationResult.INCONCLUSIVE.value,
            status_before=chunk.status,
            status_after=chunk.status,
            level=chunk.level,
            confidence=min(chunk.confidence, 0.4),
            confidence_basis="观点/假设类内容不参与事实核验",
            evidence_count=0,
            independence=len(evidence_list),
            record_id=record.record_id,
            reasons=reasons,
            warnings=["该类型知识永远不能升级为 verified"],
        ).to_dict()


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except ValueError:
        return ""


__all__ = [
    "KnowledgeVerifier",
    "VerificationOutcome",
    "chunk_from_dict",
    "estimate_confidence",
]
