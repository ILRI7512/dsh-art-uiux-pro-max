"""安全机制测试：密钥拦截、权限确认、受限执行、审计脱敏。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dsh_autonomous_learning.core.orchestrator import build_runtime
from dsh_autonomous_learning.security.permissions import contains_secret
from dsh_autonomous_learning.tools import build_registry

from .conftest import make_chunk


@pytest.fixture()
def assisted_runtime(config):
    config.learning.default_mode = "assisted"
    rt = build_runtime(config, mode="assisted")
    try:
        yield rt
    finally:
        rt.close()


def test_secret_detection():
    assert contains_secret("我的 key 是 sk-abcdefghijklmnopqrstuvwx")
    assert contains_secret("Authorization: Bearer abcdefghijklmnopqrstuvwxyz")
    assert contains_secret("api_key = '1234567890abcdef'")
    assert not contains_secret("这是一段正常的业务说明，没有密钥。")


def test_secret_blocked_when_saving(assisted_runtime):
    reg, _, _ = build_registry(assisted_runtime)
    project = reg.call(
        "create_learning_project", {"goal": "测试密钥拦截", "domain": "programming"}
    )["data"]["project"]["project"]["project_id"]
    result = reg.call(
        "save_knowledge",
        {
            "project_id": project,
            "items": [{"content": "配置示例：api_key = sk-abcdefghijklmnopqrstuvwx 请勿泄露"}],
        },
    )
    assert result["success"] is False
    assert result["error"]["type"] in {"PermissionDenied", "ValueError"}
    assert "密钥" in result["error"]["message"] or "Permission" in result["error"]["type"]


def test_destructive_requires_confirmation(assisted_runtime):
    reg, _, _ = build_registry(assisted_runtime)
    make_chunk(assisted_runtime, chunk_id="c1", content="待失效的知识内容，用于权限测试。", project_id="prj_test")
    first = reg.call("invalidate_knowledge", {"chunk_id": "c1", "project_id": "prj_test", "reason": "test"})
    assert first["success"] is False
    assert first["error"]["type"] == "ConfirmationRequired"

    pending = assisted_runtime.permissions.pending_confirmations()
    assert pending
    token = pending[0]["token"]
    # 批准只能由用户侧进行：这里直接调用权限服务的 approve（等价于 CLI / 宿主审批）
    assert assisted_runtime.permissions.approve(token) is True

    second = reg.call(
        "invalidate_knowledge",
        {"chunk_id": "c1", "project_id": "prj_test", "reason": "test", "confirm_token": token},
    )
    assert second["success"] is True
    assert assisted_runtime.metadata.get_chunk("c1")["status"] in {"stale", "superseded"}


def test_agent_has_no_self_approval_tool(assisted_runtime):
    """审批是 user-only：智能体不能通过工具给自己授权。"""

    reg, _, _ = build_registry(assisted_runtime)
    names = set(reg.names())
    assert "approve_confirmation" not in names
    assert "request_confirmation" not in names


def test_confirmations_persist_across_processes(config):
    """待确认操作必须持久化：MCP 服务器重启后仍可被用户批准。"""

    from dsh_autonomous_learning.security.permissions import PermissionManager
    from dsh_autonomous_learning.storage.metadata_store import MetadataStore

    rt = build_runtime(config, mode="assisted")
    try:
        decision = rt.permissions.request_confirmation("invalidate_knowledge", "chunk_x", "prj_x")
        token = decision.token
        assert token
        # 新连接（模拟另一个进程/重启后的 MCP 服务器）
        other = MetadataStore(rt.config.paths.db_path)
        try:
            row = other.get_confirmation(token)
            assert row is not None and row["status"] == "pending"
            manager = PermissionManager(
                rt.config.security, rt.config.learning, other, mode="assisted", delegate_to_host=False
            )
            assert manager.approve(token) is True
            assert other.get_confirmation(token)["status"] == "approved"
        finally:
            other.close()
        # 原进程消费令牌
        assert rt.permissions.consume_token(token, "invalidate_knowledge", "chunk_x") is True
        assert rt.metadata.get_confirmation(token)["status"] == "consumed"
    finally:
        rt.close()


def test_host_delegation_skips_local_token(config):
    """开启 delegate_approval_to_host 后，确认交给 DSH 宿主审批 UI。"""

    config.security.delegate_approval_to_host = True
    config.learning.default_mode = "assisted"
    rt = build_runtime(config, mode="assisted")
    try:
        reg, _, _ = build_registry(rt)
        make_chunk(rt, chunk_id="c1", content="宿主审批测试用知识条目。", project_id="prj_test")
        result = reg.call(
            "invalidate_knowledge",
            {"chunk_id": "c1", "project_id": "prj_test", "reason": "host approval"},
        )
        assert result["success"] is True, result
        assert rt.metadata.get_chunk("c1")["status"] in {"stale", "superseded"}
        # 委派路径不产生本地待确认令牌
        assert rt.permissions.pending_confirmations() == []
        rows = rt.metadata.list_audit(limit=10)
        assert any("宿主审批" in (row["detail"].get("reason") or "") for row in rows)
    finally:
        rt.close()


def test_code_execution_denied_outside_lab(assisted_runtime):
    reg, _, _ = build_registry(assisted_runtime)
    result = reg.call("run_code_test", {"code": "print('hi')", "trusted": True})
    assert result["success"] is False
    # 非 lab 模式是硬拒绝（不是"确认后可执行"），避免模型误以为拿到令牌就能跑
    assert result["error"]["type"] == "PermissionDenied"
    assert "lab" in result["error"]["message"]


def test_lab_mode_allows_trusted_code(lab_runtime):
    reg, _, _ = build_registry(lab_runtime)
    result = reg.call("run_code_test", {"code": "print('ok')", "trusted": True})
    assert result["success"] is True, result
    assert result["data"]["ok"] is True
    assert result["data"]["stdout"].strip() == "ok"
    assert result["data"]["isolation"] == "process"
    assert "不是安全沙箱" in " ".join(result["data"]["warnings"])


def test_untrusted_dangerous_code_is_refused(lab_runtime):
    reg, _, _ = build_registry(lab_runtime)
    code = "import os\nos.system('echo hacked')"
    result = reg.call("run_code_test", {"code": code, "trusted": False})
    assert result["success"] is True  # 工具本身成功返回，但执行被拒绝
    assert result["data"]["ok"] is False
    assert "拒绝" in result["data"]["stderr"] or "拒绝" in " ".join(result["data"]["warnings"])


def test_read_outside_allowed_roots_is_denied(assisted_runtime, tmp_path: Path):
    outside = tmp_path / "outside.txt"
    outside.write_text("授权目录之外的文件内容。", encoding="utf-8")
    result = assisted_runtime.reader.read(str(outside))
    assert result.ok is False
    # 硬边界：不做"确认即放行"，明确告诉用户如何授权
    assert "allowed_roots" in result.error


def test_audit_log_redacts_secrets(assisted_runtime):
    assisted_runtime.permissions.audit.log(
        action="test_action",
        target="x",
        risk="write",
        allowed=True,
        detail={"api_key": "sk-abcdefghijklmnopqrstuvwx", "note": "普通说明"},
    )
    rows = assisted_runtime.metadata.list_audit(limit=5)
    assert rows
    assert rows[0]["detail"]["api_key"] == "<redacted>"
    assert rows[0]["detail"]["note"] == "普通说明"
