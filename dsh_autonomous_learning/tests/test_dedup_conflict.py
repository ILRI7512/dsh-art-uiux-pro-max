"""重复检测与冲突检测测试（关键：相似 ≠ 重复，矛盾不得被合并）。"""

from __future__ import annotations

from dsh_autonomous_learning.knowledge.conflict_detector import ConflictDetector
from dsh_autonomous_learning.storage.metadata_store import ChunkFilter

from .conftest import make_chunk


def test_exact_duplicate_detected(runtime):
    text = "滑点是指成交价与预期价的差额，回测必须计入滑点。"
    make_chunk(runtime, chunk_id="c1", content=text)
    make_chunk(runtime, chunk_id="c2", content=text)
    report = runtime.dedup.find_and_record(chunk_id="c1")
    assert report["exact_duplicates"]
    assert report["recorded"] >= 1
    assert runtime.metadata.list_duplicates("prj_test")


def test_near_duplicate_detected(runtime):
    base = "滑点是指成交价与预期价的差额，回测必须计入滑点成本，否则收益会被高估。"
    make_chunk(runtime, chunk_id="c1", content=base)
    make_chunk(runtime, chunk_id="c2", content=base + "另外还要考虑手续费。")
    report = runtime.dedup.find_and_record(chunk_id="c1", threshold=0.75)
    assert report["near_duplicates"] or report["exact_duplicates"]


def test_numeric_contradiction_is_conflict_not_duplicate(runtime):
    a = "该策略在回测中的夏普比率为 1.80，数据区间为 2019 至 2023 年。"
    b = "该策略在回测中的夏普比率为 0.90，数据区间为 2019 至 2023 年。"
    make_chunk(runtime, chunk_id="c1", content=a, topic="夏普比率")
    make_chunk(runtime, chunk_id="c2", content=b, topic="夏普比率")

    dup = runtime.dedup.find_and_record(chunk_id="c1", threshold=0.8)
    assert dup["recorded"] == 0, "结论矛盾的片段不能登记为重复"

    result = runtime.conflicts.detect_for("c1")
    assert result["findings"], result
    assert result["recorded"] >= 1
    conflicts = runtime.metadata.list_conflicts("prj_test")
    assert conflicts
    # 双方都保留，均未被删除或合并
    assert runtime.metadata.get_chunk("c1") and runtime.metadata.get_chunk("c2")
    assert {conflicts[0]["chunk_a"], conflicts[0]["chunk_b"]} == {"c1", "c2"}


def test_polarity_contradiction(runtime):
    make_chunk(runtime, chunk_id="c1", content="该策略支持做空，在下跌行情中可以获得收益。", topic="做空")
    make_chunk(runtime, chunk_id="c2", content="该策略不支持做空，只能单边做多。", topic="做空")
    detector = ConflictDetector(runtime.store, runtime.metadata)
    findings = detector.detect_pair(
        runtime.metadata.get_chunk("c1"), runtime.metadata.get_chunk("c2")
    )
    assert findings
    assert any(f.kind in {"polarity", "negation"} for f in findings)


def test_conflict_resolution_marks_both(runtime):
    make_chunk(runtime, chunk_id="c1", content="对比度要求是 4.5:1。", topic="对比度")
    make_chunk(runtime, chunk_id="c2", content="对比度要求是 3.0:1。", topic="对比度")
    runtime.conflicts.detect_for("c1")
    conflicts = runtime.metadata.list_conflicts("prj_test")
    assert conflicts
    runtime.conflicts.resolve(conflicts[0]["conflict_id"], "以官方 WCAG 文档为准", status="resolved")
    updated = runtime.metadata.get("conflicts", conflicts[0]["conflict_id"])
    assert updated["status"] == "resolved"
    assert updated["resolution"]


def test_duplicates_not_auto_deleted(runtime):
    text = "完全相同的知识内容，用于验证重复检测不会自动删除。"
    make_chunk(runtime, chunk_id="c1", content=text)
    make_chunk(runtime, chunk_id="c2", content=text)
    report = runtime.dedup.find_and_record(chunk_id="c1")
    assert report["recorded"] >= 1
    assert runtime.metadata.get_chunk("c1") is not None
    assert runtime.metadata.get_chunk("c2") is not None
    assert runtime.metadata.count_chunks(ChunkFilter(project_id="prj_test")) == 2
