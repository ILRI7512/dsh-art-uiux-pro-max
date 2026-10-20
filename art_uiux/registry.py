"""资源注册表：15 字段校验 + 运行期状态持久化。

设计要点（对应需求三、四）：
- ``resources.seed.json`` 是**只读的种子**，不含任何「已学习」的谎报；
- 运行期状态写到 ``data/registry.json``，与种子合并后才是对外视图；
- URL 可访问 ≠ 学习完成：``access_status`` 与 ``learn_status`` 是两个独立字段，
  另有 ``learned_chunks`` 记录真正入库的知识条数，三者不可互相替代。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .taxonomy import CATEGORY_KEYS, TaxonomyError, get_category

RESOURCE_TYPES = {
    "official_documentation",
    "github_repository",
    "design_system",
    "product_case",
    "design_gallery",
    "technical_tutorial",
    "accessibility_standard",
    "visual_reference",
}

ACCESS_STATUS = {"unchecked", "reachable", "restricted", "blocked", "failed"}
LEARN_STATUS = {"not_started", "partial", "learned", "failed"}
CRAWL_POLICIES = {
    "docs_public_pages",      # 公开文档页，可增量抓取正文
    "readme_source_tests_license",  # GitHub：README + 关键源码 + 测试 + LICENSE
    "public_landing_analysis",      # 产品站：仅分析公开可访问页面
    "visual_reference_only",        # 灵感站：只提炼规律，不搬运素材
}
RELIABILITY = {"high", "medium", "low", "unknown"}

REQUIRED_FIELDS = (
    "resource_id",
    "name",
    "url",
    "resource_type",
    "primary_category",
    "secondary_categories",
    "platform",
    "learning_objectives",
    "access_status",
    "last_checked",
    "last_learned",
    "license_notes",
    "source_reliability",
    "learning_priority",
    "crawl_policy",
)


class RegistryError(ValueError):
    """注册表数据不合法。"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_resource(res: Dict[str, Any]) -> None:
    missing = [f for f in REQUIRED_FIELDS if f not in res]
    if missing:
        raise RegistryError("%s 缺少字段: %s" % (res.get("resource_id", "?"), ", ".join(missing)))
    rid = res["resource_id"]
    if not isinstance(rid, str) or not rid.strip():
        raise RegistryError("resource_id 必须是非空字符串")
    if res["resource_type"] not in RESOURCE_TYPES:
        raise RegistryError("%s 的 resource_type 非法: %r" % (rid, res["resource_type"]))
    if res["primary_category"] not in CATEGORY_KEYS:
        raise RegistryError("%s 的 primary_category 非法: %r" % (rid, res["primary_category"]))
    secondary = res.get("secondary_categories") or []
    if not isinstance(secondary, list):
        raise RegistryError("%s 的 secondary_categories 必须是数组" % rid)
    for key in secondary:
        if key == res["primary_category"]:
            raise RegistryError("%s 的辅助分类不能等于主分类" % rid)
        get_category(key)
    if res["access_status"] not in ACCESS_STATUS:
        raise RegistryError("%s 的 access_status 非法: %r" % (rid, res["access_status"]))
    if res["source_reliability"] not in RELIABILITY:
        raise RegistryError("%s 的 source_reliability 非法: %r" % (rid, res["source_reliability"]))
    if res["crawl_policy"] not in CRAWL_POLICIES:
        raise RegistryError("%s 的 crawl_policy 非法: %r" % (rid, res["crawl_policy"]))
    prio = res["learning_priority"]
    if not isinstance(prio, int) or not 1 <= prio <= 5:
        raise RegistryError("%s 的 learning_priority 必须是 1-5 的整数" % rid)
    if not isinstance(res.get("learning_objectives"), list) or not res["learning_objectives"]:
        raise RegistryError("%s 必须有至少一条 learning_objectives" % rid)


