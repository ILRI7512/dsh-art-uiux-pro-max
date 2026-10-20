import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { Registry, RegistryError, validateResource } from '../../src/domain/registry.ts'
import { cleanup, makeRoot, seedResource } from '../helpers.ts'

test('资源校验拒绝缺字段、非法类型与优先级', () => {
  const good = seedResource(); validateResource(good)
  const missing = { ...good }; delete (missing as Record<string, unknown>).license_notes
  assert.throws(() => validateResource(missing), RegistryError)
  assert.throws(() => validateResource({ ...good, resource_type: 'blog' }), RegistryError)
  assert.throws(() => validateResource({ ...good, learning_priority: 9 }), RegistryError)
})

test('种子只读，状态分离，合并后可见', () => {
  const root = makeRoot([seedResource()])
  try {
    const registry = new Registry(root, join(root, 'data'))
    assert.equal(registry.view()[0]?.learn_status, 'not_started')
    registry.recordCheck('unit-test', { accessStatus: 'reachable', httpStatus: 200 })
    registry.recordLearning('unit-test', { learnStatus: 'learned', chunks: 3 })
    const item = registry.get('unit-test')
    assert.equal(item?.access_status, 'reachable')
    assert.equal(item?.learn_status, 'learned')
    assert.equal(item?.learned_chunks, 3)
    const seed = JSON.parse(readFileSync(join(root, 'resources', 'seed.json'), 'utf8')) as { resources: Array<Record<string, unknown>> }
    assert.equal(seed.resources[0]?.access_status, 'unchecked')
    assert.equal(registry.stats().learned_chunks_total, 3)
  } finally { cleanup(root) }
})

test('状态非法时拒绝写入', () => {
  const root = makeRoot([seedResource()])
  try {
    const registry = new Registry(root, join(root, 'data'))
    assert.throws(() => registry.recordCheck('unit-test', { accessStatus: 'weird' as never }), RegistryError)
    assert.throws(() => registry.update('missing', { access_status: 'reachable' }), Error)
  } finally { cleanup(root) }
})
