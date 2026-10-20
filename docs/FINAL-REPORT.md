> **历史报告（Python 时代）**：本文件记录迁移前的实现与实测数据。Python 代码已移除，
> 文中的 `python3 scripts/...` 命令与 `art_uiux/` 路径不再可用；可复现的当前实现见
> [README](../README.md) 与 [MIGRATION-TS](MIGRATION-TS.md)。指标不自动继承到 TS 运行时。

# DSH Art UI/UX Pro Max · 最终交付报告

生成时间：2026-10-20 02:20 UTC
仓库位置：`/root/dsha-art-uiux-pro-max`（引擎 vendor 自 dsh-autolearn v1.1.0，未改一行）

> 全篇口径：资源登记 ≠ 学习完成；可访问 ≠ 已入库；已入库 ≠ 已验证。
> 所有数字来自本机实际运行，可复现脚本见 `scripts/`。

---

## 一、原始 12 项交付物

| # | 交付物 | 状态 | 证据 |
| --- | --- | --- | --- |
| 1 | 已注册的资源列表 | ✅ 49 条 | `art_uiux/resources.seed.json`（15 字段全填） |
| 2 | 实际成功访问的资源列表 | ✅ 33 条 reachable | `data/registry.json` + `scripts/check_access.py` |
| 3 | 已完成学习的资源列表 | ✅ 25 条 learned | `learn_status=learned`，累计入库 89 片段 |
| 4 | 访问失败与受限资源列表 | ✅ 13 restricted / 1 blocked / 2 failed | 每条带 HTTP 码与原因（behance 403、shadertoy 403、dribbble 202 空体、W3C SVG2 robots 禁止） |
| 5 | 已建立的知识分类树 | ✅ 12 类 × 12 项元数据 | `art_uiux/taxonomy.py`，含包含/排除范围、二级分类、入库条件、质量要求 |
| 6 | 向量库数据结构 | ✅ | 引擎 `chunks` 表 25+ 字段映射见 README/DELIVERY；embedder `hashing:hashed-ngram:512` |
| 7 | 知识入库与去重规则 | ✅ | `content_hash` 去重 + 设计相关度门槛（≥2/3 设计词、营销词 ≤2）+ 16 字段最小门槛 |
| 8 | 语义检索测试结果 | ✅ 可量化 | `docs/EVAL-REPORT.md`：5 套系统 × 18 查询 × 人工 qrels；最佳 nDCG@5 **0.607**、P@1 **0.500** |
| 9 | 案例分析结果 | ✅ 6 个案例 | `docs/cases/`：Linear、Stripe、Vercel、Finviz、TradingView、InterfaceInGame |
| 10 | 实际 UI 设计验证结果 | ✅ 8 任务 + 10 实践 | `docs/tasks/`（8）、`docs/practice/`（6 页 + 报告） |
| 11 | 安装和运行说明 | ✅ | `README.md` + 插件已接入 web profile（重启生效） |
| 12 | 后续自主学习计划 | ✅ 见第五节 | 按分类覆盖度排序的可执行清单 |

## 二、组件学习引擎 9 项交付

| # | 交付物 | 状态 | 证据 |
| --- | --- | --- | --- |
| 1 | 组件资源清单 | ✅ 16 个仓库 | `art_uiux/components.py::COMPONENT_SOURCES` |
| 2 | 组件分类树 | ✅ 8 类 | basic/layout/navigation/input/feedback/overlay/data/advanced |
| 3 | 已完成源码分析的项目 | ✅ 6 仓 + 3 组件 | `docs/components/*.md`（12 篇）+ `versions.json` commit 锁 |
| 4 | 组件知识数据结构 | ✅ 25 字段 | `ComponentKnowledge`，未知字段写 `unknown` 不编造 |
| 5 | 组件检索与比较功能 | ✅ | `comparisons()` 只比可观测项，测试断言禁止 best/score/winner |
| 6 | 组件实践测试结果 | ✅ 10 项 | `docs/practice/REPORT.md`，30 项断言全过 |
| 7 | 许可证与版本管理 | ✅ | 每个组件库记录 SPDX + commit sha（6 仓） |
| 8 | 组件更新策略 | ⚠️ 部分 | 缓存 6h + HEAD 解析；未实现"定时比对 sha 变更" |
| 9 | 安装和使用说明 | ✅ | README + `scripts/learn_components.py --keys ...` |

