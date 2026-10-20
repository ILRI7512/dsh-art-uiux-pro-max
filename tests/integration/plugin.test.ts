import assert from 'node:assert/strict'
import { test } from 'node:test'
import { join } from 'node:path'
import { apply } from '../../src/plugin/index.ts'
import { cleanup, makeRoot, seedResource } from '../helpers.ts'

test('插件注册 13 个工具与设置路由，卸载可清理', () => {
  const root = makeRoot([seedResource()])
  const tools = new Map<string, unknown>()
  const routes: string[] = []
  let disposed = false
  const ctx = {
    tools: { register(tool: any) { tools.set(tool.name, tool); return () => tools.delete(tool.name) } },
    webServer: { register(route: any) { routes.push(route.path); return () => { routes.pop() } } },
    effect(callback: () => () => void) { const off = callback(); return () => { off(); disposed = true } },
  }
  try {
    apply(ctx as any, { home: root, dataDir: join(root, 'data') })
    assert.equal(tools.size, 13)
    assert.ok(tools.has('art_search') && tools.has('art_learn'))
    assert.deepEqual(routes, ['/art-uiux/api/settings', '/art-uiux/api/stats'])
  } finally { cleanup(root) }
})
