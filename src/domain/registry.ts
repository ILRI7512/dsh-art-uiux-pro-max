/**
 * 资源注册表：15 字段校验 + 运行期状态持久化。
 *
 * 关键不变量：
 * - resources/seed.json 只读，不含“已学习”的谎报；
 * - 运行期状态写入 <dataDir>/registry.json，与种子合并后才是对外视图；
 * - access_status / learn_status / learned_chunks 是三个独立事实，不能互相替代。
 */
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { ValidationError, NotFoundError } from '../core/errors.ts'
import { nowIso } from '../core/ids.ts'
import type { AccessStatus, LearnStatus, Resource, ResourceView } from '../core/types.ts'
import { CATEGORY_KEYS, getCategory } from './taxonomy.ts'

export const RESOURCE_TYPES = new Set([
  'official_documentation', 'github_repository', 'design_system', 'product_case',
  'design_gallery', 'technical_tutorial', 'accessibility_standard', 'visual_reference',
])
export const ACCESS_STATUS = new Set<AccessStatus>(['unchecked', 'reachable', 'restricted', 'blocked', 'failed'])
export const LEARN_STATUS = new Set<LearnStatus>(['not_started', 'partial', 'learned', 'failed'])
export const CRAWL_POLICIES = new Set([
  'docs_public_pages', 'readme_source_tests_license', 'public_landing_analysis', 'visual_reference_only',
])
export const RELIABILITY = new Set(['high', 'medium', 'low', 'unknown'])

export const REQUIRED_FIELDS = [
  'resource_id', 'name', 'url', 'resource_type', 'primary_category', 'secondary_categories',
  'platform', 'learning_objectives', 'access_status', 'last_checked', 'last_learned',
  'license_notes', 'source_reliability', 'learning_priority', 'crawl_policy',
] as const

