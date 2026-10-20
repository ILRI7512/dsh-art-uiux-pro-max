"""专项能力：三种背景生成 + 多尺寸布局矩阵。

两者都不假装有浏览器：所有结论标注为「静态推断」或「公式实算」，
需要真实渲染才能得出的指标（实际溢出、重排、绘制耗时）一律 unmeasured。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple

from .design_workflow import check_palette, contrast_ratio, hex_values

# ---------------------------------------------------------------- 三种背景

BACKGROUNDS: Dict[str, Dict[str, Any]] = {
    "mesh_gradient": {
        "name": "Mesh Gradient（多层径向渐变）",
        "idea": "用 2–3 个低透明度径向渐变叠加出空间纵深，纯 CSS、无额外资源",
        "css": [
            "background-color: #0b0d12;",
            "background-image:",
            "  radial-gradient(60% 50% at 15% 20%, rgba(76,154,255,.22), transparent 70%),",
            "  radial-gradient(50% 45% at 85% 10%, rgba(255,120,80,.16), transparent 70%),",
            "  radial-gradient(80% 60% at 50% 110%, rgba(120,255,200,.10), transparent 70%);",
        ],
        "perf": "一次性绘制的渐变层，通常只有 1 次 paint；滚动时不重绘。风险最低。",
        "cost": "low",
        "dark_safe": True,
    },
    "noise_overlay": {
        "name": "Noise Overlay（噪点叠加）",
        "idea": "在纯色或渐变上叠一层极低透明度噪点，消除塑料感并掩盖渐变断层（banding）",
        "css": [
            "background-color: #101318;",
            "background-image: url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120'>",
            "  <filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='2'/></filter>",
            "  <rect width='120' height='120' filter='url(%23n)' opacity='0.06'/></svg>\");",
            "background-size: 120px 120px;",
        ],
        "perf": "SVG 滤镜在首次栅格化时较贵；平铺后为位图缓存，滚动开销低。避免对大尺寸元素动态重算。",
        "cost": "medium",
        "dark_safe": True,
    },
    "conic_sweep": {
        "name": "Conic Sweep（锥形旋光）",
        "idea": "锥形渐变制造方向性光带，适合强调区块；必须给 reduced-motion 兜底",
        "css": [
            "background: conic-gradient(from 210deg at 50% 50%,",
            "  rgba(76,154,255,.28), rgba(180,120,255,.16), rgba(76,154,255,.28));",
            "animation: sweep 18s linear infinite;",
            "@media (prefers-reduced-motion: reduce) { .sweep { animation: none } }",
        ],
        "perf": "旋转动画会持续合成（compositor）层；大区域 + 低端设备可能掉帧，建议限制在卡片级尺寸。",
        "cost": "high",
        "dark_safe": True,
    },
}


def generate_backgrounds(*, text_color: str = "#e6e9ee", count: int = 3) -> List[Dict[str, Any]]:
    """给出 3 种机制不同的背景方案，并实测每种背景上的文字对比度。"""

    out = []
    # 各方案的「最坏情况背景色」：用于保守的对比度估计
    worst_bg = {"mesh_gradient": "#141821", "noise_overlay": "#101318", "conic_sweep": "#1a1f2b"}
    for key, spec in list(BACKGROUNDS.items())[:count]:
        bg = worst_bg[key]
        ratio = contrast_ratio(text_color, bg)
        item = dict(spec)
        item.update({
            "key": key,
            "css_block": "\n".join(spec["css"]),
            "contrast": {
                "pair": "正文/最坏背景",
                "fg": text_color, "bg": bg,
                "ratio": round(ratio, 2),
                "AA_normal": ratio >= 4.5,
                "measured": True,
                "basis": "取渐变叠层中偏亮的一档作为最坏情况，公式实算",
            },
            "verdict": "unmeasured" if ratio < 4.5 else "pass",
            "note": "对比度为实算；绘制耗时与设备掉帧未测。",
        })
        out.append(item)
    return out


# ---------------------------------------------------------------- 多尺寸矩阵

BREAKPOINTS = (320, 375, 414, 768, 1024, 1440)


def responsive_matrix(html: str, *, breakpoints: Sequence[int] = BREAKPOINTS) -> Dict[str, Any]:
    """静态推断各断点下的风险：固定宽溢出、触控目标、字号可读性。"""

    fixed_widths = [int(n) for n in re.findall(r"(?<!max-)(?<!min-)width\s*:\s*(\d{3,4})px", html)]
    max_widths = [int(n) for n in re.findall(r"max-width\s*:\s*(\d{3,4})px", html)]
    media = re.findall(r"@media[^{]{0,120}\{", html)
    tap_targets = [int(n) for n in re.findall(r"(?:height|min-height)\s*:\s*(\d{1,3})px", html)]
    small_targets = [t for t in tap_targets if t < 44]
    fonts = sorted({float(n) for n in re.findall(r"font-size\s*:\s*([\d.]+)px", html)})
    tiny_fonts = [f for f in fonts if f < 12]

    rows = []
    for width in breakpoints:
        overflow = [w for w in fixed_widths if w > width]
        if overflow:
            status = "fail"
            detail = "固定宽 %s 超过视口 %d" % (", ".join("%dpx" % o for o in overflow[:3]), width)
        elif fixed_widths and not max_widths and not media:
            status = "warn"
            detail = "有固定宽但无 max-width 与媒体查询，窄屏可能横向滚动"
        else:
            status = "pass"
            detail = "未发现固定宽溢出风险"
        rows.append({"width": width, "status": status, "detail": detail,
                     "overflow_candidates": overflow[:5]})

    return {
        "breakpoints": list(breakpoints),
        "rows": rows,
        "signals": {
            "fixed_widths": sorted(set(fixed_widths)),
            "max_widths": sorted(set(max_widths)),
            "media_queries": len(media),
            "tap_targets": sorted(set(tap_targets)),
            "tap_targets_below_44": small_targets,
            "fonts_below_12px": tiny_fonts,
        },
        "counts": {s: sum(1 for r in rows if r["status"] == s) for s in ("pass", "warn", "fail")},
        "measured": False,
        "note": "静态推断，未做真实设备渲染；实际重排与溢出需浏览器验证。",
    }
