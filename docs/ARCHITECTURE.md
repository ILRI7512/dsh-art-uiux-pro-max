# 架构说明（TypeScript 版本）

本文件描述当前实现；Python 时代的历史核查记录见 git 历史与旧报告。

## 一、分层

| 层 | 位置 | 职责 |
| --- | --- | --- |
| 领域 | `src/domain/` | 12 分类、注册表、提取、案例证据、七步工作流、组件知识、指标、双语术语 |
| 基础设施 | `src/infra/` | HTML 分节、受控 HTTP、SQLite 存储、BLAKE2b 特征哈希、tokenizer |
| 应用 | `src/application/` | `ArtServices` 统一业务逻辑 + 13 个工具 Schema |
| 适配 | `src/plugin/`、`src/mcp/`、`src/cli.ts`、`src/client/` | DSH 原生插件、MCP stdio、CLI、设置卡 |

依赖方向：`domain` 不依赖 `infra`（`retrieval.ts` 以 `KnowledgeStore` 类型注入）；
`application` 组合两者；适配层只做参数校验、路由与展示。

## 二、存储

`data/knowledge.sqlite3`（`node:sqlite`，WAL）：

- `projects`：项目元数据（默认 `prj_art_uiux`）。
- `chunks`：知识行，含 `topic`（唯一主分类）、`level`、来源、核验状态、`metadata` JSON。
- `chunk_tokens`：BM25 倒排（拉丁词 + 中文 bigram）。
- `chunk_vectors`：512 维 Float32 向量（BLAKE2b 特征哈希，L2 归一化）。

写入是单事务：行、倒排、向量一起更新；同项目 `content_hash` 去重；更新同一 `chunk_id`
会重建倒排与向量。检索先用 project/topic/level/verification 过滤出允许集，再排序。

## 三、检索

1. 查询先做设计领域双语扩展（中文命中术语时追加英文等价词）。
2. 向量：暴力余弦（百条级语料足够，无 ANN 依赖）。
3. BM25：k1=1.5、b=0.75，df 只在过滤后的集合内统计。
4. RRF 融合（k=60）。
5. 重排：分类亲和度 ×(1+0.35×aff) 与词面重叠 ×(1+0.6×overlap)，保留 `base_score`、
   `category_affinity`、`lexical_overlap`、`final_score` 便于复核。
6. 每条命中带 `source.url`、`level`、`verification_status`、`warnings`；空结果明确说“证据不足”。

`rerank=ce` 没有内置模型，会显式降级并告警，不伪造 CE 分数。

## 四、质量与安全约束

- 等级：L1 仅解析/归类；L2 需要原则 + 显式约束语境；L3/L4 只能来自交叉验证/真实任务。
- 案例证据：`fact` 可到 L2，`inference` 到 L1，`opinion` 不入库；能力边界声明不入库。
- 抓取：robots 前置、256 KB 上限、20 s 超时、最多 6 跳重定向、每跳 URL 安全校验。
- SSRF：默认拒绝 loopback/RFC1918/link-local/ULA；DNS 解析结果也检查；显式配置才放行私网。
- 设置：`allowNetwork=false` 直接失败；数据目录必须绝对路径；设置原子写入。

## 五、扩展点

- 新增主分类：改 `src/domain/taxonomy-data.ts` 并补校验/测试。
- 新增工具：在 `src/application/services.ts` 实现业务，在 `tools.ts` 加 Schema；
  CLI 与 MCP 按需接线，禁止在适配层复制业务逻辑。
- 换向量方案：实现 `Embedder` 接口并保证 `embedderId` 变化时重建索引。
