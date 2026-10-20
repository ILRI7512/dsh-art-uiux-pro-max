"""检索质量测试：语义 + 关键词混合、元数据过滤、项目隔离。"""

from __future__ import annotations

from dsh_autonomous_learning.storage.metadata_store import ChunkFilter

from .conftest import make_chunk

DOCS = {
    "c_slippage": "滑点是指订单实际成交价格与预期价格之间的差额，回测时必须计入滑点成本。",
    "c_sharpe": "夏普比率衡量单位风险获得的超额收益，计算时需要减去无风险利率。",
    "c_overfit": "样本外测试用于检测过拟合，反复根据样本外结果调参会引入新的偏差。",
    "c_contrast": "无障碍设计要求正文颜色对比度不低于 4.5:1，这是可访问性的最低要求。",
}


def _seed(runtime):
    for chunk_id, content in DOCS.items():
        make_chunk(runtime, chunk_id=chunk_id, content=content, topic="量化" if chunk_id != "c_contrast" else "无障碍")


def test_semantic_search_hits_expected_chunk(runtime):
    _seed(runtime)
    result = runtime.store.search("滑点会不会影响回测", ChunkFilter(project_id="prj_test"), top_k=3)
    assert result["results"], result
    assert result["results"][0]["chunk_id"] == "c_slippage"


def test_keyword_channel_works_without_vector(runtime):
    _seed(runtime)
    result = runtime.store.search("样本外 过拟合", ChunkFilter(project_id="prj_test"), top_k=3, mode="keyword")
    assert result["results"][0]["chunk_id"] == "c_overfit"


def test_hybrid_recall_at_3(runtime):
    _seed(runtime)
    queries = {
        "滑点成本": "c_slippage",
        "夏普比率怎么算": "c_sharpe",
        "怎么避免过拟合": "c_overfit",
        "颜色对比度要求": "c_contrast",
    }
    hits = 0
    for query, expected in queries.items():
        result = runtime.store.search(query, ChunkFilter(project_id="prj_test"), top_k=3)
        ids = [r["chunk_id"] for r in result["results"]]
        if expected in ids:
            hits += 1
    assert hits == len(queries), f"Recall@3 = {hits}/{len(queries)}"


def test_metadata_filter_by_partition(runtime):
    make_chunk(runtime, chunk_id="c1", content="量化知识：滑点。", partition="quant_knowledge")
    make_chunk(runtime, chunk_id="c2", content="量化知识：滑点。", partition="pending_knowledge")
    result = runtime.store.search(
        "滑点", ChunkFilter(project_id="prj_test", partitions=["quant_knowledge"]), top_k=5
    )
    assert [r["chunk_id"] for r in result["results"]] == ["c1"]


def test_project_isolation(runtime):
    make_chunk(runtime, chunk_id="c_private", content="项目 A 的私有知识：内部架构决策。", project_id="prj_a")
    make_chunk(
        runtime,
        chunk_id="c_other",
        content="项目 B 的私有知识：另一套架构决策。",
        project_id="prj_b",
    )
    result = runtime.store.search("架构决策", ChunkFilter(project_id="prj_a"), top_k=5)
    ids = [r["chunk_id"] for r in result["results"]]
    assert "c_private" in ids
    assert "c_other" not in ids

    make_chunk(
        runtime,
        chunk_id="c_global",
        content="通用知识：架构决策应当记录 ADR。",
        visibility="global",
    )
    result = runtime.store.search("架构决策", ChunkFilter(project_id="prj_a"), top_k=5)
    ids = [r["chunk_id"] for r in result["results"]]
    assert "c_global" in ids


def test_empty_result_reports_gap(runtime):
    result = runtime.store.search("完全不存在的主题", ChunkFilter(project_id="prj_test"))
    assert result["results"] == []
    assert result["gap"] is True
    assert result["warnings"]


def test_results_carry_reliability_warnings(runtime):
    make_chunk(runtime, chunk_id="c1", content="未核验的知识：滑点影响收益。", verification_status="unverified")
    result = runtime.store.search("滑点", ChunkFilter(project_id="prj_test"))
    item = result["results"][0]
    assert item["need_reverify"] is True
    assert any("核验" in w for w in item["warnings"])
    assert item["source"]["url"]