export class RegistryError extends ValidationError {
  constructor(message: string) {
    super(message)
    this.name = 'RegistryError'
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function validateResource(raw: unknown): asserts raw is Resource {
  if (!isRecord(raw)) throw new RegistryError('资源必须是对象')
  const missing = REQUIRED_FIELDS.filter((field) => !(field in raw))
  if (missing.length > 0) throw new RegistryError(`${String(raw.resource_id ?? '?')} 缺少字段: ${missing.join(', ')}`)
  const rid = raw.resource_id
  if (typeof rid !== 'string' || !rid.trim()) throw new RegistryError('resource_id 必须是非空字符串')
  if (typeof raw.resource_type !== 'string' || !RESOURCE_TYPES.has(raw.resource_type)) {
    throw new RegistryError(`${rid} 的 resource_type 非法: ${String(raw.resource_type)}`)
  }
  if (typeof raw.primary_category !== 'string' || !CATEGORY_KEYS.includes(raw.primary_category)) {
    throw new RegistryError(`${rid} 的 primary_category 非法: ${String(raw.primary_category)}`)
  }
  const secondary = raw.secondary_categories ?? []
  if (!Array.isArray(secondary)) throw new RegistryError(`${rid} 的 secondary_categories 必须是数组`)
  for (const key of secondary) {
    if (key === raw.primary_category) throw new RegistryError(`${rid} 的辅助分类不能等于主分类`)
    if (typeof key !== 'string') throw new RegistryError(`${rid} 的辅助分类必须是字符串`)
    getCategory(key)
  }
  if (typeof raw.access_status !== 'string' || !ACCESS_STATUS.has(raw.access_status as AccessStatus)) {
    throw new RegistryError(`${rid} 的 access_status 非法: ${String(raw.access_status)}`)
  }
  if (typeof raw.source_reliability !== 'string' || !RELIABILITY.has(raw.source_reliability)) {
    throw new RegistryError(`${rid} 的 source_reliability 非法: ${String(raw.source_reliability)}`)
  }
  if (typeof raw.crawl_policy !== 'string' || !CRAWL_POLICIES.has(raw.crawl_policy)) {
    throw new RegistryError(`${rid} 的 crawl_policy 非法: ${String(raw.crawl_policy)}`)
  }
  if (!Number.isInteger(raw.learning_priority) || (raw.learning_priority as number) < 1 || (raw.learning_priority as number) > 5) {
    throw new RegistryError(`${rid} 的 learning_priority 必须是 1-5 的整数`)
  }
  if (!Array.isArray(raw.learning_objectives) || raw.learning_objectives.length === 0) {
    throw new RegistryError(`${rid} 必须有至少一条 learning_objectives`)
  }
}

export interface RegistryStats {
  total: number
  access_status: Record<string, number>
  learn_status: Record<string, number>
  by_primary_category: Record<string, number>
  learned_chunks_total: number
}

export class Registry {
  readonly root: string
  readonly dataDir: string

  constructor(root: string, dataDir = join(root, 'data')) {
    this.root = root
    this.dataDir = dataDir
  }

  get seedPath(): string {
    const preferred = join(this.root, 'resources', 'seed.json')
    if (existsSync(preferred)) return preferred
    return join(this.root, 'art_uiux', 'resources.seed.json')
  }

  get statePath(): string { return join(this.dataDir, 'registry.json') }
  get legacyStatePath(): string { return join(this.root, 'dsh_autonomous_learning', 'data', 'registry.json') }

  seed(): Resource[] {
    const parsed: unknown = JSON.parse(readFileSync(this.seedPath, 'utf8'))
    const items = Array.isArray(parsed) ? parsed : isRecord(parsed) && Array.isArray(parsed.resources) ? parsed.resources : null
    if (!items) throw new RegistryError('种子文件必须是资源数组，或 { resources: [...] }')
    for (const item of items) validateResource(item)
    return items as Resource[]
  }

  state(): { version: number; resources: Record<string, Record<string, unknown>> } {
    const file = existsSync(this.statePath) ? this.statePath : existsSync(this.legacyStatePath) ? this.legacyStatePath : ''
    if (!file) return { version: 1, resources: {} }
    try {
      const parsed: unknown = JSON.parse(readFileSync(file, 'utf8'))
      if (!isRecord(parsed) || !isRecord(parsed.resources)) return { version: 1, resources: {} }
      return { version: Number(parsed.version ?? 1), resources: parsed.resources as Record<string, Record<string, unknown>> }
    } catch {
      return { version: 1, resources: {} }
    }
  }

  saveState(state: { version: number; resources: Record<string, Record<string, unknown>> }): void {
    mkdirSync(dirname(this.statePath), { recursive: true })
    const tmp = `${this.statePath}.tmp`
    writeFileSync(tmp, `${JSON.stringify(state, null, 2)}\n`, 'utf8')
    renameSync(tmp, this.statePath)
  }

  /** 种子 + 运行期状态合并；运行期字段只覆盖同名键，不污染种子文件。 */
  view(): ResourceView[] {
    const state = this.state().resources
    return this.seed().map((res) => {
      const item = {
        ...res,
        learn_status: 'not_started' as LearnStatus,
        learned_chunks: 0,
        learn_notes: '',
        last_error: '',
        ...(state[res.resource_id] ?? {}),
      }
      return item as ResourceView
    })
  }

  get(resourceId: string): ResourceView | null {
    return this.view().find((item) => item.resource_id === resourceId) ?? null
  }

  select(options: { categories?: readonly string[]; types?: readonly string[]; platform?: string; maxPriority?: number } = {}): ResourceView[] {
    const categories = new Set(options.categories ?? [])
    const types = new Set(options.types ?? [])
    return this.view().filter((item) => {
      if (categories.size > 0 && !categories.has(item.primary_category)) return false
      if (types.size > 0 && !types.has(item.resource_type)) return false
      if (options.platform && item.platform !== options.platform) return false
      if (options.maxPriority !== undefined && item.learning_priority > options.maxPriority) return false
      return true
    })
  }

  update(resourceId: string, fields: Record<string, unknown>): Record<string, unknown> {
    const known = new Set(this.seed().map((item) => item.resource_id))
    if (!known.has(resourceId)) throw new NotFoundError(`未知 resource_id: ${resourceId}`)
    if ('access_status' in fields && !ACCESS_STATUS.has(fields.access_status as AccessStatus)) {
      throw new RegistryError(`access_status 非法: ${String(fields.access_status)}`)
    }
    if ('learn_status' in fields && !LEARN_STATUS.has(fields.learn_status as LearnStatus)) {
      throw new RegistryError(`learn_status 非法: ${String(fields.learn_status)}`)
    }
    if ('learned_chunks' in fields) {
      const chunks = Number(fields.learned_chunks)
      if (!Number.isInteger(chunks) || chunks < 0) throw new RegistryError('learned_chunks 必须是非负整数')
    }
    const state = this.state()
    const bucket = { ...(state.resources[resourceId] ?? {}), ...fields, updated_at: nowIso() }
    state.resources[resourceId] = bucket
    this.saveState(state)
    return bucket
  }

  recordCheck(resourceId: string, input: {
    accessStatus: AccessStatus
    httpStatus?: number | null
    finalUrl?: string
    contentType?: string
    bytesRead?: number
    robotsAllowed?: boolean | null
    error?: string
  }): Record<string, unknown> {
    return this.update(resourceId, {
      access_status: input.accessStatus,
      last_checked: nowIso(),
      last_http_status: input.httpStatus ?? null,
      last_final_url: input.finalUrl ?? '',
      last_content_type: input.contentType ?? '',
      last_bytes: input.bytesRead ?? 0,
      robots_allowed: input.robotsAllowed ?? null,
      last_error: input.error ?? '',
    })
  }

  recordLearning(resourceId: string, input: {
    learnStatus: LearnStatus
    chunks?: number
    notes?: string
    error?: string
  }): Record<string, unknown> {
    return this.update(resourceId, {
      learn_status: input.learnStatus,
      learned_chunks: input.chunks ?? 0,
      learn_notes: input.notes ?? '',
      last_error: input.error ?? '',
      last_learned: input.learnStatus === 'partial' || input.learnStatus === 'learned' ? nowIso() : '',
    })
  }

  stats(): RegistryStats {
    const items = this.view()
    const byAccess: Record<string, number> = {}
    const byLearn: Record<string, number> = {}
    const byCategory: Record<string, number> = {}
    let learned = 0
    for (const item of items) {
      byAccess[item.access_status] = (byAccess[item.access_status] ?? 0) + 1
      byLearn[item.learn_status] = (byLearn[item.learn_status] ?? 0) + 1
      byCategory[item.primary_category] = (byCategory[item.primary_category] ?? 0) + 1
      learned += Number(item.learned_chunks ?? 0)
    }
    return {
      total: items.length,
      access_status: byAccess,
      learn_status: byLearn,
      by_primary_category: byCategory,
      learned_chunks_total: learned,
    }
  }
}
