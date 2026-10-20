"""预算、停止条件、重试、恢复与调度测试（规则 6）。"""

from __future__ import annotations

import pytest

from dsh_autonomous_learning.config import load_config
from dsh_autonomous_learning.core.budget import BudgetExceeded, BudgetTracker
from dsh_autonomous_learning.core.orchestrator import build_runtime
from dsh_autonomous_learning.tools import build_registry


def test_budget_limits_tasks_per_run(config, corpus):
    config.learning.max_tasks_per_run = 1
    rt = build_runtime(config)
    try:
        reg, orch, _ = build_registry(rt)
        project_id = orch.create_project(
            goal="学习量化回测", domain="quant", allowed_sources=[str(corpus / "quant_basics.md")]
        )["project"]["project_id"]
        orch.plan(project_id)
        result = orch.run_round(project_id)
        assert len(result["tasks_executed"]) == 1
        assert result["stop_reason"] == "max_tasks_per_run"
        assert result["budget"]["tasks_run"] == 1
    finally:
        rt.close()


def test_budget_tracker_counts_no_progress(config):
    tracker = BudgetTracker(config.learning, config.model)
    tracker.start_task()
    tracker.finish_task(0, progress=False)
    tracker.start_task()
    tracker.finish_task(0, progress=False)
    tracker.start_task()
    tracker.finish_task(0, progress=False)
    # 按任务计数只做记录，真正的停止判定在"轮"层面
    assert tracker.state.no_progress_rounds >= 3
    assert tracker.snapshot()["new_knowledge"] == 0


def test_round_level_no_progress_stops(runtime, orchestrator):
    project_id = orchestrator.create_project(goal="无进展停止测试", domain="general")["project"]["project_id"]
    orchestrator.plan(project_id)
    from dsh_autonomous_learning.core.models import new_id, utcnow_iso

    for _ in range(3):
        run_id = new_id("run")
        runtime.metadata.start_run(
            {
                "run_id": run_id,
                "project_id": project_id,
                "iteration": runtime.metadata.next_iteration(project_id),
                "status": "completed",
                "summary": {"new_knowledge": 0},
                "stop_reason": "",
                "started_at": utcnow_iso(),
                "finished_at": utcnow_iso(),
            }
        )
    assert orchestrator._rounds_without_progress(project_id) >= 3  # noqa: SLF001
    result = orchestrator.run_round(project_id, max_tasks=2)
    assert result["stop_reason"] == "no_progress"
    assert result["continue_recommended"] is False


def test_budget_tracker_daily_spend(config):
    tracker = BudgetTracker(config.learning, config.model, daily_spent=999.0)
    should_stop, reason = tracker.should_stop()
    assert should_stop
    assert reason == "daily_budget"


def test_retry_failed_task_tool(runtime, registry, orchestrator):
    project_id = orchestrator.create_project(goal="重试测试", domain="general")["project"]["project_id"]
    orchestrator.plan(project_id)
    tasks = runtime.metadata.list_tasks(project_id)
    victim = tasks[0]["task_id"]
    runtime.metadata.update_task(victim, {"status": "failed", "error": "boom", "attempts": 3})
    result = registry.call("retry_failed_task", {"project_id": project_id, "task_id": victim})
    assert result["success"] is True
    assert victim in result["data"]["retried"]
    assert runtime.metadata.get_task(victim)["status"] == "pending"
    assert runtime.metadata.get_task(victim)["attempts"] == 0


def test_task_failure_marks_retrying(runtime, orchestrator):
    project_id = orchestrator.create_project(goal="失败重试测试", domain="general")["project"]["project_id"]
    orchestrator.plan(project_id)
    task = runtime.metadata.list_tasks(project_id)[0]
    orchestrator._handle_task_failure(task, RuntimeError("模拟失败"))  # noqa: SLF001
    updated = runtime.metadata.get_task(task["task_id"])
    assert updated["status"] == "retrying"
    assert "模拟失败" in updated["error"]


def test_scheduler_tick_runs_due_project(runtime, orchestrator):
    _, _, scheduler = build_registry(runtime)
    project_id = orchestrator.create_project(goal="定时学习测试", domain="general")["project"]["project_id"]
    orchestrator.plan(project_id)
    scheduler.schedule(project_id, next_run_at="2020-01-01T00:00:00Z")
    result = scheduler.tick(max_projects=1, max_tasks_per_project=1)
    assert result["due"] >= 1
    assert result["executed"]
    assert result["executed"][0]["status"] == "ok"
    # 一次性任务执行后自动关闭
    schedules = runtime.metadata.list_schedules()
    once = [s for s in schedules if s["project_id"] == project_id][0]
    assert once["enabled"] is False


def test_run_refuses_paused_project(runtime, orchestrator):
    project_id = orchestrator.create_project(goal="暂停后不应运行", domain="general")["project"]["project_id"]
    orchestrator.set_status(project_id, "paused")
    result = orchestrator.run_round(project_id)
    assert result["started"] is False
