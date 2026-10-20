"""第四组/第六组工具：知识提取、核验与实践。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping

from ..core.models import new_id, utcnow_iso
from ..core.orchestrator import LearningOrchestrator, Runtime
from ..knowledge import classifier as classification
from ..knowledge.conflict_detector import extract_numeric_claims, polarity_profile
from ..knowledge.extractor import (
    extract_concepts,
    extract_formulas,
    identify_assumptions,
    identify_uncertainties,
)
from ..practice.task_generator import evaluate_practice
from ..sources import parser as parsing
from .registry import ToolError, ToolRegistry, ToolSpec


def _require_execution(rt: Runtime, args: Mapping[str, Any], *, action: str, target: str = "", project_id: str = "") -> None:
    decision = rt.permissions.decide(
        action=action,
        risk="execute",
        target=target,
        project_id=project_id,
        confirmed_token=str(args.get("confirm_token") or ""),
    )
    if decision.allowed and not decision.needs_confirmation:
        return
    if decision.needs_confirmation and not args.get("confirm_token"):
        request = rt.permissions.request_confirmation(action, target, project_id)
        raise ToolError(
            f"代码执行需要用户确认：{decision.reason}。"
            f"可在 DSH 审批界面临时批准，或由用户运行 "
            f"`python -m dsh_autonomous_learning.main confirmations approve {request.token}` 后带 confirm_token 重试。",
            "ConfirmationRequired",
        )
    if not decision.allowed:
        raise PermissionError(decision.reason)


def register(reg: ToolRegistry, rt: Runtime, orch: LearningOrchestrator) -> None:
    # ------------------------------------------------------------------ #
    # 提取与分类
    # ------------------------------------------------------------------ #
    def extract_knowledge(args: Dict[str, Any]) -> Dict[str, Any]:
        project_id = args["project_id"]
        project = rt.metadata.get_project(project_id)
        if not project:
            raise ToolError(f"项目不存在: {project_id}", "NotFound")
        document: Dict[str, Any]
        if args.get("document_id"):
            doc = rt.metadata.get("documents", args["document_id"])
            if not doc:
                raise ToolError(f"文档不存在: {args['document_id']}", "NotFound")
            text = Path(doc["content_path"]).read_text(encoding="utf-8")
            source = rt.metadata.get("sources", doc.get("source_id") or "") or {}
            document = {
                **doc,
                "text": text,
                "quality": source.get("quality", 0.5),
                "source_type": source.get("source_type", "unknown"),
                "publisher": source.get("publisher", ""),
                "location": source.get("location", ""),
                "published_at": source.get("published_at", ""),
                "freshness_status": source.get("freshness_status", "unknown"),
                "license_status": source.get("license_status", "unknown"),
            }
        elif args.get("location"):
            read = rt.reader.read(args["location"], project_id=project_id)
            if not read.ok:
                raise ToolError(read.error, "ReadError")
            document = {
                "document_id": "inline_" + new_id("doc"),
                "text": read.text,
                "title": read.title,
                "location": read.location,
                "source_type": read.source_type,
                "quality": (read.metadata or {}).get("quality", 0.5),
                "publisher": (read.metadata or {}).get("publisher", ""),
                "published_at": (read.metadata or {}).get("published_at", ""),
                "freshness_status": (read.metadata or {}).get("freshness_status", "unknown"),
                "license_status": (read.metadata or {}).get("license_status", "unknown"),
                "content_hash": read.content_hash,
            }
        elif args.get("text"):
            document = {
                "document_id": "inline_" + new_id("doc"),
                "text": args["text"],
                "title": args.get("title", "inline"),
                "location": args.get("source_url", ""),
                "source_type": "user_note",
                "quality": float(args.get("source_quality", 0.5)),
                "publisher": "",
                "published_at": args.get("published_at", ""),
                "freshness_status": "unknown",
                "license_status": "unknown",
            }
        else:
            raise ToolError("必须提供 document_id / location / text 之一")

        extraction = rt.extractor.extract(
            project=project,
            document=document,
            topic=str(args.get("topic") or ""),
            use_model=bool(args.get("use_model")),
        )
        drafts = extraction["drafts"]
        persisted = None
        if args.get("persist", True) and drafts:
            persisted = rt.store.add_chunks(drafts)
        return {
            "stats": extraction["stats"],
            "warnings": extraction["warnings"],
            "drafts": [
                {
                    "chunk_id": d["chunk_id"],
                    "title": d["title"],
                    "knowledge_type": d["knowledge_type"],
                    "partition": d["partition"],
                    "summary": d["summary"],
                    "confidence": d["confidence"],
                }
                for d in drafts[:30]
            ],
            "draft_count": len(drafts),
            "persisted": persisted,
            "note": "提取结果默认进入待核验区；未经核验不会被视为事实",
        }

    reg.register(
        ToolSpec(
            name="extract_knowledge",
            description="从文档/文本提取结构化知识草稿（规则优先，可选模型提议），默认入库到待核验分区。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "document_id": {"type": "string"},
                    "location": {"type": "string"},
                    "text": {"type": "string"},
                    "title": {"type": "string"},
                    "topic": {"type": "string"},
                    "source_url": {"type": "string"},
                    "published_at": {"type": "string"},
                    "source_quality": {"type": "number", "minimum": 0, "maximum": 1},
                    "use_model": {"type": "boolean"},
                    "persist": {"type": "boolean"},
                },
                "required": ["project_id"],
            },
            handler=extract_knowledge,
            risk="write",
            side_effects="persist=true 时写入 chunks 与向量索引",
            group="extraction",
        )
    )

    reg.register(
        ToolSpec(
            name="classify_knowledge",
            description="对文本做知识类型与分区分类（可解释打分，低置信度会明确提示）。",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}, "title": {"type": "string"}, "domain": {"type": "string"}},
                "required": ["text"],
            },
            handler=lambda args: classification.classify(
                args["text"], title=args.get("title", ""), domain=args.get("domain", "")
            ).to_dict(),
            group="extraction",
        )
    )

    reg.register(
        ToolSpec(
            name="summarize_knowledge",
            description="抽取式摘要（不调用模型，不改变知识状态）。",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "max_chars": {"type": "integer", "minimum": 40, "maximum": 2000},
                },
                "required": ["text"],
            },
            handler=lambda args: {
                "summary": parsing.summarize(args["text"], int(args.get("max_chars", 160)))
            },
            group="extraction",
        )
    )

    reg.register(
        ToolSpec(
            name="extract_formulas",
            description="从文本提取公式候选（不校验正确性，校验请用 verify_formula）。",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=lambda args: {"formulas": extract_formulas(args["text"])},
            group="extraction",
        )
    )

    reg.register(
        ToolSpec(
            name="extract_concepts",
            description="提取'术语 + 定义'结构（中文'是指/定义为'与英文 'is defined as'）。",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=lambda args: {"concepts": extract_concepts(args["text"])},
            group="extraction",
        )
    )

    reg.register(
        ToolSpec(
            name="identify_assumptions",
            description="识别文本中的假设与前提条件（保留原句，便于后续核验适用条件）。",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=lambda args: {"assumptions": identify_assumptions(args["text"])},
            group="extraction",
        )
    )

    reg.register(
        ToolSpec(
            name="identify_uncertainties",
            description="识别不确定表述（可能/待验证/推测等），降低这些内容的可靠性权重。",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=lambda args: {"uncertainties": identify_uncertainties(args["text"])},
            group="extraction",
        )
    )

    def compare_sources(args: Dict[str, Any]) -> Dict[str, Any]:
        ids = list(args.get("chunk_ids") or [])
        if len(ids) < 2:
            raise ToolError("compare_sources 需要至少 2 个 chunk_id")
        chunks = []
        for chunk_id in ids:
            chunk = rt.metadata.get_chunk(chunk_id)
            if not chunk:
                raise ToolError(f"知识片段不存在: {chunk_id}", "NotFound")
            chunks.append(chunk)
        findings: List[Dict[str, Any]] = []
        for i in range(len(chunks)):
            for j in range(i + 1, len(chunks)):
                for finding in rt.conflicts.detect_pair(chunks[i], chunks[j]):
                    findings.append(finding.to_dict())
        return {
            "compared": [
                {
                    "chunk_id": c["chunk_id"],
                    "title": c["title"],
                    "source": c.get("source_url") or c.get("source_title"),
                    "source_type": c.get("source_type"),
                    "source_quality": c.get("source_quality"),
                    "verification_status": c.get("verification_status"),
                    "status": c.get("status"),
                    "numeric_claims": extract_numeric_claims(c.get("content", ""))[:5],
                    "polarity": sorted(polarity_profile(c.get("content", ""))),
                }
                for c in chunks
            ],
            "disagreements": findings,
            "note": "存在分歧时保留双方结论，不自动采信任何一方；请创建冲突分析任务补充独立证据",
        }

    reg.register(
        ToolSpec(
            name="compare_sources",
            description="比较多个知识片段的来源、说法、数值与极性，列出分歧（不合并、不覆盖）。",
            input_schema={
                "type": "object",
                "properties": {
                    "chunk_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["chunk_ids"],
            },
            handler=compare_sources,
            group="extraction",
        )
    )

    def detect_conflicts(args: Dict[str, Any]) -> Dict[str, Any]:
        if args.get("chunk_id"):
            return rt.conflicts.detect_for(args["chunk_id"], record=bool(args.get("record", True)))
        project_id = args.get("project_id")
        if not project_id:
            raise ToolError("必须提供 chunk_id 或 project_id")
        return rt.conflicts.scan(project_id, limit=int(args.get("limit", 300)), record=bool(args.get("record", True)))

    reg.register(
        ToolSpec(
            name="detect_conflicts",
            description="检测矛盾：数值不一致、极性相反、显式否定；登记冲突并保留双方证据。",
            input_schema={
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "string"},
                    "project_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 2000},
                    "record": {"type": "boolean"},
                },
            },
            handler=detect_conflicts,
            risk="write",
            side_effects="写入 conflicts/edges，并更新 chunks.conflict_status",
            group="extraction",
        )
    )

    # ------------------------------------------------------------------ #
    # 核验与实践
    # ------------------------------------------------------------------ #
    reg.register(
        ToolSpec(
            name="verify_knowledge",
            description="按知识类型核验知识：证据达标才可能升级为 verified，否则保持待核验或转 disputed。",
            input_schema={
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "string"},
                    "method": {
                        "type": "string",
                        "enum": [
                            "source_check",
                            "cross_source",
                            "official_doc_check",
                            "formula_recompute",
                            "code_test",
                            "experiment",
                            "usability_test",
                            "static_analysis",
                            "manual_review",
                        ],
                    },
                    "evidence": {"type": "array", "items": {"type": "object"}},
                    "expression": {"type": "string"},
                    "variables": {"type": "object"},
                    "expected": {"type": "number"},
                    "tolerance": {"type": "number", "minimum": 1e-12, "maximum": 1},
                },
                "required": ["chunk_id"],
            },
            handler=lambda args: rt.verifier.verify(
                args["chunk_id"],
                method=args.get("method"),
                evidence=args.get("evidence"),
                expression=args.get("expression"),
                variables=args.get("variables"),
                expected=args.get("expected"),
                tolerance=float(args.get("tolerance", 1e-6)),
            ),
            group="verification",
        )
    )

    reg.register(
        ToolSpec(
            name="verify_formula",
            description="重算公式并与期望值比较（AST 白名单求值，不执行任意代码）。",
            input_schema={
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "string"},
                    "expression": {"type": "string"},
                    "variables": {"type": "object"},
                    "expected": {"type": "number"},
                    "tolerance": {"type": "number", "minimum": 1e-12, "maximum": 1},
                },
                "required": ["chunk_id"],
            },
            handler=lambda args: rt.verifier.verify_formula(
                args["chunk_id"],
                expression=args.get("expression"),
                variables=args.get("variables"),
                expected=args.get("expected"),
                tolerance=float(args.get("tolerance", 1e-6)),
            ),
            group="verification",
        )
    )

    def run_code_test(args: Dict[str, Any]) -> Dict[str, Any]:
        _require_execution(
            rt, args, action="run_code_test", target=str(args.get("project_id") or ""), project_id=str(args.get("project_id") or "")
        )
        return rt.runner.run(
            code=args["code"],
            language=args.get("language", "python"),
            trusted=bool(args.get("trusted")),
            practice_id=args.get("practice_id"),
            project_id=str(args.get("project_id") or ""),
            timeout_s=args.get("timeout_s"),
        )

    reg.register(
        ToolSpec(
            name="run_code_test",
            description="在受限目录执行 Python 代码并记录环境/输出/退出码（lab 模式；进程级隔离，非安全沙箱）。",
            input_schema={
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "language": {"type": "string", "enum": ["python", "py"]},
                    "trusted": {"type": "boolean", "description": "代码是否可信（外部代码请保持 false）"},
                    "practice_id": {"type": "string"},
                    "project_id": {"type": "string"},
                    "timeout_s": {"type": "integer", "minimum": 1, "maximum": 300},
                    "confirm_token": {"type": "string"},
                },
                "required": ["code"],
            },
            handler=run_code_test,
            risk="execute",
            side_effects="在 data/experiments 下创建产物目录并写入 practice_results",
            requires_confirmation=True,
            group="verification",
        )
    )

    def run_experiment(args: Dict[str, Any]) -> Dict[str, Any]:
        project_id = args["project_id"]
        _require_execution(rt, args, action="run_learning_experiment", target=project_id, project_id=project_id)
        return rt.experiments.run(
            project_id=project_id,
            spec=args["spec"],
            task_id=str(args.get("task_id") or ""),
            trusted=bool(args.get("trusted")),
        )

    reg.register(
        ToolSpec(
            name="run_learning_experiment",
            description="执行受控实验（spec 含 code 与断言），记录 spec/产物/结果，失败也保留证据。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "spec": {"type": "object"},
                    "task_id": {"type": "string"},
                    "trusted": {"type": "boolean"},
                    "confirm_token": {"type": "string"},
                },
                "required": ["project_id", "spec"],
            },
            handler=run_experiment,
            risk="execute",
            side_effects="创建实验产物目录并写入 experiments",
            requires_confirmation=True,
            group="verification",
        )
    )

    def create_practice(args: Dict[str, Any]) -> Dict[str, Any]:
        if args.get("chunk_id"):
            return rt.practice_gen.from_chunk(args["chunk_id"], kind=args.get("kind"))
        if not args.get("project_id"):
            raise ToolError("必须提供 chunk_id 或 project_id")
        return rt.practice_gen.generate(args["project_id"], limit=int(args.get("limit", 5)))

    reg.register(
        ToolSpec(
            name="create_practice_task",
            description="为知识生成练习任务（公式重算/代码执行/概念问答/流程清单），不可自动判分的类型会说明原因。",
            input_schema={
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "string"},
                    "project_id": {"type": "string"},
                    "kind": {"type": "string", "enum": ["formula", "code_example", "definition", "procedure", "experiment", "self_check"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
            },
            handler=create_practice,
            risk="write",
            side_effects="写入 practice_tasks",
            group="practice",
        )
    )

    def evaluate_practice_result(args: Dict[str, Any]) -> Dict[str, Any]:
        practice = rt.metadata.get_practice(args["practice_id"])
        if not practice:
            raise ToolError(f"练习任务不存在: {args['practice_id']}", "NotFound")
        result = args.get("result")
        if result is None:
            rows = rt.metadata.list_practice_results(args["practice_id"])
            result = rows[-1] if rows else None
        evaluation = evaluate_practice(practice, result)
        rt.metadata.update("practice_tasks", args["practice_id"], {"status": evaluation["status"]})
        return {"practice": {"practice_id": practice["practice_id"], "kind": practice["kind"]}, "evaluation": evaluation}

    reg.register(
        ToolSpec(
            name="evaluate_practice_result",
            description="评估实践结果：没有执行结果就判为未完成；规则评分会明确标注需要人工复核。",
            input_schema={
                "type": "object",
                "properties": {
                    "practice_id": {"type": "string"},
                    "result": {"type": "object"},
                },
                "required": ["practice_id"],
            },
            handler=evaluate_practice_result,
            risk="write",
            side_effects="更新 practice_tasks.status",
            group="practice",
        )
    )

    reg.register(
        ToolSpec(
            name="record_experiment_result",
            description="记录人工/外部执行得到的实验结果（不运行代码），作为知识核验证据。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "spec": {"type": "object"},
                    "result": {"type": "object"},
                    "task_id": {"type": "string"},
                },
                "required": ["project_id", "spec", "result"],
            },
            handler=lambda args: rt.experiments.record_result(
                project_id=args["project_id"],
                spec=args["spec"],
                result=args["result"],
                task_id=str(args.get("task_id") or ""),
            ),
            risk="write",
            side_effects="写入 experiments",
            group="practice",
        )
    )


__all__ = ["register"]
