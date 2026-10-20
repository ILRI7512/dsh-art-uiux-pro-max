/**
 * 体检：扫描某个 dsh profile 里所有 client bundle，验证它们符合「经典脚本」契约。
 *
 * 背景见 docs/FIX-2026-10-20-desktop-profile-web-boot.md：client bundle 被
 * <script> 直接执行，只允许调用 window.__ModuleLoader__.load({ id, factory })；
 * 任何 ESM 语法（尤其是 tsc 补在末尾的 `export {};`）都会让浏览器抛
 * SyntaxError，进而让整个 web boot 以 "entry did not activate" 失败。
 *
 * 用法：
 *   node scripts/check-client-bundles.mjs [profileDir]
 *   node scripts/check-client-bundles.mjs ~/.dsh/profiles/desktop
 *
 * 退出码：0 = 全部合格；1 = 存在不合格或缺失的 bundle。
 */
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { homedir } from 'node:os'

const profileDir = process.argv[2] ?? join(homedir(), '.dsh', 'profiles', 'desktop')
const require_ = createRequire(join(profileDir, 'package.json'))
const pkg = JSON.parse(readFileSync(join(profileDir, 'package.json'), 'utf8'))

const names = new Set()
for (const key of Object.keys(pkg.dependencies ?? {})) names.add(key)
for (const key of pkg.dsh?.profile?.bundles ?? []) names.add(key)
for (const key of pkg.dsh?.desktopNextDeselectedBundles ?? []) names.add(key)

const rows = []
for (const name of [...names].sort()) {
  let pkgJsonPath
  try { pkgJsonPath = require_.resolve(`${name}/package.json`) } catch { continue }
  const manifest = JSON.parse(readFileSync(pkgJsonPath, 'utf8'))
  if (!manifest.dsh?.client) continue
  let entry
  try {
    entry = require_.resolve(`${name}/client`)
  } catch {
    entry = join(dirname(pkgJsonPath), manifest.dsh.client.entry ?? 'dist/client/index.js')
  }
  let text
  try {
    text = readFileSync(entry, 'utf8')
  } catch (error) {
    rows.push({ name, entry, status: `MISSING (${error.code})` })
    continue
  }
  let parse = 'ok'
  try { new Function(text) } catch (error) { parse = `FAIL: ${error.message}` }
  const registers = text.includes('__ModuleLoader__.load(')
  // 仅供参考：高亮器里的关键字数组也会让行首出现 import/export，
  // 权威判定是上面的经典脚本解析。
  const esmKeywordLines = /(^|\n)[ \t]*(export|import)[ \t]/u.test(text)
  rows.push({ name, entry, status: parse, registers, esmKeywordLines })
}

console.log(`profile: ${profileDir}`)
for (const row of rows) {
  const ok = row.status === 'ok' && row.registers
  console.log(`${ok ? 'PASS' : 'FAIL'}\t${row.name}\t${row.status}\tregisters=${row.registers}\tesmKeywordLines=${row.esmKeywordLines}`)
}
const broken = rows.filter((row) => !(row.status === 'ok' && row.registers))
console.log(`\n${rows.length} client bundles, ${broken.length} broken`)
if (broken.length > 0) process.exitCode = 1
