"""pytest 公共夹具：临时数据目录、运行时、注册表、示例语料。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dsh_autonomous_learning.config import load_config  # noqa: E402
from dsh_autonomous_learning.core.orchestrator import build_runtime  # noqa: E402
from dsh_autonomous_learning.tools import build_registry  # noqa: E402

QUANT_DOC = """# 量化交易基础

## 滑点

滑点是指订单实际成交价格与预期价格之间的差额。滑点通常由市场流动性不足与波动率上升导致。回测时如果不计入滑点，收益会被系统性高估。

## 夏普比率

夏普比率 = (策略年化收益 - 无风险利率) / 策略年化波动率。夏普比率越高，说明单位风险获得的超额收益越高。注意：夏普比率假设收益近似正态分布，在极端行情下可能低估尾部风险。

## 回测步骤

1. 准备历史数据并检查缺失值与复权处理。
2. 划分样本内与样本外区间，样本外数据不得参与调参。
3. 计入交易成本与滑点，记录假设条件。
4. 记录策略参数、数据版本与运行环境。

## 风险提示

不要在样本外表现不佳时反复调参，这会导致过拟合。历史回测收益不能直接当作未来收益。
"""

UIUX_DOC = """# UI/UX 基础

## 可用性

可用性是指用户在特定场景下高效完成目标的程度。可用性测试需要真实用户参与，不能只靠设计者主观判断。

## 无障碍

无障碍设计要求正文文本的颜色对比度不低于 4.5:1。注意：这是可访问性的最低要求，不是审美标准，也不能用单个案例推广为普遍规律。
"""


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    root = tmp_path / "al_home"
    root.mkdir(parents=True, exist_ok=True)
    (root / "corpus").mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture()
def corpus(home: Path) -> Path:
    (home / "corpus" / "quant_basics.md").write_text(QUANT_DOC, encoding="utf-8")
    (home / "corpus" / "uiux_basics.md").write_text(UIUX_DOC, encoding="utf-8")
    return home / "corpus"


@pytest.fixture()
def config(home: Path):
    return load_config(
        home=home,
        overrides={
            "paths": {
                "home": str(home),
                "data_dir": str(home / "data"),
                "corpus_dir": str(home / "corpus"),
            },
            "embedding": {"provider": "hashing", "dim": 256},
            "model": {"provider": "mock"},
            "learning": {"default_mode": "auto", "max_tasks_per_run": 30, "max_chunks_per_document": 60},
            "security": {"allowed_roots": [str(home)], "allow_network": False},
        },
    )


@pytest.fixture()
def lab_config(config):
    from dataclasses import replace

    config.learning.default_mode = "lab"
    return config


@pytest.fixture()
def runtime(config):
    rt = build_runtime(config)
    try:
        yield rt
    finally:
        rt.close()


@pytest.fixture()
def lab_runtime(lab_config):
    rt = build_runtime(lab_config, mode="lab")
    try:
        yield rt
    finally:
        rt.close()


@pytest.fixture()
def registry(runtime):
    reg, orch, scheduler = build_registry(runtime)
    return reg


@pytest.fixture()
def orchestrator(runtime):
    _, orch, _ = build_registry(runtime)
    return orch


def ensure_project(runtime, project_id: str) -> None:
    """确保项目行存在，满足 chunks.project_id 的外键约束。"""

    if runtime.metadata.get_project(project_id):
        return
    from dsh_autonomous_learning.core.models import Project

    project = Project(
        project_id=project_id,
        title=f"测试项目 {project_id}",
        goal="测试用学习目标",
        domain="general",
        partitions=["pending_knowledge", "general_knowledge"],
    )
    runtime.metadata.create_project(project.to_row())


def make_chunk(runtime, *, chunk_id: str, content: str, project_id: str = "prj_test", **overrides):
    """直接写入一条测试知识（绕过提取器，便于精确构造场景）。"""

    ensure_project(runtime, project_id)
    payload = {
        "chunk_id": chunk_id,
        "project_id": project_id,
        "title": overrides.pop("title", chunk_id),
        "content": content,
        "summary": content[:80],
        "knowledge_type": overrides.pop("knowledge_type", "fact"),
        "partition": overrides.pop("partition", "pending_knowledge"),
        "domain": overrides.pop("domain", "general"),
        "topic": overrides.pop("topic", "测试主题"),
        "source_id": overrides.pop("source_id", "src_a"),
        "source_url": overrides.pop("source_url", "https://example.com/a"),
        "source_type": overrides.pop("source_type", "official_doc"),
        "source_quality": overrides.pop("source_quality", 0.8),
        "status": overrides.pop("status", "pending_verification"),
        "level": overrides.pop("level", "L2"),
        **overrides,
    }
    runtime.store.add_chunks([payload])
    return payload
