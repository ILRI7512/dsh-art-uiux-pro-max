"""工具层：注册表 + 四组业务工具。

对外只暴露 ``build_registry(runtime)``，返回已注册全部工具的注册表与调度器。
"""

from __future__ import annotations

from typing import Tuple

from ..core.orchestrator import LearningOrchestrator, Runtime
from ..core.scheduler import Scheduler
from . import evaluation_tools, learning_tools, retrieval_tools, verification_tools
from .registry import ToolError, ToolRegistry, ToolSpec, validate_args


def build_registry(runtime: Runtime) -> Tuple[ToolRegistry, LearningOrchestrator, Scheduler]:
    orchestrator = LearningOrchestrator(runtime)
    scheduler = Scheduler(runtime, orchestrator)
    registry = ToolRegistry()
    learning_tools.register(registry, runtime, orchestrator)
    retrieval_tools.register(registry, runtime, orchestrator)
    verification_tools.register(registry, runtime, orchestrator)
    evaluation_tools.register(registry, runtime, orchestrator, scheduler)
    return registry, orchestrator, scheduler


__all__ = [
    "ToolError",
    "ToolRegistry",
    "ToolSpec",
    "build_registry",
    "validate_args",
]
