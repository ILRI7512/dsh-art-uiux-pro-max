# 架构说明（全部基于实际读过的源码，不含假设）

核查对象：`/root/dsh-autolearn`（v1.1.0，main 分支，2026-10-20 拉取）。

## 一、被复用的引擎事实

| 事实 | 证据位置 |
| --- | --- |
| 引擎是 Python 包 `dsh_autonomous_learning`，65 个 .py，约 1.4 万行 | `find` + `wc -l` |
| 存储在 SQLite，23 张表（projects/tasks/sources/documents/chunks/verification_records/conflicts/duplicates/gaps/practice_tasks/...） | `storage/metadata_store.py` 的 `CREATE TABLE` |
| 向量索引单独一层：默认特征哈希（离线、确定性），可重建 | `storage/vector_store.py` |
| 知识分区是**固定枚举** 7 个 + `pending_knowledge` | `core/models.py::Partition`、`knowledge/partitions.py::PARTITION_SPECS` |
| 每个 Chunk 有单值 `topic` / `subtopic` 字段和自由 `metadata` dict | `core/models.py::Chunk` |
| Source 有 `location/license_status/quality/fetch_ok/error` + 自由 `metadata` | `core/models.py::Source` |
| 学习等级已内置 L0–L5 枚举（本项目只用 L0–L4） | `core/models.py::LearningLevel` |
| 工具注册表强制统一返回结构，并按风险分级（`tool_risks.json`） | `tools/registry.py`、`tool_risks.json` |
| 网络默认关闭：`security.allow_network=False`，可设域名白名单 | `config.py`、`security/permissions.py` |
| 模型层支持 OpenAI 兼容 provider，密钥只从环境变量读 | `config.py::ModelConfig` |
| MCP 入口 `python3 -m dsh_autonomous_learning.plugin`，实测 63 个工具 | 手工 stdio 握手 |
| 引擎 pytest：96 passed | `python3 -m pytest dsh_autonomous_learning/tests` |

## 二、本项目的接入决策

1. **不修改引擎**：`dsh_autonomous_learning/` 原样 vendor 进本项目，只作为依赖使用。
2. **12 个主分类 = `Chunk.topic`**：不扩 Partition 枚举，避免碰引擎的状态机；
   辅助标签进 `Chunk.metadata["secondary_categories"]`，满足「唯一主分类 + 多标签、不重复入库」。
3. **资源注册表 = 种子 + 运行期状态分离**：
   `art_uiux/resources.seed.json`（39 条，只读）＋ `data/registry.json`（真实探测/学习状态）。
4. **三态分离**：`access_status`（能不能访问）、`learn_status`（学到哪一步）、
   `learned_chunks`（真正入库多少条）互不替代，杜绝「登记即完成」。
5. **robots.txt 前置**：`art_uiux/checker.py` 先读 robots 再抓；禁止即记 `blocked`，不绕过。

## 三、目录

```
art_uiux/
  taxonomy.py          12 主分类 + 提取字段定义 + 校验规则
  registry.py          15 字段校验、状态机、种子/状态合并
  checker.py           robots → HTTP → 结论（含软拦截识别）
  resources.seed.json  39 条资源种子
scripts/check_access.py  可重复执行的探测 CLI
docs/                 架构与交付文档
plugins/              DSH 插件包（待接）
dsh_autonomous_learning/  vendored 引擎
```

## 四、当前完成度（不夸大）

- 已完成：架构核查、12 分类定义、39 条资源注册表、真实访问探测、robots 合规。
- 未完成：知识提取入库、语义检索验证、8 项设计任务验证、DSH 插件接线。
