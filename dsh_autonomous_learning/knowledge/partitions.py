"""逻辑知识分区（规则 1）。

第一阶段：**一个**向量索引 + ``partition`` 元数据字段实现逻辑分区，
不绑定任何具体数据库集合名，将来可平滑迁移到物理分区。

分区规则：
- 每条知识必须属于且仅属于一个分区；
- 项目分区（project_knowledge）默认只在所属项目的检索中可见；
- 跨领域引用通过知识关系（edges）表达，**不合并**两条相似知识；
- 待审区（pending_knowledge）是默认落地区，核验通过后才考虑迁出。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from ..core.models import Partition


@dataclass(frozen=True)
class PartitionSpec:
    key: str
    label: str
    description: str
    default_domain: str
    keywords: Sequence[str]
    allow_auto_write: bool = True  # auto 模式下是否允许自动写入


PARTITION_SPECS: Dict[str, PartitionSpec] = {
    Partition.GENERAL.value: PartitionSpec(
        key=Partition.GENERAL.value,
        label="通用知识",
        description="数学、逻辑、基础理论与跨领域通用概念",
        default_domain="general",
        keywords=("数学", "逻辑", "统计", "概率", "算法", "math", "logic", "probability"),
    ),
    Partition.UIUX.value: PartitionSpec(
        key=Partition.UIUX.value,
        label="UI/UX 设计",
        description="视觉设计、交互设计、设计规范、可用性与无障碍",
        default_domain="uiux",
        keywords=("ui", "ux", "设计", "交互", "可用性", "无障碍", "material", "figma", "视觉"),
    ),
    Partition.FINANCE.value: PartitionSpec(
        key=Partition.FINANCE.value,
        label="金融知识",
        description="金融基础、外汇、CFD、加密货币与风险管理",
        default_domain="finance",
        keywords=("金融", "外汇", "利率", "通胀", "cfd", "加密货币", "风控", "杠杆", "保证金"),
    ),
    Partition.QUANT.value: PartitionSpec(
        key=Partition.QUANT.value,
        label="量化交易",
        description="策略、指标、回测、样本外测试与鲁棒性",
        default_domain="quant",
        keywords=("量化", "回测", "夏普", "滑点", "样本外", "策略", "指标", "过拟合", "backtest"),
    ),
    Partition.PROGRAMMING.value: PartitionSpec(
        key=Partition.PROGRAMMING.value,
        label="编程知识",
        description="Python / Rust / Kotlin / TypeScript 等语言与工程实践",
        default_domain="programming",
        keywords=("python", "rust", "kotlin", "typescript", "函数", "接口", "编译", "代码", "api"),
    ),
    Partition.PROJECT.value: PartitionSpec(
        key=Partition.PROJECT.value,
        label="项目知识",
        description="特定项目的架构、接口、决策记录与技术文档（默认项目内可见）",
        default_domain="project",
        keywords=("本项目", "架构", "接口", "决策", "adr", "模块", "部署"),
    ),
    Partition.EXPERIMENT.value: PartitionSpec(
        key=Partition.EXPERIMENT.value,
        label="实验知识",
        description="实验记录、测试结果、失败案例与性能数据",
        default_domain="experiment",
        keywords=("实验", "测试结果", "benchmark", "复现", "失败案例", "性能"),
    ),
    Partition.PENDING.value: PartitionSpec(
        key=Partition.PENDING.value,
        label="待审知识",
        description="尚未核验、等待审核或需要进一步处理的知识（默认落地区）",
        default_domain="general",
        keywords=(),
        allow_auto_write=True,
    ),
}

#: 项目可见性：这些分区默认只在所属项目内可见
PROJECT_SCOPED_PARTITIONS = {Partition.PROJECT.value, Partition.EXPERIMENT.value, Partition.PENDING.value}


def all_partitions() -> List[str]:
    return list(PARTITION_SPECS.keys())


def get_spec(partition: str) -> PartitionSpec:
    if partition not in PARTITION_SPECS:
        raise ValueError(
            f"未知知识分区: {partition}，允许值: {', '.join(all_partitions())}"
        )
    return PARTITION_SPECS[partition]


def partition_for_domain(domain: str) -> str:
    mapping = {
        "general": Partition.GENERAL.value,
        "uiux": Partition.UIUX.value,
        "ui/ux": Partition.UIUX.value,
        "finance": Partition.FINANCE.value,
        "quant": Partition.QUANT.value,
        "programming": Partition.PROGRAMMING.value,
        "project": Partition.PROJECT.value,
        "experiment": Partition.EXPERIMENT.value,
    }
    return mapping.get((domain or "").lower(), Partition.GENERAL.value)


def default_visibility(partition: str) -> str:
    return "project" if partition in PROJECT_SCOPED_PARTITIONS else "global"


def project_partitions(domain: str) -> List[str]:
    """项目默认允许写入的分区：待审区 + 领域分区。"""

    allowed = [Partition.PENDING.value]
    mapped = partition_for_domain(domain)
    if mapped not in allowed:
        allowed.append(mapped)
    return allowed


def ensure_partition_allowed(project: Optional[dict], partition: str) -> None:
    """校验分区是否属于项目的可写范围。"""

    get_spec(partition)
    if not project:
        return
    allowed = project.get("partitions") or []
    if allowed and partition not in allowed:
        raise PermissionError(
            f"分区 {partition} 不在项目 {project.get('project_id')} 的授权分区内"
            f"（允许: {', '.join(allowed)}）"
        )


def describe_partitions() -> List[Dict[str, object]]:
    return [
        {
            "partition": spec.key,
            "label": spec.label,
            "description": spec.description,
            "default_domain": spec.default_domain,
            "project_scoped": spec.key in PROJECT_SCOPED_PARTITIONS,
            "auto_write": spec.allow_auto_write,
        }
        for spec in PARTITION_SPECS.values()
    ]


__all__ = [
    "PARTITION_SPECS",
    "PROJECT_SCOPED_PARTITIONS",
    "PartitionSpec",
    "all_partitions",
    "default_visibility",
    "describe_partitions",
    "ensure_partition_allowed",
    "get_spec",
    "partition_for_domain",
    "project_partitions",
]
