#!/usr/bin/env python3
"""可量化检索评测：4 套系统 × 18 条查询 × 人工 qrels。

系统：
- vector   引擎向量检索（特征哈希 512 维）
- bm25     纯 BM25
- rrf      引擎混合检索（向量 + BM25 + RRF 融合）
- rerank   RRF + 本项目的分类亲和度与词面重叠重排

指标：P@1/P@3/P@5、Recall@10、MRR@10、nDCG@5，配 paired bootstrap 95% 区间。
同时输出「分类纯度」这一不需要标注的客观指标。

用法：
    python3 scripts/eval_retrieval.py
    python3 scripts/eval_retrieval.py --json > runs.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dsh_autonomous_learning"))

from dsh_autonomous_learning.config import load_config                        # noqa: E402
from dsh_autonomous_learning.core.orchestrator import build_runtime           # noqa: E402
from dsh_autonomous_learning.storage.metadata_store import ChunkFilter        # noqa: E402

from art_uiux import metrics as M                                             # noqa: E402
from art_uiux.retrieval import search as rerank_search                        # noqa: E402

QRELS = ROOT / "eval" / "qrels.json"
TOP_K = 10
RERANK_POOL = 12
SYSTEMS = ("vector", "bm25", "rrf", "rerank", "rerank_zh", "rerank_ce")


def run_systems(rt, query: str):
    """返回 {system: [chunk_id, ...]}，长度统一 TOP_K。"""

    filters = ChunkFilter(project_id="prj_art_uiux")
    allowed = rt.store._allowed_ids(filters)

    vec = [cid for cid, _ in rt.store._vector_search(query, allowed, TOP_K)]
    bm = [cid for cid, _ in rt.metadata.bm25_search(query, allowed_ids=allowed, top_k=TOP_K)]
    rrf_res = rt.store.search(query, top_k=TOP_K, filters=filters, include_content=False)
    rrf = [h["chunk_id"] for h in (rrf_res.get("results") or [])]
    rr_res = rerank_search(rt, query, top_k=TOP_K)
    rr = [h["chunk_id"] for h in (rr_res.get("results") or [])]
    zh_res = rerank_search(rt, query, top_k=TOP_K, bilingual=True)
    zh = [h["chunk_id"] for h in (zh_res.get("results") or [])]

    # 交叉编码器重排：先取更大候选集，再逐条精排
    from art_uiux.rerank import rerank as ce_rerank

    pool = rerank_search(rt, query, top_k=RERANK_POOL, bilingual=True).get("results") or []
    ce = ce_rerank(query, pool, top_k=TOP_K)
    return {"vector": vec, "bm25": bm, "rrf": rrf, "rerank": rr, "rerank_zh": zh,
            "rerank_ce": [h["chunk_id"] for h in ce["results"]],
            "_ce_latency": ce["latency_ms"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    data = json.loads(QRELS.read_text(encoding="utf-8"))
    queries = data["queries"]
    cfg = load_config(home=ROOT / "dsh_autonomous_learning")
    rt = build_runtime(cfg)

    per_query = []
    topic_of = {}
    try:
        for q in queries:
            started = __import__("time").perf_counter()
            runs = run_systems(rt, q["query"])
            elapsed = (__import__("time").perf_counter() - started) * 1000
            ce_latency = runs.pop("_ce_latency", None)
            row = {"qid": q["qid"], "query": q["query"], "expected_topic": q["expected_topic"],
                   "labels": q["labels"], "runs": runs, "metrics": {},
                   "latency_ms_total": round(elapsed, 1), "latency_ms_ce": ce_latency}
            for sys_name, ranked in runs.items():
                row["metrics"][sys_name] = {
                    "P@1": M.precision_at_k(ranked, q["labels"], 1),
                    "P@3": M.precision_at_k(ranked, q["labels"], 3),
                    "P@5": M.precision_at_k(ranked, q["labels"], 5),
                    "R@10": M.recall_at_k(ranked, q["labels"], 10),
                    "MRR@10": M.mrr_at_k(ranked, q["labels"], 10),
                    "nDCG@5": M.ndcg_at_k(ranked, q["labels"], 5),
                }
            for cid in {c for r in runs.values() for c in r}:
                if cid not in topic_of:
                    chunk = rt.metadata.get_chunk(cid)
                    topic_of[cid] = (chunk or {}).get("topic", "")
            for sys_name, ranked in runs.items():
                row["metrics"][sys_name]["cat_purity@5"] = M.category_purity(
                    [{"topic": topic_of.get(c, "")} for c in ranked], q["expected_topic"], 5)
            per_query.append(row)
    finally:
        rt.close()

    agg = {}
    for sys_name in SYSTEMS:
        agg[sys_name] = {
            key: M.mean([q["metrics"][sys_name][key] for q in per_query])
            for key in ("P@1", "P@3", "P@5", "R@10", "MRR@10", "nDCG@5", "cat_purity@5")
        }

    deltas = {}
    for key in ("nDCG@5", "MRR@10", "P@1"):
        a = [q["metrics"]["rerank_ce"][key] for q in per_query]
        b = [q["metrics"]["rrf"][key] for q in per_query]
        deltas[key] = M.bootstrap_diff(a, b)

    per_topic = {}
    for q in per_query:
        per_topic.setdefault(q["expected_topic"], []).append(q)
    topic_table = {}
    for topic, qs in per_topic.items():
        topic_table[topic] = {
            sys_name: M.mean([q["metrics"][sys_name]["nDCG@5"] for q in qs]) for sys_name in SYSTEMS
        }

    out = {"aggregate": agg, "deltas_rerank_vs_rrf": deltas, "per_topic_ndcg5": topic_table,
           "per_query": per_query, "annotator": data.get("annotator")}
    (ROOT / "eval" / "runs.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    def fmt(v):
        return "  n/a " if v != v else "%5.3f" % v

    lines = ["# 检索评测报告（可量化）", "",
             "- 查询数：%d（其中 %d 条有标注、%d 条为「预期无答案」负例）" % (
                 len(per_query), sum(1 for q in per_query if q["labels"]),
                 sum(1 for q in per_query if not q["labels"])),
             "- 标注者：%s" % data.get("annotator", "unknown"),
             "- 指标：P@1/3/5、Recall@10、MRR@10、nDCG@5（增益 2^g-1），另加不需要标注的分类纯度@5",
             "- 运行：`python3 scripts/eval_retrieval.py`；逐条明细见 `eval/runs.json`", "",
             "## 系统对比（18 条查询均值）", "",
             "| 系统 | P@1 | P@3 | P@5 | R@10 | MRR@10 | nDCG@5 | 分类纯度@5 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for sys_name in SYSTEMS:
        a = agg[sys_name]
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            sys_name, fmt(a["P@1"]), fmt(a["P@3"]), fmt(a["P@5"]), fmt(a["R@10"]),
            fmt(a["MRR@10"]), fmt(a["nDCG@5"]), fmt(a["cat_purity@5"])))

    lines += ["", "## rerank_ce 相对 rrf 的配对 bootstrap（2000 次，95% 区间）", "",
              "| 指标 | 均值差 | 95% 区间 | 样本 |", "| --- | --- | --- | --- |"]
    for key, d in deltas.items():
        lines.append("| %s | %+.3f | [%+.3f, %+.3f] | %d |" % (key, d["mean_diff"], d["lo"], d["hi"], d["n"]))

    lines += ["", "## 按分类看 nDCG@5", "", "| 分类 | vector | bm25 | rrf | rerank | rerank_zh | rerank_ce |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for topic, row in sorted(topic_table.items()):
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            topic, fmt(row["vector"]), fmt(row["bm25"]), fmt(row["rrf"]),
            fmt(row["rerank"]), fmt(row["rerank_zh"]), fmt(row["rerank_ce"])))

    ce_lat = [q["latency_ms_ce"] for q in per_query if q.get("latency_ms_ce")]
    lines += ["", "## 延迟（本机 arm64 CPU 实测）", "",
              "- 交叉编码器重排：每条查询中位 **%.0f ms**（候选 %d 条）" % (
                  sorted(ce_lat)[len(ce_lat)//2] if ce_lat else 0, RERANK_POOL),
              "- 全套 6 系统跑完一条查询的中位耗时：%.0f ms" % (
                  sorted(q["latency_ms_total"] for q in per_query)[len(per_query)//2])]
    lines += ["", "## 逐条结果（rerank_ce）", "", "| qid | 查询 | nDCG@5 | MRR@10 | P@1 |", "| --- | --- | --- | --- | --- |"]
    for q in per_query:
        mm = q["metrics"]["rerank_ce"]
        lines.append("| %s | %s | %s | %s | %s |" % (
            q["qid"], q["query"][:34], fmt(mm["nDCG@5"]), fmt(mm["MRR@10"]), fmt(mm["P@1"])))

    lines += ["", "## 结论与限制", "",
              "1. 无答案负例（q17/q18）的 nDCG 与 Recall 为 n/a，不参与均值；它们的意义是检查系统会不会硬凑答案。",
              "2. 单标注者 + 作者偏差：查询作者同时看过语料，标签可能对能识别的表述更友好。qrels 已导出，可人工复核修订。",
              "3. 语料只有 104 条，指标对单条差异敏感；不要把 ±0.02 当成真实提升。",
              "4. embedder 是离线特征哈希，不是神经向量模型；换模型后必须重跑同一套 qrels 对比。"]

    (ROOT / "docs" / "EVAL-REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:32]))
    print("\n报告:", ROOT / "docs" / "EVAL-REPORT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
