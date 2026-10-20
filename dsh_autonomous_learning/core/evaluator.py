"""学习评估器。

评估的是"证据"而不是"感觉"：
- 覆盖率：按规划主题的 L0-L5
- 来源完整率：有来源信息的片段占比
- 核验完成率：pending 中已处理的比例
- 实践通过率：有执行结果的实践任务通过比例
- 重复率 / 冲突数 / 过时数 / 未解决问题数
- 单位任务成本（模型调用次数与费用估算）

``goal_met`` 只有在验收标准与覆盖率同时达标时才为 True；
否则给出 remaining 列表，由规划器生成补充任务。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from ..config import LearningConfig
from ..storage.metadata_store import ChunkFilter, MetadataStore
from .gap_analyzer import KnowledgeGapAnalyzer
from .models import LearningLevel, PracticeStatus, TaskStatus
from .state_machine import at_least


class LearningEvaluator:
    def __init__(self, metadata: MetadataStore, config: LearningConfig) -> None:
        self.metadata = metadata
        self.cfg = config
        self.gaps = KnowledgeGapAnalyzer(metadata)

    # ------------------------------------------------------------------ #
    def evaluate(self, project_id: str) -> Dict[str, Any]:
        project = self.metadata.get_project(project_id)
        if not project:
            raise ValueError(f"项目不存在: {project_id}")

        analysis = self.gaps.analyze(project_id, record=False)
        total_chunks = self.metadata.count_chunks(ChunkFilter(project_id=project_id))
        with_source = int(
            self.metadata.scalar(
                "SELECT COUNT(*) FROM chunks WHERE project_id=? AND (source_id<>'' OR source_url<>'')",
                (project_id,),
                0,
            )
            or 0
        )
        verified = int(
            self.metadata.scalar(
                "SELECT COUNT(*) FROM chunks WHERE project_id=? AND verification_status='verified'",
                (project_id,),
                0,
            )
            or 0
        )
        pending = int(
            self.metadata.scalar(
                "SELECT COUNT(*) FROM chunks WHERE project_id=? AND status='pending_verification'",
                (project_id,),
                0,
            )
            or 0
        )
        disputed = int(
            self.metadata.scalar(
                "SELECT COUNT(*) FROM chunks WHERE project_id=? AND (status='disputed' OR conflict_status IN ('potential','confirmed'))",
                (project_id,),
                0,
            )
            or 0
        )
        stale = int(
            self.metadata.scalar(
                "SELECT COUNT(*) FROM chunks WHERE project_id=? AND (status='stale' OR freshness_status IN ('stale','expired'))",
                (project_id,),
                0,
            )
            or 0
        )
        duplicates = len(self.metadata.list_duplicates(project_id))
        conflicts = len(self.metadata.list_conflicts(project_id=project_id, status="open"))
        task_counts = self.metadata.task_counts(project_id)
        practice_total = int(
            self.metadata.scalar("SELECT COUNT(*) FROM practice_tasks WHERE project_id=?", (project_id,), 0) or 0
        )
        practice_passed = int(
            self.metadata.scalar(
                "SELECT COUNT(*) FROM practice_tasks WHERE project_id=? AND status=?",
                (project_id, PracticeStatus.PASSED.value),
                0,
            )
            or 0
        )
        practice_failed = int(
            self.metadata.scalar(
                "SELECT COUNT(*) FROM practice_tasks WHERE project_id=? AND status=?",
                (project_id, PracticeStatus.FAILED.value),
                0,
            )
            or 0
        )
        usage = self.metadata.llm_usage(project_id)

        metrics = {
            "chunks_total": total_chunks,
            "source_completeness": round(with_source / total_chunks, 3) if total_chunks else 0.0,
            "verification_rate": round(verified / total_chunks, 3) if total_chunks else 0.0,
            "pending_verification": pending,
            "disputed": disputed,
            "stale": stale,
            "duplicates": duplicates,
            "open_conflicts": conflicts,
            "coverage_rate": analysis["coverage_rate"],
            "target_level": analysis["target_level"],
            "practice": {
                "total": practice_total,
                "executed": practice_passed + practice_failed,
                "passed": practice_passed,
                "failed": practice_failed,
                # 只有真正执行过的实践才计入通过率；"生成了但没跑"不等于失败，也不等于通过
                "pass_rate": round(practice_passed / (practice_passed + practice_failed), 3)
                if (practice_passed + practice_failed)
                else 0.0,
            },
            "tasks": task_counts,
            "llm": usage,
            "cost_per_task": round(usage["cost_estimate"] / max(1, sum(task_counts.values())), 6),
        }

        # 验收判定（保守：任何一项不达标都不宣布"已学会"）
        remaining: List[str] = []
        if total_chunks == 0:
            remaining.append("知识库为空：尚未完成任何资料提取")
        if analysis["coverage_rate"] < 0.8:
            remaining.append(
                f"覆盖率 {analysis['coverage_rate']:.0%} < 80%（目标等级 {analysis['target_level']}）"
            )
        if total_chunks and metrics["verification_rate"] < 0.5:
            remaining.append(f"核验率 {metrics['verification_rate']:.0%} < 50%")
        if total_chunks and metrics["source_completeness"] < 0.9:
            remaining.append("存在缺少来源信息的知识，违反可追溯性要求")
        if conflicts:
            remaining.append(f"{conflicts} 个冲突尚未裁定")
        executed_practice = practice_passed + practice_failed
        if executed_practice and metrics["practice"]["pass_rate"] < 0.5:
            remaining.append("实践任务通过率低于 50%")
        if practice_total and not executed_practice:
            remaining.append("已生成实践任务但尚未执行（缺少执行结果，不能判定掌握程度）")

        uncompleted = [
            t for t in self.metadata.list_tasks(project_id) if t["status"] != TaskStatus.COMPLETED.value
        ]
        if uncompleted:
            remaining.append(f"{len(uncompleted)} 个任务未完成")

        goal_met = not remaining
        if goal_met:
            # 即使指标都达标，也只用"可以进入评审"这种表述，避免声称模型已学会
            remaining_note = "所有量化指标达标，可进入人工评审；这不等于模型永久掌握知识"
        else:
            remaining_note = "未达标：" + "；".join(remaining)

        return {
            "project_id": project_id,
            "goal": project.get("goal", ""),
            "metrics": metrics,
            "coverage": analysis["coverage"],
            "gaps": analysis["gaps"],
            "goal_met": goal_met,
            "remaining": remaining,
            "conclusion": remaining_note,
            "acceptance_criteria": project.get("acceptance_criteria", []),
            "evaluated_at": analysis["timestamp"],
        }

    # ------------------------------------------------------------------ #
    def metrics_snapshot(self, project_id: str) -> Dict[str, Any]:
        data = self.evaluate(project_id)
        return data["metrics"]


__all__ = ["LearningEvaluator"]
