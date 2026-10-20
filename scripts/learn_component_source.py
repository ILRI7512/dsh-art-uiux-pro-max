#!/usr/bin/env python3
"""读一个组件的真实源码文件，抽出可确认的组件知识（不跑代码）。

只抽取能从源码文本确定性读到的内容：props 名、variant 枚举、aria 属性、
事件处理器、样式定制入口、以及仓库里是否存在对应测试文件。

用法：
    python3 scripts/learn_component_source.py --repo headlessui --file packages/@headlessui-react/src/components/button/button.tsx
    python3 scripts/learn_component_source.py --repo tremor --file src/components/Button/Button.tsx
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dsh_autonomous_learning"))


from dsh_autonomous_learning.config import load_config                    # noqa: E402
from dsh_autonomous_learning.core.models import Chunk, KnowledgeType, Partition  # noqa: E402
from dsh_autonomous_learning.core.orchestrator import build_runtime       # noqa: E402

from art_uiux.components import COMPONENT_SOURCES as SOURCES              # noqa: E402

PROJECT_ID = "prj_art_uiux"
UA = "DSH-Art-UIUX-ProMax/0.1 (component source reading; public data only)"
OUT = ROOT / "docs" / "components"
CACHE = ROOT / ".cache" / "gh"


def fetch(path: str) -> str:
    cache = CACHE / (re.sub(r"[^a-zA-Z0-9_.-]", "_", path) + ".src")
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    req = urllib.request.Request(path, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as resp:
        text = resp.read().decode("utf-8", errors="ignore")
    CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    return text


def parse_component(name: str, code: str, *, repo: str, path: str, license_name: str,
                    test_files: int) -> dict:
    props = sorted(set(re.findall(r"^\s{2}([a-zA-Z_][A-Za-z0-9_]*)\??:", code, re.M)))
    prop_types = sorted(set(re.findall(r"Props\s*=\s*\{", code)))
    variants = sorted(set(re.findall(r"(?:variant|size|color|tone)\s*:\s*\{([^}]{0,240})", code)))
    variant_keys = []
    for block in variants:
        variant_keys += re.findall(r"([a-zA-Z][\w-]*)\s*:", block)
    aria = sorted(set(re.findall(r"aria-[a-z]+", code)))
    roles = sorted(set(re.findall(r'role="([a-z]+)"', code)))
    handlers = sorted(set(re.findall(r"on([A-Z][A-Za-z]+)\s*[:=]", code)))
    states = sorted({m for m in re.findall(r"data-([a-z-]+)=", code)})
    class_entries = len(re.findall(r"className", code))
    style_hooks = sorted(set(re.findall(r"(?:cva|clsx|cn|twMerge|styled\.)", code)))

    def join(items, empty="unknown"):
        return ", ".join(items) if items else empty

    return {
        "component_id": "cmp_%s" % hashlib.sha1((repo + path).encode()).hexdigest()[:12],
        "component_name": name,
        "component_category": "basic",
        "platform": "web",
        "framework": "React + TypeScript",
        "source_repository": repo,
        "source_file": path,
        "source_version": "HEAD",
        "license": license_name,
        "component_purpose": ("可复用基础组件；具体语义见组件名与 aria 角色"
                             if not aria else "带 aria 标注的可交互组件：%s" % join(aria)),
        "visual_structure": "样式通过 className 注入（%d 处），组件不内联布局" % class_entries
                            if style_hooks else join(style_hooks),
        "layout_rules": "unknown（未见显式布局约束）",
        "parameters": props[:40],
        "component_states": states or [s for s in ("disabled", "loading") if s in code.lower()],
        "interaction_behavior": "事件处理: %s" % join(handlers, "未声明"),
        "theme_customization": "变体键: %s；样式工具: %s" % (join(sorted(set(variant_keys))[:20], "未声明"),
                                                     join(style_hooks, "未检出")),
        "responsive_behavior": "unknown（组件内部无断点逻辑）" if "media" not in code else "含媒体查询",
        "accessibility": "aria: %s；role: %s" % (join(aria, "无"), join(roles, "无")),
        "performance_notes": "unknown（未做基准测试）",
        "implementation_example": "见源码 %s" % path,
        "testing_strategy": ("仓库存在 %d 个测试文件；本组件是否有专属测试未逐一确认" % test_files)
                            if test_files else "未发现测试文件",
        "use_cases": ["表单/操作触发"] if "onClick" in code else [],
        "limitations": "只读源码文本，未运行、未渲染，交互与视觉表现未验证",
        "anti_patterns": [],
        "related_components": [],
        "knowledge_level": "L2",
        "content_hash": hashlib.sha256(code.encode()).hexdigest(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--name", default="")
    args = ap.parse_args()

    src = next((s for s in SOURCES if s["key"] == args.repo), None)
    if not src:
        print("未知组件库 key:", args.repo)
        return 2
    url = "https://raw.githubusercontent.com/%s/%s/HEAD/%s" % (src["owner"], src["repo"], args.file)
    code = fetch(url)
    name = args.name or Path(args.file).stem

    tree_cache = CACHE / ("tree_%s_%s.json" % (src["owner"], src["repo"]))
    test_files = 0
    license_name = "unknown"
    meta_cache = CACHE / ("meta_%s_%s.json" % (src["owner"], src["repo"]))
    if meta_cache.exists():
        meta = json.loads(meta_cache.read_text(encoding="utf-8"))["value"]
        license_name = ((meta.get("license") or {}) or {}).get("spdx_id") or "unknown"
    if tree_cache.exists():
        paths = json.loads(tree_cache.read_text(encoding="utf-8"))["value"]
        test_files = len([p for p in paths if re.search(r"(test|spec)\.", p, re.I)])

    knowledge = parse_component(name, code, repo=args.repo, path=args.file,
                                license_name=license_name, test_files=test_files)
    knowledge["source_url"] = "https://github.com/%s/%s/blob/HEAD/%s" % (src["owner"], src["repo"], args.file)

    rt = build_runtime(load_config(home=ROOT / "dsh_autonomous_learning"))
    try:
        chunk = Chunk(
            chunk_id=knowledge["component_id"],
            project_id=PROJECT_ID,
            document_id="doc_src_" + hashlib.sha1(args.file.encode()).hexdigest()[:12],
            partition=Partition.UIUX.value,
            domain="uiux",
            topic="design_system",
            subtopic="component-source",
            title="%s · %s 组件源码分析" % (src["repo"], name),
            content="组件 %s（%s）：props %d 个；状态 %s；aria %s；变体 %s；事件 %s" % (
                name, args.file, len(knowledge["parameters"]),
                knowledge["component_states"] or "未检出",
                knowledge["accessibility"], knowledge["theme_customization"],
                knowledge["interaction_behavior"]),
            summary="源码级组件知识（props/状态/aria/变体），未运行未渲染",
            knowledge_type=KnowledgeType.CODE_EXAMPLE.value,
            level="L2",
            source_url=knowledge["source_url"],
            source_title="%s/%s" % (src["owner"], src["repo"]),
            source_type="code_repo",
            author_or_publisher=src["owner"],
            language="en",
            content_hash=knowledge["content_hash"],
            source_quality=0.8,
            confidence=0.55,
            confidence_basis="只读源码文本；未构建、未测试、未渲染",
            verification_status="unverified",
            visibility="project",
            metadata={"component_knowledge": knowledge},
        )
        rt.store.add_chunks([chunk.to_row()])

        OUT.mkdir(parents=True, exist_ok=True)
        fname = re.sub(r"[^a-zA-Z0-9]+", "-", "%s-%s" % (args.repo, name)).strip("-").lower()
        md = ["# 组件源码分析: %s" % name, "",
              "- 仓库: %s | 文件: `%s`" % (src["repo"], args.file),
              "- 许可证: %s | 知识等级: **L2**（读了源码，未运行）" % license_name, "",
              "## 参数（从 TS 类型声明读取）", "", "- " + (", ".join(knowledge["parameters"]) or "未声明"), "",
              "## 状态", "", "- " + (", ".join(knowledge["component_states"]) or "未检出"), "",
              "## 无障碍", "", "- " + knowledge["accessibility"], "",
              "## 交互", "", "- " + knowledge["interaction_behavior"], "",
              "## 主题与定制", "", "- " + knowledge["theme_customization"], "",
              "## 测试", "", "- " + knowledge["testing_strategy"], "",
              "## 能力边界", "",
              "- 只读源码：没有构建、没有运行测试、没有渲染截图。",
              "- 因此「视觉表现、交互手感、性能、真实无障碍表现」全部未验证。"]
        (OUT / ("%s.md" % fname)).write_text("\n".join(md), encoding="utf-8")
        print(json.dumps({k: knowledge[k] for k in ("component_name", "parameters", "component_states",
                                                   "accessibility", "theme_customization")},
                         ensure_ascii=False, indent=2)[:900])
        print("报告:", str(OUT / ("%s.md" % fname)), "| 库内:", rt.store.stats()["chunks"])
    finally:
        rt.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
