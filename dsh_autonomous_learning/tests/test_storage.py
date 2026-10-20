"""存储层测试：元数据、词元索引、向量索引、备份恢复、完整性。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dsh_autonomous_learning.storage.metadata_store import ChunkFilter, StorageError
from dsh_autonomous_learning.storage.tokenizer import bm25_scores, tokenize

from .conftest import make_chunk


def test_tokenizer_handles_chinese_and_code_terms():
    tokens = tokenize("滑点与 Sharp Ratio，node.js 与 C++ 都是术语")
    assert "滑点" in tokens
    assert "node.js" in tokens
    assert "c++" in tokens


def test_bm25_python_reference():
    docs = {"a": {"滑点": 2, "成本": 1}, "b": {"滑点": 1, "成本": 1}, "c": {"无关": 3}}
    lengths = {"a": 3, "b": 2, "c": 3}
    scores = bm25_scores(["滑点"], docs, lengths, total_docs=3, avg_length=2.7)
    assert scores["a"] > scores["b"] > 0
    assert "c" not in scores


def test_chunk_roundtrip(runtime):
    payload = make_chunk(
        runtime,
        chunk_id="chunk_t1",
        content="滑点是指订单实际成交价与预期价格的差额，高频策略对滑点非常敏感。",
        topic="滑点",
    )
    stored = runtime.metadata.get_chunk(payload["chunk_id"])
    assert stored is not None
    assert stored["content_hash"]
    details = runtime.store.get_by_id(payload["chunk_id"])
    assert details["has_vector"] is True
    assert details["verification_records"] == []


def test_bm25_sql_search_hits(runtime):
    make_chunk(runtime, chunk_id="chunk_t1", content="滑点是指成交价与预期价的差额。", topic="滑点")
    make_chunk(runtime, chunk_id="chunk_t2", content="颜色对比度应不低于 4.5:1。", topic="无障碍")
    hits = runtime.metadata.bm25_search("滑点", top_k=5)
    assert hits
    assert hits[0][0] == "chunk_t1"


def test_partition_stats(runtime):
    make_chunk(runtime, chunk_id="c1", content="滑点会显著影响收益。", partition="quant_knowledge", domain="quant")
    make_chunk(runtime, chunk_id="c2", content="另一种说法。", partition="pending_knowledge", domain="quant")
    stats = {row["partition"]: row for row in runtime.metadata.partition_stats()}
    assert stats["quant_knowledge"]["total"] == 1
    assert stats["pending_knowledge"]["total"] == 1


def test_export_formats(runtime, tmp_path: Path):
    make_chunk(runtime, chunk_id="c1", content="滑点会显著影响收益。")
    jsonl = tmp_path / "out.jsonl"
    result = runtime.store.export(jsonl, fmt="jsonl")
    assert result["count"] == 1
    assert jsonl.read_text(encoding="utf-8").strip()
    with pytest.raises(Exception):
        runtime.store.export(tmp_path / "x.doc", fmt="doc")


def test_backup_and_restore(runtime, tmp_path: Path):
    make_chunk(runtime, chunk_id="c1", content="备份前的知识：滑点影响收益。")
    backup = runtime.store.backup(tmp_path / "backups", note="test")
    db_file = tmp_path / "backups" / backup["db"]
    index_dir = tmp_path / "backups" / backup["index"]
    assert db_file.exists() and index_dir.exists()

    make_chunk(runtime, chunk_id="c2", content="备份之后新增的知识，应当被恢复操作丢弃。")
    assert runtime.metadata.count_chunks() == 2

    restored = runtime.store.restore(db_file, index_dir=index_dir)
    assert restored["integrity"]["ok"] is True
    assert runtime.metadata.count_chunks() == 1
    assert runtime.metadata.get_chunk("c1") is not None


def test_integrity_detects_missing_vectors(runtime):
    make_chunk(runtime, chunk_id="c1", content="索引一致性检查用的知识条目。")
    report = runtime.store.check_integrity()
    assert report["ok"] is True
    # 人为制造孤儿向量前，先确认基线正常
    runtime.store._remove_vectors(["c1"])  # noqa: SLF001 - 测试需要
    report = runtime.store.check_integrity()
    assert report["ok"] is False
    assert report["missing_vectors"]


def test_unknown_column_rejected(runtime):
    with pytest.raises(StorageError):
        runtime.metadata.insert("chunks", {"chunk_id": "x", "project_id": "p", "bogus": 1})
