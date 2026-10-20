# DSH Art UI/UX Pro Max

基于 [dsh-autolearn](https://github.com/ILRI7512/dsh-autolearn) 的真实架构构建的 **UI/UX 自主学习插件**。

它不做三件事：不收藏截图、不把网页可访问当成学习完成、不把审美判断当成可用性结论。
它做一件事：把公开资料变成**可检索、可追溯、可量化评测**的设计知识，并能反向支撑真实设计任务。

## 架构

```
dsh_autonomous_learning/   引擎（vendor 自 dsh-autolearn v1.1.0，未改动一行）
art_uiux/                  本项目的三层扩展
  taxonomy.py              12 个主分类 × 12 项元数据 + 16 个提取字段
  registry.py              资源注册表（15 字段 / 三态分离 / 种子与运行期状态解耦）
  checker.py               robots 前置探测 + 软拦截识别
  extract.py               分节、分类（含领域先验）、16 字段模板、质量门槛
  case_analyzer.py         Design Case Analyzer（fact / inference / opinion 三分）
  design_workflow.py       七步设计工作流 + WCAG 对比度实算 + 10 项审计
  retrieval.py             混合检索 + 分类亲和度 + 词面重叠重排
  bilingual.py             中英设计术语桥接（70 条）
  rerank.py                多语言 cross-encoder 精排
  components.py            组件学习引擎（25 字段组件知识）
  metrics.py               P/R/MRR/nDCG/bootstrap
plugins/art-uiux/          DSH 插件包（MCP 13 工具 + 设置卡）
```

12 个主分类落在引擎的单值字段 `Chunk.topic`，辅助标签进 `metadata` —— 不碰引擎的 Partition 枚举。

## 快速开始

```bash
# 1. 依赖（引擎 + 向量模型 + 精排模型）
python3 -m pip install --break-system-packages -r dsh_autonomous_learning/requirements.txt
python3 -m pip install --break-system-packages "mcp>=1.2,<2" torch sentence-transformers

# 2. 资源探测（写真实状态，不写「已学习」）
python3 scripts/check_access.py

# 3. 抓取并入库
python3 scripts/ingest.py --all --max-units 10

# 4. 案例学习
python3 scripts/analyze_case.py --resource linear

# 5. 设计任务（七步工作流）
python3 scripts/design_task.py --task "做一个金融行情终端首页"

# 6. 组件学习
python3 scripts/learn_components.py --keys shadcn-ui,ant-design,vico

# 7. 检索评测（可量化）
python3 scripts/eval_retrieval.py
```

向量模型在 `dsh_autonomous_learning/config.json` 配置：

```json
"embedding": {
  "provider": "sentence_transformers",
  "dim": 384,
  "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
}
```

换模型后必须重建索引（`store.rebuild_index()`，本机 143 条耗时 126s）。

## 状态字段（三者不可互相替代）

| 字段 | 含义 |
| --- | --- |
| `access_status` | 能不能访问：reachable / restricted / blocked / failed |
| `learn_status` | 学到哪一步：not_started / partial / learned / failed |
| `learned_chunks` | 真正入库的知识条数 |

## 质量等级

L0 原始资料 → L1 已解析并分类 → L2 已提取原则+适用场景 → L3 交叉验证 → L4 设计任务或工程验证。

当前（2026-10-20）：**143 条片段，L1=80、L2=53、L3=2、L4=8**。
L3 来自 w3.org × web.dev 的跨来源核验；L4 来自真实页面的契约测试与渲染复核。

## 检索指标（18 条查询 × 人工 qrels）

| 系统 | P@1 | MRR@10 | nDCG@5 | 延迟 |
| --- | --- | --- | --- | --- |
| 仅向量 | 0.389 | 0.462 | 0.493 | 数十 ms |
| 仅 BM25 | 0.278 | 0.301 | 0.332 | 十 ms 级 |
| RRF 混合 | 0.389 | 0.408 | 0.451 | 数十 ms |
| + 规则重排 | 0.556 | 0.597 | 0.690 | ~200 ms |
| + 交叉编码器 | **0.667** | **0.694** | **0.780** | ~2100 ms |

详见 [docs/EVAL-REPORT.md](docs/EVAL-REPORT.md)，qrels 在 `eval/qrels.json`，可直接改标签重跑。

## 文档

- [docs/FINAL-REPORT.md](docs/FINAL-REPORT.md) 交付总览（12 项 + 组件 9 项逐条对照）
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) 引擎核查结论（每条标明证据位置）
- [docs/EVAL-REPORT.md](docs/EVAL-REPORT.md) 检索评测与 A/B
- [docs/tasks/](docs/tasks/) 8 项设计任务 · [docs/cases/](docs/cases/) 6 个案例 · [docs/components/](docs/components/) 组件分析
- [docs/practice/](docs/practice/) 10 项组件实践（页面可用浏览器直接打开）

## 能力边界（如实）

- 无浏览器级渲染：本机 Chromium 在 proot 下无法启动，改用 WeasyPrint（排版引擎）复核，已抓到 2 个真实问题。
- 无用户研究数据：全项目未产生任何用户测试结论。
- 组件字段覆盖浅：仅 3 个组件读到源码正文，其余参数/状态为 `unknown`。
- 语料 143 条偏小，检索指标对单条差异敏感。

## 测试

```bash
python3 -m pytest tests/ -q     # 36 passed
```

## 许可

仓库当前未附许可证。vendored 引擎来自 dsh-autolearn（该仓库亦未附许可证）。
若要作为开源项目分发，请先确定许可证（例如 MIT / Apache-2.0）。
