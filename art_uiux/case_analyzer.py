"""Design Case Analyzer —— 从真实页面提取可复用的视觉规律。

与「收藏截图」的区别：这里只输出**可复核的证据**，并把每条结论标注为
fact（页面里能直接读到的事实）/ inference（基于事实的合理推断）/ opinion（主观审美）。

硬规则：
- 视觉漂亮 ≠ 可用性好、性能好、转化高，禁止把审美推断写成结论；
- 没有真实测试数据时，不生成任何用户研究结论；
- 对比度、可读性等需要渲染计算的项，明确标注「未测」，不给假分数。
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------- 事实抽取

HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3}){1,2}\b")
RGB_RE = re.compile(r"rgba?\(\s*\d+[^)]*\)")
FONT_RE = re.compile(r"font-family\s*:\s*([^;\"'}]+)", re.I)
SIZE_RE = re.compile(r"font-size\s*:\s*([\d.]+)(px|rem|em)")
SPACE_RE = re.compile(r"(?:gap|padding|margin)(?:-\w+)?\s*:\s*([\d.]+)(px|rem)")
RADIUS_RE = re.compile(r"border-radius\s*:\s*([\d.]+)(px|rem|%)")
SHADOW_RE = re.compile(r"box-shadow\s*:\s*([^;\"'}]+)", re.I)
GRADIENT_RE = re.compile(r"(linear-gradient|radial-gradient|conic-gradient)\s*\(", re.I)
DURATION_RE = re.compile(r"(?:transition|animation)(?:-duration)?\s*:\s*([^;\"'}]+)", re.I)
MQ_RE = re.compile(r"@media[^{]{0,120}\{", re.I)
MAXW_RE = re.compile(r"max-width\s*:\s*([\d.]+)(px|rem)")
TECH_FINGERPRINTS = {
    "next.js": ("_next/static", "__NEXT_DATA__", "/_next/"),
    "react": ("react", "data-reactroot"),
    "vue": ("vue.js", "data-v-", "__VUE__"),
    "tailwind": ("tailwind", "tw-"),
    "styled-components": ("styled-components", "sc-"),
    "svelte": ("svelte",),
    "wordpress": ("wp-content", "wp-includes"),
    "gatsby": ("gatsby",),
}


@dataclass
class Evidence:
    statement: str
    kind: str          # fact | inference | opinion
    confidence: float
    basis: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"statement": self.statement, "kind": self.kind, "confidence": self.confidence, "basis": self.basis}


@dataclass
class CaseAnalysis:
    url: str
    product: str
    platform: str
    tech_stack: List[str]
    sections: Dict[str, List[Evidence]] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""

    def add(self, section: str, ev: Evidence) -> None:
        self.sections.setdefault(section, []).append(ev)

    def summary(self) -> Dict[str, Any]:
        counts = Counter()
        for items in self.sections.values():
            for ev in items:
                counts[ev.kind] += 1
        return {
            "case": self.product, "url": self.url, "platform": self.platform,
            "tech_stack": self.tech_stack, "evidence": dict(counts),
            "sections": {k: len(v) for k, v in self.sections.items()},
        }


def _top(counter: Counter, n: int = 6) -> List[Tuple[str, int]]:
    return counter.most_common(n)


def analyze_html(html: str, *, url: str, product: str, platform: str = "web") -> CaseAnalysis:
    ca = CaseAnalysis(url=url, product=product, platform=platform,
                      tech_stack=[], content_hash=hashlib.sha256(html.encode("utf-8", "ignore")).hexdigest())
    low = html.lower()

    # --- 技术栈（事实：页面里出现了对应指纹）
    for tech, marks in TECH_FINGERPRINTS.items():
        if any(m.lower() in low for m in marks):
            ca.tech_stack.append(tech)
    ca.add("Layout Analysis", Evidence(
        "检出技术栈指纹: " + (", ".join(ca.tech_stack) or "未检出"),
        "fact", 0.8, "HTML 中的静态指纹，非运行时确认"))

    # --- 色彩
    colors = Counter(m.group(0).lower() for m in HEX_RE.finditer(html))
    if colors:
        top = _top(colors, 8)
        ca.metrics["top_colors"] = top
        ca.add("Color Analysis", Evidence(
            "页面出现频次最高的色值: " + ", ".join("%s×%d" % (c, n) for c, n in top),
            "fact", 0.9, "正则统计 HTML/CSS 文本中的十六进制色值"))
        distinct = len(colors)
        ca.add("Color Analysis", Evidence(
            "文本中出现 %d 种不同色值（含主题变量与第三方样式）" % distinct,
            "fact", 0.7, "色值计数，含非品牌色"))
        if distinct > 60:
            ca.add("Color Analysis", Evidence(
                "色值数量偏多，可能缺少统一的色彩约束层",
                "inference", 0.4, "仅以色值计数推断，未核对设计 token 体系"))

    # --- 背景
    grads = GRADIENT_RE.findall(html)
    shadows = SHADOW_RE.findall(html)
    if grads or shadows:
        ca.add("Background Analysis", Evidence(
            "渐变出现 %d 次、阴影规则 %d 条" % (len(grads), len(shadows)),
            "fact", 0.85, "CSS 文本计数"))
        if grads:
            kinds = Counter(g.lower() for g in grads)
            ca.add("Background Analysis", Evidence(
                "渐变类型分布: " + ", ".join("%s×%d" % (k, v) for k, v in kinds.most_common()),
                "fact", 0.8, "CSS 关键字计数"))
    if re.search(r"(noise|fractalNoise|feTurbulence|base64.*png)", html, re.I):
        ca.add("Background Analysis", Evidence(
            "疑似包含噪点/纹理层（噪声函数或内嵌位图）", "inference", 0.45, "关键字命中，未做视觉确认"))

    # --- 排版
    fonts = Counter(f.strip().strip("'\"") for f in FONT_RE.findall(html))
    sizes = Counter("%s%s" % (n, u) for n, u in SIZE_RE.findall(html))
    if fonts:
        ca.metrics["font_families"] = _top(fonts, 5)
        ca.add("Typography Analysis", Evidence(
            "字体族: " + ", ".join("%s×%d" % (f, n) for f, n in _top(fonts, 5)),
            "fact", 0.85, "font-family 声明统计"))
    if sizes:
        ca.metrics["font_sizes"] = _top(sizes, 10)
        ca.add("Typography Analysis", Evidence(
            "字号档位: " + ", ".join("%s×%d" % (s, n) for s, n in _top(sizes, 10)),
            "fact", 0.85, "font-size 声明统计"))
        vals = sorted({float(n) for n, u in SIZE_RE.findall(html) if u == "px"})
        if len(vals) >= 6:
            ca.add("Typography Analysis", Evidence(
                "px 字号档位 %d 档，疑似缺少收敛的排版比例尺" % len(vals),
                "inference", 0.4, "档位数量启发式，需对照设计系统确认"))

    # --- 布局
    mq = len(MQ_RE.findall(html))
    maxw = Counter("%s%s" % (n, u) for n, u in MAXW_RE.findall(html))
    gaps = Counter("%s%s" % (n, u) for n, u in SPACE_RE.findall(html))
    ca.metrics.update({"media_queries": mq, "max_widths": _top(maxw, 5), "spacing": _top(gaps, 8)})
    ca.add("Layout Analysis", Evidence(
        "响应式断点 %d 个；容器最大宽度档位: %s" % (mq, ", ".join("%s×%d" % (w, n) for w, n in _top(maxw, 4)) or "未检出"),
        "fact", 0.8, "@media 与 max-width 声明统计"))
    if gaps:
        ca.add("Layout Analysis", Evidence(
            "间距取值高频档位: " + ", ".join("%s×%d" % (g, n) for g, n in _top(gaps, 8)),
            "fact", 0.75, "gap/padding/margin 声明统计"))
    ca.add("Layout Analysis", Evidence(
        "信息重心判断需要真实渲染截图，本工具未做渲染，因此不给结论",
        "fact", 1.0, "能力边界声明"))

    # --- 组件形态
    radius = Counter("%s%s" % (n, u) for n, u in RADIUS_RE.findall(html))
    if radius:
        ca.metrics["radius"] = _top(radius, 5)
        ca.add("Component Analysis", Evidence(
            "圆角档位: " + ", ".join("%s×%d" % (r, n) for r, n in _top(radius, 5)),
            "fact", 0.8, "border-radius 声明统计"))

    # --- 交互
    durations = DURATION_RE.findall(html)
    if durations:
        ms = [d for d in durations if re.search(r"\d", d)][:8]
        ca.add("Interaction Analysis", Evidence(
            "过渡/动画声明 %d 条，示例: %s" % (len(durations), "; ".join(ms)),
            "fact", 0.8, "CSS 文本统计"))
    if "prefers-reduced-motion" in low:
        ca.add("Interaction Analysis", Evidence(
            "声明了 prefers-reduced-motion 适配", "fact", 0.95, "媒体查询命中"))
    else:
        ca.add("Interaction Analysis", Evidence(
            "未检出 prefers-reduced-motion 适配（可能在其他样式表）", "inference", 0.4, "仅基于当前抓取的 HTML/CSS"))

    # --- 无障碍
    aria = len(re.findall(r"aria-[a-z]+=", html, re.I))
    roles = len(re.findall(r'role="[a-z]+"', html, re.I))
    imgs = re.findall(r"<img\b[^>]*>", html, re.I)
    with_alt = [i for i in imgs if re.search(r'\balt\s*=', i, re.I)]
    ca.metrics.update({"aria_attrs": aria, "roles": roles,
                       "img_total": len(imgs), "img_with_alt": len(with_alt)})
    ca.add("Accessibility Analysis", Evidence(
        "aria 属性 %d 个、role %d 个；img %d 张，其中带 alt %d 张（%.0f%%）" % (
            aria, roles, len(imgs), len(with_alt), (100.0 * len(with_alt) / len(imgs)) if imgs else 0),
        "fact", 0.85, "静态标记统计，不等于无障碍达标"))
    ca.add("Accessibility Analysis", Evidence(
        "对比度、焦点顺序、屏幕阅读器表现需要真实渲染与工具检测，本工具未测",
        "fact", 1.0, "能力边界声明"))
    if "skip" in low and "content" in low:
        ca.add("Accessibility Analysis", Evidence(
            "疑似存在跳转到主内容的 skip link", "inference", 0.5, "关键字命中"))

    # --- 视觉语言（主观部分必须单列）
    ca.add("Visual Language", Evidence(
        "整体风格判断（如极简/拟物/高对比）依赖视觉主观判断，需人工或视觉模型复核，本工具不下结论",
        "fact", 1.0, "能力边界声明"))
    return ca


# ---------------------------------------------------------------- 案例 → 知识单元

SECTION_TO_CATEGORY = {
    "Layout Analysis": "web_ui",
    "Color Analysis": "color_system",
    "Background Analysis": "background_design",
    "Typography Analysis": "visual_aesthetics",
    "Component Analysis": "design_system",
    "Interaction Analysis": "motion_interaction",
    "Accessibility Analysis": "ui_quality",
    "Visual Language": "visual_aesthetics",
}

#: 只有 fact 才允许作为「可迁移规则」入库；inference 标 L1；opinion 不入库。
QUALITY_GATE = {"fact": ("L2", True), "inference": ("L1", True), "opinion": ("L0", False)}


def units_from_case(ca: CaseAnalysis, *, resource: Dict[str, Any]) -> List[Dict[str, Any]]:
    units: List[Dict[str, Any]] = []
    # 案例级画像：整份案例的整体特征，归到该资源的**主分类**下。
    # 它是归纳而非测量，所以固定 L1，且明确标注来源是「案例画像」。
    structure = "；".join("%s %d 条" % (k, len(v)) for k, v in ca.sections.items() if v)
    units.append({
        "title": "%s · 案例画像" % ca.product,
        "content": "%s 案例画像：平台 %s；技术栈 %s；证据构成 %s；分节 %s" % (
            ca.product, ca.platform, "/".join(ca.tech_stack) or "未检出",
            ", ".join("%s=%d" % (k, len(v)) for k, v in ca.sections.items()), structure),
        "category": resource["primary_category"],
        "level": "L1",
        "kind": "inference",
        "confidence": 0.45,
        "basis": "案例画像（由页面信号归纳，非实测）",
        "case": ca.product,
        "url": ca.url,
        "content_hash": hashlib.sha256((ca.product + ca.url + "profile").encode()).hexdigest(),
        "resource_id": resource["resource_id"],
    })
    for section, items in ca.sections.items():
        category = SECTION_TO_CATEGORY.get(section, "uiux_principles")
        for ev in items:
            level, ingestable = QUALITY_GATE.get(ev.kind, ("L1", False))
            if not ingestable:
                continue
            # 「本工具未测/能力边界」这类声明只留在案例报告里，不作为知识入库，
            # 否则它会污染检索结果、看起来像设计结论。
            if ev.basis.startswith("能力边界声明"):
                continue
            text = "%s｜%s" % (section, ev.statement)
            units.append({
                "title": "%s · %s" % (ca.product, section),
                "content": text,
                "category": category,
                "level": level,
                "kind": ev.kind,
                "confidence": ev.confidence,
                "basis": ev.basis,
                "case": ca.product,
                "url": ca.url,
                "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "resource_id": resource["resource_id"],
            })
    return units


# ---------------------------------------------------------------- 冲突比对

NUM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(px|rem|%)")


def numeric_rules(units: List[Dict[str, Any]]) -> Dict[str, List[Tuple[str, float]]]:
    """从案例单元里抽「可比较的数值规则」，用于与库内既有规范对比。"""

    out: Dict[str, List[Tuple[str, float]]] = {}
    for unit in units:
        for num, unit_name in NUM_RE.findall(unit["content"]):
            key = "%s|%s" % (unit["category"], unit_name)
            out.setdefault(key, []).append((unit["url"], float(num)))
    return out


def compare_with_existing(rules: Dict[str, List[Tuple[str, float]]],
                          existing: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把案例数值与既有知识比对，数值不一致就记为「潜在冲突」，不做覆盖。"""

    conflicts = []
    for chunk in existing:
        text = chunk.get("content") or ""
        for num, unit_name in NUM_RE.findall(text):
            key = "%s|%s" % (chunk.get("topic"), unit_name)
            for url, value in rules.get(key, []):
                if abs(value - float(num)) > 0.01:
                    conflicts.append({
                        "kind": "numeric_mismatch",
                        "key": key,
                        "source_a": chunk.get("source_url"),
                        "value_a": float(num),
                        "source_b": url,
                        "value_b": value,
                        "note": "仅记录差异，适用条件需人工判定；不覆盖任何一方",
                    })
    return conflicts
