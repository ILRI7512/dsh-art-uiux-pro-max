/**
 * 自主学习审批闸门（Host-only Cordis 插件）。
 *
 * 作用：把 `mcp__autolearn__*` 里风险等级为 execute / destructive（以及显式列出的工具）
 * 的调用，在执行前交给 DSH 自己的审批 UI（`tools/pre-execute` 返回 `{ kind: 'ask' }`）。
 *
 * 为什么这样做：
 * - 审批是 user-only 动作：智能体没有可调用工具能给自己授权；
 * - 复用 DSH 既有审批弹窗与审计（ask/outcome 由宿主写入会话），不另造一套 UI；
 * - 用户拒绝时工具根本不会执行，Python 侧无需再判断一次。
 *
 * 判定数据来自 `tool_risks.json`（由 Python 端 `export-tool-risks` 生成），
 * 因此工具风险清单只维护一份，避免 UI 与引擎各写一套。
 */

import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const DEFAULT_PREFIX = 'mcp__autolearn__'

function safeExists(path) {
  try {
    return existsSync(path)
  } catch {
    return false
  }
}

/** 从插件位置向上找引擎目录（含 tool_risks.json），避免写死绝对路径。 */
function findEngineHome() {
  let dir = dirname(fileURLToPath(import.meta.url))
  for (let depth = 0; depth < 8; depth += 1) {
    for (const name of ['dsh_autonomous_learning', 'engine']) {
      const candidate = join(dir, name)
      if (safeExists(join(candidate, 'tool_risks.json'))) return candidate
    }
    const parent = dirname(dir)
    if (parent === dir) break
    dir = parent
  }
  return ''
}

const ENGINE_HOME = process.env.DSH_AL_HOME || findEngineHome()
const DEFAULT_MANIFEST = ENGINE_HOME ? join(ENGINE_HOME, 'tool_risks.json') : ''
const DEFAULT_HEARTBEAT = ENGINE_HOME ? join(ENGINE_HOME, 'data', 'host_approval.heartbeat') : ''
const DEFAULT_GATE_STATE = ENGINE_HOME ? join(ENGINE_HOME, 'data', 'host_approval.gate.json') : ''
const GATE_GENERATION = 2
const DEFAULT_ASK_RISKS = ['execute', 'destructive']

const RISK_LABEL = {
  read: '读取',
  write: '写入',
  execute: '执行代码/实验',
  external: '外部网络访问',
  destructive: '删除/失效/恢复',
}

const TARGET_KEYS = ['chunk_id', 'db_file', 'project_id', 'practice_id', 'location', 'path', 'topic']

function loadManifest(path, warn) {
  if (!path) {
    warn('未定位到引擎目录（tool_risks.json）；只按配置的 askTools 判定。可设置 DSH_AL_HOME 指定引擎目录。')
    return {}
  }
  try {
    const parsed = JSON.parse(readFileSync(path, 'utf8'))
    const tools = parsed && typeof parsed.tools === 'object' ? parsed.tools : {}
    return tools
  } catch (error) {
    warn(`审批清单读取失败（${path}）：${error instanceof Error ? error.message : String(error)}；将只按配置的 askTools 判定`)
    return {}
  }
}

function pickTarget(args) {
  if (!args || typeof args !== 'object') return ''
  for (const key of TARGET_KEYS) {
    const value = args[key]
    if (typeof value === 'string' && value.trim()) {
      return `${key}=${value.length > 64 ? value.slice(0, 64) + '…' : value}`
    }
  }
  return ''
}

function buildReason(shortName, risk, args) {
  const label = RISK_LABEL[risk] ?? (risk || '高风险')
  const target = pickTarget(args)
  const suffix = target ? `（${target}）` : ''
  return (
    `自主学习插件请求执行「${shortName}」：属于${label}操作${suffix}。` +
    '批准后仅执行本次调用；拒绝则不会改动知识库。'
  )
}

/**
 * 纯函数：给定工具名与参数，返回 null（放行）或 ask 决策。
 * 单独导出便于在 Node 里直接验证判定表，不必启动整个 Harness。
 */
