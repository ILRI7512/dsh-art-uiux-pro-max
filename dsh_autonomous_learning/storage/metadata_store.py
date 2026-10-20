"""SQLite 元数据存储。

职责（对应规范第三节 MetadataStore / 第十三节目录）：
- 项目、任务、运行轮次、来源、文档、知识片段、核验记录、冲突、重复、
  知识关系、缺口、实践结果、实验、指标、审计、模型调用、定时任务。
- 词元倒排表（供 BM25 关键词检索）。
- 所有写操作走显式列白名单，杜绝 SQL 注入与"野生列"。

数据可靠性约定：
- ``PRAGMA journal_mode=WAL``、``PRAGMA foreign_keys=ON``、``synchronous=NORMAL``；
- 所有连接共享一把可重入锁，MCP 服务器多线程调用安全；
- 结构化字段以 JSON 文本存储，读取时反序列化。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from .tokenizer import BM25Params, expand_query

SCHEMA_VERSION = 1


class StorageError(RuntimeError):
    """存储层错误。"""


# --------------------------------------------------------------------------- #
# 表结构
# --------------------------------------------------------------------------- #
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    project_id        TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    goal              TEXT NOT NULL,
    domain            TEXT NOT NULL DEFAULT 'general_knowledge',
    partitions        TEXT NOT NULL DEFAULT '[]',
    depth             TEXT NOT NULL DEFAULT 'working',
    mode              TEXT NOT NULL DEFAULT 'assisted',
    status            TEXT NOT NULL DEFAULT 'active',
    acceptance_criteria TEXT NOT NULL DEFAULT '[]',
    deliverables      TEXT NOT NULL DEFAULT '[]',
    allowed_sources   TEXT NOT NULL DEFAULT '[]',
    budget            TEXT NOT NULL DEFAULT '{}',
    scope             TEXT NOT NULL DEFAULT '{}',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id         TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,
    title           TEXT NOT NULL,
    objective       TEXT NOT NULL DEFAULT '',
    inputs          TEXT NOT NULL DEFAULT '{}',
    steps           TEXT NOT NULL DEFAULT '[]',
    depends_on      TEXT NOT NULL DEFAULT '[]',
    expected_output TEXT NOT NULL DEFAULT '',
    acceptance      TEXT NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'pending',
    priority        REAL NOT NULL DEFAULT 0.5,
    attempts        INTEGER NOT NULL DEFAULT 0,
    max_retries     INTEGER NOT NULL DEFAULT 3,
    timeout_s       INTEGER NOT NULL DEFAULT 300,
    error           TEXT NOT NULL DEFAULT '',
    result          TEXT NOT NULL DEFAULT '{}',
    iteration       INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT NOT NULL DEFAULT '',
    started_at      TEXT NOT NULL DEFAULT '',
    finished_at     TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_idem
    ON tasks(project_id, idempotency_key) WHERE idempotency_key <> '';

CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    iteration   INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'running',
    summary     TEXT NOT NULL DEFAULT '{}',
    stop_reason TEXT NOT NULL DEFAULT '',
    started_at  TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project_id, started_at);

CREATE TABLE IF NOT EXISTS sources (
    source_id      TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    source_type    TEXT NOT NULL DEFAULT 'unknown',
    location       TEXT NOT NULL DEFAULT '',
    title          TEXT NOT NULL DEFAULT '',
    publisher      TEXT NOT NULL DEFAULT '',
    published_at   TEXT NOT NULL DEFAULT '',
    accessed_at    TEXT NOT NULL,
    license_status TEXT NOT NULL DEFAULT 'unknown',
    quality        REAL NOT NULL DEFAULT 0.5,
    quality_basis  TEXT NOT NULL DEFAULT '',
    freshness_status TEXT NOT NULL DEFAULT 'unknown',
    content_hash   TEXT NOT NULL DEFAULT '',
    fetch_ok       INTEGER NOT NULL DEFAULT 0,
    error          TEXT NOT NULL DEFAULT '',
    metadata       TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sources_project ON sources(project_id);
CREATE INDEX IF NOT EXISTS idx_sources_hash ON sources(content_hash);

CREATE TABLE IF NOT EXISTS documents (
    document_id  TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    source_id    TEXT NOT NULL,
    title        TEXT NOT NULL DEFAULT '',
    doc_type     TEXT NOT NULL DEFAULT 'text',
    language     TEXT NOT NULL DEFAULT 'unknown',
    content_path TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    char_count   INTEGER NOT NULL DEFAULT 0,
    parser       TEXT NOT NULL DEFAULT '',
    parse_status TEXT NOT NULL DEFAULT 'parsed',
    error        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_project ON documents(project_id);
CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id              TEXT PRIMARY KEY,
    project_id            TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    document_id           TEXT NOT NULL DEFAULT '',
    partition             TEXT NOT NULL DEFAULT 'pending_knowledge',
    domain                TEXT NOT NULL DEFAULT 'general',
    topic                 TEXT NOT NULL DEFAULT '',
    subtopic              TEXT NOT NULL DEFAULT '',
    title                 TEXT NOT NULL DEFAULT '',
    content               TEXT NOT NULL DEFAULT '',
    summary               TEXT NOT NULL DEFAULT '',
    knowledge_type        TEXT NOT NULL DEFAULT 'fact',
    status                TEXT NOT NULL DEFAULT 'pending_verification',
    level                 TEXT NOT NULL DEFAULT 'L2',
    source_id             TEXT NOT NULL DEFAULT '',
    source_url            TEXT NOT NULL DEFAULT '',
    source_title          TEXT NOT NULL DEFAULT '',
    source_type           TEXT NOT NULL DEFAULT 'unknown',
    author_or_publisher   TEXT NOT NULL DEFAULT '',
    published_at          TEXT NOT NULL DEFAULT '',
    accessed_at           TEXT NOT NULL DEFAULT '',
    language              TEXT NOT NULL DEFAULT 'unknown',
    content_hash          TEXT NOT NULL DEFAULT '',
    version               INTEGER NOT NULL DEFAULT 1,
    source_quality        REAL NOT NULL DEFAULT 0.5,
    evidence_count        INTEGER NOT NULL DEFAULT 0,
    evidence_independence INTEGER NOT NULL DEFAULT 0,
    confidence            REAL NOT NULL DEFAULT 0.3,
    confidence_basis      TEXT NOT NULL DEFAULT '',
    verification_status   TEXT NOT NULL DEFAULT 'unverified',
    verification_method   TEXT NOT NULL DEFAULT 'none',
    verification_evidence TEXT NOT NULL DEFAULT '[]',
    freshness_status      TEXT NOT NULL DEFAULT 'unknown',
    conflict_status       TEXT NOT NULL DEFAULT 'none',
    limitations           TEXT NOT NULL DEFAULT '',
    license_status        TEXT NOT NULL DEFAULT 'unknown',
    visibility            TEXT NOT NULL DEFAULT 'project',
    metadata              TEXT NOT NULL DEFAULT '{}',
    invalidated_at        TEXT NOT NULL DEFAULT '',
    superseded_by         TEXT NOT NULL DEFAULT '',
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_project ON chunks(project_id, status);
CREATE INDEX IF NOT EXISTS idx_chunks_partition ON chunks(partition);
CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(content_hash);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_domain ON chunks(domain, topic);
CREATE INDEX IF NOT EXISTS idx_chunks_status ON chunks(status, verification_status);

CREATE TABLE IF NOT EXISTS chunk_versions (
    id            TEXT PRIMARY KEY,
    chunk_id      TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    version       INTEGER NOT NULL,
    content_hash  TEXT NOT NULL DEFAULT '',
    content       TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT '',
    change_reason TEXT NOT NULL DEFAULT '',
    changed_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_versions_chunk ON chunk_versions(chunk_id, version);

CREATE TABLE IF NOT EXISTS verification_records (
    record_id  TEXT PRIMARY KEY,
    chunk_id   TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    method     TEXT NOT NULL,
    result     TEXT NOT NULL,
    evidence   TEXT NOT NULL DEFAULT '[]',
    notes      TEXT NOT NULL DEFAULT '',
    verifier   TEXT NOT NULL DEFAULT 'system',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verify_chunk ON verification_records(chunk_id);

CREATE TABLE IF NOT EXISTS conflicts (
    conflict_id TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    chunk_a     TEXT NOT NULL,
    chunk_b     TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'contradiction',
    detail      TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'open',
    evidence    TEXT NOT NULL DEFAULT '[]',
    resolution  TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    resolved_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_conflicts_project ON conflicts(project_id, status);

CREATE TABLE IF NOT EXISTS duplicates (
    dup_id      TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    chunk_a     TEXT NOT NULL,
    chunk_b     TEXT NOT NULL,
    similarity  REAL NOT NULL DEFAULT 0.0,
    reason      TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS edges (
    edge_id    TEXT PRIMARY KEY,
    src_id     TEXT NOT NULL,
    dst_id     TEXT NOT NULL,
    relation   TEXT NOT NULL,
    weight     REAL NOT NULL DEFAULT 1.0,
    metadata   TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_id, relation);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_id, relation);

CREATE TABLE IF NOT EXISTS gaps (
    gap_id     TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    topic      TEXT NOT NULL,
    subtopic   TEXT NOT NULL DEFAULT '',
    level      TEXT NOT NULL DEFAULT 'L0',
    reason     TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'open',
    priority   REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    resolved_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_gaps_project ON gaps(project_id, status);

CREATE TABLE IF NOT EXISTS practice_tasks (
    practice_id  TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    chunk_id     TEXT NOT NULL DEFAULT '',
    kind         TEXT NOT NULL DEFAULT 'formula',
    title        TEXT NOT NULL DEFAULT '',
    spec         TEXT NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT 'created',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS practice_results (
    result_id    TEXT PRIMARY KEY,
    practice_id  TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'created',
    input_data   TEXT NOT NULL DEFAULT '{}',
    environment  TEXT NOT NULL DEFAULT '{}',
    output       TEXT NOT NULL DEFAULT '',
    error        TEXT NOT NULL DEFAULT '',
    exit_code    INTEGER,
    conclusion   TEXT NOT NULL DEFAULT '',
    artifact_dir TEXT NOT NULL DEFAULT '',
    duration_ms  INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_practice_results ON practice_results(practice_id);

CREATE TABLE IF NOT EXISTS experiments (
    experiment_id TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    task_id       TEXT NOT NULL DEFAULT '',
    spec          TEXT NOT NULL DEFAULT '{}',
    result        TEXT NOT NULL DEFAULT '{}',
    status        TEXT NOT NULL DEFAULT 'created',
    artifact_dir  TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS metrics (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL DEFAULT '',
    run_id     TEXT NOT NULL DEFAULT '',
    kind       TEXT NOT NULL,
    name       TEXT NOT NULL,
    value      REAL NOT NULL DEFAULT 0.0,
    metadata   TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_project ON metrics(project_id, kind);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    actor      TEXT NOT NULL DEFAULT 'agent',
    action     TEXT NOT NULL,
    target     TEXT NOT NULL DEFAULT '',
    risk       TEXT NOT NULL DEFAULT 'read',
    allowed    INTEGER NOT NULL DEFAULT 1,
    project_id TEXT NOT NULL DEFAULT '',
    detail     TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);

CREATE TABLE IF NOT EXISTS llm_calls (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                TEXT NOT NULL,
    project_id        TEXT NOT NULL DEFAULT '',
    stage             TEXT NOT NULL DEFAULT '',
    model             TEXT NOT NULL DEFAULT '',
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost_estimate     REAL NOT NULL DEFAULT 0.0,
    ok                INTEGER NOT NULL DEFAULT 1,
    error             TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS schedules (
    schedule_id   TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    kind          TEXT NOT NULL DEFAULT 'interval',
    expression    TEXT NOT NULL DEFAULT '',
    next_run_at   TEXT NOT NULL,
    enabled       INTEGER NOT NULL DEFAULT 1,
    last_run_at   TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);

-- 待用户确认的高风险操作（跨进程持久化：MCP 服务器 / CLI / 宿主审批 UI 共用）
CREATE TABLE IF NOT EXISTS confirmations (
    token      TEXT PRIMARY KEY,
    action     TEXT NOT NULL,
    target     TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    approved_at TEXT NOT NULL DEFAULT '',
    note       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_confirmations_status ON confirmations(status, expires_at);

CREATE TABLE IF NOT EXISTS tokens (
    chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    token    TEXT NOT NULL,
    tf       INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (chunk_id, token)
);
CREATE INDEX IF NOT EXISTS idx_tokens_token ON tokens(token);

CREATE TABLE IF NOT EXISTS chunk_lex (
    chunk_id TEXT PRIMARY KEY REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    length   INTEGER NOT NULL DEFAULT 0
);
"""


