import assert from 'node:assert/strict'
import { test } from 'node:test'
import { sectionize } from '../../src/infra/html.ts'
import { buildUnit, classify, designRelevance, summarizeUnit } from '../../src/domain/extract.ts'
import { CATEGORY_KEYS } from '../../src/domain/taxonomy.ts'
import { FIXTURE_HTML, seedResource } from '../helpers.ts'
import type { Resource } from '../../src/core/types.ts'

test('分节抽出正文，分类确定且分数归一', () => {
  const sections = sectionize(FIXTURE_HTML)
  assert.ok(sections.length > 0)
  const result = classify(sections[0]!.text, sections[0]!.heading)
  assert.ok(CATEGORY_KEYS.includes(result.category))
  assert.ok(result.score >= 0 && result.score <= 1)
  assert.deepEqual(classify(sections[0]!.text, sections[0]!.heading), result)
})

test('等级必须由证据决定：有显式约束才是 L2', () => {
  const resource = seedResource() as unknown as Resource
  const sections = sectionize(FIXTURE_HTML)
  const normative = sections.find((section) => section.text.toLowerCase().includes('should'))
  assert.ok(normative)
  const unit = buildUnit(normative!, { resource, category: 'ui_quality', score: 0.6, matched: ['contrast'] })
  assert.equal(unit.level, 'L2')
  assert.equal(unit.knowledge.evidence_level, 'L2')
  const complete = ['core_principle', 'applicable_context', 'source_ref', 'evidence_level'].every((key) => unit.knowledge[key])
  assert.equal(unit.ready_to_ingest, complete && unit.relevance.relevant)

  const plain = buildUnit(sections.at(-1)!, { resource, category: 'web_ui', score: 0.3, matched: ['css'] })
  assert.ok(['L1', 'L2'].includes(plain.knowledge.evidence_level!))
  const mapped = summarizeUnit(unit, resource)
  assert.equal(mapped.topic, 'ui_quality')
  assert.equal((mapped.metadata.extraction as Record<string, string>).source_ref, resource.url)
})

test('设计相关度拒绝营销文案', () => {
  assert.equal(designRelevance('pricing contact sales sign up free trial customers trusted by', 3).relevant, false)
  assert.equal(designRelevance('布局 间距 对比度 响应式 组件', 3).relevant, true)
})
