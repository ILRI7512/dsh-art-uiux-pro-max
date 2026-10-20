"""UI Component Learning Engine —— 组件级学习与比较。

与「收集组件代码」的区别：
- 只写能从仓库真实结构/文件里确认的字段，确认不了的一律 `unknown`；
- 组件知识等级按实际看到的证据决定：只看了元数据+README → L1；
  看到组件目录与源码文件清单 → L2；读过参数定义与测试 → 仍只是 L2，
  除非有真实构建/测试结果才允许 L3/L4；
- 比较表只比可观测项（API 形态、依赖数量、许可证、维护活跃度），
  不比"哪个更好看"。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------- 组件资源清单

COMPONENT_SOURCES: List[Dict[str, str]] = [
    {"key": "compose-samples", "owner": "android", "repo": "compose-samples", "platform": "android", "kind": "official_samples"},
    {"key": "nowinandroid", "owner": "android", "repo": "nowinandroid", "platform": "android", "kind": "official_app"},
    {"key": "androidx", "owner": "androidx", "repo": "androidx", "platform": "android", "kind": "official_library"},
    {"key": "koalaplot", "owner": "KoalaPlot", "repo": "koalaplot-core", "platform": "android", "kind": "third_party"},
    {"key": "vico", "owner": "patrykandpatrick", "repo": "vico", "platform": "android", "kind": "third_party"},
    {"key": "landscapist", "owner": "skydoves", "repo": "landscapist", "platform": "android", "kind": "third_party"},
    {"key": "compose-rich-editor", "owner": "halilozercan", "repo": "compose-rich-editor", "platform": "android", "kind": "third_party"},
    {"key": "reorderable", "owner": "Calvin-LL", "repo": "Reorderable", "platform": "android", "kind": "third_party"},
    {"key": "shadcn-ui", "owner": "shadcn-ui", "repo": "ui", "platform": "web", "kind": "third_party"},
    {"key": "ant-design", "owner": "ant-design", "repo": "ant-design", "platform": "web", "kind": "third_party"},
    {"key": "headlessui", "owner": "tailwindlabs", "repo": "headlessui", "platform": "web", "kind": "third_party"},
    {"key": "storybook", "owner": "storybookjs", "repo": "storybook", "platform": "web", "kind": "third_party"},
    {"key": "tremor", "owner": "tremorlabs", "repo": "tremor", "platform": "web", "kind": "third_party"},
    # 图标/视觉资产：这些库的 README + 文件树能提供真实的尺寸/网格/许可信息
    {"key": "simple-icons", "owner": "simple-icons", "repo": "simple-icons", "platform": "web", "kind": "icon_library", "topic": "visual_assets"},
    {"key": "heroicons-repo", "owner": "tailwindlabs", "repo": "heroicons", "platform": "web", "kind": "icon_library", "topic": "visual_assets"},
    {"key": "material-design-icons", "owner": "google", "repo": "material-design-icons", "platform": "web", "kind": "icon_library", "topic": "visual_assets"},
]

# ---------------------------------------------------------------- 分类树

COMPONENT_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "basic": {"label": "基础组件", "members": ["button", "text", "label", "icon", "divider", "avatar", "badge", "chip"]},
    "layout": {"label": "布局组件", "members": ["row", "column", "grid", "list", "container", "scroll", "stack", "spacer"]},
    "navigation": {"label": "导航组件", "members": ["bottom-nav", "top-app-bar", "sidebar", "tabs", "breadcrumb", "nav-rail"]},
    "input": {"label": "输入组件", "members": ["text-field", "search", "select", "switch", "slider", "date-picker", "checkbox", "radio"]},
    "feedback": {"label": "反馈组件", "members": ["progress", "spinner", "banner", "toast", "snackbar", "skeleton"]},
    "overlay": {"label": "浮层组件", "members": ["dialog", "bottom-sheet", "popover", "tooltip", "dropdown", "menu"]},
    "data": {"label": "数据组件", "members": ["table", "stat-card", "chart", "data-list", "pagination", "sparkline"]},
    "advanced": {"label": "高级组件", "members": ["rich-text-editor", "drag-reorder", "gesture", "custom-drawing", "image-loader"]},
}

#: 匹配顺序 = 具体程度：高级/数据组件先判，基础组件最后兜底。
#: 键按「完整单词」匹配，避免 "table" 被 "tab" 误判成导航组件。
CATEGORY_PATTERNS = {
    "advanced": ("editor", "reorder", "drag", "gesture", "canvas", "render", "loader", "rich"),
    "data": ("table", "chart", "plot", "stat", "pagination", "graph", "candle", "sparkline", "card"),
    "overlay": ("dialog", "sheet", "popover", "tooltip", "dropdown", "menu", "modal"),
    "input": ("input", "field", "search", "select", "switch", "slider", "picker", "checkbox", "radio"),
    "navigation": ("nav", "tab", "tabs", "breadcrumb", "sidebar", "appbar", "rail", "navigation"),
    "feedback": ("progress", "spinner", "toast", "snackbar", "banner", "skeleton", "loading"),
    "layout": ("layout", "grid", "column", "row", "list", "container", "spacer", "stack"),
    "basic": ("button", "text", "label", "icon", "divider", "avatar", "badge", "chip"),
}


def _words(name: str) -> set:
    parts = re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+", name)
    out = set()
    for part in parts:
        out.add(part.lower())
    out.add(re.sub(r"[^a-z0-9]", "", name.lower()))
    return out


def categorize(name: str) -> str:
    words = _words(name)
    for cat, keys in CATEGORY_PATTERNS.items():
        if any(k in words for k in keys):
            return cat
    return "unknown"


# ---------------------------------------------------------------- 知识结构

UNKNOWN = "unknown"


@dataclass
class ComponentKnowledge:
    """25 字段，缺证据就写 unknown，不生成假信息。"""

    component_id: str
    component_name: str
    component_category: str          # basic/layout/.../unknown
    platform: str
    framework: str = UNKNOWN
    source_repository: str = ""
    source_file: str = UNKNOWN
    source_version: str = UNKNOWN
    license: str = UNKNOWN
    component_purpose: str = UNKNOWN
    visual_structure: str = UNKNOWN
    layout_rules: str = UNKNOWN
    parameters: List[str] = field(default_factory=list)
    component_states: List[str] = field(default_factory=list)
    interaction_behavior: str = UNKNOWN
    theme_customization: str = UNKNOWN
    responsive_behavior: str = UNKNOWN
    accessibility: str = UNKNOWN
    performance_notes: str = UNKNOWN
    implementation_example: str = UNKNOWN
    testing_strategy: str = UNKNOWN
    use_cases: List[str] = field(default_factory=list)
    limitations: str = UNKNOWN
    anti_patterns: List[str] = field(default_factory=list)
    related_components: List[str] = field(default_factory=list)
    knowledge_level: str = "L1"
    content_hash: str = ""
    last_verified: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def fill_hash(self) -> None:
        blob = json.dumps({k: v for k, v in self.to_dict().items() if k != "content_hash"},
                          ensure_ascii=False, sort_keys=True)
        self.content_hash = hashlib.sha256(blob.encode()).hexdigest()


# ---------------------------------------------------------------- 仓库事实 → 组件知识

TEST_HINTS = ("test", "spec", "__tests__", "androidTest", "testFixtures")
EXAMPLE_HINTS = ("example", "examples", "demo", "samples", "storybook")


def analyze_repository(repo_meta: Dict[str, Any], readme: str, paths: Sequence[str], *,
                       platform: str, source_key: str) -> Dict[str, Any]:
    """从真实仓库数据推导组件知识；推导不出的字段保持 unknown。"""

    name = repo_meta.get("full_name") or source_key
    license_name = ((repo_meta.get("license") or {}) or {}).get("spdx_id") or UNKNOWN
    archived = bool(repo_meta.get("archived"))
    stars = repo_meta.get("stargazers_count")
    pushed = repo_meta.get("pushed_at") or ""
    pushed_year = pushed[:4] if pushed else ""
    language = repo_meta.get("language") or UNKNOWN

    # 从路径里找组件目录：带 component/ui/widgets/controls 段的
    comp_paths = [p for p in paths if re.search(r"/(components?|ui|widgets?|controls?)/", p, re.I)][:400]
    test_paths = [p for p in paths if any(h.lower() in p.lower() for h in TEST_HINTS)]
    example_paths = [p for p in paths if any(h.lower() in p.lower() for h in EXAMPLE_HINTS)]

    # 组件名候选：去掉扩展名后的基名，只保留 camel/Pascal 形式的目录名
    names = []
    for p in comp_paths:
        stem = p.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if re.fullmatch(r"[A-Z][A-Za-z0-9]{2,}", stem) or re.fullmatch(r"[a-z][a-z0-9-]{3,}", stem):
            if stem.lower() not in ("index", "types", "utils", "styles", "readme"):
                names.append(stem)
    uniq_names = sorted(set(names))[:60]

    by_cat: Dict[str, List[str]] = {}
    for n in uniq_names:
        by_cat.setdefault(categorize(n), []).append(n)

    # 等级：有组件路径 + 有测试或示例 → L2；否则 L1
    level = "L2" if comp_paths and (test_paths or example_paths) else "L1"

    readme_head = re.sub(r"\s+", " ", readme or "")[:400]
    purpose = readme_head if readme_head else UNKNOWN

    return {
        "repository": name,
        "platform": platform,
        "framework": language,
        "license": license_name,
        "stars": stars,
        "archived": archived,
        "last_push": pushed,
        "source_version": pushed_year or UNKNOWN,
        "component_paths": comp_paths[:40],
        "component_count_candidates": len(uniq_names),
        "components_by_category": {k: v[:12] for k, v in by_cat.items()},
        "test_files": len(test_paths),
        "example_paths": example_paths[:10],
        "knowledge_level": level,
        "purpose": purpose,
        "limitations": (
            "仓库已归档，可能不再维护" if archived
            else ("最近推送 %s，维护活跃度未知" % pushed_year if pushed_year else "维护状态未知")
        ),
    }


def comparisons(repos: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """横向比较：只比可观测项，不给「最好」结论。"""

    rows = []
    for r in repos:
        rows.append({
            "repository": r["repository"],
            "license": r["license"],
            "framework": r["framework"],
            "components": r["component_count_candidates"],
            "categories": sorted(r["components_by_category"].keys()),
            "tests": r["test_files"],
            "archived": r["archived"],
            "last_push": r["last_push"],
        })
    return rows
