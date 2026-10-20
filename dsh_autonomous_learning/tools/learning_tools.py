"""第一组/第二组工具：学习项目管理 + 学习规划。"""

from __future__ import annotations

from typing import Any, Dict, List

from ..core.models import TaskStatus
from ..core.orchestrator import LearningOrchestrator, Runtime
from .registry import ToolError, ToolRegistry, ToolSpec

PROJECT_PROPS = {
    "goal": {"type": "string", "description": "学习目标（自然语言）"},
    "title": {"type": "string", "description": "项目标题，省略时取目标前 40 字"},
    "domain": {
        "type": "string",
        "enum": ["general", "uiux", "finance", "quant", "programming", "project", "experiment"],
        "description": "领域，决定默认主题模板与分区",
    },
    "depth": {"type": "string", "enum": ["overview", "working", "deep"], "description": "学习深度"},
    "mode": {"type": "string", "enum": ["assisted", "auto", "lab"], "description": "自主等级"},
    "partitions": {"type": "array", "items": {"type": "string"}, "description": "允许写入的知识分区"},
    "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
    "deliverables": {"type": "array", "items": {"type": "string"}},
    "allowed_sources": {"type": "array", "items": {"type": "string"}, "description": "允许使用的 URL 或本地路径"},
    "plan": {"type": "boolean", "description": "是否立即生成学习计划，默认 true"},
}


