"""执行策略与受限执行。

必须诚实说明的边界（规范第十二节明确要求）：
- 这不是安全沙箱。Python 的 ``exec``/``eval``/简单子进程超时都不能构成沙箱。
- 因此在没有真正隔离环境时，默认**禁止执行不可信代码**：
  * 代码执行只在 lab 模式、且经过静态风险扫描、且工作目录被限定在
    ``data/experiments/<id>`` 时允许；
  * 子进程使用 ``-I`` 隔离模式、清空环境变量白名单、限制超时与输出大小；
  * 任何"来源未知 + 未标记可信"的代码默认拒绝。
- 公式验证走 AST 白名单求值（不执行任意代码），这是真正安全的实现。
"""

from __future__ import annotations

import ast
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..config import LearningConfig, SecurityConfig

# --------------------------------------------------------------------------- #
# 公式安全求值
# --------------------------------------------------------------------------- #
_SAFE_FUNCTIONS: Dict[str, Any] = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "pow": pow,
    "sum": sum,
    "len": len,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "floor": math.floor,
    "ceil": math.ceil,
    "pi": math.pi,
    "e": math.e,
}

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv)
_ALLOWED_UNARY = (ast.UAdd, ast.USub)
_FORBIDDEN_NODES = (
    ast.Attribute,
    ast.Subscript,
    ast.Lambda,
    ast.Compare,
    ast.BoolOp,
    ast.IfExp,
    ast.ListComp,
    ast.DictComp,
    ast.SetComp,
    ast.GeneratorExp,
    ast.Await,
    ast.Yield,
    ast.Import,
    ast.ImportFrom,
    ast.Call,
)


class ExecutionDenied(RuntimeError):
    """执行被策略拒绝。"""


class FormulaError(ValueError):
    """公式求值失败（语法或数值问题）。"""


def safe_eval_expression(
    expression: str, variables: Optional[Mapping[str, float]] = None
) -> float:
    """白名单 AST 求值：只允许四则运算、幂、取模，以及安全数学函数。

    不调用 ``eval``，不接触内置命名空间，因此不存在任意代码执行风险。
    """

    variables = dict(variables or {})
    expr = (expression or "").replace("^", "**")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"公式语法错误: {exc.msg}") from exc

    def _ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _ev(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return float(node.value)
            raise FormulaError(f"不支持的常量: {node.value!r}")
        if isinstance(node, ast.Name):
            if node.id in variables:
                return float(variables[node.id])
            if node.id in _SAFE_FUNCTIONS and isinstance(_SAFE_FUNCTIONS[node.id], (int, float)):
                return float(_SAFE_FUNCTIONS[node.id])
            raise FormulaError(f"未定义变量: {node.id}")
        if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOPS):
            left, right = _ev(node.left), _ev(node.right)
            op = node.op
            if isinstance(op, ast.Add):
                return left + right
            if isinstance(op, ast.Sub):
                return left - right
            if isinstance(op, ast.Mult):
                return left * right
            if isinstance(op, ast.Div):
                if right == 0:
                    raise FormulaError("除以零")
                return left / right
            if isinstance(op, ast.Pow):
                return left ** right
            if isinstance(op, ast.Mod):
                if right == 0:
                    raise FormulaError("取模零")
                return left % right
            if isinstance(op, ast.FloorDiv):
                if right == 0:
                    raise FormulaError("整除零")
                return left // right
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, _ALLOWED_UNARY):
            value = _ev(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _SAFE_FUNCTIONS:
                raise FormulaError("只允许调用白名单数学函数")
            if node.keywords:
                raise FormulaError("不允许关键字参数")
            func = _SAFE_FUNCTIONS[node.func.id]
            if not callable(func):
                raise FormulaError(f"{node.func.id} 不是函数")
            return float(func(*[_ev(arg) for arg in node.args]))
        raise FormulaError(f"不允许的语法节点: {type(node).__name__}")

    try:
        result = _ev(tree)
    except (ZeroDivisionError, OverflowError, ValueError) as exc:
        raise FormulaError(f"计算失败: {exc}") from exc
    if math.isnan(result) or math.isinf(result):
        raise FormulaError("计算结果不是有限数值")
    return result


# --------------------------------------------------------------------------- #
# 代码静态风险扫描
# --------------------------------------------------------------------------- #
_DANGEROUS_TOKENS = (
    "os.system",
    "subprocess",
    "os.popen",
    "shutil.rmtree",
    "eval(",
    "exec(",
    "__import__",
    "ctypes",
    "socket.",
    "requests.get",
    "urllib.request",
    "urlopen",
    "open('/",
    'open("/',
    "pathlib.Path.home",
    "os.environ",
    "webbrowser",
    "pickle.loads",
    "marshal.loads",
    "importlib",
    "pty.",
    "fork(",
)


def scan_code(code: str) -> List[str]:
    """返回命中的危险模式（用于解释拒绝原因，不做安全保证）。"""

    lowered = (code or "").lower()
    return [token for token in _DANGEROUS_TOKENS if token.lower() in lowered]


# --------------------------------------------------------------------------- #
# 子进程执行
# --------------------------------------------------------------------------- #
@dataclass
class ExecutionResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    duration_ms: int = 0
    timed_out: bool = False
    truncated: bool = False
    isolation: str = "process"
    warnings: List[str] = field(default_factory=list)
    environment: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
            "truncated": self.truncated,
            "isolation": self.isolation,
            "warnings": list(self.warnings),
            "environment": self.environment,
        }


