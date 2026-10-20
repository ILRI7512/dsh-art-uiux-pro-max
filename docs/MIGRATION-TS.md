# Python → TypeScript 迁移记录

日期：2026-10-20
基线：`d89884e`（Python 引擎 + art_uiux + JS 插件）

## 为什么要迁移

旧实现有三套运行时：Python 引擎（约 1.6 万行）、Python 扩展层（约 2.7 千行）、
Node 插件（只做设置卡与 MCP 注册）。每次改一个字段要跨语言同步；部署还依赖
`mcp`、`httpx`、`beautifulsoup4`，可选精排再依赖 `torch + sentence-transformers`（约 470 MB）。

TS 版本把运行时收敛为 Node 单进程：
- 原生工具直接调用服务层，不再启动 MCP 子进程；
- SQLite 用 `node:sqlite`，无 ORM；
- HTML 用 `parse5`，无浏览器；
- 特征哈希、BM25、RRF、WCAG 对比度全部本地确定性计算。

## 对应关系

| Python | TypeScript |
| --- | --- |
| `art_uiux/taxonomy.py` | `src/domain/taxonomy.ts` + `taxonomy-data.ts` |
| `art_uiux/registry.py` | `src/domain/registry.ts` |
| `art_uiux/checker.py` | `src/infra/http.ts` |
| `art_uiux/extract.py` | `src/infra/html.ts` + `src/domain/extract.ts` |
| `art_uiux/case_analyzer.py` | `src/domain/case-analyzer.ts` |
| `art_uiux/design_workflow.py` | `src/domain/design-workflow.ts` |
| `art_uiux/retrieval.py` | `src/domain/retrieval.ts` + `src/infra/store.ts` |
| `art_uiux/components.py` | `src/domain/components.ts` |
| `art_uiux/metrics.py` / `rerank.py` | `src/domain/metrics.ts` / `rerank.ts` |
| `art_uiux/tasks_special.py` | `src/domain/tasks-special.ts` |
| 设计智能库（新增） | `src/domain/design-library.ts` + `resources/design-library.json` |
| `art_uiux/mcp_server.py` | `src/mcp/server.ts` + `src/application/tools.ts` |
| `dsh_autonomous_learning/*` | 精简为 `src/infra/store.ts`（只保留本项目需要的行/倒排/向量/检索） |
| `scripts/*.py` | `src/cli.ts` |
| `tests/*.py` | `tests/**/*.test.ts` |
| `plugins/art-uiux/index.js` + `client.js` | `src/plugin/index.ts` + `src/client/index.ts` |

## 行为变化（有意的）

1. **`art_learn` 真的入库**：旧 MCP 工具只做预览并返回“请走 scripts/ingest.py”，
   现在与 CLI 共用 `learn()`，返回真实入库/去重/跳过数。
2. **检索过滤修复**：旧 `retrieve()` 构造了 `min_level` 过滤却未用于实际检索；
   现在 `minLevel` 与分类过滤都进入 SQL 允许集。
3. **robots 与抓取共用缓存**：旧 `fetch_html` 不检查 robots，只有 probe 检查；
   现在两者共用同一个 robots 缓存，并在每一跳重定向后重新做 URL 安全校验。
4. **SSRF 默认拒绝**：默认阻止 loopback/私网/link-local，需显式开启。
5. **设置真正生效**：旧 art 插件的设置卡实际是从 autolearn 复制的，路由与包名都不匹配；
   现在 `/art-uiux/api/settings` 与 `/art-uiux/api/stats` 由 TS Host 注册。
6. **CE 重排诚实降级**：不捆绑模型；请求 `ce` 时明确告警并回退规则重排。
7. **删除无关插件**：`plugins/approval`、`plugins/autolearn` 是从 dsh-autolearn 复制进来的，
   与本项目无关，已移除。

## 未迁移/删除的东西

- `scripts/install_plugin.py`：安装改为 `dsh plugin add link:`（见 README）。
- `scripts/render_check.py`、`practice_components.py`、`cross_validate.py`：
  属于一次性交付物生成器，不是运行时能力；产物保留在 `docs/practice/` 与 `docs/tasks/`。
- Python 引擎的完整学习状态机、任务调度、模型适配器：本项目只用到“知识行 + 检索”，
  没有移植未被调用的子系统；这也意味着 `dsh-autolearn` 的跨轮学习能力不在此仓库内。

## 数据迁移

- 种子：`art_uiux/resources.seed.json` → `resources/seed.json`（内容未改）。
- 运行期状态：新代码仍会读取 `dsh_autonomous_learning/data/registry.json` 作为兜底，
  首次写入后落到 `<dataDir>/registry.json`。
- 知识库：旧 `metadata.sqlite3` 的 chunks 表结构较宽，未做自动导入；
  需要的话按 `ChunkInput` 字段映射后调用 `store.addChunks()`（会重建倒排与向量）。

## 回滚

基线提交 `d89884e` 保留完整 Python 实现；`git show d89884e:README.md` 可查看旧安装方式。
