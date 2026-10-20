"""知识缺口分析。

覆盖率不是"文件数"，而是按规划主题计算 L0-L5：
- L0 未覆盖：该主题没有任何知识片段
- L1 已发现：只有 discovered 片段
- L2 已提取：存在 extracted / pending_verification
- L3 已核验：至少一条 verified
- L4 已实践：至少一条 practiced
- L5 已评估：至少一条 evaluated

缺口判定（可配置目标等级，默认 L3）：
- 覆盖率不足、只有单一来源、未核验、存在冲突、可能过时、重复堆积。
每条缺口都会写入 ``gaps`` 表，由编排器生成补充任务。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from ..storage.metadata_store import ChunkFilter, MetadataStore
from .models import (
    Gap,
    GapStatus,
    KnowledgeStatus,
    LearningLevel,
    new_id,
    utcnow_iso,
)
from .state_machine import at_least, max_level

TARGET_LEVEL_DEFAULT = LearningLevel.L3.value


@dataclass
class TopicCoverage:
    topic: str
    total: int = 0
    level: str = LearningLevel.L0.value
    verified: int = 0
    pending: int = 0
    stale: int = 0
    disputed: int = 0
    practiced: int = 0
    sources: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "topic": self.topic,
            "total": self.total,
            "level": self.level,
            "verified": self.verified,
            "pending_verification": self.pending,
            "stale": self.stale,
            "disputed": self.disputed,
            "practiced": self.practiced,
            "independent_sources": self.sources,
        }


class KnowledgeGapAnalyzer:
    def __init__(self, metadata: MetadataStore) -> None:
        self.metadata = metadata

    # ------------------------------------------------------------------ #
    def topics(self, project_id: str) -> List[str]:
        """项目已规划的主题（来自任务的 inputs.topic，去重保序）。"""

        rows = self.metadata.query_dicts(
            "SELECT inputs FROM tasks WHERE project_id=? ORDER BY created_at", (project_id,)
        )
        import json

        topics: List[str] = []
        for row in rows:
            try:
                data = json.loads(row["inputs"] or "{}")
            except json.JSONDecodeError:
                continue
            topic = (data or {}).get("topic")
            if topic and topic not in topics:
                topics.append(str(topic))
        return topics

    # ------------------------------------------------------------------ #
    def analyze(self, project_id: str, *, target_level: str = TARGET_LEVEL_DEFAULT, record: bool = True) -> Dict[str, Any]:
        project = self.metadata.get_project(project_id)
        if not project:
            raise ValueError(f"项目不存在: {project_id}")

        coverage: List[TopicCoverage] = []
        gaps: List[Dict[str, Any]] = []

        for topic in self.topics(project_id):
            rows = self.metadata.list_chunks(
                ChunkFilter(project_id=project_id, topics=[topic]), limit=5000
            )
            item = TopicCoverage(topic=topic, total=len(rows))
            levels: List[str] = []
            source_keys = set()
            for row in rows:
                levels.append(row.get("level") or LearningLevel.L2.value)
                status = row.get("status")
                if status == KnowledgeStatus.VERIFIED.value or row.get("verification_status") == "verified":
                    item.verified += 1
                if status == KnowledgeStatus.PENDING_VERIFICATION.value:
                    item.pending += 1
                if status == KnowledgeStatus.STALE.value or row.get("freshness_status") in {"stale", "expired"}:
                    item.stale += 1
                if status == KnowledgeStatus.DISPUTED.value or row.get("conflict_status") in {"potential", "confirmed"}:
                    item.disputed += 1
                if status in {KnowledgeStatus.PRACTICED.value, KnowledgeStatus.EVALUATED.value}:
                    item.practiced += 1
                key = row.get("source_id") or row.get("source_url")
                if key:
                    source_keys.add(key)
            item.sources = len(source_keys)
            item.level = max_level(*levels) if levels else LearningLevel.L0.value
            coverage.append(item)

            if item.total == 0:
                gaps.append(
                    {
                        "topic": topic,
                        "level": item.level,
                        "reason": "没有任何知识片段",
                        "priority": 0.95,
                        "kind": "no_knowledge",
                    }
                )
            elif not at_least(item.level, target_level):
                gaps.append(
                    {
                        "topic": topic,
                        "level": item.level,
                        "reason": f"覆盖等级 {item.level} 低于目标 {target_level}（未核验/未实践）",
                        "priority": 0.8 if item.pending else 0.7,
                        "kind": "below_target",
                    }
                )
            if item.total and item.sources <= 1 and item.verified == 0:
                gaps.append(
                    {
                        "topic": topic,
                        "level": item.level,
                        "reason": "只有单一来源且未核验，需要独立来源交叉验证",
                        "priority": 0.75,
                        "kind": "single_source",
                    }
                )
            if item.stale:
                gaps.append(
                    {
                        "topic": topic,
                        "level": item.level,
                        "reason": f"{item.stale} 条知识可能过时，需要检查更新版本",
                        "priority": 0.6,
                        "kind": "stale",
                    }
                )
            if item.disputed:
                gaps.append(
                    {
                        "topic": topic,
                        "level": item.level,
                        "reason": f"{item.disputed} 条知识存在冲突或争议，需要冲突分析",
                        "priority": 0.7,
                        "kind": "conflict",
                    }
                )

        # 全局缺口：未分配主题的知识、重复堆积
        typed_rows = self.metadata.query_dicts(
            "SELECT topic, COUNT(*) AS n FROM chunks WHERE project_id=? GROUP BY topic", (project_id,)
        )
        for row in typed_rows:
            topic = row["topic"] or ""
            if topic and topic not in [c.topic for c in coverage]:
                gaps.append(
                    {
                        "topic": topic,
                        "level": LearningLevel.L2.value,
                        "reason": "知识存在但未纳入学习计划",
                        "priority": 0.5,
                        "kind": "unplanned",
                    }
                )
        dup_count = len(self.metadata.list_duplicates(project_id))
        if dup_count:
            gaps.append(
                {
                    "topic": "__duplicates__",
                    "level": LearningLevel.L2.value,
                    "reason": f"{dup_count} 组重复知识待合并",
                    "priority": 0.35,
                    "kind": "duplicates",
                }
            )

        recorded: List[Dict[str, Any]] = []
        if record:
            for gap in gaps:
                if gap["topic"] == "__duplicates__":
                    continue
                row = Gap(
                    gap_id=new_id("gap"),
                    project_id=project_id,
                    topic=gap["topic"],
                    subtopic="",
                    level=gap["level"],
                    reason=gap["reason"],
                    status=GapStatus.OPEN.value,
                    priority=float(gap["priority"]),
                )
                recorded.append(self.metadata.add_gap(row.to_row()))

        covered = sum(1 for c in coverage if at_least(c.level, target_level))
        return {
            "project_id": project_id,
            "target_level": target_level,
            "coverage": [c.to_dict() for c in coverage],
            "coverage_rate": round(covered / len(coverage), 3) if coverage else 0.0,
            "gaps": gaps,
            "recorded_gaps": len(recorded),
            "unverified_chunks": int(
                self.metadata.scalar(
                    "SELECT COUNT(*) FROM chunks WHERE project_id=? AND verification_status<>'verified'",
                    (project_id,),
                    0,
                )
                or 0
            ),
            "stale_chunks": int(
                self.metadata.scalar(
                    "SELECT COUNT(*) FROM chunks WHERE project_id=? AND (status='stale' OR freshness_status IN ('stale','expired'))",
                    (project_id,),
                    0,
                )
                or 0
            ),
            "duplicates": dup_count,
            "timestamp": utcnow_iso(),
        }

    # ------------------------------------------------------------------ #
    def open_gaps(self, project_id: str) -> List[Dict[str, Any]]:
        return self.metadata.list_gaps(project_id, status=GapStatus.OPEN.value)


__all__ = ["KnowledgeGapAnalyzer", "TARGET_LEVEL_DEFAULT", "TopicCoverage"]
