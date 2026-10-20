"""文档解析与切块。

原则：
- 只做确定性文本处理，不在这里调用模型；
- 解析失败必须显式报告原因，不允许"静默返回空字符串"；
- 切块按语义边界（标题/段落/代码块）优先，硬切只在超长段落时兜底。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

_HTML_DROP_TAGS = [
    "script",
    "style",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "noscript",
    "iframe",
    "svg",
]
_HTML_BLOCK_TAGS = ["p", "div", "section", "article", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr"]
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_CODE_FENCE_RE = re.compile(r"```([A-Za-z0-9_+#.\-]*)\n(.*?)```", re.S)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


class ParseError(RuntimeError):
    """文档解析失败。"""


# --------------------------------------------------------------------------- #
# HTML / Markdown
# --------------------------------------------------------------------------- #
def html_to_text(html: str) -> Tuple[str, str]:
    """HTML -> 纯文本，返回 (title, text)。"""

    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ParseError("解析 HTML 需要 beautifulsoup4，请先安装") from exc

    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(_HTML_DROP_TAGS):
        tag.decompose()
    for tag in soup(_HTML_BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    text = soup.get_text("\n")
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return title, text.strip()


def markdown_to_text(md: str) -> str:
    """保留结构信息的 Markdown 纯文本化（标题行保留 #，便于后续分段）。"""

    text = md or ""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)  # 图片
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)  # 链接保留文字
    text = re.sub(r"^\s{0,3}>\s?", "", text, flags=re.M)  # 引用
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_markup(text: str, doc_type: str = "text") -> str:
    if doc_type in {"html", "htm"}:
        return html_to_text(text)[1]
    if doc_type in {"markdown", "md"}:
        return markdown_to_text(text)
    return (text or "").strip()


# --------------------------------------------------------------------------- #
# 语言与结构
# --------------------------------------------------------------------------- #
def detect_language(text: str) -> str:
    sample = (text or "")[:4000]
    if not sample.strip():
        return "unknown"
    cjk = len(_CJK_RE.findall(sample))
    latin = len(re.findall(r"[A-Za-z]", sample))
    if cjk == 0 and latin == 0:
        return "unknown"
    if cjk >= max(10, latin * 0.25):
        return "zh"
    return "en"


def extract_code_blocks(text: str) -> List[Dict[str, str]]:
    blocks: List[Dict[str, str]] = []
    for match in _CODE_FENCE_RE.finditer(text or ""):
        code = match.group(2).rstrip()
        if code.strip():
            blocks.append({"language": (match.group(1) or "text").lower(), "code": code})
    return blocks


@dataclass
class Section:
    heading: str = ""
    level: int = 0
    text: str = ""
    index: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"heading": self.heading, "level": self.level, "text": self.text, "index": self.index}


def split_sections(text: str) -> List[Section]:
    """按 Markdown 标题 / 编号标题 / 空行段落切分章节。"""

    lines = (text or "").splitlines()
    sections: List[Section] = []
    current = Section(heading="", level=0)
    buffer: List[str] = []

    def flush() -> None:
        nonlocal current, buffer
        body = "\n".join(buffer).strip()
        if body or current.heading:
            current.text = body
            current.index = len(sections)
            sections.append(current)
        buffer = []

    for line in lines:
        match = _HEADING_RE.match(line.strip())
        if match:
            flush()
            current = Section(heading=match.group(2).strip(), level=len(match.group(1)))
            continue
        buffer.append(line)
    flush()
    if not sections:
        sections = [Section(heading="", level=0, text=(text or "").strip(), index=0)]
    return [s for s in sections if s.text or s.heading]


# --------------------------------------------------------------------------- #
# 切块
# --------------------------------------------------------------------------- #
def chunk_text(
    text: str,
    *,
    chunk_size: int = 900,
    overlap: int = 120,
    min_chars: int = 40,
    max_chunks: int = 400,
) -> List[str]:
    """按段落聚合切块；超长段落按句子/硬切兜底，带重叠。"""

    text = (text or "").strip()
    if not text:
        return []
    chunk_size = max(120, int(chunk_size))
    overlap = max(0, min(int(overlap), chunk_size // 2))
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    units: List[str] = []
    for para in paragraphs:
        if len(para) <= chunk_size:
            units.append(para)
            continue
        # 长段落按句子切
        sentences = re.split(r"(?<=[。！？.!?；;])\s*", para)
        buf = ""
        for sentence in sentences:
            if not sentence:
                continue
            if len(buf) + len(sentence) <= chunk_size:
                buf += sentence
            else:
                if buf:
                    units.append(buf)
                while len(sentence) > chunk_size:
                    units.append(sentence[:chunk_size])
                    sentence = sentence[chunk_size - overlap :]
                buf = sentence
        if buf:
            units.append(buf)

    chunks: List[str] = []
    current = ""
    for unit in units:
        if not current:
            current = unit
        elif len(current) + len(unit) + 2 <= chunk_size:
            current = f"{current}\n\n{unit}"
        else:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            current = f"{tail}\n\n{unit}".strip() if tail else unit
    if current:
        chunks.append(current)

    cleaned: List[str] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if len(chunk) < min_chars:
            if cleaned:
                cleaned[-1] = f"{cleaned[-1]}\n\n{chunk}".strip()
            elif chunk:
                cleaned.append(chunk)
            continue
        cleaned.append(chunk)
    return cleaned[:max_chunks]


def summarize(text: str, max_chars: int = 160) -> str:
    """抽取式摘要：取首句 + 关键句，不调用模型。"""

    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= max_chars:
        return text
    sentences = re.split(r"(?<=[。！？.!?])\s*", text)
    summary = ""
    for sentence in sentences:
        if len(summary) + len(sentence) > max_chars:
            break
        summary += sentence
    if not summary:
        summary = text[:max_chars]
    return summary.strip() + "…"


__all__ = [
    "ParseError",
    "Section",
    "chunk_text",
    "detect_language",
    "extract_code_blocks",
    "html_to_text",
    "markdown_to_text",
    "split_sections",
    "strip_markup",
    "summarize",
]
