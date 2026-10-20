"""来源元数据：类型、质量、许可、时效。

这里的分数是**启发式先验**，不是事实判断：
- 它只用于排序与"是否需要交叉验证"的提示；
- 最终是否可信由核验记录与证据决定（见 core/state_machine.py）；
- 任何先验都必须把依据（basis）一并落库，便于审计。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from ..core.models import FreshnessStatus, LicenseStatus, SourceType

# 官方/标准/论文来源的域名白名单（命中则提高先验质量）
OFFICIAL_DOMAINS = {
    "developer.android.com",
    "developer.mozilla.org",
    "docs.python.org",
    "doc.rust-lang.org",
    "kotlinlang.org",
    "www.w3.org",
    "w3.org",
    "www.ietf.org",
    "ietf.org",
    "www.iso.org",
    "iso.org",
    "docs.oracle.com",
    "learn.microsoft.com",
    "www.rfc-editor.org",
    "arxiv.org",
    "dl.acm.org",
    "ieeexplore.ieee.org",
    "www.nature.com",
    "www.sciencedirect.com",
    "pubmed.ncbi.nlm.nih.gov",
    "github.com",
    "gitlab.com",
    "www.material.io",
    "m3.material.io",
    "m2.material.io",
    "www.nngroup.com",
    "www.w3.org/WAI",
}
STANDARD_HINTS = ("rfc", "iso", "iec", "ieee", "gb/t", "gb ", "standard", "specification")
PAPER_HINTS = ("doi:", "arxiv", "abstract", "et al.", "论文", "研究")
DOC_EXTENSIONS = {".md", ".markdown", ".rst", ".txt", ".pdf", ".docx", ".html", ".htm", ".ipynb"}
CODE_EXTENSIONS = {".py", ".rs", ".kt", ".java", ".ts", ".tsx", ".js", ".jsx", ".go", ".c", ".cpp", ".h", ".cs", ".rb", ".php", ".sh", ".sql"}

LICENSE_BY_DOMAIN = {
    "developer.mozilla.org": (LicenseStatus.PERMITTED.value, "MDN 内容采用 CC-BY-SA 2.5"),
    "docs.python.org": (LicenseStatus.PERMITTED.value, "Python 文档许可（PSF）"),
    "developer.android.com": (LicenseStatus.PERMITTED.value, "Android 文档 CC-BY 4.0"),
    "doc.rust-lang.org": (LicenseStatus.PERMITTED.value, "Rust 文档 MIT/Apache-2.0 双许可"),
    "www.w3.org": (LicenseStatus.PERMITTED.value, "W3C 文档许可"),
    "wikipedia.org": (LicenseStatus.PERMITTED.value, "CC-BY-SA"),
    "zh.wikipedia.org": (LicenseStatus.PERMITTED.value, "CC-BY-SA"),
    "arxiv.org": (LicenseStatus.RESTRICTED.value, "作者保留部分权利，需逐篇确认"),
}

# 时效半衰期（天）：不同领域知识老化速度不同
FRESHNESS_HALF_LIFE_DAYS = {
    SourceType.OFFICIAL_DOC.value: 730,
    SourceType.STANDARD.value: 1825,
    SourceType.PAPER.value: 3650,
    SourceType.TECH_DOC.value: 540,
    SourceType.CODE_REPO.value: 365,
    SourceType.WEB_PAGE.value: 365,
    SourceType.LOCAL_FILE.value: 730,
    SourceType.USER_NOTE.value: 365,
    SourceType.EXPERIMENT.value: 3650,
    SourceType.UNKNOWN.value: 365,
}


def classify_source(location: str, *, doc_type: str = "", title: str = "") -> str:
    """根据 URL/路径/标题判断来源类型。"""

    loc = (location or "").lower()
    parsed = urlparse(loc) if loc.startswith(("http://", "https://")) else None
    host = (parsed.netloc.lower() if parsed else "")
    suffix = ""
    if "." in loc.rsplit("/", 1)[-1]:
        suffix = "." + loc.rsplit(".", 1)[-1]

    if host in {"github.com", "gitlab.com"} or "/repos/" in loc or loc.endswith(".git"):
        return SourceType.CODE_REPO.value
    if any(h in host for h in ("arxiv.org", "dl.acm.org", "ieee", "nature.com", "sciencedirect", "pubmed")):
        return SourceType.PAPER.value
    if any(token in (title or "").lower() for token in STANDARD_HINTS) or host in {"www.w3.org", "w3.org", "www.iso.org", "iso.org", "www.rfc-editor.org"}:
        return SourceType.STANDARD.value
    if host in OFFICIAL_DOMAINS:
        return SourceType.OFFICIAL_DOC.value
    if doc_type in {"pdf"}:
        return SourceType.PAPER.value
    if suffix in CODE_EXTENSIONS:
        return SourceType.CODE_REPO.value
    if suffix in DOC_EXTENSIONS and not host:
        return SourceType.LOCAL_FILE.value
    if host:
        return SourceType.WEB_PAGE.value
    if not host and location:
        return SourceType.LOCAL_FILE.value
    return SourceType.UNKNOWN.value


def source_quality(source_type: str, location: str = "", publisher: str = "") -> Tuple[float, str]:
    """来源质量先验 + 依据说明。"""

    base = {
        SourceType.OFFICIAL_DOC.value: 0.90,
        SourceType.STANDARD.value: 0.92,
        SourceType.PAPER.value: 0.85,
        SourceType.TECH_DOC.value: 0.75,
        SourceType.CODE_REPO.value: 0.70,
        SourceType.WEB_PAGE.value: 0.50,
        SourceType.LOCAL_FILE.value: 0.60,
        SourceType.USER_NOTE.value: 0.45,
        SourceType.EXPERIMENT.value: 0.65,
        SourceType.UNKNOWN.value: 0.35,
    }.get(source_type, 0.4)

    parsed = urlparse(location or "")
    host = parsed.netloc.lower()
    basis = [f"来源类型={source_type}"]
    if host:
        basis.append(f"域名={host}")
        if host in OFFICIAL_DOMAINS:
            base = min(1.0, base + 0.05)
            basis.append("命中官方/权威域名白名单 +0.05")
        if host.endswith(".edu") or host.endswith(".gov") or host.endswith(".ac.cn"):
            base = min(1.0, base + 0.03)
            basis.append("教育/政府域名 +0.03")
    if publisher:
        basis.append(f"发布机构={publisher}")
    if not parsed.scheme and location:
        basis.append("本地文件，质量取决于原始出处")
    return round(min(1.0, base), 3), "；".join(basis)


def guess_license(location: str, source_type: str = "") -> Tuple[str, str]:
    parsed = urlparse(location or "")
    host = parsed.netloc.lower().replace("www.", "")
    for domain, (status, note) in LICENSE_BY_DOMAIN.items():
        if host == domain.replace("www.", "") or host.endswith("." + domain.replace("www.", "")):
            return status, note
    if not parsed.scheme:
        return LicenseStatus.UNKNOWN.value, "本地文件：许可未知，需人工确认来源与授权"
    if source_type in {SourceType.PAPER.value, SourceType.WEB_PAGE.value}:
        return LicenseStatus.UNKNOWN.value, "网页/论文：未自动判定许可，转载或商用前需确认"
    if source_type in {SourceType.CODE_REPO.value}:
        return LicenseStatus.UNKNOWN.value, "代码仓库：需检查仓库 LICENSE 文件"
    return LicenseStatus.UNKNOWN.value, "未判定"


def parse_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y年%m月%d日",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def freshness_status(
    published_at: str = "", source_type: str = SourceType.UNKNOWN.value, now: Optional[datetime] = None
) -> Tuple[str, str]:
    """时效状态 + 依据。"""

    now = now or datetime.now(timezone.utc)
    published = parse_datetime(published_at)
    if published is None:
        return FreshnessStatus.UNKNOWN.value, "未提供发布时间，无法判定时效"
    age_days = (now - published).days
    half_life = FRESHNESS_HALF_LIFE_DAYS.get(source_type, 365)
    if age_days < 0:
        return FreshnessStatus.UNKNOWN.value, "发布时间晚于当前时间，数据可能有误"
    if age_days <= half_life * 0.5:
        status = FreshnessStatus.FRESH.value
    elif age_days <= half_life:
        status = FreshnessStatus.AGING.value
    elif age_days <= half_life * 2:
        status = FreshnessStatus.STALE.value
    else:
        status = FreshnessStatus.EXPIRED.value
    return status, f"距发布 {age_days} 天，该类型半衰期 {half_life} 天"


def extract_publisher(location: str, title: str = "") -> str:
    parsed = urlparse(location or "")
    if parsed.netloc:
        return parsed.netloc.lower()
    return ""


def describe_source(
    location: str, *, title: str = "", published_at: str = "", doc_type: str = ""
) -> Dict[str, Any]:
    """生成一份完整的来源元数据（不含抓取结果）。"""

    source_type = classify_source(location, doc_type=doc_type, title=title)
    quality, basis = source_quality(source_type, location, extract_publisher(location))
    license_status, license_note = guess_license(location, source_type)
    fresh, fresh_basis = freshness_status(published_at, source_type)
    return {
        "source_type": source_type,
        "quality": quality,
        "quality_basis": basis,
        "license_status": license_status,
        "license_note": license_note,
        "freshness_status": fresh,
        "freshness_basis": fresh_basis,
        "publisher": extract_publisher(location, title),
        "title": title,
        "published_at": published_at,
    }


def is_paywalled_or_login(location: str) -> bool:
    """明显需要登录/付费的站点：不绕过，直接记录失败原因。"""

    host = urlparse(location or "").netloc.lower()
    blocked = (
        "linkedin.com",
        "facebook.com",
        "instagram.com",
        "x.com",
        "twitter.com",
        "weibo.com",
        "zhihu.com/people",
        "patreon.com",
        "udemy.com",
    )
    return any(host.endswith(b) or b in host for b in blocked)


__all__ = [
    "CODE_EXTENSIONS",
    "DOC_EXTENSIONS",
    "FRESHNESS_HALF_LIFE_DAYS",
    "LICENSE_BY_DOMAIN",
    "OFFICIAL_DOMAINS",
    "classify_source",
    "describe_source",
    "extract_publisher",
    "freshness_status",
    "guess_license",
    "is_paywalled_or_login",
    "parse_datetime",
    "source_quality",
]
