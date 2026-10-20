"""端到端学习流程测试：目标 → 规划 → 发现 → 提取 → 核验 → 评估 → 报告。"""

from __future__ import annotations

import json
from pathlib import Path

from dsh_autonomous_learning.storage.metadata_store import ChunkFilter


def test_end_to_end_learning_round(corpus, runtime, orchestrator):
    doc = corpus / "quant_basics.md"
    created = orchestrator.create_project(
        goal="学习外汇量化交易基础，区分理论结论与待验证假设",
        domain="quant",
        depth="overview",
        allowed_sources=[str(doc)],
    )
    project_id = created["project"]["project_id"]
    assert created["project"]["goal"]
    assert "pending_knowledge" in created["project"]["partitions"]

    plan = orchestrator.plan(project_id)
    assert plan["task_count"] >= 10
    kinds = {t["kind"] for t in plan["tasks"]}
    assert {"plan", "discover", "extract", "verify", "practice", "evaluate", "report"} & kinds

    result = orchestrator.run_round(project_id, max_tasks=12)
    assert result["tasks_executed"], result
    assert result["new_knowledge"] > 0, result

    chunks = runtime.metadata.count_chunks(ChunkFilter(project_id=project_id))
    assert chunks > 0

    with_source = runtime.metadata.scalar(
        "SELECT COUNT(*) FROM chunks WHERE project_id=? AND source_id<>''", (project_id,), 0
    )
    assert with_source == chunks, "每条知识都必须有来源"

    # 任何 verified 都必须有可追溯的通过证据；没有证据的一律不得 verified
    verified_rows = runtime.metadata.query_dicts(
        "SELECT chunk_id FROM chunks WHERE project_id=? AND verification_status='verified'", (project_id,)
    )
    for row in verified_rows:
        records = runtime.metadata.list_verifications(row["chunk_id"])
        assert any(r["result"] == "pass" and r["evidence"] for r in records), row
    # 默认落地区是待审分区
    pending = runtime.metadata.count_chunks(
        ChunkFilter(project_id=project_id, partitions=["pending_knowledge"])
    )
    assert pending > 0, "新提取的知识应默认进入 pending_knowledge"

    evaluation = runtime.evaluator.evaluate(project_id)
    assert evaluation["metrics"]["chunks_total"] == chunks
    assert "coverage_rate" in evaluation["metrics"]
    assert evaluation["goal_met"] is False or evaluation["conclusion"]

    report = runtime.reporter.generate(project_id, evaluation=evaluation)
    assert Path(report["report_path"]).exists()
    assert Path(report["json_path"]).exists()
    markdown = Path(report["report_path"]).read_text(encoding="utf-8")
    assert "学习报告" in markdown
    assert "未核验" in markdown or "已核验" in markdown
    assert "后续建议" in markdown


def test_resume_after_interruption(corpus, runtime, orchestrator):
    doc = corpus / "quant_basics.md"
    project_id = orchestrator.create_project(
        goal="学习量化回测", domain="quant", allowed_sources=[str(doc)]
    )["project"]["project_id"]
    orchestrator.plan(project_id)
    first = orchestrator.run_round(project_id, max_tasks=3)
    assert first["tasks_executed"]

    # 模拟崩溃：把一个任务标为 running 且开始时间很早
    pending = runtime.metadata.list_tasks(project_id, status=["pending"])
    assert pending
    victim = pending[0]["task_id"]
    runtime.metadata.update_task(victim, {"status": "running", "started_at": "2020-01-01T00:00:00Z"})

    recovered = orchestrator.recover(project_id)
    assert recovered["count"] >= 1
    assert runtime.metadata.get_task(victim)["status"] in {"retrying", "failed"}

    second = orchestrator.run_round(project_id, max_tasks=3)
    assert second["run_id"] != first["run_id"]


def test_gap_analysis_creates_gaps(corpus, runtime, orchestrator):
    project_id = orchestrator.create_project(
        goal="学习 UI/UX 设计原则", domain="uiux", allowed_sources=[str(corpus / "uiux_basics.md")]
    )["project"]["project_id"]
    orchestrator.plan(project_id)
    analysis = runtime.gaps.analyze(project_id)
    assert analysis["coverage"]
    assert all(item["level"] for item in analysis["coverage"])
    assert analysis["gaps"], "空知识库应当产生缺口"
    assert runtime.metadata.list_gaps(project_id, status="open")