export function decideApproval({
  name,
  args,
  prefix = DEFAULT_PREFIX,
  table = {},
  askRisks = DEFAULT_ASK_RISKS,
  askTools = [],
  allowTools = [],
} = {}) {
  if (typeof name !== 'string' || !name.startsWith(prefix)) return null
  const shortName = name.slice(prefix.length)
  if (allowTools.includes(shortName)) return null

  const spec = table[shortName] ?? {}
  const risk = typeof spec.risk === 'string' ? spec.risk : ''
  const mustAsk =
    askTools.includes(shortName) ||
    spec.requires_confirmation === true ||
    (risk !== '' && askRisks.includes(risk))
  if (!mustAsk) return null
  return { kind: 'ask', reason: buildReason(shortName, risk, args) }
}

export function apply(ctx, config = {}) {
  const prefix = typeof config.prefix === 'string' && config.prefix ? config.prefix : DEFAULT_PREFIX
  const manifestPath =
    typeof config.manifestPath === 'string' && config.manifestPath ? config.manifestPath : DEFAULT_MANIFEST
  const askRisks = Array.isArray(config.askRisks) ? config.askRisks : DEFAULT_ASK_RISKS
  const askTools = Array.isArray(config.askTools) ? config.askTools : []
  const allowTools = Array.isArray(config.allowTools) ? config.allowTools : []

  const warn = (message) => console.warn(`[autolearn-approval] ${message}`)
  const table = loadManifest(manifestPath, warn)
  const count = Object.keys(table).length
  console.log(
    `[autolearn-approval] active: prefix=${prefix} tools=${count} askRisks=${askRisks.join('/')} askTools=${askTools.length}`,
  )

  // 心跳：Python 端只有在心跳新鲜时才把高风险确认"外包"给宿主。
  // 插件被禁用或崩溃 → 心跳过期 → Python 自动退回本地确认流程（fail-closed）。
  const heartbeatPath =
    typeof config.heartbeatPath === 'string' && config.heartbeatPath ? config.heartbeatPath : DEFAULT_HEARTBEAT
  const beat = () => {
    if (!heartbeatPath) return
    try {
      mkdirSync(dirname(heartbeatPath), { recursive: true })
      writeFileSync(
        heartbeatPath,
        JSON.stringify({ pid: process.pid, ts: Date.now(), prefix, plugin: '@local/dsh-autolearn-approval' }),
        'utf8',
      )
    } catch (error) {
      warn(`心跳写入失败（${heartbeatPath}）：${error instanceof Error ? error.message : String(error)}`)
    }
  }
  beat()
  const heartbeatTimer = setInterval(beat, 30000)
  if (typeof heartbeatTimer.unref === 'function') heartbeatTimer.unref()

  // 代际标记：证明"这一代闸门会写心跳"。卸载时不删除它，
  // 这样 Python 端可以把"升级过、随后被禁用"识别为心跳缺失并 fail-closed。
  const gateStatePath =
    typeof config.gateStatePath === 'string' && config.gateStatePath ? config.gateStatePath : DEFAULT_GATE_STATE
  if (gateStatePath) {
    try {
      mkdirSync(dirname(gateStatePath), { recursive: true })
      writeFileSync(
        gateStatePath,
        JSON.stringify({
          generation: GATE_GENERATION,
          installedAt: new Date().toISOString(),
          prefix,
          plugin: '@local/dsh-autolearn-approval',
        }),
        'utf8',
      )
    } catch (error) {
      warn(`闸门标记写入失败（${gateStatePath}）：${error instanceof Error ? error.message : String(error)}`)
    }
  }

  const cleanupHeartbeat = () => {
    try {
      clearInterval(heartbeatTimer)
    } catch {
      /* ignore */
    }
    try {
      unlinkSync(heartbeatPath)
    } catch {
      /* 文件可能已被清理 */
    }
  }

  if (typeof ctx.on !== 'function') {
    warn('ctx.on 不可用：审批闸门未挂载')
    return cleanupHeartbeat
  }

  const listener = (exec, next) => {
    try {
      const decision = decideApproval({
        name: exec?.name,
        args: exec?.args,
        prefix,
        table,
        askRisks,
        askTools,
        allowTools,
      })
      if (decision) {
        console.log(`[autolearn-approval] ask tool=${exec?.name}`)
        return decision
      }
      return next()
    } catch (error) {
      // 闸门自身出错时放行，交由 Python 端的权限与审计兜底；
      // 不能因为 UI 插件的 bug 把正常学习流程全部卡死。
      warn(`判定失败，放行：${error instanceof Error ? error.message : String(error)}`)
      return next()
    }
  }

  const dispose = ctx.on('tools/pre-execute', listener)
  return () => {
    try {
      dispose?.()
    } catch {
      /* 已注销 */
    }
    cleanupHeartbeat()
  }
}
