"""核验测试：无证据不得升级、公式重算、观点不可验证、失败保留记录。"""

from __future__ import annotations

import json

from dsh_autonomous_learning.core.models import Chunk

from .conftest import make_chunk


def test_fact_needs_evidence(runtime):
    make_chunk(
        runtime,
        chunk_id="c1",
        content="滑点会显著降低高频策略的净收益。",
        source_quality=0.9,
    )
    outcome = runtime.verifier.verify("c1", method="source_check")
    # 单一来源对 fact 类型不够：只能是 partial/fail，不能升级
    assert outcome["result"] in {"fail", "partial"}
    assert outcome["status_after"] != "verified"
    chunk = runtime.metadata.get_chunk("c1")
    assert chunk["verification_status"] != "verified"
    # 失败/未通过也必须留下记录
    assert runtime.metadata.list_verifications("c1")


def test_no_source_at_all_is_fail(runtime):
    make_chunk(
        runtime,
        chunk_id="c2",
        content="一条没有任何来源的断言：滑点必然导致亏损。",
        source_id="",
        source_url="",
        source_quality=0.2,
        source_type="unknown",
    )
    outcome = runtime.verifier.verify("c2", method="source_check")
    assert outcome["result"] == "fail"
    assert outcome["status_after"] != "verified"


def test_fact_verified_with_two_independent_sources(runtime):
    make_chunk(runtime, chunk_id="c1", content="滑点会显著降低高频策略的净收益。", source_quality=0.9)
    outcome = runtime.verifier.verify(
        "c1",
        method="cross_source",
        evidence=[
            {"kind": "cross_source", "source_id": "src_b", "url": "https://b.example/doc"},
            {"kind": "cross_source", "source_id": "src_c", "url": "https://c.example/doc"},
        ],
    )
    assert outcome["result"] == "pass"
    assert outcome["status_after"] == "verified"
    chunk = runtime.metadata.get_chunk("c1")
    assert chunk["verification_status"] == "verified"
    assert chunk["level"] == "L3"
    assert chunk["evidence_count"] >= 2
    assert chunk["evidence_independence"] >= 2
    assert chunk["confidence"] <= 0.95
    assert "上限 0.95" in chunk["confidence_basis"]


def test_model_self_review_does_not_verify(runtime):
    make_chunk(runtime, chunk_id="c1", content="某个未经证实的技术结论。", source_quality=0.4)
    outcome = runtime.verifier.verify(
        "c1", method="manual_review", evidence=[{"kind": "model_claim", "note": "模型认为是对的"}]
    )
    # manual_review 需要显式证据；即使有，来源质量与独立性不足也不能升级
    assert outcome["status_after"] != "verified"


def test_opinion_is_marked_unverifiable(runtime):
    make_chunk(runtime, chunk_id="c1", content="我认为这个设计方案更好，纯属个人观点。", knowledge_type="opinion")
    outcome = runtime.verifier.verify("c1")
    assert outcome["result"] == "inconclusive"
    assert outcome["status_after"] == "pending_verification"
    chunk = runtime.metadata.get_chunk("c1")
    assert chunk["verification_status"] == "unverifiable"
    assert chunk["confidence"] <= 0.4


def test_formula_recompute_pass_and_fail(runtime):
    make_chunk(
        runtime,
        chunk_id="c_formula",
        content="夏普比率 = (年化收益 - 无风险利率) / 年化波动率。",
        knowledge_type="formula",
        source_quality=0.75,
        metadata={"formulas": [{"expression": "(ret - rf) / vol"}]},
    )
    ok = runtime.verifier.verify_formula(
        "c_formula", expression="(ret - rf) / vol", variables={"ret": 0.12, "rf": 0.02, "vol": 0.1}, expected=1.0
    )
    assert ok["result"] == "pass"
    assert ok["status_after"] == "verified"

    make_chunk(
        runtime,
        chunk_id="c_formula2",
        content="另一个公式：f = x * y。",
        knowledge_type="formula",
        source_quality=0.75,
    )
    bad = runtime.verifier.verify_formula("c_formula2", expression="x * y", variables={"x": 2, "y": 3}, expected=7)
    assert bad["result"] == "fail"
    assert bad["status_after"] == "disputed"


def test_formula_without_expected_is_inconclusive(runtime):
    make_chunk(runtime, chunk_id="c1", content="公式：y = a + b。", knowledge_type="formula")
    outcome = runtime.verifier.verify_formula("c1", expression="a + b", variables={"a": 1, "b": 2})
    assert outcome["result"] == "inconclusive"
    assert outcome["status_after"] != "verified"


def test_code_verification_uses_execution_result(runtime):
    make_chunk(runtime, chunk_id="c1", content="代码示例：print(1+1)", knowledge_type="code_example", source_quality=0.6)
    outcome = runtime.verifier.verify(
        "c1",
        method="code_test",
        code_result={"ok": True, "exit_code": 0, "stdout": "2", "environment": {"python": "3.13"}},
    )
    assert outcome["result"] == "pass"
    assert outcome["status_after"] == "verified"


def test_safe_formula_evaluator_rejects_code():
    from dsh_autonomous_learning.security.execution_policy import FormulaError, safe_eval_expression

    assert safe_eval_expression("sqrt(9) + 1") == 4.0
    for bad in ("__import__('os').system('echo hi')", "open('/etc/passwd')", "a if b else c", "lambda: 1"):
        try:
            safe_eval_expression(bad, {"a": 1, "b": 2, "c": 3})
        except FormulaError:
            continue
        raise AssertionError(f"公式求值不应接受: {bad}")
