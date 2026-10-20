import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { DEFAULTS, effectiveDataDir, readSettings, settingsPath, writeSettings } from '../../src/core/settings.ts'
import { cleanup, tempDir } from '../helpers.ts'

test('默认值与落盘后可回读', () => {
  const root = tempDir()
  try {
    assert.deepEqual(readSettings(root), { ...DEFAULTS })
    const result = writeSettings(root, { allowNetwork: false, maxUnits: 12, rerank: 'ce' })
    assert.equal(result.error, undefined)
    assert.equal(result.settings?.allowNetwork, false)
    const readBack = readSettings(root)
    assert.equal(readBack.maxUnits, 12)
    assert.equal(readBack.rerank, 'ce')
    const raw = JSON.parse(readFileSync(settingsPath(root), 'utf8')) as Record<string, unknown>
    assert.ok(raw.updatedAt && raw.revision)
    assert.equal(effectiveDataDir(root, readBack), join(root, 'data'))
  } finally { cleanup(root) }
})

test('非法值被拒绝且不落盘', () => {
  const root = tempDir()
  try {
    assert.ok(writeSettings(root, { dataDir: 'relative/path' }).error)
    assert.ok(writeSettings(root, { maxUnits: 0 }).error)
    assert.ok(writeSettings(root, { rerank: 'nope' }).error)
    assert.ok(writeSettings(root, { allowNetwork: 'yes' }).error)
    assert.deepEqual(readSettings(root), { ...DEFAULTS })
  } finally { cleanup(root) }
})

test('绝对数据目录生效', () => {
  const root = tempDir()
  try {
    const result = writeSettings(root, { dataDir: '/tmp/art-data' })
    assert.equal(result.settings?.dataDir, '/tmp/art-data')
    assert.equal(effectiveDataDir(root, result.settings!), '/tmp/art-data')
  } finally { cleanup(root) }
})
