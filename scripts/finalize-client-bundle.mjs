/**
 * 客户端 bundle 收尾。
 *
 * DSH 的 client bundle 契约是「经典脚本」：文件被 <script> 执行时只做一件事——
 * 调用 `window.__ModuleLoader__.load({ id, factory })` 注册工厂，任何 ESM 语法都不合法。
 *
 * 但 tsconfig 走 `module: NodeNext` + package.json `type: module`，TypeScript 会把
 * 「没有任何 import / export 的 .ts」也当成模块，于是给 dist/client/index.js 末尾
 * 补一行 `export {};`。浏览器执行到这里会抛 `Uncaught SyntaxError: Unexpected token
 * 'export'`，整个 web boot 以 "entry did not activate" 失败（P0：desktop profile 进不去）。
 *
 * 所以构建后必须把这一行去掉，并守住两条不变量：
 *   1. 文件里不再有任何顶层 `export` / `import` 语句；
 *   2. 文件确实以 `__ModuleLoader__.load(` 注册。
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const target = fileURLToPath(new URL('../dist/client/index.js', import.meta.url))
const original = readFileSync(target, 'utf8')

// 只删 tsc 补在文件末尾的 `export {};`（可带前导空行/缩进），其余内容保持逐字节不变。
const stripped = original.replace(/(^|\r?\n)[ \t]*export[ \t]*\{[ \t]*\}[ \t]*;?[ \t]*(?=\r?\n?$)/u, '$1')

if (stripped.includes("window.__ModuleLoader__.load(") === false) {
  throw new Error(`[finalize-client-bundle] ${target} 没有注册 __ModuleLoader__ 工厂，构建产物不正确`)
}

const leftover = /(^|\r?\n)[ \t]*(export|import)[ \t]/u.exec(stripped)
if (leftover !== null) {
  throw new Error(
    `[finalize-client-bundle] ${target} 仍有 ESM 语句：${JSON.stringify(leftover[0].trim())}；` +
      '客户端 bundle 必须是经典脚本',
  )
}

if (stripped !== original) {
  writeFileSync(target, stripped, 'utf8')
  console.log(`[finalize-client-bundle] 已移除 dist/client/index.js 末尾的 "export {};"（${original.length} → ${stripped.length} 字节）`)
} else {
  console.log('[finalize-client-bundle] dist/client/index.js 已是经典脚本，无需修改')
}
