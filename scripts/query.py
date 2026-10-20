#!/usr/bin/env python3
"""混合检索（向量 + BM25 + RRF），并强制附带来源与质量等级。

用法：
    python3 scripts/query.py "深色背景下的对比度控制" --category color_system
    python3 scripts/query.py "金融仪表盘的数值层级" --category financial_dashboard --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dsh_autonomous_learning"))

from dsh_autonomous_learning.config import load_config            # noqa: E402
from dsh_autonomous_learning.core.orchestrator import build_runtime  # noqa: E402
from dsh_autonomous_learning.storage.metadata_store import ChunkFilter  # noqa: E402

PROJECT_ID = "prj_art_uiux"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--category", default="")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--min-level", default="")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    cfg = load_config(home=ROOT / "dsh_autonomous_learning")
    rt = build_runtime(cfg)
    try:
        filters = ChunkFilter(project_id=PROJECT_ID)
        if args.category:
            filters.topics = [args.category]
        if args.min_level:
            filters.levels = [args.min_level]
        res = rt.store.search(args.query, top_k=args.top, filters=filters, include_content=True)
        hits = res.get("results") or res.get("hits") or []
        if not hits:
            out = {"query": args.query, "answer": "知识库暂无足够证据：0 条命中，建议先跑学习任务", "results": []}
        else:
            out = {"query": args.query, "count": len(hits), "results": [
                {
                    "chunk_id": h.get("chunk_id"),
                    "title": h.get("title"),
                    "score": round(float(h.get("score") or 0), 4),
                    "level": h.get("level"),
                    "topic": h.get("topic"),
                    "verification": h.get("verification_status"),
                    "source": (h.get("source") or {}).get("url"),
                    "content": (h.get("content") or "")[:180],
                    "warnings": h.get("warnings") or [],
                } for h in hits]}
        print(json.dumps(out, ensure_ascii=False, indent=2) if args.json else
              ("\n".join(["%s [%s %s] %.3f %s\n  %s" % (
                  r["title"], r["level"], r["topic"], r["score"], r["source"], r["content"])
                  for r in out["results"]]) or out["answer"]))
    finally:
        rt.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
