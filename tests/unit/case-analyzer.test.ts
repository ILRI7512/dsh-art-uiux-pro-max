import assert from 'node:assert/strict'
import { test } from 'node:test'
import { analyzeHtml, unitsFromCase } from '../../src/domain/case-analyzer.ts'
import { CATEGORY_KEYS } from '../../src/domain/taxonomy.ts'
import { FIXTURE_HTML, seedResource } from '../helpers.ts'
import type { Resource } from '../../src/core/types.ts'

test('事实/推断/观点三分，并给出真实 alt 统计', () => {
  const analysis = analyzeHtml(FIXTURE_HTML, { url: 'https://example.com/', product: 'Fixture' })
  const kinds = new Set(Object.values(analysis.sections).flat().map((evidence) => evidence.kind))
  assert.deepEqual([...kinds].sort(), ['fact', 'inference'])
  assert.ok(Object.values(analysis.sections).flat().some((evidence) => evidence.statement.includes('linear-gradient')))
  const a11y = (analysis.sections['Accessibility Analysis'] ?? []).map((evidence) => evidence.statement).join(' ')
  assert.ok(a11y.includes('img 2 张') && a11y.includes('带 alt 1 张'))
  assert.ok(Array.isArray(analysis.tech_stack))
})

test('能力边界声明不入库，等级只到 L2', () => {
  const analysis = analyzeHtml(FIXTURE_HTML, { url: 'https://example.com/', product: 'Fixture' })
  const resource = seedResource() as unknown as Resource
  const units = unitsFromCase(analysis, resource)
  assert.ok(units.length > 0)
  assert.ok(!units.map((unit) => unit.content).join(' ').includes('能力边界'))
  for (const unit of units) {
    assert.ok(CATEGORY_KEYS.includes(unit.category))
    assert.ok(['L1', 'L2'].includes(unit.level))
  }
})

test('opinion 证据被过滤', () => {
  const analysis = analyzeHtml(FIXTURE_HTML, { url: 'https://example.com/', product: 'Fixture' })
  analysis.sections['Visual Language']?.push({ statement: '看起来更高级', kind: 'opinion', confidence: 0.2, basis: '主观' })
  const units = unitsFromCase(analysis, seedResource() as unknown as Resource)
  assert.ok(!units.some((unit) => unit.content.includes('看起来更高级')))
})
