"""从公开页面提取「设计知识单元」并入库。

原则（对应需求六、七、八）：
- 只写入有独立意义的单元，不把整页正文灌进向量库；
- 每个单元过 16 字段模板，缺失字段如实记录为 extraction_gaps；
- 规则提取最多到 L2（已提取设计知识）；L3/L4 必须靠交叉验证与真实设计任务，本模块不虚标；
- L1（仅解析分类）落 pending 分区，L2（有一定结构）落 uiux 分区，但一律 unverified。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from bs4 import BeautifulSoup

from .taxonomy import CATEGORIES, EXTRACTION_FIELDS, EXTRACTION_MINIMUM, get_category

# ---------------------------------------------------------------- 抓取


def fetch_html(url: str, *, timeout: float = 45.0, max_bytes: int = 2_000_000) -> Tuple[str, str, int]:
    """抓取 HTML（已由 checker 做过 robots 判定）。返回 (html, final_url, status)。"""

    import httpx

    from .checker import UA

    with httpx.Client(follow_redirects=True, headers={"User-Agent": UA}, timeout=timeout) as client:
        with client.stream("GET", url) as resp:
            body = b""
            for chunk in resp.iter_bytes():
                body += chunk
                if len(body) >= max_bytes:
                    break
            return body.decode("utf-8", errors="ignore"), str(resp.url), resp.status_code


# ---------------------------------------------------------------- 解析


BLOCK_TAGS = ("script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg")


@dataclass
class Section:
    heading: str
    level: int
    text: str


def sectionize(html: str, *, min_chars: int = 120, max_chars: int = 900) -> List[Section]:
    """把页面拆成「标题 + 段落」的区块，丢弃导航/页脚/脚本。"""

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(BLOCK_TAGS):
        tag.decompose()

    sections: List[Section] = []
    current = Section(heading="", level=0, text="")
    for node in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "pre", "code"]):
        text = re.sub(r"[ \t]+", " ", node.get_text(" ", strip=True)).strip()
        if not text:
            continue
        if node.name in ("h1", "h2", "h3", "h4"):
            if len(current.text) >= min_chars:
                sections.append(current)
            current = Section(heading=text, level=int(node.name[1]), text="")
        else:
            sep = "\n" if node.name in ("pre", "code") else " "
            current.text = (current.text + sep + text).strip() if current.text else text

    if len(current.text) >= min_chars:
        sections.append(current)

    out: List[Section] = []
    for sec in sections:
        body = sec.text[:max_chars].strip()
        if len(body) < min_chars:
            continue
        out.append(Section(heading=sec.heading[:160], level=sec.level, text=body))
    return out



#: 设计语汇：一段文字要在「设计知识库」里有价值，至少得谈这些词里的几个。
DESIGN_TERMS = (
    "layout", "spacing", "padding", "margin", "grid", "align", "hierarchy", "whitespace",
    "typography", "font", "line-height", "type scale", "baseline",
    "color", "contrast", "palette", "tint", "shade", "dark mode", "theme",
    "component", "variant", "token", "design system", "component library",
    "motion", "animation", "transition", "easing", "duration", "gesture",
    "radius", "corner", "shadow", "elevation", "border", "divider",
    "gradient", "noise", "texture", "blur", "glow", "opacity",
    "accessib", "aria", "focus", "screen reader", "wcag", "a11y",
    "responsive", "breakpoint", "viewport", "media query", "adaptive",
    "icon", "illustration", "svg", "asset",
    "usability", "heuristic", "cognitive", "affordance", "feedback",
    "布局", "间距", "留白", "层级", "排版", "字体", "字号", "色彩", "对比度", "主题",
    "组件", "变体", "设计 token", "动效", "缓动", "圆角", "阴影", "渐变", "纹理",
    "无障碍", "焦点", "响应式", "断点", "图标", "素材", "可用性", "启发式",
)

#: 营销/销售话术特征：命中过多说明这是营销文案，不是设计知识。
MARKETING_TERMS = (
    "pricing", "contact sales", "sign up", "get started", "subscribe", "free trial",
    "customers", "case study", "roi", "revenue", "processes billions", "trusted by",
    "learn more", "book a demo", "talk to sales",
)

MIN_DESIGN_TERMS = 3


def design_relevance(text: str, *, min_terms: int = MIN_DESIGN_TERMS) -> dict:
    """算设计相关度：设计词命中数 / 营销词命中数 / 千字密度。"""

    low = text.lower()
    hits = sorted({t for t in DESIGN_TERMS if t in low})
    marketing = sorted({t for t in MARKETING_TERMS if t in low})
    density = (len(hits) * 1000.0 / max(len(low), 1))
    ok = len(hits) >= min_terms and len(marketing) <= 2
    return {
        "design_terms": hits,
        "design_term_count": len(hits),
        "marketing_terms": marketing,
        "density_per_1k": round(density, 2),
        "relevant": ok,
    }


# ---------------------------------------------------------------- 分类


def classify_all(text: str, *, heading: str = "") -> Dict[str, Tuple[float, List[str]]]:
    """返回全部分类的得分与命中词，供「领域先验」判定使用。"""

    blob = (heading + " " + text).lower()
    out: Dict[str, Tuple[float, List[str]]] = {}
    for key, cat in CATEGORIES.items():
        matched = [kw for kw in cat.keywords if kw.lower() in blob]
        if not matched:
            continue
        score = sum(2.0 if kw.lower() in heading.lower() else 1.0 for kw in matched)
        score += 0.15 * max(len(x) for x in matched)
        out[key] = (score, matched)
    return out


def classify_with_prior(text: str, *, heading: str, primary_category: str,
                        ) -> Tuple[str, float, List[str], str]:
    """领域先验优先的分类。

    关键词分类器只看词面，会把「游戏 HUD 文档」分到 web_ui。
    规则：若资源声明的主分类进入关键词打分的前两名，就采用主分类；
    否则采用关键词第一名。返回 (分类, 归一化分, 命中词, 判定来源)。
    """

    scores = classify_all(text, heading=heading)
    if not scores:
        return primary_category, 0.0, [], "fallback_primary"
    ranked = sorted(scores.items(), key=lambda kv: kv[1][0], reverse=True)
    top_keys = [k for k, _ in ranked[:2]]
    total = sum(v[0] for v in scores.values()) or 1.0
    if primary_category in top_keys:
        score, matched = scores[primary_category]
        return primary_category, round(score / total, 3), matched, "domain_prior"
    best, (score, matched) = ranked[0]
    return best, round(score / total, 3), matched, "keyword"


def classify(text: str, *, heading: str = "") -> Tuple[str, float, List[str]]:
    """按分类关键词给文本打分，返回 (主分类, 归一化得分, 命中词)。

    规则是确定性的：同一份文本永远得到同一个分类，便于复核与重跑对比。
    """

    blob = (heading + " " + text).lower()
    scores: Dict[str, float] = {}
    hits: Dict[str, List[str]] = {}
    for key, cat in CATEGORIES.items():
        matched = [kw for kw in cat.keywords if kw.lower() in blob]
        if not matched:
            continue
        # 标题命中加倍，长关键词权重更高
        score = sum(2.0 if kw.lower() in heading.lower() else 1.0 for kw in matched)
        score += 0.15 * max(len(x) for x in matched)
        scores[key] = score
        hits[key] = matched
    if not scores:
        return "uiux_principles", 0.0, []
    best = max(scores, key=lambda k: scores[k])
    total = sum(scores.values()) or 1.0
    return best, round(scores[best] / total, 3), hits[best]


# ---------------------------------------------------------------- 单元构造


def _first_sentences(text: str, limit: int = 240) -> str:
    parts = re.split(r"(?<=[。！？.!?])\s+", text.strip())
    out = ""
    for part in parts:
        if not part:
            continue
        out = (out + " " + part).strip()
        if len(out) >= limit:
            break
    return out[:limit]


def build_unit(
    section: Section,
    *,
    resource: Dict[str, Any],
    category: str,
    score: float,
    matched: Sequence[str],
    min_design_terms: int = MIN_DESIGN_TERMS,
) -> Dict[str, Any]:
    knowledge: Dict[str, str] = {name: "" for name in EXTRACTION_FIELDS}

    knowledge["core_principle"] = _first_sentences(section.text)
    # 只填能从正文低风险推断的字段；其余留空，不编
    normative = bool(re.search(r"(should|must|recommend|建议|应当|必须|不要|避免|prefer|avoid)", section.text, re.I))
    if normative:
        knowledge["applicable_context"] = "正文给出显式约束或建议的场合（文本推断，未做任务验证）"
    elif section.heading:
        knowledge["applicable_context"] = "原文小节语境：%s" % section.heading[:80]
    if re.search(r"(\d+(\.\d+)?\s*(px|dp|sp|rem|em|%))", section.text):
        knowledge["layout_rule"] = "正文包含具体尺寸/间距数值：" + ", ".join(
            re.findall(r"\d+(?:\.\d+)?\s*(?:px|dp|sp|rem|em|%)", section.text)[:6]
        )
    if re.search(r"#(?:[0-9a-f]{3}|[0-9a-f]{6})\b|rgb\(|hsl\(", section.text, re.I):
        knowledge["color_rule"] = "正文包含颜色值：" + ", ".join(
            re.findall(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b|rgba?\([^)]*\)|hsla?\([^)]*\)", section.text)[:4]
        )
    if re.search(r"(gradient|渐变|noise|噪|blur|光晕|shadow|纹理)", section.text, re.I):
        knowledge["background_method"] = "正文涉及渐变/噪点/光影等背景手法的处理方式"
    if re.search(r"(contrast|accessible|wcag|aria|无障碍|对比度)", section.text, re.I):
        knowledge["a11y_requirement"] = "正文涉及可访问性或对比度要求（具体阈值需回查原文核对）"
    if re.search(r"(animation|transition|easing|动效|缓动)", section.text, re.I):
        knowledge["interaction_rule"] = "正文涉及动效或过渡的实现/时长说明"
    if re.search(r"(performance|latency|jank|fps|性能|卡顿)", section.text, re.I):
        knowledge["performance_note"] = "正文涉及性能或流畅度约束"
    if re.search(r"(don't|avoid|never|反模式|避免|错误做法)", section.text, re.I):
        knowledge["anti_pattern"] = "正文提到应当避免的做法（原文措辞，未做效果验证）"

    knowledge["source_ref"] = resource["url"]
    knowledge["license_note"] = resource["license_notes"]
    # 等级必须由实际完成的工作决定：只有「原则 + 显式约束语境」才算 L2，
    # 仅解析出段落并归类的是 L1；两者都不算已验证。
    level = "L2" if (knowledge["core_principle"] and normative) else "L1"
    knowledge["evidence_level"] = level
    filled = [k for k, v in knowledge.items() if v]
    complete = all(knowledge[k] for k in EXTRACTION_MINIMUM)

    relevance = design_relevance(section.text, min_terms=min_design_terms)
    return {
        "category": category,
        "relevance": relevance,
        "category_score": score,
        "matched_keywords": list(matched),
        "heading": section.heading,
        "text": section.text,
        "knowledge": knowledge,
        "fields_filled": filled,
        "extraction_gaps": [k for k in EXTRACTION_FIELDS if not knowledge[k]],
        "level": level,
        "ready_to_ingest": bool(complete and relevance["relevant"]),
        "content_hash": hashlib.sha256(
            re.sub(r"\s+", " ", section.text).strip().lower().encode("utf-8")
        ).hexdigest(),
    }


def summarize_unit(unit: Dict[str, Any], resource: Dict[str, Any]) -> Dict[str, Any]:
    """把单元压成引擎 Chunk 的字段映射（内容仍然来自原文，不伪造）。"""

    cat = get_category(unit["category"])
    return {
        "topic": unit["category"],
        "subtopic": unit["heading"][:120],
        "title": (unit["heading"] or resource["name"])[:160],
        "content": unit["text"],
        "summary": unit["knowledge"]["core_principle"][:400],
        "metadata": {
            "secondary_categories": [c for c in resource.get("secondary_categories", []) if c != unit["category"]],
            "resource_id": resource["resource_id"],
            "category_label": cat.label,
            "category_score": unit["category_score"],
            "matched_keywords": unit["matched_keywords"],
            "extraction": unit["knowledge"],
            "extraction_gaps": unit["extraction_gaps"],
            "fields_filled": unit["fields_filled"],
        },
    }
