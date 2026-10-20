"""轻量知识关系图。

第一阶段用 SQLite ``edges`` 表实现，不引入图数据库（规范允许）。
关系类型：depends_on / includes / similar_to / conflicts_with / cites /
supersedes / derived_from / applies_to。

关键约束（规则 1）：
- 跨领域知识只建立关系，**不合并**；
- 关系边保留创建理由与权重，可审计；
- 图遍历有深度与节点数上限，避免大图把上下文撑爆。
"""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, Iterable, List, Optional, Set

from ..core.models import RelationType, new_id, utcnow_iso
from ..storage.metadata_store import MetadataStore


class KnowledgeGraph:
    def __init__(self, metadata: MetadataStore) -> None:
        self.metadata = metadata

    # ------------------------------------------------------------------ #
    def link(
        self,
        src_id: str,
        dst_id: str,
        relation: str,
        *,
        weight: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        relation = RelationType.parse(relation, "relation").value
        if src_id == dst_id:
            raise ValueError("不能把知识与自身建立关系")
        for chunk_id in (src_id, dst_id):
            if not self.metadata.get_chunk(chunk_id):
                raise ValueError(f"知识片段不存在: {chunk_id}")
        existing = self.metadata.query_dicts(
            "SELECT edge_id FROM edges WHERE src_id=? AND dst_id=? AND relation=?",
            (src_id, dst_id, relation),
        )
        if existing:
            return {"edge_id": existing[0]["edge_id"], "created": False}
        edge = {
            "edge_id": new_id("edge"),
            "src_id": src_id,
            "dst_id": dst_id,
            "relation": relation,
            "weight": float(weight),
            "metadata": metadata or {},
            "created_at": utcnow_iso(),
        }
        self.metadata.add_edge(edge)
        return {"edge_id": edge["edge_id"], "created": True, **edge}

    def unlink(self, edge_id: str) -> bool:
        return self.metadata.delete("edges", edge_id) > 0

    # ------------------------------------------------------------------ #
    def neighbors(
        self,
        chunk_id: str,
        *,
        relation: Optional[str] = None,
        direction: str = "both",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        edges = self.metadata.relations(chunk_id, direction)
        out: List[Dict[str, Any]] = []
        for edge in edges:
            if relation and edge["relation"] != relation:
                continue
            other_id = edge["dst_id"] if edge["src_id"] == chunk_id else edge["src_id"]
            other = self.metadata.get_chunk(other_id)
            if not other:
                continue
            out.append(
                {
                    "edge_id": edge["edge_id"],
                    "chunk_id": other_id,
                    "title": other.get("title", ""),
                    "relation": edge["relation"],
                    "direction": "out" if edge["src_id"] == chunk_id else "in",
                    "weight": edge["weight"],
                    "status": other.get("status", ""),
                    "partition": other.get("partition", ""),
                }
            )
            if len(out) >= limit:
                break
        return out

    def subgraph(self, chunk_id: str, *, depth: int = 2, max_nodes: int = 40) -> Dict[str, Any]:
        depth = max(1, min(int(depth), 4))
        seen: Set[str] = {chunk_id}
        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []
        queue = deque([(chunk_id, 0)])
        while queue and len(seen) < max_nodes:
            current, level = queue.popleft()
            chunk = self.metadata.get_chunk(current)
            if chunk:
                nodes.append(
                    {
                        "chunk_id": current,
                        "title": chunk.get("title", ""),
                        "partition": chunk.get("partition", ""),
                        "status": chunk.get("status", ""),
                        "level": level,
                    }
                )
            if level >= depth:
                continue
            for edge in self.metadata.relations(current, "both"):
                edges.append(
                    {
                        "src": edge["src_id"],
                        "dst": edge["dst_id"],
                        "relation": edge["relation"],
                        "weight": edge["weight"],
                    }
                )
                other = edge["dst_id"] if edge["src_id"] == current else edge["src_id"]
                if other not in seen and len(seen) < max_nodes:
                    seen.add(other)
                    queue.append((other, level + 1))
        return {"root": chunk_id, "nodes": nodes, "edges": edges[: max_nodes * 3], "truncated": len(seen) >= max_nodes}

    # ------------------------------------------------------------------ #
    def auto_link_topic(self, chunk_id: str, *, limit: int = 5, min_similarity: float = 0.55) -> int:
        """按同主题建立 similar_to 关系（不合并，只关联）。"""

        chunk = self.metadata.get_chunk(chunk_id)
        if not chunk:
            raise ValueError(f"知识片段不存在: {chunk_id}")
        topic = chunk.get("topic")
        if not topic:
            return 0
        rows = self.metadata.query_dicts(
            "SELECT chunk_id FROM chunks WHERE topic=? AND chunk_id<>? LIMIT ?",
            (topic, chunk_id, limit * 4),
        )
        created = 0
        for row in rows:
            if created >= limit:
                break
            try:
                result = self.link(
                    chunk_id,
                    row["chunk_id"],
                    RelationType.SIMILAR_TO.value,
                    weight=min_similarity,
                    metadata={"basis": "same_topic", "topic": topic},
                )
            except ValueError:
                continue
            if result.get("created"):
                created += 1
        return created

    def stats(self) -> Dict[str, Any]:
        rows = self.metadata.query_dicts("SELECT relation, COUNT(*) AS n FROM edges GROUP BY relation")
        return {
            "edges": sum(int(r["n"]) for r in rows),
            "by_relation": {r["relation"]: int(r["n"]) for r in rows},
        }


__all__ = ["KnowledgeGraph"]
