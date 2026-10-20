# DSH 自主学习插件（Python 引擎 + MCP 接入）

> 目标：让 DSH Agent 具备**可验证、可追溯、可审计、有边界**的自主学习能力，
> 并用同一套引擎为不同专业领域建立与维护知识库。

本目录不是架构演示或伪代码：核心流程（规划 → 资料发现 → 解析 → 提取 → 入库 → 检索 →
核验 → 实践 → 评估 → 报告 → 断点续跑/调度）均已实现，并有 **96 项 pytest 用例**覆盖，
MCP 协议握手已用真实客户端验证（63 个工具可被列出并调用）；assisted 模式的高风险操作
已接入 **DSH 原生审批弹窗**（见第 5 节"审批接入"）。

---

## 0. P0 环境检查结论（真实环境，2026-10-19）

| 项目 | 检查结果 | 影响与取舍 |
| --- | --- | --- |
| DSH 版本/插件机制 | DSH Desktop 使用 Cordis 插件体系，profile 位于 `%USERPROFILE%\.dsh\profiles\desktop`；已安装 `dsh-mcp-connector@0.2.75` | **不写 Cordis/npm 插件**，改用 MCP stdio 接入；不碰 DSH 内核文件 |
| 工具调用协议 | MCP（`mcp` Python SDK 1.27.2 已安装）；连接器支持 stdio/streamable-http | 直接用官方 MCP SDK 暴露 60+ 工具，DSH 侧以 `mcp__<server>__<tool>` 调用 |
| 模型接口 | profile 配置了 OpenAI 兼容 provider（`commandcode`，`/provider/v1`），密钥在凭据引用中；**子进程环境不可见** | 模型适配层可配置，默认 `mock`；无密钥时规则路径照常工作，不伪造模型调用 |
| Python | 3.13.5（本机 `python`）；pip 26.1.1；可访问 PyPI | 以 3.13 为目标 |
| 向量库 | 未安装 Chroma / Qdrant / sentence-transformers | **自研轻量向量层**：SQLite 元数据 + `.npy` 矩阵 + 余弦检索；零重依赖、离线可跑、可精确测试 |
| 文档解析 | `pypdf 6.21.1`、`python-docx`、`beautifulsoup4 4.14.3` 可用 | 支持 PDF/DOCX/HTML/Markdown/代码文件 |
| 测试 | `pytest 9.1.1` | 每阶段执行真实测试 |
| 网络 | 可访问 PyPI；`HTTP(S)_PROXY=127.0.0.1:7890` | 联网默认关闭（`security.allow_network=false`），需要时显式开启并做域名/体积限制 |

**结论**：MCP 是当前 DSH 最稳妥的接入方式；向量层自研优于强行引入 Chroma（体积大、默认模型需联网下载、
且会把业务绑定到具体集合名）。统一 `KnowledgeStore` 接口保证将来可平滑替换为 Chroma/Qdrant。

---

## 1. 目录结构

```
dsh_autonomous_learning/
├── config.py                 # 配置系统（默认值 + 校验 + 环境变量）
├── plugin.py                 # MCP stdio 服务器（DSH 接入入口）
├── main.py                   # 本地 CLI
├── config.json               # 默认配置
├── requirements.txt
├── adapters 概念落在 core/    # 模型/向量化适配器
├── core/
│   ├── models.py             # 枚举与实体
│   ├── state_machine.py      # 知识状态机 + L0-L5 推导 + 证据门槛
│   ├── planner.py            # 目标拆解、任务 DAG、优先级
│   ├── gap_analyzer.py       # 覆盖率与知识缺口
│   ├── evaluator.py          # 学习评估
│   ├── orchestrator.py       # 学习闭环编排 + 运行时组装
│   ├── budget.py             # 预算与停止条件
│   ├── scheduler.py          # 有界定时任务
│   ├── model_adapter.py      # 模型接口（mock / OpenAI 兼容 / 禁用）
│   ├── embedder.py           # 向量化（hashing / OpenAI / sentence-transformers）
│   ├── reporter.py           # 学习报告（Markdown + JSON）
├── sources/                  # 发现、读取、解析、来源元数据
├── knowledge/                # 分类、分区、提取、核验、去重、冲突、版本、关系图
├── storage/                  # SQLite 元数据、BM25 词元索引、向量知识库、备份
├── practice/                 # 练习任务、受限代码执行、实验
├── security/                 # 分级权限、执行策略、审计脱敏
├── tools/                    # 工具注册表 + 四组业务工具
├── examples/                 # 可复现示例（语料 + 端到端脚本）
├── data/                     # 运行时数据（DB/索引/文档/报告/实验产物）
└── tests/                    # 96 项 pytest 用例

<repo>\
├── dsh-autolearn\             # DSH 插件包 1：把引擎注册为 MCP 服务器（配置型 bundle）
└── dsh-autolearn-approval\    # DSH 插件包 2：高风险调用接入 DSH 审批弹窗
```

