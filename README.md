# DSH Art UI/UX Pro Max

基于 [dsh-autolearn](https://github.com/ILRI7512/dsh-autolearn) 的真实架构构建的 UI/UX 自主学习插件。
目标不是收藏截图，而是把公开资料变成**可检索、可追溯、可验证**的设计知识，并能反向支撑真实设计任务。

## 与 dsh-autolearn 的关系

- `dsh_autonomous_learning/` 是原样 vendor 的引擎（未改一行），提供 SQLite 存储、向量索引、BM25、工具注册、风险分级。
- 本项目在引擎之上加了三层：12 主分类体系、资源注册表、Design Case Analyzer。
- 知识的主分类落在引擎的 `Chunk.topic`（单值字段），辅助标签进 `Chunk.metadata`，因此不碰引擎的 Partition 枚举。

## 快速开始

```bash
# 1. 依赖（引擎已 vendor，只需 Python 侧依赖）
python3 -m pip install --break-system-packages -r dsh_autonomous_learning/requirements.txt
python3 -m pip install --break-system-packages "mcp>=1.2,<2"   # 引擎用的是 1.x 的装饰器 API

# 2. 访问探测（写真实状态，不写「已学习」）
python3 scripts/check_access.py

# 3. 抓取并入库
python3 scripts/ingest.py --limit 5
python3 scripts/ingest.py --only nng,lawsofux,radix

# 4. 案例学习（Design Case Analyzer）
python3 scripts/analyze_case.py --resource linear

# 5. 检索
python3 scripts/query.py "gradient background" --category background_design
```

## 状态字段（三者不可互相替代）

| 字段 | 含义 |
| --- | --- |
| `access_status` | 能不能访问：reachable / restricted / blocked / failed |
| `learn_status` | 学到哪一步：not_started / partial / learned / failed |
| `learned_chunks` | 真正入库的知识条数 |

## 质量等级

L0 原始资料 → L1 已解析并分类 → L2 已提取原则+适用场景 → L3 交叉验证 → L4 设计任务/工程验证。
当前库内只有 L1 与 L2，`verification_status` 全部为 `unverified`，检索时会被强制附告警。

## 测试

```bash
python3 -m pytest tests/test_art_uiux.py -q     # 10 passed
```
