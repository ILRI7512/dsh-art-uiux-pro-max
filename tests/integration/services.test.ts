import assert from 'node:assert/strict'
import { test, before, after } from 'node:test'
import { createServer, type Server } from 'node:http'
import { join } from 'node:path'
import { ArtServices } from '../../src/application/services.ts'
import { cleanup, makeRoot, seedResource } from '../helpers.ts'

let server: Server
let base = ''

before(async () => {
  server = createServer((req, res) => {
    if (req.url === '/robots.txt') { res.writeHead(404); res.end(); return }
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' })
    res.end(`<!doctype html><html><head><title>Fixture Docs</title><style>:root{--bg:#101318;--fg:#e6e9ee}.card{border-radius:12px;padding:24px;gap:16px}</style></head><body>
<h1>Color and contrast</h1>
<p>The interface should keep contrast above 4.5:1 for body text. Use 16px body text and a limited palette. Avoid pure white on dark backgrounds. Layout spacing should follow an 8px grid with consistent hierarchy.</p>
<h2>Responsive layout</h2>
<p>Use a responsive grid with breakpoints at 768px and 1024px. Components should keep a visible focus ring and a touch target of at least 44px. The card radius is 12px and the shadow is subtle.</p>
<h2>Typography</h2>
<p>Typography should use a five step type scale. Font sizes are 12px, 14px, 16px, 20px and 28px. Line height should stay readable for long paragraphs and dense tables.</p>
</body></html>`)
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  base = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`
})
after(() => new Promise<void>((resolve) => server.close(() => resolve())))

test('learn 正式入库；search 带回来源与告警', async () => {
  const root = makeRoot([seedResource({ url: `${base}/docs`, primary_category: 'ui_quality', resource_type: 'official_documentation' })])
  const services = new ArtServices({ root, settings: { allowPrivateNetworks: true } })
  try {
    const learned = await services.learn({ resourceId: 'unit-test', maxUnits: 5, minIntervalMs: 0 })
    assert.equal(learned.access_status, 'reachable')
    assert.ok(learned.sections >= 2)
    assert.ok(learned.ingested > 0)
    const stats = services.stats() as any
    assert.ok(stats.knowledge.chunks > 0)
    assert.equal(services.registry.get('unit-test')?.learn_status, 'learned')
    const found = services.search({ query: 'contrast ratio for body text', topK: 3 })
    assert.ok(found.count > 0)
    assert.ok(found.hits[0]?.source.url.endsWith('/docs'))
    assert.ok(found.hits[0]?.warnings.some((warning) => warning.includes('unverified')))
  } finally { services.close(); cleanup(root) }
})

test('caseAnalyze 产出证据单元与冲突结构', async () => {
  const root = makeRoot([seedResource({ url: `${base}/case`, primary_category: 'web_ui' })])
  const services = new ArtServices({ root, settings: { allowPrivateNetworks: true } })
  try {
    const result = await services.caseAnalyze({ resourceId: 'unit-test', maxUnits: 10, minIntervalMs: 0 })
    assert.ok(result.units > 0)
    assert.ok(result.ingested > 0)
    assert.ok(Array.isArray(result.conflicts))
    assert.ok(result.warnings.some((warning) => warning.includes('未测')))
  } finally { services.close(); cleanup(root) }
})

test('designTask 走完整七步并保留 unmeasured', async () => {
  const root = makeRoot([seedResource({ url: `${base}/docs` })])
  const services = new ArtServices({ root, settings: { allowPrivateNetworks: true } })
  try {
    await services.learn({ resourceId: 'unit-test', minIntervalMs: 0 })
    const result = await services.designTask({ task: '做一个金融行情终端首页' }) as any
    assert.equal(result.routed.task_type, 'fintech_terminal')
    assert.equal(result.design_system.verified, false)
    assert.ok(result.audit.items.length === 10)
    assert.ok(result.design_system.contrast.every((item: any) => item.measured))
  } finally { services.close(); cleanup(root) }
})

test('关闭网络后 learn 明确拒绝', async () => {
  const root = makeRoot([seedResource({ url: `${base}/docs` })])
  const services = new ArtServices({ root, settings: { allowNetwork: false, allowPrivateNetworks: true } })
  try {
    await assert.rejects(() => services.learn({ resourceId: 'unit-test' }), /网络访问/)
  } finally { services.close(); cleanup(root) }
})

test('设置切换数据目录后存储与注册表一起切换', async () => {
  const root = makeRoot([seedResource()])
  const first = join(root, 'first')
  const services = new ArtServices({ root, dataDir: first })
  try {
    services.stats()
    assert.ok(services.stats().knowledge && (services.stats().knowledge as any).db_path.includes('first'))
    const result = services.updateSettings({ dataDir: join(root, 'second') })
    assert.equal(result.error, undefined)
    assert.equal(services.dataDir, join(root, 'second'))
    assert.ok((services.stats().knowledge as any).db_path.includes('second'))
  } finally { services.close(); cleanup(root) }
})

test('非法分类与非法重排策略明确拒绝', async () => {
  const root = makeRoot([seedResource()])
  const services = new ArtServices({ root, dataDir: join(root, 'data') })
  try {
    assert.throws(() => services.search({ query: 'x', categories: ['nope'] }), /未知主分类/)
    assert.throws(() => services.search({ query: 'x', rerank: 'nope' as never }), /rerank/)
    assert.throws(() => services.search({ query: 'x', minLevel: 'L9' }), /min_level/)
  } finally { services.close(); cleanup(root) }
})

test('Android 任务产出 Kotlin 且审计全 unmeasured', async () => {
  const root = makeRoot([seedResource()])
  const services = new ArtServices({ root, dataDir: join(root, 'data') })
  try {
    const result = await services.designTask({ task: '用 Compose 写一个 Android 首页' }) as any
    assert.equal(result.routed.task_type, 'android_native')
    assert.equal(result.code_ext, 'kt')
    assert.ok(result.code.includes('@Composable'))
    assert.equal(result.audit.items.length, 0)
    assert.equal(result.audit.counts.unmeasured, 10)
  } finally { services.close(); cleanup(root) }
})

test('旧 Python 知识库可迁移，保留 chunk_id 与内容', async () => {
  const { DatabaseSync } = await import('node:sqlite')
  const root = makeRoot([seedResource()])
  const legacyPath = join(root, 'legacy.sqlite3')
  const legacy = new DatabaseSync(legacyPath)
  legacy.exec(`CREATE TABLE chunks(
    chunk_id TEXT, project_id TEXT, topic TEXT, title TEXT, content TEXT, content_hash TEXT,
    level TEXT, partition TEXT, source_url TEXT, source_title TEXT, metadata TEXT
  )`)
  legacy.prepare('INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?,?,?,?)').run(
    'chunk_legacy1', 'prj_art_uiux', 'color_system', '对比度底线',
    '正文与背景的对比度建议不低于 4.5:1。', 'hash-legacy', 'L2', 'uiux_knowledge',
    'https://example.com/legacy', 'Legacy', '{}',
  )
  legacy.close()
  const services = new ArtServices({ root, dataDir: join(root, 'data') })
  try {
    const result = services.importLegacy(legacyPath) as any
    assert.equal(result.found, 1)
    assert.equal(result.imported, 1)
    assert.equal(services.store.getChunk('chunk_legacy1')?.title, '对比度底线')
    const found = services.search({ query: '对比度 可读性', topK: 3 })
    assert.ok(found.hits.some((hit) => hit.chunk_id === 'chunk_legacy1'))
  } finally { services.close(); cleanup(root) }
})
