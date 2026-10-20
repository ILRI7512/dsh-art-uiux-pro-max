"""知识提取器。

目标：把"清洗后的文档"转成结构化知识草稿，而不是把整页文本塞进向量库。

实现策略：
- 规则优先：按章节 + 段落切块，按模式识别知识类型、公式、代码、假设、不确定项；
- 模型可选：开启后让模型给出"候选条目"，一律标记 ``proposed_by=model``、
  状态 ``pending_verification``、置信度更低——绝不允许模型直接产出 verified；
- 幂等：chunk_id 由 ``project_id + document_id + 内容指纹`` 决定，
  同一文档重复导入不会产生重复条目。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from ..config import LearningConfig
from ..core.model_adapter import BaseModel, ModelError
from ..core.models import (
    Chunk,
    FreshnessStatus,
    KnowledgeStatus,
    KnowledgeType,
    LearningLevel,
    LicenseStatus,
    Partition,
    SourceType,
    stable_hash,
    utcnow_iso,
)
from ..sources.parser import chunk_text, detect_language, extract_code_blocks, split_sections, summarize
from . import classifier as classification
from .partitions import default_visibility

_FORMULA_PATTERNS = [
    re.compile(r"\$([^$\n]{2,120})\$"),
    re.compile(r"\\\((.+?)\\\)"),
    re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*\s*=\s*[^=\n]{2,120})$", re.M),
]
_CODE_FENCE = re.compile(r"```([A-Za-z0-9_+#.\-]*)\n(.*?)```", re.S)
_ASSUMPTION_MARKERS = ("假设", "假定", "前提是", "若", "如果", "在……条件下", "assuming", "given that", "suppose", "if ")
_UNCERTAINTY_MARKERS = (
    "可能",
    "也许",
    "尚不清楚",
    "不确定",
    "待验证",
    "估计",
    "推测",
    "may ",
    "might ",
    "likely",
    "probably",
    "unclear",
    "unverified",
)


@dataclass
class KnowledgeDraft:
    """提取结果（尚未入库）。"""

    chunk_id: str
    project_id: str
    document_id: str
    title: str
    content: str
    summary: str
    knowledge_type: str
    partition: str
    domain: str
    topic: str = ""
    subtopic: str = ""
    source_id: str = ""
    source_url: str = ""
    source_title: str = ""
    source_type: str = SourceType.UNKNOWN.value
    author_or_publisher: str = ""
    published_at: str = ""
    accessed_at: str = ""
    language: str = "unknown"
    content_hash: str = ""
    status: str = KnowledgeStatus.PENDING_VERIFICATION.value
    level: str = LearningLevel.L2.value
    source_quality: float = 0.5
    confidence: float = 0.3
    confidence_basis: str = ""
    verification_status: str = "unverified"
    verification_method: str = "none"
    freshness_status: str = FreshnessStatus.UNKNOWN.value
    license_status: str = LicenseStatus.UNKNOWN.value
    visibility: str = "global"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def extract_formulas(text: str) -> List[Dict[str, str]]:
    found: List[Dict[str, str]] = []
    seen = set()
    for pattern in _FORMULA_PATTERNS:
        for match in pattern.finditer(text or ""):
            expr = match.group(1).strip()
            if not expr or expr in seen or len(expr) > 200:
                continue
            # 排除明显的非公式（纯一句话、没有运算符）
            if not re.search(r"[=+\-*/^<>≤≥∑√π]|\\frac|\\sum|\\int", expr):
                continue
            seen.add(expr)
            found.append({"expression": expr, "kind": "inline"})
    return found[:20]


def extract_concepts(text: str) -> List[Dict[str, str]]:
    concepts: List[Dict[str, str]] = []
    patterns = [
        re.compile(r"([\u4e00-\u9fffA-Za-z0-9\- ]{2,24})\s*(?:是指|指的是|定义为)\s*([^。\n]{2,120})"),
        re.compile(r"([A-Za-z][A-Za-z0-9_\- ]{2,40})\s+(?:is defined as|refers to)\s+([^.\n]{2,160})", re.I),
    ]
    for pattern in patterns:
        for match in pattern.finditer(text or ""):
            term = match.group(1).strip()
            definition = match.group(2).strip()
            if term and definition:
                concepts.append({"term": term, "definition": definition})
    return concepts[:20]


def identify_assumptions(text: str) -> List[str]:
    assumptions: List[str] = []
    for line in re.split(r"(?<=[。！？.!?])\s*|\n", text or ""):
        lowered = line.lower()
        if any(marker in line or marker in lowered for marker in _ASSUMPTION_MARKERS):
            snippet = line.strip()
            if 4 <= len(snippet) <= 300:
                assumptions.append(snippet)
    return list(dict.fromkeys(assumptions))[:10]


def identify_uncertainties(text: str) -> List[str]:
    items: List[str] = []
    for line in re.split(r"(?<=[。！？.!?])\s*|\n", text or ""):
        lowered = line.lower()
        if any(marker in line or marker in lowered for marker in _UNCERTAINTY_MARKERS):
            snippet = line.strip()
            if 4 <= len(snippet) <= 300:
                items.append(snippet)
    return list(dict.fromkeys(items))[:10]


def extract_code_examples(text: str) -> List[Dict[str, str]]:
    return extract_code_blocks(text)


@dataclass
class ExtractionStats:
    sections: int = 0
    candidates: int = 0
    kept: int = 0
    skipped_short: int = 0
    model_items: int = 0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sections": self.sections,
            "candidates": self.candidates,
            "kept": self.kept,
            "skipped_short": self.skipped_short,
            "model_items": self.model_items,
            "warnings": list(self.warnings),
        }


class KnowledgeExtractor:
    def __init__(self, config: LearningConfig, model: Optional[BaseModel] = None) -> None:
        self.cfg = config
        self.model = model

    # ------------------------------------------------------------------ #
    def extract(
        self,
        *,
        project: Mapping[str, Any],
        document: Mapping[str, Any],
        topic: str = "",
        use_model: bool = False,
    ) -> Dict[str, Any]:
        text = str(document.get("text") or "")
        stats = ExtractionStats()
        if not text.strip():
            return {"drafts": [], "stats": stats.to_dict(), "warnings": ["文档正文为空，未提取到知识"]}

        sections = split_sections(text)
        stats.sections = len(sections)
        drafts: List[KnowledgeDraft] = []
        language = document.get("language") or detect_language(text)
        source_quality = float(document.get("quality", 0.5) or 0.5)
        source_type = document.get("source_type") or SourceType.UNKNOWN.value
        default_topic = topic or document.get("title") or project.get("title", "")

        for section in sections:
            section_title = section.heading or default_topic
            chunks = chunk_text(
                section.text,
                chunk_size=self.cfg.chunk_size,
                overlap=self.cfg.chunk_overlap,
                min_chars=self.cfg.min_chunk_chars,
                max_chunks=self.cfg.max_chunks_per_document,
            )
            for index, chunk in enumerate(chunks):
                stats.candidates += 1
                if len(chunk) < self.cfg.min_chunk_chars:
                    stats.skipped_short += 1
                    continue
                draft = self._build_draft(
                    project=project,
                    document=document,
                    chunk=chunk,
                    section_title=section_title,
                    section_index=section.index,
                    chunk_index=index,
                    language=language,
                    source_quality=source_quality,
                    source_type=source_type,
                    topic=topic or default_topic,
                )
                drafts.append(draft)
                stats.kept += 1

        model_drafts = []
        if use_model and self.model is not None:
            try:
                model_drafts = self._model_proposals(project, document, text, topic or default_topic)
                stats.model_items = len(model_drafts)
                drafts.extend(model_drafts)
            except Exception as exc:  # noqa: BLE001
                stats.warnings.append(f"模型提取失败，已仅使用规则提取: {exc}")

        # 去重（同一文档内相同内容指纹）
        unique: Dict[str, KnowledgeDraft] = {}
        for draft in drafts:
            unique.setdefault(draft.content_hash, draft)
        stats.kept = len(unique)
        return {
            "drafts": [d.to_row() for d in unique.values()],
            "stats": stats.to_dict(),
            "warnings": stats.warnings,
        }

    # ------------------------------------------------------------------ #
    def _build_draft(
        self,
        *,
        project: Mapping[str, Any],
        document: Mapping[str, Any],
        chunk: str,
        section_title: str,
        section_index: int,
        chunk_index: int,
        language: str,
        source_quality: float,
        source_type: str,
        topic: str,
    ) -> KnowledgeDraft:
        title = section_title.strip() or (chunk.splitlines()[0][:60] if chunk else "未命名知识")
        cls = classification.classify(chunk, title=title, domain=str(project.get("domain") or ""))
        content_hash = stable_hash(f"{document.get('document_id')}|{chunk}")
        chunk_id = "chunk_" + stable_hash(
            f"{project.get('project_id')}|{document.get('document_id')}|{content_hash}", 24
        )
        formulas = extract_formulas(chunk)
        codes = extract_code_examples(chunk)
        assumptions = identify_assumptions(chunk)
        uncertainties = identify_uncertainties(chunk)
        concepts = extract_concepts(chunk)

        # 初始置信度：来源质量给一点先验，核验后才有资格提高（规则 3.2）
        confidence = round(min(0.45, 0.15 + 0.35 * float(source_quality)), 3)
        basis = (
            f"初始置信度={confidence}：来源质量 {source_quality:.2f} 的先验"
            f"（{cls.basis}）；尚未核验，不能视作事实"
        )
        metadata: Dict[str, Any] = {
            "extraction_method": "rules",
            "section": section_title,
            "section_index": section_index,
            "chunk_index": chunk_index,
            "classification_scores": cls.scores,
            "classification_basis": cls.basis,
            "classification_low_confidence": cls.low_confidence,
            "intended_partition": cls.partition,
            "formulas": formulas,
            "code_blocks": codes,
            "assumptions": assumptions,
            "uncertainties": uncertainties,
            "concepts": concepts,
            "source_content_hash": document.get("content_hash", ""),
        }
        return KnowledgeDraft(
            chunk_id=chunk_id,
            project_id=str(project.get("project_id")),
            document_id=str(document.get("document_id")),
            title=title,
            content=chunk,
            summary=summarize(chunk),
            knowledge_type=cls.knowledge_type,
            partition=Partition.PENDING.value,
            domain=cls.domain,
            topic=topic,
            subtopic=section_title if section_title != topic else "",
            source_id=str(document.get("source_id", "")),
            source_url=str(document.get("location", "")),
            source_title=str(document.get("title", "")),
            source_type=source_type,
            author_or_publisher=str(document.get("publisher", "")),
            published_at=str(document.get("published_at", "")),
            accessed_at=str(document.get("accessed_at") or utcnow_iso()),
            language=language,
            content_hash=content_hash,
            source_quality=float(source_quality),
            confidence=confidence,
            confidence_basis=basis,
            freshness_status=str(document.get("freshness_status") or FreshnessStatus.UNKNOWN.value),
            license_status=str(document.get("license_status") or LicenseStatus.UNKNOWN.value),
            visibility=default_visibility(Partition.PENDING.value),
            metadata=metadata,
        )

    # ------------------------------------------------------------------ #
    def _model_proposals(
        self,
        project: Mapping[str, Any],
        document: Mapping[str, Any],
        text: str,
        topic: str,
    ) -> List[KnowledgeDraft]:
        assert self.model is not None
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "content": {"type": "string"},
                            "summary": {"type": "string"},
                            "knowledge_type": {"type": "string"},
                            "topic": {"type": "string"},
                        },
                        "required": ["title", "content", "knowledge_type"],
                    },
                }
            },
            "required": ["items"],
        }
        system = (
            "你是知识提取助手。只抽取文档中明确出现的定义、事实、原理、流程、公式、"
            "代码、最佳实践、案例、警告、假设、观点与未解决问题。"
            "不得补充文档中没有的内容；不得声称内容已被验证。只输出 JSON。"
        )
        user = (
            f"主题: {topic}\n文档标题: {document.get('title')}\n"
            f"文档内容（截断到 12000 字符）:\n{text[:12000]}"
        )
        response = self.model.complete("extract", system, user, json_schema=schema, max_tokens=2000)
        parsed = response.parsed or {}
        items = parsed.get("items") or []
        if not isinstance(items, list):
            raise ModelError("模型返回的 items 不是数组")
        drafts: List[KnowledgeDraft] = []
        for item in items[:40]:
            content = str(item.get("content") or "").strip()
            if len(content) < self.cfg.min_chunk_chars:
                continue
            title = str(item.get("title") or topic)[:120]
            ktype = str(item.get("knowledge_type") or "fact")
            if ktype not in KnowledgeType.values():
                ktype = KnowledgeType.CONCEPT.value
            content_hash = stable_hash(f"{document.get('document_id')}|model|{content}")
            cls = classification.classify(content, title=title, domain=str(project.get("domain") or ""))
            drafts.append(
                KnowledgeDraft(
                    chunk_id="chunk_" + stable_hash(f"{project.get('project_id')}|model|{content_hash}", 24),
                    project_id=str(project.get("project_id")),
                    document_id=str(document.get("document_id")),
                    title=title,
                    content=content,
                    summary=str(item.get("summary") or summarize(content)),
                    knowledge_type=ktype,
                    partition=Partition.PENDING.value,
                    domain=cls.domain,
                    topic=str(item.get("topic") or topic),
                    subtopic="模型提议",
                    source_id=str(document.get("source_id", "")),
                    source_url=str(document.get("location", "")),
                    source_title=str(document.get("title", "")),
                    source_type=str(document.get("source_type") or SourceType.UNKNOWN.value),
                    author_or_publisher=str(document.get("publisher", "")),
                    published_at=str(document.get("published_at", "")),
                    accessed_at=utcnow_iso(),
                    language=detect_language(content),
                    content_hash=content_hash,
                    confidence=0.2,
                    confidence_basis="模型提议条目：未经外部核验，低于规则提取的置信度",
                    visibility=default_visibility(Partition.PENDING.value),
                    metadata={
                        "extraction_method": "model_proposal",
                        "proposed_by": "model",
                        "model": response.model,
                        "classification_basis": cls.basis,
                    },
                )
            )
        return drafts


__all__ = [
    "ExtractionStats",
    "KnowledgeDraft",
    "KnowledgeExtractor",
    "extract_code_examples",
    "extract_concepts",
    "extract_formulas",
    "identify_assumptions",
    "identify_uncertainties",
]
