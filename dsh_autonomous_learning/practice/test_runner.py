"""受限代码测试执行器。

边界声明（必须诚实）：
- 采用 ``python -I`` 子进程 + 独立工作目录 + 清空环境变量白名单 + 超时 + 输出上限；
- 这是**进程级隔离**，不是安全沙箱。因此默认只允许 lab 模式 + 显式可信代码；
- 执行结果（含 stdout/stderr/退出码/环境）全部落库，作为核验证据；
- 代码来自外部文档时默认 trusted=False，扫描命中危险模式直接拒绝。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from ..core.models import PracticeStatus, new_id, utcnow_iso
from ..security.execution_policy import ExecutionDenied, ExecutionPolicy, ExecutionResult, scan_code
from ..storage.metadata_store import MetadataStore


class CodeTestRunner:
    def __init__(self, policy: ExecutionPolicy, metadata: MetadataStore, experiments_dir: str | Path) -> None:
        self.policy = policy
        self.metadata = metadata
        self.experiments_dir = Path(experiments_dir)
        self.experiments_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    def run(
        self,
        *,
        code: str,
        language: str = "python",
        trusted: bool = False,
        practice_id: Optional[str] = None,
        project_id: str = "",
        timeout_s: Optional[int] = None,
        filename: str = "main.py",
    ) -> Dict[str, Any]:
        if language.lower() not in {"python", "py"}:
            raise ExecutionDenied(
                f"仅支持 Python 受限执行，收到 language={language}；"
                "其它语言请改用静态审查或人工验证"
            )
        if not (code or "").strip():
            raise ValueError("code 不能为空")

        artifact_dir = self.policy.prepare_dir(self.experiments_dir, "test")
        (artifact_dir / filename).write_text(code, encoding="utf-8")
        findings = scan_code(code)

        try:
            result: ExecutionResult = self.policy.run_python(
                code,
                workdir=artifact_dir,
                timeout_s=timeout_s,
                trusted=trusted,
            )
            payload = result.to_dict()
        except ExecutionDenied as exc:
            payload = {
                "ok": False,
                "stdout": "",
                "stderr": f"执行被拒绝: {exc}",
                "exit_code": None,
                "duration_ms": 0,
                "timed_out": False,
                "isolation": "none",
                "warnings": ["执行策略拒绝，未运行任何代码"],
                "environment": {"cwd": str(artifact_dir)},
            }

        payload.update(
            {
                "artifact_dir": str(artifact_dir),
                "static_findings": findings,
                "trusted": trusted,
                "language": "python",
                "project_id": project_id,
                "practice_id": practice_id or "",
                "created_at": utcnow_iso(),
            }
        )
        (artifact_dir / "result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        if practice_id:
            self.metadata.add_practice_result(
                {
                    "result_id": new_id("res"),
                    "practice_id": practice_id,
                    "status": PracticeStatus.PASSED.value if payload["ok"] else PracticeStatus.FAILED.value,
                    "input_data": {"code_hash_ok": True, "chars": len(code)},
                    "environment": payload.get("environment", {}),
                    "output": (payload.get("stdout") or "")[:8000],
                    "error": (payload.get("stderr") or "")[:4000],
                    "exit_code": payload.get("exit_code"),
                    "conclusion": "执行成功" if payload["ok"] else "执行失败",
                    "artifact_dir": str(artifact_dir),
                    "duration_ms": int(payload.get("duration_ms") or 0),
                    "created_at": utcnow_iso(),
                }
            )
        return payload


__all__ = ["CodeTestRunner"]
