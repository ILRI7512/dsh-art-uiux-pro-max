# 学习记录：dsh-ui-ux-pro-max → @local/art-uiux

## 1. 学习对象

| 项 | 值 |
| --- | --- |
| 仓库 | [ChenYiming-aaa/dsh-ui-ux-pro-max](https://github.com/ChenYiming-aaa/dsh-ui-ux-pro-max) v1.4.1 |
| 数据上游 | `nextlevelbuilder/ui-ux-pro-max-skill@56ea9cf174ed86786187daa9de0e6247cb0747e4` |
| 许可 | MIT（代码与数据）；字体二进制未引入 |
| 本地快照 | `/root/learn-uiux-target`（仅 README/docs/data/lib，未复制 22 MB 字体） |

## 2. 自主学习插件执行记录

使用 `@local/dsh-autolearn` 的 TypeScript 引擎（不走 Python/MCP）：

| 项 | 值 |
| --- | --- |
| 项目 ID | `prj_8d55422fe592cb11334e97546ee07e60` |
| 项目名 | 设计知识库学习 v2：dsh-ui-ux-pro-max → art-uiux |
| 数据目录 | `/root/dsh-autolearn/data` |
| 运行轮次 | 2 轮（`run_7216ff23…`、`run_b14beef9…`） |
| 入库片段 | 74 条 |
| 主题分布 | 设计原则与规范 35 / 视觉与排版 16 / 设计流程与交付 18 / 组件与交互模式 5 |
| 核验 | 1 条 verified（1.4%）；73 条 pending_verification |
| 成本 | LLM 调用 0 次；规则提取，非模型生成 |

**口径**：74 条中只有 1 条通过核验。本文件只把「实际读到的代码/数据/文档」作为事实，
其余作为待核验笔记；不把学习产物的数量当作质量。

## 3. 学到的关键事实

1. **数据模型**：`data/index.json` 用 `domains` 装 11 个域（style/color/chart/landing/product/ux/typography/icons/gsap/react/web）+ 独立 `reasoning`；每域是扁平字符串表格，首行字段名如 `Style Category`、`Product Type`、`Severity`。
2. **规模**：88 style / 192 color / 74 typography / 119 ux / 44 react / 32 web / 192 product / 25 chart / 34 landing / 192 reasoning；共 4,319 行（含 stacks/googleFonts）。
3. **检索**：纯 JS BM25（k1=1.5, b=0.75），CJK 二元分词 + 413 条中文领域别名 + 4 条单字兜底；`deprecated` 默认排除，显式 `legacy`/`deprecated` 时保留。
4. **推荐**：product → reasoning（按 `UI_Category`）→ style/color/landing/typography 五域检索 → 按 `Style_Priority` 选最佳匹配；UX 规范三级召回，不足时按通用类别补齐。
5. **审查**：UX/React/Web 规则按平台降权而非过滤，按 `Severity` 排序；只输出规则与正误代码，不冒充真实渲染测试。
6. **数据血缘**：`data/index.json` 自带 upstream/ref/date；静态发布，不在运行时同步。

## 4. 对 @local/art-uiux 的更新

| 更新 | 证据 |
| --- | --- |
| 新增 `resources/design-library.json`（9 域 + 192 推理规则，716 KB） | `src/domain/design-library.ts` 加载并校验 |
| 新增 `art_recommend`：产品 → 风格/16 色令牌/字体/落地页/UX/反模式/旋钮 | `src/domain/design-library.ts::recommend` |
| 新增 `art_review`：195 条规范的严重度排序 + 正误代码 + 10 项检查清单 | `src/domain/design-library.ts::review` |
| 新增 `art_library_search`：9 域 BM25 + 中文别名 + 废弃条目开关 | `src/domain/design-library.ts::searchDomain` |
| CLI 增加 `recommend` / `review` / `library` | `src/cli.ts` |
| 工具数 13 → 16；设置卡显示设计库计数 | `src/application/tools.ts`、`src/client/index.ts` |
| 来源与许可 | `THIRD_PARTY_NOTICES.md` |

调色板令牌**不替代** WCAG 实算：`art_design_system` 仍按公式计算对比度；
`art_recommend` 输出中的 `provenance` 明确标注「上游静态数据，未逐条重测」。

## 5. 不复制的东西

- 不复制上游 `lib/**` 代码；检索/推荐/审查为本项目 TypeScript 实现。
- 不引入图标/GSAP/技术栈/Google Fonts 表，也不引入任何字体二进制。
- 不把 74 条未核验的学习笔记直接当插件知识；插件只使用静态数据快照与可复算的令牌。
- 不删除原 `art_design_system` 的 4 套基线；新库是增量能力。

## 6. 复现

```bash
# 1) 学习（可选；需要本机 @local/dsh-autolearn 数据目录）
#    项目 ID 见上；入口是 AutolearnEngine.services.sourceManage({action:'read'}) + learningRun
# 2) 插件侧验证
npm test
node dist/cli.js recommend "财务 数据看板 深色 高密度"
node dist/cli.js review "移动端登录页，提交后没有任何反馈" --platform mobile
node dist/cli.js library "毛玻璃 深色" --domain style
```
