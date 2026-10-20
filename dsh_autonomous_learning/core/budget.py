"""预算与停止条件（规则 6：持续学习必须有界）。

预算维度（与配置文件对应）：
- 单轮时间 / 任务数 / 迭代次数
- 单任务超时
- 模型调用次数与费用估算
- 单任务资料数量
- 文件与实验产物大小

所有计数都在内存里实时累计，同时把关键指标写入 metrics 表，
保证进程崩溃后仍能从数据库看到"为什么停下"。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..config import LearningConfig, ModelConfig
from ..storage.metadata_store import MetadataStore


class BudgetExceeded(RuntimeError):
    """预算耗尽，需要暂停并生成阶段报告。"""

    def __init__(self, reason: str, dimension: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.dimension = dimension


@dataclass
class BudgetState:
    run_id: str = ""
    project_id: str = ""
    started_at: float = field(default_factory=time.monotonic)
    tasks_run: int = 0
    sources_read: int = 0
    llm_calls: int = 0
    cost_estimate: float = 0.0
    new_knowledge: int = 0
    no_progress_rounds: int = 0
    stop_reason: str = ""


class BudgetTracker:
    """单轮学习的预算核算器。"""

    def __init__(
        self,
        config: LearningConfig,
        model_config: ModelConfig,
        metadata: Optional[MetadataStore] = None,
        *,
        run_id: str = "",
        project_id: str = "",
        daily_spent: float = 0.0,
    ) -> None:
        self.cfg = config
        self.model_cfg = model_config
        self.metadata = metadata
        self.state = BudgetState(run_id=run_id, project_id=project_id)
        self.daily_spent = float(daily_spent)
        self.iteration = 0

    # ------------------------------------------------------------------ #
    def set_iteration(self, iteration: int) -> None:
        self.iteration = iteration

    def start_task(self) -> None:
        if self.state.tasks_run >= self.cfg.max_tasks_per_run:
            raise BudgetExceeded(
                f"已达到单轮最大任务数 {self.cfg.max_tasks_per_run}", "max_tasks_per_run"
            )
        self.state.tasks_run += 1
        self.check_time()

    def finish_task(self, task_new_knowledge: int = 0, progress: bool = True) -> None:
        """记录任务结果。无进展判定放在"轮次"层面（见 orchestrator.run_round），
        避免把 discover/verify 这类不直接产出新知识的任务误判成停滞。"""

        self.state.new_knowledge += max(0, task_new_knowledge)
        if progress:
            self.state.no_progress_rounds = 0
        else:
            self.state.no_progress_rounds += 1

    def consume_sources(self, count: int) -> None:
        if count <= 0:
            return
        if self.state.sources_read + count > self.cfg.max_sources_per_task:
            raise BudgetExceeded(
                f"超出单任务最大资料数 {self.cfg.max_sources_per_task}", "max_sources_per_task"
            )
        self.state.sources_read += count

    def consume_llm(self, response: Any) -> None:
        """记录一次模型调用（response 可为 ModelResponse 或 None）。"""

        self.state.llm_calls += 1
        if self.state.llm_calls > self.cfg.max_llm_calls_per_run:
            raise BudgetExceeded(
                f"超出单轮模型调用上限 {self.cfg.max_llm_calls_per_run}", "max_llm_calls_per_run"
            )
        cost = float(getattr(response, "cost_estimate", 0.0) or 0.0)
        self.state.cost_estimate += cost
        self.daily_spent += cost
        if self.cfg.daily_budget_usd > 0 and self.daily_spent > self.cfg.daily_budget_usd:
            raise BudgetExceeded(
                f"超出每日预算 {self.cfg.daily_budget_usd:.2f} USD（估算）", "daily_budget"
            )
        if (
            self.metadata is not None
            and self.model_cfg.max_cost_usd > 0
            and self.state.cost_estimate > self.model_cfg.max_cost_usd
        ):
            raise BudgetExceeded(
                f"超出单轮费用上限 {self.model_cfg.max_cost_usd:.2f} USD（估算）", "model_cost"
            )

    def check_time(self) -> None:
        elapsed = time.monotonic() - self.state.started_at
        if elapsed > self.cfg.max_run_seconds:
            raise BudgetExceeded(
                f"单轮运行时间超过 {self.cfg.max_run_seconds}s", "max_run_seconds"
            )

    def can_continue(self, iteration: int) -> bool:
        return iteration < self.cfg.max_iterations_per_run

    # ------------------------------------------------------------------ #
    def should_stop(self) -> tuple[bool, str]:
        """返回 (是否应停止, 原因)。不抛异常，便于在循环里优雅收尾。"""

        try:
            self.check_time()
            if self.state.tasks_run >= self.cfg.max_tasks_per_run:
                return True, "max_tasks_per_run"
            if self.state.llm_calls >= self.cfg.max_llm_calls_per_run:
                return True, "max_llm_calls_per_run"
            if self.cfg.daily_budget_usd > 0 and self.daily_spent >= self.cfg.daily_budget_usd:
                return True, "daily_budget"
            if not self.can_continue(self.iteration):
                return True, "max_iterations_per_run"
        except BudgetExceeded as exc:
            return True, exc.dimension or "budget"
        return False, ""

    def snapshot(self) -> Dict[str, Any]:
        elapsed = round(time.monotonic() - self.state.started_at, 2)
        return {
            "run_id": self.state.run_id,
            "project_id": self.state.project_id,
            "iteration": self.iteration,
            "tasks_run": self.state.tasks_run,
            "sources_read": self.state.sources_read,
            "llm_calls": self.state.llm_calls,
            "cost_estimate": round(self.state.cost_estimate, 6),
            "daily_spent": round(self.daily_spent, 6),
            "new_knowledge": self.state.new_knowledge,
            "no_progress_rounds": self.state.no_progress_rounds,
            "elapsed_s": elapsed,
            "limits": {
                "max_tasks_per_run": self.cfg.max_tasks_per_run,
                "max_iterations_per_run": self.cfg.max_iterations_per_run,
                "max_llm_calls_per_run": self.cfg.max_llm_calls_per_run,
                "max_run_seconds": self.cfg.max_run_seconds,
                "daily_budget_usd": self.cfg.daily_budget_usd,
            },
        }


__all__ = ["BudgetExceeded", "BudgetState", "BudgetTracker"]
