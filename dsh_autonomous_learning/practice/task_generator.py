"""练习任务生成与评估。

任务类型与知识类型对应：
- formula      -> 公式重算（需要表达式与期望值，缺一不可）
- code_example -> 在受限环境中执行代码并检查退出码/断言
- definition   -> 概念问答（规则评分：参考要点覆盖率，需人工复核）
- procedure    -> 流程清单自检（不可自动判定）
- quant        -> 回测类任务：本插件**不实现**回测引擎，明确标记为未支持，
                  避免"看起来运行了"的假象

生成的任务都写入 ``practice_tasks``，执行结果写入 ``practice_results``；
评估结论只反映"这次实践的证据"，不会自动把知识升级为 evaluated。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from ..config import LearningConfig
from ..core.models import PracticeStatus, new_id, utcnow_iso
from ..storage.metadata_store import ChunkFilter, MetadataStore
from ..storage.vector_store import KnowledgeStore

_EXPR_WITH_VALUE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*\s*=\s*[^=\n]{2,80})")


@dataclass
class GeneratedTask:
    practice_id: str
    kind: str
    title: str
    chunk_id: str
    spec: Dict[str, Any]
    runnable: bool
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "practice_id": self.practice_id,
            "kind": self.kind,
            "title": self.title,
            "chunk_id": self.chunk_id,
            "spec": self.spec,
            "runnable": self.runnable,
            "reason": self.reason,
        }


class PracticeTaskGenerator:
    def __init__(self, store: KnowledgeStore, metadata: MetadataStore, config: LearningConfig) -> None:
        self.store = store
        self.metadata = metadata
        self.cfg = config

    # ------------------------------------------------------------------ #
    def from_chunk(self, chunk_id: str, kind: Optional[str] = None) -> Dict[str, Any]:
        chunk = self.metadata.get_chunk(chunk_id)
        if not chunk:
            raise ValueError(f"知识片段不存在: {chunk_id}")
        kind = kind or self._kind_for(chunk)
        spec, runnable, reason = self._build_spec(chunk, kind)
        record = {
            "practice_id": new_id("prc"),
            "project_id": chunk["project_id"],
            "chunk_id": chunk_id,
            "kind": kind,
            "title": f"[{kind}] {chunk.get('title') or chunk_id[:12]}",
            "spec": spec,
            "status": PracticeStatus.CREATED.value,
            "created_at": utcnow_iso(),
        }
        self.metadata.add_practice(record)
        return GeneratedTask(
            practice_id=record["practice_id"],
            kind=kind,
            title=record["title"],
            chunk_id=chunk_id,
            spec=spec,
            runnable=runnable,
            reason=reason,
        ).to_dict()

    def generate(self, project_id: str, *, limit: int = 5, kinds: Optional[List[str]] = None) -> Dict[str, Any]:
        chunks = self.metadata.list_chunks(
            ChunkFilter(project_id=project_id, knowledge_types=kinds) if kinds else ChunkFilter(project_id=project_id),
            limit=limit * 3,
        )
        tasks: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        for chunk in chunks:
            if len(tasks) >= limit:
                break
            try:
                task = self.from_chunk(chunk["chunk_id"])
            except Exception as exc:  # noqa: BLE001
                skipped.append({"chunk_id": chunk["chunk_id"], "reason": str(exc)})
                continue
            if task["runnable"]:
                tasks.append(task)
            else:
                skipped.append({"chunk_id": chunk["chunk_id"], "kind": task["kind"], "reason": task["reason"]})
        return {"tasks": tasks, "skipped": skipped, "requested": limit}

    # ------------------------------------------------------------------ #
    def _kind_for(self, chunk: Mapping[str, Any]) -> str:
        ktype = chunk.get("knowledge_type")
        return {
            "formula": "formula",
            "code_example": "code_example",
            "definition": "definition",
            "concept": "definition",
            "procedure": "procedure",
            "experimental_result": "experiment",
        }.get(ktype, "self_check")

    def _build_spec(self, chunk: Mapping[str, Any], kind: str) -> tuple[Dict[str, Any], bool, str]:
        metadata = chunk.get("metadata") or {}
        if kind == "formula":
            formulas = metadata.get("formulas") or []
            expressions = [f.get("expression", "") for f in formulas if f.get("expression")]
            if not expressions:
                matches = _EXPR_WITH_VALUE.findall(chunk.get("content") or "")
                expressions = matches[:3]
            if not expressions:
                return (
                    {"expressions": [], "expected": None},
                    False,
                    "未从内容中识别出可重算的公式表达式",
                )
            return (
                {
                    "expressions": expressions,
                    "variables": {},
                    "expected": None,
                    "hint": "请在调用 verify_formula 时补充 variables 与 expected（期望值来自独立计算或官方示例）",
                },
                True,
                "",
            )
        if kind == "code_example":
            blocks = metadata.get("code_blocks") or []
            python_blocks = [b for b in blocks if b.get("language") in {"python", "py"}]
            if not python_blocks:
                return (
                    {"code": "", "language": ""},
                    False,
                    "没有 Python 代码块；本插件只支持 Python 受限执行，其它语言请改用代码审查",
                )
            code = python_blocks[0]["code"]
            spec = {
                "language": "python",
                "code": code,
                "note": "代码来自外部文档，默认视为不可信；执行需 lab 模式与显式信任标记",
            }
            return spec, True, ""
        if kind == "definition":
            return (
                {
                    "question": f"请用自己的话解释：{chunk.get('title') or '该概念'}",
                    "reference_points": _key_points(chunk.get("content") or ""),
                    "grading": "rule_overlap",
                },
                True,
                "",
            )
        if kind == "procedure":
            steps = _extract_steps(chunk.get("content") or "")
            return (
                {"checklist": steps, "grading": "manual"},
                False,
                "流程类任务只能人工/Agent 自检，不做自动判分",
            )
        if kind == "experiment":
            return (
                {
                    "experiment": chunk.get("content", "")[:2000],
                    "note": "需要可复现的实验方案；插件不会自动执行未知来源实验",
                },
                False,
                "实验类任务需要人工提供可执行规范",
            )
        return (
            {
                "question": f"关于「{chunk.get('title') or chunk_id}」，你能复述哪些要点？",
                "reference_points": _key_points(chunk.get("content") or ""),
                "grading": "rule_overlap",
            },
            True,
            "",
        )


# --------------------------------------------------------------------------- #
# 评估
# --------------------------------------------------------------------------- #
def evaluate_practice(practice: Mapping[str, Any], result: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """根据实践记录给出结论。没有执行结果就是未完成。"""

    kind = practice.get("kind")
    spec = practice.get("spec") or {}
    result = result or {}

    if kind in {"formula", "code_example", "experiment"}:
        if not result:
            return {
                "status": PracticeStatus.SKIPPED.value,
                "conclusion": "没有执行结果，不能声称已通过",
                "score": 0.0,
                "requires_manual_review": True,
            }
        ok = bool(result.get("ok"))
        return {
            "status": PracticeStatus.PASSED.value if ok else PracticeStatus.FAILED.value,
            "conclusion": "执行成功" if ok else f"执行失败：{result.get('stderr') or result.get('error') or '未知原因'}",
            "score": 1.0 if ok else 0.0,
            "exit_code": result.get("exit_code"),
            "requires_manual_review": not ok,
        }

    if kind == "definition":
        answer = str((result or {}).get("answer") or "")
        reference = spec.get("reference_points") or []
        if not answer:
            return {"status": PracticeStatus.SKIPPED.value, "conclusion": "未作答", "score": 0.0}
        hit = [point for point in reference if point and point in answer]
        score = round(len(hit) / max(1, len(reference)), 3) if reference else 0.0
        missing = [p for p in reference if p not in hit]
        return {
            "status": PracticeStatus.PASSED.value if score >= 0.6 else PracticeStatus.FAILED.value,
            "conclusion": f"命中 {len(hit)}/{len(reference)} 个参考要点",
            "score": score,
            "missing_points": missing[:10],
            "grading": "rule_overlap",
            "requires_manual_review": True,
            "note": "规则重叠评分只作参考，概念理解的最终判定需要人工或更强的评估器",
        }

    return {
        "status": PracticeStatus.SKIPPED.value,
        "conclusion": "该任务类型不支持自动评估",
        "score": 0.0,
        "requires_manual_review": True,
    }


def _key_points(text: str, limit: int = 6) -> List[str]:
    """抽取参考要点：较短的句子/列表项。"""

    points: List[str] = []
    for line in re.split(r"(?<=[。！？.!?])\s*|\n", text or ""):
        line = line.strip(" -*\t")
        if 6 <= len(line) <= 80:
            points.append(line)
        if len(points) >= limit:
            break
    return points


def _extract_steps(text: str) -> List[str]:
    steps: List[str] = []
    for line in (text or "").splitlines():
        match = re.match(r"^\s*(?:\d+[.)、]|[-*]|第[一二三四五六七八九十]+步)\s*(.+)$", line)
        if match and match.group(1).strip():
            steps.append(match.group(1).strip()[:200])
    return steps[:20]


__all__ = ["GeneratedTask", "PracticeTaskGenerator", "evaluate_practice"]