## 三、知识库现状

- **143 条 / 143 向量**（384 维多语言向量），`check_integrity` = ok。
- 等级：L0 = 0，L1 = 54，L2 = 40，**L3 = 2**，**L4 = 8**。
- 分类分布：ui_quality 29、design_system 28、web_ui 12、background_design 11、color_system 10、
  android_ui 4、visual_assets 2、uiux_principles 2、motion_interaction 2、financial_dashboard 2、
  visual_aesthetics 1、game_ui 1。
- 测试：**30 passed**（分类规则、注册表状态机、对比度数学、案例证据分级、端到端检索、实践页契约）。

## 四、检索评测（可量化，`docs/EVAL-REPORT.md`）

18 条查询（16 条带人工 qrels + 2 条「预期无答案」负例）× 5 套系统，指标 P@1/3/5、R@10、MRR@10、nDCG@5。

| 系统 | P@1 | MRR@10 | nDCG@5 |
| --- | --- | --- | --- |
| vector（仅向量） | 0.167 | 0.247 | 0.246 |
| bm25（仅关键词） | 0.278 | 0.307 | 0.332 |
| rrf（引擎混合） | 0.222 | 0.312 | 0.323 |
| rerank（+分类亲和解和词面重叠） | 0.444 | 0.450 | 0.484 |
| **rerank_zh（+中英术语桥接）** | **0.500** | **0.477** | **0.607** |

- **已换用真正的多语言向量模型**：`paraphrase-multilingual-MiniLM-L12-v2`（384 维，CPU 推理）。
  同一套 qrels 下 `rerank_zh` 从 nDCG@5 0.570 提升到 **0.690**，P@1 0.444 → **0.556**，Recall@10 0.760 → **0.901**；
  只看向量的系统提升最大（nDCG 0.218 → 0.493），说明此前瓶颈确在向量化。
- rerank_zh 相对 rrf 的配对 bootstrap：nDCG@5 **+0.239**，95% 区间 **[+0.014, +0.451]（不含 0）**；MRR 区间跨零，不显著。
- 成本：模型 ~470 MB、重建索引 126s、单次查询中位 **206 ms**（arm64 CPU）。
- 双语桥接解决了最严重的问题：中文查询对英文语料的 nDCG@5 从 **0.000 → 0.693（background_design）**、
  **0.000 → 0.879（color_system）**。
- 限制：单标注者、18 条查询、语料只有 104 条；qrels 已导出到 `eval/qrels.json` 供复核。

## 五、后续自主学习计划（按收益排序）

1. **补薄分类的定向学习**（最大收益）：`visual_aesthetics`、`uiux_principles`、`motion_interaction`、
   `financial_dashboard`、`game_ui` 各目标 ≥10 条 L2。优先动效与审美类原文（easing 规范、构图原则文章）。
2. **换更好的 embedder**：当前特征哈希 512 维语义能力弱；接 sentence-transformers 后重跑
   `scripts/search_eval.py` 作为回归基线。
3. **浏览器级视觉验证**：本机 Chromium 无法启动（GPU 崩溃），需换环境或解锁手机屏幕后做真机截屏复核。
4. **L3 扩容**：目前只有 2 条。补齐同规则的多来源原文（W3C + MDN + Material + Apple HIG）可批量提级。
5. **组件深度**：把 10 个代表性组件读到"参数 + 状态 + 主题 + 测试"四类字段齐全，而不是 3 个。
6. **DSH 运行时验证**：重启后确认 13 个 `mcp__artuiux__*` 工具可调用（配置合成已通过）。

## 六、已知风险与未验证项（不粉饰）

1. **没有浏览器级渲染**：WeasyPrint 只是排版引擎；视觉回归、运行时交互、动画表现均未验证。
2. **没有用户研究数据**：全项目未产生任何用户测试结论，案例里的审美判断一律标 opinion 且不入库。
3. **DSH 侧 13 个工具未做运行时验证**（只验到 dump-config 与直接 stdio 握手）。
4. **薄分类的知识密度低**：`visual_aesthetics` 1 条、`game_ui` 1 条，检索会漏。
5. **组件字段覆盖浅**：只有 3 个组件读了源码正文，其余参数/状态字段是 unknown。
