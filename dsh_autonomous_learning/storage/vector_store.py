"""向量知识库（统一 KnowledgeStore 接口）。

实现取舍（已在技术选型报告中说明）：
- 元数据/过滤走 SQLite，向量走本地 ``.npy`` 矩阵 + 暴力余弦检索。
  在数万级片段规模下延迟可接受（< 100ms），且完全可离线、可复现、可精确测试；
  比直接引入 Chroma/Qdrant 更轻，也不会把业务逻辑绑定到某个集合名。
- 关键词通道用自研 BM25 倒排表；两路用 RRF 融合（可配置权重）。
- 接口保持与规范一致的 ``add_document / search / update_document /
  invalidate_document / delete_document / get_by_id / find_duplicates /
  find_conflicts / backup``，将来替换成 Chroma/Qdrant 只需替换本类实现。

安全与正确性约束：
- 换向量模型必须重建索引（清单里记录 embedder_id 与 dim），否则拒绝检索并报错。
- 检索结果永远带来源与核验状态；相似度不是"正确性"。
- 项目知识默认只在所属项目的检索中可见（visibility=project）。
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from ..config import RetrievalConfig
from ..core.embedder import BaseEmbedder, EmbeddingError
from ..core.models import (
    Chunk,
    KnowledgeStatus,
    LicenseStatus,
    SourceType,
    new_id,
    normalize_text,
    stable_hash,
    utcnow_iso,
)
from .metadata_store import ChunkFilter, MetadataStore, StorageError
from .tokenizer import expand_query

INDEX_VERSION = 1
MANIFEST = "manifest.json"
VECTORS = "vectors.npy"
IDS = "ids.json"


class KnowledgeStoreError(RuntimeError):
    """知识库操作错误。"""


class KnowledgeStore:
    """向量 + 元数据一体的知识库。"""

    def __init__(
        self,
        metadata: MetadataStore,
        index_dir: str | Path,
        embedder: BaseEmbedder,
        retrieval: Optional[RetrievalConfig] = None,
    ) -> None:
        self.metadata = metadata
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self.retrieval = retrieval or RetrievalConfig()
        self._ids: List[str] = []
        self._pos: Dict[str, int] = {}
        self._matrix: np.ndarray = np.zeros((0, embedder.dim or 0), dtype=np.float32)
        self._dirty = False
        self._last_error = ""
        self._load_index()

    # ------------------------------------------------------------------ #
    # 索引生命周期
    # ------------------------------------------------------------------ #
    @property
    def manifest_path(self) -> Path:
        return self.index_dir / MANIFEST

    def _load_index(self) -> None:
        if not self.manifest_path.exists():
            return
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self._last_error = f"索引清单损坏: {exc}"
            return
        if manifest.get("embedder_id") != self.embedder.embedder_id:
            self._last_error = (
                "索引是用不同的向量化器建立的："
                f"索引={manifest.get('embedder_id')}，当前={self.embedder.embedder_id}。"
                "请运行 rebuild_index() 重建，或在配置中改回原向量化器。"
            )
            return
        try:
            self._ids = json.loads((self.index_dir / IDS).read_text(encoding="utf-8"))
            self._matrix = np.load(self.index_dir / VECTORS, allow_pickle=False)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._last_error = f"索引文件读取失败: {exc}"
            self._ids, self._matrix = [], np.zeros((0, self.embedder.dim), dtype=np.float32)
            return
        if len(self._ids) != int(self._matrix.shape[0]):
            self._last_error = "索引 ids 与向量行数不一致，请重建索引"
            self._ids, self._matrix = [], np.zeros((0, self.embedder.dim), dtype=np.float32)
            return
        if self._matrix.size and int(self._matrix.shape[1]) != int(self.embedder.dim):
            self._last_error = "索引维度与当前向量化器不一致，请重建索引"
            self._ids, self._matrix = [], np.zeros((0, self.embedder.dim), dtype=np.float32)
            return
        self._pos = {cid: i for i, cid in enumerate(self._ids)}

    def _save_index(self) -> None:
        if self._matrix.ndim == 1:
            self._matrix = self._matrix.reshape(0, self.embedder.dim)
        ids_tmp = self.index_dir / (IDS + ".tmp")
        vec_tmp = self.index_dir / (VECTORS + ".tmp")
        ids_tmp.write_text(json.dumps(self._ids, ensure_ascii=False), encoding="utf-8")
        np.save(vec_tmp, self._matrix.astype(np.float32), allow_pickle=False)
        os.replace(ids_tmp, self.index_dir / IDS)
        os.replace(str(vec_tmp) + ".npy", self.index_dir / VECTORS)
        manifest = {
            "index_version": INDEX_VERSION,
            "embedder_id": self.embedder.embedder_id,
            "dim": int(self._matrix.shape[1] if self._matrix.size else self.embedder.dim),
            "count": len(self._ids),
            "updated_at": utcnow_iso(),
            "backend": "local_numpy",
        }
        tmp = self.index_dir / (MANIFEST + ".tmp")
        tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.manifest_path)
        self._dirty = False

    def rebuild_index(self, batch_size: int = 64) -> Dict[str, Any]:
        """按元数据重建向量索引（用于换模型、修复损坏索引）。"""

        ids = self.metadata.list_chunk_ids()
        vectors: List[np.ndarray] = []
        kept_ids: List[str] = []
        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i : i + batch_size]
            chunks = self.metadata.get_chunks(batch_ids)
            texts = [_index_text(c) for c in chunks]
            if not texts:
                continue
            matrix = self.embedder.embed(texts)
            vectors.append(matrix.astype(np.float32))
            kept_ids.extend([c["chunk_id"] for c in chunks])
        self._ids = kept_ids
        self._matrix = (
            np.vstack(vectors).astype(np.float32)
            if vectors
            else np.zeros((0, self.embedder.dim), dtype=np.float32)
        )
        self._pos = {cid: i for i, cid in enumerate(self._ids)}
        self._last_error = ""
        self._save_index()
        return {"indexed": len(self._ids), "embedder": self.embedder.embedder_id}

    # ------------------------------------------------------------------ #
    # 写入
    # ------------------------------------------------------------------ #
    def _vectorize(self, chunks: Sequence[Mapping[str, Any]]) -> np.ndarray:
        texts = [_index_text(c) for c in chunks]
        try:
            matrix = self.embedder.embed(texts)
        except EmbeddingError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise KnowledgeStoreError(f"向量化失败: {exc}") from exc
        matrix = np.asarray(matrix, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[1] != (self.embedder.dim or matrix.shape[1]):
            raise KnowledgeStoreError("向量化返回的维度不符合预期")
        if not self.embedder.dim:
            self.embedder.dim = int(matrix.shape[1])
        return matrix

    def add_chunks(self, chunks: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        """批量写入知识片段（幂等：同 chunk_id 覆盖；同内容指纹识别重复）。"""

        if not chunks:
            return {"added": 0, "updated": 0, "duplicates": [], "chunks": []}
        prepared: List[Dict[str, Any]] = []
        seen_content: Dict[str, str] = {}
        duplicates: List[Dict[str, Any]] = []
        for raw in chunks:
            chunk = _coerce_chunk(raw)
            fp = chunk.get("content_hash") or stable_hash(normalize_text(chunk["content"]))
            chunk["content_hash"] = fp
            existing_same = self.metadata.find_chunks_by_hash(fp, chunk.get("project_id"))
            same_other = [c for c in existing_same if c["chunk_id"] != chunk["chunk_id"]]
            if same_other or fp in seen_content:
                duplicates.append(
                    {
                        "chunk_id": chunk["chunk_id"],
                        "duplicate_of": (same_other[0]["chunk_id"] if same_other else seen_content[fp]),
                        "reason": "content_hash",
                    }
                )
            seen_content.setdefault(fp, chunk["chunk_id"])
            prepared.append(chunk)

        matrix = self._vectorize(prepared)

        added = updated = 0
        for chunk in prepared:
            exists = self.metadata.get_chunk(chunk["chunk_id"]) is not None
            if exists:
                updated += 1
            else:
                added += 1
            # 先写元数据（含词元索引），再写向量，保证检索时元数据一定已落库
            self.metadata.upsert_chunk(chunk)
        kept_ids: List[str] = []
        kept_rows: List[int] = []
        for row, chunk in enumerate(prepared):
            cid = chunk["chunk_id"]
            if cid in self._pos:
                self._matrix[self._pos[cid]] = matrix[row]
            else:
                kept_ids.append(cid)
                kept_rows.append(row)
        if kept_ids:
            new_block = matrix[kept_rows]
            self._matrix = (
                np.vstack([self._matrix, new_block]).astype(np.float32)
                if self._matrix.size
                else new_block.astype(np.float32)
            )
            start = len(self._ids)
            self._ids.extend(kept_ids)
            for offset, cid in enumerate(kept_ids):
                self._pos[cid] = start + offset
        self._dirty = True
        self._save_index()
        return {
            "added": added,
            "updated": updated,
            "duplicates": duplicates,
            "chunks": [c["chunk_id"] for c in prepared],
        }

    def add_document(
        self,
        document_id: str,
        chunks: Sequence[Mapping[str, Any]],
        *,
        project_id: str = "",
        replace_existing: bool = False,
    ) -> Dict[str, Any]:
        """把一篇文档切出的片段批量入库。"""

        if replace_existing:
            self._remove_document_vectors(document_id)
            self.metadata.query("DELETE FROM chunks WHERE document_id=?", (document_id,))
        payload = []
        for raw in chunks:
            chunk = dict(raw)
            chunk.setdefault("document_id", document_id)
            if project_id:
                chunk.setdefault("project_id", project_id)
            payload.append(chunk)
        return self.add_chunks(payload)

    def update_document(self, chunk_id: str, fields: Mapping[str, Any], *, reason: str = "update") -> Dict[str, Any]:
        """更新知识片段：保留旧版本快照，内容变化时重算指纹与向量。"""

        chunk = self.metadata.get_chunk(chunk_id)
        if not chunk:
            raise KnowledgeStoreError(f"知识片段不存在: {chunk_id}")
        new_content = fields.get("content", chunk["content"])
        if normalize_text(new_content) != normalize_text(chunk["content"]):
            version = int(chunk.get("version", 1))
            self.metadata.add_version(
                {
                    "id": new_id("ver"),
                    "chunk_id": chunk_id,
                    "version": version,
                    "content_hash": chunk.get("content_hash", ""),
                    "content": chunk["content"],
                    "status": chunk["status"],
                    "change_reason": reason,
                    "changed_at": utcnow_iso(),
                }
            )
            fields = dict(fields)
            fields["version"] = version + 1
            fields["content_hash"] = stable_hash(normalize_text(new_content))
            fields.setdefault("verification_status", "unverified")
            fields.setdefault("verification_method", "none")
            fields.setdefault("verification_evidence", [])
            fields.setdefault("status", KnowledgeStatus.PENDING_VERIFICATION.value)
            fields.setdefault("evidence_count", 0)
            fields.setdefault("evidence_independence", 0)
            fields.setdefault("confidence", 0.3)
            fields.setdefault("confidence_basis", "内容已更新，历史核验证据不再适用")
        self.metadata.update_chunk(chunk_id, fields)
        updated = self.metadata.get_chunk(chunk_id)
        assert updated is not None
        if chunk_id in self._pos:
            vec = self._vectorize([updated])[0]
            self._matrix[self._pos[chunk_id]] = vec
            self._save_index()
        else:
            self.add_chunks([updated])
        return {"chunk_id": chunk_id, "version": updated["version"], "status": updated["status"]}

    def invalidate_document(self, chunk_id: str, reason: str = "", superseded_by: str = "") -> Dict[str, Any]:
        """把知识标记为失效/过时（不物理删除，保留审计与历史）。"""

        chunk = self.metadata.get_chunk(chunk_id)
        if not chunk:
            raise KnowledgeStoreError(f"知识片段不存在: {chunk_id}")
        fields: Dict[str, Any] = {
            "freshness_status": "stale",
            "invalidated_at": utcnow_iso(),
            "limitations": (chunk.get("limitations") or "") + (f"\n失效原因: {reason}" if reason else ""),
        }
        if superseded_by:
            fields["status"] = KnowledgeStatus.SUPERSEDED.value
            fields["superseded_by"] = superseded_by
        elif chunk["status"] not in {KnowledgeStatus.SUPERSEDED.value, KnowledgeStatus.REJECTED.value}:
            fields["status"] = KnowledgeStatus.STALE.value
        self.metadata.update_chunk(chunk_id, fields)
        return {"chunk_id": chunk_id, "status": fields.get("status", chunk["status"]), "superseded_by": superseded_by}

    def delete_document(self, chunk_id: str) -> bool:
        """物理删除（高风险，调用方必须先经权限检查）。"""

        if chunk_id in self._pos:
            self._remove_vectors([chunk_id])
        return self.metadata.delete_chunk(chunk_id) > 0

    def get_by_id(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        chunk = self.metadata.get_chunk(chunk_id)
        if not chunk:
            return None
        chunk = dict(chunk)
        chunk["verification_records"] = self.metadata.list_verifications(chunk_id)
        chunk["relations"] = self.metadata.relations(chunk_id)
        chunk["versions"] = self.metadata.list_versions(chunk_id)
        chunk["has_vector"] = chunk_id in self._pos
        return chunk

    # ------------------------------------------------------------------ #
    # 检索
    # ------------------------------------------------------------------ #
    def _allowed_ids(self, filters: ChunkFilter) -> List[str]:
        project_id = filters.project_id
        project_ids = list(filters.project_ids or [])
        scoped = replace(filters, project_id=None, project_ids=None)
        where, args = scoped.to_sql("c")
        clauses: List[str] = []
        if where:
            clauses.append(where.replace(" WHERE ", "", 1))
        if project_id:
            clauses.append("(c.project_id = ? OR c.visibility = 'global')")
            args.append(project_id)
        if project_ids:
            placeholders = ",".join("?" * len(project_ids))
            clauses.append(f"(c.project_id IN ({placeholders}) OR c.visibility = 'global')")
            args.extend(project_ids)
        sql = "SELECT c.chunk_id FROM chunks c"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return [r["chunk_id"] for r in self.metadata.query(sql, args)]

    def search(
        self,
        query: str,
        filters: Optional[ChunkFilter] = None,
        top_k: Optional[int] = None,
        *,
        mode: Optional[str] = None,
        include_content: bool = True,
    ) -> Dict[str, Any]:
        """混合检索。返回结构化结果，包含来源、核验状态、冲突与时效提示。

        注意：相似度只代表"相关"，不代表"正确"。结果里显式携带
        verification_status / source_quality / confidence / warnings，
        让调用方（Agent）自己判断能否直接使用。
        """

        started = time.perf_counter()
        filters = filters or ChunkFilter()
        top_k = int(top_k or self.retrieval.top_k)
        mode = (mode or ("hybrid" if self.retrieval.hybrid else "vector")).lower()
        warnings: List[str] = []
        if self._last_error:
            warnings.append(self._last_error)

        allowed = self._allowed_ids(filters)
        if not allowed:
            return {
                "query": query,
                "mode": mode,
                "results": [],
                "warnings": warnings + ["知识库中没有满足过滤条件的知识，这意味着一个知识缺口"],
                "gap": True,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            }

        vector_rank: List[Tuple[str, float]] = []
        keyword_rank: List[Tuple[str, float]] = []

        if mode in {"vector", "hybrid"} and not self._last_error:
            vector_rank = self._vector_search(query, allowed, top_k=max(top_k * 4, 40))
        if mode in {"keyword", "hybrid"}:
            keyword_rank = [
                (cid, score)
                for cid, score in self.metadata.bm25_search(query, allowed, top_k=max(top_k * 4, 40))
            ]

        fused = self._fuse(vector_rank, keyword_rank, mode)
        if not fused:
            return {
                "query": query,
                "mode": mode,
                "results": [],
                "warnings": warnings + ["没有检索到相关知识（既无向量命中也无关键词命中）"],
                "gap": True,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            }

        rows = {c["chunk_id"]: c for c in self.metadata.get_chunks([cid for cid, _ in fused])}
        results: List[Dict[str, Any]] = []
        for chunk_id, score in fused[:top_k]:
            chunk = rows.get(chunk_id)
            if not chunk:
                continue
            item = self._format_result(chunk, score, include_content)
            results.append(item)

        elapsed = round((time.perf_counter() - started) * 1000, 2)
        return {
            "query": query,
            "mode": mode,
            "results": results,
            "warnings": warnings,
            "gap": not results,
            "elapsed_ms": elapsed,
            "filters": filters.describe(),
        }

    def _vector_search(
        self, query: str, allowed: Sequence[str], top_k: int
    ) -> List[Tuple[str, float]]:
        if not self._ids or not allowed:
            return []
        qv = self.embedder.embed_one(query or "").astype(np.float32)
        if qv.shape[0] != self._matrix.shape[1]:
            raise KnowledgeStoreError(
                f"查询向量维度 {qv.shape[0]} 与索引维度 {self._matrix.shape[1]} 不一致"
            )
        allowed_set = set(allowed)
        rows = [self._pos[cid] for cid in allowed if cid in self._pos]
        if not rows:
            return []
        sub = self._matrix[rows]
        # 向量均已 L2 归一化，点积即余弦
        sims = sub @ qv
        order = np.argsort(-sims)[: top_k]
        out: List[Tuple[str, float]] = []
        for idx in order:
            score = float(sims[idx])
            if score <= 0:
                continue
            cid = self._ids[rows[int(idx)]]
            if cid in allowed_set:
                out.append((cid, score))
        return out

    def _fuse(
        self,
        vector_rank: Sequence[Tuple[str, float]],
        keyword_rank: Sequence[Tuple[str, float]],
        mode: str,
    ) -> List[Tuple[str, float]]:
        k = max(1, int(self.retrieval.rrf_k))
        scores: Dict[str, float] = {}
        if mode == "vector":
            return list(vector_rank)
        if mode == "keyword":
            return list(keyword_rank)
        wv = self.retrieval.vector_weight
        wk = self.retrieval.keyword_weight
        for rank, (cid, _) in enumerate(vector_rank):
            scores[cid] = scores.get(cid, 0.0) + wv / (k + rank + 1)
        for rank, (cid, _) in enumerate(keyword_rank):
            scores[cid] = scores.get(cid, 0.0) + wk / (k + rank + 1)
        if not scores:
            return []
        peak = max(scores.values()) or 1.0
        fused = [(cid, value / peak) for cid, value in scores.items()]
        fused.sort(key=lambda x: -x[1])
        return fused

    def _format_result(self, chunk: Mapping[str, Any], score: float, include_content: bool) -> Dict[str, Any]:
        warnings: List[str] = []
        if chunk.get("verification_status") != "verified":
            warnings.append(f"核验状态为 {chunk.get('verification_status')}，不能当作既定事实")
        if chunk.get("status") == KnowledgeStatus.STALE.value or chunk.get("freshness_status") in {"stale", "expired"}:
            warnings.append("该知识可能已过时，使用前请核验更新版本")
        if chunk.get("conflict_status") == "confirmed":
            warnings.append("该知识存在已确认的来源冲突，请同时查看冲突记录")
        elif chunk.get("conflict_status") == "potential":
            warnings.append("该知识存在潜在冲突，尚未裁定")
        if chunk.get("license_status") in {LicenseStatus.UNKNOWN.value, LicenseStatus.RESTRICTED.value}:
            warnings.append(f"许可状态: {chunk.get('license_status')}，转载或商用前需确认")

        reliability = {
            "source_quality": chunk.get("source_quality", 0.0),
            "evidence_count": chunk.get("evidence_count", 0),
            "evidence_independence": chunk.get("evidence_independence", 0),
            "confidence": chunk.get("confidence", 0.0),
            "confidence_basis": chunk.get("confidence_basis", ""),
            "verification_method": chunk.get("verification_method", "none"),
        }
        # 排序微调：可靠性只做小幅加成，不允许低质量内容仅凭相似度夺冠
        adjusted = score * (0.85 + 0.15 * float(chunk.get("confidence") or 0.0))
        result = {
            "chunk_id": chunk["chunk_id"],
            "title": chunk.get("title", ""),
            "summary": chunk.get("summary", ""),
            "content": chunk.get("content", "") if include_content else "",
            "score": round(float(adjusted), 6),
            "similarity": round(float(score), 6),
            "partition": chunk.get("partition", ""),
            "domain": chunk.get("domain", ""),
            "topic": chunk.get("topic", ""),
            "subtopic": chunk.get("subtopic", ""),
            "knowledge_type": chunk.get("knowledge_type", ""),
            "status": chunk.get("status", ""),
            "level": chunk.get("level", ""),
            "verification_status": chunk.get("verification_status", ""),
            "reliability": reliability,
            "source": {
                "source_id": chunk.get("source_id", ""),
                "url": chunk.get("source_url", ""),
                "title": chunk.get("source_title", ""),
                "type": chunk.get("source_type", ""),
                "publisher": chunk.get("author_or_publisher", ""),
                "published_at": chunk.get("published_at", ""),
                "accessed_at": chunk.get("accessed_at", ""),
            },
            "version": chunk.get("version", 1),
            "updated_at": chunk.get("updated_at", ""),
            "freshness_status": chunk.get("freshness_status", "unknown"),
            "conflict_status": chunk.get("conflict_status", "none"),
            "need_reverify": bool(
                chunk.get("verification_status") != "verified"
                or chunk.get("freshness_status") in {"stale", "expired"}
                or chunk.get("conflict_status") == "confirmed"
            ),
            "warnings": warnings,
        }
        return result

    # ------------------------------------------------------------------ #
    # 重复 / 冲突候选
    # ------------------------------------------------------------------ #
    def find_duplicates(
        self,
        chunk_id: Optional[str] = None,
        *,
        threshold: Optional[float] = None,
        filters: Optional[ChunkFilter] = None,
        max_pairs: int = 200,
    ) -> List[Dict[str, Any]]:
        """查找重复知识：内容指纹完全相同，或向量相似度超过阈值。"""

        threshold = float(threshold if threshold is not None else self.retrieval.dedupe_similarity)
        filters = filters or ChunkFilter()
        if chunk_id:
            target = self.metadata.get_chunk(chunk_id)
            if not target:
                raise KnowledgeStoreError(f"知识片段不存在: {chunk_id}")
            filters = replace(filters, project_id=filters.project_id or target["project_id"])
            candidates = self._allowed_ids(filters)
            return self._similar_pairs_for(target, candidates, threshold, max_pairs)

        ids = self._allowed_ids(filters)
        if len(ids) < 2:
            return []
        rows = [self._pos[cid] for cid in ids if cid in self._pos]
        if len(rows) < 2:
            return []
        sub = self._matrix[rows]
        found: List[Dict[str, Any]] = []
        for start in range(0, len(rows), 256):
            block = sub[start : start + 256]
            sims = block @ sub.T
            for local_i in range(block.shape[0]):
                global_i = start + local_i
                for j in range(global_i + 1, len(rows)):
                    if len(found) >= max_pairs:
                        return found
                    sim = float(sims[local_i, j])
                    if sim >= threshold:
                        found.append(
                            {
                                "chunk_a": self._ids[rows[global_i]],
                                "chunk_b": self._ids[rows[j]],
                                "similarity": round(sim, 4),
                                "reason": "vector_similarity",
                            }
                        )
        return found

    def _similar_pairs_for(
        self,
        target: Mapping[str, Any],
        candidates: Sequence[str],
        threshold: float,
        max_pairs: int,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for cid in candidates:
            if cid == target["chunk_id"] or cid not in self._pos:
                continue
            sim = float(self._matrix[self._pos[cid]] @ self._matrix[self._pos[target["chunk_id"]]])
            other = self.metadata.get_chunk(cid)
            if not other:
                continue
            if other.get("content_hash") and other["content_hash"] == target.get("content_hash"):
                out.append(
                    {
                        "chunk_a": target["chunk_id"],
                        "chunk_b": cid,
                        "similarity": 1.0,
                        "reason": "content_hash",
                    }
                )
            elif sim >= threshold:
                out.append(
                    {
                        "chunk_a": target["chunk_id"],
                        "chunk_b": cid,
                        "similarity": round(sim, 4),
                        "reason": "vector_similarity",
                    }
                )
            if len(out) >= max_pairs:
                break
        return out

    def find_conflicts(
        self, chunk_id: Optional[str] = None, project_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """返回已记录冲突 + 相似但结论可能矛盾的候选。"""

        recorded = self.metadata.list_conflicts(project_id=project_id)
        if chunk_id:
            recorded = [c for c in recorded if chunk_id in (c["chunk_a"], c["chunk_b"])]
        candidates: List[Dict[str, Any]] = []
        if chunk_id:
            chunk = self.metadata.get_chunk(chunk_id)
            if chunk and chunk_id in self._pos:
                filters = ChunkFilter(project_id=chunk["project_id"])
                similar = self.find_duplicates(chunk_id, threshold=self.retrieval.conflict_similarity, filters=filters)
                candidates = [s for s in similar if s["similarity"] < self.retrieval.dedupe_similarity]
        return {"recorded": recorded, "candidates": candidates}

    # ------------------------------------------------------------------ #
    # 统计 / 完整性 / 备份
    # ------------------------------------------------------------------ #
    def stats(self) -> Dict[str, Any]:
        return {
            "chunks": self.metadata.count_chunks(),
            "vectors": len(self._ids),
            "dim": int(self._matrix.shape[1] if self._matrix.size else self.embedder.dim),
            "embedder": self.embedder.embedder_id,
            "partitions": self.metadata.partition_stats(),
            "index_error": self._last_error,
        }

    def check_integrity(self) -> Dict[str, Any]:
        problems: List[str] = []
        warnings: List[str] = []
        db_ids = set(self.metadata.list_chunk_ids())
        index_ids = set(self._ids)
        missing_vectors = sorted(db_ids - index_ids)
        orphans = sorted(index_ids - db_ids)
        if len(self._ids) != len(self._pos) or len(self._ids) != int(self._matrix.shape[0]):
            problems.append("索引 ids/位置映射/矩阵行数不一致")
        if self._matrix.size:
            if not np.isfinite(self._matrix).all():
                problems.append("索引中存在 NaN/Inf 向量")
            norms = np.linalg.norm(self._matrix, axis=1)
            if np.any(norms < 1e-6):
                warnings.append(f"{int((norms < 1e-6).sum())} 个零向量（空内容片段）")
        if orphans:
            problems.append(f"{len(orphans)} 个向量对应的知识片段已不存在（孤儿向量）")
        if missing_vectors:
            problems.append(
                f"{len(missing_vectors)} 个知识片段缺少向量（语义检索会漏召回，请重建索引）"
            )
        if self._last_error:
            problems.append(self._last_error)
        dim = int(self._matrix.shape[1] if self._matrix.size else self.embedder.dim)
        return {
            "ok": not problems,
            "problems": problems,
            "warnings": warnings,
            "chunks": len(db_ids),
            "vectors": len(self._ids),
            "dim": dim,
            "embedder": self.embedder.embedder_id,
            "missing_vectors": missing_vectors[:20],
            "orphans": orphans[:20],
        }

    def backup(self, dest_dir: str | Path, *, note: str = "") -> Dict[str, Any]:
        """备份数据库与向量索引（SQLite 在线备份 API，不中断服务）。"""

        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        db_target = dest / f"metadata-{stamp}.sqlite3"
        with self.metadata.transaction() as conn:
            target_conn = __import__("sqlite3").connect(str(db_target))
            try:
                conn.backup(target_conn)
            finally:
                target_conn.close()
        index_target = dest / f"index-{stamp}"
        index_target.mkdir(parents=True, exist_ok=True)
        for name in (MANIFEST, IDS, VECTORS):
            src = self.index_dir / name
            if src.exists():
                shutil.copy2(src, index_target / name)
        manifest = {
            "created_at": utcnow_iso(),
            "db": db_target.name,
            "index": index_target.name,
            "chunks": self.metadata.count_chunks(),
            "note": note,
            "embedder": self.embedder.embedder_id,
        }
        (dest / f"backup-{stamp}.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"backup_dir": str(dest), **manifest}

    def restore(self, db_file: str | Path, index_dir: str | Path | None = None) -> Dict[str, Any]:
        """从备份恢复；恢复前会把当前库另存为 .pre-restore 副本。"""

        db_file = Path(db_file)
        if not db_file.exists():
            raise KnowledgeStoreError(f"备份数据库不存在: {db_file}")
        safety = self.metadata.db_path.with_suffix(".pre-restore.sqlite3")
        with self.metadata.transaction() as conn:
            target = __import__("sqlite3").connect(str(safety))
            try:
                conn.backup(target)
            finally:
                target.close()
        self.metadata.close()
        shutil.copy2(db_file, self.metadata.db_path)
        for suffix in ("-wal", "-shm"):
            extra = Path(str(self.metadata.db_path) + suffix)
            if extra.exists():
                extra.unlink()
        self.metadata.connect()
        self.metadata.migrate()
        if index_dir:
            idx = Path(index_dir)
            for name in (MANIFEST, IDS, VECTORS):
                if (idx / name).exists():
                    shutil.copy2(idx / name, self.index_dir / name)
        self._ids, self._pos = [], {}
        self._matrix = np.zeros((0, self.embedder.dim), dtype=np.float32)
        self._last_error = ""
        self._load_index()
        report = self.check_integrity()
        return {"restored_from": str(db_file), "safety_copy": str(safety), "integrity": report}

    def export(self, path: str | Path, fmt: str = "jsonl", filters: Optional[ChunkFilter] = None) -> Dict[str, Any]:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        chunks = self.metadata.list_chunks(filters or ChunkFilter(), limit=1_000_000)
        fmt = fmt.lower()
        if fmt == "jsonl":
            with target.open("w", encoding="utf-8") as fh:
                for chunk in chunks:
                    fh.write(json.dumps(chunk, ensure_ascii=False) + "\n")
        elif fmt == "json":
            target.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
        elif fmt == "csv":
            import csv

            with target.open("w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(Chunk.__dataclass_fields__.keys()))
                writer.writeheader()
                for chunk in chunks:
                    writer.writerow({k: _csv_safe(v) for k, v in chunk.items() if k in writer.fieldnames})
        else:
            raise KnowledgeStoreError(f"不支持的导出格式: {fmt}（可选 jsonl/json/csv）")
        return {"path": str(target), "format": fmt, "count": len(chunks)}

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _remove_vectors(self, chunk_ids: Iterable[str]) -> None:
        drop = {cid for cid in chunk_ids if cid in self._pos}
        if not drop:
            return
        keep_rows = [i for i, cid in enumerate(self._ids) if cid not in drop]
        self._ids = [self._ids[i] for i in keep_rows]
        self._matrix = self._matrix[keep_rows] if keep_rows else np.zeros((0, self.embedder.dim), dtype=np.float32)
        self._pos = {cid: i for i, cid in enumerate(self._ids)}
        self._save_index()

    def _remove_document_vectors(self, document_id: str) -> None:
        ids = [
            r["chunk_id"]
            for r in self.metadata.query("SELECT chunk_id FROM chunks WHERE document_id=?", (document_id,))
        ]
        self._remove_vectors(ids)


# --------------------------------------------------------------------------- #
# 辅助
# --------------------------------------------------------------------------- #
def _index_text(chunk: Mapping[str, Any]) -> str:
    title = str(chunk.get("title") or "")
    summary = str(chunk.get("summary") or "")
    content = str(chunk.get("content") or "")
    # 标题权重更高：重复 2 次
    return f"{title}\n{title}\n{summary}\n{content}"


def _coerce_chunk(raw: Mapping[str, Any]) -> Dict[str, Any]:
    data: Dict[str, Any] = {k: raw.get(k) for k in Chunk.__dataclass_fields__.keys() if k in raw}
    for required in ("chunk_id", "project_id"):
        if not data.get(required):
            raise KnowledgeStoreError(f"知识片段缺少必填字段 {required}")
    defaults = Chunk(
        chunk_id=data["chunk_id"],
        project_id=data["project_id"],
        document_id=str(data.get("document_id") or ""),
    )
    merged = {**defaults.to_row(), **{k: v for k, v in data.items() if v is not None}}
    if not merged.get("content") and not merged.get("summary"):
        raise KnowledgeStoreError("知识片段必须有 content 或 summary")
    if not merged.get("content_hash"):
        merged["content_hash"] = stable_hash(normalize_text(merged.get("content", "")))
    if not merged.get("source_type"):
        merged["source_type"] = SourceType.UNKNOWN.value
    merged.setdefault("partition", "pending_knowledge")
    return merged


def _csv_safe(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    return value


__all__ = [
    "INDEX_VERSION",
    "KnowledgeStore",
    "KnowledgeStoreError",
    "MANIFEST",
    "VECTORS",
    "IDS",
]
