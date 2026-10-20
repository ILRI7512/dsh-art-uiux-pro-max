# 故障与修复记录：Desktop profile 无法进入

- 日期：2026-10-20
- 组件：`@local/art-uiux` 1.1.0（本仓库）
- 环境：DSH Desktop 2.0.18-next / dsh 0.2.1-alpha.2 / Electron 44.0.0 / Node v24.18.1 / Windows 11
- 修复提交：`221210a fix(client): keep the client bundle a classic script`

## 1. 现象

在桌面端切换到 `desktop` profile 时无法进入：窗口停在启动/失败状态，主进程日志记录 `runtime.failed`。
`web` profile（未启用本插件）不受影响，所以问题被误判为“profile 配置坏了”。

## 2. 影响面

- 所有启用了本插件 client bundle 的 profile（当时是 `desktop`）。
- 与 profile 的 `cordis.yml` / `cordis.patch.yml` 无关：Host 侧其实已经 `process.ready`，是**渲染进程**的 web boot 失败。
- 插件 16 个原生工具在 Host 侧是正常的，用户完全看不到——因为界面根本没起来。

## 3. 证据

日志：`%USERPROFILE%\.dsh\logs\desktop-next.log`（`2026-10-20T15:19:50Z`）

```
[error] Uncaught SyntaxError: Unexpected token 'export' [renderer] console {"webContentsId":1}
[error] Error: web boot: 1 entry did not activate
        @local/art-uiux: import failed (see console for the import error) [renderer] console
[error] [desktop] runtime.failed {"name":"Error","message":"web boot: 1 entry did not activate\n@local/art-uiux: import failed ..."}
```

同一时刻另一个 entry 的报错是干扰项（`better-sidebar ... pending (waiting for service: webRuntime)`），
`pending` 不会让 boot 失败，只有 `1 entry did not activate` 会。

最小复现（不用起 GUI）：

```bash
node -e "new Function(require('fs').readFileSync('dist/client/index.js','utf8'))"
# SyntaxError: Unexpected token 'export'
```

## 4. 根因

四层，缺一层都不会炸：

1. **契约**：DSH 的 client bundle 是**经典脚本**。`app.asar` 里 `@deepseek-ai/dsh-client-modules` 的说明写明：
   执行 bundle 只做一件事——`window.__ModuleLoader__.load({ id, factory })`，模块体副作用推迟到 factory 执行时。
   因此文件里出现任何 ESM 语法都是非法的。
2. **编译产物**：本仓库 `tsconfig` 是 `module: NodeNext`，`package.json` 是 `type: module`。
   TypeScript 会把「没有任何 `import`/`export` 的 `.ts`」也判定为模块，并在产物末尾补 `export {};` 以保持模块身份。
3. **本插件的源码形态**：`src/client/index.ts` 恰好是「零 import/export、只操作 `window` 全局」的经典脚本源文件，
   正是会被补 `export {};` 的那一类。
4. **失败放大**：浏览器解析到末尾 `SyntaxError` → 该 entry 的 `import` 失败 →
   `client-modules` 统计到未激活 entry → web boot 整体失败 → 桌面端 profile 进不去。

链式表达：`export {};` → `SyntaxError` → entry import 失败 → `web boot: 1 entry did not activate` → profile 无法进入。

## 5. 同一文件里的第二个缺陷（独立问题）

`apply()` 里直接读 `ctx.webServer`。Cordis 对**未在 `inject` 中声明**的服务做属性取值会抛：

```
cannot get property "webServer" without inject
```

原实现用 `try/catch` 吞掉了异常，后果是**设置卡路由从未注册**——设置卡打开就是 404。
（`dsh-autolearn` 因为没兜异常，直接表现为 entry 激活失败，已在其仓库单独修复。）

注意：把 `webServer` 写进顶层 `inject` 不是解法——headless / CLI profile 没有 web server，
entry 会永久 `pending`，16 个原生工具跟着失效。正确做法见下。

## 6. 修复

| 文件 | 改动 |
| --- | --- |
| `dist/client/index.js` | 删除 tsc 补在末尾的 `export {};` |
| `scripts/finalize-client-bundle.mjs` | 新增：构建后剥离 ESM 尾巴，并断言「无 import/export」+「已注册 `__ModuleLoader__`」，否则构建失败 |
| `package.json` | `build` 改为 `tsc … && node ./scripts/finalize-client-bundle.mjs`，防止复发 |
| `src/plugin/index.ts` | 设置卡路由改为在子注入上下文挂载：`ctx.inject(['webServer'], (wctx) => …)`；顶层 `inject` 仍然只有 `['tools']` |
| `tests/unit/client-bundle.test.ts` | 新增回归测试：产物必须能被经典脚本解析且注册 loader |
| `scripts/check-client-bundles.mjs` | 新增体检脚本：扫描整份 profile 的所有 client bundle |

`ctx.inject` 的做法与 DSH 官方 `dsh-mcp-connector` 的 `injectWebRoutes` 一致：
服务就绪后回调，未就绪则等待但不阻塞主插件。

## 7. 验证

1. **产物层**：`new Function(dist/client/index.js)` 通过，文件以 `});` 结尾，无 ESM 语法。
2. **构建自守**：`npm run build` 输出
   `[finalize-client-bundle] 已移除 dist/client/index.js 末尾的 "export {};"`；
   重复构建结果稳定（幂等）。
3. **Host 真实启动**（按桌面端的 spawn 方式：Electron 二进制 + `app.asar/lib/host.js` + IPC + `ELECTRON_RUN_AS_NODE=1`）：
   - `dsh web: http://127.0.0.1:<port>/?token=…` 正常
   - `dsh: warning: 1 entry did not activate` —— 只剩 `better-sidebar` 的 `pending`，修复前是 2 个且含报错
   - 插件日志：`[art-uiux] 原生工具已注册: 16 个`
4. **真实 boot 载荷**：抓取 index 里的 3 个合并 bundle（11,226,667 / 6,214,501 / 40,661 字节），
   共 **81 个 client entry** 全部按经典脚本解析通过，`@local/art-uiux` 在 boot graph 中。
5. **接口层**：`GET /art-uiux/api/settings`、`GET /art-uiux/api/stats` 均返回 200 与真实数据。
6. **测试**：`npm test` 59/59 通过；`npm run typecheck` 通过。
7. **全量体检**：`node scripts/check-client-bundles.mjs` → `13 client bundles, 0 broken`。

## 8. 防复发

- 构建后置断言已是 `npm run build` 的一部分：只要 tsc 再补 `export {};`，构建直接失败。
- 单测锁住产物形态（改回模块化、被人手工编辑都会被拦下）。
- 任何装了一堆第三方插件的 profile，都可以用 `node scripts/check-client-bundles.mjs <profileDir>` 一次性体检。

给其他插件作者的经验：**如果你的 client bundle 是手写经典脚本、又用 tsc 编译，务必把 `export {};` 剥掉**，
或者干脆用 bundler（如 tsdown）产出 `__ModuleLoader__` 工厂包，别让编译产物变成 ESM。

## 9. 相关但未在本次修复

- `dsh-better-sidebar@0.24.1` 在本版 DSH 里一直 `pending (waiting for service: webRuntime)`：
  alpha.1 起该服务已由 `webStartup` 取代，属于第三方插件的版本不匹配，需升级或替换，不在本仓库范围。
- `@local/dsh-autolearn` 的同类缺陷已在其仓库修复（`42fc9d0`）。
