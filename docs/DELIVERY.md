# 交付报告 · DSH Art UI/UX Pro Max

> 生成时间 2026-10-20。所有数字来自实际运行，不是估算。
> 判定口径：资源登记 ≠ 学习完成；可访问 ≠ 已入库；已入库 ≠ 已验证。

## 1. 现有插件架构分析

见 [ARCHITECTURE.md](ARCHITECTURE.md)。要点：引擎是 Python 包 + SQLite（23 表）+ 特征哈希向量层 + 63 个 MCP 工具；
知识分区是固定枚举，`Chunk.topic` 是单值字段 —— 本项目正是用这个字段承载「唯一主分类」，未改引擎一行。

## 2. 知识分类树

12 个主分类，每个带 12 项元数据（id / 中英文名 / 描述 / 包含范围 / 排除范围 /
二级分类 / 检索关键词 / 典型知识类型 / 关联分类 / 入库条件 / 质量要求），见 `art_uiux/taxonomy.py`。
唯一主分类 + 辅助标签，不做跨分类内容复制。

## 3. 数据模型与存储

| 目标字段 | 实际落点 |
| --- | --- |
| knowledge_id / title / summary / content | `chunks.chunk_id / title / summary / content` |
| category（主分类） | `chunks.topic`（单值，强约束 12 选 1） |
| subcategory / tags / platform / design_style / technology | `chunks.metadata.*` |
| knowledge_type | `chunks.knowledge_type`（引擎 14 种枚举） |
| principle / reasoning / application / implementation | `chunks.metadata.extraction.*`（16 字段模板） |
| anti_patterns / accessibility_notes / performance_notes | `metadata.extraction.anti_pattern / a11y_requirement / performance_note` |
| source_url / source_title / source_license / source_author / source_date | `chunks.source_url / source_title / license_status / author_or_publisher / published_at` |
| retrieved_at | `chunks.accessed_at` |
| evidence_level | `chunks.level`（L0–L4）+ `metadata.extraction.evidence_level` |
| confidence | `chunks.confidence` + `confidence_basis` |
| content_hash | `chunks.content_hash`（去重键） |
| embedding_model | 引擎 `store.stats().embedder` = `hashing:hashed-ngram:512` |

未落地的字段不伪造：`design_style`、`technology` 只有在文本里能确定性抽到时才写。

## 4. 分类与入库流程

`probe（robots 前置）→ fetch → sectionize → classify（关键词加权）→ 16 字段模板 →
质量门槛（4 个最小字段）→ L1/L2 判定 → Chunk → add_chunks（内容哈希去重）`。
实现：`art_uiux/extract.py`、`scripts/ingest.py`。

## 5. 向量检索流程

引擎自带混合检索（向量 + BM25 + RRF 融合），本项目在此之上加：分类过滤、等级过滤、
来源回带、以及四条强制告警（未核验 / 过时 / 冲突 / 许可未知）。
中文提问对英文语料召不回时，用分类关键词做一次确定性扩展并标记 `query_expanded`；
仍为空才返回「知识库暂无足够证据」。

## 6. 重复知识处理

以 `content_hash`（正文空白归一化后的 SHA-256）为主键去重，同 chunk_id 覆盖更新；
跨来源的相似内容不合并，交由引擎的 `find_duplicates` / `conflicts` 记录。

## 7. 知识质量评估

- L0 原始资料 / L1 已解析并分类 / L2 已提取原则+适用场景 / L3 交叉验证 / L4 设计任务或工程验证。
- 当前真实分布：**L0 = 0，L1 = 33，L2 = 28，L3/L4 = 0，verified = 0**。
- 案例结论按 `fact / inference / opinion` 三分：fact 才能进 L2，inference 降为 L1，opinion 不入库。

## 8. 测试

`python3 -m pytest tests/test_art_uiux.py -q` → **18 passed**，覆盖分类规则、注册表状态机、
分节与等级判定、对比度数学（黑白 = 21:1）、审计的 unmeasured 语义、以及一条真实入库+检索的端到端用例。

## 9. 真实运行结果

- 资源注册表：39 条；访问 **reachable 34 / restricted 4 / blocked 1**；已学习 7 条。
- 知识库：**61 条片段 / 61 个向量**，一致性检查 `ok=true`，9 个主分类有内容。
- 案例：Linear、Stripe、Vercel 三个，产出 `docs/cases/*.md`。
- 设计任务：8 项全部有产物，见下表。

