#!/usr/bin/env python3
"""把注册表里的可达资源真正写入向量知识库。

流程：probe → 抓正文 → 分节 → 分类 → 16 字段模板 → 质量门槛 → Chunk → store.add_chunks

用法：
    python3 scripts/ingest.py --limit 5
    python3 scripts/ingest.py --only m3-material,nng,shadcn
    python3 scripts/ingest.py --all --max-units 12
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dsh_autonomous_learning"))

from dsh_autonomous_learning.config import load_config          # noqa: E402
from dsh_autonomous_learning.core.models import (              # noqa: E402
    Chunk, Document, KnowledgeType, LicenseStatus, Partition, Project, Source, SourceType,
)
from dsh_autonomous_learning.core.orchestrator import build_runtime  # noqa: E402

from art_uiux.checker import probe                              # noqa: E402
from art_uiux.extract import build_unit, fetch_html, sectionize, summarize_unit  # noqa: E402
from art_uiux.registry import Registry                          # noqa: E402

PROJECT_ID = "prj_art_uiux"
SOURCE_TYPE_MAP = {
    "official_documentation": SourceType.OFFICIAL_DOC.value,
    "github_repository": SourceType.CODE_REPO.value,
    "design_system": SourceType.TECH_DOC.value,
    "product_case": SourceType.WEB_PAGE.value,
    "design_gallery": SourceType.WEB_PAGE.value,
    "technical_tutorial": SourceType.TECH_DOC.value,
    "accessibility_standard": SourceType.STANDARD.value,
    "visual_reference": SourceType.WEB_PAGE.value,
}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_project(rt) -> None:
    if rt.metadata.get_project(PROJECT_ID):
        return
    proj = Project(
        project_id=PROJECT_ID,
        title="DSH Art UI/UX Pro Max",
        goal="建立 UI/UX 设计知识的可持续学习、可检索、可验证体系",
        domain="uiux",
        partitions=[Partition.UIUX.value, Partition.PENDING.value],
        depth="deep",
        mode="assisted",
        acceptance_criteria=[
            "每条知识有唯一主分类",
            "来源与许可证可追溯",
            "L2 以上知识具备原则与适用场景",
            "不得以资源登记代替学习完成",
        ],
        deliverables=["12 项交付物报告"],
    )
    rt.metadata.create_project(proj.to_row())


def ingest_one(rt, reg: Registry, res: dict, *, max_units: int) -> dict:
    rid = res["resource_id"]
    check = probe(res["url"])
    if check.access_status != "reachable":
        reg.record_check(rid, access_status=check.access_status, http_status=check.http_status,
                         final_url=check.final_url, content_type=check.content_type,
                         bytes_read=check.bytes_read, robots_allowed=check.robots_allowed,
                         error=check.error or "非 2xx 或响应体异常")
        return {"resource_id": rid, "ingested": 0, "reason": "access=" + check.access_status}

    html, final_url, status = fetch_html(res["url"])
    sections = sectionize(html)
    if not sections:
        reg.record_check(rid, access_status="restricted", http_status=status, final_url=final_url,
                         content_type="text/html", bytes_read=len(html), robots_allowed=True,
                         error="正文区块提取为空（可能是纯 JS 渲染）")
        return {"resource_id": rid, "ingested": 0, "reason": "no_sections"}

    source_type = SOURCE_TYPE_MAP.get(res["resource_type"], SourceType.WEB_PAGE.value)
    src = Source(
        source_id="src_" + hashlib.sha1(rid.encode()).hexdigest()[:16],
        project_id=PROJECT_ID,
        source_type=source_type,
        location=res["url"],
        title=res["name"],
        license_status=LicenseStatus.UNKNOWN.value,
        quality={"high": 0.85, "medium": 0.6, "low": 0.35}.get(res["source_reliability"], 0.5),
        quality_basis="source_reliability=" + res["source_reliability"],
        content_hash=hashlib.sha256(html.encode("utf-8", "ignore")).hexdigest(),
        fetch_ok=True,
        metadata={"resource_id": rid, "crawl_policy": res["crawl_policy"]},
    )
    if not rt.metadata.get("sources", src.source_id):
        rt.metadata.insert("sources", src.to_row())

    doc = Document(
        document_id="doc_" + hashlib.sha1((rid + final_url).encode()).hexdigest()[:16],
        project_id=PROJECT_ID,
        source_id=src.source_id,
        title=res["name"],
        doc_type="html",
        language="en",
        content_hash=hashlib.sha256(html.encode("utf-8", "ignore")).hexdigest(),
        char_count=sum(len(s.text) for s in sections),
        parser="art_uiux.extract.sectionize",
        parse_status="parsed",
    )
    if not rt.metadata.get("documents", doc.document_id):
        rt.metadata.insert("documents", doc.to_row())

    # 教程/官方文档/标准整篇都是设计内容，门槛放到 2 个设计词；
    # 产品站与画廊仍要 3 个，避免把营销文案收进来。
    min_terms = 2 if res["resource_type"] in (
        "technical_tutorial", "official_documentation", "accessibility_standard") else 3
    units, skipped = [], 0
    for section in sections[:max_units]:
        from art_uiux.extract import classify_with_prior

        category, score, matched, source_of = classify_with_prior(
            section.text, heading=section.heading, primary_category=res["primary_category"])
        unit = build_unit(section, resource=res, category=category, score=score,
                          matched=matched, min_design_terms=min_terms)
        unit["classification_source"] = source_of
        if not unit["ready_to_ingest"]:
            skipped += 1
            continue
        units.append(unit)

    rows = []
    for unit in units:
        mapped = summarize_unit(unit, res)
        chunk_id = "chunk_" + hashlib.sha1((rid + unit["content_hash"]).encode()).hexdigest()[:16]
        chunk = Chunk(
            chunk_id=chunk_id,
            project_id=PROJECT_ID,
            document_id=doc.document_id,
            partition=Partition.UIUX.value if unit["level"] == "L2" else Partition.PENDING.value,
            domain="uiux",
            topic=mapped["topic"],
            subtopic=mapped["subtopic"],
            title=mapped["title"],
            content=mapped["content"],
            summary=mapped["summary"],
            knowledge_type=KnowledgeType.BEST_PRACTICE.value,
            level=unit["level"],
            source_id=src.source_id,
            source_url=res["url"],
            source_title=res["name"],
            source_type=source_type,
            author_or_publisher=res["name"],
            accessed_at=now(),
            language="en",
            content_hash=unit["content_hash"],
            source_quality={"high": 0.85, "medium": 0.6, "low": 0.35}.get(res["source_reliability"], 0.5),
            confidence=0.35,
            confidence_basis="规则提取，未经交叉验证或任务验证",
            verification_status="unverified",
            freshness_status="unknown",
            license_status=LicenseStatus.UNKNOWN.value,
            visibility="project",
            metadata={**mapped["metadata"], "classification_source": unit.get("classification_source", "")},
        )
        rows.append(chunk.to_row())

    result = rt.store.add_chunks(rows)
    learned = int(result.get("added", 0)) + int(result.get("updated", 0))
    reg.record_learning(
        rid,
        learn_status="learned" if learned else "partial",
        chunks=learned,
        notes="分节 %d / 过门槛 %d / 跳过 %d / 重复 %d" % (
            len(sections), len(rows), skipped, len(result.get("duplicates", []))),
    )
    return {
        "resource_id": rid,
        "ingested": learned,
        "duplicates": len(result.get("duplicates", [])),
        "skipped": skipped,
        "sections": len(sections),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--max-units", type=int, default=10)
    args = ap.parse_args()

    reg = Registry(ROOT)
    items = [i for i in reg.view() if i["access_status"] == "reachable"]
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        items = [i for i in items if i["resource_id"] in wanted]
    if args.limit:
        items = items[: args.limit]
    if not args.all and not args.only and not args.limit:
        items = items[:5]

    cfg = load_config(home=ROOT / "dsh_autonomous_learning",
                      overrides={"security": {"allow_network": True}})
    rt = build_runtime(cfg)
    try:
        ensure_project(rt)
        total = 0
        for item in items:
            try:
                out = ingest_one(rt, reg, item, max_units=args.max_units)
            except Exception as exc:  # noqa: BLE001 - 单个资源失败不能中断整批学习
                reg.record_learning(item["resource_id"], learn_status="failed", chunks=0,
                                    error="%s: %s" % (type(exc).__name__, exc))
                out = {"resource_id": item["resource_id"], "ingested": 0,
                       "reason": "fetch_error: %s" % type(exc).__name__}
                print("%-22s 抓取失败: %s" % (item["resource_id"], type(exc).__name__))
            total += out.get("ingested", 0)
            print("%-22s ingested=%-3s chunks  %s" % (
                out["resource_id"], out.get("ingested", 0),
                out.get("reason", "dupes=%s skipped=%s sections=%s" % (
                    out.get("duplicates"), out.get("skipped"), out.get("sections")))))
        print("\n本次入库片段:", total)
        print("库内统计:", rt.store.stats())
        print("注册表:", reg.stats())
    finally:
        rt.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
