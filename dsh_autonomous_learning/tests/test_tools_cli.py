"""工具契约测试与 CLI 冒烟测试。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dsh_autonomous_learning.storage.metadata_store import ChunkFilter

from .conftest import make_chunk

EXPECTED_TOOLS = {
    # 1 项目管理
    "create_learning_project",
    "get_learning_project",
    "list_learning_projects",
    "pause_learning_project",
    "resume_learning_project",
    "cancel_learning_project",
    "get_learning_progress",
    # 2 规划
    "plan_learning_path",
    "decompose_learning_goal",
    "analyze_knowledge_gaps",
    "generate_learning_tasks",
    "prioritize_learning_tasks",
    # 3 资料
    "discover_sources",
    "search_sources",
    "read_source",
    "parse_document",
    "extract_code_examples",
    "get_source_metadata",
    "check_source_freshness",
    "check_source_license",
    # 4 提取
    "extract_knowledge",
    "classify_knowledge",
    "summarize_knowledge",
    "extract_formulas",
    "extract_concepts",
    "identify_assumptions",
    "identify_uncertainties",
    "compare_sources",
    "detect_conflicts",
    # 5 知识库
    "save_knowledge",
    "search_knowledge",
    "search_knowledge_by_keyword",
    "update_knowledge",
    "invalidate_knowledge",
    "find_duplicate_knowledge",
    "get_knowledge_details",
    "get_knowledge_sources",
    "get_knowledge_relations",
    "export_knowledge",
    "backup_knowledge_base",
    "restore_knowledge_base",
    # 6 核验实践
    "verify_knowledge",
    "verify_formula",
    "run_code_test",
    "run_learning_experiment",
    "create_practice_task",
    "evaluate_practice_result",
    "record_experiment_result",
    # 7 评估迭代
    "evaluate_learning",
    "generate_learning_report",
    "recommend_next_tasks",
    "schedule_learning_task",
    "retry_failed_task",
    "get_learning_metrics",
    "audit_knowledge_base",
}


def test_all_required_tools_registered(registry):
    names = set(registry.names())
    missing = EXPECTED_TOOLS - names
    assert not missing, f"缺少工具: {sorted(missing)}"
    assert len(names) >= 55


def test_tool_specs_have_required_fields(registry):
    for spec in registry.list_specs():
        assert spec["name"] and spec["description"]
        assert isinstance(spec["input_schema"], dict)
        assert spec["input_schema"].get("type") == "object"
        assert spec["risk"] in {"read", "write", "execute", "external", "destructive"}


def test_argument_validation(registry):
    result = registry.call("search_knowledge", {})
    assert result["success"] is False
    assert result["error"]["type"] == "ValidationError"
    assert "query" in result["error"]["message"]

    result = registry.call("search_knowledge", {"query": "x", "top_k": 0})
    assert result["success"] is False
    assert "top_k" in result["error"]["message"]


def test_unknown_tool(registry):
    result = registry.call("no_such_tool", {})
    assert result["success"] is False
    assert result["error"]["type"] == "UnknownTool"


def test_project_and_search_tools(runtime, registry):
    created = registry.call(
        "create_learning_project",
        {"goal": "学习量化交易基础", "domain": "quant", "plan": True},
    )
    assert created["success"] is True, created
    project_id = created["data"]["project"]["project"]["project_id"]
    assert created["data"]["plan"]["task_count"] > 0

    make_chunk(runtime, chunk_id="c1", content="滑点是指成交价与预期价的差额。", project_id=project_id)
    found = registry.call("search_knowledge", {"query": "滑点", "project_id": project_id})
    assert found["success"] is True
    assert found["data"]["results"]
    assert found["data"]["results"][0]["chunk_id"] == "c1"

    details = registry.call("get_knowledge_details", {"chunk_id": "c1"})
    assert details["success"] is True
    assert details["data"]["source_url"]
    assert details["data"]["has_vector"] is True

    audit = registry.call("audit_knowledge_base", {"project_id": project_id})
    assert audit["success"] is True
    assert audit["data"]["index_integrity"]["ok"] is True


def test_save_and_verify_via_tools(runtime, registry):
    project_id = registry.call(
        "create_learning_project", {"goal": "工具链测试", "domain": "programming", "plan": False}
    )["data"]["project"]["project"]["project_id"]
    saved = registry.call(
        "save_knowledge",
        {
            "project_id": project_id,
            "items": [
                {
                    "title": "Python GIL",
                    "content": "CPython 的 GIL 使同一时刻只有一个线程执行字节码，因此 CPU 密集任务应使用多进程。",
                    "knowledge_type": "fact",
                    "source_url": "https://docs.python.org/3/glossary.html",
                    "source_type": "official_doc",
                }
            ],
        },
    )
    assert saved["success"] is True, saved
    chunk_id = saved["data"]["chunks"][0]
    verified = registry.call(
        "verify_knowledge",
        {
            "chunk_id": chunk_id,
            "method": "official_doc_check",
            "evidence": [{"kind": "source", "source_id": "docs.python.org", "url": "https://docs.python.org/3/glossary.html"}],
        },
    )
    assert verified["success"] is True, verified
    # 单来源且来源类型为 official_doc：官方文档核验可升级
    assert verified["data"]["status_after"] == "verified"


def test_cli_smoke(home: Path):
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "dsh_autonomous_learning.main",
            "--home",
            str(home),
            "tools",
            "list",
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    payload = json.loads(proc.stdout)
    names = {item["name"] for item in payload}
    assert "search_knowledge" in names
