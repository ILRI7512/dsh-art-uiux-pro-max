#!/usr/bin/env python3
"""对一个真实产品页面跑 Design Case Analyzer，产出案例报告 + 知识单元 + 冲突记录。

用法：
    python3 scripts/analyze_case.py --resource linear
    python3 scripts/analyze_case.py --resource stripe --max-units 12
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dsh_autonomous_learning"))

from dsh_autonomous_learning.config import load_config                       # noqa: E402
from dsh_autonomous_learning.core.models import (                            # noqa: E402
    Chunk, KnowledgeType, LicenseStatus, Partition, SourceType,
)
from dsh_autonomous_learning.core.orchestrator import build_runtime          # noqa: E402

from art_uiux.case_analyzer import (                                         # noqa: E402
    analyze_html, numeric_rules, units_from_case,
)
from art_uiux.checker import probe                                           # noqa: E402
from art_uiux.extract import fetch_html, sectionize                          # noqa: E402
from art_uiux.registry import Registry                                       # noqa: E402

PROJECT_ID = "prj_art_uiux"
CASE_SECTIONS = (
    "Case Summary", "Visual Language", "Layout Analysis", "Color Analysis",
    "Background Analysis", "Typography Analysis", "Component Analysis",
    "Interaction Analysis", "Accessibility Analysis",
    "Reusable Design Patterns", "Anti-Patterns", "Source and License",
)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resource", required=True)
    ap.add_argument("--max-units", type=int, default=24)
    args = ap.parse_args()

    reg = Registry(ROOT)
    res = reg.get(args.resource)
    if not res:
        print("未知资源:", args.resource)
        return 2

    chk = probe(res["url"])
    print("访问:", chk.access_status, chk.http_status, (chk.title or "")[:60])
    if chk.access_status != "reachable":
        reg.record_check(res["resource_id"], access_status=chk.access_status, http_status=chk.http_status,
                         final_url=chk.final_url, error=chk.error or "非 2xx")
        return 1

    html, final_url, status = fetch_html(res["url"])
    ca = analyze_html(html, url=res["url"], product=res["name"], platform=res["platform"])
    units = units_from_case(ca, resource=res)[: args.max_units]

    cfg = load_config(home=ROOT / "dsh_autonomous_learning",
                      overrides={"security": {"allow_network": True}})
    rt = build_runtime(cfg)
    try:
        if not rt.metadata.get_project(PROJECT_ID):
            from scripts.ingest import ensure_project
            ensure_project(rt)

        # 既有知识（用于冲突比对，取同类目样本）
        existing = rt.metadata.query_dicts(
            "SELECT chunk_id, topic, content, source_url FROM chunks "
            "WHERE project_id=? AND topic IN (%s) LIMIT 400" % ",".join("?" * len({u["category"] for u in units})),
            (PROJECT_ID, *sorted({u["category"] for u in units})),
        )

        rows = []
        for unit in units:
            cid = "chunk_" + hashlib.sha1((unit["resource_id"] + unit["content_hash"]).encode()).hexdigest()[:16]
            chunk = Chunk(
                chunk_id=cid, project_id=PROJECT_ID, document_id="doc_" + hashlib.sha1(res["url"].encode()).hexdigest()[:16],
                partition=Partition.UIUX.value if unit["level"] == "L2" else Partition.PENDING.value,
                domain="uiux", topic=unit["category"], subtopic=unit["title"][:120],
                title=unit["title"][:160], content=unit["content"],
                summary=unit["content"][:300],
                knowledge_type=KnowledgeType.CASE_STUDY.value, level=unit["level"],
                source_id="src_" + hashlib.sha1(res["resource_id"].encode()).hexdigest()[:16],
                source_url=res["url"], source_title=res["name"], source_type=SourceType.WEB_PAGE.value,
                author_or_publisher=res["name"], accessed_at=now(), language="en",
                content_hash=unit["content_hash"], source_quality=0.6,
                confidence=unit["confidence"], confidence_basis="case-analyzer:" + unit["kind"],
                verification_status="unverified", freshness_status="unknown",
                license_status=LicenseStatus.UNKNOWN.value, visibility="project",
                metadata={"case": ca.product, "evidence_kind": unit["kind"], "evidence_basis": unit["basis"],
                          "resource_id": res["resource_id"], "tech_stack": ca.tech_stack},
            )
            rows.append(chunk.to_row())

        result = rt.store.add_chunks(rows)

        # 数值冲突对比（不覆盖，仅登记）
        rules = numeric_rules(units)
        conflicts = []
        for chunk in existing:
            for num, unit_name in re.findall(r"(\d+(?:\.\d+)?)\s*(px|rem|%)", chunk.get("content") or ""):
                key = "%s|%s" % (chunk.get("topic"), unit_name)
                for unit in units:
                    if unit["category"] != chunk.get("topic"):
                        continue
                    for cnum, cunit in re.findall(r"(\d+(?:\.\d+)?)\s*(px|rem|%)", unit["content"]):
                        unit_key = "%s|%s" % (unit["category"], cunit)
                        if unit_key == key and abs(float(cnum) - float(num)) > 0.01:
                            conflicts.append({
                                "key": key, "a_source": chunk.get("source_url"), "a_value": float(num),
                                "b_source": unit["url"], "b_value": float(cnum),
                            })
        seen = set()
        uniq = []
        for c in conflicts:
            sig = (c["key"], c["a_source"], c["a_value"], c["b_value"])
            if sig in seen:
                continue
            seen.add(sig)
            uniq.append(c)

        out_dir = ROOT / "docs" / "cases"
        out_dir.mkdir(parents=True, exist_ok=True)
        report = {
            "generated_at": now(), "case": ca.product, "url": final_url, "http_status": status,
            "platform": ca.platform, "tech_stack": ca.tech_stack,
            "sections": {k: [e.as_dict() for e in v] for k, v in ca.sections.items()},
            "metrics": ca.metrics,
            "ingested_chunks": result.get("added", 0) + result.get("updated", 0),
            "duplicates": result.get("duplicates", []),
            "potential_conflicts": uniq[:40],
        }
        (out_dir / ("%s.json" % args.resource)).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        md = ["# Design Case: %s" % ca.product, "", "- URL: %s" % final_url,
              "- 抓取时间: %s" % now(), "- 平台: %s" % ca.platform,
              "- 技术栈指纹: %s" % (", ".join(ca.tech_stack) or "未检出"), ""]
        for section in CASE_SECTIONS:
            md.append("## %s" % section)
            items = ca.sections.get(section)
            if items:
                for ev in items:
                    md.append("- [%s, 置信 %.2f] %s" % (ev.kind, ev.confidence, ev.statement))
            elif section == "Reusable Design Patterns":
                facts = [e for v in ca.sections.values() for e in v if e.kind == "fact"]
                md.append("- 可迁移规则（仅基于事实）：")
                for ev in facts[:8]:
                    md.append("  - %s" % ev.statement)
            elif section == "Anti-Patterns":
                md.append("- 未检出可判定的反模式；需结合渲染与审计工具复核")
            elif section == "Source and License":
                md.append("- 来源: %s" % res["url"])
                md.append("- 许可证说明: %s" % res["license_notes"])
                md.append("- 版权归原站点所有；本文件仅归纳公开可访问页面的技术特征")
            md.append("")
        if uniq:
            md.append("## 与现有知识的潜在冲突（未覆盖，仅登记）")
            for c in uniq[:20]:
                md.append("- %s：%s → %s vs %s → %s" % (c["key"], c["a_source"], c["a_value"], c["b_source"], c["b_value"]))
        md.append("")
        md.append("## 能力边界")
        md.append("- 本分析基于静态 HTML/CSS 文本，未做真实渲染、未采集用户行为数据。")
        md.append("- 视觉美观、可用性、性能、转化率之间没有因果关系，此处不做任何此类推断。")
        (out_dir / ("%s.md" % args.resource)).write_text("\n".join(md), encoding="utf-8")

        reg.record_learning(res["resource_id"],
                            learn_status="learned" if report["ingested_chunks"] else "partial",
                            chunks=report["ingested_chunks"],
                            notes="case-analyzer: 单元 %d / 冲突 %d" % (len(units), len(uniq)))

        print(json.dumps({
            "case": ca.product, "tech_stack": ca.tech_stack,
            "sections": {k: len(v) for k, v in ca.sections.items()},
            "ingested": report["ingested_chunks"], "duplicates": len(report["duplicates"]),
            "potential_conflicts": len(uniq), "report": str(out_dir / ("%s.md" % args.resource)),
        }, ensure_ascii=False, indent=2))
        print("库内统计:", rt.store.stats()["chunks"], "条；分区:",
              [(p["partition"], p["total"]) for p in rt.store.stats()["partitions"]])
    finally:
        rt.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
