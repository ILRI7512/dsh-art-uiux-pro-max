import assert from 'node:assert/strict'
import { test } from 'node:test'
import { Readable } from 'node:stream'
import { join } from 'node:path'
import { ArtServices } from '../../src/application/services.ts'
import { settingsRoute, statsRoute } from '../../src/plugin/settings-route.ts'
import { cleanup, makeRoot, seedResource } from '../helpers.ts'

function call(route: any, method: string, body?: unknown): Promise<{ status: number; body: any }> {
  return new Promise((resolve) => {
    const req = body === undefined
      ? { method }
      : Object.assign(Readable.from([Buffer.from(JSON.stringify(body))]), { method })
    const res = {
      status: 0,
      writeHead(status: number) { this.status = status; return this },
      end(text?: string) { resolve({ status: this.status, body: text ? JSON.parse(text) : null }) },
    }
    void route.handler(req, res)
  })
}

test('设置路由读写、校验与统计', async () => {
  const root = makeRoot([seedResource()])
  const services = new ArtServices({ root, dataDir: join(root, 'data') })
  try {
    const route = settingsRoute(services)
    assert.equal(route.path, '/art-uiux/api/settings')
    const get = await call(route, 'GET')
    assert.equal(get.status, 200)
    assert.equal(get.body.settings.allowNetwork, true)
    assert.ok(get.body.settingsPath.endsWith('settings.json'))

    const post = await call(route, 'POST', { maxUnits: 12, allowPrivateNetworks: true })
    assert.equal(post.status, 200)
    assert.equal(post.body.settings.maxUnits, 12)
    assert.equal(services.settings.maxUnits, 12)

    const bad = await call(route, 'POST', { dataDir: 'relative' })
    assert.equal(bad.status, 400)
    assert.match(bad.body.error, /absolute/)

    const rejected = await call(route, 'POST', { maxUnits: 0 })
    assert.equal(rejected.status, 400)

    const stats = await call(statsRoute(services), 'GET')
    assert.equal(stats.status, 200)
    assert.equal(stats.body.registry.total, 1)
    assert.equal(stats.body.knowledge.chunks, 0)
  } finally { services.close(); cleanup(root) }
})