| # | 任务 | 产物 | 结论 |
| --- | --- | --- | --- |
| 1 | Android 首页 | `docs/tasks/android_native.kt` | 骨架代码；审计 10 项 unmeasured（未构建未渲染） |
| 2 | 金融仪表盘 | `docs/tasks/fintech_terminal.md` | 9 pass / 1 warn（无 aria） |
| 3 | SaaS 网页 | `docs/tasks/web_page.md` | 9 pass / 1 warn |
| 4 | 三种背景 | `docs/tasks/backgrounds.md` | 对比度 14.59 / 15.29 / 13.54 : 1 全过 AA |
| 5 | Design Token | `docs/tasks/design_system.md` | 6 组对比度实算全过 AA |
| 6 | UI 审计 | 复用行情页原型 | 9 pass / 1 warn |
| 7 | 多尺寸布局 | `docs/tasks/responsive.md` | 6 断点静态推断：无溢出风险 |
| 8 | 对比度与无障碍 | 同上两处 | 对比度为公式实算；aria 缺失判 warn |

## 10. 安装与使用

见 [README.md](../README.md)。DSH 侧已接入 web profile（`@local/art-uiux` bundle +
`art-uiux-mcp` 条目），**需要重启 DSH 才会出现 `mcp__artuiux__*` 13 个工具**。

## 11. 失败恢复与数据迁移

- 引擎自带 `store.backup()` / `store.restore()` / `rebuild_index()` / `check_integrity()`，已实测 integrity ok。
- 注册表状态写 `data/registry.json`，先写 `.tmp` 再 `os.replace`，避免半写。
- profile 变更前已备份：`package.json.bak-artuiux`、`cordis.patch.yml.bak-artuiux`。
- 删除知识走 `delete_chunk` + `rebuild_index`（本轮清理 9 条能力边界声明后重建，向量数从 70 收敛到 61）。

## 12. 仍不确定 / 未完成

1. **L3 未达成**：没有任何知识做过交叉验证；`verified = 0` 是真实状态。
2. **游戏 UI / 视觉素材 / 金融专项知识稀缺**：9/12 分类有内容，`game_ui`、`visual_assets`、`financial_dashboard` 实质为空。
3. **视觉验证缺渲染**：没有浏览器截图或真机渲染，所有视觉结论只能到「静态推断」。
4. **DSH 侧未重启验证**：13 个工具尚未在本会话中真实加载过。
5. **案例冲突匹配仍是数值候选**，噪声大（Stripe/Vercel 各 44 条候选未收敛）。

---

# 追加模块 · UI Component Learning Engine

## 组件资源清单（13 个仓库，已登记）

Android：compose-samples、nowinandroid、androidx、koalaplot-core、vico、landscapist、compose-rich-editor、Reorderable
Web：shadcn-ui/ui、ant-design、headlessui、storybook、tremor

登记不等于学习完成。真实学习状态见下。

## 组件分类树（8 类）

basic / layout / navigation / input / feedback / overlay / data / advanced。
分类由组件名按「完整单词」判定，顺序从具体到兜底（修过一次 bug：`table` 曾被 `tab` 误判成导航组件）。

## 已完成仓库级分析（6 个，逐项来自 GitHub API 真实元数据）

| 仓库 | 许可证 | 语言 | 组件候选 | 覆盖类别 | 测试文件 | 等级 |
| --- | --- | --- | --- | --- | --- | --- |
| shadcn-ui/ui | MIT | TypeScript | 60 | 8 | 801 | L2 |
| ant-design | MIT | TypeScript | 28 | 5 | 1153 | L2 |
| headlessui | MIT | TypeScript | 60 | 6 | 85 | L2 |
| tremor | Apache-2.0 | TypeScript | 41 | 8 | 40 | L2 |
| vico | Apache-2.0 | Kotlin | 5 | 2 | 34 | L2 |
| landscapist | Apache-2.0 | Kotlin | 16 | 3 | 116 | L2 |

等级口径：只看了元数据+README → L1；看到组件目录且有测试或示例 → L2；读过组件源码正文仍只算 L2（未运行、未渲染）。

## 已完成源码级分析（3 个组件）