# --------------------------------------------------------------------------- #
# 列定义（写入白名单）
# --------------------------------------------------------------------------- #
JSON_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "projects": ("partitions", "acceptance_criteria", "deliverables", "allowed_sources", "budget", "scope"),
    "tasks": ("inputs", "steps", "depends_on", "acceptance", "result"),
    "runs": ("summary",),
    "sources": ("metadata",),
    "documents": (),
    "chunks": ("verification_evidence", "metadata"),
    "verification_records": ("evidence",),
    "conflicts": ("evidence",),
    "duplicates": (),
    "edges": ("metadata",),
    "gaps": (),
    "practice_tasks": ("spec",),
    "practice_results": ("input_data", "environment"),
    "experiments": ("spec", "result"),
    "metrics": ("metadata",),
    "audit_log": ("detail",),
    "chunk_versions": (),
    "llm_calls": (),
    "schedules": (),
}

BOOL_COLUMNS = {
    ("sources", "fetch_ok"),
    ("audit_log", "allowed"),
    ("llm_calls", "ok"),
    ("schedules", "enabled"),
}

COLUMNS: Dict[str, Tuple[str, ...]] = {
    "meta": ("key", "value"),
    "projects": (
        "project_id", "title", "goal", "domain", "partitions", "depth", "mode", "status",
        "acceptance_criteria", "deliverables", "allowed_sources", "budget", "scope",
        "created_at", "updated_at",
    ),
    "tasks": (
        "task_id", "project_id", "kind", "title", "objective", "inputs", "steps",
        "depends_on", "expected_output", "acceptance", "status", "priority", "attempts",
        "max_retries", "timeout_s", "error", "result", "iteration", "idempotency_key",
        "started_at", "finished_at", "created_at", "updated_at",
    ),
    "runs": (
        "run_id", "project_id", "iteration", "status", "summary", "stop_reason",
        "started_at", "finished_at",
    ),
    "sources": (
        "source_id", "project_id", "source_type", "location", "title", "publisher",
        "published_at", "accessed_at", "license_status", "quality", "quality_basis",
        "freshness_status", "content_hash", "fetch_ok", "error", "metadata", "created_at",
    ),
    "documents": (
        "document_id", "project_id", "source_id", "title", "doc_type", "language",
        "content_path", "content_hash", "char_count", "parser", "parse_status", "error",
        "created_at",
    ),
    "chunks": (
        "chunk_id", "project_id", "document_id", "partition", "domain", "topic", "subtopic",
        "title", "content", "summary", "knowledge_type", "status", "level", "source_id",
        "source_url", "source_title", "source_type", "author_or_publisher", "published_at",
        "accessed_at", "language", "content_hash", "version", "source_quality",
        "evidence_count", "evidence_independence", "confidence", "confidence_basis",
        "verification_status", "verification_method", "verification_evidence",
        "freshness_status", "conflict_status", "limitations", "license_status",
        "visibility", "metadata", "invalidated_at", "superseded_by", "created_at",
        "updated_at",
    ),
    "chunk_versions": (
        "id", "chunk_id", "version", "content_hash", "content", "status",
        "change_reason", "changed_at",
    ),
    "verification_records": (
        "record_id", "chunk_id", "method", "result", "evidence", "notes", "verifier",
        "created_at",
    ),
    "conflicts": (
        "conflict_id", "project_id", "chunk_a", "chunk_b", "kind", "detail", "status",
        "evidence", "resolution", "created_at", "resolved_at",
    ),
    "duplicates": (
        "dup_id", "project_id", "chunk_a", "chunk_b", "similarity", "reason", "status",
        "created_at",
    ),
    "edges": ("edge_id", "src_id", "dst_id", "relation", "weight", "metadata", "created_at"),
    "gaps": (
        "gap_id", "project_id", "topic", "subtopic", "level", "reason", "status",
        "priority", "created_at", "resolved_at",
    ),
    "practice_tasks": ("practice_id", "project_id", "chunk_id", "kind", "title", "spec", "status", "created_at"),
    "practice_results": (
        "result_id", "practice_id", "status", "input_data", "environment", "output",
        "error", "exit_code", "conclusion", "artifact_dir", "duration_ms", "created_at",
    ),
    "experiments": (
        "experiment_id", "project_id", "task_id", "spec", "result", "status",
        "artifact_dir", "created_at",
    ),
    "metrics": ("project_id", "run_id", "kind", "name", "value", "metadata", "created_at"),
    "audit_log": ("ts", "actor", "action", "target", "risk", "allowed", "project_id", "detail"),
    "llm_calls": (
        "ts", "project_id", "stage", "model", "prompt_tokens", "completion_tokens",
        "cost_estimate", "ok", "error",
    ),
    "schedules": (
        "schedule_id", "project_id", "kind", "expression", "next_run_at", "enabled",
        "last_run_at", "created_at",
    ),
    "confirmations": (
        "token", "action", "target", "project_id", "status", "created_at",
        "expires_at", "approved_at", "note",
    ),
}

