"""重复知识检测（规则 1/3：相似不等于同一事实）。

两种重复：
- 完全重复：内容指纹（content_hash）相同；
- 近似重复：向量相似度超过阈值（默认 0.94）。

处理后约定：
- 重复不会自动删除，而是登记到 ``duplicates`` 表，状态 open，等待人工/规则确认；
- 合并（merge）只做"标记为 superseded + 建立 supersedes 关系"，保留全部历史；
- 跨领域相似不合并：只建立 similar_to 关系，避免把统计学知识并进量化策略。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from ..core.models import KnowledgeStatus, RelationType, new_id, utcnow_iso
from ..storage.metadata_store import ChunkFilter, MetadataStore
from ..storage.vector_store import KnowledgeStore


@dataclass
class DuplicateReport:
    exact: List[Dict[str, Any]]
    near: List[Dict[str, Any]]
    recorded: int
    warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "exact_duplicates": self.exact,
            "near_duplicates": self.near,
            "recorded": self.recorded,
            "warnings": self.warnings,
            "total": len(self.exact) + len(self.near),
        }


class Deduplicator:
    def __init__(self, store: KnowledgeStore, metadata: MetadataStore) -> None:
        self.store = store
        self.metadata = metadata

    # ------------------------------------------------------------------ #
    def find_and_record(
        self,
        *,
        chunk_id: Optional[str] = None,
        project_id: Optional[str] = None,
        threshold: Optional[float] = None,
        limit: int = 200,
    ) -> Dict[str, Any]:
        warnings: List[str] = []
        exact: List[Dict[str, Any]] = []
        near: List[Dict[str, Any]] = []

        if chunk_id:
            chunk = self.metadata.get_chunk(chunk_id)
            if not chunk:
                raise ValueError(f"知识片段不存在: {chunk_id}")
            pairs = self.store.find_duplicates(chunk_id, threshold=threshold)
        else:
            filters = ChunkFilter(project_id=project_id)
            pairs = self.store.find_duplicates(threshold=threshold, filters=filters, max_pairs=limit)

        for pair in pairs:
            if pair.get("reason") == "content_hash":
                exact.append(pair)
            else:
                near.append(pair)

        recorded = 0
        for pair in exact + near:
            if self._pair_exists(pair["chunk_a"], pair["chunk_b"]):
                continue
            if self._contradictory(pair["chunk_a"], pair["chunk_b"]):
                # 结论矛盾的两个片段不是"重复"，交给冲突检测，绝不合并
                continue
            self.metadata.add_duplicate(
                {
                    "dup_id": new_id("dup"),
                    "project_id": project_id or self._project_of(pair["chunk_a"]),
                    "chunk_a": pair["chunk_a"],
                    "chunk_b": pair["chunk_b"],
                    "similarity": float(pair.get("similarity", 0.0)),
                    "reason": pair.get("reason", "vector_similarity"),
                    "status": "open",
                    "created_at": utcnow_iso(),
                }
            )
            recorded += 1

        if not pairs:
            warnings.append("未发现重复知识")
        return DuplicateReport(exact=exact, near=near, recorded=recorded, warnings=warnings).to_dict()

    def list_open(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.metadata.list_duplicates(project_id)

    # ------------------------------------------------------------------ #
    def merge(
        self, keep_id: str, drop_id: str, *, reason: str = "duplicate_merge", actor: str = "system"
    ) -> Dict[str, Any]:
        """合并重复：保留 keep，drop 标记 superseded 并建立关系。"""

        keep = self.metadata.get_chunk(keep_id)
        drop = self.metadata.get_chunk(drop_id)
        if not keep or not drop:
            raise ValueError("合并双方必须都存在")
        self.store.invalidate_document(drop_id, reason=reason, superseded_by=keep_id)
        self.metadata.add_edge(
            {
                "edge_id": new_id("edge"),
                "src_id": drop_id,
                "dst_id": keep_id,
                "relation": RelationType.SUPERSEDES.value,
                "weight": 1.0,
                "metadata": {"reason": reason, "actor": actor},
                "created_at": utcnow_iso(),
            }
        )
        for dup in self.metadata.list_duplicates(keep.get("project_id")):
            if {dup["chunk_a"], dup["chunk_b"]} == {keep_id, drop_id}:
                self.metadata.update("duplicates", dup["dup_id"], {"status": "merged"})
        return {
            "kept": keep_id,
            "superseded": drop_id,
            "status": KnowledgeStatus.SUPERSEDED.value,
            "reason": reason,
        }

    # ------------------------------------------------------------------ #
    def _pair_exists(self, a: str, b: str) -> bool:
        rows = self.metadata.query_dicts(
            "SELECT dup_id FROM duplicates WHERE (chunk_a=? AND chunk_b=?) OR (chunk_a=? AND chunk_b=?)",
            (a, b, b, a),
        )
        return bool(rows)

    def _contradictory(self, a: str, b: str) -> bool:
        """相似但结论矛盾的两个片段不能当重复处理。"""

        from .conflict_detector import ConflictDetector

        chunk_a = self.metadata.get_chunk(a)
        chunk_b = self.metadata.get_chunk(b)
        if not chunk_a or not chunk_b:
            return False
        return bool(ConflictDetector(self.store, self.metadata).detect_pair(chunk_a, chunk_b))

    def _project_of(self, chunk_id: str) -> str:
        chunk = self.metadata.get_chunk(chunk_id)
        return chunk["project_id"] if chunk else ""


__all__ = ["Deduplicator", "DuplicateReport"]
