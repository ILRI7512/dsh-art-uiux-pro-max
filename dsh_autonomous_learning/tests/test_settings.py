"""设置卡（DSH 插件设置）与引擎的联动测试。

覆盖：
1. settings.json 覆盖静态 config.json；
2. 显式环境变量 / overrides 仍然优先；
3. 非法值被忽略，不影响启动；
4. 每轮开始前重读设置（模式/预算/任务上限即时生效）；
5. 数据目录变更只在下一次建连生效（运行中只报告 pending）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dsh_autonomous_learning.config import host_settings_file, load_config, read_host_settings


def _write(home: Path, payload: dict) -> Path:
    path = host_settings_file(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_settings_override_static_config(home: Path):
    (home / "config.json").write_text(
        json.dumps({"learning": {"default_mode": "auto", "daily_budget_usd": 5}}), encoding="utf-8"
    )
    _write(home, {"mode": "lab", "dailyBudgetUsd": 2.5, "maxTasksPerRun": 7})
    cfg = load_config(home=home)
    assert cfg.learning.default_mode == "lab"
    assert cfg.learning.daily_budget_usd == 2.5
    assert cfg.learning.max_tasks_per_run == 7


def test_env_and_overrides_win_over_settings(home: Path, monkeypatch):
    _write(home, {"mode": "lab"})
    monkeypatch.setenv("DSH_AL_MODE", "assisted")
    cfg = load_config(home=home, overrides={"learning": {"default_mode": "auto"}})
    assert cfg.learning.default_mode == "auto"


def test_settings_data_dir_is_applied(home: Path):
    custom = home / "custom-data"
    _write(home, {"dataDir": str(custom)})
    cfg = load_config(home=home)
    assert Path(cfg.paths.data_dir) == custom.resolve()
    assert Path(cfg.paths.db_path).parent == custom.resolve()


def test_invalid_settings_are_ignored(home: Path):
    _write(
        home,
        {"mode": "yolo", "dailyBudgetUsd": -3, "maxTasksPerRun": 9999, "dataDir": "relative/path"},
    )
    cfg = load_config(home=home)
    assert cfg.learning.default_mode == "assisted"
    assert cfg.learning.daily_budget_usd == 1.0
    assert cfg.learning.max_tasks_per_run == 30
    assert Path(cfg.paths.data_dir) != Path("relative/path")


def test_runtime_applies_settings_live(runtime, orchestrator, home: Path):
    _write(home, {"mode": "lab", "dailyBudgetUsd": 3.5, "maxTasksPerRun": 11})
    applied = runtime.apply_settings()
    assert applied["mode"] == "lab"
    assert applied["daily_budget_usd"] == 3.5
    assert applied["max_tasks_per_run"] == 11
    assert runtime.permissions.mode == "lab"
    assert runtime.policy.mode == "lab"

    # 下一轮 run_round 会把同样的值带上
    project_id = orchestrator.create_project(goal="设置联动测试", domain="general")["project"]["project_id"]
    result = orchestrator.run_round(project_id, max_tasks=1)
    assert result["settings"]["mode"] == "lab"
    assert result["settings"]["daily_budget_usd"] == 3.5


def test_data_dir_change_reports_pending(runtime, home: Path):
    other = home / "moved-data"
    _write(home, {"dataDir": str(other)})
    applied = runtime.apply_settings()
    assert applied.get("data_dir_pending") == str(other)
    # 运行中的 DB 不会被偷偷搬走
    assert Path(runtime.config.paths.data_dir) != other


def test_read_host_settings_missing_file(home: Path):
    assert read_host_settings(home) == {}


def test_settings_file_env_override(home: Path, monkeypatch, tmp_path: Path):
    custom = tmp_path / "custom-settings.json"
    custom.write_text(json.dumps({"mode": "auto"}), encoding="utf-8")
    monkeypatch.setenv("DSH_AL_SETTINGS_FILE", str(custom))
    cfg = load_config(home=home)
    assert cfg.learning.default_mode == "auto"
