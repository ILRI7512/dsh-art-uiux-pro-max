import assert from 'node:assert/strict'
import { test } from 'node:test'
import { analyzeRepository, categorize, comparisons, parseComponentSource } from '../../src/domain/components.ts'

function fakeRepo(archived = false, license = 'MIT') {
  return {
    meta: { full_name: 'demo/ui', license: { spdx_id: license }, archived, stargazers_count: 1234, pushed_at: '2025-06-01T00:00:00Z', language: 'TypeScript', default_branch: 'main' },
    readme: '# Demo UI\nA component library.',
    paths: [
      'packages/ui/src/components/button/Button.tsx',
      'packages/ui/src/components/dialog/Dialog.tsx',
      'packages/ui/src/components/table/Table.tsx',
      'packages/ui/src/components/__tests__/button.test.tsx',
      'apps/docs/examples/button.md',
    ],
  }
}

test('组件分类覆盖八组', () => {
  assert.equal(categorize('Button'), 'basic')
  assert.equal(categorize('BottomSheet'), 'overlay')
  assert.equal(categorize('StatCard'), 'data')
  assert.equal(categorize('RichTextEditor'), 'advanced')
  assert.equal(categorize('UnknownThing'), 'unknown')
})

test('知识等级按真实证据授予', () => {
  const { meta, readme, paths } = fakeRepo()
  const info = analyzeRepository(meta, readme, paths, { platform: 'web', sourceKey: 'demo' })
  assert.equal(info.license, 'MIT')
  assert.equal(info.knowledge_level, 'L2')
  assert.ok(info.test_files >= 1)
  assert.ok('basic' in info.components_by_category)
  const info2 = analyzeRepository({ ...meta, license: { spdx_id: 'Apache-2.0' } }, readme, paths.slice(0, 2), { platform: 'android', sourceKey: 'demo2' })
  assert.equal(info2.knowledge_level, 'L1')
  assert.equal(info2.license, 'Apache-2.0')
})

test('归档仓库体现为局限', () => {
  const { meta, readme, paths } = fakeRepo(true)
  const info = analyzeRepository(meta, readme, paths, { platform: 'web', sourceKey: 'demo' })
  assert.ok(info.limitations.includes('归档'))
})

test('比较表不含质量裁决', () => {
  const first = analyzeRepository(...Object.values(fakeRepo()) as [Record<string, unknown>, string, string[]], { platform: 'web', sourceKey: 'a' })
  const rows = comparisons([first])
  assert.ok(rows[0] && ['license', 'framework', 'components', 'tests'].every((key) => key in rows[0]!))
  assert.ok(!['best', 'score', 'winner'].some((key) => key in (rows[0] ?? {})))
})

test('源码只读抽取，未运行不越级', () => {
  const knowledge = parseComponentSource('Button', 'type Props = { variant?: "a" | "b" }\n  disabled?: boolean\n  onClick?: () => void\naria-label role="button"', { repo: 'demo', path: 'Button.tsx', license: 'MIT', testFiles: 0 })
  assert.deepEqual(knowledge.parameters, ['disabled', 'onClick'])
  assert.equal(knowledge.knowledge_level, 'L2')
  assert.ok(knowledge.accessibility.includes('aria-label'))
})
