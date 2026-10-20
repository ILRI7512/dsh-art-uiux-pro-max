#!/usr/bin/env python3
"""语义检索评测：固定查询集，统计 hit@1 / hit@3 与来源回带率。"""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "dsh_autonomous_learning"))
from dsh_autonomous_learning.config import load_config
from dsh_autonomous_learning.core.orchestrator import build_runtime
from art_uiux.retrieval import search as art_search

CASES = [
    ("text contrast ratio requirement for body copy", "color_system"),
    ("touch target minimum size accessibility", "ui_quality"),
    ("gradient background performance cost", "background_design"),
    ("design tokens theme customization", "design_system"),
    ("android compose adaptive window size class", "android_ui"),
    ("css grid responsive breakpoints", "web_ui"),
    ("animation duration easing reduced motion", "motion_interaction"),
    ("financial dashboard kpi density", "financial_dashboard"),
    ("game hud skill bar layout", "game_ui"),
    ("svg icon grid stroke rules", "visual_assets"),
    ("visual hierarchy whitespace composition", "visual_aesthetics"),
    ("usability heuristic cognitive load", "uiux_principles"),
]

def main() -> int:
    rt = build_runtime(load_config(home=ROOT / "dsh_autonomous_learning"))
    rows, h1, h3, src_ok = [], 0, 0, 0
    try:
        for query, expected in CASES:
            res = art_search(rt, query, top_k=5)
            hits = res.get("results") or []
            topics = [h.get("topic") for h in hits]
            top1 = bool(topics[:1] == [expected])
            top3 = expected in topics[:3]
            has_src = bool(hits and (hits[0].get("source") or {}).get("url"))
            h1 += top1; h3 += top3; src_ok += has_src
            rows.append({"query": query, "expected": expected, "top3": topics[:3],
                         "hit@1": top1, "hit@3": top3, "source_attached": has_src,
                         "levels": [h.get("level") for h in hits[:3]]})
    finally:
        rt.close()
    n = len(CASES)
    md = ["# 语义检索评测", "",
          "查询数 %d | hit@1 **%d/%d (%.0f%%)** | hit@3 **%d/%d (%.0f%%)** | 来源回带 %d/%d" % (
              n, h1, n, 100.0*h1/n, h3, n, 100.0*h3/n, src_ok, n), "",
          "| 查询 | 期望分类 | 实际 top3 | hit@1 | hit@3 |", "| --- | --- | --- | --- | --- |"]
    for r in rows:
        md.append("| %s | %s | %s | %s | %s |" % (r["query"][:46], r["expected"],
                  ", ".join(x or "-" for x in r["top3"]), "✓" if r["hit@1"] else "✗",
                  "✓" if r["hit@3"] else "✗"))
    md += ["", "> 说明：embedder 是离线特征哈希（512 维），不是神经向量模型；",
           "> 该指标反映的是**当前检索链路**的能力，接入 embedding 服务后需重测。"]
    (ROOT / "docs" / "SEARCH-EVAL.md").write_text("\n".join(md), encoding="utf-8")
    print("hit@1 %d/%d | hit@3 %d/%d | 来源回带 %d/%d" % (h1, n, h3, n, src_ok, n))
    for r in rows:
        print("  %-46s → %s %s" % (r["query"][:46], r["top3"][:2], "OK" if r["hit@3"] else "MISS"))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
