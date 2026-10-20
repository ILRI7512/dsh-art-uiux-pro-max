import { mkdtempSync, mkdirSync, writeFileSync, copyFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

export const REPO_ROOT = fileURLToPath(new URL('..', import.meta.url))

export function tempDir(prefix = 'art-uiux-test-'): string {
  return mkdtempSync(join(tmpdir(), prefix))
}

export function cleanup(dir: string): void {
  rmSync(dir, { recursive: true, force: true })
}

export function seedResource(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    resource_id: 'unit-test',
    name: 'Fixture Product',
    url: 'https://example.com/',
    resource_type: 'product_case',
    primary_category: 'web_ui',
    secondary_categories: ['visual_aesthetics'],
    platform: 'web',
    learning_objectives: ['测试'],
    access_status: 'unchecked',
    last_checked: '',
    last_learned: '',
    license_notes: '测试用',
    source_reliability: 'medium',
    learning_priority: 3,
    crawl_policy: 'public_landing_analysis',
    ...overrides,
  }
}

export function makeRoot(resources: Array<Record<string, unknown>>): string {
  const root = tempDir()
  mkdirSync(join(root, 'resources'), { recursive: true })
  writeFileSync(join(root, 'resources', 'seed.json'), `${JSON.stringify({ resources }, null, 2)}\n`, 'utf8')
  return root
}

export function copyQrels(root: string): void {
  mkdirSync(join(root, 'eval'), { recursive: true })
  copyFileSync(join(REPO_ROOT, 'eval', 'qrels.json'), join(root, 'eval', 'qrels.json'))
}

export const FIXTURE_HTML = `
<html><head><style>
:root{--bg:#0b0b0f;--fg:#e5e5e5}
.hero{background:linear-gradient(180deg,#0b0b0f,#1a1030);padding:48px;border-radius:12px;}
.card{border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,.4);padding:24px;gap:16px}
h1{font-family:Inter,sans-serif;font-size:56px}
@media (max-width:768px){.hero{padding:24px}}
</style></head>
<body>
<h1>Design for teams</h1>
<p>The interface should keep contrast high enough for reading. Use 16px body text and avoid pure white on dark backgrounds.</p>
<h2>Gradients</h2>
<p>A linear-gradient from #0b0b0f to #1a1030 gives depth. Never stack more than two gradients in one section.</p>
<img src="a.png" alt="preview">
<img src="b.png">
<div role="button" aria-label="open"></div>
</body></html>
`
