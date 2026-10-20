"""Art UI/UX Pro Max 的最小可验证测试集。

只测真实实现的东西：分类规则、注册表状态机、分节与等级判定、案例证据分级、
以及一条端到端的入库+检索（临时目录，不碰生产库）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dsh_autonomous_learning"))

from art_uiux import taxonomy
from art_uiux.case_analyzer import analyze_html, units_from_case
from art_uiux.extract import build_unit, classify, sectionize
from art_uiux.registry import Registry, RegistryError, validate_resource

FIXTURE_HTML = """
<html><head><style>
:root{--bg:#0b0b0f;--fg:#e5e5e5}
.hero{background:linear-gradient(180deg,#0b0b0f,#1a1030);padding:48px;border-radius:12px;}
.card{border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,.4);padding:24px;gap:16px}
h1{font-family:Inter,sans-serif;font-size:56px}
@media (max-width:768px){.hero{padding:24px}}
</style></head>
<body>
<h1>Design for teams</h1>
<p>The interface should keep contrast high enough for reading. Use 16px body text and avoid pure white on dark backgrounds.</p>
<h2>Gradients</h2>
<p>A linear-gradient from #0b0b0f to #1a1030 gives depth. Never stack more than two gradients in one section.</p>
<img src="a.png" alt="preview">
<img src="b.png">
<div role="button" aria-label="open"></div>
</body></html>
"""

FIXTURE_RESOURCE = {
    "resource_id": "unit-test",
    "name": "Fixture Product",
    "url": "https://example.com/",
    "resource_type": "product_case",
    "primary_category": "web_ui",
    "secondary_categories": ["visual_aesthetics"],
    "platform": "web",
    "learning_objectives": ["测试"],
    "access_status": "unchecked",
    "last_checked": "",
    "last_learned": "",
    "license_notes": "测试用",
    "source_reliability": "medium",
    "learning_priority": 3,
    "crawl_policy": "public_landing_analysis",
}


def test_taxonomy_has_exactly_twelve_primary_categories():
    assert len(taxonomy.CATEGORY_KEYS) == 12
    assert len(set(taxonomy.CATEGORY_KEYS)) == 12


def test_taxonomy_assignment_rules():
    assert taxonomy.validate_assignment("color_system", ["ui_quality", "ui_quality"]) == ["ui_quality"]
    with pytest.raises(taxonomy.TaxonomyError):
        taxonomy.validate_assignment("color_system", ["color_system"])
    with pytest.raises(taxonomy.TaxonomyError):
        taxonomy.validate_assignment("not_a_category")
    with pytest.raises(taxonomy.TaxonomyError):
        taxonomy.validate_assignment("color_system", ["nope"])


def test_extraction_fields_match_spec():
    # 需求六的 16 个字段必须齐全
    assert len(taxonomy.EXTRACTION_FIELDS) == 16
    assert "source_ref" in taxonomy.EXTRACTION_MINIMUM


def test_registry_validation_rejects_bad_data():
    good = dict(FIXTURE_RESOURCE)
    validate_resource(good)

    bad = dict(good); bad.pop("license_notes")
    with pytest.raises(RegistryError):
        validate_resource(bad)

    bad = dict(good); bad["resource_type"] = "blog"
    with pytest.raises(RegistryError):
        validate_resource(bad)

    bad = dict(good); bad["learning_priority"] = 9
    with pytest.raises(RegistryError):
        validate_resource(bad)


def test_registry_state_is_separate_from_seed(tmp_path):
    (tmp_path / "art_uiux").mkdir()
    (tmp_path / "art_uiux" / "resources.seed.json").write_text(
        '{"resources": [%s]}' % __import__("json").dumps(FIXTURE_RESOURCE), encoding="utf-8")
    reg = Registry(tmp_path)
    assert reg.view()[0]["learn_status"] == "not_started"

    reg.record_check("unit-test", access_status="reachable", http_status=200)
    reg.record_learning("unit-test", learn_status="learned", chunks=3)
    item = reg.get("unit-test")
    assert item["access_status"] == "reachable"
    assert item["learn_status"] == "learned"
    assert item["learned_chunks"] == 3
    # 种子文件没被污染
    import json
    seed = json.loads((tmp_path / "art_uiux" / "resources.seed.json").read_text())
    assert seed["resources"][0]["access_status"] == "unchecked"


def test_sectionize_and_classify():
    sections = sectionize(FIXTURE_HTML)
    assert sections, "应能抽出正文区块"
    cat, score, matched = classify(sections[0].text, heading=sections[0].heading)
    assert cat in taxonomy.CATEGORY_KEYS
    assert 0.0 <= score <= 1.0


def test_build_unit_levels_are_earned():
    sections = sectionize(FIXTURE_HTML)
    normative = [s for s in sections if "should" in s.text.lower()]
    assert normative, "fixture 里应有带 should 的规范句"
    unit = build_unit(normative[0], resource=FIXTURE_RESOURCE, category="ui_quality", score=0.6, matched=["contrast"])
    assert unit["level"] == "L2", "有显式约束语才算 L2"
    assert unit["knowledge"]["evidence_level"] == "L2"
    # 是否允许入库现在还多了一道设计相关度门槛，这里分开断言，避免把两件事混为一谈
    assert unit["relevance"]["relevant"] in (True, False)
    assert unit["ready_to_ingest"] == (all(unit["knowledge"][k] for k in
                                          ("core_principle", "applicable_context", "source_ref", "evidence_level"))
                                      and unit["relevance"]["relevant"])

    plain = build_unit(sectionize(FIXTURE_HTML)[-1], resource=FIXTURE_RESOURCE,
                       category="web_ui", score=0.3, matched=["css"])
    assert plain["knowledge"]["evidence_level"] in {"L1", "L2"}


def test_case_analyzer_separates_fact_from_opinion():
    ca = analyze_html(FIXTURE_HTML, url="https://example.com/", product="Fixture")
    kinds = {ev.kind for items in ca.sections.values() for ev in items}
    assert kinds <= {"fact", "inference", "opinion"}
    assert any("linear-gradient" in ev.statement for ev in ca.sections["Background Analysis"])
    # 无障碍：两张图只有一张带 alt
    a11y = " ".join(ev.statement for ev in ca.sections["Accessibility Analysis"])
    assert "img 2 张" in a11y and "带 alt 1 张" in a11y
    # 技术栈未检出不硬编造
    assert isinstance(ca.tech_stack, list)


def test_case_units_exclude_capability_disclaimers():
    ca = analyze_html(FIXTURE_HTML, url="https://example.com/", product="Fixture")
    units = units_from_case(ca, resource=FIXTURE_RESOURCE)
    assert units, "应产出知识单元"
    joined = " ".join(u["content"] for u in units)
    assert "能力边界" not in joined, "能力边界声明不得入库"
    for unit in units:
        assert unit["category"] in taxonomy.CATEGORY_KEYS
        assert unit["level"] in {"L1", "L2"}


def test_end_to_end_ingest_and_hybrid_search(tmp_path):
    """真跑一次：入库 → 检索 → 必须带回来源与等级。"""

    from dsh_autonomous_learning.config import load_config
    from dsh_autonomous_learning.core.models import Chunk, Project
    from dsh_autonomous_learning.core.orchestrator import build_runtime
    from dsh_autonomous_learning.storage.metadata_store import ChunkFilter

    home = tmp_path / "engine"
    home.mkdir()
    cfg = load_config(home=home)
    rt = build_runtime(cfg)
    try:
        proj = Project(project_id="p_test", title="t", goal="g", domain="uiux",
                       partitions=["uiux_knowledge", "pending_knowledge"])
        rt.metadata.create_project(proj.to_row())
        chunk = Chunk(
            chunk_id="c_test", project_id="p_test", document_id="d_test", partition="uiux_knowledge", domain="uiux",
            topic="color_system", title="对比度底线", content="正文与背景对比度建议不低于 4.5:1，用于可读性判断。",
            summary="对比度 4.5:1", level="L2", source_url="https://example.com/a", source_title="A",
            verification_status="unverified", confidence=0.4,
        )
        rt.store.add_chunks([chunk.to_row()])
        res = rt.store.search("对比度 可读性", top_k=3, filters=ChunkFilter(project_id="p_test"), include_content=True)
        hits = res.get("results") or []
        assert hits, "入库后应能检索到"
        assert hits[0]["source"]["url"] == "https://example.com/a", "检索结果必须带来源"
        assert hits[0]["level"] == "L2"
        assert any("unverified" in w for w in hits[0]["warnings"]), "未核验必须告警"
    finally:
        rt.close()


# ---------------------------------------------------------------- 七步工作流

from art_uiux.design_workflow import (   # noqa: E402
    AUDIT_ITEMS, audit_html, build_design_system, check_palette, contrast_ratio,
    feedback_unit, propose_directions, route_task, tokens_to_css,
)


def test_contrast_math_matches_wcag_reference():
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio("#ffffff", "#ffffff") == pytest.approx(1.0, abs=0.001)
    # 灰字白底应低于 AA 正文阈值
    assert contrast_ratio("#999999", "#ffffff") < 4.5


def test_palette_report_flags_failing_pairs():
    report = check_palette([("bad", "#999999", "#ffffff"), ("good", "#111111", "#ffffff")])
    bad, good = report
    assert bad["AA_normal"] is False and bad["measured"] is True
    assert good["AA_normal"] is True and good["ratio"] > 15


def test_route_task_picks_specialised_type():
    assert route_task("给我做一个金融行情终端界面")[0] == "fintech_terminal"
    assert route_task("用 Compose 写一个 Android 首页")[0] == "android_native"
    assert route_task("随便聊聊")[0] in ("web_page", "ui_refactor")


def test_directions_are_distinct_and_not_default_cliche():
    dirs = propose_directions("fintech_terminal", count=3)
    assert len(dirs) == 3
    assert len({d["key"] for d in dirs}) == 3
    # 三个方向必须在风格/色彩/布局上互不相同
    assert len({d["style"] for d in dirs}) == 3
    assert len({d["layout"] for d in dirs}) == 3
    joined = " ".join(d["idea"] for d in dirs)
    assert "玻璃拟态" not in joined


def test_design_system_reports_real_contrast_and_marks_unverified():
    ds = build_design_system("industrial_dense")
    assert ds["verified"] is False
    assert ds["contrast"], "必须给出实测对比度"
    assert all(c.get("measured") for c in ds["contrast"])
    assert ";" in tokens_to_css(ds)


def test_audit_marks_unmeasured_instead_of_passing_silently():
    html = '<div style="font-size:16px;color:#999999"></div><img src="a.png">'
    result = audit_html(html)
    assert len(result["items"]) == len(AUDIT_ITEMS)
    statuses = {i["item"]: i["status"] for i in result["items"]}
    assert statuses["background_readability"] == "unmeasured"
    assert statuses["accessibility"] == "fail"  # img 无 alt


def test_audit_with_tokens_flags_contrast_failure():
    html = '<style>:root{font-size:14px}.x{box-shadow:0 1px 2px}#fff</style><img alt="ok">'
    ds = build_design_system("editorial_light", base={"fg": "#dddddd"})
    result = audit_html(html, tokens=ds["tokens"])
    statuses = {i["item"]: i["status"] for i in result["items"]}
    assert statuses["background_readability"] == "fail", "浅灰正文在浅底上必须被判失败"


def test_feedback_keeps_project_knowledge_out_of_general_scope():
    unit = feedback_unit(decision="紧凑行高适用于交易台", evidence="在 1080p 下实测 8 行可读",
                         scope="project", category="financial_dashboard")
    assert unit["partition"] == "project_knowledge"
    assert unit["level"] == "L2"
    with pytest.raises(ValueError):
        feedback_unit(decision="x", evidence="y", scope="global", category="web_ui")


# ---------------------------------------------------------------- 组件学习引擎

from art_uiux.components import analyze_repository, categorize, comparisons  # noqa: E402


def test_component_categories_cover_eight_groups():
    assert categorize("Button") == "basic"
    assert categorize("BottomSheet") == "overlay"
    assert categorize("StatCard") == "data"
    assert categorize("RichTextEditor") == "advanced"
    assert categorize("UnknownThing") == "unknown"


def _fake_repo(archived=False, license_id="MIT"):
    meta = {"full_name": "demo/ui", "license": {"spdx_id": license_id}, "archived": archived,
            "stargazers_count": 1234, "pushed_at": "2025-06-01T00:00:00Z", "language": "TypeScript",
            "default_branch": "main"}
    paths = [
        "packages/ui/src/components/button/Button.tsx",
        "packages/ui/src/components/dialog/Dialog.tsx",
        "packages/ui/src/components/table/Table.tsx",
        "packages/ui/src/components/__tests__/button.test.tsx",
        "apps/docs/examples/button.md",
    ]
    return meta, "# Demo UI\nA component library.", paths


def test_repository_analysis_marks_level_from_real_evidence():
    meta, readme, paths = _fake_repo()
    info = analyze_repository(meta, readme, paths, platform="web", source_key="demo")
    assert info["license"] == "MIT"
    assert info["knowledge_level"] == "L2", "有组件目录且有测试/示例才算 L2"
    assert info["test_files"] >= 1
    assert "basic" in info["components_by_category"]

    meta2, readme2, paths2 = _fake_repo(license_id="Apache-2.0")
    info2 = analyze_repository(meta2, readme2, paths2[:2], platform="android", source_key="demo2")
    assert info2["knowledge_level"] == "L1", "没有测试/示例只能到 L1"
    assert info2["license"] == "Apache-2.0"


def test_archived_repository_shows_up_as_limitation():
    meta, readme, paths = _fake_repo(archived=True)
    info = analyze_repository(meta, readme, paths, platform="web", source_key="demo")
    assert "归档" in info["limitations"]


def test_comparison_has_no_quality_verdict():
    rows = comparisons([analyze_repository(*_fake_repo(), platform="web", source_key="a"),
                        analyze_repository(*_fake_repo(license_id="Apache-2.0"), platform="android", source_key="b")])
    keys = set(rows[0])
    assert {"license", "framework", "components", "tests"} <= keys
    assert not any(k in keys for k in ("best", "score", "winner")), "比较表不得给「最好」结论"


# ---------------------------------------------------------------- 可量化检索评测

from art_uiux import metrics as M   # noqa: E402
from art_uiux.bilingual import expand as bilingual_expand  # noqa: E402


def test_precision_recall_mrr_on_known_ranking():
    ranked = ["a", "b", "c", "d"]
    rel = {"a": 2, "c": 1}
    assert M.precision_at_k(ranked, rel, 1) == 1.0
    assert M.precision_at_k(ranked, rel, 3) == pytest.approx(2 / 3)
    assert M.recall_at_k(ranked, rel, 2) == 0.5
    assert M.recall_at_k(ranked, rel, 10) == 1.0
    assert M.mrr_at_k(ranked, rel, 10) == 1.0
    # 只有 grade 1 不算「首个正确答案」
    assert M.mrr_at_k(["b", "a"], rel, 10) == 0.5


def test_ndcg_matches_hand_computation():
    # 完美排序 ndcg = 1
    rel = {"a": 2, "b": 1}
    assert M.ndcg_at_k(["a", "b"], rel, 5) == pytest.approx(1.0)
    # 反序：(2^1-1)/log2(2) + (2^2-1)/log2(3) / ideal
    got = M.ndcg_at_k(["b", "a"], rel, 5)
    ideal = (2 ** 2 - 1) + (2 ** 1 - 1) / 1.584962500721156
    exp = ((2 ** 1 - 1) + (2 ** 2 - 1) / 1.584962500721156) / ideal
    assert got == pytest.approx(exp, rel=1e-6)


def test_no_answer_query_metrics_are_nan_not_zero():
    assert M.recall_at_k(["x", "y"], {}, 5) != M.recall_at_k(["x", "y"], {}, 5)  # NaN
    assert M.ndcg_at_k(["x"], {}, 5) != M.ndcg_at_k(["x"], {}, 5)


def test_bootstrap_reports_interval_and_n():
    a = [1.0, 0.8, 0.9, 0.7, 1.0]
    b = [0.5, 0.4, 0.6, 0.3, 0.5]
    out = M.bootstrap_diff(a, b)
    assert out["n"] == 5
    assert out["mean_diff"] > 0
    assert out["lo"] <= out["mean_diff"] <= out["hi"]


def test_bilingual_expansion_adds_domain_terms_only_for_chinese():
    q, hits = bilingual_expand("深色模式下的对比度怎么控制")
    assert "contrast ratio" in q and "dark mode" in q
    assert len(hits) >= 2
    q2, hits2 = bilingual_expand("contrast ratio for dark mode")
    assert q2 == "contrast ratio for dark mode" and hits2 == []


def test_rerank_returns_empty_without_loading_model():
    from art_uiux.rerank import rerank as ce_rerank
    out = ce_rerank("任何查询", [], top_k=5)
    assert out["results"] == [] and out["reranked"] == 0
