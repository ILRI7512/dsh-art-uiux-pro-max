import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'

const clientBundle = new URL('../../dist/client/index.js', import.meta.url)

/**
 * 回归：客户端 bundle 必须是「经典脚本」。
 *
 * 它被 <script> 直接执行，只允许调用 window.__ModuleLoader__.load({ id, factory })。
 * 一旦构建把 `export {}`（tsc 对无 import/export 的模块会补这一行）带进产物，
 * 浏览器就会抛 Uncaught SyntaxError: Unexpected token 'export'，
 * 整个 web boot 以 "@local/art-uiux: import failed" 失败 —— desktop profile 进不去。
 */
test('客户端 bundle 是经典脚本，能注册 __ModuleLoader__ 工厂', () => {
  const source = readFileSync(clientBundle, 'utf8')

  assert.ok(source.includes('__ModuleLoader__.load('), '必须注册 __ModuleLoader__ 工厂')
  assert.doesNotMatch(
    source,
    /(^|\r?\n)[ \t]*(export|import)[ \t]/u,
    '客户端 bundle 不允许出现 ESM 的 import/export 语句',
  )
  assert.doesNotThrow(() => new Function(source), '客户端 bundle 必须能被 <script> 解析执行')
})
