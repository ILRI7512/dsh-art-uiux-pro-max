"""审计日志。

要求（规范第十二/规则 5）：
- 重要外部操作、权限拒绝、写入、删除、执行、配置变更都要留痕；
- 日志不得泄露密钥：写之前做脱敏；
- 审计失败不能影响主流程（降级为 stderr 警告），但也不能假装成功。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ..config import SecurityConfig
from ..storage.metadata_store import MetadataStore

_REDACT_KEYS = {
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "password",
    "passwd",
    "secret",
    "authorization",
    "private_key",
    "credential",
    "cookie",
}
_INLINE_SECRET = re.compile(
    r"(?i)\b(sk-[A-Za-z0-9_\-]{8,}|Bearer\s+[A-Za-z0-9._\-]{8,}|gh[pousr]_[A-Za-z0-9]{8,})\b"
)


def redact(value: Any, depth: int = 0) -> Any:
    """递归脱敏：按键名屏蔽，按值做正则替换，限制嵌套深度。"""

    if depth > 6:
        return "<max-depth>"
    if isinstance(value, Mapping):
        out: Dict[str, Any] = {}
        for key, val in value.items():
            if str(key).lower() in _REDACT_KEYS:
                out[key] = "<redacted>"
            else:
                out[key] = redact(val, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(item, depth + 1) for item in value[:200]]
    if isinstance(value, str):
        return _INLINE_SECRET.sub("<redacted>", value)
    return value


class AuditLogger:
    def __init__(self, metadata: Optional[MetadataStore], *, enabled: bool = True) -> None:
        self.metadata = metadata
        self.enabled = enabled
        self._buffer: List[Dict[str, Any]] = []

    def log(
        self,
        action: str,
        target: str = "",
        risk: str = "read",
        allowed: bool = True,
        project_id: str = "",
        detail: Optional[Mapping[str, Any]] = None,
        actor: str = "agent",
    ) -> Dict[str, Any]:
        record = {
            "action": action,
            "target": target,
            "risk": risk,
            "allowed": allowed,
            "project_id": project_id,
            "detail": redact(dict(detail or {})),
            "actor": actor,
        }
        if not self.enabled:
            return record
        if self.metadata is None:
            self._buffer.append(record)
            return record
        try:
            self.metadata.log_audit(
                action=action,
                target=target,
                risk=risk,
                allowed=allowed,
                project_id=project_id,
                actor=actor,
                detail=record["detail"],
            )
        except Exception as exc:  # noqa: BLE001 - 审计失败不得中断业务
            print(f"[audit] 审计写入失败: {exc}", file=sys.stderr)
        return record

    def tail(self, limit: int = 50) -> List[Dict[str, Any]]:
        if self.metadata is None:
            return self._buffer[-limit:]
        return self.metadata.list_audit(limit=limit)

    def export(self, path: str | Path) -> Dict[str, Any]:
        records = self.tail(limit=100_000)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"path": str(target), "count": len(records)}


__all__ = ["AuditLogger", "redact"]
