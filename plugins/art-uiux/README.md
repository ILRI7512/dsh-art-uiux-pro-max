# @local/dsh-autolearn

把自主学习引擎打包成 **DSH 插件**（配置型 bundle）：安装即自动注册 MCP stdio 服务器，
无需手工在连接器面板里填命令与路径。

## 安装后的形态

| 项 | 值 |
| --- | --- |
| 插件名 | `@local/dsh-autolearn`（Plugin Manager 可见） |
| 提供的 MCP 服务器 | `serverName: autolearn` |
| 工具名 | `mcp__autolearn__*`（63 个） |
| 引擎位置 | `<repo>/dsh_autonomous_learning`（Python） |
| 审批闸门 | 配套插件 `@local/dsh-autolearn-approval` |

## patch 做了什么

```yaml
- insert:
    - id: autolearn-mcp
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: autolearn
        transport: stdio
        command: 'python'
        args: ['-m', 'dsh_autonomous_learning.plugin']
        ...
```

`DSH_AL_HOST_APPROVAL=1` 让引擎把高危确认交给宿主审批；
`DSH_AL_HOME` / `PYTHONPATH` 指向引擎目录与包父目录。

## 设置卡

插件在「设置 → 插件 → 自主学习」的 bundle 页上渲染一张配置卡（Client 半边
`client.js` 注册进 `plugins.bundle.config`），包含：

| 字段 | 说明 | 生效时机 |
| --- | --- | --- |
| 运行模式 | assisted / auto / lab | 下一轮学习开始时 |
| 数据目录 | 绝对路径；留空用 `data/` | 重连 MCP 连接后（DB 与索引在建连时打开） |
| 每日预算 | USD，估算值，0–1000 | 下一轮学习开始时 |

数据通过 Host 路由 `/dsh-autolearn/api/settings` 读写 `data/settings.json`，
与 Python 引擎共用同一份文件（不引入第二套配置真相）。Host 半边同时校验
模式枚举、预算范围与绝对路径。

## 验证

1. Plugin Manager 中出现「自主学习 / Autonomous Learning」；
2. 重启或安装后，Agent 工具列表出现 `mcp__autolearn__create_learning_project` 等；
3. 调 `get_runtime_info` 应看到 `host_gate_installed=true` 与 `settings` 生效值；
4. `curl http://127.0.0.1:58586/dsh-autolearn/api/settings` 返回当前设置。
