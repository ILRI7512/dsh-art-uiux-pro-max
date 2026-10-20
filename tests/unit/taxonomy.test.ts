import assert from 'node:assert/strict'
import { test } from 'node:test'
import { CATEGORY_KEYS, EXTRACTION_FIELDS, describeTaxonomy, getCategory, validateAssignment, TaxonomyError } from '../../src/domain/taxonomy.ts'

test('12 个主分类且唯一', () => {
  assert.equal(CATEGORY_KEYS.length, 12)
  assert.equal(new Set(CATEGORY_KEYS).size, 12)
  assert.equal((describeTaxonomy() as { categories: unknown[] }).categories.length, 12)
})

test('分类校验拒绝同主/未知辅分类，并去重', () => {
  assert.deepEqual(validateAssignment('color_system', ['ui_quality', 'ui_quality']), ['ui_quality'])
  assert.throws(() => validateAssignment('color_system', ['color_system']), TaxonomyError)
  assert.throws(() => validateAssignment('nope'), TaxonomyError)
  assert.throws(() => validateAssignment('color_system', ['nope']), TaxonomyError)
})

test('16 个提取字段与最小集', () => {
  assert.equal(EXTRACTION_FIELDS.length, 16)
  assert.ok(EXTRACTION_FIELDS.includes('source_ref'))
  const category = getCategory('ui_quality')
  assert.equal(category.label, '可访问性与视觉质量审计')
  assert.ok(category.keywords.includes('wcag'))
})