| 组件 | 文件 | 读到的事实 | 等级 |
| --- | --- | --- | --- |
| headlessui Button | `packages/@headlessui-react/src/components/button/button.tsx` | 状态含 disabled；无 aria/role 声明 | L2 |
| tremor Button | `src/components/Button/Button.tsx` | 状态 disabled+loading；aria-hidden；变体 dark/hover/primary | L2 |
| antd Button | `components/button/Button.tsx` | 状态 disabled+loading；aria-disabled；变体 type/size/variant；仓库有 a11y.test.ts | L2 |

## 组件知识数据结构（25 字段）

见 `art_uiux/components.py::ComponentKnowledge`。无法确认的字段一律写 `unknown`：
本轮 6 个仓库的参数、状态机、主题定制、无障碍实现、性能特征**全部 unknown**，
因为只做了仓库级分析，没读组件源码正文 —— 只有上面 3 个组件补上了部分字段。

## 组件比较功能

`comparisons()` 只输出可观测项（许可证、语言、组件数、覆盖类别、测试文件数、归档状态、最近推送），
代码里没有、也不允许出现「best/score/winner」这类字段，测试里对此有断言。

## 仍未完成

1. 10 项组件实践任务（登录页、首页、仪表盘、设置页、弹窗交互、主题、双风格、多尺寸、无障碍检查、组件测试）**尚未执行**。
2. 组件级字段覆盖不全：只读了 3 个组件，参数/状态/主题多为 unknown。
3. 组件知识未做交叉验证，全部 unverified。
4. 版本管理只记了 `HEAD` 与最近推送年份，没有 commit sha 级别的版本锁定。

---

# 追加 · 第五轮补记（2026-10-20 02:00）

## 空分类回填

新增 10 条资源（注册表 46 → **49** 条）：interface-in-game、gameui-database、finviz、tradingview、
material-icons、heroicons、simple-icons、wcag-contrast、wcag-target-size、webdev-contrast。

- `gameui-database` 被 Cloudflare 拦截 → 记 **restricted**，未绕过。
- `tradingview / material-icons / heroicons / simple-icons` 是 SPA，静态抓取抽不到正文 → 记 `no_sections`，改用组件/案例路径补。
- 现在 **12/12 分类都有内容**（此前 9/12）。

## 首次达到 L3（这是真交叉验证，不是自封）

| 片段 | 分类 | 主来源 | 佐证来源 | 方法 | 置信度 |
| --- | --- | --- | --- | --- | --- |
| `chunk_37cc80…` | color_system | w3.org（WCAG 2.2 SC 1.4.3） | web.dev | cross_source | 0.925 |
| `chunk_5cdf91…` | color_system | w3.org（SC 1.4.3 理由） | web.dev | cross_source | 0.925 |

关键修正：最初按「同话题内配对」找不到证据，因为同一条规则被关键词分类器分别放进
`color_system` 和 `ui_quality`。改成**按规则签名全局配对**（对比度 4.5:1 无论归在哪个分类都是同一条规则），
并在证据里记录两侧分类，才得到 2 条真 L3。

## 组件版本锁

`docs/components/versions.json` 记录 6 个仓库的 commit sha 与提交日期（不再只写 HEAD）：
shadcn-ui `ba1503c64472`、ant-design `c275ff818dcc`、headlessui `eea57cf46fd6`、
tremor `ca4d588f4782`、vico `eeebede537fd`、landscapist `4ff7cb22a711`。

## 当前真实状态

- 知识库：**96 条 / 96 向量**，integrity ok。
- 等级：L1 = 54，L2 = 40，**L3 = 2**，L4 = 0。
- 12 分类分布：design_system 28、ui_quality 21、web_ui 12、background_design 11、color_system 10、
  android_ui 4、motion_interaction 2、financial_dashboard 2、uiux_principles 2、visual_assets 2、game_ui 1、visual_aesthetics 1。
- 注册表 49 条：reachable 33、restricted 13、blocked 1、failed 2；已学习 25。
- 测试 22 passed。

## 仍未完成

1. **10 项组件实践任务全部未做**（登录页、首页、仪表盘、设置页、弹窗交互、主题、双风格、多尺寸、无障碍、组件测试）。
2. L4 仍为 0：没有任何知识经过真实设计任务或工程实现验证。
3. 组件字段覆盖仍浅：只读了 3 个组件源码，多数参数/状态字段是 unknown。
4. DSH 侧 13 个 MCP 工具尚未重启验证。

