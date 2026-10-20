# @local/art-uiux

DSH Art UI/UX Pro Max 的插件包（TypeScript 原生，无 Python / MCP 子进程）。

| 项 | 值 |
| --- | --- |
| 插件名 | `@local/art-uiux` |
| 工具 | 16 个 `art_*` 原生工具 |
| 入口 | `dist/plugin/index.js`（`npm run build` 产物） |
| 设置卡 | `/art-uiux/api/settings` + `/art-uiux/api/stats` |
| 数据 | `<repo>/data/knowledge.sqlite3`、`data/registry.json`、`data/settings.json` |

## 安装

```bash
npm install
npm run build
dsh plugin --profile web add link:/path/to/dsh-art-uiux-pro-max
```

然后把 `"@local/art-uiux"` 加入该 profile 的 `dsh.profile.bundles`，重启 DSH。
`cordis.patch.yml` 是空 patch：工具由插件入口直接注册，不再插入 MCP 客户端条目。

## 设置

设置卡可改：数据目录、是否允许网络、是否允许私网地址、单次学习区块上限、默认重排策略。
`allowNetwork=false` 时所有抓取明确失败（`NETWORK_BLOCKED`），不会静默降级。

## 可选 MCP

其他 MCP 客户端可运行：

```bash
node dist/mcp/server.js
```

它与原生工具共用同一份服务与数据库。原生 DSH 使用不需要它。