@dataclass
class Registry:
    root: Path

    @property
    def seed_path(self) -> Path:
        return self.root / "art_uiux" / "resources.seed.json"

    @property
    def state_path(self) -> Path:
        return self.root / "dsh_autonomous_learning" / "data" / "registry.json"

    # ---- 读写 ----

    def seed(self) -> List[Dict[str, Any]]:
        data = json.loads(self.seed_path.read_text(encoding="utf-8"))
        items = data["resources"] if isinstance(data, dict) else data
        for res in items:
            validate_resource(res)
        return items

    def state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {"version": 1, "resources": {}}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"version": 1, "resources": {}}

    def save_state(self, state: Dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.state_path)

    # ---- 视图 ----

    def view(self) -> List[Dict[str, Any]]:
        """种子 + 运行期状态合并后的对外视图。"""

        state = self.state().get("resources", {})
        merged = []
        for res in self.seed():
            item = dict(res)
            item.setdefault("learn_status", "not_started")
            item.setdefault("learned_chunks", 0)
            item.setdefault("learn_notes", "")
            item.setdefault("last_error", "")
            item.update(state.get(item["resource_id"], {}))
            merged.append(item)
        return merged

    def get(self, resource_id: str) -> Optional[Dict[str, Any]]:
        for item in self.view():
            if item["resource_id"] == resource_id:
                return item
        return None

    def select(
        self,
        *,
        categories: Optional[Iterable[str]] = None,
        types: Optional[Iterable[str]] = None,
        platform: Optional[str] = None,
        max_priority: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        cats = set(categories or ())
        typs = set(types or ())
        out = []
        for item in self.view():
            if cats and item["primary_category"] not in cats:
                continue
            if typs and item["resource_type"] not in typs:
                continue
            if platform and item["platform"] != platform:
                continue
            if max_priority is not None and item["learning_priority"] > max_priority:
                continue
            out.append(item)
        return out

    # ---- 状态写入 ----

    def update(self, resource_id: str, **fields: Any) -> Dict[str, Any]:
        known = {r["resource_id"] for r in self.seed()}
        if resource_id not in known:
            raise RegistryError("未知 resource_id: %s" % resource_id)
        if "access_status" in fields and fields["access_status"] not in ACCESS_STATUS:
            raise RegistryError("access_status 非法: %r" % fields["access_status"])
        if "learn_status" in fields and fields["learn_status"] not in LEARN_STATUS:
            raise RegistryError("learn_status 非法: %r" % fields["learn_status"])
        state = self.state()
        bucket = state.setdefault("resources", {}).setdefault(resource_id, {})
        bucket.update(fields)
        bucket["updated_at"] = _now()
        self.save_state(state)
        return bucket

    def record_check(
        self,
        resource_id: str,
        *,
        access_status: str,
        http_status: Optional[int] = None,
        final_url: str = "",
        content_type: str = "",
        bytes_read: int = 0,
        robots_allowed: Optional[bool] = None,
        error: str = "",
    ) -> Dict[str, Any]:
        return self.update(
            resource_id,
            access_status=access_status,
            last_checked=_now(),
            last_http_status=http_status,
            last_final_url=final_url,
            last_content_type=content_type,
            last_bytes=bytes_read,
            robots_allowed=robots_allowed,
            last_error=error,
        )

    def record_learning(
        self,
        resource_id: str,
        *,
        learn_status: str,
        chunks: int = 0,
        notes: str = "",
        error: str = "",
    ) -> Dict[str, Any]:
        return self.update(
            resource_id,
            learn_status=learn_status,
            learned_chunks=chunks,
            learn_notes=notes,
            last_error=error,
            last_learned=_now() if learn_status in ("partial", "learned") else "",
        )

    # ---- 统计 ----

    def stats(self) -> Dict[str, Any]:
        items = self.view()
        by_access: Dict[str, int] = {}
        by_learn: Dict[str, int] = {}
        by_cat: Dict[str, int] = {}
        for item in items:
            by_access[item["access_status"]] = by_access.get(item["access_status"], 0) + 1
            by_learn[item["learn_status"]] = by_learn.get(item["learn_status"], 0) + 1
            by_cat[item["primary_category"]] = by_cat.get(item["primary_category"], 0) + 1
        return {
            "total": len(items),
            "access_status": by_access,
            "learn_status": by_learn,
            "by_primary_category": by_cat,
            "learned_chunks_total": sum(int(i.get("learned_chunks") or 0) for i in items),
        }
