import assert from 'node:assert/strict'
import { test, before, after } from 'node:test'
import { createServer, type Server } from 'node:http'
import { HttpClient, assertSafeHttpUrl, NetworkBlockedError } from '../../src/infra/http.ts'

let server: Server
let base = ''

before(async () => {
  server = createServer((req, res) => {
    const url = req.url ?? '/'
    if (url === '/robots.txt') {
      res.writeHead(200, { 'content-type': 'text/plain' })
      res.end('User-agent: *\nDisallow: /blocked\nAllow: /\n')
      return
    }
    if (url === '/blocked') { res.writeHead(200, { 'content-type': 'text/html' }); res.end(`<html><body>${'blocked '.repeat(40)}</body></html>`); return }
    if (url === '/empty') { res.writeHead(200, { 'content-type': 'text/html' }); res.end('x'); return }
    if (url === '/json') { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify({ ok: true })); return }
    if (url === '/403') { res.writeHead(403, { 'content-type': 'text/html' }); res.end('no'); return }
    if (url === '/redirect') { res.writeHead(302, { location: '/ok' }); res.end(); return }
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' })
    res.end(`<html><head><title>OK page</title></head><body><p>${'design tokens layout '.repeat(20)}</p></body></html>`)
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  base = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`
})

after(() => new Promise<void>((resolve) => server.close(() => resolve())))

test('默认拒绝 loopback，显式开启后才允许', async () => {
  await assert.rejects(() => assertSafeHttpUrl(base), NetworkBlockedError)
  const url = await assertSafeHttpUrl(base, { allowPrivateNetworks: true })
  assert.equal(url.hostname, '127.0.0.1')
})

test('probe 走 robots、重定向与状态分类', async () => {
  const client = new HttpClient({ allowPrivateNetworks: true, minHostIntervalMs: 0 })
  const ok = await client.probe(`${base}/ok`)
  assert.equal(ok.access_status, 'reachable')
  assert.equal(ok.http_status, 200)
  assert.equal(ok.title, 'OK page')
  assert.equal(ok.robots_allowed, true)

  const blocked = await client.probe(`${base}/blocked`)
  assert.equal(blocked.access_status, 'blocked')
  assert.equal(blocked.robots_allowed, false)

  const empty = await client.probe(`${base}/empty`)
  assert.equal(empty.access_status, 'restricted')

  const denied = await client.probe(`${base}/403`)
  assert.equal(denied.access_status, 'restricted')

  const redirect = await client.probe(`${base}/redirect`)
  assert.equal(redirect.access_status, 'reachable')
  assert.ok(redirect.final_url.endsWith('/ok'))
})

test('fetchHtml 拒绝非文本内容与 robots 禁止路径', async () => {
  const client = new HttpClient({ allowPrivateNetworks: true, minHostIntervalMs: 0 })
  const page = await client.fetchHtml(`${base}/ok`)
  assert.ok(page.html.includes('design tokens'))
  await assert.rejects(() => client.fetchHtml(`${base}/json`), /内容类型/)
  await assert.rejects(() => client.fetchHtml(`${base}/blocked`), /robots/)
})

test('网络关闭时所有抓取都被拒绝', async () => {
  const client = new HttpClient({ allowPrivateNetworks: true, minHostIntervalMs: 0 })
  const result = await client.probe('ftp://example.com/a')
  assert.equal(result.access_status, 'blocked')
})