PRIMARY_KEYS = {
    "meta": "key",
    "projects": "project_id",
    "tasks": "task_id",
    "runs": "run_id",
    "sources": "source_id",
    "documents": "document_id",
    "chunks": "chunk_id",
    "chunk_versions": "id",
    "verification_records": "record_id",
    "conflicts": "conflict_id",
    "duplicates": "dup_id",
    "edges": "edge_id",
    "gaps": "gap_id",
    "practice_tasks": "practice_id",
    "practice_results": "result_id",
    "experiments": "experiment_id",
    "schedules": "schedule_id",
    "confirmations": "token",
}


@dataclass
class ChunkFilter:
    """知识检索/统计的元数据过滤条件。"""

    project_id: Optional[str] = None
    project_ids: Optional[Sequence[str]] = None
    partitions: Optional[Sequence[str]] = None
    domains: Optional[Sequence[str]] = None
    topics: Optional[Sequence[str]] = None
    subtopics: Optional[Sequence[str]] = None
    statuses: Optional[Sequence[str]] = None
    levels: Optional[Sequence[str]] = None
    verification_statuses: Optional[Sequence[str]] = None
    knowledge_types: Optional[Sequence[str]] = None
    source_types: Optional[Sequence[str]] = None
    licenses: Optional[Sequence[str]] = None
    freshness: Optional[Sequence[str]] = None
    conflict_statuses: Optional[Sequence[str]] = None
    document_id: Optional[str] = None
    source_id: Optional[str] = None
    visibility: Optional[str] = None
    min_confidence: Optional[float] = None
    min_source_quality: Optional[float] = None
    updated_after: Optional[str] = None
    updated_before: Optional[str] = None
    published_after: Optional[str] = None
    accessed_after: Optional[str] = None

    def to_sql(self, alias: str = "c") -> Tuple[str, List[Any]]:
        clauses: List[str] = []
        args: List[Any] = []
        prefix = f"{alias}." if alias else ""

        def add_in(col: str, values: Optional[Sequence[str]]) -> None:
            if not values:
                return
            cleaned = [v for v in values if v not in (None, "")]
            if not cleaned:
                return
            clauses.append(f"{prefix}{col} IN ({','.join('?' * len(cleaned))})")
            args.extend(cleaned)

        if self.project_id:
            clauses.append(f"{prefix}project_id = ?")
            args.append(self.project_id)
        add_in("project_id", self.project_ids)
        add_in("partition", self.partitions)
        add_in("domain", self.domains)
        add_in("topic", self.topics)
        add_in("subtopic", self.subtopics)
        add_in("status", self.statuses)
        add_in("level", self.levels)
        add_in("verification_status", self.verification_statuses)
        add_in("knowledge_type", self.knowledge_types)
        add_in("source_type", self.source_types)
        add_in("license_status", self.licenses)
        add_in("freshness_status", self.freshness)
        add_in("conflict_status", self.conflict_statuses)
        if self.document_id:
            clauses.append(f"{prefix}document_id = ?")
            args.append(self.document_id)
        if self.source_id:
            clauses.append(f"{prefix}source_id = ?")
            args.append(self.source_id)
        if self.visibility:
            clauses.append(f"{prefix}visibility = ?")
            args.append(self.visibility)
        if self.min_confidence is not None:
            clauses.append(f"{prefix}confidence >= ?")
            args.append(float(self.min_confidence))
        if self.min_source_quality is not None:
            clauses.append(f"{prefix}source_quality >= ?")
            args.append(float(self.min_source_quality))
        if self.updated_after:
            clauses.append(f"{prefix}updated_at >= ?")
            args.append(self.updated_after)
        if self.updated_before:
            clauses.append(f"{prefix}updated_at <= ?")
            args.append(self.updated_before)
        if self.published_after:
            clauses.append(f"{prefix}published_at >= ?")
            args.append(self.published_after)
        if self.accessed_after:
            clauses.append(f"{prefix}accessed_at >= ?")
            args.append(self.accessed_after)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, args

    def describe(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in (None, [], "", False)}


