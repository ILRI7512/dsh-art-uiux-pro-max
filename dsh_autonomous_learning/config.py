"""配置系统。

设计要点：
1. 所有配置都有合理默认值，缺省即可运行（离线、无模型 API 也能跑通 P1）。
2. 加载顺序：默认值 -> 配置文件（JSON 或 YAML）-> 环境变量覆盖 -> 显式 overrides。
3. 严格校验：未知字段直接报错（避免拼写错误导致配置静默失效）。
4. 密钥只从环境变量读取，绝不写入配置文件。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

CONFIG_ENV = "DSH_AL_CONFIG"
HOME_ENV = "DSH_AL_HOME"


class ConfigError(ValueError):
    """配置非法。"""


# --------------------------------------------------------------------------- #
# 子配置
# --------------------------------------------------------------------------- #
@dataclass
class PathsConfig:
    """目录与文件位置。"""

    home: str = ""  # 为空时由 DSH_AL_HOME 或包目录推导
    data_dir: str = ""  # 为空时为 <home>/data
    documents_dir: str = ""
    processed_dir: str = ""
    experiments_dir: str = ""
    reports_dir: str = ""
    db_path: str = ""
    index_dir: str = ""
    corpus_dir: str = ""  # 默认本地语料目录（discover_sources 会扫描）
    log_dir: str = ""

    def resolved(self, default_home: Path) -> "PathsConfig":
        home = Path(self.home) if self.home else default_home
        home = home.resolve()
        data = Path(self.data_dir) if self.data_dir else home / "data"
        out = PathsConfig(
            home=str(home),
            data_dir=str(data),
            documents_dir=str(Path(self.documents_dir) if self.documents_dir else data / "documents"),
            processed_dir=str(Path(self.processed_dir) if self.processed_dir else data / "processed"),
            experiments_dir=str(Path(self.experiments_dir) if self.experiments_dir else data / "experiments"),
            reports_dir=str(Path(self.reports_dir) if self.reports_dir else data / "reports"),
            db_path=str(Path(self.db_path) if self.db_path else data / "metadata.sqlite3"),
            index_dir=str(Path(self.index_dir) if self.index_dir else data / "index"),
            corpus_dir=str(Path(self.corpus_dir) if self.corpus_dir else data / "corpus"),
            log_dir=str(Path(self.log_dir) if self.log_dir else data / "logs"),
        )
        return out

    def ensure(self) -> None:
        for attr in (
            "data_dir",
            "documents_dir",
            "processed_dir",
            "experiments_dir",
            "reports_dir",
            "index_dir",
            "corpus_dir",
            "log_dir",
        ):
            Path(getattr(self, attr)).mkdir(parents=True, exist_ok=True)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)


@dataclass
class EmbeddingConfig:
    """向量化配置。

    provider:
      - hashing             纯本地特征哈希（默认，离线可跑，确定性）
      - openai              走 OpenAI 兼容 /embeddings 接口
      - sentence_transformers  本地模型（可选依赖，未安装则明确报错）
    """

    provider: str = "hashing"
    dim: int = 512
    model: str = ""
    base_url: str = ""
    api_key_env: str = "DSH_AL_EMBEDDING_API_KEY"
    timeout_s: int = 30
    batch_size: int = 32

    def validate(self) -> None:
        if self.provider not in {"hashing", "openai", "sentence_transformers"}:
            raise ConfigError(f"embedding.provider 不支持: {self.provider}")
        if self.provider == "hashing" and not (64 <= self.dim <= 8192):
            raise ConfigError("embedding.dim 必须在 64..8192 之间")
        if self.provider == "openai" and not (self.base_url or os.environ.get("OPENAI_BASE_URL")):
            raise ConfigError("embedding.provider=openai 时必须配置 base_url")
        if self.timeout_s <= 0:
            raise ConfigError("embedding.timeout_s 必须为正数")


@dataclass
class ModelConfig:
    """语言模型配置。

    provider:
      - mock                确定性模拟模型（单元测试默认）
      - openai              OpenAI 兼容 /chat/completions（含 commandcode 等）
      - none                完全禁用模型调用（纯规则模式）
    """

    provider: str = "mock"
    base_url: str = ""
    api_key_env: str = "DSH_AL_MODEL_API_KEY"
    model: str = "mock-1"
    timeout_s: int = 60
    max_retries: int = 2
    max_tokens: int = 2048
    temperature: float = 0.2
    rate_limit_per_min: int = 60
    max_cost_usd: float = 0.0  # 0 表示不做费用上限（仍受 max_llm_calls 限制）
    price_input_per_1k: float = 0.0
    price_output_per_1k: float = 0.0
    stages: Dict[str, str] = field(default_factory=dict)  # 阶段 -> 模型名覆盖

    def validate(self) -> None:
        if self.provider not in {"mock", "openai", "none"}:
            raise ConfigError(f"model.provider 不支持: {self.provider}")
        if self.provider == "openai":
            if not self.base_url:
                raise ConfigError("model.provider=openai 时必须配置 base_url")
            if not os.environ.get(self.api_key_env):
                raise ConfigError(
                    f"model.provider=openai 但环境变量 {self.api_key_env} 未设置（密钥不得写入配置）"
                )
        if self.timeout_s <= 0 or self.max_tokens <= 0:
            raise ConfigError("model.timeout_s / max_tokens 必须为正数")
        if self.max_retries < 0:
            raise ConfigError("model.max_retries 不能为负")


@dataclass
class LearningConfig:
    """学习流程与预算。"""

    default_mode: str = "assisted"  # assisted | auto | lab
    max_iterations_per_run: int = 10
    max_tasks_per_run: int = 30
    max_sources_per_task: int = 20
    max_retries_per_task: int = 3
    max_llm_calls_per_run: int = 200
    max_task_seconds: int = 300
    max_run_seconds: int = 3600
    stop_when_no_new_knowledge: bool = True
    no_progress_rounds: int = 3
    stop_when_budget_exceeded: bool = True
    require_source_tracking: bool = True
    require_verification_status: bool = True
    auto_execute_untrusted_code: bool = False
    auto_install_dependencies: bool = False
    auto_modify_other_plugins: bool = False
    daily_budget_usd: float = 1.0
    max_doc_chars: int = 400_000
    chunk_size: int = 900
    chunk_overlap: int = 120
    min_chunk_chars: int = 40
    max_chunks_per_document: int = 400

    def validate(self) -> None:
        if self.default_mode not in {"assisted", "auto", "lab"}:
            raise ConfigError("learning.default_mode 必须是 assisted/auto/lab")
        for name in (
            "max_iterations_per_run",
            "max_tasks_per_run",
            "max_sources_per_task",
            "max_llm_calls_per_run",
            "chunk_size",
            "max_doc_chars",
        ):
            if int(getattr(self, name)) <= 0:
                raise ConfigError(f"learning.{name} 必须为正整数")
        if self.chunk_overlap >= self.chunk_size:
            raise ConfigError("learning.chunk_overlap 必须小于 chunk_size")


@dataclass
class SecurityConfig:
    """安全与执行策略。"""

    allowed_roots: List[str] = field(default_factory=list)  # 允许读取的本地根目录
    allow_network: bool = False
    allowed_domains: List[str] = field(default_factory=list)  # 为空表示不限制（仍受 allow_network 控制）
    max_download_bytes: int = 8 * 1024 * 1024
    max_output_bytes: int = 64 * 1024
    exec_timeout_s: int = 10
    exec_memory_mb: int = 512
    audit_log: bool = True
    block_secret_patterns: bool = True
    # 是否把高风险操作的确认交给宿主（DSH）审批 UI。
    # 开启后本插件不再要求 confirm_token，而是依赖宿主在工具执行前的审批；
    # 独立运行（CLI/其它 MCP 客户端）时保持 false，改用 `confirmations` 子命令人工批准。
    delegate_approval_to_host: bool = False

    def validate(self) -> None:
        if self.exec_timeout_s <= 0:
            raise ConfigError("security.exec_timeout_s 必须为正数")


@dataclass
class RetrievalConfig:
    """检索配置。"""

    top_k: int = 8
    min_score: float = 0.0
    hybrid: bool = True
    vector_weight: float = 0.65
    keyword_weight: float = 0.35
    rrf_k: int = 60
    dedupe_similarity: float = 0.94
    conflict_similarity: float = 0.82


@dataclass
class SchedulerConfig:
    """后台调度配置（默认关闭，避免无限循环）。"""

    enabled: bool = False
    tick_interval_s: int = 300
    max_parallel_projects: int = 1
    auto_start: bool = False


@dataclass
class LoggingConfig:
    level: str = "INFO"
    jsonl: bool = True
    file: str = ""


@dataclass
class Config:
    paths: PathsConfig = field(default_factory=PathsConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    learning: LearningConfig = field(default_factory=LearningConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    # ------------------------------------------------------------------ #
    def validate(self) -> None:
        self.embedding.validate()
        self.model.validate()
        self.learning.validate()
        self.security.validate()
        if self.logging.level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ConfigError("logging.level 非法")
        if self.retrieval.top_k <= 0:
            raise ConfigError("retrieval.top_k 必须为正整数")

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # 绝不回显密钥
        return data

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# 加载
# --------------------------------------------------------------------------- #
def _merge_dataclass(obj: Any, data: Mapping[str, Any], prefix: str = "") -> Any:
    """把字典合并进 dataclass，未知键报错。"""
    if not isinstance(data, Mapping):
        raise ConfigError(f"配置节点 {prefix or '<root>'} 必须是对象")
    allowed = {f.name: f for f in fields(obj)}
    for key, value in data.items():
        if key not in allowed:
            raise ConfigError(f"未知配置项: {prefix + key}")
        current = getattr(obj, key)
        if is_dataclass(current) and isinstance(value, Mapping):
            _merge_dataclass(current, value, prefix=f"{prefix}{key}.")
        else:
            if is_dataclass(current):
                raise ConfigError(f"配置项 {prefix + key} 需要对象")
            setattr(obj, key, value)
    return obj


def _parse_file(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise ConfigError("读取 YAML 配置需要 PyYAML，可改用 JSON 配置") from exc
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text or "{}")
    if not isinstance(data, dict):
        raise ConfigError("配置文件根节点必须是对象")
    return data


def _apply_env(cfg: Config) -> None:
    """少量关键项支持环境变量覆盖（便于 CI / 容器）。"""

    def env(name: str) -> Optional[str]:
        v = os.environ.get(name)
        return v if v not in (None, "") else None

    if v := env("DSH_AL_MODE"):
        cfg.learning.default_mode = v.strip().lower()
    if v := env("DSH_AL_MODEL_PROVIDER"):
        cfg.model.provider = v.strip().lower()
    if v := env("DSH_AL_MODEL_BASE_URL"):
        cfg.model.base_url = v.strip()
    if v := env("DSH_AL_MODEL_NAME"):
        cfg.model.model = v.strip()
    if v := env("DSH_AL_EMBEDDING_PROVIDER"):
        cfg.embedding.provider = v.strip().lower()
    if v := env("DSH_AL_ALLOW_NETWORK"):
        cfg.security.allow_network = v.strip().lower() in {"1", "true", "yes", "on"}
    if v := env("DSH_AL_HOST_APPROVAL"):
        cfg.security.delegate_approval_to_host = v.strip().lower() in {"1", "true", "yes", "on"}
    if v := env("DSH_AL_LOG_LEVEL"):
        cfg.logging.level = v.strip().upper()
    if v := env("DSH_AL_DATA_DIR"):
        cfg.paths.data_dir = v.strip()
    if v := env("DSH_AL_CORPUS_DIR"):
        cfg.paths.corpus_dir = v.strip()


def project_home() -> Path:
    env = os.environ.get(HOME_ENV)
    if env:
        return Path(env)
    return Path(__file__).resolve().parent


# --------------------------------------------------------------------------- #
# 宿主设置卡（DSH 插件设置）共享的 settings.json
# --------------------------------------------------------------------------- #
SETTINGS_FILE_ENV = "DSH_AL_SETTINGS_FILE"


def host_settings_file(home: Path) -> Path:
    """设置卡与 Python 引擎共享的配置文件；环境变量可覆盖（测试/便携部署）。"""

    override = os.environ.get(SETTINGS_FILE_ENV)
    if override:
        return Path(override)
    return home / "data" / "settings.json"


def read_host_settings(home: Path) -> Dict[str, Any]:
    """读取设置卡写入的值；文件缺失或损坏时返回空字典（不阻断启动）。"""

    path = host_settings_file(home)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def apply_host_settings(cfg: Config, home: Path) -> Dict[str, Any]:
    """把设置卡的 mode / dailyBudgetUsd / maxTasksPerRun / dataDir 应用到配置。

    非法值直接忽略：设置卡已做校验，这里再兜一层，避免手改文件把引擎弄挂。
    """

    data = read_host_settings(home)
    applied: Dict[str, Any] = {}
    mode = data.get("mode")
    if isinstance(mode, str) and mode in {"assisted", "auto", "lab"}:
        cfg.learning.default_mode = mode
        applied["mode"] = mode
    budget = data.get("dailyBudgetUsd")
    if isinstance(budget, (int, float)) and not isinstance(budget, bool) and 0 <= float(budget) <= 1000:
        cfg.learning.daily_budget_usd = float(budget)
        applied["dailyBudgetUsd"] = float(budget)
    tasks = data.get("maxTasksPerRun")
    if isinstance(tasks, int) and not isinstance(tasks, bool) and 1 <= tasks <= 200:
        cfg.learning.max_tasks_per_run = tasks
        applied["maxTasksPerRun"] = tasks
    data_dir = data.get("dataDir")
    if isinstance(data_dir, str) and data_dir.strip() and Path(data_dir.strip()).is_absolute():
        cfg.paths.data_dir = data_dir.strip()
        applied["dataDir"] = data_dir.strip()
    return applied


def load_config(
    path: Optional[Path | str] = None,
    overrides: Optional[Mapping[str, Any]] = None,
    home: Optional[Path | str] = None,
) -> Config:
    """加载配置：默认值 + 文件 + 环境变量 + 显式覆盖。"""

    cfg = Config()
    candidate: Optional[Path] = None
    if path:
        candidate = Path(path)
    elif os.environ.get(CONFIG_ENV):
        candidate = Path(os.environ[CONFIG_ENV])
    else:
        for name in ("config.json", "config.yaml", "config.yml"):
            p = (Path(home) if home else project_home()) / name
            if p.exists():
                candidate = p
                break
    if candidate:
        if not candidate.exists():
            raise ConfigError(f"配置文件不存在: {candidate}")
        _merge_dataclass(cfg, _parse_file(candidate))

    base_home = Path(home) if home else project_home()
    # 设置卡（DSH 插件设置）> 静态配置文件；显式环境变量与调用方 overrides 仍然最后生效
    apply_host_settings(cfg, base_home)
    _apply_env(cfg)
    if overrides:
        _merge_dataclass(cfg, overrides)

    default_home = base_home
    cfg.paths = cfg.paths.resolved(default_home)
    cfg.validate()
    return cfg


__all__ = [
    "Config",
    "ConfigError",
    "EmbeddingConfig",
    "LearningConfig",
    "LoggingConfig",
    "ModelConfig",
    "PathsConfig",
    "RetrievalConfig",
    "SchedulerConfig",
    "SecurityConfig",
    "load_config",
    "project_home",
]
