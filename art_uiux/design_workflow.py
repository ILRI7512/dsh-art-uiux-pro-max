"""七步设计工作流（可调用模块，不是文档）。

1 route_task   识别任务类型
2 retrieve     按任务类型选分类、按平台/等级过滤，检索知识
3 propose      提出有明显区别的视觉方向（拒绝默认玻璃拟态/深色/蓝紫渐变）
4 build_system 产出 Design Tokens（含对比度实算）
5 implement    输出可落地的 CSS 变量与结构建议（不覆盖既有工程）
6 audit        10 项设计审计，能测的算出来，不能测的标「未测」
7 feedback     把已验证结论回写知识库（项目级 vs 通用级分开）

硬约束：没有真实测试就标 unverified；审美判断不得冒充可用性结论。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------- 1 任务识别

TASK_TYPES = {
    "android_native": {"label": "Android 原生应用", "categories": ["android_ui", "motion_interaction", "design_system"]},
    "web_page": {"label": "Web 网页", "categories": ["web_ui", "visual_aesthetics", "ui_quality"]},
    "admin_console": {"label": "管理后台", "categories": ["web_ui", "design_system", "ui_quality"]},
    "fintech_terminal": {"label": "金融终端", "categories": ["financial_dashboard", "color_system", "ui_quality"]},
    "game_ui": {"label": "游戏界面", "categories": ["game_ui", "motion_interaction", "visual_aesthetics"]},
    "data_viz": {"label": "数据可视化", "categories": ["financial_dashboard", "color_system", "design_system"]},
    "design_system": {"label": "设计系统", "categories": ["design_system", "color_system", "ui_quality"]},
    "background_asset": {"label": "背景与视觉资产", "categories": ["background_design", "color_system", "visual_assets"]},
    "ui_refactor": {"label": "现有 UI 改造", "categories": ["ui_quality", "web_ui", "android_ui"]},
}

TASK_KEYWORDS = {
    "android_native": ("android", "compose", "kotlin", "app 首页", "移动端原生"),
    "admin_console": ("后台", "管理台", "console", "dashboard 表格", "权限管理"),
    "fintech_terminal": ("金融", "行情", "k线", "持仓", "ticker", "外汇", "交易终端"),
    "game_ui": ("游戏", "hud", "技能", "背包", "关卡"),
    "data_viz": ("图表", "可视化", "指标", "趋势图"),
    "design_system": ("设计系统", "token", "组件库", "主题"),
    "background_asset": ("背景", "渐变", "纹理", "光晕", "插画", "图标"),
    "ui_refactor": ("改造", "重构", "审计", "优化现有", "翻新"),
    "web_page": ("网页", "官网", "落地页", "landing", "saas 页面"),
}


def route_task(text: str) -> Tuple[str, List[str], str]:
    """返回 (任务类型, 相关主分类, 判定依据)。"""

    low = text.lower()
    best, best_hits = "web_page", []
    for task, kws in TASK_KEYWORDS.items():
        hits = [k for k in kws if k.lower() in low]
        if len(hits) > len(best_hits):
            best, best_hits = task, hits
    cats = TASK_TYPES[best]["categories"]
    basis = "命中关键词 %s" % best_hits if best_hits else "无关键词，默认按网页任务处理"
    return best, cats, basis


# ---------------------------------------------------------------- 2 检索


def retrieve(rt, *, query: str, categories: Sequence[str], platform: str = "",
             top_k: int = 6, min_level: str = "") -> Dict[str, Any]:
    """按分类检索，回带来源、等级与告警；证据不足时明确说不足。"""

    from dsh_autonomous_learning.storage.metadata_store import ChunkFilter

    filters = ChunkFilter(project_id="prj_art_uiux", topics=list(categories))
    if min_level:
        filters.levels = [min_level]
    from .retrieval import search as _rsearch

    res = _rsearch(rt, query, top_k=top_k, categories=list(categories), bilingual=True)
    hits = res.get("results") or []
    expanded = False
    if not hits:
        # 中文提问 + 英文语料时会召不回：用分类关键词做一次确定性扩展。
        from .taxonomy import get_category

        terms = []
        for cat in categories:
            try:
                terms.extend(list(get_category(cat).keywords)[:6])
            except Exception:
                continue
        if terms:
            expanded = True
            res = rt.store.search(" ".join(terms), top_k=top_k, filters=filters, include_content=True)
            hits = res.get("results") or []
    if platform:
        matched = [h for h in hits if platform in ((h.get("source") or {}).get("url") or "")]
        hits = matched or hits
    levels = [h.get("level") for h in hits]
    return {
        "query": query, "categories": list(categories), "count": len(hits),
        "hits": hits,
        "evidence_sufficient": bool(hits),
        "answer_if_empty": "" if hits else "知识库暂无足够证据：该分类尚未学到相关内容，建议先补学习任务",
        "level_spread": {lv: levels.count(lv) for lv in set(levels)},
        "query_expanded": expanded,
        "unverified": all(h.get("verification_status") != "verified" for h in hits) if hits else None,
    }


# ---------------------------------------------------------------- 3 视觉方向

DIRECTIONS: Dict[str, Dict[str, Any]] = {
    "editorial_light": {
        "name": "Editorial Light（编辑部留白）",
        "idea": "以阅读节奏为第一优先级，靠留白与字号对比建立秩序",
        "style": "纸感浅底、低饱和、强排版层级",
        "color": "暖白底 + 近黑字 + 单一强调色（饱和度中等）",
        "type": "衬线大标题 + 无衬线正文，字号跨度 3 档以上",
        "layout": "单栏窄容器，长段落，弱化卡片边界",
        "background": "纯色或极轻纸纹，无渐变",
        "interaction": "轻微淡入与下划线反馈，时长 120–180ms",
        "fits": "内容型站点、品牌官网、长文阅读",
        "drawbacks": "信息密度低，不适合高频操作台",
    },
    "swiss_grid": {
        "name": "Swiss Grid（瑞士栅格）",
        "idea": "用严格栅格与对齐制造秩序感，装饰最小化",
        "style": "高对比黑白 + 一个功能色，几何化",
        "color": "白底/黑字 + 单一功能色，色板极窄",
        "type": "单一无衬线，字号档位收敛到 5 档",
        "layout": "12 栏栅格，强对齐，模块化区块",
        "background": "纯色，允许细网格线",
        "interaction": "状态用位移/底色变化表达，避免阴影",
        "fits": "设计系统文档、作品集、数据型展示页",
        "drawbacks": "对细节容错低，字体基线错误会非常明显",
    },
    "industrial_dense": {
        "name": "Industrial Dense（工业高密度）",
        "idea": "为高频操作优化，牺牲呼吸感换信息密度与确定性",
        "style": "深灰/蓝灰中性底，细边框分区",
        "color": "低饱和中性色阶 + 状态语义色（涨/跌/警告）",
        "type": "系统无衬线，等宽数字用于数值列",
        "layout": "多栏密集布局，固定表头，紧凑行高",
        "background": "无渐变，允许极细分割线",
        "interaction": "即时反馈优先，动效短（≤100ms），避免大位移",
        "fits": "交易终端、监控台、后台管理系统",
        "drawbacks": "视觉疲劳风险高，长时使用需要降对比选项",
    },
    "soft_brutalist": {
        "name": "Soft Brutalist（柔性粗野）",
        "idea": "以强烈形制与直白结构建立记忆点，同时保证可读",
        "style": "大圆角、粗描边、块面撞色",
        "color": "2–3 个高明度撞色 + 白/黑基色",
        "type": "大字号无衬线，紧凑行距",
        "layout": "错位栅格，模块尺寸差异大",
        "background": "纯色块面拼接，可用粗噪点纹理",
        "interaction": "按压反馈明显，允许 180–240ms 缓动",
        "fits": "工具类产品、年轻化 C 端、活动页",
        "drawbacks": "易过度设计；高饱和色会增加无障碍风险",
    },
}

#: 明确不允许「不问场景就默认采用」的做法。
FORBIDDEN_DEFAULTS = ("玻璃拟态", "深色背景", "蓝紫渐变", "发光边框")


def propose_directions(task_type: str, *, count: int = 3,
                       exclude: Iterable[str] = FORBIDDEN_DEFAULTS) -> List[Dict[str, Any]]:
    """给出有实质区别的方向；不同方向之间必须至少在 3 个维度上不同。"""

    order = ["editorial_light", "swiss_grid", "industrial_dense", "soft_brutalist"]
    if task_type in ("fintech_terminal", "admin_console", "data_viz"):
        order = ["industrial_dense", "swiss_grid", "editorial_light", "soft_brutalist"]
    elif task_type == "game_ui":
        order = ["soft_brutalist", "industrial_dense", "swiss_grid", "editorial_light"]

    picked = []
    for key in order:
        if len(picked) >= count:
            break
        d = dict(DIRECTIONS[key])
        d["key"] = key
        d["excluded_defaults_checked"] = list(exclude)
        picked.append(d)
    return picked


# ---------------------------------------------------------------- 4 设计系统 / 对比度

HEX_RE = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def hex_values(text: str) -> set:
    """findall 取到的是分组内容，这里补回 '#'，避免与 token 值比对时全部错位。"""

    return {"#" + c.lower() for c in HEX_RE.findall(text)}


def _to_rgb(color: str) -> Tuple[int, int, int]:
    m = HEX_RE.search(color.strip())
    if not m:
        raise ValueError("不是十六进制颜色: %r" % color)
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def relative_luminance(color: str) -> float:
    def chan(v: int) -> float:
        s = v / 255.0
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = _to_rgb(color)
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG 2.x 对比度：1.0 ~ 21.0。纯黑对纯白应为 21.0。"""

    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