---

## 2. 安装

```powershell
cd <repo>                     # 注意：要在此父目录执行，包名才是 dsh_autonomous_learning
python -m pip install -r dsh_autonomous_learning\requirements.txt
python -m dsh_autonomous_learning.main --home dsh_autonomous_learning init
```

## 3. 本地使用（CLI）

```powershell
cd <repo>
$env:PYTHONPATH = "<repo>"

# 1) 创建学习项目（自动生成计划）
python -m dsh_autonomous_learning.main project-create `
  --goal "学习外汇量化交易，区分理论结论、实证结果与待验证假设" `
  --domain quant --depth working --plan

# 2) 导入并提取一份资料（--path 或 --url）
python -m dsh_autonomous_learning.main ingest --project prj_xxx --path dsh_autonomous_learning\examples\corpus\quant_demo_a.md --topic 量化

# 3) 执行一轮有界学习
python -m dsh_autonomous_learning.main run --project prj_xxx --max-tasks 12

# 4) 检索
python -m dsh_autonomous_learning.main search --query "滑点对回测的影响" --project prj_xxx

# 5) 核验（公式重算）
python -m dsh_autonomous_learning.main verify --chunk chunk_xxx `
  --expression "(ret - rf) / vol" --variables '{"ret":0.12,"rf":0.02,"vol":0.1}' --expected 1.0

# 6) 报告与体检
python -m dsh_autonomous_learning.main report --project prj_xxx
python -m dsh_autonomous_learning.main audit --project prj_xxx

