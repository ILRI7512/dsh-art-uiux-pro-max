"""第七组工具：评估、报告、迭代与系统管理。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping

from ..config import host_settings_file
from ..core.models import TaskStatus, utcnow_iso
from ..core.orchestrator import LearningOrchestrator, Runtime
from ..core.scheduler import Scheduler
from ..storage.metadata_store import ChunkFilter
from .registry import ToolError, ToolRegistry, ToolSpec


def register(reg: ToolRegistry, rt: Runtime, orch: LearningOrchestrator, scheduler: Scheduler) -> None:
    # ------------------------------------------------------------------ #
    # 评估
    # ------------------------------------------------------------------ #
    reg.register(
        ToolSpec(
            name="evaluate_learning",
            description="评估学习成果：覆盖率、来源完整率、核验率、实践通过率、冲突/重复/过时与成本。",
            input_schema={
                "type": "object",
                "properties": {"project_id": {"type": "string"}},
                "required": ["project_id"],
            },
            handler=lambda args: rt.evaluator.evaluate(args["project_id"]),
            group="evaluation",
        )
    )

    reg.register(
        ToolSpec(
            name="get_learning_metrics",
            description="获取学习指标明细（指标汇总 + 模型调用与成本估算）。",
            input_schema={
                "type": "object",
                "properties": {"project_id": {"type": "string"}},
                "required": ["project_id"],
            },
            handler=lambda args: {
                "metrics": rt.evaluator.evaluate(args["project_id"])["metrics"],
                "metric_events": rt.metadata.metrics_summary(args["project_id"]),
                "llm_usage": rt.metadata.llm_usage(args["project_id"]),
            },
            group="evaluation",
        )
    )

    def report(args: Dict[str, Any]) -> Dict[str, Any]:
        result = rt.reporter.generate(
            args["project_id"],
            evaluation=rt.evaluator.evaluate(args["project_id"]),
        )
        return {
            "report_path": result["report_path"],
            "json_path": result["json_path"],
            "goal_met": result["summary"].get("goal_met"),
            "markdown": result["markdown"] if args.get("include_markdown") else "",
        }

    reg.register(
        ToolSpec(
            name="generate_learning_report",
            description="生成学习报告（Markdown + JSON），包含成果、来源、冲突、失败与后续建议。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "include_markdown": {"type": "boolean"},
                },
                "required": ["project_id"],
            },
            handler=report,
            risk="write",
            side_effects="写入 reports 目录",
            group="evaluation",
        )
    )

    def recommend(args: Dict[str, Any]) -> Dict[str, Any]:
        project_id = args["project_id"]
        project = rt.metadata.get_project(project_id)
        if not project:
            raise ToolError(f"项目不存在: {project_id}", "NotFound")
        ready = rt.metadata.next_ready_tasks(project_id, limit=20)
        ordered = rt.planner.priorities(ready)[: int(args.get("limit", 5))]
        gaps = rt.metadata.list_gaps(project_id, status="open")[:3]
        conflicts = rt.metadata.list_conflicts(project_id=project_id, status="open")[:2]
        suggestions: List[Dict[str, Any]] = [
            {
                "action": "run_task",
                "task_id": t["task_id"],
                "kind": t["kind"],
                "title": t["title"],
                "reason": "依赖已满足，按优先级可直接执行",
            }
            for t in ordered
        ]
        for gap in gaps:
            suggestions.append(
                {
                    "action": "fill_gap",
                    "topic": gap["topic"],
                    "reason": gap["reason"],
                    "priority": gap["priority"],
                    "tool": "generate_learning_tasks",
                }
            )
        for conflict in conflicts:
            suggestions.append(
                {
                    "action": "analyze_conflict",
                    "conflict_id": conflict["conflict_id"],
                    "reason": conflict["detail"],
                    "tool": "verify_knowledge",
                }
            )
        if not suggestions:
            suggestions.append(
                {
                    "action": "review",
                    "reason": "没有待执行任务与未解决缺口，建议人工评审当前知识库或扩大目标范围",
                }
            )
        return {"project_id": project_id, "recommendations": suggestions[: int(args.get("limit", 10))]}

    reg.register(
        ToolSpec(
            name="recommend_next_tasks",
            description="推荐下一步任务：就绪任务排序 + 缺口补充 + 冲突分析建议。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["project_id"],
            },
            handler=recommend,
            group="evaluation",
        )
    )

    # ------------------------------------------------------------------ #
    # 调度与重试
    # ------------------------------------------------------------------ #
    reg.register(
        ToolSpec(
            name="schedule_learning_task",
            description="登记定时学习（间隔或指定时间）；后台执行依赖真实进程存活，不承诺永久运行。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "interval_minutes": {"type": "integer", "minimum": 1, "maximum": 10080},
                    "next_run_at": {"type": "string", "description": "ISO8601，例如 2026-10-20T09:00:00Z"},
                },
                "required": ["project_id"],
            },
            handler=lambda args: scheduler.schedule(
                args["project_id"],
                interval_minutes=args.get("interval_minutes"),
                next_run_at=args.get("next_run_at"),
            ),
            risk="write",
            side_effects="写入 schedules",
            group="iteration",
        )
    )

    def retry_failed(args: Dict[str, Any]) -> Dict[str, Any]:
        project_id = args["project_id"]
        if args.get("task_id"):
            task = rt.metadata.get_task(args["task_id"])
            if not task:
                raise ToolError(f"任务不存在: {args['task_id']}", "NotFound")
            targets = [task]
        else:
            targets = rt.metadata.list_tasks(project_id, status=["failed"])
        retried = []
        for task in targets:
            if task["status"] not in {TaskStatus.FAILED.value, TaskStatus.RETRYING.value}:
                continue
            rt.metadata.update_task(
                task["task_id"],
                {"status": TaskStatus.PENDING.value, "attempts": 0, "error": "", "started_at": "", "finished_at": ""},
            )
            retried.append(task["task_id"])
        return {"project_id": project_id, "retried": retried, "count": len(retried)}

    reg.register(
        ToolSpec(
            name="retry_failed_task",
            description="把失败任务重置为待执行（可指定单个任务或全部失败任务）。",
            input_schema={
                "type": "object",
                "properties": {"project_id": {"type": "string"}, "task_id": {"type": "string"}},
                "required": ["project_id"],
            },
            handler=retry_failed,
            risk="write",
            side_effects="更新 tasks.status/attempts",
            group="iteration",
        )
    )

    # ------------------------------------------------------------------ #
    # 健康检查
    # ------------------------------------------------------------------ #
    def audit(args: Dict[str, Any]) -> Dict[str, Any]:
        project_id = args.get("project_id")
        integrity = rt.store.check_integrity()
        filters = ChunkFilter(project_id=project_id) if project_id else ChunkFilter()
        total = rt.metadata.count_chunks(filters)
        missing_source = int(
            rt.metadata.scalar(
                "SELECT COUNT(*) FROM chunks WHERE (source_id='' AND source_url='')"
                + (" AND project_id=?" if project_id else ""),
                (project_id,) if project_id else (),
                0,
            )
            or 0
        )
        unverified = int(
            rt.metadata.scalar(
                "SELECT COUNT(*) FROM chunks WHERE verification_status<>'verified'"
                + (" AND project_id=?" if project_id else ""),
                (project_id,) if project_id else (),
                0,
            )
            or 0
        )
        stale = int(
            rt.metadata.scalar(
                "SELECT COUNT(*) FROM chunks WHERE (status='stale' OR freshness_status IN ('stale','expired'))"
                + (" AND project_id=?" if project_id else ""),
                (project_id,) if project_id else (),
                0,
            )
            or 0
        )
        duplicates = 0
        conflicts = 0
        if args.get("fix"):
            dup = rt.dedup.find_and_record(project_id=project_id)
            duplicates = dup["recorded"]
            scan = rt.conflicts.scan(project_id, record=True) if project_id else {"recorded": 0}
            conflicts = scan["recorded"]
        issues: List[Dict[str, Any]] = []
        if not integrity["ok"]:
            issues.append({"severity": "high", "issue": "索引完整性问题", "detail": integrity["problems"]})
        if total and missing_source / total > 0.05:
            issues.append(
                {"severity": "high", "issue": "来源缺失", "detail": f"{missing_source}/{total} 条知识没有来源信息"}
            )
        if total and unverified / total > 0.7:
            issues.append(
                {"severity": "medium", "issue": "核验率过低", "detail": f"{unverified}/{total} 条未核验"}
            )
        if stale:
            issues.append({"severity": "medium", "issue": "过时知识", "detail": f"{stale} 条可能过时"})
        return {
            "project_id": project_id or "",
            "chunks": total,
            "index_integrity": integrity,
            "missing_source": missing_source,
            "unverified": unverified,
            "stale": stale,
            "new_duplicates": duplicates,
            "new_conflicts": conflicts,
            "issues": issues,
            "audited_at": utcnow_iso(),
        }

    reg.register(
        ToolSpec(
            name="audit_knowledge_base",
            description="知识库体检：索引一致性、来源缺失、核验率、过时、重复与冲突（fix=true 会登记重复/冲突）。",
            input_schema={
                "type": "object",
                "properties": {"project_id": {"type": "string"}, "fix": {"type": "boolean"}},
            },
            handler=audit,
            risk="write",
            side_effects="fix=true 时写入 duplicates/conflicts",
            group="evaluation",
        )
    )

    # ------------------------------------------------------------------ #
    # 系统 / 编排
    # ------------------------------------------------------------------ #
    reg.register(
        ToolSpec(
            name="run_learning_round",
            description="执行一轮有界学习（规划→发现→提取→核验→实践→评估→报告），受预算与停止条件约束。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "max_tasks": {"type": "integer", "minimum": 1, "maximum": 50},
                    "use_model": {"type": "boolean"},
                },
                "required": ["project_id"],
            },
            handler=lambda args: orch.run_round(
                args["project_id"],
                max_tasks=args.get("max_tasks"),
                use_model=bool(args.get("use_model")),
            ),
            risk="write",
            side_effects="执行学习任务，写入知识与多个表",
            group="system",
        )
    )

    reg.register(
        ToolSpec(
            name="run_scheduler_tick",
            description="检查并执行到期的定时学习任务（有界，不会无限循环）。",
            input_schema={
                "type": "object",
                "properties": {
                    "max_projects": {"type": "integer", "minimum": 1, "maximum": 5},
                    "max_tasks_per_project": {"type": "integer", "minimum": 1, "maximum": 20},
                },
            },
            handler=lambda args: scheduler.tick(
                max_projects=int(args.get("max_projects", 1)),
                max_tasks_per_project=int(args.get("max_tasks_per_project", 5)),
            ),
            risk="write",
            side_effects="执行学习并更新 schedules",
            group="system",
        )
    )

    reg.register(
        ToolSpec(
            name="list_scheduled_tasks",
            description="列出定时学习任务及其下次运行时间。",
            input_schema={"type": "object", "properties": {}},
            handler=lambda args: {"schedules": scheduler.list()},
            group="system",
        )
    )

    reg.register(
        ToolSpec(
            name="get_runtime_info",
            description="查看运行时信息：模式、路径、向量化器、模型、预算、索引与权限状态（含设置卡生效值）。",
            input_schema={"type": "object", "properties": {}},
            handler=lambda args: {
                "mode": rt.permissions.mode,
                "settings": rt.apply_settings(),
                "settings_file": str(host_settings_file(Path(rt.config.paths.home))),
                "paths": {
                    "home": rt.config.paths.home,
                    "data_dir": rt.config.paths.data_dir,
                    "db_path": rt.config.paths.db_path,
                    "index_dir": rt.config.paths.index_dir,
                    "corpus_dir": rt.config.paths.corpus_dir,
                    "reports_dir": rt.config.paths.reports_dir,
                    "experiments_dir": rt.config.paths.experiments_dir,
                },
                "embedder": rt.store.embedder.describe()
                if hasattr(rt.store.embedder, "describe")
                else {"provider": rt.store.embedder.provider},
                "model": {"provider": rt.config.model.provider, "model": rt.config.model.model},
                "learning": {
                    "max_tasks_per_run": rt.config.learning.max_tasks_per_run,
                    "max_iterations_per_run": rt.config.learning.max_iterations_per_run,
                    "daily_budget_usd": rt.config.learning.daily_budget_usd,
                    "max_sources_per_task": rt.config.learning.max_sources_per_task,
                },
                "security": {
                    "allow_network": rt.config.security.allow_network,
                    "auto_execute_untrusted_code": rt.config.learning.auto_execute_untrusted_code,
                    "delegate_approval_to_host": rt.permissions.delegate_to_host,
                    "host_gate_installed": rt.permissions._host_gate_installed(),  # noqa: SLF001
                    "host_approval_heartbeat": str(rt.permissions.heartbeat_path or ""),
                    "host_approval_fresh": rt.permissions._host_heartbeat_fresh(),  # noqa: SLF001
                    "host_approval_stale": rt.permissions._host_heartbeat_stale(),  # noqa: SLF001
                    "allowed_roots": [str(p) for p in rt.permissions.allowed_roots()],
                    "audit_enabled": rt.config.security.audit_log,
                },
                "index": rt.store.stats(),
                "pending_confirmations": rt.permissions.pending_confirmations(),
                "db_stats": rt.metadata.stats(),
            },
            group="system",
        )
    )

    reg.register(
        ToolSpec(
            name="rebuild_vector_index",
            description="按元数据重建向量索引（换向量模型或索引损坏后使用）。",
            input_schema={"type": "object", "properties": {}},
            handler=lambda args: rt.store.rebuild_index(),
            risk="write",
            side_effects="重写 index 目录",
            group="system",
        )
    )

    reg.register(
        ToolSpec(
            name="check_index_integrity",
            description="检查向量索引与元数据是否一致（孤儿向量、缺失向量、NaN）。",
            input_schema={"type": "object", "properties": {}},
            handler=lambda args: rt.store.check_integrity(),
            group="system",
        )
    )

    reg.register(
        ToolSpec(
            name="list_learning_tools",
            description="列出本插件提供的所有工具及其风险等级与参数 schema。",
            input_schema={
                "type": "object",
                "properties": {"group": {"type": "string"}},
            },
            handler=lambda args: {"tools": reg.list_specs(args.get("group")), "count": len(reg.names())},
            group="system",
        )
    )


__all__ = ["register"]
