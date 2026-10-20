"""工具注册表。

每个工具都必须具备（规范第九节/规则 4）：
名称、用途、输入参数与类型、参数校验、返回值结构、错误类型、
超时/预算、权限要求、是否修改数据、是否需要确认。

返回值统一为::

    {
      "success": bool,
      "tool": "<name>",
      "data": {...} | null,
      "error": {"type": "...", "message": "..."} | null,
      "warnings": [...],
      "elapsed_ms": 12.3
    }

实现约束：数据库查询、文件读取、重复检测、状态更新都用确定性程序逻辑；
只有需要语言理解的环节（提取/总结/规划补充）才调用模型。
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from ..core.models import RiskLevel


class ToolError(Exception):
    def __init__(self, message: str, kind: str = "InvalidArgument") -> None:
        super().__init__(message)
        self.kind = kind


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[[Dict[str, Any]], Dict[str, Any]]
    risk: str = RiskLevel.READ.value
    side_effects: str = "none"
    requires_confirmation: bool = False
    group: str = "general"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "risk": self.risk,
            "side_effects": self.side_effects,
            "requires_confirmation": self.requires_confirmation,
            "group": self.group,
        }


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "null":
        return value is None
    return True


def validate_args(schema: Mapping[str, Any], args: Mapping[str, Any]) -> List[str]:
    """最小 JSON Schema 校验（够用即可）：required / type / enum / 数值范围。"""

    errors: List[str] = []
    if not isinstance(args, dict):
        return ["arguments 必须是对象"]
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    for key in required:
        if key not in args or args[key] is None:
            errors.append(f"缺少必填参数: {key}")
    for key, value in args.items():
        spec = properties.get(key)
        if spec is None:
            continue  # 允许额外字段，但工具实现需要自行忽略
        expected = spec.get("type")
        if expected and not _type_ok(value, expected):
            errors.append(f"参数 {key} 类型应为 {expected}")
            continue
        if value is None:
            continue
        enum = spec.get("enum")
        if enum and value not in enum:
            errors.append(f"参数 {key} 必须是 {enum} 之一")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in spec and value < spec["minimum"]:
                errors.append(f"参数 {key} 不能小于 {spec['minimum']}")
            if "maximum" in spec and value > spec["maximum"]:
                errors.append(f"参数 {key} 不能大于 {spec['maximum']}")
        if isinstance(value, list) and spec.get("items", {}).get("type"):
            item_type = spec["items"]["type"]
            for item in value:
                if not _type_ok(item, item_type):
                    errors.append(f"参数 {key} 的元素类型应为 {item_type}")
                    break
    return errors


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    # ------------------------------------------------------------------ #
    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"工具重复注册: {spec.name}")
        self._tools[spec.name] = spec

    def tool(self, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """装饰器形式注册。"""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.register(
                ToolSpec(handler=func, **{**kwargs, "name": kwargs.get("name") or func.__name__})  # type: ignore[arg-type]
            )
            return func

        return decorator

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise ToolError(f"未知工具: {name}", "UnknownTool")
        return self._tools[name]

    def names(self) -> List[str]:
        return sorted(self._tools)

    def list_specs(self, group: Optional[str] = None) -> List[Dict[str, Any]]:
        specs = self._tools.values()
        if group:
            specs = [s for s in specs if s.group == group]
        return [s.to_dict() for s in sorted(specs, key=lambda s: s.name)]

    # ------------------------------------------------------------------ #
    def call(self, name: str, arguments: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        started = time.perf_counter()
        args = dict(arguments or {})
        try:
            spec = self.get(name)
            errors = validate_args(spec.input_schema, args)
            if errors:
                raise ToolError("；".join(errors), "ValidationError")
            data = spec.handler(args)
            warnings = []
            if isinstance(data, dict):
                warnings = data.pop("_warnings", []) or []
                if "_error" in data:
                    raise ToolError(str(data.pop("_error")), data.pop("_error_type", "ExecutionError"))
            return {
                "success": True,
                "tool": name,
                "data": data,
                "error": None,
                "warnings": warnings,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        except ToolError as exc:
            return {
                "success": False,
                "tool": name,
                "data": None,
                "error": {"type": exc.kind, "message": str(exc)},
                "warnings": [],
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        except PermissionError as exc:
            return {
                "success": False,
                "tool": name,
                "data": None,
                "error": {"type": "PermissionDenied", "message": str(exc)},
                "warnings": [],
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        except FileNotFoundError as exc:
            return {
                "success": False,
                "tool": name,
                "data": None,
                "error": {"type": "NotFound", "message": str(exc)},
                "warnings": [],
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        except Exception as exc:  # noqa: BLE001 - 工具边界统一转结构化错误
            return {
                "success": False,
                "tool": name,
                "data": None,
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "trace": traceback.format_exc(limit=3) if _debug() else "",
                },
                "warnings": [],
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            }


def _debug() -> bool:
    import os

    return os.environ.get("DSH_AL_DEBUG", "").lower() in {"1", "true", "yes"}


__all__ = ["ToolError", "ToolRegistry", "ToolSpec", "validate_args"]
