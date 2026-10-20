"""第三组/第五组工具：资料检索与知识库管理。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ..core.models import KnowledgeStatus, new_id
from ..core.orchestrator import LearningOrchestrator, Runtime
from ..knowledge.partitions import describe_partitions
from ..sources import metadata as source_meta
from ..sources import parser as parsing
from ..sources.discovery import normalize_url
from ..storage.metadata_store import ChunkFilter
from .registry import ToolError, ToolRegistry, ToolSpec


def _require(
    rt: Runtime,
    args: Mapping[str, Any],
    *,
    action: str,
    risk: str,
    target: str = "",
    project_id: str = "",
    content: str = "",
) -> None:
    decision = rt.permissions.decide(
        action=action,
        risk=risk,
        target=target,
        project_id=project_id,
        confirmed_token=str(args.get("confirm_token") or ""),
        content=content,
    )
    if decision.allowed and not decision.needs_confirmation:
        return
    if decision.needs_confirmation and not args.get("confirm_token"):
        request = rt.permissions.request_confirmation(action, target, project_id)
        raise ToolError(
            f"该操作需要用户确认：{action}。确认方式二选一："
            f"(1) 在 DSH 审批界面批准该工具调用（宿主开启 delegate_approval_to_host 时自动生效）；"
            f"(2) 由用户运行 `python -m dsh_autonomous_learning.main confirmations approve {request.token}`，"
            f"再把该 token 作为 confirm_token 重试。",
            "ConfirmationRequired",
        )
    if not decision.allowed:
        raise PermissionError(decision.reason)


def register(reg: ToolRegistry, rt: Runtime, orch: LearningOrchestrator) -> None:
    # ------------------------------------------------------------------ #
    # 资料发现与读取
    # ------------------------------------------------------------------ #
    def discover_sources(args: Dict[str, Any]) -> Dict[str, Any]:
        project_id = args.get("project_id")
        project = rt.metadata.get_project(project_id) if project_id else None
        locations = list(args.get("locations") or (project or {}).get("allowed_sources") or [])
        result = rt.discovery.discover(
            topics=list(args.get("topics") or []),
            explicit_locations=locations,
            include_corpus=bool(args.get("include_corpus", True)),
            keywords=list(args.get("keywords") or []),
            limit=int(args.get("limit", 20)),
        )
        result["project_id"] = project_id or ""
        result["note"] = (
            "这里只做发现与去重，不抓取内容；确认候选后调用 read_source 读取，"
            "或直接运行 run_learning_round 由编排器按预算抓取。"
        )
        return result

    reg.register(
        ToolSpec(
            name="discover_sources",
            description="发现候选资料：显式 URL/路径 + 本地语料目录 + （可选）注入的搜索通道，自动去重并给出质量先验。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "locations": {"type": "array", "items": {"type": "string"}, "description": "URL 或本地路径/目录"},
                    "topics": {"type": "array", "items": {"type": "string"}},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "include_corpus": {"type": "boolean", "description": "是否扫描本地语料目录（默认 true）"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
            },
            handler=discover_sources,
            group="source",
        )
    )

    def search_sources(args: Dict[str, Any]) -> Dict[str, Any]:
        sql = "SELECT * FROM sources WHERE 1=1"
        params: List[Any] = []
        if args.get("project_id"):
            sql += " AND project_id=?"
            params.append(args["project_id"])
        if args.get("query"):
            sql += " AND (title LIKE ? OR location LIKE ? OR publisher LIKE ?)"
            like = f"%{args['query']}%"
            params.extend([like, like, like])
        if args.get("source_type"):
            sql += " AND source_type=?"
            params.append(args["source_type"])
        if args.get("fetch_ok") is not None:
            sql += " AND fetch_ok=?"
            params.append(1 if args["fetch_ok"] else 0)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(int(args.get("limit", 20)))
        rows = rt.metadata.query_dicts(sql, params)
        return {
            "sources": [
                {
                    "source_id": r["source_id"],
                    "title": r["title"],
                    "location": r["location"],
                    "source_type": r["source_type"],
                    "quality": r["quality"],
                    "license_status": r["license_status"],
                    "freshness_status": r["freshness_status"],
                    "fetch_ok": bool(r["fetch_ok"]),
                    "error": r["error"],
                }
                for r in rows
            ],
            "count": len(rows),
        }

    reg.register(
        ToolSpec(
            name="search_sources",
            description="在已登记来源中检索（标题/地址/发布机构），可按类型与抓取状态过滤。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "query": {"type": "string"},
                    "source_type": {
                        "type": "string",
                        "enum": ["official_doc", "standard", "paper", "tech_doc", "code_repo", "web_page", "local_file", "user_note", "experiment", "unknown"],
                    },
                    "fetch_ok": {"type": "boolean"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
            },
            handler=search_sources,
            group="source",
        )
    )

    def read_source(args: Dict[str, Any]) -> Dict[str, Any]:
        location = args["location"]
        project_id = str(args.get("project_id") or "")
        result = rt.reader.read(location, project_id=project_id, confirm_token=str(args.get("confirm_token") or ""))
        if not result.ok:
            raise ToolError(result.error, "ReadError")
        data = result.to_dict()
        if args.get("persist") and project_id:
            saved = orch.ingest_document(project_id, result, topic=str(args.get("topic") or ""))
            data["persisted"] = saved
        return data

    reg.register(
        ToolSpec(
            name="read_source",
            description="读取资料（本地文件或网页），返回正文、类型、来源元数据与内容指纹；可选落库为文档供后续提取。",
            input_schema={
                "type": "object",
                "properties": {
                    "location": {"type": "string"},
                    "project_id": {"type": "string"},
                    "topic": {"type": "string"},
                    "persist": {"type": "boolean", "description": "是否写入 sources/documents 表"},
                    "confirm_token": {"type": "string"},
                },
                "required": ["location"],
            },
            handler=read_source,
            risk="read",
            side_effects="persist=true 时写入 sources/documents",
            group="source",
        )
    )

    def parse_document(args: Dict[str, Any]) -> Dict[str, Any]:
        text = args.get("text")
        title = args.get("title", "")
        if not text:
            if not args.get("location"):
                raise ToolError("必须提供 text 或 location")
            read = rt.reader.read(args["location"], project_id=str(args.get("project_id") or ""))
            if not read.ok:
                raise ToolError(read.error, "ReadError")
            text = read.text
            title = title or read.title
        sections = parsing.split_sections(text)
        chunks = parsing.chunk_text(
            text,
            chunk_size=rt.config.learning.chunk_size,
            overlap=rt.config.learning.chunk_overlap,
            min_chars=rt.config.learning.min_chunk_chars,
            max_chunks=rt.config.learning.max_chunks_per_document,
        )
        return {
            "title": title,
            "language": parsing.detect_language(text),
            "char_count": len(text),
            "section_count": len(sections),
            "sections": [
                {"heading": s.heading, "level": s.level, "chars": len(s.text)} for s in sections[:50]
            ],
            "chunk_count": len(chunks),
            "chunks_preview": [c[:200] for c in chunks[:5]],
            "code_blocks": len(parsing.extract_code_blocks(text)),
            "summary": parsing.summarize(text, 300),
        }

    reg.register(
        ToolSpec(
            name="parse_document",
            description="解析文档结构：章节、语言、切块数量与预览（不写入知识库）。",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "location": {"type": "string"},
                    "project_id": {"type": "string"},
                    "title": {"type": "string"},
                },
            },
            handler=parse_document,
            group="source",
        )
    )

    reg.register(
        ToolSpec(
            name="extract_code_examples",
            description="从文本中提取代码块（语言 + 代码），用于后续受限执行或静态审查。",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=lambda args: {"code_blocks": parsing.extract_code_blocks(args["text"])},
            group="source",
        )
    )

    reg.register(
        ToolSpec(
            name="get_source_metadata",
            description="根据 URL/路径与发布时间，生成来源类型、质量先验、许可与时效判定（附依据）。",
            input_schema={
                "type": "object",
                "properties": {
                    "location": {"type": "string"},
                    "title": {"type": "string"},
                    "published_at": {"type": "string", "description": "ISO8601 或 YYYY-MM-DD"},
                    "doc_type": {"type": "string"},
                },
                "required": ["location"],
            },
            handler=lambda args: source_meta.describe_source(
                args["location"],
                title=args.get("title", ""),
                published_at=args.get("published_at", ""),
                doc_type=args.get("doc_type", ""),
            ),
            group="source",
        )
    )

    reg.register(
        ToolSpec(
            name="check_source_freshness",
            description="判断资料的时效状态（fresh/aging/stale/expired/unknown）并给出依据。",
            input_schema={
                "type": "object",
                "properties": {
                    "published_at": {"type": "string"},
                    "source_type": {"type": "string"},
                },
                "required": ["published_at"],
            },
            handler=lambda args: dict(
                zip(
                    ("freshness_status", "basis"),
                    source_meta.freshness_status(args["published_at"], args.get("source_type", "unknown")),
                )
            ),
            group="source",
        )
    )

    reg.register(
        ToolSpec(
            name="check_source_license",
            description="给出资料的使用许可判定与说明（未知就明确说未知，不做乐观假设）。",
            input_schema={
                "type": "object",
                "properties": {"location": {"type": "string"}, "source_type": {"type": "string"}},
                "required": ["location"],
            },
            handler=lambda args: dict(
                zip(("license_status", "note"), source_meta.guess_license(args["location"], args.get("source_type", "")))
            ),
            group="source",
        )
    )

    # ------------------------------------------------------------------ #
    # 知识入库与检索
    # ------------------------------------------------------------------ #
    def save_knowledge(args: Dict[str, Any]) -> Dict[str, Any]:
        items = args.get("items") or []
        if not items and args.get("content"):
            items = [
                {
                    "content": args["content"],
                    "title": args.get("title", ""),
                    "topic": args.get("topic", ""),
                    "source_url": args.get("source_url", ""),
                }
            ]
        if not items:
            raise ToolError("必须提供 items 数组或单条 content")
        return orch.save_knowledge(args["project_id"], items)

    reg.register(
        ToolSpec(
            name="save_knowledge",
            description="保存知识到知识库（默认落待审分区，状态 pending_verification，未核验前不会被视为事实）。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "content": {"type": "string"},
                                "summary": {"type": "string"},
                                "knowledge_type": {"type": "string"},
                                "partition": {"type": "string"},
                                "domain": {"type": "string"},
                                "topic": {"type": "string"},
                                "source_url": {"type": "string"},
                                "source_title": {"type": "string"},
                                "source_type": {"type": "string"},
                                "published_at": {"type": "string"},
                            },
                            "required": ["content"],
                        },
                    },
                    "content": {"type": "string"},
                    "title": {"type": "string"},
                    "topic": {"type": "string"},
                    "source_url": {"type": "string"},
                },
                "required": ["project_id"],
            },
            handler=save_knowledge,
            risk="write",
            side_effects="写入 chunks 与向量索引",
            group="knowledge",
        )
    )

    def search_knowledge(args: Dict[str, Any]) -> Dict[str, Any]:
        filters = ChunkFilter(
            project_id=args.get("project_id") or None,
            partitions=args.get("partitions"),
            domains=args.get("domains"),
            topics=args.get("topics"),
            statuses=args.get("statuses"),
            verification_statuses=args.get("verification_statuses"),
            knowledge_types=args.get("knowledge_types"),
            source_types=args.get("source_types"),
            min_confidence=args.get("min_confidence"),
            updated_after=args.get("updated_after"),
        )
        if args.get("include_global") and args.get("project_id"):
            filters.visibility = None  # 由 store 的 project/global 规则处理
        return rt.store.search(
            args["query"],
            filters,
            top_k=int(args.get("top_k", rt.config.retrieval.top_k)),
            mode=args.get("mode"),
            include_content=bool(args.get("include_content", True)),
        )

    reg.register(
        ToolSpec(
            name="search_knowledge",
            description="语义+关键词混合检索知识库；返回来源、核验状态、冲突与时效提示（相似不等于正确）。",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "project_id": {"type": "string"},
                    "partitions": {"type": "array", "items": {"type": "string"}},
                    "domains": {"type": "array", "items": {"type": "string"}},
                    "topics": {"type": "array", "items": {"type": "string"}},
                    "statuses": {"type": "array", "items": {"type": "string"}},
                    "verification_statuses": {"type": "array", "items": {"type": "string"}},
                    "knowledge_types": {"type": "array", "items": {"type": "string"}},
                    "source_types": {"type": "array", "items": {"type": "string"}},
                    "min_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "updated_after": {"type": "string"},
                    "include_content": {"type": "boolean"},
                    "include_global": {"type": "boolean"},
                    "mode": {"type": "string", "enum": ["hybrid", "vector", "keyword"]},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["query"],
            },
            handler=search_knowledge,
            group="knowledge",
        )
    )

    def keyword_search(args: Dict[str, Any]) -> Dict[str, Any]:
        allowed: Optional[List[str]] = None
        if args.get("project_id"):
            allowed = rt.metadata.list_chunk_ids(ChunkFilter(project_id=args["project_id"]))
        hits = rt.metadata.bm25_search(args["query"], allowed, top_k=int(args.get("top_k", 10)))
        chunks = {c["chunk_id"]: c for c in rt.metadata.get_chunks([h[0] for h in hits])}
        return {
            "query": args["query"],
            "results": [
                {
                    "chunk_id": cid,
                    "score": round(score, 4),
                    "title": chunks.get(cid, {}).get("title", ""),
                    "summary": chunks.get(cid, {}).get("summary", ""),
                    "status": chunks.get(cid, {}).get("status", ""),
                    "verification_status": chunks.get(cid, {}).get("verification_status", ""),
                }
                for cid, score in hits
                if cid in chunks
            ],
        }

    reg.register(
        ToolSpec(
            name="search_knowledge_by_keyword",
            description="纯关键词检索（BM25 倒排表），不依赖向量，适合精确术语与代码符号。",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "project_id": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["query"],
            },
            handler=keyword_search,
            group="knowledge",
        )
    )

    def update_knowledge(args: Dict[str, Any]) -> Dict[str, Any]:
        project_id = str(args.get("project_id") or "")
        _require(
            rt,
            args,
            action="update_knowledge",
            risk="write",
            target=args["chunk_id"],
            project_id=project_id,
            content=str(args.get("content") or ""),
        )
        result = rt.versions.update(
            args["chunk_id"],
            content=args.get("content"),
            fields=args.get("fields"),
            reason=str(args.get("reason") or "manual_update"),
        )
        return result

    reg.register(
        ToolSpec(
            name="update_knowledge",
            description="更新知识内容/元数据：保留旧版本快照，内容变化会重置核验状态与置信度。",
            input_schema={
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "string"},
                    "content": {"type": "string"},
                    "fields": {"type": "object"},
                    "reason": {"type": "string"},
                    "project_id": {"type": "string"},
                    "confirm_token": {"type": "string"},
                },
                "required": ["chunk_id"],
            },
            handler=update_knowledge,
            risk="write",
            side_effects="写入 chunk_versions 并更新 chunks/向量",
            group="knowledge",
        )
    )

    def invalidate_knowledge(args: Dict[str, Any]) -> Dict[str, Any]:
        _require(
            rt,
            args,
            action="invalidate_knowledge",
            risk="destructive",
            target=args["chunk_id"],
            project_id=str(args.get("project_id") or ""),
        )
        return rt.store.invalidate_document(
            args["chunk_id"],
            reason=str(args.get("reason") or ""),
            superseded_by=str(args.get("superseded_by") or ""),
        )

    reg.register(
        ToolSpec(
            name="invalidate_knowledge",
            description="把知识标记为过时/失效或已被替代（不物理删除，保留审计与历史）。",
            input_schema={
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "string"},
                    "reason": {"type": "string"},
                    "superseded_by": {"type": "string"},
                    "project_id": {"type": "string"},
                    "confirm_token": {"type": "string"},
                },
                "required": ["chunk_id"],
            },
            handler=invalidate_knowledge,
            risk="destructive",
            side_effects="更新 chunks.status/freshness_status",
            requires_confirmation=True,
            group="knowledge",
        )
    )

    reg.register(
        ToolSpec(
            name="find_duplicate_knowledge",
            description="查找完全重复与近似重复知识并登记（不自动删除，避免误合并）。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "chunk_id": {"type": "string"},
                    "threshold": {"type": "number", "minimum": 0.5, "maximum": 1.0},
                },
            },
            handler=lambda args: rt.dedup.find_and_record(
                chunk_id=args.get("chunk_id"),
                project_id=args.get("project_id"),
                threshold=args.get("threshold"),
            ),
            risk="write",
            side_effects="写入 duplicates 表",
            group="knowledge",
        )
    )

    def details(args: Dict[str, Any]) -> Dict[str, Any]:
        chunk = rt.store.get_by_id(args["chunk_id"])
        if not chunk:
            raise ToolError(f"知识片段不存在: {args['chunk_id']}", "NotFound")
        return chunk

    reg.register(
        ToolSpec(
            name="get_knowledge_details",
            description="获取知识完整详情：内容、状态、可靠性属性、核验记录、版本与关系。",
            input_schema={
                "type": "object",
                "properties": {"chunk_id": {"type": "string"}},
                "required": ["chunk_id"],
            },
            handler=details,
            group="knowledge",
        )
    )

    def sources_of(args: Dict[str, Any]) -> Dict[str, Any]:
        chunk = rt.metadata.get_chunk(args["chunk_id"])
        if not chunk:
            raise ToolError(f"知识片段不存在: {args['chunk_id']}", "NotFound")
        source = rt.metadata.get("sources", chunk.get("source_id") or "") if chunk.get("source_id") else None
        return {
            "chunk_id": args["chunk_id"],
            "source": source,
            "verification_records": rt.metadata.list_verifications(args["chunk_id"]),
            "source_quality": chunk.get("source_quality"),
            "evidence_count": chunk.get("evidence_count"),
            "evidence_independence": chunk.get("evidence_independence"),
        }

    reg.register(
        ToolSpec(
            name="get_knowledge_sources",
            description="查询知识条目的来源与全部核验证据（可追溯性的入口）。",
            input_schema={
                "type": "object",
                "properties": {"chunk_id": {"type": "string"}},
                "required": ["chunk_id"],
            },
            handler=sources_of,
            group="knowledge",
        )
    )

    def relations(args: Dict[str, Any]) -> Dict[str, Any]:
        depth = int(args.get("depth", 1))
        if depth <= 1:
            return {
                "chunk_id": args["chunk_id"],
                "neighbors": rt.graph.neighbors(
                    args["chunk_id"], relation=args.get("relation"), direction=args.get("direction", "both")
                ),
            }
        return rt.graph.subgraph(args["chunk_id"], depth=depth)

    reg.register(
        ToolSpec(
            name="get_knowledge_relations",
            description="获取知识关系：一跳邻居，或 depth>=2 时的子图（有节点上限）。",
            input_schema={
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "string"},
                    "relation": {"type": "string"},
                    "direction": {"type": "string", "enum": ["both", "in", "out"]},
                    "depth": {"type": "integer", "minimum": 1, "maximum": 4},
                },
                "required": ["chunk_id"],
            },
            handler=relations,
            group="knowledge",
        )
    )

    def export_knowledge(args: Dict[str, Any]) -> Dict[str, Any]:
        path = args.get("path") or str(Path(rt.config.paths.data_dir) / "exports" / "knowledge.jsonl")
        filters = ChunkFilter(project_id=args.get("project_id") or None)
        return rt.store.export(path, fmt=args.get("format", "jsonl"), filters=filters)

    reg.register(
        ToolSpec(
            name="export_knowledge",
            description="导出知识为 JSONL/JSON/CSV（含来源与核验状态），用于备份或外部分析。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "format": {"type": "string", "enum": ["jsonl", "json", "csv"]},
                    "project_id": {"type": "string"},
                },
            },
            handler=export_knowledge,
            risk="write",
            side_effects="写入导出文件",
            group="knowledge",
        )
    )

    def backup(args: Dict[str, Any]) -> Dict[str, Any]:
        dest = args.get("dest_dir") or str(Path(rt.config.paths.data_dir) / "backups")
        return rt.store.backup(dest, note=str(args.get("note") or ""))

    reg.register(
        ToolSpec(
            name="backup_knowledge_base",
            description="备份知识库（SQLite 在线备份 + 向量索引 + 清单）。",
            input_schema={
                "type": "object",
                "properties": {"dest_dir": {"type": "string"}, "note": {"type": "string"}},
            },
            handler=backup,
            risk="write",
            side_effects="写入备份目录",
            group="knowledge",
        )
    )

    def restore(args: Dict[str, Any]) -> Dict[str, Any]:
        _require(
            rt,
            args,
            action="restore_knowledge_base",
            risk="destructive",
            target=args["db_file"],
            project_id=str(args.get("project_id") or ""),
        )
        return rt.store.restore(args["db_file"], index_dir=args.get("index_dir"))

    reg.register(
        ToolSpec(
            name="restore_knowledge_base",
            description="从备份恢复知识库（恢复前自动保留 .pre-restore 副本并做完整性检查）。",
            input_schema={
                "type": "object",
                "properties": {
                    "db_file": {"type": "string"},
                    "index_dir": {"type": "string"},
                    "project_id": {"type": "string"},
                    "confirm_token": {"type": "string"},
                },
                "required": ["db_file"],
            },
            handler=restore,
            risk="destructive",
            side_effects="替换数据库与索引文件",
            requires_confirmation=True,
            group="knowledge",
        )
    )

    # ------------------------------------------------------------------ #
    # 附加：分区信息
    # ------------------------------------------------------------------ #
    reg.register(
        ToolSpec(
            name="list_knowledge_partitions",
            description="列出逻辑知识分区及其统计（数量、已核验、待核验、冲突、过时）。",
            input_schema={
                "type": "object",
                "properties": {"project_id": {"type": "string"}},
            },
            handler=lambda args: {
                "partitions": describe_partitions(),
                "stats": rt.metadata.partition_stats(args.get("project_id")),
            },
            group="knowledge",
        )
    )


__all__ = ["register"]
