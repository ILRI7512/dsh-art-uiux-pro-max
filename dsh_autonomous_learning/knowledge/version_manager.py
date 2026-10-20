"""知识版本管理。

规则：
- 内容变化必须留旧版本快照（不改历史）；
- 版本更新会重置核验状态（旧证据对新内容不再适用）——由
  ``KnowledgeStore.update_document`` 强制保证；
- 新版本替代旧版本时，旧条目置为 superseded 并建立 supersedes 关系；
- 支持回滚到任意历史版本（回滚本身也产生一条新版本）。
"""

from __future__ import annotations

import difflib
from typing import Any, Dict, List, Optional

from ..core.models import KnowledgeStatus, RelationType, new_id, utcnow_iso
from ..storage.metadata_store import MetadataStore
from ..storage.vector_store import KnowledgeStore, KnowledgeStoreError


class VersionManager:
    def __init__(self, store: KnowledgeStore, metadata: MetadataStore) -> None:
        self.store = store
        self.metadata = metadata

    # ------------------------------------------------------------------ #
    def update(
        self,
        chunk_id: str,
        *,
        content: Optional[str] = None,
        fields: Optional[Dict[str, Any]] = None,
        reason: str = "manual_update",
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = dict(fields or {})
        if content is not None:
            payload["content"] = content
        if not payload:
            raise ValueError("没有需要更新的字段")
        before = self.metadata.get_chunk(chunk_id)
        if not before:
            raise KnowledgeStoreError(f"知识片段不存在: {chunk_id}")
        result = self.store.update_document(chunk_id, payload, reason=reason)
        result["previous_version"] = before.get("version", 1)
        result["reset_verification"] = content is not None
        return result

    def supersede(self, old_id: str, new_id_: str, reason: str = "new_version") -> Dict[str, Any]:
        old = self.metadata.get_chunk(old_id)
        new = self.metadata.get_chunk(new_id_)
        if not old or not new:
            raise KnowledgeStoreError("新旧知识片段必须都存在")
        self.store.invalidate_document(old_id, reason=reason, superseded_by=new_id_)
        self.metadata.add_edge(
            {
                "edge_id": new_id("edge"),
                "src_id": new_id_,
                "dst_id": old_id,
                "relation": RelationType.SUPERSEDES.value,
                "weight": 1.0,
                "metadata": {"reason": reason},
                "created_at": utcnow_iso(),
            }
        )
        return {
            "old": old_id,
            "new": new_id_,
            "old_status": KnowledgeStatus.SUPERSEDED.value,
            "reason": reason,
        }

    # ------------------------------------------------------------------ #
    def history(self, chunk_id: str) -> Dict[str, Any]:
        chunk = self.metadata.get_chunk(chunk_id)
        if not chunk:
            raise KnowledgeStoreError(f"知识片段不存在: {chunk_id}")
        versions = self.metadata.list_versions(chunk_id)
        return {
            "chunk_id": chunk_id,
            "current_version": chunk.get("version", 1),
            "status": chunk.get("status"),
            "versions": [
                {
                    "version": v["version"],
                    "changed_at": v["changed_at"],
                    "change_reason": v["change_reason"],
                    "status": v["status"],
                    "char_count": len(v["content"] or ""),
                }
                for v in versions
            ],
            "superseded_by": chunk.get("superseded_by", ""),
        }

    def diff(self, chunk_id: str, from_version: int, to_version: Optional[int] = None) -> Dict[str, Any]:
        versions = {v["version"]: v for v in self.metadata.list_versions(chunk_id)}
        chunk = self.metadata.get_chunk(chunk_id)
        if not chunk:
            raise KnowledgeStoreError(f"知识片段不存在: {chunk_id}")
        current_version = int(chunk.get("version", 1))
        to_version = int(to_version or current_version)
        old = versions.get(from_version)
        if not old:
            raise ValueError(f"历史版本不存在: {from_version}")
        new_text = chunk["content"] if to_version == current_version else (versions.get(to_version) or {}).get("content", "")
        diff_lines = list(
            difflib.unified_diff(
                (old["content"] or "").splitlines(),
                (new_text or "").splitlines(),
                fromfile=f"v{from_version}",
                tofile=f"v{to_version}",
                lineterm="",
            )
        )
        return {
            "chunk_id": chunk_id,
            "from_version": from_version,
            "to_version": to_version,
            "diff": diff_lines[:400],
            "changed": bool(diff_lines),
        }

    def rollback(self, chunk_id: str, version: int, reason: str = "rollback") -> Dict[str, Any]:
        versions = {v["version"]: v for v in self.metadata.list_versions(chunk_id)}
        target = versions.get(int(version))
        if not target:
            raise ValueError(f"历史版本不存在: {version}")
        result = self.update(
            chunk_id,
            content=target["content"],
            reason=f"{reason}:restore_v{version}",
        )
        result["restored_from"] = int(version)
        return result


__all__ = ["VersionManager"]