class ExecutionPolicy:
    """封装"能不能跑"和"怎么跑"。"""

    def __init__(self, security: SecurityConfig, learning: LearningConfig, mode: str = "assisted") -> None:
        self.security = security
        self.learning = learning
        self.mode = mode
        self._env_allow = {
            "PYTHONIOENCODING",
            "PYTHONHASHSEED",
            "TZ",
            "LANG",
            "LC_ALL",
        }

    # ------------------------------------------------------------------ #
    def check(self, *, trusted: bool, code: str = "") -> List[str]:
        """返回拒绝原因列表；空列表表示允许。"""

        reasons: List[str] = []
        if self.mode != "lab":
            reasons.append(f"当前模式 {self.mode} 不执行代码（仅 lab 模式允许）")
        if not trusted and not self.learning.auto_execute_untrusted_code:
            reasons.append("代码来源未标记可信，且配置禁止自动执行不可信代码")
        findings = scan_code(code)
        if findings and not trusted:
            reasons.append("静态风险扫描命中: " + ", ".join(findings))
        return reasons

    def prepare_dir(self, root: str | Path, tag: str = "exp") -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = Path(root) / f"{tag}-{stamp}-{int(time.time() * 1000) % 100000}"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def run_python(
        self,
        code: str,
        *,
        workdir: str | Path,
        timeout_s: Optional[int] = None,
        max_output_bytes: Optional[int] = None,
        trusted: bool = False,
    ) -> ExecutionResult:
        reasons = self.check(trusted=trusted, code=code)
        if reasons:
            raise ExecutionDenied("；".join(reasons))

        workdir = Path(workdir)
        if not workdir.exists():
            raise ExecutionDenied(f"工作目录不存在: {workdir}")
        timeout = int(timeout_s or self.security.exec_timeout_s)
        limit = int(max_output_bytes or self.security.max_output_bytes)

        env = {k: v for k, v in os.environ.items() if k in self._env_allow}
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONHASHSEED", "0")

        cmd = [sys.executable, "-I", "-X", "utf8", "-c", code]
        kwargs: Dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

        started = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(workdir),
                env=env,
                capture_output=True,
                timeout=timeout,
                text=True,
                encoding="utf-8",
                errors="replace",
                **kwargs,
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            stdout, out_trunc = _truncate(proc.stdout or "", limit)
            stderr, err_trunc = _truncate(proc.stderr or "", limit)
            result = ExecutionResult(
                ok=proc.returncode == 0,
                stdout=stdout,
                stderr=stderr,
                exit_code=proc.returncode,
                duration_ms=duration_ms,
                truncated=out_trunc or err_trunc,
                warnings=[
                    "进程级隔离（-I、空环境白名单、超时与输出上限），不是安全沙箱",
                ],
                environment={
                    "python": sys.version.split()[0],
                    "platform": sys.platform,
                    "cwd": str(workdir),
                    "timeout_s": timeout,
                    "max_output_bytes": limit,
                },
            )
            return result
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            stdout, _ = _truncate((exc.stdout or "") if isinstance(exc.stdout, str) else "", limit)
            return ExecutionResult(
                ok=False,
                stdout=stdout,
                stderr=f"执行超时（>{timeout}s），进程已终止",
                exit_code=None,
                duration_ms=duration_ms,
                timed_out=True,
                warnings=["超时终止；如为死循环，代码逻辑需要修正"],
                environment={"python": sys.version.split()[0], "cwd": str(workdir)},
            )


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text.encode("utf-8", errors="replace")) <= limit:
        return text, False
    clipped = text.encode("utf-8", errors="replace")[:limit].decode("utf-8", errors="replace")
    return clipped + "\n...[输出已截断]", True


__all__ = [
    "ExecutionDenied",
    "ExecutionPolicy",
    "ExecutionResult",
    "FormulaError",
    "safe_eval_expression",
    "scan_code",
]
