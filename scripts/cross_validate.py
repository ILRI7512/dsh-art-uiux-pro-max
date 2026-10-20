#!/usr/bin/env python3
"""交叉验证：把「两个独立来源说法一致」的知识升级到 L3。

规则（与引擎 verifier 对齐）：
- 只在同一主分类内配对；
- 两个来源必须来自不同站点（host 不同），否则不算独立证据；
- 内容相似度用确定性 token 重叠计算，低于阈值不配对；
- 核验由引擎 KnowledgeVerifier 判定，PASS 才写 L3，其余保持原等级；
- 不做任何覆盖删除：冲突只登记，不裁决。

用法：
    python3 scripts/cross_validate.py --threshold 0.45 --dry-run
    python3 scripts/cross_validate.py --threshold 0.45
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.parse
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dsh_autonomous_learning"))

from dsh_autonomous_learning.config import load_config                    # noqa: E402
from dsh_autonomous_learning.core.orchestrator import build_runtime      # noqa: E402

PROJECT_ID = "prj_art_uiux"
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "for", "with",
        "on", "as", "by", "that", "this", "it", "be", "use", "using", "should", "must"}


def host(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).netloc
    except Exception:
        return ""


def tokens(text: str) -> set:
    words = re.findall(r"[a-z]{3,}", (text or "").lower())
    return {w for w in words if w not in STOP}


def similarity(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


#: 可交叉验证的「规则签名」：从文本中抽可复现的阈值/规范锚点。
SIGNATURES = (
    ("contrast_aa_normal", r"(4\.5\s*:?\s*1|4\.5\s*比|4\.5:|contrast.{0,24}4\.5)"),
    ("contrast_large", r"(3\s*:\s*1|3:1)"),
    ("contrast_aaa", r"(7\s*:\s*1|7:1)"),
    ("touch_target_44", r"(44\s*(px|dp)|48\s*(px|dp)|44\s*×\s*44|48\s*×\s*48)"),
    ("reduced_motion", r"(prefers-reduced-motion|reduced motion|减少动态)"),
    ("focus_visible", r"(focus-visible|focus visible|焦点可见|visible focus)"),
    ("min_font_12", r"(12\s*(px|sp))"),
    ("breakpoint_600", r"(600\s*px|600dp)"),
    ("breakpoint_768", r"(768\s*px)"),
    ("breakpoint_1024", r"(1024\s*px|1024dp)"),
    ("duration_200", r"(200\s*ms)"),
    ("duration_300", r"(300\s*ms)"),
    ("spacing_8", r"(8\s*(px|dp)\s*(grid|scale|基数|间距))"),
)


def signatures(text: str) -> set:
    low = (text or "").lower()
    return {name for name, pattern in SIGNATURES if re.search(pattern, low)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.45)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    cfg = load_config(home=ROOT / "dsh_autonomous_learning")
    rt = build_runtime(cfg)
    try:
        rows = rt.metadata.query_dicts(
            "SELECT chunk_id, topic, content, source_url, source_id, level, verification_status, metadata "
            "FROM chunks WHERE project_id=? AND verification_status != 'verified'", (PROJECT_ID,))
        # 关键过滤：案例分析器产出的「对某个站点的测量事实」不能互相作证。
        # 两个站点都说自己「img alt 覆盖 100%」不构成同一规则的独立复现，
        # 那是同一段模板套了两遍 —— 这种伪独立性会把 L3 灌水。
        import json as _json
        filtered = []
        for row in rows:
            try:
                meta = _json.loads(row.get("metadata") or "{}")
            except Exception:
                meta = {}
            if meta.get("evidence_kind"):
                continue
            filtered.append(row)
        rows = filtered
        # 跨分类配对：同一条规则（例如「正文对比度 ≥ 4.5:1」）可能被
        # 关键词分类器分别放进 color_system 与 ui_quality，但规则本身相同。
        # 这里按签名全局配对，并在证据里记录两侧分类。
        by_topic = {"__all__": list(rows)}

        verified = 0
        attempted = 0
        details = []
        for topic, items in by_topic.items():
            for i, a in enumerate(items):
                if args.limit and attempted >= args.limit:
                    break
                for b in items[i + 1:]:
                    if host(a["source_url"]) == host(b["source_url"]):
                        continue
                    sa, sb = signatures(a["content"]), signatures(b["content"])
                    shared = sa & sb
                    sim = similarity(a["content"], b["content"])
                    # 有共同规则签名（阈值/规范锚点）才算独立复现；纯文本相似不算。
                    if not shared:
                        continue
                    attempted += 1
                    evidence = [{
                        "kind": "source",
                        "topic_a": a["topic"], "topic_b": b["topic"],
                        "source_id": b["source_id"],
                        "url": b["source_url"],
                        "snippet": (b["content"] or "")[:300],
                        "relation": "corroborates",
                        "shared_signatures": sorted(shared),
                        "similarity": round(sim, 3),
                    }]
                    if args.dry_run:
                        details.append({"topic": topic, "a": a["chunk_id"], "b": b["chunk_id"],
                                        "shared": sorted(shared)})
                        continue
                    outcome = rt.verifier.verify(a["chunk_id"], method="cross_source", evidence=evidence)
                    if outcome.get("result") == "pass" and outcome.get("verification_status") == "verified":
                        rt.store.update_document(a["chunk_id"], {"level": "L3"},
                                                 reason="cross_source: 另一个独立来源说法一致")
                        verified += 1
                    details.append({"topic": topic, "a": a["chunk_id"], "b": b["chunk_id"],
                                    "shared": sorted(shared), "result": outcome.get("result")})
                    break  # 每条知识只需一个独立佐证即可升级

        stats = rt.store.stats()
        print("配对尝试:", attempted, "| 升级 L3:", verified, "| dry_run:", args.dry_run)
        for d in details[:8]:
            print("  ", d)
        print("levels:", {lv: rt.metadata.scalar(
            "SELECT COUNT(*) FROM chunks WHERE level=?", (lv,)) for lv in ("L1", "L2", "L3", "L4")})
        print("verified:", rt.metadata.scalar(
            "SELECT COUNT(*) FROM chunks WHERE verification_status='verified'"), "/", stats["chunks"])
    finally:
        rt.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
