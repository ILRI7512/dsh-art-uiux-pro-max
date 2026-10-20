import assert from 'node:assert/strict'
import { test } from 'node:test'
import { join } from 'node:path'
import { KnowledgeStore } from '../../src/infra/store.ts'
import { cleanup, tempDir } from '../helpers.ts'
import type { ChunkInput } from '../../src/core/types.ts'

function chunk(overrides: Partial<ChunkInput> = {}): ChunkInput {
  return {
    chunk_id: 'c_test',
    project_id: 'prj_art_uiux',
    partition: 'uiux_knowledge',
    topic: 'color_system',
    title: '对比度底线',
    content: '正文与背景对比度建议不低于 4.5:1，用于可读性判断。',
    summary: '对比度 4.5:1',
    level: 'L2',
    source_url: 'https://example.com/a',
    source_title: 'A',
    verification_status: 'unverified',
    confidence: 0.4,
    ...overrides,
  }
}

test('入库后可混合检索，结果带来源、等级与未核验告警', () => {
  const dir = tempDir()
  const store = new KnowledgeStore(join(dir, 'k.sqlite3'))
  try {
    store.ensureProject('prj_art_uiux')
    const result = store.addChunks([chunk()])
    assert.equal(result.added, 1)
    const found = store.search('对比度 可读性', { topK: 3, filters: { projectId: 'prj_art_uiux' } })
    assert.ok(found.hits.length > 0)
    assert.equal(found.hits[0]?.source.url, 'https://example.com/a')
    assert.equal(found.hits[0]?.level, 'L2')
    assert.ok(found.hits[0]?.warnings.some((warning) => warning.includes('unverified')))
    assert.equal(store.stats().chunks, 1)
    assert.deepEqual(store.checkIntegrity(), { missing_tokens: [], missing_vectors: [] })
  } finally { store.close(); cleanup(dir) }
})

test('同项目同内容去重，不同项目不误杀', () => {
  const dir = tempDir()
  const store = new KnowledgeStore(join(dir, 'k.sqlite3'))
  try {
    store.ensureProject('prj_art_uiux')
    store.addChunks([chunk()])
    const duplicate = store.addChunks([chunk({ chunk_id: 'c_dup' })])
    assert.equal(duplicate.added, 0)
    assert.equal(duplicate.duplicates.length, 1)
    const other = store.addChunks([chunk({ chunk_id: 'c_other', project_id: 'prj_other' })])
    assert.equal(other.added, 1)
  } finally { store.close(); cleanup(dir) }
})

test('更新标题会重建倒排与向量', () => {
  const dir = tempDir()
  const store = new KnowledgeStore(join(dir, 'k.sqlite3'))
  try {
    store.ensureProject('prj_art_uiux')
    store.addChunks([chunk()])
    store.addChunks([chunk({ title: 'Typography scale', content: 'Use a 5 step type scale for hierarchy.', topic: 'visual_aesthetics' })])
    const found = store.search('typography hierarchy', { topK: 3, filters: { projectId: 'prj_art_uiux' } })
    assert.ok(found.hits.some((hit) => hit.title === 'Typography scale'))
    assert.equal(store.stats().topics.visual_aesthetics, 1)
  } finally { store.close(); cleanup(dir) }
})

test('按分类与等级过滤不会跨范围', () => {
  const dir = tempDir()
  const store = new KnowledgeStore(join(dir, 'k.sqlite3'))
  try {
    store.ensureProject('prj_art_uiux')
    store.addChunks([chunk(), chunk({ chunk_id: 'c2', topic: 'web_ui', level: 'L1', content: 'CSS grid layout with responsive breakpoints.' })])
    const found = store.search('layout', { topK: 5, filters: { projectId: 'prj_art_uiux', topics: ['web_ui'], levels: ['L1'] } })
    assert.ok(found.hits.length > 0)
    assert.ok(found.hits.every((hit) => hit.topic === 'web_ui' && hit.level === 'L1'))
  } finally { store.close(); cleanup(dir) }
})