---

# 追加 · 组件实践任务（10 项）与首次 L4

## 产物

`docs/practice/`：login / home / dashboard / settings / dialog / dual_style 六个可直接打开的页面 +
`tokens.css` + `REPORT.md` / `REPORT.json`。

## 10 项任务与结果

| # | 任务 | 结果 |
| --- | --- | --- |
| 1 | 基础组件构建登录页 | 6/6 契约通过 |
| 2 | 导航组件构建首页 | 6/6 |
| 3 | 卡片与表格构建金融仪表盘 | 7/7 |
| 4 | 表单组件构建设置页 | 6/6 |
| 5 | 弹窗与提示实现完整交互 | 6/6 |
| 6 | 统一主题与 Design Tokens | 6 组对比度全过 AA |
| 7 | 同一组件两种视觉风格 | 6/6（实体强调 / 描边克制） |
| 8 | 多尺寸布局检查 | 6 断点静态推断，无溢出 |
| 9 | 可访问性检查 | 各页审计 fail = 0 |
| 10 | 编写组件测试 | `tests/test_practice_pages.py`，30 项断言全过 |

契约测试测的是标记契约：label 关联、button type、`:focus-visible`、`min-height ≥ 44px`、
表格 `caption` + `scope`、`aria-live`、`prefers-reduced-motion`。

## 首次 L4

6 条「组件实践验证」记录写入 `experiment_knowledge` 分区，`level=L4`、`verification_method=code_test`、
`verification_status=verified`，证据指向真实页面与通过的检查项。

**L4 的口径说明**：这里的「验证」是**工程实现验证**（在真实生成的页面上跑契约与静态审计），
不是用户研究结论。任何 `unmeasured` 项都不计入 L4 证据。

## 当前真实状态

- 知识库：**102 条 / 102 向量**。
- 等级：L1 = 54，L2 = 40，L3 = 2，**L4 = 6**。
- 测试：**30 passed**（22 + 8 条实践契约断言）。
- 六轮修正记录：`table` 被 `tab` 误判、营销文案入库、能力边界声明污染检索、
  分类不一致导致 L3 永远为 0 —— 四处都已修并留痕。

## 仍未完成

1. **视觉验证仍缺真实渲染**：没有浏览器截图，视觉回归、运行时交互、动画表现都未验证。
2. 组件字段仍浅：源码级只读 3 个组件，多数参数/状态是 unknown。
3. DSH 侧 13 个 MCP 工具尚未重启验证（配置已合成正确，未证明运行时连通）。

---

# 追加 · 真实渲染验证（WeasyPrint，非浏览器）

## 尝试过程（如实记录）

1. 装 Playwright + chrome-headless-shell arm64（120 MB）→ 缺系统库。
2. 修 apt 源（容器 arm64 却配了 amd64 源）→ 装齐 glib/nss/atk/pango/cairo/gbm 等。
3. Chromium 仍无法启动：GPU 进程 `exit_code=5` 崩溃，4 组启动参数组合全部失败。
4. 退回 **WeasyPrint 70**（真实 CSS 排版引擎，无 JS）+ `pdftoppm` 转 PNG。

## 从像素里抓到的两个真问题

| 问题 | 证据 | 修复 |
| --- | --- | --- |
| 输入框边界对比度 **1.10:1**（WCAG 1.4.11 要求 ≥3:1） | 公式实算 + 截图里输入框几乎"消失" | 新增 `--color-border` token（#6b7484 → 3.47:1），并把 1.4.11 检查并入对比度表 |
| 375px 下 4 列表格表头折行成竖排 | 截图 `dashboard-375-1.png` | `th{white-space:nowrap}` |

这两条 10 项静态审计全部漏掉，只有渲染才暴露 → 说明「静态审计通过」不等于「视觉没问题」。

## 一条不敢当成真问题的观察

按钮溢出卡片右侧，加 `width:auto` 后消失 —— 但可能是 WeasyPrint 的按钮布局差异，
没有浏览器可验证，因此**不入库**，只记在 [RENDER.md](practice/RENDER.md)。

## 当前等级

L1 = 54，L2 = 40，L3 = 2，**L4 = 8**（6 条组件实践 + 2 条渲染验证）。
知识库 **104 条 / 104 向量**。
