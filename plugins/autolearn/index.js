/**
 * 自主学习插件的 Host 半边：提供设置卡的数据接口。
 *
 * 设置存放于 `<engine home>/data/settings.json`，与 Python 引擎共享：
 * - 模式（assisted / auto / lab）与每日预算在下一轮学习开始时生效（引擎每轮重读）；
 * - 数据目录变更需要重连 MCP 连接（数据库与索引在建连时打开）。
 *
 * 为什么用文件而不是插件 Config：这里的值要跨语言（Node 设置卡 ↔ Python 引擎）
 * 共享，文件是唯一不会出现两套真相的介质；卡片与引擎都只读写这一份。
 */

import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { dirname, join, isAbsolute } from 'node:path'
import { fileURLToPath } from 'node:url'

export const inject = ['webServer']

export const DEFAULTS = Object.freeze({
  mode: 'assisted',
  dataDir: '',
  dailyBudgetUsd: 1,
  maxTasksPerRun: 30,
})

const MODES = ['assisted', 'auto', 'lab']

/**
 * 从插件自身位置向上找引擎目录，避免任何绝对路径：
 * 命中 `<dir>/dsh_autonomous_learning/config.json` 或 `<dir>/engine/config.json`。
 */
function findEngineHome() {
  let dir = dirname(fileURLToPath(import.meta.url))
  for (let depth = 0; depth < 8; depth += 1) {
    for (const name of ['dsh_autonomous_learning', 'engine']) {
      const candidate = join(dir, name)
      try {
        if (existsSync(join(candidate, 'config.json'))) return candidate
      } catch {
        /* keep looking */
      }
    }
    const parent = dirname(dir)
    if (parent === dir) break
    dir = parent
  }
  return ''
}

/** 引擎根目录：环境变量 > 从插件位置向上查找。两者都没有时返回空串。 */
export function engineHome(env = process.env) {
  return env.DSH_AL_HOME || findEngineHome()
}

export function settingsPath(env = process.env) {
  if (env.DSH_AL_SETTINGS_FILE) return env.DSH_AL_SETTINGS_FILE
  const home = engineHome(env)
  if (!home) throw new Error('engine home not found; set DSH_AL_HOME or keep the plugin inside the repo')
  return join(home, 'data', 'settings.json')
}

export function defaultDataDir(env = process.env) {
  const home = engineHome(env)
  return home ? join(home, 'data') : ''
}

function normalize(raw) {
  const settings = { ...DEFAULTS }
  if (!raw || typeof raw !== 'object') return settings
  if (typeof raw.mode === 'string' && MODES.includes(raw.mode)) settings.mode = raw.mode
  if (typeof raw.dataDir === 'string') settings.dataDir = raw.dataDir.trim()
  const budget = Number(raw.dailyBudgetUsd)
  if (Number.isFinite(budget) && budget >= 0 && budget <= 1000) settings.dailyBudgetUsd = budget
  const tasks = Number(raw.maxTasksPerRun)
  if (Number.isFinite(tasks) && tasks >= 1 && tasks <= 200) settings.maxTasksPerRun = Math.trunc(tasks)
  return settings
}

export function readSettings(env = process.env) {
  const file = settingsPath(env)
  try {
    return normalize(JSON.parse(readFileSync(file, 'utf8')))
  } catch {
    return { ...DEFAULTS }
  }
}

/** 校验并落盘；返回 { settings } 或 { error }。 */
export function writeSettings(patch, env = process.env) {
  if (!patch || typeof patch !== 'object') return { error: 'settings payload must be an object' }
  if (patch.mode !== undefined && !MODES.includes(patch.mode)) {
    return { error: `mode must be one of ${MODES.join('/')}` }
  }
  if (patch.dailyBudgetUsd !== undefined) {
    const value = Number(patch.dailyBudgetUsd)
    if (!Number.isFinite(value) || value < 0 || value > 1000) {
      return { error: 'dailyBudgetUsd must be a number between 0 and 1000' }
    }
  }
  if (patch.maxTasksPerRun !== undefined) {
    const value = Number(patch.maxTasksPerRun)
    if (!Number.isFinite(value) || value < 1 || value > 200) {
      return { error: 'maxTasksPerRun must be an integer between 1 and 200' }
    }
  }
  if (patch.dataDir !== undefined) {
    const value = String(patch.dataDir ?? '').trim()
    if (value && !isAbsolute(value)) {
      return { error: 'dataDir must be an absolute path, or empty to use the default' }
    }
  }

  const next = normalize({ ...readSettings(env), ...patch })
  const file = settingsPath(env)
  try {
    mkdirSync(dirname(file), { recursive: true })
    const tmp = `${file}.tmp`
    writeFileSync(
      tmp,
      JSON.stringify({ ...next, updatedAt: new Date().toISOString(), revision: hashOf(next) }, null, 2),
      'utf8',
    )
    renameSync(tmp, file)
  } catch (error) {
    return { error: `failed to persist settings: ${error instanceof Error ? error.message : String(error)}` }
  }
  return { settings: next }
}

function hashOf(settings) {
  return createHash('sha256').update(JSON.stringify(settings)).digest('hex').slice(0, 16)
}

function send(res, status, body) {
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8' })
  res.end(JSON.stringify(body))
}

async function readBody(req, limit = 64 * 1024) {
  const chunks = []
  let total = 0
  for await (const chunk of req) {
    total += chunk.length
    if (total > limit) throw new Error('payload too large')
    chunks.push(chunk)
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'))
}

/** 设置卡的两个接口：GET 读当前值，POST 局部更新。 */
export function settingsRoute(env = process.env) {
  return {
    name: 'dsh-autolearn-settings',
    kind: 'exact',
    path: '/dsh-autolearn/api/settings',
    handler: async (req, res) => {
      if (req.method === 'GET') {
        const settings = readSettings(env)
        send(res, 200, {
          settings,
          defaults: { ...DEFAULTS },
          effectiveDataDir: settings.dataDir || defaultDataDir(env),
          modes: MODES,
          settingsPath: settingsPath(env),
          notes: {
            live: '模式与每日预算在下一轮学习开始时生效',
            reconnect: '数据目录变更需要重连 MCP 连接（数据库与索引在建连时打开）',
          },
        })
        return
      }
      if (req.method !== 'POST') {
        res.writeHead(405).end()
        return
      }
      try {
        const patch = await readBody(req)
        const result = writeSettings(patch, env)
        if (result.error) {
          send(res, 400, { error: result.error })
          return
        }
        send(res, 200, {
          settings: result.settings,
          effectiveDataDir: result.settings.dataDir || defaultDataDir(env),
          savedAt: new Date().toISOString(),
        })
      } catch (error) {
        send(res, 400, { error: error instanceof Error ? error.message : String(error) })
      }
    },
  }
}

export function apply(ctx, config = {}) {
  const env = { ...process.env, ...(config.env ?? {}) }
  let target = ''
  try {
    target = settingsPath(env)
  } catch (error) {
    console.warn(`[dsh-autolearn] ${error instanceof Error ? error.message : String(error)}`)
    return
  }
  try {
    if (!existsSync(target)) {
      writeSettings({}, env)
    }
  } catch (error) {
    console.warn(`[dsh-autolearn] settings bootstrap failed: ${error}`)
  }
  if (!ctx?.webServer || typeof ctx.webServer.register !== 'function') {
    console.warn('[dsh-autolearn] webServer unavailable; settings card API disabled')
    return
  }
  ctx.effect(() => ctx.webServer.register(settingsRoute(env)), 'dsh-autolearn: settings route')
  console.log(`[dsh-autolearn] settings API ready: ${target}`)
}
