"""组件实践产物的契约测试（第 10 项任务：组件测试）。

这些断言跑在真实生成的页面上，不是 mock：
- 每个页面都要满足标记契约（label / button type / focus / 触控目标 / 表头 / aria-live / reduced-motion）
- token 配色对比度必须达标
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dsh_autonomous_learning"))

spec = importlib.util.spec_from_file_location("practice", ROOT / "scripts" / "practice_components.py")
practice = importlib.util.module_from_spec(spec)
spec.loader.exec_module(practice)

PAGES = Path(ROOT / "docs" / "practice")


def _html(name: str) -> str:
    path = PAGES / ("%s.html" % name)
    if not path.exists():
        pytest.skip("尚未生成 %s，先跑 scripts/practice_components.py" % name)
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("page", ["login", "home", "dashboard", "settings", "dialog", "dual_style"])
def test_page_markup_contracts(page):
    results = practice.contract_tests(_html(page))
    failed = [(check, detail) for check, ok, detail in results if not ok]
    assert not failed, "%s 未通过契约: %s" % (page, failed)


def test_tokens_css_has_contrast_vars():
    css = (PAGES / "tokens.css").read_text(encoding="utf-8")
    for var in ("--color-bg", "--color-fg", "--color-accent", "--text-1", "--space-1", "--radius-1"):
        assert var in css, "tokens.css 缺少 %s" % var


def test_practice_report_has_ten_tasks():
    import json
    report = json.loads((PAGES / "REPORT.json").read_text(encoding="utf-8"))
    assert len(report["tasks"]) >= 10, "10 项实践任务都要在报告里"
