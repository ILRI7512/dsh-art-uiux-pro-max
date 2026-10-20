#!/usr/bin/env python3
"""学习一个开源组件仓库：拉真实元数据/README/文件树 → 推导组件知识 → 入库 + 报告。

只使用公开数据；不下载仓库压缩包，不复制源码进知识库。
对每个仓库的记录都写明「看到什么才算学到哪一级」。

用法：
    python3 scripts/learn_components.py --keys shadcn-ui,ant-design,vico
    python3 scripts/learn_components.py --all --limit 6
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dsh_autonomous_learning"))

from dsh_autonomous_learning.config import load_config                        # noqa: E402
from dsh_autonomous_learning.core.models import (                             # noqa: E402
    Chunk, KnowledgeType, LicenseStatus, Partition,
)
from dsh_autonomous_learning.core.orchestrator import build_runtime           # noqa: E402

from art_uiux.components import (                                             # noqa: E402
    COMPONENT_SOURCES, analyze_repository, comparisons,
)

PROJECT_ID = "prj_art_uiux"
UA = "DSH-Art-UIUX-ProMax/0.1 (component learning; public data only)"
OUT = ROOT / "docs" / "components"
_cache = ROOT / ".cache" / "gh"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_json(url: str, timeout: float = 25.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def http_text(url: str, timeout: float = 25.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def cached(name: str, fetcher):
    path = _cache / (re.sub(r"[^a-zA-Z0-9_.-]", "_", name) + ".json")
    if path.exists() and time.time() - path.stat().st_mtime < 6 * 3600:
        return json.loads(path.read_text(encoding="utf-8"))["value"]
    value = fetcher()
    _cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"value": value}, ensure_ascii=False), encoding="utf-8")
    return value


def fetch_repo(owner: str, repo: str) -> dict:
    meta = cached("meta_%s_%s" % (owner, repo), lambda: http_json("https://api.github.com/repos/%s/%s" % (owner, repo)))

    def readme():
        for name in ("README.md", "readme.md", "README.MD", "README.rst", "README"):
            try:
                return http_text("https://raw.githubusercontent.com/%s/%s/HEAD/%s" % (owner, repo, name))[:20000]
            except urllib.error.HTTPError:
                continue
        return ""

    readme_text = cached("readme_%s_%s" % (owner, repo), readme)

    def tree():
        branch = meta.get("default_branch") or "HEAD"
        data = http_json("https://api.github.com/repos/%s/%s/git/trees/%s?recursive=1" % (owner, repo, branch))
        return [n["path"] for n in data.get("tree", []) if n.get("type") == "blob"]

    try:
        paths = cached("tree_%s_%s" % (owner, repo), tree)
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise RuntimeError("GitHub API 限流（403），请稍后重试或分批运行") from exc
        paths = []
    return {"meta": meta, "readme": readme_text, "paths": paths}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    sources = COMPONENT_SOURCES
    if args.keys:
        wanted = {k.strip() for k in args.keys.split(",") if k.strip()}
        sources = [s for s in sources if s["key"] in wanted]
    if args.limit:
        sources = sources[: args.limit]

    cfg = load_config(home=ROOT / "dsh_autonomous_learning", overrides={"security": {"allow_network": True}})
    rt = build_runtime(cfg)
    results = []
    try:
        for src in sources:
            try:
                fetched = fetch_repo(src["owner"], src["repo"])
            except Exception as exc:  # noqa: BLE001
                print("%-18s 失败: %s" % (src["key"], exc))
                results.append({"repository": src["key"], "error": str(exc)})
                continue
            info = analyze_repository(fetched["meta"], fetched["readme"], fetched["paths"],
                                      platform=src["platform"], source_key=src["key"])
            info["source_key"] = src["key"]
            info["fetched_at"] = now()
            results.append(info)

            chunk = Chunk(
                chunk_id="chunk_comp_" + hashlib.sha1(src["key"].encode()).hexdigest()[:16],
                project_id=PROJECT_ID,
                document_id="doc_comp_" + hashlib.sha1(src["key"].encode()).hexdigest()[:16],
                partition=Partition.UIUX.value if info["knowledge_level"] == "L2" else Partition.PENDING.value,
                domain="uiux",
                topic=src.get("topic") or ("design_system" if src["platform"] == "web" else "android_ui"),
                subtopic="component-library",
                title="%s 组件库 · %s" % (info["repository"], "Web" if src["platform"] == "web" else "Android"),
                content=("组件库 %s：许可证 %s，语言 %s，候选组件 %d 个，类别 %s；"
                         "测试文件 %d 个，示例目录 %d 个；%s") % (
                    info["repository"], info["license"], info["framework"],
                    info["component_count_candidates"],
                    ", ".join(sorted(info["components_by_category"])) or "未识别",
                    info["test_files"], len(info["example_paths"]), info["limitations"]),
                summary=info["purpose"][:300],
                knowledge_type=KnowledgeType.BEST_PRACTICE.value,
                level=info["knowledge_level"],
                source_url="https://github.com/%s/%s" % (src["owner"], src["repo"]),
                source_title=info["repository"],
                source_type="code_repo",
                author_or_publisher=src["owner"],
                accessed_at=now(),
                language="en",
                content_hash=hashlib.sha256(json.dumps(info, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                source_quality=0.8 if not info["archived"] else 0.5,
                confidence=0.5,
                confidence_basis="仓库元数据+README+文件树，未读组件源码正文",
                verification_status="unverified",
                license_status=LicenseStatus.UNKNOWN.value,
                visibility="project",
                metadata={"component_library": info},
            )
            rt.store.add_chunks([chunk.to_row()])

            OUT.mkdir(parents=True, exist_ok=True)
            md = ["# 组件库学习: %s" % info["repository"], "",
                  "- 来源: https://github.com/%s/%s" % (src["owner"], src["repo"]),
                  "- 平台: %s | 语言: %s | 许可证: %s" % (src["platform"], info["framework"], info["license"]),
                  "- Star: %s | 归档: %s | 最近推送: %s" % (info["stars"], info["archived"], info["last_push"]),
                  "- 知识等级: **%s**（%s）" % (info["knowledge_level"],
                                            "看到组件目录且有测试/示例" if info["knowledge_level"] == "L2" else "仅元数据+README"),
                  "", "## 组件分类树（从目录名推导）", ""]
            for cat, names in sorted(info["components_by_category"].items()):
                md.append("- **%s**: %s" % (cat, ", ".join(names[:12])))
            md += ["", "## 测试与示例", "",
                   "- 测试文件数: %d" % info["test_files"],
                   "- 示例目录: %s" % (", ".join(info["example_paths"][:5]) or "未发现"),
                   "", "## 未确认字段（不编造）", "",
                   "- 组件参数 / 状态机 / 主题定制 / 无障碍实现 / 性能特征 / 交互行为："
                   "本次**未读取组件源码正文**，全部标 unknown；需下一步按文件抽样阅读。",
                   "", "## 局限", "", "- " + info["limitations"]]
            (OUT / ("%s.md" % src["key"])).write_text("\n".join(md), encoding="utf-8")
            print("%-18s %s | 组件候选 %-3d | 类别 %d | 测试 %-4d | 许可 %s" % (
                src["key"], info["knowledge_level"], info["component_count_candidates"],
                len(info["components_by_category"]), info["test_files"], info["license"]))

        ok = [r for r in results if "error" not in r]
        if ok:
            rows = comparisons(ok)
            OUT.mkdir(parents=True, exist_ok=True)
            md = ["# 组件库横向比较（只比可观测项）", "",
                  "| 仓库 | 许可证 | 语言 | 组件候选 | 覆盖类别 | 测试文件 | 归档 | 最近推送 |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- |"]
            for r in rows:
                md.append("| %s | %s | %s | %d | %s | %d | %s | %s |" % (
                    r["repository"], r["license"], r["framework"], r["components"],
                    ", ".join(r["categories"]) or "-", r["tests"], r["archived"], r["last_push"][:10]))
            md += ["", "> 本表不含「哪个更好」的结论：视觉美感、DX、长期维护成本都不在这张表里。"]
            (OUT / "compare.md").write_text("\n".join(md), encoding="utf-8")
            print("\n比较表:", str(OUT / "compare.md"))
        print("库内:", rt.store.stats()["chunks"], "条")
    finally:
        rt.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