class MetadataStore:
    """线程安全的 SQLite 存储。"""

    def __init__(self, db_path: str | Path, *, timeout: float = 30.0) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._timeout = timeout
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self.connect()

    # ------------------------------------------------------------------ #
    # 连接与事务
    # ------------------------------------------------------------------ #
    def connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is not None:
                return self._conn
            conn = sqlite3.connect(str(self.db_path), timeout=self._timeout, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._conn = conn
            return conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self.connect()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self.connect()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def migrate(self) -> None:
        with self.transaction() as conn:
            conn.executescript(SCHEMA_SQL)
            cur = conn.execute("SELECT value FROM meta WHERE key='schema_version'")
            row = cur.fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES ('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            else:
                found = int(row["value"])
                if found > SCHEMA_VERSION:
                    raise StorageError(
                        f"数据库 schema 版本 {found} 高于代码支持的 {SCHEMA_VERSION}，请升级插件"
                    )

    # ------------------------------------------------------------------ #
    # 通用读写
    # ------------------------------------------------------------------ #
    def _encode(self, table: str, row: Mapping[str, Any]) -> Dict[str, Any]:
        allowed = COLUMNS[table]
        out: Dict[str, Any] = {}
        json_cols = JSON_COLUMNS.get(table, ())
        for key, value in row.items():
            if key not in allowed:
                raise StorageError(f"表 {table} 不存在列 {key}")
            if key in json_cols:
                out[key] = json.dumps(value, ensure_ascii=False)
            elif (table, key) in BOOL_COLUMNS:
                out[key] = 1 if value else 0
            elif value is None:
                out[key] = None
            else:
                out[key] = value
        return out

    def _decode(self, table: str, row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        data = dict(row)
        for col in JSON_COLUMNS.get(table, ()):
            if col in data and isinstance(data[col], (str, bytes)):
                try:
                    data[col] = json.loads(data[col])
                except (json.JSONDecodeError, TypeError):
                    data[col] = None
        for col in {c for t, c in BOOL_COLUMNS if t == table}:
            if col in data and data[col] is not None:
                data[col] = bool(data[col])
        return data

    def insert(self, table: str, row: Mapping[str, Any]) -> Dict[str, Any]:
        if table not in COLUMNS:
            raise StorageError(f"未知表: {table}")
        row = _coerce_row(table, row)
        encoded = self._encode(table, row)
        cols = ", ".join(encoded)
        marks = ", ".join("?" * len(encoded))
        with self.transaction() as conn:
            conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(encoded.values()))
        return dict(row)

    def upsert(self, table: str, row: Mapping[str, Any], key: Optional[str] = None) -> Dict[str, Any]:
        pk = key or PRIMARY_KEYS.get(table)
        if not pk:
            raise StorageError(f"表 {table} 没有主键，无法 upsert")
        row = _coerce_row(table, row)
        encoded = self._encode(table, row)
        cols = ", ".join(encoded)
        marks = ", ".join("?" * len(encoded))
        updates = ", ".join(f"{c}=excluded.{c}" for c in encoded if c != pk)
        with self.transaction() as conn:
            conn.execute(
                f"INSERT INTO {table} ({cols}) VALUES ({marks}) "
                f"ON CONFLICT({pk}) DO UPDATE SET {updates}",
                list(encoded.values()),
            )
        return dict(row)

    def update(self, table: str, id_value: Any, fields: Mapping[str, Any]) -> int:
        if table not in COLUMNS:
            raise StorageError(f"未知表: {table}")
        pk = PRIMARY_KEYS.get(table)
        if not pk:
            raise StorageError(f"表 {table} 没有主键")
        encoded = self._encode(table, fields)
        if not encoded:
            return 0
        assignments = ", ".join(f"{c}=?" for c in encoded)
        with self.transaction() as conn:
            cur = conn.execute(
                f"UPDATE {table} SET {assignments} WHERE {pk}=?",
                [*encoded.values(), id_value],
            )
            return cur.rowcount

    def get(self, table: str, id_value: Any, key: Optional[str] = None) -> Optional[Dict[str, Any]]:
        pk = key or PRIMARY_KEYS.get(table)
        with self._lock:
            cur = self.conn.execute(f"SELECT * FROM {table} WHERE {pk}=?", (id_value,))
            return self._decode(table, cur.fetchone())

    def delete(self, table: str, id_value: Any, key: Optional[str] = None) -> int:
        pk = key or PRIMARY_KEYS.get(table)
        with self.transaction() as conn:
            cur = conn.execute(f"DELETE FROM {table} WHERE {pk}=?", (id_value,))
            return cur.rowcount

    def query(self, sql: str, params: Sequence[Any] = ()) -> List[sqlite3.Row]:
        with self._lock:
            return list(self.conn.execute(sql, params).fetchall())

    def query_dicts(self, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.query(sql, params)]

    def scalar(self, sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        with self._lock:
            row = self.conn.execute(sql, params).fetchone()
        if row is None:
            return default
        return row[0]

    def count(self, table: str, where: str = "", params: Sequence[Any] = ()) -> int:
        sql = f"SELECT COUNT(*) FROM {table}"
        if where:
            sql += f" WHERE {where}"
        return int(self.scalar(sql, params, 0) or 0)

    # ------------------------------------------------------------------ #
    # 项目
    # ------------------------------------------------------------------ #
    def create_project(self, project: Dict[str, Any]) -> Dict[str, Any]:
        self.insert("projects", project)
        return self.get_project(project["project_id"]) or {}

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        return self.get("projects", project_id)

    def update_project(self, project_id: str, fields: Mapping[str, Any]) -> None:
        fields = {**fields, "updated_at": fields.get("updated_at") or _now()}
        self.update("projects", project_id, fields)

    def list_projects(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM projects"
        args: List[Any] = []
        if status:
            sql += " WHERE status=?"
            args.append(status)
        sql += " ORDER BY created_at DESC"
        return [self._decode("projects", r) for r in self.query(sql, args)]  # type: ignore[misc]

    # ------------------------------------------------------------------ #
    # 任务
    # ------------------------------------------------------------------ #
    def create_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self.insert("tasks", task)
        except sqlite3.IntegrityError:
            # 幂等：同项目同幂等键已存在时返回既有任务
            existing = self.query_dicts(
                "SELECT task_id FROM tasks WHERE project_id=? AND idempotency_key=?",
                (task["project_id"], task.get("idempotency_key", "")),
            )
            if existing:
                return self.get_task(existing[0]["task_id"]) or {}
            raise
        return self.get_task(task["task_id"]) or {}

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self.get("tasks", task_id)

    def update_task(self, task_id: str, fields: Mapping[str, Any]) -> None:
        self.update("tasks", task_id, {**fields, "updated_at": fields.get("updated_at") or _now()})

    def list_tasks(
        self, project_id: str, status: Optional[Sequence[str] | str] = None, kind: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM tasks WHERE project_id=?"
        args: List[Any] = [project_id]
        if status:
            statuses = [status] if isinstance(status, str) else list(status)
            sql += f" AND status IN ({','.join('?' * len(statuses))})"
            args.extend(statuses)
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        sql += " ORDER BY priority DESC, created_at ASC"
        return [self._decode("tasks", r) for r in self.query(sql, args)]  # type: ignore[misc]

    def next_ready_tasks(self, project_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """返回依赖已满足的待执行任务。"""

        candidates = self.list_tasks(project_id, status=["pending", "retrying"])
        done = {
            row["task_id"]
            for row in self.query("SELECT task_id FROM tasks WHERE project_id=? AND status='completed'", (project_id,))
        }
        ready = []
        for task in candidates:
            deps = task.get("depends_on") or []
            if all(dep in done for dep in deps):
                ready.append(task)
        ready.sort(key=lambda t: (-float(t.get("priority", 0.5)), t.get("created_at", "")))
        return ready[:limit]

    def task_counts(self, project_id: str) -> Dict[str, int]:
        rows = self.query(
            "SELECT status, COUNT(*) AS n FROM tasks WHERE project_id=? GROUP BY status", (project_id,)
        )
        return {r["status"]: int(r["n"]) for r in rows}

    # ------------------------------------------------------------------ #
    # 运行轮次
    # ------------------------------------------------------------------ #
    def start_run(self, run: Dict[str, Any]) -> Dict[str, Any]:
        self.insert("runs", run)
        return run

    def finish_run(self, run_id: str, status: str, summary: Dict[str, Any], stop_reason: str = "") -> None:
        self.update(
            "runs",
            run_id,
            {
                "status": status,
                "summary": summary,
                "stop_reason": stop_reason,
                "finished_at": _now(),
            },
        )

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        return self.get("runs", run_id)

    def last_runs(self, project_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        rows = self.query(
            "SELECT * FROM runs WHERE project_id=? ORDER BY started_at DESC LIMIT ?", (project_id, limit)
        )
        return [self._decode("runs", r) for r in rows]  # type: ignore[misc]

    def next_iteration(self, project_id: str) -> int:
        value = self.scalar("SELECT MAX(iteration) FROM runs WHERE project_id=?", (project_id,), 0)
        return int(value or 0) + 1

    # ------------------------------------------------------------------ #
    # 知识片段
    # ------------------------------------------------------------------ #
    def insert_chunk(self, chunk: Mapping[str, Any]) -> Dict[str, Any]:
        self.insert("chunks", chunk)
        self._reindex_chunk(chunk)
        return dict(chunk)

    def upsert_chunk(self, chunk: Mapping[str, Any]) -> Dict[str, Any]:
        self.upsert("chunks", chunk)
        self._reindex_chunk(chunk)
        return dict(chunk)

    def update_chunk(self, chunk_id: str, fields: Mapping[str, Any]) -> None:
        fields = {**fields, "updated_at": fields.get("updated_at") or _now()}
        self.update("chunks", chunk_id, fields)
        if {"content", "title", "summary"} & set(fields):
            row = self.get_chunk(chunk_id)
            if row:
                self._reindex_chunk(row)

    def get_chunk(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        return self.get("chunks", chunk_id)

    def get_chunks(self, chunk_ids: Sequence[str]) -> List[Dict[str, Any]]:
        if not chunk_ids:
            return []
        out: List[Dict[str, Any]] = []
        for i in range(0, len(chunk_ids), 400):
            batch = list(chunk_ids[i : i + 400])
            sql = f"SELECT * FROM chunks WHERE chunk_id IN ({','.join('?' * len(batch))})"
            out.extend(self._decode("chunks", r) for r in self.query(sql, batch))  # type: ignore[misc]
        return [c for c in out if c]

    def list_chunks(
        self, filters: Optional[ChunkFilter] = None, limit: int = 100, offset: int = 0
    ) -> List[Dict[str, Any]]:
        where, args = (filters or ChunkFilter()).to_sql("")
        sql = f"SELECT * FROM chunks{where} ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        rows = self.query(sql, [*args, limit, offset])
        return [self._decode("chunks", r) for r in rows]  # type: ignore[misc]

    def list_chunk_ids(self, filters: Optional[ChunkFilter] = None, limit: int = 0) -> List[str]:
        where, args = (filters or ChunkFilter()).to_sql("")
        sql = f"SELECT chunk_id FROM chunks{where}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [r["chunk_id"] for r in self.query(sql, args)]

    def count_chunks(self, filters: Optional[ChunkFilter] = None) -> int:
        where, args = (filters or ChunkFilter()).to_sql("")
        return int(self.scalar(f"SELECT COUNT(*) FROM chunks{where}", args, 0) or 0)

    def find_chunks_by_hash(self, content_hash: str, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM chunks WHERE content_hash=?"
        args: List[Any] = [content_hash]
        if project_id:
            sql += " AND project_id=?"
            args.append(project_id)
        return [self._decode("chunks", r) for r in self.query(sql, args)]  # type: ignore[misc]

    def partition_stats(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = """
            SELECT partition,
                   COUNT(*) AS total,
                   SUM(CASE WHEN verification_status='verified' THEN 1 ELSE 0 END) AS verified,
                   SUM(CASE WHEN status='pending_verification' THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN status='stale' THEN 1 ELSE 0 END) AS stale,
                   SUM(CASE WHEN conflict_status='confirmed' THEN 1 ELSE 0 END) AS conflicted,
                   MAX(updated_at) AS last_updated
              FROM chunks
        """
        args: List[Any] = []
        if project_id:
            sql += " WHERE project_id=?"
            args.append(project_id)
        sql += " GROUP BY partition ORDER BY partition"
        rows = self.query_dicts(sql, args)
        dup_sql = "SELECT COUNT(*) FROM duplicates WHERE status='open'"
        return [
            {
                "partition": r["partition"],
                "total": int(r["total"] or 0),
                "verified": int(r["verified"] or 0),
                "pending_verification": int(r["pending"] or 0),
                "stale": int(r["stale"] or 0),
                "conflicts": int(r["conflicted"] or 0),
                "duplicates": int(self.scalar(dup_sql, (), 0) or 0),
                "last_updated": r["last_updated"] or "",
            }
            for r in rows
        ]

    # ------------------------------------------------------------------ #
    # 词元索引 / BM25
    # ------------------------------------------------------------------ #
    def _reindex_chunk(self, chunk: Mapping[str, Any]) -> None:
        from .tokenizer import term_frequencies, tokenize

        text = "\n".join(
            str(chunk.get(k) or "") for k in ("title", "summary", "content")
        )
        freqs = term_frequencies(text)
        length = len(tokenize(text))
        with self.transaction() as conn:
            conn.execute("DELETE FROM tokens WHERE chunk_id=?", (chunk["chunk_id"],))
            conn.executemany(
                "INSERT OR REPLACE INTO tokens(chunk_id, token, tf) VALUES (?,?,?)",
                [(chunk["chunk_id"], tok, tf) for tok, tf in freqs.items()],
            )
            conn.execute(
                "INSERT OR REPLACE INTO chunk_lex(chunk_id, length) VALUES (?,?)",
                (chunk["chunk_id"], length),
            )

    def delete_chunk(self, chunk_id: str) -> int:
        with self.transaction() as conn:
            conn.execute("DELETE FROM tokens WHERE chunk_id=?", (chunk_id,))
            conn.execute("DELETE FROM chunk_lex WHERE chunk_id=?", (chunk_id,))
        return self.delete("chunks", chunk_id)

    def bm25_search(
        self,
        query: str,
        allowed_ids: Optional[Sequence[str]] = None,
        top_k: int = 20,
        params: BM25Params | None = None,
    ) -> List[Tuple[str, float]]:
        """BM25 关键词检索，返回 [(chunk_id, score)]。"""

        params = params or BM25Params()
        terms = expand_query(query)
        if not terms:
            return []

        with self._lock:
            conn = self.connect()
            conn.execute("CREATE TEMP TABLE IF NOT EXISTS _allow (chunk_id TEXT PRIMARY KEY)")
            conn.execute("DELETE FROM _allow")
            if allowed_ids is not None:
                conn.executemany(
                    "INSERT OR IGNORE INTO _allow(chunk_id) VALUES (?)",
                    [(i,) for i in allowed_ids],
                )
            join = (
                " JOIN _allow a ON a.chunk_id=t.chunk_id" if allowed_ids is not None else ""
            )
            placeholders = ",".join("?" * len(terms))
            rows = conn.execute(
                f"SELECT t.chunk_id, t.token, t.tf FROM tokens t{join} WHERE t.token IN ({placeholders})",
                terms,
            ).fetchall()
            total_docs = int(
                conn.execute(
                    "SELECT COUNT(*) FROM chunk_lex" + (" JOIN _allow a ON a.chunk_id=chunk_lex.chunk_id" if allowed_ids is not None else "")
                ).fetchone()[0]
            )
            avg_len = float(
                conn.execute(
                    "SELECT AVG(length) FROM chunk_lex" + (" JOIN _allow a ON a.chunk_id=chunk_lex.chunk_id" if allowed_ids is not None else "")
                ).fetchone()[0]
                or 0.0
            )
            lengths = {
                r["chunk_id"]: r["length"]
                for r in conn.execute(
                    "SELECT chunk_id, length FROM chunk_lex" + (" JOIN _allow a USING(chunk_id)" if allowed_ids is not None else "")
                ).fetchall()
            }

        if total_docs <= 0 or not rows:
            return []
        freqs: Dict[str, Dict[str, int]] = {}
        for row in rows:
            freqs.setdefault(row["chunk_id"], {})[row["token"]] = int(row["tf"])

        import math

        df = {t: sum(1 for f in freqs.values() if t in f) for t in terms}
        avgdl = avg_len or 1.0
        scored: List[Tuple[str, float]] = []
        for doc_id, doc_freqs in freqs.items():
            dl = lengths.get(doc_id, sum(doc_freqs.values())) or 1
            score = 0.0
            for term in terms:
                tf = doc_freqs.get(term, 0)
                if not tf:
                    continue
                idf = math.log(1 + (total_docs - df[term] + 0.5) / (df[term] + 0.5))
                denom = tf + params.k1 * (1 - params.b + params.b * dl / avgdl)
                score += idf * (tf * (params.k1 + 1)) / denom
            if score > 0:
                scored.append((doc_id, score))
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]

    # ------------------------------------------------------------------ #
    # 核验、冲突、重复、关系、缺口
    # ------------------------------------------------------------------ #
    def add_verification(self, record: Mapping[str, Any]) -> Dict[str, Any]:
        self.insert("verification_records", record)
        return dict(record)

    def list_verifications(self, chunk_id: str) -> List[Dict[str, Any]]:
        rows = self.query(
            "SELECT * FROM verification_records WHERE chunk_id=? ORDER BY created_at ASC", (chunk_id,)
        )
        return [self._decode("verification_records", r) for r in rows]  # type: ignore[misc]

    def add_conflict(self, conflict: Mapping[str, Any]) -> Dict[str, Any]:
        self.insert("conflicts", conflict)
        return dict(conflict)

    def list_conflicts(
        self, project_id: Optional[str] = None, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM conflicts"
        clauses: List[str] = []
        args: List[Any] = []
        if project_id:
            clauses.append("project_id=?")
            args.append(project_id)
        if status:
            clauses.append("status=?")
            args.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC"
        return [self._decode("conflicts", r) for r in self.query(sql, args)]  # type: ignore[misc]

    def add_duplicate(self, dup: Mapping[str, Any]) -> None:
        self.insert("duplicates", dup)

    def list_duplicates(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM duplicates"
        args: List[Any] = []
        if project_id:
            sql += " WHERE project_id=?"
            args.append(project_id)
        sql += " ORDER BY similarity DESC"
        return self.query_dicts(sql, args)

    def add_edge(self, edge: Mapping[str, Any]) -> None:
        self.insert("edges", edge)

    def relations(self, chunk_id: str, direction: str = "both") -> List[Dict[str, Any]]:
        if direction == "out":
            rows = self.query("SELECT * FROM edges WHERE src_id=?", (chunk_id,))
        elif direction == "in":
            rows = self.query("SELECT * FROM edges WHERE dst_id=?", (chunk_id,))
        else:
            rows = self.query("SELECT * FROM edges WHERE src_id=? OR dst_id=?", (chunk_id, chunk_id))
        return [self._decode("edges", r) for r in rows]  # type: ignore[misc]

    def add_gap(self, gap: Mapping[str, Any]) -> Dict[str, Any]:
        existing = self.query_dicts(
            "SELECT * FROM gaps WHERE project_id=? AND topic=? AND subtopic=? AND status='open'",
            (gap["project_id"], gap["topic"], gap.get("subtopic", "")),
        )
        if existing:
            return existing[0]
        self.insert("gaps", gap)
        return dict(gap)

    def list_gaps(self, project_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM gaps WHERE project_id=?"
        args: List[Any] = [project_id]
        if status:
            sql += " AND status=?"
            args.append(status)
        sql += " ORDER BY priority DESC, created_at ASC"
        return self.query_dicts(sql, args)

    def resolve_gap(self, gap_id: str) -> None:
        self.update("gaps", gap_id, {"status": "resolved", "resolved_at": _now()})

    # ------------------------------------------------------------------ #
    # 实践 / 实验
    # ------------------------------------------------------------------ #
    def add_practice(self, practice: Mapping[str, Any]) -> Dict[str, Any]:
        self.insert("practice_tasks", practice)
        return dict(practice)

    def get_practice(self, practice_id: str) -> Optional[Dict[str, Any]]:
        return self.get("practice_tasks", practice_id)

    def add_practice_result(self, result: Mapping[str, Any]) -> Dict[str, Any]:
        self.insert("practice_results", result)
        self.update("practice_tasks", result["practice_id"], {"status": result["status"]})
        return dict(result)

    def list_practice_results(self, practice_id: str) -> List[Dict[str, Any]]:
        rows = self.query(
            "SELECT * FROM practice_results WHERE practice_id=? ORDER BY created_at ASC", (practice_id,)
        )
        return [self._decode("practice_results", r) for r in rows]  # type: ignore[misc]

    def add_experiment(self, experiment: Mapping[str, Any]) -> Dict[str, Any]:
        self.insert("experiments", experiment)
        return dict(experiment)

    # ------------------------------------------------------------------ #
    # 指标 / 审计 / 模型调用
    # ------------------------------------------------------------------ #
    def record_metric(
        self, kind: str, name: str, value: float, project_id: str = "", run_id: str = "", metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        self.insert(
            "metrics",
            {
                "project_id": project_id,
                "run_id": run_id,
                "kind": kind,
                "name": name,
                "value": float(value),
                "metadata": metadata or {},
                "created_at": _now(),
            },
        )

    def metrics_summary(self, project_id: str) -> Dict[str, Dict[str, float]]:
        rows = self.query(
            "SELECT kind, name, SUM(value) AS total, MAX(value) AS peak, COUNT(*) AS n "
            "FROM metrics WHERE project_id=? GROUP BY kind, name",
            (project_id,),
        )
        out: Dict[str, Dict[str, float]] = {}
        for r in rows:
            out.setdefault(r["kind"], {})[r["name"]] = {
                "total": float(r["total"] or 0),
                "peak": float(r["peak"] or 0),
                "count": float(r["n"] or 0),
            }
        return out

    def log_audit(
        self,
        action: str,
        target: str = "",
        risk: str = "read",
        allowed: bool = True,
        project_id: str = "",
        actor: str = "agent",
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.insert(
            "audit_log",
            {
                "ts": _now(),
                "actor": actor,
                "action": action,
                "target": target,
                "risk": risk,
                "allowed": allowed,
                "project_id": project_id,
                "detail": detail or {},
            },
        )

    def list_audit(self, project_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM audit_log"
        args: List[Any] = []
        if project_id:
            sql += " WHERE project_id=?"
            args.append(project_id)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return [self._decode("audit_log", r) for r in self.query(sql, args)]  # type: ignore[misc]

    def log_llm_call(
        self,
        stage: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost: float,
        ok: bool = True,
        error: str = "",
        project_id: str = "",
    ) -> None:
        self.insert(
            "llm_calls",
            {
                "ts": _now(),
                "project_id": project_id,
                "stage": stage,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_estimate": cost,
                "ok": ok,
                "error": error,
            },
        )

    def llm_usage(self, project_id: str = "") -> Dict[str, float]:
        sql = "SELECT COUNT(*) AS n, SUM(prompt_tokens) AS pt, SUM(completion_tokens) AS ct, SUM(cost_estimate) AS cost FROM llm_calls"
        args: List[Any] = []
        if project_id:
            sql += " WHERE project_id=?"
            args.append(project_id)
        row = self.query_dicts(sql, args)[0]
        return {
            "calls": float(row["n"] or 0),
            "prompt_tokens": float(row["pt"] or 0),
            "completion_tokens": float(row["ct"] or 0),
            "cost_estimate": float(row["cost"] or 0.0),
        }

    # ------------------------------------------------------------------ #
    # 定时任务
    # ------------------------------------------------------------------ #
    def upsert_schedule(self, schedule: Mapping[str, Any]) -> Dict[str, Any]:
        self.upsert("schedules", schedule)
        return dict(schedule)

    def list_schedules(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM schedules"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY next_run_at ASC"
        return [self._decode("schedules", r) for r in self.query(sql)]  # type: ignore[misc]

    def due_schedules(self, now_iso: str) -> List[Dict[str, Any]]:
        rows = self.query(
            "SELECT * FROM schedules WHERE enabled=1 AND next_run_at <= ? ORDER BY next_run_at", (now_iso,)
        )
        return [self._decode("schedules", r) for r in rows]  # type: ignore[misc]

    # ------------------------------------------------------------------ #
    # 待确认操作（跨进程持久化）
    # ------------------------------------------------------------------ #
    def add_confirmation(self, row: Mapping[str, Any]) -> Dict[str, Any]:
        self.insert("confirmations", row)
        return dict(row)

    def get_confirmation(self, token: str) -> Optional[Dict[str, Any]]:
        return self.get("confirmations", token)

    def list_confirmations(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM confirmations"
        args: List[Any] = []
        if status:
            sql += " WHERE status=?"
            args.append(status)
        sql += " ORDER BY created_at DESC"
        return [self._decode("confirmations", r) for r in self.query(sql, args)]  # type: ignore[misc]

    def update_confirmation(self, token: str, fields: Mapping[str, Any]) -> int:
        return self.update("confirmations", token, fields)

    # ------------------------------------------------------------------ #
    # 版本
    # ------------------------------------------------------------------ #
    def add_version(self, version_row: Mapping[str, Any]) -> None:
        self.insert("chunk_versions", version_row)

    def list_versions(self, chunk_id: str) -> List[Dict[str, Any]]:
        rows = self.query(
            "SELECT * FROM chunk_versions WHERE chunk_id=? ORDER BY version ASC", (chunk_id,)
        )
        return [self._decode("chunk_versions", r) for r in rows]  # type: ignore[misc]

    def stats(self) -> Dict[str, int]:
        tables = ["projects", "tasks", "sources", "documents", "chunks", "verification_records", "conflicts", "duplicates", "edges", "gaps", "practice_tasks", "experiments", "audit_log"]
        return {t: self.count(t) for t in tables}


def _coerce_row(table: str, row: Any) -> Mapping[str, Any]:
    """允许传 dataclass 实体（带 to_row）或普通映射。"""

    if isinstance(row, Mapping):
        return row
    to_row = getattr(row, "to_row", None)
    if callable(to_row):
        return to_row()
    raise StorageError(f"表 {table} 的行数据必须是 Mapping 或带 to_row() 的实体，收到 {type(row).__name__}")


def _now() -> str:
    from ..core.models import utcnow_iso

    return utcnow_iso()


__all__ = [
    "BOOL_COLUMNS",
    "COLUMNS",
    "ChunkFilter",
    "JSON_COLUMNS",
    "MetadataStore",
    "PRIMARY_KEYS",
    "SCHEMA_SQL",
    "SCHEMA_VERSION",
    "StorageError",
]
