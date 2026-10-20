"""资料发现。

三条来源通道：
1. 显式 URL / 本地路径（由 Agent 或用户提供）——最可靠，优先使用；
2. 本地语料目录扫描（默认 ``data/corpus``，按扩展名与关键词筛选）；
3. 可注入的 web 搜索适配器（默认关闭）。DSH Agent 自己具备网页搜索工具，
   因此推荐流程是：Agent 搜索后把候选 URL 通过 ``discover_sources`` 传进来，
   由本插件负责去重、元数据补全与抓取预算控制——避免插件内再实现一套搜索。

不做的事情：不猜测站点结构去爬取、不绕过登录/付费墙、不下载未知可执行文件。
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from ..config import SecurityConfig
from ..core.models import SourceType
from . import metadata as meta

_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "spm",
    "from",
    "fr",
    "ref",
}

DEFAULT_PATTERNS = ("*.md", "*.txt", "*.rst", "*.html", "*.htm", "*.pdf", "*.docx", "*.py", "*.rs", "*.kt", "*.ts", "*.java", "*.json")


@dataclass
class Candidate:
    location: str
    title: str = ""
    source_type: str = SourceType.UNKNOWN.value
    quality: float = 0.0
    quality_basis: str = ""
    reason: str = ""
    published_at: str = ""
    doc_type: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "location": self.location,
            "title": self.title,
            "source_type": self.source_type,
            "quality": self.quality,
            "quality_basis": self.quality_basis,
            "reason": self.reason,
            "published_at": self.published_at,
            "doc_type": self.doc_type,
        }


def normalize_url(url: str) -> str:
    """去掉跟踪参数与末尾斜杠，用于去重。"""

    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    if not parsed.scheme:
        return url
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=False) if k.lower() not in _TRACKING_PARAMS]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.params, urlencode(query), ""))


class SourceDiscovery:
    def __init__(self, security: SecurityConfig, *, corpus_dir: Optional[str | Path] = None) -> None:
        self.security = security
        self.corpus_dir = Path(corpus_dir) if corpus_dir else None

    # ------------------------------------------------------------------ #
    def from_explicit(self, locations: Sequence[str], reason: str = "agent_provided") -> List[Candidate]:
        out: List[Candidate] = []
        for loc in locations:
            loc = (loc or "").strip()
            if not loc:
                continue
            if loc.startswith(("http://", "https://")):
                info = meta.describe_source(loc)
                out.append(
                    Candidate(
                        location=normalize_url(loc),
                        title=info["title"] or loc,
                        source_type=info["source_type"],
                        quality=info["quality"],
                        quality_basis=info["quality_basis"],
                        reason=reason,
                    )
                )
            else:
                path = Path(loc).expanduser()
                if not path.exists():
                    out.append(Candidate(location=loc, reason="not_found", quality=0.0))
                    continue
                if path.is_dir():
                    out.extend(self.scan_local(path, reason="dir_from_agent"))
                else:
                    info = meta.describe_source(str(path))
                    out.append(
                        Candidate(
                            location=str(path),
                            title=path.name,
                            source_type=info["source_type"],
                            quality=info["quality"],
                            quality_basis=info["quality_basis"],
                            reason=reason,
                            doc_type=path.suffix.lower().lstrip("."),
                        )
                    )
        return out

    def scan_local(
        self,
        directory: Path,
        *,
        patterns: Sequence[str] = DEFAULT_PATTERNS,
        keywords: Sequence[str] = (),
        limit: int = 200,
        reason: str = "local_corpus",
    ) -> List[Candidate]:
        if not directory.exists():
            return []
        results: List[Candidate] = []
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"node_modules", "__pycache__", ".git"}]
            for name in files:
                if len(results) >= limit:
                    return results
                if not any(fnmatch.fnmatch(name.lower(), pat.lower()) for pat in patterns):
                    continue
                path = Path(root) / name
                if keywords:
                    haystack = f"{path.name}".lower()
                    if not any(k.lower() in haystack for k in keywords):
                        continue
                try:
                    if path.stat().st_size > self.security.max_download_bytes:
                        continue
                except OSError:
                    continue
                info = meta.describe_source(str(path), title=path.stem)
                results.append(
                    Candidate(
                        location=str(path),
                        title=path.stem,
                        source_type=info["source_type"],
                        quality=info["quality"],
                        quality_basis=info["quality_basis"],
                        reason=reason,
                        doc_type=path.suffix.lower().lstrip("."),
                    )
                )
        return results

    def discover(
        self,
        *,
        topics: Sequence[str] = (),
        explicit_locations: Sequence[str] | None = None,
        include_corpus: bool = True,
        keywords: Sequence[str] = (),
        limit: int = 30,
        web_search: Optional[Callable[[str, int], List[Dict[str, Any]]]] = None,
    ) -> Dict[str, Any]:
        """汇总候选来源并去重排序。"""

        warnings: List[str] = []
        candidates: List[Candidate] = []

        if explicit_locations:
            candidates.extend(self.from_explicit(explicit_locations))
        if include_corpus and self.corpus_dir and self.corpus_dir.exists():
            candidates.extend(
                self.scan_local(
                    self.corpus_dir,
                    keywords=keywords or topics,
                    limit=limit,
                )
            )
        if web_search and topics:
            if not self.security.allow_network:
                warnings.append("未开启 security.allow_network，已跳过 web 搜索通道")
            else:
                for topic in topics[:5]:
                    try:
                        for hit in web_search(topic, min(limit, 8)) or []:
                            url = hit.get("url") or hit.get("location") or ""
                            if not url:
                                continue
                            info = meta.describe_source(url, title=hit.get("title", ""))
                            candidates.append(
                                Candidate(
                                    location=normalize_url(url),
                                    title=hit.get("title", "") or url,
                                    source_type=info["source_type"],
                                    quality=info["quality"],
                                    quality_basis=info["quality_basis"],
                                    reason="web_search",
                                    published_at=hit.get("published_at", ""),
                                )
                            )
                    except Exception as exc:  # noqa: BLE001
                        warnings.append(f"web 搜索失败（{topic}）: {exc}")

        deduped: Dict[str, Candidate] = {}
        for cand in candidates:
            if cand.reason == "not_found":
                warnings.append(f"来源不存在，已跳过: {cand.location}")
                continue
            key = normalize_url(cand.location)
            existing = deduped.get(key)
            if existing is None or cand.quality > existing.quality:
                deduped[key] = cand

        ordered = sorted(deduped.values(), key=lambda c: (-c.quality, c.location))[:limit]
        return {
            "candidates": [c.to_dict() for c in ordered],
            "total_found": len(candidates),
            "total_after_dedupe": len(deduped),
            "returned": len(ordered),
            "warnings": warnings,
        }


__all__ = [
    "Candidate",
    "DEFAULT_PATTERNS",
    "SourceDiscovery",
    "normalize_url",
]
