"""学习规划器。

职责：
1. 把学习目标拆成主题/子主题（规则模板 + 目标关键词，可解释）；
2. 生成带依赖、验收条件、预算与失败策略的任务 DAG；
3. 为缺口/冲突/失败实践生成补充任务；
4. 按"价值 × 就绪度 − 依赖深度惩罚"排序（确定性，可测试）。

规划器不依赖模型也能工作；有模型时可让模型补充主题，但会与规则结果合并去重，
并在 ``basis`` 里记录来源，便于审计。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..config import LearningConfig
from ..storage.metadata_store import MetadataStore
from .model_adapter import BaseModel
from .models import Task, TaskKind, TaskStatus, new_id

DOMAIN_TEMPLATES: Dict[str, List[str]] = {
    "uiux": ["设计原则与规范", "组件与交互模式", "可用性与无障碍", "视觉与排版", "设计流程与交付"],
    "quant": ["数据质量与预处理", "策略与信号构造", "回测方法与偏差", "风险管理与仓位", "交易成本与执行"],
    "finance": ["基础概念与术语", "市场结构与参与者", "风险、杠杆与保证金", "工具与产品差异"],
    "programming": ["语言核心与类型系统", "工程结构与依赖管理", "测试、调试与可观测性", "性能与并发", "生态与工具链"],
    "general": ["基础概念与定义", "核心原理与机制", "方法与流程", "常见风险与误区", "实践案例"],
}

DEPTH_TOPIC_LIMIT = {"overview": 3, "working": 5, "deep": 8}


@dataclass
class Topic:
    name: str
    subtopics: List[str] = field(default_factory=list)
    origin: str = "template"  # template | goal | model | gap

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "subtopics": list(self.subtopics), "origin": self.origin}


class LearningPlanner:
    def __init__(self, metadata: MetadataStore, config: LearningConfig, model: Optional[BaseModel] = None) -> None:
        self.metadata = metadata
        self.cfg = config
        self.model = model

    # ------------------------------------------------------------------ #
    # 目标拆解
    # ------------------------------------------------------------------ #
    def decompose_goal(
        self, goal: str, *, domain: str = "general", depth: str = "working", use_model: bool = False
    ) -> Dict[str, Any]:
        limit = DEPTH_TOPIC_LIMIT.get(depth, 5)
        topics: List[Topic] = []
        template = DOMAIN_TEMPLATES.get(domain, DOMAIN_TEMPLATES["general"])
        for name in template[:limit]:
            topics.append(Topic(name=name, origin="template"))

        for segment in re.split(r"[，,、；;。.\n]|以及|并且", goal or ""):
            segment = segment.strip(" ：:*-")
            if 3 <= len(segment) <= 40 and not _looks_like_action(segment):
                if all(segment not in t.name for t in topics):
                    topics.append(Topic(name=segment, origin="goal"))
            if len(topics) >= limit + 2:
                break

        model_topics: List[str] = []
        if use_model and self.model is not None:
            try:
                model_topics = self._model_topics(goal, domain)
                for name in model_topics:
                    if all(name not in t.name for t in topics):
                        topics.append(Topic(name=name, origin="model"))
            except Exception:  # noqa: BLE001 - 模型不可用不应中断规则规划
                model_topics = []

        selected = topics[: max(limit, 3)]
        return {
            "goal": goal,
            "domain": domain,
            "depth": depth,
            "topics": [t.to_dict() for t in selected],
            "dropped": [t.to_dict() for t in topics[len(selected) :]],
            "basis": (
                f"领域模板 {domain} 提供 {min(len(template), limit)} 个主题；"
                f"目标文本补充 {sum(1 for t in selected if t.origin == 'goal')} 个；"
                f"模型补充 {len(model_topics)} 个"
            ),
        }

    def _model_topics(self, goal: str, domain: str) -> List[str]:
        assert self.model is not None
        schema = {
            "type": "object",
            "properties": {"topics": {"type": "array", "items": {"type": "string"}}},
            "required": ["topics"],
        }
        response = self.model.complete(
            "plan",
            "你是学习规划助手。请把学习目标拆成 3-6 个可独立验证的主题，只输出 JSON。",
            f"领域: {domain}\n目标: {goal}",
            json_schema=schema,
            max_tokens=500,
        )
        topics = (response.parsed or {}).get("topics") or []
        return [str(t)[:40] for t in topics if isinstance(t, str) and t.strip()][:6]

    # ------------------------------------------------------------------ #
    # 学习计划
    # ------------------------------------------------------------------ #
    def create_plan(self, project: Mapping[str, Any], *, use_model: bool = False) -> Dict[str, Any]:
        project_id = project["project_id"]
        decomposition = self.decompose_goal(
            str(project.get("goal") or ""),
            domain=str(project.get("domain") or "general"),
            depth=str(project.get("depth") or "working"),
            use_model=use_model,
        )
        rows: List[Dict[str, Any]] = []

        for order, topic in enumerate(decomposition["topics"]):
            base = round(max(0.2, 1.0 - order * 0.12), 3)
            discover = self._make_task(
                project_id,
                kind=TaskKind.DISCOVER.value,
                title=f"发现资料：{topic['name']}",
                objective=f"为「{topic['name']}」找到可访问、可追溯的资料",
                inputs={"topic": topic["name"], "subtopics": topic["subtopics"]},
                acceptance=["至少 1 个来源被成功记录", "每个来源都有类型、质量与许可判定"],
                priority=base,
                idempotency_key=f"discover::{project_id}::{topic['name']}",
            )
            extract = self._make_task(
                project_id,
                kind=TaskKind.EXTRACT.value,
                title=f"提取知识：{topic['name']}",
                objective=f"从「{topic['name']}」的资料中提取结构化知识并入库（待核验）",
                inputs={"topic": topic["name"]},
                depends_on=[discover["task_id"]],
                acceptance=["至少 1 条知识进入待核验区", "每条知识都有来源与内容指纹"],
                priority=round(base - 0.02, 3),
                idempotency_key=f"extract::{project_id}::{topic['name']}",
            )
            verify = self._make_task(
                project_id,
                kind=TaskKind.VERIFY.value,
                title=f"核验知识：{topic['name']}",
                objective=f"对「{topic['name']}」的待核验知识执行类型匹配的核验",
                inputs={"topic": topic["name"]},
                depends_on=[extract["task_id"]],
                acceptance=["每条待核验知识都有核验记录或明确失败原因", "verified 必须满足证据门槛"],
                priority=round(base - 0.04, 3),
                idempotency_key=f"verify::{project_id}::{topic['name']}",
            )
            practice = self._make_task(
                project_id,
                kind=TaskKind.PRACTICE.value,
                title=f"实践检验：{topic['name']}",
                objective=f"为「{topic['name']}」中可实践的公式/代码生成并执行受控检验",
                inputs={"topic": topic["name"]},
                depends_on=[verify["task_id"]],
                acceptance=["公式需重算通过或明确记录无法重算", "代码需执行并记录环境与输出"],
                priority=round(base - 0.06, 3),
                idempotency_key=f"practice::{project_id}::{topic['name']}",
            )
            rows.extend([discover, extract, verify, practice])

        gap = self._make_task(
            project_id,
            kind=TaskKind.GAP_ANALYSIS.value,
            title="分析知识缺口",
            objective="统计覆盖率、未核验、冲突、过时与重复，生成缺口列表",
            acceptance=["每条主题都有 L0-L5 覆盖等级", "缺口有优先级且可解释"],
            priority=0.8,
            idempotency_key=f"gap::{project_id}::v1",
        )
        evaluate = self._make_task(
            project_id,
            kind=TaskKind.EVALUATE.value,
            title="评估学习成果",
            objective="按验收标准计算覆盖率、核验率、实践通过率与成本",
            depends_on=[gap["task_id"]],
            acceptance=["给出达标/未达标结论", "未达标项生成补充任务"],
            priority=0.9,
            idempotency_key=f"evaluate::{project_id}::v1",
        )
        report = self._make_task(
            project_id,
            kind=TaskKind.REPORT.value,
            title="生成学习报告",
            objective="输出包含成果、来源、冲突、失败与后续建议的报告",
            depends_on=[evaluate["task_id"]],
            acceptance=["报告落盘且包含来源与未解决问题"],
            priority=1.0,
            idempotency_key=f"report::{project_id}::v1",
        )
        rows.extend([gap, evaluate, report])

        created = [self.metadata.create_task(row) for row in rows]
        return {
            "project_id": project_id,
            "decomposition": decomposition,
            "tasks": created,
            "task_count": len(created),
        }

    # ------------------------------------------------------------------ #
    # 补充任务
    # ------------------------------------------------------------------ #
    def tasks_for_gap(self, project: Mapping[str, Any], gap: Mapping[str, Any]) -> List[Dict[str, Any]]:
        project_id = project["project_id"]
        topic = gap.get("topic") or "未命名主题"
        discover = self._make_task(
            project_id,
            kind=TaskKind.DISCOVER.value,
            title=f"补充资料：{topic}",
            objective=f"知识缺口「{topic}」缺少可核验资料，需要补充来源",
            inputs={"topic": topic, "reason": gap.get("reason", "")},
            acceptance=["新增至少 1 个独立来源", "来源可追溯"],
            priority=float(gap.get("priority", 0.6)),
            idempotency_key=f"gapfix-discover::{project_id}::{topic}::{gap.get('gap_id','')}",
        )
        extract = self._make_task(
            project_id,
            kind=TaskKind.EXTRACT.value,
            title=f"补充提取：{topic}",
            objective=f"从新增资料中提取「{topic}」的知识",
            inputs={"topic": topic},
            depends_on=[discover["task_id"]],
            priority=round(float(gap.get("priority", 0.6)) - 0.02, 3),
            idempotency_key=f"gapfix-extract::{project_id}::{topic}::{gap.get('gap_id','')}",
        )
        return [self.metadata.create_task(discover), self.metadata.create_task(extract)]

    def tasks_for_conflict(self, project: Mapping[str, Any], conflict: Mapping[str, Any]) -> List[Dict[str, Any]]:
        project_id = project["project_id"]
        row = self._make_task(
            project_id,
            kind=TaskKind.VERIFY.value,
            title="冲突分析任务",
            objective="对相互矛盾的两条知识收集独立证据，保留双方结论，不做简单删除",
            inputs={
                "conflict_id": conflict["conflict_id"],
                "chunk_a": conflict["chunk_a"],
                "chunk_b": conflict["chunk_b"],
            },
            acceptance=["双方证据均被记录", "冲突状态明确（open/disputed/resolved）"],
            priority=0.85,
            idempotency_key=f"conflict::{conflict['conflict_id']}",
        )
        return [self.metadata.create_task(row)]

    # ------------------------------------------------------------------ #
    # 排序
    # ------------------------------------------------------------------ #
    def priorities(self, tasks: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        """按 价值 × 就绪度 − 依赖深度惩罚 排序。依赖深度由入参任务图计算。"""

        by_id = {t["task_id"]: t for t in tasks}
        depth_cache: Dict[str, int] = {}

        def depth(task_id: str, guard: int = 0) -> int:
            if guard > 50:
                return 50
            if task_id in depth_cache:
                return depth_cache[task_id]
            task = by_id.get(task_id)
            deps = (task or {}).get("depends_on") or []
            value = 0 if not deps else 1 + max(depth(d, guard + 1) for d in deps)
            depth_cache[task_id] = value
            return value

        def score(task: Mapping[str, Any]) -> float:
            base = float(task.get("priority", 0.5))
            ready = 1.0 if task.get("status") in {TaskStatus.PENDING.value, TaskStatus.RETRYING.value} else 0.3
            return round(base * ready - 0.03 * depth(task["task_id"]), 4)

        return sorted(tasks, key=lambda t: (-score(t), t.get("created_at", "")))

    # ------------------------------------------------------------------ #
    def _make_task(
        self,
        project_id: str,
        *,
        kind: str,
        title: str,
        objective: str,
        inputs: Optional[Dict[str, Any]] = None,
        depends_on: Optional[List[str]] = None,
        acceptance: Optional[List[str]] = None,
        priority: float = 0.5,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        task = Task(
            task_id=new_id("task"),
            project_id=project_id,
            kind=kind,
            title=title,
            objective=objective,
            inputs=inputs or {},
            depends_on=depends_on or [],
            acceptance=acceptance or [],
            priority=priority,
            max_retries=self.cfg.max_retries_per_task,
            timeout_s=self.cfg.max_task_seconds,
            idempotency_key=idempotency_key,
        )
        return task.to_row()


def _looks_like_action(text: str) -> bool:
    actions = ("学习", "建立", "总结", "验证", "生成", "区分", "完成", "掌握", "研究", "构建", "要求")
    return any(text.startswith(a) for a in actions) and len(text) > 12


__all__ = ["DEPTH_TOPIC_LIMIT", "DOMAIN_TEMPLATES", "LearningPlanner", "Topic"]
