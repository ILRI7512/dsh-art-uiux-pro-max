"""冲突检测（绝不"删掉其中一个"）。

检测三类矛盾信号：
1. 数值矛盾：同一语境（上下文 token 高度重叠）下，数值 + 单位不一致；
2. 极性矛盾：同一主语的肯定/否定表述相反（支持 vs 不支持、可以 vs 不可以…）；
3. 显式否定：一句话在另一句基础上插入否定词（"X 支持 Y" vs "X 不支持 Y"）。

所有判定都会写进 ``conflicts`` 表并保留双方证据；
检测为近重复（相似度 >= 去重阈值）时按重复处理，不制造伪冲突。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from ..core.models import ConflictStatus, RelationType, new_id, utcnow_iso
from ..storage.metadata_store import ChunkFilter, MetadataStore
from ..storage.tokenizer import tokenize
from ..storage.vector_store import KnowledgeStore

_NUM_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(%|％|倍|ms|毫秒|秒|px|dp|sp|美元|元|手|点|天|年|个月)?")
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？；;])\s*|(?<=[.!?])(?=\s)|\n")
_NEGATORS = ("不", "未", "没有", "无", "非", "无法", "不能", "禁止", "不应", "not ", "no ", "never", "cannot", "don't", "doesn't")
_POLARITY_PAIRS = [
    ("支持", "不支持"),
    ("允许", "不允许"),
    ("可以", "不可以"),
    ("推荐", "不推荐"),
    ("有效", "无效"),
    ("增加", "减少"),
    ("高于", "低于"),
    ("大于", "小于"),
    ("正向", "反向"),
    ("should", "should not"),
    ("increase", "decrease"),
    ("valid", "invalid"),
]


@dataclass
class ConflictFinding:
    chunk_a: str
    chunk_b: str
    kind: str
    detail: str
    evidence: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_a": self.chunk_a,
            "chunk_b": self.chunk_b,
            "kind": self.kind,
            "detail": self.detail,
            "evidence": self.evidence,
        }


def extract_numeric_claims(text: str) -> List[Dict[str, Any]]:
    """从句子中抽取 (语境键, 数值, 单位)。

    语境键 = 去掉数字后的句子 token 集合排序拼接，用于判断"说的是同一件事"。
    """

    claims: List[Dict[str, Any]] = []
    for sentence in _SENTENCE_SPLIT.split(text or ""):
        matches = list(_NUM_RE.finditer(sentence))
        if not matches:
            continue
        context = _NUM_RE.sub(" ", sentence)
        context_key = " ".join(sorted(set(tokenize(context))))
        if len(context_key.split()) < 2:
            continue
        for match_index, match in enumerate(matches):
            claims.append(
                {
                    "context": context_key,
                    "position": match_index,
                    "value": float(match.group(1)),
                    "unit": (match.group(2) or "").strip(),
                    "sentence": sentence.strip()[:200],
                }
            )
    return claims


def polarity_profile(text: str) -> Dict[str, bool]:
    """返回 {特征: 是否出现}，用于比较两段文本的极性。"""

    lowered = (text or "").lower()
    profile: Dict[str, bool] = {}
    for positive, negative in _POLARITY_PAIRS:
        if negative.lower() in lowered:
            profile[negative.lower()] = True
        elif positive.lower() in lowered:
            profile[positive.lower()] = True
    return profile


def _context_similarity(a: str, b: str) -> float:
    """语境相似度：用重叠系数（intersection / min），而非 Jaccard。

    两句话描述同一指标时，常出现"一句更啰嗦"的情况（多出限定词、来源说明）。
    Jaccard 会被这些额外词稀释，重叠系数则能识别"短句被长句包含"的同义语境。
    """

    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


class ConflictDetector:
    def __init__(self, store: KnowledgeStore, metadata: MetadataStore) -> None:
        self.store = store
        self.metadata = metadata

    # ------------------------------------------------------------------ #
    def detect_pair(self, a: Mapping[str, Any], b: Mapping[str, Any]) -> List[ConflictFinding]:
        findings: List[ConflictFinding] = []
        text_a = f"{a.get('title', '')}\n{a.get('content', '')}"
        text_b = f"{b.get('title', '')}\n{b.get('content', '')}"

        # 1) 数值矛盾：按"句内位置 + 相同单位 + 语境重叠"对齐数值，
        #    避免把年份 2019 和比率 0.90 这种不同角色的数字硬凑成矛盾。
        claims_a = extract_numeric_claims(text_a)
        claims_b = extract_numeric_claims(text_b)
        by_ctx_a: Dict[str, List[Dict[str, Any]]] = {}
        by_ctx_b: Dict[str, List[Dict[str, Any]]] = {}
        for claim in claims_a:
            by_ctx_a.setdefault(claim["context"], []).append(claim)
        for claim in claims_b:
            by_ctx_b.setdefault(claim["context"], []).append(claim)

        for ctx_a, list_a in by_ctx_a.items():
            for ctx_b, list_b in by_ctx_b.items():
                if _context_similarity(ctx_a, ctx_b) < 0.55:
                    continue
                by_position = {c["position"]: c for c in list_b}
                for claim in list_a:
                    other = by_position.get(claim["position"])
                    if other is None or other["unit"] != claim["unit"]:
                        continue
                    if abs(claim["value"] - other["value"]) > max(
                        1e-9, abs(claim["value"]) * 0.02
                    ):
                        findings.append(
                            ConflictFinding(
                                chunk_a=a["chunk_id"],
                                chunk_b=b["chunk_id"],
                                kind="numeric",
                                detail=(
                                    f"同一语境下数值不一致: {claim['value']}{claim['unit']} vs "
                                    f"{other['value']}{other['unit']}"
                                ),
                                evidence=[
                                    {
                                        "chunk_id": a["chunk_id"],
                                        "sentence": claim["sentence"],
                                        "value": claim["value"],
                                    },
                                    {
                                        "chunk_id": b["chunk_id"],
                                        "sentence": other["sentence"],
                                        "value": other["value"],
                                    },
                                ],
                            )
                        )
                        break
                if findings:
                    break
            if findings:
                break

        # 2) 极性矛盾
        pa, pb = polarity_profile(text_a), polarity_profile(text_b)
        for positive, negative in _POLARITY_PAIRS:
            pos, neg = positive.lower(), negative.lower()
            if (pa.get(pos) and pb.get(neg)) or (pa.get(neg) and pb.get(pos)):
                findings.append(
                    ConflictFinding(
                        chunk_a=a["chunk_id"],
                        chunk_b=b["chunk_id"],
                        kind="polarity",
                        detail=f"极性表述相反: 「{positive}」vs「{negative}」",
                        evidence=[
                            {"chunk_id": a["chunk_id"], "profile": sorted(k for k in pa if k in {pos, neg})},
                            {"chunk_id": b["chunk_id"], "profile": sorted(k for k in pb if k in {pos, neg})},
                        ],
                    )
                )
                break

        # 3) 显式否定
        if not findings:
            base_a = _strip_negation(text_a)
            if base_a and base_a[:120] in text_b and _has_negation(text_b) != _has_negation(text_a):
                findings.append(
                    ConflictFinding(
                        chunk_a=a["chunk_id"],
                        chunk_b=b["chunk_id"],
                        kind="negation",
                        detail="两段文本主体相同但否定极性相反",
                        evidence=[
                            {"chunk_id": a["chunk_id"], "snippet": text_a[:200]},
                            {"chunk_id": b["chunk_id"], "snippet": text_b[:200]},
                        ],
                    )
                )
        return findings

    # ------------------------------------------------------------------ #
    def _candidates(self, chunk: Mapping[str, Any], *, limit: int = 60) -> List[str]:
        """候选比较对象：同主题的知识 + 向量相似的其它知识。

        只靠向量相似度会漏掉"短文本、术语不同但结论相反"的情况，
        所以同主题（topic 相同）的知识必须参与比较。
        """

        ids: List[str] = []
        topic = chunk.get("topic") or ""
        if topic:
            for row in self.metadata.query_dicts(
                "SELECT chunk_id FROM chunks WHERE project_id=? AND topic=? AND chunk_id<>? LIMIT ?",
                (chunk.get("project_id"), topic, chunk["chunk_id"], limit),
            ):
                if row["chunk_id"] not in ids:
                    ids.append(row["chunk_id"])
        for cand in self.store.find_duplicates(
            chunk["chunk_id"],
            threshold=self.store.retrieval.conflict_similarity,
            filters=ChunkFilter(project_id=chunk.get("project_id")),
            max_pairs=limit,
        ):
            if cand["chunk_b"] not in ids:
                ids.append(cand["chunk_b"])
        return ids[:limit]

    def detect_for(self, chunk_id: str, *, record: bool = True) -> Dict[str, Any]:
        chunk = self.metadata.get_chunk(chunk_id)
        if not chunk:
            raise ValueError(f"知识片段不存在: {chunk_id}")
        findings: List[Dict[str, Any]] = []
        for other_id in self._candidates(chunk):
            other = self.metadata.get_chunk(other_id)
            if not other:
                continue
            if other.get("content_hash") and other.get("content_hash") == chunk.get("content_hash"):
                continue  # 完全重复交给 deduplicator
            for finding in self.detect_pair(chunk, other):
                findings.append(finding.to_dict())
        recorded = self._record(findings, chunk["project_id"]) if record else 0
        return {"chunk_id": chunk_id, "findings": findings, "recorded": recorded}

    def scan(self, project_id: str, *, limit: int = 300, record: bool = True) -> Dict[str, Any]:
        chunks = self.metadata.list_chunks(ChunkFilter(project_id=project_id), limit=limit)
        findings: List[Dict[str, Any]] = []
        seen_pairs: Set[Tuple[str, str]] = set()
        for chunk in chunks:
            for other_id in self._candidates(chunk, limit=20):
                key = tuple(sorted((chunk["chunk_id"], other_id)))
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)  # type: ignore[arg-type]
                other = self.metadata.get_chunk(other_id)
                if not other or other.get("project_id") != project_id:
                    continue
                if other.get("content_hash") and other.get("content_hash") == chunk.get("content_hash"):
                    continue
                for finding in self.detect_pair(chunk, other):
                    findings.append(finding.to_dict())
        # 去重（a,b 无序）
        unique: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for finding in findings:
            key = tuple(sorted((finding["chunk_a"], finding["chunk_b"])))
            unique.setdefault(key, finding)  # type: ignore[arg-type]
        deduped = list(unique.values())
        recorded = self._record(deduped, project_id) if record else 0
        return {"scanned": len(chunks), "findings": deduped, "recorded": recorded}

    # ------------------------------------------------------------------ #
    def _record(self, findings: Sequence[Mapping[str, Any]], project_id: str) -> int:
        recorded = 0
        for finding in findings:
            a, b = finding["chunk_a"], finding["chunk_b"]
            exists = self.metadata.query_dicts(
                "SELECT conflict_id FROM conflicts WHERE (chunk_a=? AND chunk_b=?) OR (chunk_a=? AND chunk_b=?)",
                (a, b, b, a),
            )
            if exists:
                continue
            self.metadata.add_conflict(
                {
                    "conflict_id": new_id("cfl"),
                    "project_id": project_id,
                    "chunk_a": a,
                    "chunk_b": b,
                    "kind": finding.get("kind", "contradiction"),
                    "detail": finding.get("detail", ""),
                    "status": ConflictStatus.OPEN.value,
                    "evidence": list(finding.get("evidence", [])),
                    "resolution": "",
                    "created_at": utcnow_iso(),
                    "resolved_at": "",
                }
            )
            for chunk_id in (a, b):
                self.metadata.update_chunk(chunk_id, {"conflict_status": "potential"})
            self.metadata.add_edge(
                {
                    "edge_id": new_id("edge"),
                    "src_id": a,
                    "dst_id": b,
                    "relation": RelationType.CONFLICTS_WITH.value,
                    "weight": 1.0,
                    "metadata": {"kind": finding.get("kind", "contradiction")},
                    "created_at": utcnow_iso(),
                }
            )
            recorded += 1
        return recorded

    def resolve(self, conflict_id: str, resolution: str, *, status: str = "resolved") -> Dict[str, Any]:
        """裁定冲突：可以采信一方、也可以保留为"公认争议"。"""

        conflict = self.metadata.get("conflicts", conflict_id)
        if not conflict:
            raise ValueError(f"冲突不存在: {conflict_id}")
        self.metadata.update(
            "conflicts",
            conflict_id,
            {
                "status": ConflictStatus.parse(status, "status").value,
                "resolution": resolution,
                "resolved_at": utcnow_iso(),
            },
        )
        new_status = "confirmed" if status == ConflictStatus.ACCEPTED_AS_DISPUTE.value else "resolved"
        for chunk_id in (conflict["chunk_a"], conflict["chunk_b"]):
            self.metadata.update_chunk(chunk_id, {"conflict_status": new_status})
        return {"conflict_id": conflict_id, "status": status, "resolution": resolution}


def _has_negation(text: str) -> bool:
    lowered = (text or "").lower()
    return any(neg in lowered for neg in _NEGATORS)


def _strip_negation(text: str) -> str:
    cleaned = text or ""
    for neg in _NEGATORS:
        cleaned = cleaned.replace(neg, "")
    return " ".join(cleaned.split())


__all__ = [
    "ConflictDetector",
    "ConflictFinding",
    "extract_numeric_claims",
    "polarity_profile",
]
