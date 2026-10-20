import assert from 'node:assert/strict'
import { test } from 'node:test'
import { expand } from '../../src/domain/bilingual.ts'

test('中文查询补充英文术语，英文原样返回', () => {
  const first = expand('深色模式下的对比度怎么控制')
  assert.ok(first.query.includes('contrast ratio'))
  assert.ok(first.query.includes('dark mode'))
  assert.ok(first.hits.length >= 2)
  const second = expand('contrast ratio for dark mode')
  assert.equal(second.query, 'contrast ratio for dark mode')
  assert.deepEqual(second.hits, [])
})