# 7) 工具直达
python -m dsh_autonomous_learning.main tools list
python -m dsh_autonomous_learning.main tools call search_knowledge '{"query":"滑点"}'
```

## 4. 作为 DSH 插件安装

引擎本体是 Python，**打包成两个 DSH 插件包**（Cordis bundle，装进 profile，Plugin Manager 可见）：

| 插件包 | 位置 | 作用 |
| --- | --- | --- |
| `@local/dsh-autolearn` | `<repo>/plugins/autolearn` | 配置型 bundle：自动注册 MCP stdio 服务器（`serverName: autolearn`） |
| `@local/dsh-autolearn-approval` | `<repo>/plugins/approval` | Host 插件：高风险工具调用接入 DSH 原生审批弹窗 |

安装（二者都已安装并 applied）：

```powershell
# 在 DSH 里由 plugin_manager 完成；等价命令：
#   install_bundle target=<repo>/plugins/autolearn
#   install_bundle target=<repo>/plugins/approval
```

安装后的效果：

- Plugin Manager 中出现「自主学习 / Autonomous Learning」与「自主学习审批闸门」；
- 63 个工具以 `mcp__autolearn__create_learning_project`、`mcp__autolearn__run_learning_round`、
  `mcp__autolearn__search_knowledge` 等名字出现在 Agent 工具列表中（已用 Host
  `Tool.listTools` 核对：63 个）；
- 不需要手工在「MCP 连接器」里填命令、参数与环境变量。

> 说明：MCP 服务器是**长驻进程**，由 DSH 的 mcp-client 行启动/回收；插件自身不常驻后台、
> 不自行触发无限循环。定时任务需要外部（DSH/系统计划任务）周期性调用 `run_scheduler_tick`。

<details>
<summary>手动注册方式（不使用插件包时的备选）</summary>

设置 → 插件 → MCP 连接器 → 新增 stdio 连接：

- serverName：`autolearn`，命令 `python`，参数 `-m dsh_autonomous_learning.plugin`
- 工作目录 `<repo>`
- 环境变量 `DSH_AL_HOME=<repo>/dsh_autonomous_learning`、`PYTHONPATH=<repo>`

</details>

## 4.1 assisted 审批接入 DSH 审批 UI（已实现）

组成两半，职责互不重叠：

| 半边 | 位置 | 职责 |
| --- | --- | --- |
| 判定清单 | `tool_risks.json`（`export-tool-risks` 生成） | 每个工具的风险等级与是否需要确认，只维护一份 |
| 宿主闸门 | `<repo>/plugins/approval`（Cordis 插件，已安装启用） | 在 `tools/pre-execute` 里对高风险调用返回 `{kind:'ask'}`，弹出 **DSH 原生审批框** |
| 引擎 | `security/permissions.py` | `DSH_AL_HOST_APPROVAL=1` 时不再要求 confirm_token，把把关交给宿主 |

判定规则（默认）：`risk=execute` 或 `destructive` 的调用、以及显式列出的
`update_knowledge / invalidate_knowledge / restore_knowledge_base / run_code_test /
run_learning_experiment` → 弹审批；读取、检索、保存到待审分区 → 直接执行。

安全要点：

1. **审批是 user-only**：MCP 工具里不再提供 `approve_confirmation`，智能体没有任何
   "给自己授权"的路径。宿主拒绝 → 工具根本不会执行。
2. **fail-closed**：引擎在委派前会检查 profile 的 bundle 列表、`cordis.patch.yml`
   是否 `disabled: true`、以及闸门心跳/代际标记；任何一项不成立就退回本地确认流程
   （`confirmations approve`），不会"以为有人审批其实没人"。
3. 本地流程的待确认操作持久化在 SQLite，MCP 进程重启后仍可由用户批准。
4. 所有放行/拒绝都写审计，日志脱敏。

备用通道（不经 DSH 时）：

```powershell
python -m dsh_autonomous_learning.main confirmations list
python -m dsh_autonomous_learning.main confirmations approve <token>
```

> 升级提示：闸门插件新增心跳是**新模块代际**，安装器会报 `restart-required`；
> 重启 DSH 后新代际生效（此前旧代际仍会正常弹审批）。重启后可用
> `mcp__autolearn__get_runtime_info` 查看 `host_approval_fresh=true` 确认心跳。

手动复核闸门判定（不启动 Harness）：

```powershell
cd <repo>/plugins/approval
node decision_test.mjs   # 用真实 tool_risks.json 验证 8 条判定
```



## 4.2 插件设置卡（模式 / 数据目录 / 每日预算）

`@local/dsh-autolearn` 现在同时有 Host 与 Client 两半：

- **Client**：`client.js` 注册进 `plugins.bundle.config`（key 为包名），在
  「设置 → 插件 → 自主学习」的 bundle 页渲染一张配置卡；
- **Host**：`index.js` 注册路由 `/dsh-autolearn/api/settings`（GET/POST JSON，
  64KB 上限，校验模式枚举、预算范围、绝对路径），读写 `data/settings.json`；
- **引擎**：`load_config` 会合并该文件，`run_round` 每轮开始前再读一次。

| 字段 | 生效时机 | 校验 |
| --- | --- | --- |
| 运行模式 assisted/auto/lab | 下一轮学习开始时 | 枚举 |
| 数据目录（绝对路径，可留空） | 重连 MCP 连接后 | 必须绝对路径 |
| 每日预算 USD（0–1000） | 下一轮学习开始时 | 数值范围 |

设计取舍：设置不写进 Cordis 插件 Config，而是落在 `data/settings.json`，
因为这份值需要跨语言共享（Node 卡片 ↔ Python 引擎），单一文件避免两套真相；
静态 `config.json` 仍是缺省值来源。



## 5. 关键设计（与 6 条强制规则对应）

### 规则 1：分区与隔离
- 8 个逻辑分区（general/uiux/finance/quant/programming/project/experiment/pending），
  单一向量索引 + 元数据过滤，不绑定任何集合名。
- 项目知识默认 `visibility=project`，跨项目检索默认不可见；跨领域只建关系、不合并。
- 每个分区提供数量/已核验/待核验/冲突/过时/最近更新统计。

### 规则 2：反馈闭环
`run_learning_round` 每轮：取就绪任务 → 执行 → 记录证据 → 更新状态 → 检查预算 →
评估 → 按缺口/冲突生成补充任务 → 决定继续/暂停。停止条件：目标达标、任务/迭代上限、
时间/费用预算、连续无进展、依赖不可用、需要授权。

### 规则 3：状态与可靠性分离
- 处理状态：`discovered → extracted → pending_verification → verified → practiced → evaluated`，
  外加 `stale / disputed / rejected / superseded`，迁移走白名单 + 守卫。
- 可靠性属性独立：`source_quality / evidence_count / evidence_independence / confidence /
  freshness / conflict_status / verification_method / verification_evidence / limitations`。
- `verified` 是受保护状态：必须有**方法匹配 + 结果 pass + 含证据**的核验记录，且满足
  证据条数、独立来源数、来源质量门槛；观点/假设/未解决问题**永不**升级为事实。
- L0-L5 由系统根据状态与证据推导，模型无权指定。

### 规则 4：独立工具
共 **63** 个工具（规范要求的 55 个 + 系统/审计/调度辅助），每个都有：名称、说明、JSON Schema、
参数校验、结构化返回（`success/data/error/warnings`）、风险等级、副作用说明。
数据库/文件/去重/状态更新用确定性逻辑；只有提取增强、主题补充等才调模型。

### 规则 5：分级权限
- `assisted`：读/规划/提取允许；删除、正式迁移、外部抓取、代码执行需要确认令牌。
  在 DSH 里确认方式已改为**原生审批弹窗**（见 4.1），由用户点批准/拒绝。
- `auto`：已授权范围内自动提取/核验/写入待审区；代码执行仍禁止。
- `lab`：允许受控目录内执行 Python（`-I`、空环境白名单、超时、输出上限），
  **明确声明这是进程级隔离，不是安全沙箱**。
- 硬规则：外部内容不可改配置；密钥模式扫描（`sk-…`、Bearer、私钥等）禁止入库；审计全量留痕并脱敏。

### 规则 6：有界、可恢复、可评估
- 任务状态机 + 依赖 + 幂等键；崩溃后 `recover` 把 running 恢复为 retrying。
- 预算：单轮任务数/迭代数/时间、单任务资料数、模型调用数、费用估算、每日预算。
- 调度：持久化 interval/once，`tick` 有界执行，一次性任务执行后自动关闭。
- 每轮产出 run 摘要与阶段报告，报告含成果、来源、冲突、失败与后续建议。

## 6. 知识入库规则（对应规范第五节）

采集 → 记录来源/时间/许可 → 类型判断 → 正文清洗 → 语言/主题 → 内容指纹 →
按章节/段落切块 → 元数据 → 公式/代码/假设/不确定项提取 → 冲突候选 →
向量化 → 写入 → SQLite 记录版本 → 抽样检索测试（由评估/体检工具承担）→ 失败项生成修复任务。

默认落地区是 `pending_knowledge`；核验通过后在 `auto/lab` 模式才会迁入领域分区，
`assisted` 模式保持待审、等待人工确认。

## 7. 检索

- 混合检索：向量通道（余弦）+ 关键词通道（自研 BM25），RRF 融合，权重可配。
- 元数据过滤：分区、领域、主题、状态、核验状态、知识类型、来源类型、许可、时效、
  置信度下限、时间范围、项目可见性。
- 结果永远携带：来源、相关度、核验状态、可靠性属性、冲突/时效提示、是否需要重新核验。
- **相似度不是正确性**：低置信度/未核验/冲突项会显式标注，不会被"顺滑地"当作事实。

## 8. 测试与真实结果

```powershell
cd <repo>
$env:PYTHONPATH = "<repo>"
python -m pytest dsh_autonomous_learning\tests
```

覆盖：配置、存储/索引/备份恢复、状态机守卫、提取与分类、检索 Recall@3、
去重（精确/近似）、冲突（数值/极性/否定）、核验（无证据不得升级、公式重算、
观点不可验证、代码执行证据）、端到端闭环、断点续跑、缺口分析、权限确认、
密钥拦截、审计脱敏、预算停止、重试、调度、工具契约与 CLI 冒烟。

**本机真实执行结果（2026-10-19）**：`96 passed in 3.01s`（exit 0）。
完整演示 `python examples\demo_end_to_end.py` 的真实输出摘要：

| 步骤 | 实际结果 |
| --- | --- |
| 创建项目 + 计划 | 5 个主题、23 个任务（含依赖与验收条件） |
| 执行一轮 | 执行 14 个任务，新增 4 条知识，停止原因 `task_limit_reached`，读入 2 个来源 |
| 知识库 | 5 条片段 / 5 个向量 / 512 维；1 条已核验（warning 类型，单来源质量 0.60 达标） |
| 混合检索「滑点对回测收益的影响」 | 命中 3 条，均带来源、核验状态与许可告警 |
| 冲突检测 | 登记 1 组：`1.8 vs 0.9`（同一策略的夏普比率），双方证据保留 |
| 核验 | definition 类型因 `来源质量 0.60 < 0.80` 判为 partial，状态保持待核验 |
| 评估 | 覆盖率 20%、核验率 20%、冲突 1 组；`goal_met=false`，给出 4 条未达标原因 |
| 报告 | 生成 Markdown + JSON（`data/reports/…`） |
| 体检 | 索引一致，无来源缺失，提示「核验率过低」 |

MCP 握手（真实客户端 `mcp` SDK）：`initialize` 成功 → `tools/list` 返回 63 个工具 →
`create_learning_project` / `save_knowledge` / `search_knowledge` 调用成功，
空库检索明确返回 `gap=true`。

在 DSH 中已注册连接 `custom-autolearn`（serverName=`autolearn`），
工具以 `mcp__autolearn__*` 形式暴露；完整状态与命令见 `docs/交付报告.md`。

> 说明：演示里未接入真实模型 API（配置默认 `mock`），也没有执行任何不可信代码；
> 所有"已核验"条目都带可追溯证据，未核验条目不会被粉饰为事实。


## 9. 安全边界（必须如实告知）

- 代码执行**不是沙箱**：只是独立目录 + `-I` + 环境变量白名单 + 超时 + 输出截断。
  因此默认禁止执行不可信代码；外部文档里的代码默认 `trusted=false`。
- 不绕过登录/付费墙/访问控制；网络默认关闭；下载有体积上限与域名白名单。
- 不做 OCR；扫描版 PDF 会明确报"未提取到文本"。
- 不做真实回测/交易：量化类实践任务会明确标记"需要外部回测引擎"，不会伪造收益。

## 10. 已知问题与未实现

1. `sentence_transformers` / OpenAI embeddings 适配器已实现但**未在本机联网验证**（无密钥/未装模型）。
2. MCP 服务器由客户端拉起；插件不保证进程常驻，长周期学习需要外部调度。
3. 中文关键词依赖二元组切分，未接分词器；对同义改写召回不如神经向量模型（已用混合检索缓解）。
4. 概念类问答的自动判分是"要点覆盖"规则，仅作参考，仍需人工复核。
5. 冲突检测是规则式（数值/极性/否定），不做深度语义蕴含判断；复杂矛盾需要人/模型介入并保留双方证据。
6. 未实现图数据库、UI 面板、回测引擎、OCR；均不在 P1-P6 必需范围内。
7. 审批闸门新增心跳属于新模块代际：安装器返回 `restart-required`，重启 DSH 后生效；
   重启前旧代闸门仍会弹审批。审批弹窗的**实际点击交互**尚未在浏览器中验证。

## 11. 后续建议

- 接入可控的嵌入服务（bge-m3 / text-embedding-3）后重建索引，量化对比 Recall@K 与 MRR。
- 把 `assisted` 模式的确认流程接到 DSH 的审批 UI，形成"人审入库"闭环。
- 为量化/UI/编程领域分别补充领域验证插件（P5 扩展点已在 `knowledge/partitions.py` 与工具层预留）。
