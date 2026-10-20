# @local/dsh-autolearn-approval

把 `dsh_autonomous_learning`（自主学习 MCP Server）的高风险工具调用接入 **DSH 原生审批弹窗**。

## 行为

- 监听 `tools/pre-execute`；
- 对 `mcp__autolearn__*` 中：
  - `risk=execute`（如 `run_code_test`、`run_learning_experiment`）
  - `risk=destructive`（如 `invalidate_knowledge`、`restore_knowledge_base`）
  - 以及配置里 `askTools` 显式列出的工具（默认含 `update_knowledge`）
  返回 `{ kind: 'ask', reason }`；
- 其它调用直接 `next()` 放行；
- 用户拒绝 → 工具不会执行；宿主会把 ask/outcome 写进会话日志。

风险清单来自 `<repo>/dsh_autonomous_learning/tool_risks.json`，
由引擎的 `export-tool-risks` 生成；工具增减后重新导出即可，不必改本插件。

## 配置（cordis.patch.yml）

```yaml
- insert:
    - id: autolearn-approval
      name: '@local/dsh-autolearn-approval'
      config:
        prefix: 'mcp__autolearn__'
        manifestPath: '<repo>/dsh_autonomous_learning/tool_risks.json'
        askRisks: [execute, destructive]
        askTools: [update_knowledge, invalidate_knowledge, restore_knowledge_base, run_code_test, run_learning_experiment]
        allowTools: []
```

## 心跳与 fail-closed

插件每 30s 写 `data/host_approval.heartbeat`，并在启动时写
`data/host_approval.gate.json`（`generation: 2`）。引擎只有在

1. profile 的 bundle 列表包含本包；
2. `cordis.patch.yml` 未 `disabled: true`；
3. 代际 ≥2 时心跳新鲜

三条同时成立时，才把高风险确认交给宿主；否则退回本地 `confirmations approve` 流程。

## 自测

```powershell
cd <repo>/plugins/approval
node --check index.js
node decision_test.mjs
```
