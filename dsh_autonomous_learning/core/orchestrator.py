"""自主学习编排器。

一轮学习的循环（规则 2 的闭环）：

    取出就绪任务 → 执行 → 记录证据 → 更新知识状态 → 检查预算/停止条件
    → 评估 → 生成补充任务 → 决定继续/暂停/完成

设计原则：
- 每个任务可断点续跑：状态、次数、错误、结果都落库；
- 预算与停止条件在循环内实时检查，不靠模型"自觉"；
- 任何"成功"都必须有可验证产物（来源、核验记录、执行结果）；
- 没有新知识且连续多轮无进展时主动停止，不无限循环。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ..config import Config, read_host_settings
from ..knowledge.classifier import classify
from ..knowledge.conflict_detector import ConflictDetector
from ..knowledge.deduplicator import Deduplicator
from ..knowledge.extractor import KnowledgeExtractor
from ..knowledge.knowledge_graph import KnowledgeGraph
from ..knowledge.partitions import (
    default_visibility,
    partition_for_domain,
    project_partitions,
)
from ..knowledge.partitions import ensure_partition_allowed
from ..knowledge.verifier import KnowledgeVerifier
from ..knowledge.version_manager import VersionManager
from ..practice.experiment_runner import ExperimentRunner
from ..practice.task_generator import PracticeTaskGenerator
from ..practice.test_runner import CodeTestRunner
from ..security.execution_policy import ExecutionPolicy
from ..security.permissions import PermissionManager
from ..sources.discovery import SourceDiscovery
from ..sources.metadata import describe_source
from ..sources.reader import SourceReader
from ..storage.metadata_store import ChunkFilter, MetadataStore, StorageError
from ..storage.vector_store import KnowledgeStore, KnowledgeStoreError
from .budget import BudgetExceeded, BudgetTracker
from .embedder import build_embedder
from .evaluator import LearningEvaluator
from .gap_analyzer import KnowledgeGapAnalyzer
from .model_adapter import BaseModel, build_model
from .models import (
    Document,
    KnowledgeStatus,
    LearningLevel,
    Partition,
    Project,
    ProjectStatus,
    Run,
    RunStatus,
    Source,
    TaskKind,
    TaskStatus,
    new_id,
    utcnow_iso,
)
from .planner import LearningPlanner
from .reporter import ReportGenerator


@dataclass
class Runtime:
    """一次进程内共享的依赖集合（避免各处重复构造）。"""

    config: Config
    metadata: MetadataStore
    store: KnowledgeStore
    model: BaseModel
    permissions: PermissionManager
    reader: SourceReader
    discovery: SourceDiscovery
    planner: LearningPlanner
    extractor: KnowledgeExtractor
    verifier: KnowledgeVerifier
    dedup: Deduplicator
    conflicts: ConflictDetector
    graph: KnowledgeGraph
    versions: VersionManager
    gaps: KnowledgeGapAnalyzer
    evaluator: LearningEvaluator
    practice_gen: PracticeTaskGenerator
    runner: CodeTestRunner
    experiments: ExperimentRunner
    reporter: ReportGenerator
    policy: ExecutionPolicy

    def close(self) -> None:
        self.metadata.close()

    def apply_settings(self) -> Dict[str, Any]:
        """重读 DSH 设置卡写入的 settings.json。

        模式、每日预算、单轮任务上限即时生效（每轮开始时调用）；
        数据目录涉及数据库与索引的打开位置，只能在下次 MCP 连接时生效。
        """

        home = Path(self.config.paths.home)
        data = read_host_settings(home)
        result: Dict[str, Any] = {
            "mode": self.permissions.mode,
            "daily_budget_usd": self.config.learning.daily_budget_usd,
            "max_tasks_per_run": self.config.learning.max_tasks_per_run,
        }
        mode = data.get("mode")
        if isinstance(mode, str) and mode in {"assisted", "auto", "lab"}:
            self.permissions.set_mode(mode)
            self.policy.mode = mode
            result["mode"] = mode
        budget = data.get("dailyBudgetUsd")
        if isinstance(budget, (int, float)) and not isinstance(budget, bool) and 0 <= float(budget) <= 1000:
            self.config.learning.daily_budget_usd = float(budget)
            result["daily_budget_usd"] = float(budget)
        tasks = data.get("maxTasksPerRun")
        if isinstance(tasks, int) and not isinstance(tasks, bool) and 1 <= tasks <= 200:
            self.config.learning.max_tasks_per_run = tasks
            result["max_tasks_per_run"] = tasks
        data_dir = data.get("dataDir")
        if isinstance(data_dir, str) and data_dir.strip() and data_dir.strip() != self.config.paths.data_dir:
            result["data_dir_pending"] = data_dir.strip()
        return result


def build_runtime(config: Config, *, mode: Optional[str] = None) -> Runtime:
    """按配置组装运行时。所有目录在这里就绪。"""

    config.paths.ensure()
    metadata = MetadataStore(config.paths.db_path)
    metadata.migrate()
    embedder = build_embedder(config.embedding)
    store = KnowledgeStore(metadata, config.paths.index_dir, embedder, config.retrieval)
    model = build_model(config.model)
    permissions = PermissionManager(
        config.security,
        config.learning,
        metadata,
        mode=mode,
        data_dir=config.paths.data_dir,
    )
    policy = ExecutionPolicy(config.security, config.learning, mode=permissions.mode)
    reader = SourceReader(config.security, permissions)
    discovery = SourceDiscovery(config.security, corpus_dir=config.paths.corpus_dir)
    planner = LearningPlanner(metadata, config.learning, model)
    extractor = KnowledgeExtractor(config.learning, model)
    verifier = KnowledgeVerifier(store, metadata)
    evaluator = LearningEvaluator(metadata, config.learning)
    runtime = Runtime(
        config=config,
        metadata=metadata,
        store=store,
        model=model,
        permissions=permissions,
        reader=reader,
        discovery=discovery,
        planner=planner,
        extractor=extractor,
        verifier=verifier,
        dedup=Deduplicator(store, metadata),
        conflicts=ConflictDetector(store, metadata),
        graph=KnowledgeGraph(metadata),
        versions=VersionManager(store, metadata),
        gaps=KnowledgeGapAnalyzer(metadata),
        evaluator=evaluator,
        practice_gen=PracticeTaskGenerator(store, metadata, config.learning),
        runner=CodeTestRunner(policy, metadata, config.paths.experiments_dir),
        experiments=ExperimentRunner(policy, metadata, config.paths.experiments_dir),
        reporter=ReportGenerator(metadata, store, evaluator, config.paths.reports_dir),
        policy=policy,
    )
    return runtime


class LearningOrchestrator:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime
        self.cfg = runtime.config.learning
        self.metadata = runtime.metadata
        self.store = runtime.store

    # ------------------------------------------------------------------ #
    # 项目管理
    # ------------------------------------------------------------------ #
    def create_project(
        self,
        *,
        goal: str,
        title: str = "",
        domain: str = "general",
        depth: str = "working",
        mode: Optional[str] = None,
        partitions: Optional[List[str]] = None,
        acceptance_criteria: Optional[List[str]] = None,
        deliverables: Optional[List[str]] = None,
        allowed_sources: Optional[List[str]] = None,
        budget: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not (goal or "").strip():
            raise ValueError("学习目标 goal 不能为空")
        if depth not in {"overview", "working", "deep"}:
            raise ValueError("depth 必须是 overview/working/deep")
        chosen_mode = mode or self.rt.permissions.mode
        allowed_partitions = partitions or project_partitions(domain)
        for part in allowed_partitions:
            ensure_partition_allowed(None, part)
        project = Project(
            project_id=new_id("prj"),
            title=title or (goal.strip()[:40]),
            goal=goal.strip(),
            domain=domain,
            partitions=allowed_partitions,
            depth=depth,
            mode=chosen_mode,
            acceptance_criteria=acceptance_criteria or [],
            deliverables=deliverables or [],
            allowed_sources=allowed_sources or [],
            budget=budget or {},
            scope={"explicit_acceptance": bool(acceptance_criteria)},
        )
        self.metadata.create_project(project.to_row())
        self.rt.permissions.audit.log(
            action="create_learning_project",
            target=project.project_id,
            risk="write",
            allowed=True,
            project_id=project.project_id,
            detail={"goal": goal[:200], "domain": domain, "mode": chosen_mode},
        )
        self.metadata.record_metric("project", "created", 1, project.project_id)
        return self.get_project(project.project_id)

    def get_project(self, project_id: str) -> Dict[str, Any]:
        project = self.metadata.get_project(project_id)
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        counts = self.metadata.task_counts(project_id)
        chunks = self.metadata.count_chunks(ChunkFilter(project_id=project_id))
        return {
            "project": project,
            "tasks": counts,
            "chunks": chunks,
            "budget_config": {
                "max_iterations_per_run": self.cfg.max_iterations_per_run,
                "max_tasks_per_run": self.cfg.max_tasks_per_run,
                "max_sources_per_task": self.cfg.max_sources_per_task,
                "daily_budget_usd": self.cfg.daily_budget_usd,
            },
        }

    def list_projects(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.metadata.list_projects(status)

    def set_status(self, project_id: str, status: str) -> Dict[str, Any]:
        ProjectStatus.parse(status, "status")
        self.metadata.update_project(project_id, {"status": status})
        self.rt.permissions.audit.log(
            action=f"project_{status}", target=project_id, risk="write", allowed=True, project_id=project_id
        )
        return {"project_id": project_id, "status": status}

    # ------------------------------------------------------------------ #
    # 规划
    # ------------------------------------------------------------------ #
    def plan(self, project_id: str, *, use_model: bool = False) -> Dict[str, Any]:
        project = self.metadata.get_project(project_id)
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        existing = self.metadata.list_tasks(project_id)
        if existing:
            return {
                "project_id": project_id,
                "already_planned": True,
                "task_count": len(existing),
                "tasks": existing,
            }
        result = self.rt.planner.create_plan(project, use_model=use_model)
        self.metadata.record_metric("plan", "tasks_created", result["task_count"], project_id)
        return result

    # ------------------------------------------------------------------ #
    # 主循环
    # ------------------------------------------------------------------ #
    def run_round(
        self,
        project_id: str,
        *,
        max_tasks: Optional[int] = None,
        use_model: bool = False,
    ) -> Dict[str, Any]:
        project = self.metadata.get_project(project_id)
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        if project["status"] != ProjectStatus.ACTIVE.value:
            return {
                "project_id": project_id,
                "started": False,
                "reason": f"项目状态为 {project['status']}，不是 active，拒绝运行",
            }

        # 设置卡可能在两轮之间被改过：模式/预算/任务上限在这里刷新
        settings = self.rt.apply_settings()

        if not self.metadata.list_tasks(project_id):
            self.plan(project_id, use_model=use_model)

        self.recover(project_id)
        iteration = self.metadata.next_iteration(project_id)
        run = Run(
            run_id=new_id("run"),
            project_id=project_id,
            iteration=iteration,
            status=RunStatus.RUNNING.value,
        )
        self.metadata.start_run(run.to_row())

        tracker = BudgetTracker(
            self.cfg,
            self.rt.config.model,
            self.metadata,
            run_id=run.run_id,
            project_id=project_id,
            daily_spent=self._today_spend(),
        )
        tracker.set_iteration(iteration)

        executed: List[Dict[str, Any]] = []
        new_knowledge = 0
        stop_reason = ""
        limit = max_tasks or self.cfg.max_tasks_per_run
        error: str = ""

        try:
            for _ in range(limit):
                should_stop, why = tracker.should_stop()
                if should_stop:
                    stop_reason = why
                    break
                ready = self.metadata.next_ready_tasks(project_id, limit=1)
                if not ready:
                    stop_reason = "no_ready_tasks"
                    break
                task = ready[0]
                try:
                    result = self._execute_task(task, tracker, use_model=use_model, run_id=run.run_id)
                except BudgetExceeded as exc:
                    stop_reason = exc.dimension or "budget_exceeded"
                    executed.append({"task_id": task["task_id"], "status": "blocked", "error": str(exc)})
                    break
                except Exception as exc:  # noqa: BLE001 - 单任务失败不拖垮整轮
                    self._handle_task_failure(task, exc)
                    executed.append(
                        {
                            "task_id": task["task_id"],
                            "kind": task["kind"],
                            "status": self.metadata.get_task(task["task_id"])["status"],
                            "error": str(exc)[:500],
                        }
                    )
                    continue
                added = int(result.get("new_knowledge", 0) or 0)
                new_knowledge += added
                if task["kind"] == TaskKind.DISCOVER.value:
                    tracker.consume_sources(int(result.get("sources_saved", 0) or 0))
                executed.append(
                    {
                        "task_id": task["task_id"],
                        "kind": task["kind"],
                        "title": task["title"],
                        "status": "completed",
                        "new_knowledge": added,
                        "details": {
                            k: v for k, v in result.items() if k not in {"drafts", "chunks"} and not isinstance(v, list)
                        },
                    }
                )
                try:
                    tracker.finish_task(added, progress=(added > 0 or result.get("progress", False)))
                except BudgetExceeded as exc:
                    stop_reason = exc.dimension or "no_progress"
                    break
                # 每完成一个任务就重新评估是否仍有价值继续
                if stop_reason:
                    break
            if not stop_reason and self.cfg.stop_when_no_new_knowledge:
                if self._rounds_without_progress(project_id, exclude_run_id=run.run_id) >= self.cfg.no_progress_rounds:
                    stop_reason = "no_progress"
            if not stop_reason:
                # 达到本轮任务上限（而不是"没有任务可做"）
                if self.metadata.next_ready_tasks(project_id, limit=1):
                    stop_reason = (
                        "max_tasks_per_run" if limit >= self.cfg.max_tasks_per_run else "task_limit_reached"
                    )
        finally:
            evaluation = self._safe_evaluate(project_id)
            summary = {
                "run_id": run.run_id,
                "iteration": iteration,
                "tasks_executed": len(executed),
                "new_knowledge": new_knowledge,
                "stop_reason": stop_reason,
                "budget": tracker.snapshot(),
                "goal_met": bool(evaluation.get("goal_met")),
                "coverage_rate": evaluation.get("metrics", {}).get("coverage_rate", 0.0),
                "remaining": evaluation.get("remaining", [])[:10],
                "error": error,
            }
            status = RunStatus.STOPPED.value if stop_reason else RunStatus.COMPLETED.value
            if stop_reason == "error":
                status = RunStatus.FAILED.value
            self.metadata.finish_run(run.run_id, status, summary, stop_reason)
            self.metadata.record_metric("run", "new_knowledge", new_knowledge, project_id, run.run_id)
            if evaluation.get("goal_met"):
                # 不自动把项目标记 completed：需要人工评审确认
                summary["note"] = "量化指标已达标，等待人工评审确认后才算完成"

        return {
            "project_id": project_id,
            "run_id": run.run_id,
            "iteration": iteration,
            "tasks_executed": executed,
            "new_knowledge": new_knowledge,
            "stop_reason": stop_reason,
            "budget": tracker.snapshot(),
            "evaluation": evaluation,
            "settings": settings,
            "continue_recommended": self._should_continue(project_id, evaluation, stop_reason),
        }

    # ------------------------------------------------------------------ #
    # 任务执行
    # ------------------------------------------------------------------ #
    def _execute_task(
        self, task: Mapping[str, Any], tracker: BudgetTracker, *, use_model: bool, run_id: str
    ) -> Dict[str, Any]:
        task_id = task["task_id"]
        self.metadata.update_task(
            task_id,
            {
                "status": TaskStatus.RUNNING.value,
                "attempts": int(task.get("attempts", 0)) + 1,
                "started_at": utcnow_iso(),
                "error": "",
            },
        )
        tracker.start_task()
        kind = task["kind"]
        project_id = task["project_id"]
        self.metadata.record_metric("task", f"start:{kind}", 1, project_id, run_id)

        if kind == TaskKind.PLAN.value:
            result = self.plan(project_id, use_model=use_model)
            result = {"new_knowledge": 0, "progress": True, "tasks_created": result.get("task_count", 0)}
        elif kind == TaskKind.GAP_ANALYSIS.value:
            result = self.rt.gaps.analyze(project_id)
            result = {
                "new_knowledge": 0,
                "progress": True,
                "coverage_rate": result["coverage_rate"],
                "gaps": len(result["gaps"]),
            }
        elif kind == TaskKind.DISCOVER.value:
            result = self._task_discover(task)
        elif kind == TaskKind.EXTRACT.value:
            result = self._task_extract(task, use_model=use_model)
        elif kind == TaskKind.VERIFY.value:
            result = self._task_verify(task)
        elif kind == TaskKind.PRACTICE.value:
            result = self._task_practice(task)
        elif kind == TaskKind.EVALUATE.value:
            result = self._task_evaluate(task)
        elif kind == TaskKind.REPORT.value:
            report = self.rt.reporter.generate(project_id, run_id=run_id)
            result = {
                "new_knowledge": 0,
                "progress": True,
                "report_path": report["report_path"],
                "goal_met": report["summary"].get("goal_met", False),
            }
        else:
            raise ValueError(f"未知任务类型: {kind}")

        self.metadata.update_task(
            task_id,
            {
                "status": TaskStatus.COMPLETED.value,
                "finished_at": utcnow_iso(),
                "result": {k: v for k, v in result.items() if isinstance(v, (int, float, str, bool, list, dict))},
                "error": "",
            },
        )
        self.metadata.record_metric("task", f"done:{kind}", 1, project_id, run_id)
        return result

    def _handle_task_failure(self, task: Mapping[str, Any], exc: Exception) -> None:
        attempts = int(task.get("attempts", 0)) + 1
        max_retries = int(task.get("max_retries", self.cfg.max_retries_per_task))
        if attempts <= max_retries:
            status = TaskStatus.RETRYING.value
        else:
            status = TaskStatus.FAILED.value
        self.metadata.update_task(
            task["task_id"],
            {
                "status": status,
                "attempts": attempts,
                "error": str(exc)[:1000],
                "finished_at": utcnow_iso() if status == TaskStatus.FAILED.value else "",
            },
        )
        self.rt.permissions.audit.log(
            action="task_failed",
            target=task["task_id"],
            risk="write",
            allowed=False,
            project_id=task["project_id"],
            detail={"kind": task["kind"], "error": str(exc)[:300], "status": status},
        )

    # ------------------------------------------------------------------ #
    # 具体任务
    # ------------------------------------------------------------------ #
    def _task_discover(self, task: Mapping[str, Any]) -> Dict[str, Any]:
        project = self.metadata.get_project(task["project_id"])
        if not project:
            raise ValueError("项目不存在")
        topic = str((task.get("inputs") or {}).get("topic") or "")
        locations = list((task.get("inputs") or {}).get("locations") or project.get("allowed_sources") or [])
        found = self.rt.discovery.discover(
            topics=[topic] if topic else [],
            explicit_locations=locations,
            keywords=[topic] if topic else [],
            limit=self.cfg.max_sources_per_task,
        )

        warnings = list(found.get("warnings", []))
        saved: List[Dict[str, Any]] = []
        failures: List[Dict[str, Any]] = []
        for candidate in found["candidates"][: self.cfg.max_sources_per_task]:
            read = self.rt.reader.read(candidate["location"], project_id=project["project_id"])
            if not read.ok:
                failures.append({"location": candidate["location"], "error": read.error})
                source = Source(
                    source_id=new_id("src"),
                    project_id=project["project_id"],
                    source_type=candidate.get("source_type", "unknown"),
                    location=candidate["location"],
                    title=candidate.get("title", ""),
                    fetch_ok=False,
                    error=read.error[:500],
                )
                self.metadata.insert("sources", source.to_row())
                continue
            existing = self.metadata.query_dicts(
                "SELECT source_id FROM sources WHERE project_id=? AND content_hash=? LIMIT 1",
                (project["project_id"], read.content_hash),
            )
            if existing:
                warnings.append(f"内容重复，已跳过: {candidate['location']}")
                continue

            try:
                saved_item = self.ingest_document(project["project_id"], read, topic=topic)
            except StorageError as exc:
                failures.append({"location": candidate["location"], "error": str(exc)})
                continue
            saved.append(saved_item)

        if saved:
            self.rt.permissions.audit.log(
                action="discover_sources",
                target=f"{len(saved)} sources",
                risk="write",
                allowed=True,
                project_id=project["project_id"],
                detail={"topic": topic, "sources": [s["location"] for s in saved][:10]},
            )
        return {
            "new_knowledge": 0,
            "progress": bool(saved),
            "sources_saved": len(saved),
            "documents": saved,
            "failures": failures,
            "warnings": warnings[:20],
        }

    def ingest_document(self, project_id: str, read: Any, *, topic: str = "") -> Dict[str, Any]:
        """把一次成功的读取结果落库（来源 + 文档），供工具与编排器复用。"""

        if not getattr(read, "ok", False):
            raise StorageError(getattr(read, "error", "读取失败"))
        info = read.metadata or {}
        source = Source(
            source_id=new_id("src"),
            project_id=project_id,
            source_type=read.source_type,
            location=read.location,
            title=read.title,
            publisher=info.get("publisher", ""),
            published_at=info.get("published_at", ""),
            accessed_at=utcnow_iso(),
            license_status=info.get("license_status", "unknown"),
            quality=float(info.get("quality", 0.5) or 0.5),
            quality_basis=info.get("quality_basis", ""),
            freshness_status=info.get("freshness_status", "unknown"),
            content_hash=read.content_hash,
            fetch_ok=True,
            metadata={"bytes": read.bytes_read, "doc_type": read.doc_type, "topic": topic},
        )
        self.metadata.insert("sources", source.to_row())

        document_id = new_id("doc")
        content_path = Path(self.rt.config.paths.documents_dir) / f"{document_id}.txt"
        content_path.write_text(read.text, encoding="utf-8")
        document = Document(
            document_id=document_id,
            project_id=project_id,
            source_id=source.source_id,
            title=read.title,
            doc_type=read.doc_type,
            language=info.get("language", "unknown"),
            content_path=str(content_path),
            content_hash=read.content_hash,
            char_count=len(read.text),
            parser=read.doc_type,
            parse_status="parsed",
        )
        self.metadata.insert("documents", document.to_row())
        return {
            "source_id": source.source_id,
            "document_id": document_id,
            "location": read.location,
            "chars": len(read.text),
            "source_type": read.source_type,
            "quality": source.quality,
        }

    def _task_extract(self, task: Mapping[str, Any], *, use_model: bool) -> Dict[str, Any]:
        project = self.metadata.get_project(task["project_id"])
        if not project:
            raise ValueError("项目不存在")
        topic = str((task.get("inputs") or {}).get("topic") or "")
        docs = self.metadata.query_dicts(
            "SELECT * FROM documents WHERE project_id=? AND parse_status='parsed' ORDER BY created_at LIMIT ?",
            (project["project_id"], self.cfg.max_sources_per_task),
        )
        added = 0
        processed = 0
        warnings: List[str] = []
        for doc in docs:
            try:
                text = Path(doc["content_path"]).read_text(encoding="utf-8")
            except OSError as exc:
                warnings.append(f"文档读取失败 {doc['document_id']}: {exc}")
                self.metadata.update("documents", doc["document_id"], {"parse_status": "error", "error": str(exc)})
                continue
            source = self.metadata.get("sources", doc["source_id"]) or {}
            payload = {
                **doc,
                "text": text,
                "quality": source.get("quality", 0.5),
                "source_type": source.get("source_type", "unknown"),
                "publisher": source.get("publisher", ""),
                "location": source.get("location", ""),
                "published_at": source.get("published_at", ""),
                "freshness_status": source.get("freshness_status", "unknown"),
                "license_status": source.get("license_status", "unknown"),
                "title": doc.get("title") or source.get("title", ""),
                "language": doc.get("language", "unknown"),
            }
            extraction = self.rt.extractor.extract(
                project=project, document=payload, topic=topic, use_model=use_model
            )
            drafts = extraction["drafts"]
            if drafts:
                result = self.store.add_chunks(drafts)
                added += int(result.get("added", 0)) + int(result.get("updated", 0))
            warnings.extend(extraction.get("warnings", []))
            self.metadata.update("documents", doc["document_id"], {"parse_status": "extracted"})
            processed += 1

        if added:
            self.metadata.record_metric("knowledge", "added", added, project["project_id"])
        return {
            "new_knowledge": added,
            "progress": processed > 0,
            "documents_processed": processed,
            "chunks_added": added,
            "warnings": warnings[:20],
        }

    def _task_verify(self, task: Mapping[str, Any]) -> Dict[str, Any]:
        project_id = task["project_id"]
        topic = str((task.get("inputs") or {}).get("topic") or "")
        filters = ChunkFilter(
            project_id=project_id,
            statuses=[KnowledgeStatus.PENDING_VERIFICATION.value],
            topics=[topic] if topic else None,
        )
        chunks = self.metadata.list_chunks(filters, limit=40)
        verified = 0
        attempted = 0
        failures: List[Dict[str, Any]] = []
        warnings: List[str] = []
        for chunk in chunks:
            attempted += 1
            try:
                outcome = self.rt.verifier.verify(chunk["chunk_id"])
            except Exception as exc:  # noqa: BLE001
                failures.append({"chunk_id": chunk["chunk_id"], "error": str(exc)})
                continue
            if outcome["status_after"] == KnowledgeStatus.VERIFIED.value:
                verified += 1
            warnings.extend(outcome.get("warnings", []))

        promoted = self._promote_verified(project_id)
        return {
            "new_knowledge": 0,
            "progress": attempted > 0,
            "attempted": attempted,
            "verified": verified,
            "promoted": promoted,
            "failures": failures[:10],
            "warnings": warnings[:20],
        }

    def _promote_verified(self, project_id: str) -> int:
        """把已核验知识从待审区迁到领域分区（assisted 模式需人工确认，不自动迁移）。"""

        if self.rt.permissions.mode == "assisted":
            return 0
        project = self.metadata.get_project(project_id) or {}
        rows = self.metadata.list_chunks(
            ChunkFilter(
                project_id=project_id,
                partitions=["pending_knowledge"],
                statuses=[KnowledgeStatus.VERIFIED.value],
            ),
            limit=50,
        )
        promoted = 0
        for row in rows:
            target = partition_for_domain(row.get("domain") or project.get("domain") or "general")
            if target == "pending_knowledge":
                continue
            allowed = project.get("partitions") or []
            if allowed and target not in allowed:
                continue
            self.metadata.update_chunk(row["chunk_id"], {"partition": target, "visibility": default_visibility(target)})
            promoted += 1
        return promoted

    def _task_practice(self, task: Mapping[str, Any]) -> Dict[str, Any]:
        project_id = task["project_id"]
        generated = self.rt.practice_gen.generate(project_id, limit=5)
        executed = 0
        skipped: List[Dict[str, Any]] = []
        results: List[Dict[str, Any]] = []
        for item in generated["tasks"]:
            spec = item.get("spec") or {}
            if item["kind"] == "formula":
                if spec.get("expected") is None:
                    skipped.append({"practice_id": item["practice_id"], "reason": "缺少期望值，无法重算"})
                    continue
                outcome = self.rt.verifier.verify_formula(
                    item["chunk_id"],
                    expression=(spec.get("expressions") or [None])[0],
                    variables=spec.get("variables") or {},
                    expected=spec.get("expected"),
                )
                executed += 1
                results.append({"practice_id": item["practice_id"], "result": outcome["result"]})
            elif item["kind"] == "code_example":
                if self.rt.permissions.mode != "lab":
                    skipped.append(
                        {
                            "practice_id": item["practice_id"],
                            "reason": "代码执行仅在 lab 模式允许（当前 "
                            + self.rt.permissions.mode
                            + "）",
                        }
                    )
                    continue
                try:
                    payload = self.rt.runner.run(
                        code=spec.get("code", ""),
                        trusted=False,
                        practice_id=item["practice_id"],
                        project_id=project_id,
                    )
                    executed += 1
                    results.append(
                        {
                            "practice_id": item["practice_id"],
                            "ok": payload.get("ok"),
                            "exit_code": payload.get("exit_code"),
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    skipped.append({"practice_id": item["practice_id"], "reason": str(exc)})
            else:
                skipped.append({"practice_id": item["practice_id"], "reason": "该类型不做自动判分"})
        return {
            "new_knowledge": 0,
            "progress": executed > 0,
            "generated": len(generated["tasks"]),
            "executed": executed,
            "results": results[:10],
            "skipped": skipped[:10],
        }

    def _task_evaluate(self, task: Mapping[str, Any]) -> Dict[str, Any]:
        project_id = task["project_id"]
        evaluation = self.rt.evaluator.evaluate(project_id)
        created = 0
        project = self.metadata.get_project(project_id) or {}
        for gap in evaluation.get("gaps", [])[:3]:
            if gap.get("kind") == "duplicates":
                continue
            try:
                created += len(self.rt.planner.tasks_for_gap(project, gap))
            except Exception:  # noqa: BLE001
                continue
        for conflict in self.metadata.list_conflicts(project_id=project_id, status="open")[:3]:
            try:
                created += len(self.rt.planner.tasks_for_conflict(project, conflict))
            except Exception:  # noqa: BLE001
                continue
        return {
            "new_knowledge": 0,
            "progress": True,
            "goal_met": evaluation["goal_met"],
            "coverage_rate": evaluation["metrics"]["coverage_rate"],
            "verification_rate": evaluation["metrics"]["verification_rate"],
            "remaining": evaluation["remaining"],
            "followup_tasks": created,
        }

    # ------------------------------------------------------------------ #
    # 恢复 / 停止 / 辅助
    # ------------------------------------------------------------------ #
    def recover(self, project_id: str) -> Dict[str, Any]:
        """把崩溃/中断留下的 running 任务恢复到可重试状态。"""

        rows = self.metadata.query_dicts(
            "SELECT * FROM tasks WHERE project_id=? AND status='running'", (project_id,)
        )
        recovered = []
        now = datetime.now(timezone.utc)
        for row in rows:
            started = row.get("started_at") or ""
            stale = True
            try:
                dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                stale = (now - dt) > timedelta(seconds=max(60, int(row.get("timeout_s", 300))))
            except ValueError:
                stale = True
            if not stale:
                continue
            attempts = int(row.get("attempts", 0))
            max_retries = int(row.get("max_retries", 3))
            status = TaskStatus.RETRYING.value if attempts <= max_retries else TaskStatus.FAILED.value
            self.metadata.update_task(
                row["task_id"],
                {
                    "status": status,
                    "error": (row.get("error") or "") + "\n[recover] 检测到中断的运行状态",
                    "started_at": "",
                },
            )
            recovered.append({"task_id": row["task_id"], "status": status})
        return {"recovered": recovered, "count": len(recovered)}

    def _safe_evaluate(self, project_id: str) -> Dict[str, Any]:
        try:
            return self.rt.evaluator.evaluate(project_id)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc), "goal_met": False, "metrics": {}, "remaining": [str(exc)]}

    def _should_continue(self, project_id: str, evaluation: Mapping[str, Any], stop_reason: str) -> bool:
        if stop_reason in {"daily_budget", "max_llm_calls_per_run", "max_tasks_per_run", "no_progress"}:
            return False
        if evaluation.get("goal_met"):
            return False
        return bool(self.metadata.next_ready_tasks(project_id, limit=1))

    def _rounds_without_progress(self, project_id: str, *, exclude_run_id: str = "") -> int:
        """最近连续多少轮没有产生任何新知识（按轮统计，而不是按任务）。"""

        runs = [
            r
            for r in self.metadata.last_runs(project_id, limit=self.cfg.no_progress_rounds + 1)
            if r.get("run_id") != exclude_run_id
        ]
        count = 0
        for run in runs[: self.cfg.no_progress_rounds]:
            summary = run.get("summary") or {}
            if int(summary.get("new_knowledge", 0) or 0) == 0:
                count += 1
            else:
                break
        return count

    def _today_spend(self) -> float:
        today = utcnow_iso()[:10]
        value = self.metadata.scalar(
            "SELECT SUM(cost_estimate) FROM llm_calls WHERE ts LIKE ?", (f"{today}%",), 0.0
        )
        return float(value or 0.0)

    # ------------------------------------------------------------------ #
    # 知识操作（对外工具复用）
    # ------------------------------------------------------------------ #
    def save_knowledge(self, project_id: str, items: List[Mapping[str, Any]]) -> Dict[str, Any]:
        project = self.metadata.get_project(project_id)
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        prepared: List[Dict[str, Any]] = []
        for item in items:
            content = str(item.get("content") or "").strip()
            if not content and not item.get("summary"):
                raise ValueError("每条知识必须有 content 或 summary")
            cls = classify(content, title=str(item.get("title") or ""), domain=str(item.get("domain") or project.get("domain") or ""))
            partition = item.get("partition") or Partition.PENDING.value
            ensure_partition_allowed(project, partition)
            decision = self.rt.permissions.decide(
                action="save_knowledge",
                risk="write",
                target=partition,
                project_id=project_id,
                content=content,
            )
            if not decision.allowed:
                raise PermissionError(decision.reason)

            # 未显式给出来源质量时，按来源地址推断先验（官方文档/标准更高），
            # 并把依据一并保存，避免"所有外部知识都是 0.5"的粗放处理。
            source_url = str(item.get("source_url") or "")
            source_type = str(item.get("source_type") or "")
            license_status = str(item.get("license_status") or "")
            quality = item.get("source_quality")
            if quality is None and source_url:
                prior = describe_source(
                    source_url,
                    title=str(item.get("source_title") or ""),
                    published_at=str(item.get("published_at") or ""),
                )
                quality = prior["quality"]
                source_type = source_type or str(prior["source_type"])
                license_status = license_status or str(prior["license_status"])
                quality_basis = str(prior["quality_basis"])
            else:
                quality_basis = "调用方显式指定来源质量"
            prepared.append(
                {
                    "project_id": project_id,
                    "chunk_id": item.get("chunk_id") or new_id("chunk"),
                    "title": str(item.get("title") or cls.knowledge_type),
                    "content": content,
                    "summary": str(item.get("summary") or ""),
                    "knowledge_type": item.get("knowledge_type") or cls.knowledge_type,
                    "partition": partition,
                    "domain": item.get("domain") or cls.domain,
                    "topic": item.get("topic") or project.get("title", ""),
                    "subtopic": item.get("subtopic", ""),
                    "source_url": source_url,
                    "source_title": item.get("source_title", ""),
                    "source_type": source_type or "unknown",
                    "author_or_publisher": item.get("author_or_publisher", ""),
                    "published_at": item.get("published_at", ""),
                    "accessed_at": item.get("accessed_at") or utcnow_iso(),
                    "language": item.get("language", "unknown"),
                    "source_quality": float(quality if quality is not None else 0.5),
                    "confidence": float(item.get("confidence", 0.3) or 0.3),
                    "confidence_basis": item.get("confidence_basis")
                    or f"人工/工具写入：未核验前置信度不高于 0.3（来源质量依据：{quality_basis}）",
                    "status": KnowledgeStatus.PENDING_VERIFICATION.value,
                    "level": LearningLevel.L2.value,
                    "visibility": default_visibility(partition),
                    "license_status": license_status or "unknown",
                    "metadata": item.get("metadata") or {"extraction_method": "tool"},
                }
            )
        result = self.store.add_chunks(prepared)
        self.rt.permissions.audit.log(
            action="save_knowledge",
            target=f"{len(prepared)} chunks",
            risk="write",
            allowed=True,
            project_id=project_id,
            detail={"partitions": list({p["partition"] for p in prepared})},
        )
        return result


__all__ = ["LearningOrchestrator", "Runtime", "build_runtime"]
