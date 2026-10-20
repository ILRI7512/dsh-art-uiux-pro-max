"""任务调度器（有界、可恢复、默认关闭）。

能力：
- 持久化定时任务（``schedules`` 表）：间隔触发 / 指定下次运行时间；
- ``tick()`` 检查到期任务并执行**有限轮次**的学习，不在进程内起无限循环；
- 执行次数、预算与错误全部落库；失败不影响进程；
- 支持暂停/恢复/删除定时任务。

必须明确（规则 6）：后台执行依赖真实运行环境与进程生命周期。
本插件不假装"模型能永久运行"：进程退出后定时任务不会自己醒来，
需要 DSH 或操作系统再次调用 ``run_scheduler_tick``。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..core.models import new_id, utcnow_iso
from ..core.orchestrator import LearningOrchestrator, Runtime


class Scheduler:
    def __init__(self, runtime: Runtime, orchestrator: LearningOrchestrator) -> None:
        self.rt = runtime
        self.orch = orchestrator
        self.metadata = runtime.metadata

    # ------------------------------------------------------------------ #
    def schedule(
        self,
        project_id: str,
        *,
        interval_minutes: Optional[int] = None,
        next_run_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        project = self.metadata.get_project(project_id)
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        if not interval_minutes and not next_run_at:
            raise ValueError("必须提供 interval_minutes 或 next_run_at 之一")
        if interval_minutes is not None and int(interval_minutes) < 1:
            raise ValueError("interval_minutes 必须 >= 1")
        when = next_run_at or (
            datetime.now(timezone.utc) + timedelta(minutes=int(interval_minutes or 60))
        ).isoformat(timespec="seconds").replace("+00:00", "Z")
        row = {
            "schedule_id": new_id("sch"),
            "project_id": project_id,
            "kind": "interval" if interval_minutes else "once",
            "expression": str(int(interval_minutes)) if interval_minutes else "",
            "next_run_at": when,
            "enabled": True,
            "last_run_at": "",
            "created_at": utcnow_iso(),
        }
        self.metadata.upsert_schedule(row)
        return row

    def list(self) -> List[Dict[str, Any]]:
        return self.metadata.list_schedules()

    def set_enabled(self, schedule_id: str, enabled: bool) -> Dict[str, Any]:
        row = self.metadata.get("schedules", schedule_id)
        if not row:
            raise ValueError(f"定时任务不存在: {schedule_id}")
        self.metadata.update("schedules", schedule_id, {"enabled": bool(enabled)})
        return {"schedule_id": schedule_id, "enabled": bool(enabled)}

    def delete(self, schedule_id: str) -> bool:
        return self.metadata.delete("schedules", schedule_id) > 0

    # ------------------------------------------------------------------ #
    def tick(self, *, max_projects: int = 1, max_tasks_per_project: int = 5) -> Dict[str, Any]:
        now = utcnow_iso()
        due = self.metadata.due_schedules(now)
        executed: List[Dict[str, Any]] = []
        for schedule in due[:max_projects]:
            project_id = schedule["project_id"]
            started = utcnow_iso()
            try:
                result = self.orch.run_round(project_id, max_tasks=max_tasks_per_project)
                status = "ok"
                summary = {
                    "run_id": result.get("run_id"),
                    "tasks_executed": len(result.get("tasks_executed", [])),
                    "stop_reason": result.get("stop_reason", ""),
                }
            except Exception as exc:  # noqa: BLE001 - 定时任务失败不能拖垮进程
                status = "error"
                summary = {"error": str(exc)[:500]}

            interval = schedule.get("expression")
            if schedule.get("kind") == "interval" and interval:
                nxt = (
                    datetime.now(timezone.utc) + timedelta(minutes=int(interval))
                ).isoformat(timespec="seconds").replace("+00:00", "Z")
                enabled = True
            else:
                nxt = schedule.get("next_run_at", "")
                enabled = False
            self.metadata.update(
                "schedules",
                schedule["schedule_id"],
                {"next_run_at": nxt, "enabled": enabled, "last_run_at": started},
            )
            executed.append(
                {
                    "schedule_id": schedule["schedule_id"],
                    "project_id": project_id,
                    "status": status,
                    **summary,
                }
            )
        return {"checked_at": now, "due": len(due), "executed": executed}


__all__ = ["Scheduler"]
