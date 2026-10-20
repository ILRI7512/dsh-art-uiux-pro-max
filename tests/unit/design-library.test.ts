import assert from 'node:assert/strict'
import { test } from 'node:test'
import { colorTokens, expandQuery, library, librarySearch, recommend, review, searchDomain } from '../../src/domain/design-library.ts'

test('设计库计数与来源可追溯', () => {
  const data = library()
  assert.equal(data.domains.style?.length, 88)
  assert.equal(data.domains.color?.length, 192)
  assert.equal(data.domains.typography?.length, 74)
  assert.equal(data.domains.ux?.length, 119)
  assert.equal(data.reasoning.length, 192)
  assert.match(data.upstream, /ui-ux-pro-max-skill/)
  assert.equal(data.upstreamRef?.length, 40)
})

test('中文别名扩展是确定性的', () => {
  const expanded = expandQuery('毛玻璃 深色')
  assert.ok(expanded.query.includes('glassmorphism') || expanded.query.includes('glass'))
  assert.ok(expanded.hits.length > 0)
  const single = expandQuery('图')
  assert.ok(single.query.includes('chart'))
})

test('推荐包含风格/令牌/字体/UX/旋钮', () => {
  const result = recommend({ query: '财务 数据看板 深色 高密度', variance: 7, motion: 4, density: 9 })
  assert.ok(String(result.category).length > 0)
  assert.ok((result.styles as unknown[]).length > 0)
  const tokens = (result.palette as any).tokens
  assert.equal(Object.keys(tokens).length, 16)
  assert.ok(tokens.background?.startsWith('#'))
  assert.ok(String((result.typography as any).heading).length > 0)
  assert.ok((result.ux_guidelines as unknown[]).length >= 4)
  assert.deepEqual((result.knobs as any).spacing_scale_px, [2, 4, 6, 8, 12, 16, 24, 32])
  assert.match(String((result.provenance as any).upstreamRef), /^[0-9a-f]{40}$/)
})

test('审查按严重度排序且带代码对照', () => {
  const result = review({ target: '移动端登录页，提交后没有任何反馈', platform: 'mobile', maxRules: 8 })
  const rules = result.rules as any[]
  assert.ok(rules.length >= 3)
  assert.ok(rules.some((rule) => rule.severity === 'Critical' || rule.severity === 'High'))
  assert.ok(rules.every((rule) => typeof rule.do === 'string'))
  assert.equal((result.checklist as unknown[]).length, 10)
  assert.throws(() => review({ target: 'x', platform: 'nope' }), /platform/)
})

test('库检索按域返回，并支持废弃条目开关', () => {
  const glass = librarySearch({ query: '毛玻璃 深色', domain: 'style', maxResults: 3 })
  assert.ok((glass.count as number) > 0)
  assert.ok((glass.results as any[]).every((hit) => hit.domain === 'style'))
  const deprecated = searchDomain('style', 'legacy Swiss', 10, true)
  assert.ok(deprecated.length > 0)
  assert.throws(() => searchDomain('nope' as never, 'x'), /未知设计库域/)
})

test('调色板令牌映射到 16 个语义名', () => {
  const row = library().domains.color?.[0] ?? {}
  const tokens = colorTokens(row)
  assert.equal(Object.keys(tokens).length, 16)
  assert.ok(tokens.primary && tokens['on-primary'] && tokens.ring)
})
