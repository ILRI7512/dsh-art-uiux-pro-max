"""学习报告生成。

报告必须包含（规范阶段 J）：
学习目标、完成任务、未完成任务、新增知识数量、主要来源、已核验结论、
未核验结论、冲突与不确定性、实践结果、知识库更新记录、后续学习建议。

同时输出 Markdown（给人看）与 JSON（给程序/审计用）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ..storage.metadata_store import ChunkFilter, MetadataStore
from ..storage.vector_store import KnowledgeStore
from .evaluator import LearningEvaluator
from .models import KnowledgeStatus, TaskStatus, utcnow_iso


class ReportGenerator:
    def __init__(
        self,
        metadata: MetadataStore,
        store: KnowledgeStore,
        evaluator: LearningEvaluator,
        reports_dir: str | Path,
    ) -> None:
        self.metadata = metadata
        self.store = store
        self.evaluator = evaluator
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    def generate(
        self,
        project_id: str,
        *,
        evaluation: Optional[Mapping[str, Any]] = None,
        run_id: str = "",
    ) -> Dict[str, Any]:
        project = self.metadata.get_project(project_id)
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        evaluation = dict(evaluation or self.evaluator.evaluate(project_id))

        tasks = self.metadata.list_tasks(project_id)
        done = [t for t in tasks if t["status"] == TaskStatus.COMPLETED.value]
        unfinished = [t for t in tasks if t["status"] != TaskStatus.COMPLETED.value]
        chunks = self.metadata.list_chunks(ChunkFilter(project_id=project_id), limit=10000)
        verified = [c for c in chunks if c.get("verification_status") == "verified"]
        unverified = [c for c in chunks if c.get("verification_status") != "verified"]
        conflicts = self.metadata.list_conflicts(project_id=project_id)
        duplicates = self.metadata.list_duplicates(project_id)
        gaps = self.metadata.list_gaps(project_id, status="open")
        practices = self.metadata.query_dicts(
            "SELECT * FROM practice_tasks WHERE project_id=? ORDER BY created_at DESC LIMIT 50", (project_id,)
        )
        experiments = self.metadata.query_dicts(
            "SELECT experiment_id, status, created_at, artifact_dir FROM experiments WHERE project_id=? ORDER BY created_at DESC LIMIT 20",
            (project_id,),
        )
        sources = self.metadata.query_dicts(
            "SELECT title, location, source_type, quality, license_status, freshness_status FROM sources WHERE project_id=? ORDER BY created_at DESC LIMIT 50",
            (project_id,),
        )
        runs = self.metadata.last_runs(project_id, limit=5)

        summary = {
            "project_id": project_id,
            "title": project.get("title"),
            "goal": project.get("goal"),
            "generated_at": utcnow_iso(),
            "run_id": run_id,
            "task_summary": {
                "total": len(tasks),
                "completed": len(done),
                "unfinished": len(unfinished),
            },
            "knowledge": {
                "total": len(chunks),
                "verified": len(verified),
                "unverified": len(unverified),
                "partitions": self.metadata.partition_stats(project_id),
            },
            "sources": sources,
            "conflicts": [
                {
                    "conflict_id": c["conflict_id"],
                    "kind": c["kind"],
                    "status": c["status"],
                    "detail": c["detail"],
                    "chunk_a": c["chunk_a"],
                    "chunk_b": c["chunk_b"],
                }
                for c in conflicts
            ],
            "duplicates": duplicates,
            "gaps": [
                {"topic": g["topic"], "level": g["level"], "reason": g["reason"], "priority": g["priority"]}
                for g in gaps
            ],
            "practices": [
                {"practice_id": p["practice_id"], "kind": p["kind"], "title": p["title"], "status": p["status"]}
                for p in practices
            ],
            "experiments": experiments,
            "metrics": evaluation.get("metrics", {}),
            "goal_met": bool(evaluation.get("goal_met")),
            "remaining": evaluation.get("remaining", []),
            "runs": [
                {
                    "run_id": r["run_id"],
                    "iteration": r["iteration"],
                    "status": r["status"],
                    "stop_reason": r["stop_reason"],
                    "started_at": r["started_at"],
                }
                for r in runs
            ],
        }

        markdown = self._render_markdown(summary, verified, unverified, unfinished)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        base = self.reports_dir / f"{project_id}-{stamp}"
        md_path = base.with_suffix(".md")
        json_path = base.with_suffix(".json")
        md_path.write_text(markdown, encoding="utf-8")
        json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "report_path": str(md_path),
            "json_path": str(json_path),
            "summary": summary,
            "markdown": markdown,
        }

    # ------------------------------------------------------------------ #
    def _render_markdown(
        self,
        summary: Mapping[str, Any],
        verified: List[Mapping[str, Any]],
        unverified: List[Mapping[str, Any]],
        unfinished: List[Mapping[str, Any]],
    ) -> str:
        m = summary.get("metrics", {})
        lines: List[str] = []
        lines.append(f"# 学习报告：{summary.get('title')}")
        lines.append("")
        lines.append(f"- 生成时间：{summary.get('generated_at')}")
        lines.append(f"- 学习目标：{summary.get('goal')}")
        lines.append(f"- 达标判定：{'达标（可进入人工评审）' if summary.get('goal_met') else '未达标'}")
        lines.append("")
        lines.append("## 一、任务")
        ts = summary.get("task_summary", {})
        lines.append(f"- 总任务 {ts.get('total', 0)}，已完成 {ts.get('completed', 0)}，未完成 {ts.get('unfinished', 0)}")
        if unfinished:
            lines.append("")
            lines.append("未完成任务：")
            for task in unfinished[:20]:
                lines.append(f"- [{task['kind']}] {task['title']}（{task['status']}）")
        lines.append("")
        lines.append("## 二、知识库")
        kn = summary.get("knowledge", {})
        lines.append(f"- 知识片段 {kn.get('total', 0)}，已核验 {kn.get('verified', 0)}，未核验 {kn.get('unverified', 0)}")
        lines.append(f"- 覆盖率 {m.get('coverage_rate', 0):.0%}，核验率 {m.get('verification_rate', 0):.0%}，"
                     f"来源完整率 {m.get('source_completeness', 0):.0%}")
        lines.append("")
        lines.append("分区统计：")
        for part in kn.get("partitions", []):
            lines.append(
                f"- {part['partition']}：{part['total']} 条（已核验 {part['verified']}，待核验 {part['pending_verification']}，"
                f"冲突 {part['conflicts']}）"
            )
        lines.append("")
        lines.append("## 三、已核验结论")
        if verified:
            for chunk in verified[:30]:
                lines.append(
                    f"- **{chunk.get('title')}**（{chunk.get('knowledge_type')}，置信度 {chunk.get('confidence')}，"
                    f"来源 {chunk.get('source_title') or chunk.get('source_url') or '未记录'}）"
                )
                lines.append(f"  - {str(chunk.get('summary') or '')[:200]}")
                lines.append(f"  - 核验方法：{chunk.get('verification_method')}；依据：{chunk.get('confidence_basis')}")
        else:
            lines.append("- 暂无已核验结论。未核验不等于错误，但**不能当作既定事实使用**。")
        lines.append("")
        lines.append("## 四、未核验/待处理结论")
        if unverified:
            for chunk in unverified[:30]:
                lines.append(
                    f"- {chunk.get('title')}（{chunk.get('status')}，核验状态 {chunk.get('verification_status')}，"
                    f"冲突 {chunk.get('conflict_status')}）"
                )
        else:
            lines.append("- 无")
        lines.append("")
        lines.append("## 五、冲突与不确定性")
        conflicts = summary.get("conflicts", [])
        if conflicts:
            for conflict in conflicts:
                lines.append(
                    f"- [{conflict['status']}] {conflict['kind']}：{conflict['detail']}"
                    f"（{conflict['chunk_a']} ↔ {conflict['chunk_b']}）"
                )
        else:
            lines.append("- 未检测到已记录冲突")
        gaps = summary.get("gaps", [])
        if gaps:
            lines.append("")
            lines.append("知识缺口：")
            for gap in gaps[:20]:
                lines.append(f"- [{gap['level']}] {gap['topic']}：{gap['reason']}（优先级 {gap['priority']}）")
        lines.append("")
        lines.append("## 六、实践与实验")
        practices = summary.get("practices", [])
        if practices:
            for practice in practices[:20]:
                lines.append(f"- [{practice['kind']}] {practice['title']}：{practice['status']}")
        else:
            lines.append("- 尚未生成实践任务")
        experiments = summary.get("experiments", [])
        if experiments:
            for exp in experiments[:10]:
                lines.append(f"- 实验 {exp['experiment_id']}：{exp['status']}（产物 {exp['artifact_dir'] or '无'}）")
        lines.append("")
        lines.append("## 七、主要来源")
        sources = summary.get("sources", [])
        if sources:
            for src in sources[:30]:
                lines.append(
                    f"- {src['title'] or src['location']}（{src['source_type']}，质量 {src['quality']}，"
                    f"许可 {src['license_status']}，时效 {src['freshness_status']}）"
                )
        else:
            lines.append("- 无来源记录")
        lines.append("")
        lines.append("## 八、成本与运行")
        llm = m.get("llm", {})
        lines.append(
            f"- 模型调用 {int(llm.get('calls', 0))} 次，token {int(llm.get('prompt_tokens', 0))}/"
            f"{int(llm.get('completion_tokens', 0))}，费用估算 {llm.get('cost_estimate', 0):.4f} USD"
        )
        lines.append(f"- 单位任务成本（估算）：{m.get('cost_per_task', 0):.6f} USD")
        runs = summary.get("runs", [])
        if runs:
            lines.append("")
            lines.append("最近运行：")
            for run in runs:
                lines.append(
                    f"- 第 {run['iteration']} 轮：{run['status']}（{run['stop_reason'] or '正常结束'}）"
                )
        lines.append("")
        lines.append("## 九、后续建议")
        remaining = summary.get("remaining", [])
        if remaining:
            for item in remaining:
                lines.append(f"- {item}")
        else:
            lines.append("- 当前指标达标，建议进入人工评审，并补充真实业务场景验证")
        lines.append("- 对未核验知识补充独立来源；对冲突项保留双方证据并做冲突分析")
        lines.append("- 对可实践知识补充受控实验；不要把历史回测收益当作未来收益")
        lines.append("")
        lines.append("---")
        lines.append("本报告由 DSH 自主学习插件自动生成；所有结论均可追溯到来源与核验记录。")
        return "\n".join(lines)


__all__ = ["ReportGenerator"]