def register(reg: ToolRegistry, rt: Runtime, orch: LearningOrchestrator) -> None:
    # ------------------------------------------------------------------ #
    # 项目管理
    # ------------------------------------------------------------------ #
    def create_project(args: Dict[str, Any]) -> Dict[str, Any]:
        project = orch.create_project(
            goal=args["goal"],
            title=args.get("title", ""),
            domain=args.get("domain", "general"),
            depth=args.get("depth", "working"),
            mode=args.get("mode"),
            partitions=args.get("partitions"),
            acceptance_criteria=args.get("acceptance_criteria"),
            deliverables=args.get("deliverables"),
            allowed_sources=args.get("allowed_sources"),
        )
        data: Dict[str, Any] = {"project": project}
        if args.get("plan", True):
            data["plan"] = orch.plan(project["project"]["project_id"])
        return data

    reg.register(
        ToolSpec(
            name="create_learning_project",
            description="创建学习项目：登记目标、领域、深度、允许数据源与验收标准，并可选立即生成学习计划。",
            input_schema={"type": "object", "properties": PROJECT_PROPS, "required": ["goal"]},
            handler=create_project,
            risk="write",
            side_effects="写入 projects 表，可能写入 tasks 表",
            group="project",
        )
    )

    def get_project(args: Dict[str, Any]) -> Dict[str, Any]:
        return orch.get_project(args["project_id"])

    reg.register(
        ToolSpec(
            name="get_learning_project",
            description="获取学习项目状态（任务统计、知识量、预算配置）。",
            input_schema={
                "type": "object",
                "properties": {"project_id": {"type": "string"}},
                "required": ["project_id"],
            },
            handler=get_project,
            group="project",
        )
    )

    reg.register(
        ToolSpec(
            name="list_learning_projects",
            description="列出学习项目，可按状态过滤。",
            input_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["active", "paused", "completed", "cancelled", "blocked"]}
                },
            },
            handler=lambda args: {"projects": orch.list_projects(args.get("status"))},
            group="project",
        )
    )

    def _set_status(args: Dict[str, Any], status: str) -> Dict[str, Any]:
        return orch.set_status(args["project_id"], status)

    for name, status, desc in (
        ("pause_learning_project", "paused", "暂停学习项目（保留全部状态，可恢复）"),
        ("resume_learning_project", "active", "恢复已暂停的学习项目"),
        ("cancel_learning_project", "cancelled", "取消学习项目（不删除数据，仅停止后续任务）"),
    ):
        reg.register(
            ToolSpec(
                name=name,
                description=desc,
                input_schema={
                    "type": "object",
                    "properties": {"project_id": {"type": "string"}},
                    "required": ["project_id"],
                },
                handler=lambda args, s=status: _set_status(args, s),
                risk="write",
                side_effects="更新 projects.status",
                group="project",
            )
        )

    def progress(args: Dict[str, Any]) -> Dict[str, Any]:
        project_id = args["project_id"]
        project = rt.metadata.get_project(project_id)
        if not project:
            raise ToolError(f"项目不存在: {project_id}")
        tasks = rt.metadata.list_tasks(project_id)
        counts = rt.metadata.task_counts(project_id)
        by_kind: Dict[str, Dict[str, int]] = {}
        for task in tasks:
            bucket = by_kind.setdefault(task["kind"], {})
            bucket[task["status"]] = bucket.get(task["status"], 0) + 1
        analysis = rt.gaps.analyze(project_id, record=False)
        runs = rt.metadata.last_runs(project_id, limit=3)
        return {
            "project_id": project_id,
            "project_status": project["status"],
            "tasks": counts,
            "tasks_by_kind": by_kind,
            "chunks": rt.metadata.count_chunks(),
            "coverage_rate": analysis["coverage_rate"],
            "coverage": analysis["coverage"],
            "open_gaps": len(rt.metadata.list_gaps(project_id, status="open")),
            "open_conflicts": len(rt.metadata.list_conflicts(project_id=project_id, status="open")),
            "last_runs": [
                {"run_id": r["run_id"], "iteration": r["iteration"], "status": r["status"], "stop_reason": r["stop_reason"]}
                for r in runs
            ],
        }

    reg.register(
        ToolSpec(
            name="get_learning_progress",
            description="获取学习进度：任务分布、覆盖等级、缺口与冲突、最近运行轮次。",
            input_schema={
                "type": "object",
                "properties": {"project_id": {"type": "string"}},
                "required": ["project_id"],
            },
            handler=progress,
            group="project",
        )
    )

    # ------------------------------------------------------------------ #
    # 规划
    # ------------------------------------------------------------------ #
    reg.register(
        ToolSpec(
            name="plan_learning_path",
            description="生成学习路线：主题 → 发现 → 提取 → 核验 → 实践 → 评估 → 报告的任务 DAG（含依赖与验收条件）。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "use_model": {"type": "boolean", "description": "是否让模型补充主题（默认 false）"},
                },
                "required": ["project_id"],
            },
            handler=lambda args: orch.plan(args["project_id"], use_model=bool(args.get("use_model"))),
            risk="write",
            side_effects="写入 tasks 表（幂等：已有计划则返回现状）",
            group="planning",
        )
    )

    reg.register(
        ToolSpec(
            name="decompose_learning_goal",
            description="把学习目标拆成主题列表（领域模板 + 目标关键词，可解释；可选模型补充）。",
            input_schema={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "domain": {"type": "string", "enum": ["general", "uiux", "finance", "quant", "programming", "project", "experiment"]},
                    "depth": {"type": "string", "enum": ["overview", "working", "deep"]},
                    "use_model": {"type": "boolean"},
                },
                "required": ["goal"],
            },
            handler=lambda args: rt.planner.decompose_goal(
                args["goal"],
                domain=args.get("domain", "general"),
                depth=args.get("depth", "working"),
                use_model=bool(args.get("use_model")),
            ),
            group="planning",
        )
    )

    reg.register(
        ToolSpec(
            name="analyze_knowledge_gaps",
            description="分析知识缺口：按主题计算 L0-L5 覆盖、单一来源、过时、冲突，并登记缺口。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "target_level": {"type": "string", "enum": ["L0", "L1", "L2", "L3", "L4", "L5"]},
                    "record": {"type": "boolean", "description": "是否写入 gaps 表，默认 true"},
                },
                "required": ["project_id"],
            },
            handler=lambda args: rt.gaps.analyze(
                args["project_id"],
                target_level=args.get("target_level", "L3"),
                record=bool(args.get("record", True)),
            ),
            group="planning",
        )
    )

    def generate_tasks(args: Dict[str, Any]) -> Dict[str, Any]:
        project_id = args["project_id"]
        project = rt.metadata.get_project(project_id)
        if not project:
            raise ToolError(f"项目不存在: {project_id}")
        gaps = rt.metadata.list_gaps(project_id, status="open")[: int(args.get("limit", 3))]
        created: List[Dict[str, Any]] = []
        for gap in gaps:
            created.extend(rt.planner.tasks_for_gap(project, gap))
        for conflict in rt.metadata.list_conflicts(project_id=project_id, status="open")[:2]:
            created.extend(rt.planner.tasks_for_conflict(project, conflict))
        return {"created": created, "count": len(created), "source_gaps": len(gaps)}

    reg.register(
        ToolSpec(
            name="generate_learning_tasks",
            description="根据未解决缺口与冲突生成补充学习任务（发现资料 / 提取 / 冲突分析）。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["project_id"],
            },
            handler=generate_tasks,
            risk="write",
            side_effects="写入 tasks 表",
            group="planning",
        )
    )

    def prioritize(args: Dict[str, Any]) -> Dict[str, Any]:
        tasks = rt.metadata.list_tasks(args["project_id"], status=["pending", "retrying", "blocked"])
        ordered = rt.planner.priorities(tasks)
        return {
            "project_id": args["project_id"],
            "tasks": [
                {
                    "task_id": t["task_id"],
                    "kind": t["kind"],
                    "title": t["title"],
                    "priority": t["priority"],
                    "status": t["status"],
                    "depends_on": t.get("depends_on", []),
                }
                for t in ordered[: int(args.get("limit", 20))]
            ],
        }

    reg.register(
        ToolSpec(
            name="prioritize_learning_tasks",
            description="按价值、就绪状态与依赖深度对任务排序。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["project_id"],
            },
            handler=prioritize,
            group="planning",
        )
    )


__all__ = ["register"]
