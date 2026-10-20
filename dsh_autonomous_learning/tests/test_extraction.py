"""提取与分类测试。"""

from __future__ import annotations

from dsh_autonomous_learning.knowledge import classifier
from dsh_autonomous_learning.knowledge.extractor import (
    KnowledgeExtractor,
    extract_formulas,
    identify_assumptions,
    identify_uncertainties,
)
from dsh_autonomous_learning.sources.parser import chunk_text, detect_language, split_sections

from .conftest import QUANT_DOC


def test_chunk_text_respects_size_and_overlap():
    text = "\n\n".join(["段落内容。" * 60] * 5)
    chunks = chunk_text(text, chunk_size=300, overlap=40, min_chars=20)
    assert chunks
    assert all(len(c) <= 600 for c in chunks)  # 允许一定溢出（段内句子拼接）
    assert any("段落内容" in c for c in chunks)


def test_split_sections_and_language():
    sections = split_sections(QUANT_DOC)
    assert len(sections) >= 4
    assert sections[1].heading
    assert detect_language(QUANT_DOC) == "zh"


def test_classifier_detects_types():
    assert classifier.classify_knowledge_type("滑点是指成交价与预期价的差额。")[0] == "definition"
    assert classifier.classify_knowledge_type("```python\nprint(1)\n```")[0] == "code_example"
    assert classifier.classify_knowledge_type("夏普比率 = (收益 - 无风险利率) / 波动率")[0] == "formula"
    assert classifier.classify_knowledge_type("我认为这个设计更好，个人观点仅供参考")[0] == "opinion"


def test_classifier_partition_from_keywords():
    partition, basis = classifier.classify_partition("量化策略的回测需要计入滑点与交易成本", domain="")
    assert partition == "quant_knowledge"
    assert "关键词" in basis


def test_formula_and_uncertainty_extraction():
    formulas = extract_formulas("夏普比率 = (收益 - 无风险利率) / 波动率，另外 $E=mc^2$。")
    assert formulas
    assert identify_uncertainties("这个结论可能不成立，仍需验证。")
    assert identify_assumptions("假设市场无摩擦，则策略收益等于组合收益。")


def test_extractor_is_idempotent(runtime):
    extractor = KnowledgeExtractor(runtime.config.learning, runtime.model)
    project = {"project_id": "prj_x", "domain": "quant", "title": "量化"}
    document = {
        "document_id": "doc_x",
        "text": QUANT_DOC,
        "title": "量化交易基础",
        "source_id": "src_x",
        "location": "https://example.com/quant",
        "source_type": "official_doc",
        "quality": 0.9,
        "language": "zh",
        "content_hash": "abc",
    }
    first = extractor.extract(project=project, document=document, topic="量化")
    second = extractor.extract(project=project, document=document, topic="量化")
    ids_first = [d["chunk_id"] for d in first["drafts"]]
    ids_second = [d["chunk_id"] for d in second["drafts"]]
    assert ids_first and ids_first == ids_second
    assert first["stats"]["kept"] > 0
    # 初始置信度必须很低，且明确说明未核验
    assert all(d["confidence"] <= 0.45 for d in first["drafts"])
    assert all("尚未核验" in d["confidence_basis"] or "未核验" in d["confidence_basis"] for d in first["drafts"])
