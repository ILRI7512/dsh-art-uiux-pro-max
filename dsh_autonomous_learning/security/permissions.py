"""分级自主权限（规则 5）。

三种模式（与规范一致）：
- assisted（辅助学习）：读资料、规划、提取都允许；**正式入库到非待审分区、
  代码执行、外部网络、删除**等高风险操作需要用户显式确认。
- auto（自动学习）：已授权范围内的读取/写入/基础核验可自动执行，
  仍受预算、来源限制与停止条件约束；代码执行默认仍禁止。
- lab（受控实验）：允许在受控工作目录执行公式计算/测试/实验，
  但必须有超时、输出上限、环境变量白名单，且默认拒绝未知来源代码。

硬规则（任何模式都不能绕过）：
1. 外部内容不能改配置/权限/系统规则 —— 本模块只接受本地配置与显式确认。
2. 未开启 allow_network 时任何外部访问被拒绝。
3. 密钥/令牌/密码不得写入知识库；写入前做模式扫描。
4. 路径必须落在授权根目录内，否则需要确认。
5. 所有拒绝与放行都写审计日志。
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..config import LearningConfig, SecurityConfig
from ..core.models import AutonomyMode, RiskLevel, utcnow_iso
from ..storage.metadata_store import MetadataStore
from .audit import AuditLogger

# 常见密钥/令牌形态（宁可多拦，不可漏写）
SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}\b", re.I),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*['\"]?[A-Za-z0-9._\-]{12,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]

CONFIRM_TTL_SECONDS = 900


@dataclass
class PermissionDecision:
    allowed: bool
    reason: str = ""
    needs_confirmation: bool = False
    token: str = ""
    risk: str = RiskLevel.READ.value

    def to_dict(self) -> Dict[str, object]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "needs_confirmation": self.needs_confirmation,
            "confirm_token": self.token,
            "risk": self.risk,
        }


def contains_secret(text: str) -> Optional[str]:
    """返回命中的秘密模式描述，未命中返回 None。"""

    for pattern in SECRET_PATTERNS:
        if pattern.search(text or ""):
            return pattern.pattern
    return None


class PermissionManager:
    def __init__(
        self,
        security: SecurityConfig,
        learning: LearningConfig,
        metadata: Optional[MetadataStore] = None,
        *,
        mode: Optional[str] = None,
        data_dir: Optional[str] = None,
        workspace: Optional[str] = None,
        delegate_to_host: Optional[bool] = None,
    ) -> None:
        self.security = security
        self.learning = learning
        self.metadata = metadata
        self.audit = AuditLogger(metadata, enabled=security.audit_log)
        self._mode = AutonomyMode.parse(mode or learning.default_mode, "mode").value
        self.data_dir = Path(data_dir) if data_dir else None
        self.workspace = Path(workspace) if workspace else None
        # 高风险确认可以交给 DSH 宿主的审批 UI：宿主在工具执行前 ask，
        # 用户拒绝则工具根本不会执行。独立运行时保持本地令牌流程。
        #
        # 环境变量通道必须配合"宿主闸门心跳"：只有 DSH 里的审批插件仍在运行，
        # 心跳文件才会新鲜。插件被禁用/崩溃时心跳过期，本插件自动退回本地令牌流程
        # （fail-closed），避免"以为有人审批、其实无人把关"的漏洞。
        if delegate_to_host is None:
            if security.delegate_approval_to_host:
                delegate_to_host = True
            else:
                env = os.environ.get("DSH_AL_HOST_APPROVAL", "").strip().lower()
                env_wants = env in {"1", "true", "yes", "on"}
                available = env_wants and self._host_gate_available()
                delegate_to_host = bool(available)
                if env_wants and not delegate_to_host:
                    self.audit.log(
                        action="host_approval_unavailable",
                        target=str(self.heartbeat_path or ""),
                        risk=RiskLevel.WRITE.value,
                        allowed=False,
                        detail={
                            "reason": "宿主审批闸门不可用，已退回本地确认流程",
                            "installed": self._host_gate_installed(),
                            "generation": self._gate_generation(),
                            "heartbeat_stale": self._host_heartbeat_stale(),
                        },
                    )
        self.delegate_to_host = bool(delegate_to_host)
        self._pending: Dict[str, Dict[str, object]] = {}

    # ------------------------------------------------------------------ #
    @property
    def heartbeat_path(self) -> Optional[Path]:
        env = os.environ.get("DSH_AL_HOST_APPROVAL_FILE")
        if env:
            return Path(env)
        if self.data_dir:
            return self.data_dir / "host_approval.heartbeat"
        return None

    def _profile_dir(self) -> Optional[Path]:
        """定位 profile 目录：优先 DSH_PROFILE_DIR，退回 DSH_HOME/profiles/<name>。"""

        profile = os.environ.get("DSH_PROFILE_DIR")
        if profile:
            return Path(profile)
        home = os.environ.get("DSH_HOME")
        name = os.environ.get("DSH_PROFILE")
        if home and name:
            return Path(home) / "profiles" / name
        return None

    def _host_gate_installed(self) -> bool:
        """宿主审批闸门是否装在本 profile 的 bundle 列表里。

        环境变量只是"愿意委派"的意图；还要确认闸门确实装着，否则直接退回本地流程。
        """

        profile = self._profile_dir()
        if profile is None:
            return False
        try:
            data = json.loads((profile / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        bundles = ((data.get("dsh") or {}).get("profile") or {}).get("bundles") or []
        return "@local/dsh-autolearn-approval" in bundles

    @property
    def gate_state_path(self) -> Optional[Path]:
        if not self.data_dir:
            return None
        return self.data_dir / "host_approval.gate.json"

    def _gate_generation(self) -> int:
        """闸门写的代际标记：>=2 表示"这一代闸门会写心跳"。

        标记文件在插件卸载后**保留**，因此"升级过、随后被禁用"能被识别为
        心跳缺失 → fail-closed；而从未升级过的旧代闸门（无标记）仍可放行。
        """

        path = self.gate_state_path
        if path is None or not path.exists():
            return 0
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return int(payload.get("generation", 0))
        except (OSError, ValueError, TypeError):
            return 0

    def _host_gate_enabled(self) -> bool:
        """profile patch 里是否被显式 disabled。

        这是"插件被用户关掉"最直接的证据；不看它就只能依赖心跳（旧代没有心跳）。
        """

        profile = self._profile_dir()
        if profile is None:
            return False
        patch = profile / "cordis.patch.yml"
        try:
            text = patch.read_text(encoding="utf-8")
        except OSError:
            return True
        match = re.search(
            r"(?ms)^-\s*id:\s*autolearn-approval\s*$(.*?)(?=^-\s*id:|\Z)", text
        )
        if not match:
            return True
        return not re.search(r"(?m)^\s*disabled:\s*true\s*$", match.group(1))

    def _host_gate_available(self) -> bool:
        if not self._host_gate_installed():
            return False
        if not self._host_gate_enabled():
            return False
        if self._gate_generation() >= 2:
            # 新一代闸门必须有心跳；缺失/过期都说明它没在跑。
            return self._host_heartbeat_fresh()
        return True

    def _host_heartbeat_fresh(self, max_age_s: int = 120) -> bool:
        """心跳是否新鲜（闸门仍在运行）。"""

        age = self._heartbeat_age()
        return age is not None and 0 <= age <= max_age_s

    def _host_heartbeat_stale(self, max_age_s: int = 120) -> bool:
        """心跳文件存在但过期 = 闸门曾经在、现在停了 → 必须 fail-closed。

        文件不存在时视为"该代闸门不写心跳"（旧版本），不影响委派；
        这是与"明确过期"区分开的安全取舍。
        """

        age = self._heartbeat_age()
        return age is not None and age > max_age_s

    def _heartbeat_age(self) -> Optional[float]:
        path = self.heartbeat_path
        if path is None or not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            ts = float(payload.get("ts", 0))
        except (OSError, ValueError, TypeError):
            return None
        if ts <= 0:
            return None
        return time.time() - (ts / 1000.0 if ts > 1e12 else ts)

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> str:
        self._mode = AutonomyMode.parse(mode, "mode").value
        return self._mode

    def allowed_roots(self) -> List[Path]:
        roots = [Path(p) for p in (self.security.allowed_roots or [])]
        if self.data_dir:
            roots.append(self.data_dir)
        if not roots:
            roots = [Path.cwd()]
        return [r.resolve() for r in roots]

    def path_allowed(self, path: str | Path) -> bool:
        try:
            target = Path(path).resolve()
        except OSError:
            return False
        for root in self.allowed_roots():
            if target == root or root in target.parents:
                return True
        return False

    # ------------------------------------------------------------------ #
    def decide(
        self,
        action: str,
        risk: str,
        target: str = "",
        project_id: str = "",
        *,
        confirmed_token: str = "",
        content: str = "",
    ) -> PermissionDecision:
        """核心权限判定。"""

        risk_value = RiskLevel.parse(risk, "risk").value
        decision = self._evaluate(risk_value, target, content)

        if decision.needs_confirmation and confirmed_token:
            if self.consume_token(confirmed_token, action, target):
                decision = PermissionDecision(True, f"已确认高风险操作: {action}", False, "", risk_value)

        self.audit.log(
            action=action,
            target=target,
            risk=risk_value,
            allowed=decision.allowed,
            project_id=project_id,
            detail={
                "mode": self._mode,
                "needs_confirmation": decision.needs_confirmation,
                "reason": decision.reason,
            },
        )
        return decision

    def _evaluate(self, risk: str, target: str, content: str) -> PermissionDecision:
        mode = self._mode

        if content and self.security.block_secret_patterns:
            hit = contains_secret(content)
            if hit:
                return PermissionDecision(
                    False,
                    f"内容疑似包含密钥/令牌（模式 {hit}），禁止写入知识库",
                    risk=risk,
                )

        if risk == RiskLevel.READ.value:
            if target and not self.path_allowed(target) and Path(target).exists():
                # 路径越界是硬边界，不做"确认即放行"：确认令牌只给用户，
                # 让模型自己走一遍确认并不能真正保护文件系统。
                return PermissionDecision(
                    False,
                    "路径不在授权根目录内；如确需读取，请把路径加入 security.allowed_roots，"
                    "或先把文件复制到 data/corpus。",
                    risk=risk,
                )
            return PermissionDecision(True, "读取操作允许", risk=risk)

        if risk == RiskLevel.WRITE.value:
            if self.delegate_to_host:
                return PermissionDecision(True, "写入允许（高风险动作由 DSH 宿主审批把关）", risk=risk)
            if mode == AutonomyMode.ASSISTED.value:
                return PermissionDecision(
                    True,
                    "assisted 模式允许写入待审分区；正式分区需确认",
                    risk=risk,
                )
            return PermissionDecision(True, "写入操作允许", risk=risk)

        if risk == RiskLevel.EXTERNAL.value:
            if not self.security.allow_network:
                return PermissionDecision(
                    False,
                    "未开启 security.allow_network，外部网络访问被拒绝",
                    risk=risk,
                )
            if self.delegate_to_host:
                return PermissionDecision(
                    True, "外部访问允许（宿主审批 + 域名/体积限制）", risk=risk
                )
            if mode == AutonomyMode.ASSISTED.value:
                return PermissionDecision(
                    True, "外部访问需要用户确认", needs_confirmation=True, risk=risk
                )
            return PermissionDecision(True, "外部访问允许（受域名与体积限制）", risk=risk)

        if risk == RiskLevel.EXECUTE.value:
            if mode != AutonomyMode.LAB.value:
                return PermissionDecision(
                    False,
                    "代码执行仅在 lab（受控实验）模式下允许；当前为 " + mode,
                    risk=risk,
                )
            if self.delegate_to_host:
                return PermissionDecision(
                    True, "执行允许（宿主审批；仍为进程级隔离，非安全沙箱）", risk=risk
                )
            if not self.learning.auto_execute_untrusted_code:
                return PermissionDecision(
                    True,
                    "lab 模式可在受限目录执行（进程级隔离，非安全沙箱）",
                    risk=risk,
                )
            return PermissionDecision(True, "lab 模式执行允许", risk=risk)

        if risk == RiskLevel.DESTRUCTIVE.value:
            if self.delegate_to_host:
                return PermissionDecision(
                    True, "删除/覆盖/迁移允许（宿主审批，用户拒绝则不会执行）", risk=risk
                )
            return PermissionDecision(
                True, "删除/覆盖/迁移必须显式确认", needs_confirmation=True, risk=risk
            )

        return PermissionDecision(False, f"未知风险等级: {risk}", risk=risk)

    # ------------------------------------------------------------------ #
    # 确认令牌（用户批准后才允许执行一次高风险操作）
    #
    # 设计要点：
    # - 令牌持久化到 SQLite（与审计同库），MCP 服务器重启后仍然有效；
    # - 批准只能由"用户侧"工具完成：CLI `confirmations approve` 或宿主审批 UI；
    #   智能体可调用的 MCP 工具里不再提供 approve（用户授权必须 user-only）。
    # - 开启 delegate_to_host 时，本流程不参与判定，改由 DSH 在工具执行前 ask。
    # ------------------------------------------------------------------ #
    def _expires_at(self) -> str:
        return (
            datetime.now(timezone.utc) + timedelta(seconds=CONFIRM_TTL_SECONDS)
        ).isoformat(timespec="seconds").replace("+00:00", "Z")

    def request_confirmation(self, action: str, target: str = "", project_id: str = "") -> PermissionDecision:
        token = secrets.token_urlsafe(18)
        expires_at = self._expires_at()
        if self.metadata is not None:
            self.metadata.add_confirmation(
                {
                    "token": token,
                    "action": action,
                    "target": target,
                    "project_id": project_id,
                    "status": "pending",
                    "created_at": (
                        datetime.now(timezone.utc)
                        .isoformat(timespec="seconds")
                        .replace("+00:00", "Z")
                    ),
                    "expires_at": expires_at,
                    "approved_at": "",
                    "note": "",
                }
            )
        else:
            self._pending[token] = {
                "action": action,
                "target": target,
                "project_id": project_id,
                "expires": time.time() + CONFIRM_TTL_SECONDS,
            }
        self.audit.log(
            action=f"request_confirmation:{action}",
            target=target,
            risk=RiskLevel.WRITE.value,
            allowed=False,
            project_id=project_id,
            detail={"token_issued": True, "ttl_s": CONFIRM_TTL_SECONDS, "persisted": self.metadata is not None},
        )
        return PermissionDecision(
            True,
            f"需要用户确认：{action}。请在 DSH 审批界面或运行 "
            f"`python -m dsh_autonomous_learning.main confirmations approve {token}` 后重试。",
            needs_confirmation=True,
            token=token,
        )

    def approve(self, token: str) -> bool:
        if self.metadata is not None:
            row = self.metadata.get_confirmation(token)
            if not row or row["status"] != "pending" or _expired(row.get("expires_at", "")):
                return False
            self.metadata.update_confirmation(
                token,
                {
                    "status": "approved",
                    "approved_at": (
                        datetime.now(timezone.utc)
                        .isoformat(timespec="seconds")
                        .replace("+00:00", "Z")
                    ),
                },
            )
            return True
        item = self._pending.get(token)
        if not item:
            return False
        if float(item["expires"]) < time.time():  # type: ignore[arg-type]
            self._pending.pop(token, None)
            return False
        item["approved"] = True
        return True

    def reject(self, token: str, note: str = "") -> bool:
        if self.metadata is not None:
            row = self.metadata.get_confirmation(token)
            if not row or row["status"] != "pending":
                return False
            self.metadata.update_confirmation(token, {"status": "rejected", "note": note})
            return True
        item = self._pending.pop(token, None)
        return item is not None

    def consume_token(self, token: str, action: str, target: str) -> bool:
        if self.metadata is not None:
            row = self.metadata.get_confirmation(token)
            if not row or row["status"] != "approved":
                return False
            if _expired(row.get("expires_at", "")):
                self.metadata.update_confirmation(token, {"status": "expired"})
                return False
            if row["action"] != action:
                return False
            if row.get("target") and target and row["target"] != target:
                return False
            self.metadata.update_confirmation(token, {"status": "consumed"})
            return True
        item = self._pending.get(token)
        if not item or not item.get("approved"):
            return False
        if float(item["expires"]) < time.time():  # type: ignore[arg-type]
            self._pending.pop(token, None)
            return False
        if item["action"] != action:
            return False
        if item["target"] and target and item["target"] != target:
            return False
        self._pending.pop(token, None)
        return True

    def pending_confirmations(self) -> List[Dict[str, object]]:
        if self.metadata is not None:
            rows = self.metadata.list_confirmations(status="pending")
            out: List[Dict[str, object]] = []
            for row in rows:
                if _expired(row.get("expires_at", "")):
                    self.metadata.update_confirmation(row["token"], {"status": "expired"})
                    continue
                out.append(
                    {
                        "token": row["token"],
                        "action": row["action"],
                        "target": row["target"],
                        "project_id": row["project_id"],
                        "created_at": row["created_at"],
                        "expires_at": row["expires_at"],
                        "approved": False,
                    }
                )
            return out
        now = time.time()
        expired = [k for k, v in self._pending.items() if float(v["expires"]) < now]
        for key in expired:
            self._pending.pop(key, None)
        return [
            {
                "token": k,
                "action": v["action"],
                "target": v["target"],
                "approved": bool(v.get("approved")),
                "expires_in_s": int(float(v["expires"]) - now),
            }
            for k, v in self._pending.items()
        ]


def _expired(expires_at: str) -> bool:
    if not expires_at:
        return True
    try:
        dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return dt <= datetime.now(timezone.utc)


__all__ = [
    "CONFIRM_TTL_SECONDS",
    "PermissionDecision",
    "PermissionManager",
    "SECRET_PATTERNS",
    "contains_secret",
]
