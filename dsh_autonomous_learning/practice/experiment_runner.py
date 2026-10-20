"""受控实验执行与结果记录。

实验规范（spec）示例::

    {
      "name": "验证排序稳定性",
      "code": "print('ok')",
      "assert_stdout_contains": ["ok"],
      "timeout_s": 10
    }

执行约束与 test_runner 相同：lab 模式 + 可信标记 + 受限目录 + 超时 + 输出上限。
实验产物（spec.json / main.py / result.json）保存在 data/experiments 下，可复现。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ..core.models import new_id, utcnow_iso
from ..security.execution_policy import ExecutionDenied, ExecutionPolicy, scan_code
from ..storage.metadata_store import MetadataStore


class ExperimentRunner:
    def __init__(self, policy: ExecutionPolicy, metadata: MetadataStore, experiments_dir: str | Path) -> None:
        self.policy = policy
        self.metadata = metadata
        self.experiments_dir = Path(experiments_dir)
        self.experiments_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    def run(
        self,
        *,
        project_id: str,
        spec: Mapping[str, Any],
        task_id: str = "",
        trusted: bool = False,
    ) -> Dict[str, Any]:
        code = str(spec.get("code") or "")
        if not code.strip():
            raise ValueError("实验 spec 必须包含 code")
        name = str(spec.get("name") or "experiment")
        assertions: List[str] = list(spec.get("assert_stdout_contains") or [])
        timeout_s = spec.get("timeout_s")

        artifact_dir = self.policy.prepare_dir(self.experiments_dir, "exp")
        (artifact_dir / "spec.json").write_text(
            json.dumps(dict(spec), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (artifact_dir / "main.py").write_text(code, encoding="utf-8")

        experiment_id = new_id("exp")
        started = time.monotonic()
        try:
            result = self.policy.run_python(
                code, workdir=artifact_dir, timeout_s=timeout_s, trusted=trusted
            ).to_dict()
        except ExecutionDenied as exc:
            result = {
                "ok": False,
                "stdout": "",
                "stderr": f"实验被拒绝: {exc}",
                "exit_code": None,
                "duration_ms": 0,
                "timed_out": False,
                "isolation": "none",
                "warnings": ["执行策略拒绝，未运行任何代码"],
                "environment": {},
            }

        missing = [token for token in assertions if token not in (result.get("stdout") or "")]
        passed = bool(result.get("ok")) and not missing
        row = {
            "experiment_id": experiment_id,
            "project_id": project_id,
            "task_id": task_id,
            "spec": dict(spec),
            "result": {
                **result,
                "assertions": assertions,
                "missing_assertions": missing,
                "passed": passed,
                "artifact_dir": str(artifact_dir),
                "duration_s": round(time.monotonic() - started, 3),
                "static_findings": scan_code(code),
                "trusted": trusted,
            },
            "status": "passed" if passed else "failed",
            "artifact_dir": str(artifact_dir),
            "created_at": utcnow_iso(),
        }
        self.metadata.add_experiment(row)

        (artifact_dir / "result.json").write_text(
            json.dumps(row["result"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        row["code_hash"] = hashlib.sha256(code.encode("utf-8", errors="replace")).hexdigest()
        return row

    # ------------------------------------------------------------------ #
    def record_result(
        self,
        *,
        project_id: str,
        spec: Mapping[str, Any],
        result: Mapping[str, Any],
        task_id: str = "",
    ) -> Dict[str, Any]:
        """记录人工/外部执行得到的实验结果（不运行代码）。"""

        if not result:
            raise ValueError("result 不能为空；没有结果就不要记录实验")
        row = {
            "experiment_id": new_id("exp"),
            "project_id": project_id,
            "task_id": task_id,
            "spec": dict(spec),
            "result": dict(result),
            "status": str(result.get("status") or ("passed" if result.get("ok") else "failed")),
            "artifact_dir": str(result.get("artifact_dir") or ""),
            "created_at": utcnow_iso(),
        }
        self.metadata.add_experiment(row)
        return row


__all__ = ["ExperimentRunner"]
