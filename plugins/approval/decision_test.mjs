/**
 * 审批判定自测（不启动 Harness）。
 * 风险清单从插件位置向上查找引擎目录，不依赖绝对路径。
 */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { decideApproval } from './index.js'

function findManifest() {
  let dir = dirname(fileURLToPath(import.meta.url))
  for (let depth = 0; depth < 8; depth += 1) {
    for (const name of ['dsh_autonomous_learning', 'engine']) {
      const candidate = join(dir, name, 'tool_risks.json')
      try {
        return JSON.parse(readFileSync(candidate, 'utf8')).tools
      } catch {
        /* keep looking */
      }
    }
    const parent = dirname(dir)
    if (parent === dir) break
    dir = parent
  }
  throw new Error('tool_risks.json not found; keep the plugin inside the repo or set DSH_AL_HOME')
}

const table = findManifest()
const base = {
  prefix: 'mcp__autolearn__',
  table,
  askRisks: ['execute', 'destructive'],
  askTools: ['update_knowledge'],
  allowTools: [],
}
const cases = [
  ['mcp__autolearn__run_code_test', { code: 'print(1)' }, true],
  ['mcp__autolearn__invalidate_knowledge', { chunk_id: 'chunk_abc' }, true],
  ['mcp__autolearn__update_knowledge', { chunk_id: 'chunk_abc' }, true],
  ['mcp__autolearn__save_knowledge', { project_id: 'prj_1' }, false],
  ['mcp__autolearn__search_knowledge', { query: '滑点' }, false],
  ['mcp__autolearn__get_runtime_info', {}, false],
  ['mcp__other__run_code_test', {}, false],
]

let ok = true
for (const [name, args, expectAsk] of cases) {
  const decision = decideApproval({ ...base, name, args })
  const asked = decision !== null
  const pass = asked === expectAsk
  ok = ok && pass
  console.log(pass ? 'PASS' : 'FAIL', name, 'asked=' + asked, asked ? '| ' + decision.reason : '')
}

const allowed = decideApproval({
  ...base,
  name: 'mcp__autolearn__run_code_test',
  args: {},
  allowTools: ['run_code_test'],
})
const allowPass = allowed === null
ok = ok && allowPass
console.log(allowPass ? 'PASS' : 'FAIL', 'allowTools override')

process.exit(ok ? 0 : 1)
