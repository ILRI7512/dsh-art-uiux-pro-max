"""中英设计术语桥接。

背景：知识库正文以英文为主，而使用者用中文提问。
离线特征哈希 embedder 与 BM25 都无法跨语言匹配，实测中文查询的召回率接近 0。

做法：维护一张**设计领域**的中英术语表（不是通用翻译），命中即把英文等价词追加到查询里。
这是确定性扩展，可复核、无模型依赖；扩展了什么会写进返回值的 `bilingual` 字段。
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

#: 只收设计领域高频词，避免引入无关歧义。
LEXICON: Dict[str, str] = {
    "对比度": "contrast ratio",
    "可读性": "readability legibility",
    "留白": "whitespace spacing",
    "间距": "spacing gap",
    "排版": "typography type scale",
    "字体": "font typeface",
    "字号": "font size",
    "行高": "line height leading",
    "圆角": "border radius",
    "阴影": "box shadow elevation",
    "边框": "border outline",
    "渐变": "gradient",
    "噪点": "noise texture",
    "纹理": "texture",
    "光晕": "glow blur",
    "背景": "background",
    "配色": "color palette",
    "色板": "palette swatches",
    "主题": "theme theming",
    "语义色": "semantic color",
    "深色模式": "dark mode",
    "图标": "icon",
    "插画": "illustration",
    "矢量": "svg vector",
    "组件": "component",
    "设计系统": "design system",
    "设计令牌": "design tokens",
    "变量": "css variables custom properties",
    "动效": "animation motion",
    "动画": "animation",
    "过渡": "transition",
    "缓动": "easing curve",
    "手势": "gesture",
    "无障碍": "accessibility a11y",
    "焦点": "focus focus-visible",
    "屏幕阅读器": "screen reader",
    "触控目标": "touch target hit area",
    "响应式": "responsive breakpoints",
    "断点": "breakpoint media query",
    "自适应": "adaptive window size class",
    "栅格": "grid columns",
    "布局": "layout",
    "表头": "table header",
    "表格": "table",
    "仪表盘": "dashboard",
    "行情": "market ticker quote",
    "持仓": "position portfolio",
    "金融": "financial",
    "游戏": "game hud",
    "技能栏": "skill bar",
    "背包": "inventory",
    "按钮": "button",
    "输入框": "text field input",
    "弹窗": "dialog modal",
    "提示": "tooltip toast snackbar",
    "加载": "loading spinner skeleton",
    "许可": "license",
    "测试": "test testing",
    "性能": "performance",
    "可用性": "usability heuristic",
    "认知负荷": "cognitive load",
    "构图": "composition",
    "视觉层级": "visual hierarchy",
}

_CJK = re.compile(r"[\u4e00-\u9fff]")


def expand(query: str) -> Tuple[str, List[Dict[str, str]]]:
    """返回 (扩展后的查询, 命中明细)。没有命中中文术语就原样返回。"""

    if not _CJK.search(query or ""):
        return query, []
    hits: List[Dict[str, str]] = []
    extra: List[str] = []
    for zh, en in LEXICON.items():
        if zh in query:
            hits.append({"zh": zh, "en": en})
            extra.append(en)
    if not extra:
        return query, []
    return (query + " " + " ".join(extra)).strip(), hits
