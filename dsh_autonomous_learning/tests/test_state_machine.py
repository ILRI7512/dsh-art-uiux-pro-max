"""知识状态机与学习等级测试（规则 3）。"""

from __future__ import annotations

import pytest

from dsh_autonomous_learning.core.models import (
    Chunk,
    VerificationRecord,
    VerificationResult,
)
from dsh_autonomous_learning.core.state_machine import (
    at_least,
    compute_level,
    evaluate_transition,
    level_index,
)


def _chunk(**kwargs) -> Chunk:
    base = dict(
        chunk_id="c1",
        project_id="p1",
        document_id="d1",
        content="滑点是指成交价与预期价的差额。",
        knowledge_type="fact",
        status="pending_verification",
        source_quality=0.8,
    )
    base.update(kwargs)
    return Chunk(**base)


def _record(**kwargs) -> VerificationRecord:
    base = dict(
        record_id="r1",
        chunk_id="c1",
        method="cross_source",
        result=VerificationResult.PASS.value,
        evidence=[{"source_id": "s1", "url": "https://a"}, {"source_id": "s2", "url": "https://b"}],
    )
    base.update(kwargs)
    return VerificationRecord(**base)


def test_no_evidence_cannot_verify():
    decision = evaluate_transition(_chunk(), "verified", [])
    assert not decision.allowed
    assert "核验记录" in " ".join(decision.reasons)


def test_two_independent_sources_can_verify():
    decision = evaluate_transition(_chunk(), "verified", [_record()])
    assert decision.allowed, decision.reasons


def test_single_source_insufficient_for_fact():
    record = _record(evidence=[{"source_id": "s1"}])
    decision = evaluate_transition(_chunk(), "verified", [record])
    assert not decision.allowed


def test_opinion_never_verified():
    decision = evaluate_transition(_chunk(knowledge_type="opinion"), "verified", [_record()])
    assert not decision.allowed
    assert "观点" in " ".join(decision.reasons) or "opinion" in " ".join(decision.reasons)


def test_hypothesis_never_verified():
    decision = evaluate_transition(_chunk(knowledge_type="hypothesis"), "verified", [_record()])
    assert not decision.allowed


def test_low_quality_source_blocks_verification():
    decision = evaluate_transition(_chunk(source_quality=0.2), "verified", [_record()])
    assert not decision.allowed
    assert "来源质量" in " ".join(decision.reasons)


def test_illegal_transition_rejected():
    decision = evaluate_transition(_chunk(status="rejected"), "verified", [_record()])
    assert not decision.allowed


def test_practiced_requires_execution_evidence():
    chunk = _chunk(status="verified")
    decision = evaluate_transition(chunk, "practiced", [])
    assert not decision.allowed
    code_record = VerificationRecord(
        record_id="r2",
        chunk_id="c1",
        method="code_test",
        result=VerificationResult.PASS.value,
        evidence=[{"kind": "code_test", "exit_code": 0}],
    )
    assert evaluate_transition(chunk, "practiced", [code_record]).allowed


def test_superseded_requires_target():
    chunk = _chunk(status="verified")
    assert not evaluate_transition(chunk, "superseded", []).allowed
    chunk.superseded_by = "c2"
    assert evaluate_transition(chunk, "superseded", []).allowed


def test_levels_are_derived_not_claimed():
    assert compute_level(_chunk(status="discovered")) == "L1"
    assert compute_level(_chunk(status="extracted")) == "L2"
    assert compute_level(_chunk(status="verified")) == "L3"
    assert compute_level(_chunk(status="practiced")) == "L4"
    assert compute_level(_chunk(status="evaluated")) == "L5"
    assert level_index("L5") > level_index("L2")
    assert at_least("L3", "L2")
    assert not at_least("L1", "L2")
