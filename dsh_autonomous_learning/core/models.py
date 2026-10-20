"""核心数据模型：枚举、实体与工具函数。

约定：
- 时间统一使用 UTC ISO8601（带时区），对外展示可再本地化。
- 主键使用 ``<前缀>_<32位十六进制>``，便于日志定位与人工阅读。
- 枚举以字符串落库，读取时校验，避免数据库里出现"野生状态"。
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(16)}"


def stable_hash(text: str, n: int = 64) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:n]


def normalize_text(text: str) -> str:
    """归一化文本用于指纹/关键词：小写、压缩空白、去零宽字符。"""

    text = (text or "").replace("\u200b", "").replace("\ufeff", "")
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def content_fingerprint(text: str) -> str:
    return stable_hash(normalize_text(text))


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# --------------------------------------------------------------------------- #
# 枚举
# --------------------------------------------------------------------------- #
class StrEnum(str, Enum):
    """字符串枚举基类。"""

    @classmethod
    def values(cls) -> List[str]:
        return [m.value for m in cls]

    @classmethod
    def parse(cls, value: Any, name: str = "") -> "StrEnum":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except ValueError as exc:
            label = name or cls.__name__
            raise ValueError(
                f"{label} 取值非法: {value!r}，允许值: {', '.join(cls.values())}"
            ) from exc


class KnowledgeStatus(StrEnum):
    DISCOVERED = "discovered"
    EXTRACTED = "extracted"
    PENDING_VERIFICATION = "pending_verification"
    VERIFIED = "verified"
    PRACTICED = "practiced"
    EVALUATED = "evaluated"
    STALE = "stale"
    DISPUTED = "disputed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class LearningLevel(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"


class KnowledgeType(StrEnum):
    DEFINITION = "definition"
    FACT = "fact"
    CONCEPT = "concept"
    PRINCIPLE = "principle"
    PROCEDURE = "procedure"
    FORMULA = "formula"
    CODE_EXAMPLE = "code_example"
    BEST_PRACTICE = "best_practice"
    CASE_STUDY = "case_study"
    HYPOTHESIS = "hypothesis"
    OPINION = "opinion"
    WARNING = "warning"
    UNRESOLVED_QUESTION = "unresolved_question"
    EXPERIMENTAL_RESULT = "experimental_result"


class Partition(StrEnum):
    GENERAL = "general_knowledge"
    UIUX = "uiux_knowledge"
    FINANCE = "finance_knowledge"
    QUANT = "quant_knowledge"
    PROGRAMMING = "programming_knowledge"
    PROJECT = "project_knowledge"
    EXPERIMENT = "experiment_knowledge"
    PENDING = "pending_knowledge"


class TaskKind(StrEnum):
    PLAN = "plan"
    GAP_ANALYSIS = "gap_analysis"
    DISCOVER = "discover"
    READ = "read"
    EXTRACT = "extract"
    VERIFY = "verify"
    PRACTICE = "practice"
    EVALUATE = "evaluate"
    REPORT = "report"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"
    RETRYING = "retrying"


TERMINAL_TASK_STATUSES = {
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
}


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class AutonomyMode(StrEnum):
    ASSISTED = "assisted"
    AUTO = "auto"
    LAB = "lab"


class RiskLevel(StrEnum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    EXTERNAL = "external"
    DESTRUCTIVE = "destructive"


class SourceType(StrEnum):
    OFFICIAL_DOC = "official_doc"
    STANDARD = "standard"
    PAPER = "paper"
    TECH_DOC = "tech_doc"
    CODE_REPO = "code_repo"
    WEB_PAGE = "web_page"
    LOCAL_FILE = "local_file"
    USER_NOTE = "user_note"
    EXPERIMENT = "experiment"
    UNKNOWN = "unknown"


class VerificationMethod(StrEnum):
    SOURCE_CHECK = "source_check"
    CROSS_SOURCE = "cross_source"
    OFFICIAL_DOC_CHECK = "official_doc_check"
    FORMULA_RECOMPUTE = "formula_recompute"
    CODE_TEST = "code_test"
    EXPERIMENT = "experiment"
    USABILITY_TEST = "usability_test"
    STATIC_ANALYSIS = "static_analysis"
    MANUAL_REVIEW = "manual_review"
    NONE = "none"


class VerificationResult(StrEnum):
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


class FreshnessStatus(StrEnum):
    UNKNOWN = "unknown"
    FRESH = "fresh"
    AGING = "aging"
    STALE = "stale"
    EXPIRED = "expired"


class LicenseStatus(StrEnum):
    UNKNOWN = "unknown"
    PERMITTED = "permitted"
    RESTRICTED = "restricted"
    PROHIBITED = "prohibited"


class RelationType(StrEnum):
    DEPENDS_ON = "depends_on"
    INCLUDES = "includes"
    SIMILAR_TO = "similar_to"
    CONFLICTS_WITH = "conflicts_with"
    CITES = "cites"
    SUPERSEDES = "supersedes"
    DERIVED_FROM = "derived_from"
    APPLIES_TO = "applies_to"


class ConflictStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    ACCEPTED_AS_DISPUTE = "accepted_as_dispute"


class GapStatus(StrEnum):
    OPEN = "open"
    PLANNED = "planned"
    RESOLVED = "resolved"
    WONT_FIX = "wont_fix"


class PracticeStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


# --------------------------------------------------------------------------- #
# 实体
# --------------------------------------------------------------------------- #
@dataclass
class Project:
    project_id: str
    title: str
    goal: str
    domain: str = "general_knowledge"
    partitions: List[str] = field(default_factory=lambda: [Partition.GENERAL.value])
    depth: str = "working"  # overview | working | deep
    mode: str = AutonomyMode.ASSISTED.value
    status: str = ProjectStatus.ACTIVE.value
    acceptance_criteria: List[str] = field(default_factory=list)
    deliverables: List[str] = field(default_factory=list)
    allowed_sources: List[str] = field(default_factory=list)
    budget: Dict[str, Any] = field(default_factory=dict)
    scope: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)

    def to_row(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Task:
    task_id: str
    project_id: str
    kind: str
    title: str
    objective: str = ""
    inputs: Dict[str, Any] = field(default_factory=dict)
    steps: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)
    expected_output: str = ""
    acceptance: List[str] = field(default_factory=list)
    status: str = TaskStatus.PENDING.value
    priority: float = 0.5
    attempts: int = 0
    max_retries: int = 3
    timeout_s: int = 300
    error: str = ""
    result: Dict[str, Any] = field(default_factory=dict)
    iteration: int = 0
    idempotency_key: str = ""
    started_at: str = ""
    finished_at: str = ""
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)

    def to_row(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Source:
    source_id: str
    project_id: str
    source_type: str = SourceType.UNKNOWN.value
    location: str = ""  # URL 或本地路径
    title: str = ""
    publisher: str = ""
    published_at: str = ""
    accessed_at: str = field(default_factory=utcnow_iso)
    license_status: str = LicenseStatus.UNKNOWN.value
    quality: float = 0.5
    quality_basis: str = ""
    freshness_status: str = FreshnessStatus.UNKNOWN.value
    content_hash: str = ""
    fetch_ok: bool = False
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow_iso)

    def to_row(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Document:
    document_id: str
    project_id: str
    source_id: str
    title: str = ""
    doc_type: str = "text"
    language: str = "unknown"
    content_path: str = ""
    content_hash: str = ""
    char_count: int = 0
    parser: str = ""
    parse_status: str = "parsed"
    error: str = ""
    created_at: str = field(default_factory=utcnow_iso)

    def to_row(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Chunk:
    """知识片段：向量库中的最小可检索单元。

    处理状态（status/level）与可靠性属性（source_quality/evidence_count 等）
    是两个独立维度，禁止合并成单一分数（规则 3）。
    """

    chunk_id: str
    project_id: str
    document_id: str
    partition: str = Partition.PENDING.value
    domain: str = "general"
    topic: str = ""
    subtopic: str = ""
    title: str = ""
    content: str = ""
    summary: str = ""
    knowledge_type: str = KnowledgeType.FACT.value
    status: str = KnowledgeStatus.PENDING_VERIFICATION.value
    level: str = LearningLevel.L2.value
    source_id: str = ""
    source_url: str = ""
    source_title: str = ""
    source_type: str = SourceType.UNKNOWN.value
    author_or_publisher: str = ""
    published_at: str = ""
    accessed_at: str = ""
    language: str = "unknown"
    content_hash: str = ""
    version: int = 1
    source_quality: float = 0.5
    evidence_count: int = 0
    evidence_independence: int = 0
    confidence: float = 0.3
    confidence_basis: str = ""
    verification_status: str = "unverified"  # unverified | partial | verified | disputed | rejected
    verification_method: str = VerificationMethod.NONE.value
    verification_evidence: List[Dict[str, Any]] = field(default_factory=list)
    freshness_status: str = FreshnessStatus.UNKNOWN.value
    conflict_status: str = "none"  # none | potential | confirmed
    limitations: str = ""
    license_status: str = LicenseStatus.UNKNOWN.value
    visibility: str = "project"  # project | global
    metadata: Dict[str, Any] = field(default_factory=dict)
    invalidated_at: str = ""
    superseded_by: str = ""
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)

    def to_row(self) -> Dict[str, Any]:
        return asdict(self)

    def searchable_text(self) -> str:
        return "\n".join(x for x in (self.title, self.summary, self.content) if x)


@dataclass
class VerificationRecord:
    record_id: str
    chunk_id: str
    method: str
    result: str
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    notes: str = ""
    verifier: str = "system"  # system | model | user
    created_at: str = field(default_factory=utcnow_iso)

    def to_row(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Conflict:
    conflict_id: str
    project_id: str
    chunk_a: str
    chunk_b: str
    kind: str = "contradiction"
    detail: str = ""
    status: str = ConflictStatus.OPEN.value
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    resolution: str = ""
    created_at: str = field(default_factory=utcnow_iso)
    resolved_at: str = ""

    def to_row(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class KnowledgeEdge:
    edge_id: str
    src_id: str
    dst_id: str
    relation: str
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow_iso)

    def to_row(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Gap:
    gap_id: str
    project_id: str
    topic: str
    subtopic: str = ""
    level: str = LearningLevel.L0.value
    reason: str = ""
    status: str = GapStatus.OPEN.value
    priority: float = 0.5
    created_at: str = field(default_factory=utcnow_iso)
    resolved_at: str = ""

    def to_row(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Run:
    run_id: str
    project_id: str
    iteration: int = 0
    status: str = RunStatus.RUNNING.value
    summary: Dict[str, Any] = field(default_factory=dict)
    stop_reason: str = ""
    started_at: str = field(default_factory=utcnow_iso)
    finished_at: str = ""

    def to_row(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PracticeResult:
    result_id: str
    practice_id: str
    status: str = PracticeStatus.CREATED.value
    input_data: Dict[str, Any] = field(default_factory=dict)
    environment: Dict[str, Any] = field(default_factory=dict)
    output: str = ""
    error: str = ""
    exit_code: Optional[int] = None
    conclusion: str = ""
    artifact_dir: str = ""
    duration_ms: int = 0
    created_at: str = field(default_factory=utcnow_iso)

    def to_row(self) -> Dict[str, Any]:
        return asdict(self)


def ensure_enum(value: Any, enum_cls: type, field_name: str) -> str:
    """校验枚举取值并返回字符串，用于工具入参校验。"""

    try:
        return enum_cls.parse(value, field_name).value  # type: ignore[attr-defined]
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


def parse_str_list(value: Any, field_name: str) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Iterable):
        out: List[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(f"{field_name} 必须是字符串数组")
            if item.strip():
                out.append(item.strip())
        return out
    raise ValueError(f"{field_name} 必须是字符串或字符串数组")


__all__ = [name for name in dir() if not name.startswith("_")]