WCAG_MIN = {"AA_normal": 4.5, "AA_large": 3.0, "AAA_normal": 7.0, "AAA_large": 4.5, "ui_component": 3.0}


def check_palette(pairs: Sequence[Tuple[str, str, str]]) -> List[Dict[str, Any]]:
    """pairs: [(名称, 前景, 背景)] → 每条附实测比值与是否达标。"""

    out = []
    for name, fg, bg in pairs:
        try:
            ratio = contrast_ratio(fg, bg)
        except ValueError as exc:
            out.append({"pair": name, "error": str(exc)})
            continue
        verdict = {k: ratio >= v for k, v in WCAG_MIN.items()}
        out.append({
            "pair": name, "fg": fg, "bg": bg,
            "ratio": round(ratio, 2),
            "AA_normal": verdict["AA_normal"], "AA_large": verdict["AA_large"],
            "AAA_normal": verdict["AAA_normal"], "ui_component": verdict["ui_component"],
            "measured": True,
        })
    return out


TYPE_SCALE = (12, 14, 16, 20, 28, 40, 56)
SPACE_SCALE = (4, 8, 12, 16, 24, 32, 48, 64)
RADIUS_SCALE = (0, 4, 8, 12, 16)


def build_design_system(direction_key: str, *, base: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """产出一套可落地的 token，并对关键配色做对比度实算。"""

    presets = {
        "editorial_light": {"bg": "#faf8f4", "fg": "#15130f", "muted": "#6b6459", "accent": "#8a4b2a",
                            "surface": "#ffffff", "positive": "#1c6b3a", "negative": "#a32118", "warning": "#8a5a00",
                            "border": "#8d8a9e"},
        "swiss_grid": {"bg": "#ffffff", "fg": "#0a0a0a", "muted": "#5c5c5c", "accent": "#d4351c",
                       "surface": "#f2f2f2", "positive": "#146b32", "negative": "#b32113", "warning": "#8a5a00",
                       "border": "#7a7a7a"},
        "industrial_dense": {"bg": "#14171c", "fg": "#e6e9ee", "muted": "#9aa3af", "accent": "#4c9aff",
                             "surface": "#1c2027", "positive": "#4ade80", "negative": "#f87171", "warning": "#fbbf24",
                             "border": "#6b7484"},
        "soft_brutalist": {"bg": "#fffdf6", "fg": "#121212", "muted": "#5f5a4e", "accent": "#ff5c38",
                           "surface": "#ffe9a8", "positive": "#1d6b3a", "negative": "#a82a1c", "warning": "#8a5a00",
                           "border": "#8a7a5c"},
    }
    colors = dict(presets.get(direction_key, presets["swiss_grid"]))
    if base:
        colors.update(base)

    pairs = [
        ("正文/背景", colors["fg"], colors["bg"]),
        ("次要文字/背景", colors["muted"], colors["bg"]),
        ("强调色/背景", colors["accent"], colors["bg"]),
        ("正文/卡片面", colors["fg"], colors["surface"]),
        ("涨/正向", colors["positive"], colors["bg"]),
        ("跌/负向", colors["negative"], colors["bg"]),
        # WCAG 1.4.11：UI 组件边界（非文本）需要 ≥3:1
        ("边框/卡片面", colors["border"], colors["surface"]),
    ]
    contrast = check_palette(pairs)
    failing = [c for c in contrast if c.get("measured") and not c.get("AA_normal")]
    return {
        "direction": direction_key,
        "tokens": {
            "color": colors,
            "type_scale_px": list(TYPE_SCALE),
            "space_scale_px": list(SPACE_SCALE),
            "radius_px": list(RADIUS_SCALE),
            "shadow": ["0 1px 2px rgba(0,0,0,.06)", "0 8px 24px rgba(0,0,0,.10)"],
            "motion": {"fast_ms": 120, "base_ms": 180, "easing": "cubic-bezier(.2,.8,.2,1)",
                       "reduced_motion": "支持 prefers-reduced-motion"},
        },
        "component_states": ["default", "hover", "active", "focus-visible", "disabled", "loading", "error"],
        "responsive": ["compact <600", "medium 600–1023", "expanded ≥1024"],
        "a11y": ["焦点可见（≥3:1 轮廓对比）", "触控目标 ≥44×44", "不依赖颜色单独传达状态"],
        "contrast": contrast,
        "failing_pairs": failing,
        "verified": False,
        "note": "对比度为公式实算；其余项为设计约定，尚未经真实任务验证",
    }


def tokens_to_css(system: Dict[str, Any]) -> str:
    c = system["tokens"]["color"]
    lines = [":root {"]
    for key, value in c.items():
        lines.append("  --color-%s: %s;" % (key, value))
    for i, size in enumerate(system["tokens"]["type_scale_px"]):
        lines.append("  --text-%d: %dpx;" % (i, size))
    for i, size in enumerate(system["tokens"]["space_scale_px"]):
        lines.append("  --space-%d: %dpx;" % (i, size))
    for i, size in enumerate(system["tokens"]["radius_px"]):
        lines.append("  --radius-%d: %dpx;" % (i, size))
    m = system["tokens"]["motion"]
    lines.append("  --motion-fast: %dms;" % m["fast_ms"])
    lines.append("  --motion-base: %dms;" % m["base_ms"])
    lines.append("  --easing-standard: %s;" % m["easing"])
    lines.append("}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 6 审计

AUDIT_ITEMS = (
    "visual_hierarchy", "decoration", "consistency", "component_language",
    "background_readability", "responsive_overflow", "interaction_states",
    "accessibility", "motion_performance", "design_drift",
)


@dataclass
class Finding:
    item: str
    status: str        # pass | warn | fail | unmeasured
    detail: str
    evidence: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {"item": self.item, "status": self.status, "detail": self.detail, "evidence": self.evidence}


def audit_html(html: str, *, tokens: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """10 项审计。能算的算出来，不能算的明确 unmeasured，不给假通过。"""

    low = html.lower()
    findings: List[Finding] = []

    sizes = sorted({float(n) for n in re.findall(r"font-size\s*:\s*([\d.]+)px", html)})
    findings.append(Finding(
        "visual_hierarchy",
        "pass" if len(sizes) >= 3 else ("warn" if sizes else "unmeasured"),
        "字号档位 %d 档%s" % (len(sizes), "：" + ", ".join("%gpx" % s for s in sizes) if sizes else "（未在内联样式声明）"),
        {"font_sizes": sizes}))

    shadows = len(re.findall(r"box-shadow", html))
    grads = len(re.findall(r"gradient\(", html))
    findings.append(Finding(
        "decoration", "warn" if (shadows + grads) > 12 else "pass",
        "阴影 %d 处、渐变 %d 处" % (shadows, grads), {"shadows": shadows, "gradients": grads}))

    colors = hex_values(html)
    families = {f.strip().strip("'\"") for f in re.findall(r"font-family\s*:\s*([^;\"'}]+)", html)}
    findings.append(Finding(
        "consistency",
        "pass" if len(colors) <= 12 else "warn",
        "色值 %d 个、字体族 %d 种" % (len(colors), len(families)),
        {"colors": sorted(colors), "font_families": sorted(families)}))

    radii = sorted({r for r in re.findall(r"border-radius\s*:\s*([\d.]+)%?", html)})
    findings.append(Finding(
        "component_language",
        "pass" if len(radii) <= 4 else "warn",
        "圆角档位 %d 档: %s" % (len(radii), ", ".join(radii) or "未声明"), {"radii": radii}))

    if tokens:
        c = tokens.get("color") or {}
        pairs = [("正文/背景", c.get("fg"), c.get("bg")), ("次要/背景", c.get("muted"), c.get("bg"))]
        results = [r for r in check_palette([(n, f, b) for n, f, b in pairs if f and b]) if r.get("measured")]
        worst = min((r["ratio"] for r in results), default=None)
        findings.append(Finding(
            "background_readability",
            "unmeasured" if worst is None else ("pass" if worst >= 4.5 else "fail"),
            "正文对比度最低 %.2f:1" % worst if worst else "未提供配色，无法实测",
            {"results": results}))
    else:
        findings.append(Finding("background_readability", "unmeasured", "未提供 token 配色，无法实测对比度"))

    fixed = [int(n) for n in re.findall(r"width\s*:\s*(\d{3,4})px", html)]
    overflow = [w for w in fixed if w > 360]
    findings.append(Finding(
        "responsive_overflow", "warn" if overflow else "pass",
        "存在 %d 处固定宽度 >360px，小屏可能溢出" % len(overflow) if overflow else "未发现明显固定宽溢出",
        {"fixed_widths": fixed}))

    states = {s: low.count(s) for s in (":hover", ":focus", ":active", ":disabled", "focus-visible")}
    missing = [s for s, n in states.items() if n == 0]
    findings.append(Finding(
        "interaction_states", "warn" if missing else "pass",
        "缺失状态: " + ", ".join(missing) if missing else "关键交互状态齐全", {"states": states}))

    imgs = re.findall(r"<img\b[^>]*>", html, re.I)
    with_alt = [i for i in imgs if re.search(r"\balt\s*=", i, re.I)]
    aria = len(re.findall(r"aria-[a-z]+=", html, re.I))
    ratio = (len(with_alt) / len(imgs)) if imgs else 1.0
    if imgs and ratio < 1:
        a11y_status, a11y_note = "fail", "存在无 alt 的图片"
    elif aria == 0:
        a11y_status, a11y_note = "warn", "无 aria 标注（可能缺语义角色）"
    else:
        a11y_status, a11y_note = "pass", "静态标记齐全"
    findings.append(Finding(
        "accessibility", a11y_status,
        "%s；img alt 覆盖 %.0f%%（%d/%d），aria 属性 %d 个" % (
            a11y_note, ratio * 100, len(with_alt), len(imgs), aria),
        {"aria": aria, "img": len(imgs), "with_alt": len(with_alt)}))

    durations = [float(d) for d in re.findall(r"transition[^;]*?(\d+)ms", html)]
    heavy = re.findall(r"transition\s*:\s*(?:all|width|height|top|left)", html, re.I)
    findings.append(Finding(
        "motion_performance", "warn" if (heavy or any(d > 400 for d in durations)) else "pass",
        "过渡时长 %s；触发布局动画 %d 处" % (durations or "未声明", len(heavy)),
        {"durations": durations, "layout_animations": len(heavy)}))

    if tokens:
        declared = {d.lower() for d in (tokens.get("color") or {}).values()}
        drift = sorted(u for u in colors if u not in declared)
        findings.append(Finding(
            "design_drift", "warn" if len(drift) > 5 else "pass",
            "非 token 色值 %d 个" % len(drift), {"drift_colors": drift[:12]}))
    else:
        findings.append(Finding("design_drift", "unmeasured", "无 token 基线，无法判定实现偏差"))

    counts = {}
    for f in findings:
        counts[f.status] = counts.get(f.status, 0) + 1
    return {
        "items": [f.as_dict() for f in findings],
        "counts": counts,
        "measured_items": len([f for f in findings if f.status != "unmeasured"]),
        "note": "unmeasured 表示当前输入不足以判定；不得当作通过。",
    }


# ---------------------------------------------------------------- 7 反馈回写

def feedback_unit(*, decision: str, evidence: str, scope: str,
                  category: str, source_url: str = "") -> Dict[str, Any]:
    """把设计任务的结论组装成待回写知识。

    scope=project 的结论只能进项目分区，不得直接升级为通用设计原则。
    """

    if scope not in ("project", "general"):
        raise ValueError("scope 必须是 project 或 general")
    text = "%s｜%s" % (decision, evidence)
    return {
        "title": decision[:120],
        "content": text,
        "category": category,
        "scope": scope,
        "partition": "project_knowledge" if scope == "project" else "pending_knowledge",
        "level": "L3" if scope == "general" else "L2",
        "verified": bool(source_url),
        "source_url": source_url,
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
