"""宿主审批委派（DSH 审批 UI）的判定测试。

覆盖三条安全边界：
1. 环境变量 + 闸门已安装 + 无心跳（旧代闸门）→ 委派；
2. 心跳过期（闸门曾运行后停止）→ fail-closed，退回本地确认；
3. 闸门没装在 profile 里 → 不委派。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from dsh_autonomous_learning.security.permissions import PermissionManager

PLUGIN = "@local/dsh-autolearn-approval"


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "package.json").write_text(
        json.dumps({"dsh": {"profile": {"bundles": [PLUGIN]}}}), encoding="utf-8"
    )
    return profile


def _manager(config, tmp_path: Path) -> PermissionManager:
    return PermissionManager(
        config.security,
        config.learning,
        None,
        mode="assisted",
        data_dir=str(tmp_path / "data"),
    )


def test_delegates_when_gate_installed_without_heartbeat(config, tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_PROFILE_DIR", str(_profile(tmp_path)))
    monkeypatch.setenv("DSH_AL_HOST_APPROVAL", "1")
    monkeypatch.delenv("DSH_AL_HOST_APPROVAL_FILE", raising=False)
    manager = _manager(config, tmp_path)
    assert manager.delegate_to_host is True


def _gate_state(tmp_path: Path, generation: int = 2) -> Path:
    path = tmp_path / "data" / "host_approval.gate.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"generation": generation}), encoding="utf-8")
    return path


def test_fails_closed_on_stale_heartbeat(config, tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_PROFILE_DIR", str(_profile(tmp_path)))
    monkeypatch.setenv("DSH_AL_HOST_APPROVAL", "1")
    _gate_state(tmp_path, 2)
    heartbeat = tmp_path / "data" / "host_approval.heartbeat"
    heartbeat.write_text(json.dumps({"ts": int((time.time() - 600) * 1000)}), encoding="utf-8")
    manager = _manager(config, tmp_path)
    assert manager.delegate_to_host is False
    assert manager._host_heartbeat_stale() is True  # noqa: SLF001


def test_gate_upgraded_but_not_running_fails_closed(config, tmp_path, monkeypatch):
    """闸门升级过（代际 2）后心跳缺失 = 被禁用/崩溃，必须退回本地确认。"""

    monkeypatch.setenv("DSH_PROFILE_DIR", str(_profile(tmp_path)))
    monkeypatch.setenv("DSH_AL_HOST_APPROVAL", "1")
    _gate_state(tmp_path, 2)
    manager = _manager(config, tmp_path)
    assert manager.delegate_to_host is False
    assert manager._gate_generation() == 2  # noqa: SLF001


def test_fresh_heartbeat_keeps_delegation(config, tmp_path, monkeypatch):
    heartbeat = tmp_path / "data" / "host_approval.heartbeat"
    heartbeat.parent.mkdir(parents=True, exist_ok=True)
    heartbeat.write_text(json.dumps({"ts": int(time.time() * 1000)}), encoding="utf-8")
    _gate_state(tmp_path, 2)
    monkeypatch.setenv("DSH_PROFILE_DIR", str(_profile(tmp_path)))
    monkeypatch.setenv("DSH_AL_HOST_APPROVAL", "1")
    manager = _manager(config, tmp_path)
    assert manager.delegate_to_host is True
    assert manager._host_heartbeat_fresh() is True  # noqa: SLF001


def test_no_gate_installed_means_local_flow(config, tmp_path, monkeypatch):
    profile = tmp_path / "profile-empty"
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "package.json").write_text(json.dumps({"dsh": {"profile": {"bundles": []}}}), encoding="utf-8")
    monkeypatch.setenv("DSH_PROFILE_DIR", str(profile))
    monkeypatch.setenv("DSH_AL_HOST_APPROVAL", "1")
    manager = _manager(config, tmp_path)
    assert manager.delegate_to_host is False


def test_disabled_in_profile_patch_fails_closed(config, tmp_path, monkeypatch):
    profile = _profile(tmp_path)
    (profile / "cordis.patch.yml").write_text(
        "- id: autolearn-approval\n  disabled: true\n", encoding="utf-8"
    )
    monkeypatch.setenv("DSH_PROFILE_DIR", str(profile))
    monkeypatch.setenv("DSH_AL_HOST_APPROVAL", "1")
    manager = _manager(config, tmp_path)
    assert manager.delegate_to_host is False


def test_explicit_config_delegation_wins(config, tmp_path, monkeypatch):
    monkeypatch.delenv("DSH_AL_HOST_APPROVAL", raising=False)
    config.security.delegate_approval_to_host = True
    manager = _manager(config, tmp_path)
    assert manager.delegate_to_host is True
