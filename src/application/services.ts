/**
 * 应用服务：CLI、13 个原生 DSH 工具与 MCP 适配层共用同一份业务逻辑。
 * 任何“未验证”结论都在返回值里带 warnings，不靠调用方自觉。
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { ArtError, ERROR_CODES, NotFoundError, ValidationError, asError } from '../core/errors.ts'
import { sha1Hex, shortId } from '../core/ids.ts'
import type { ChunkInput, Resource, ResourceView, SearchFilters } from '../core/types.ts'
import { DEFAULTS, effectiveDataDir, readSettings, writeSettings } from '../core/settings.ts'
import type { ArtSettings, SettingsWriteResult } from '../core/settings.ts'
import { resolveArtRoot } from '../core/paths.ts'
import { Registry } from '../domain/registry.ts'
import { buildUnit, classifyWithPrior, summarizeUnit, type KnowledgeUnit } from '../domain/extract.ts'
import { analyzeHtml, compareWithExisting, numericRules, unitsFromCase } from '../domain/case-analyzer.ts'
import { sectionize } from '../infra/html.ts'
import { KnowledgeStore } from '../infra/store.ts'
import { HttpClient, NetworkBlockedError, assertSafeHttpUrl } from '../infra/http.ts'
import { retrieve, type RetrieveOptions, type RetrieveResult } from '../domain/retrieval.ts'
import {
  buildDesignSystem, proposeDirections, routeTask, tokensToCss, auditHtml, feedbackUnit,
  TASK_TYPES, type DesignSystem,
} from '../domain/design-workflow.ts'
import { generateBackgrounds, responsiveMatrix } from '../domain/tasks-special.ts'
import { describeTaxonomy } from '../domain/taxonomy.ts'
import {
  COMPONENT_SOURCES, analyzeRepository, comparisons, parseComponentSource,
  type RepositoryInfo, type ComponentSource,
} from '../domain/components.ts'
import { bootstrapDiff, mean, mrrAtK, ndcgAtK, precisionAtK, recallAtK, categoryPurity } from '../domain/metrics.ts'
import { rankedIds } from '../domain/retrieval.ts'

export interface ArtServicesOptions {
  root?: string
  dataDir?: string
  settings?: Partial<ArtSettings>
}

export interface LearnResult {
  resource_id: string
  access_status: string
  sections: number
  units: number
  ingested: number
  duplicates: number
  skipped: number
  warnings: string[]
}

export interface CaseResult {
  resource_id: string
  case: string
  url: string
  tech_stack: string[]
  sections: Record<string, number>
  metrics: Record<string, unknown>
  units: number
  ingested: number
  duplicates: number
  conflicts: Array<Record<string, unknown>>
  report: Record<string, unknown>
  warnings: string[]
}

const SOURCE_TYPE_MAP: Record<string, string> = {
  official_documentation: 'official_doc',
  github_repository: 'code_repo',
  design_system: 'tech_doc',
  product_case: 'web_page',
  design_gallery: 'web_page',
  technical_tutorial: 'tech_doc',
  accessibility_standard: 'standard',
  visual_reference: 'web_page',
}

const QUALITY: Record<string, number> = { high: 0.85, medium: 0.6, low: 0.35 }

function clampMaxUnits(value: unknown, fallback: number): number {
  const number = Number(value)
  if (!Number.isFinite(number)) return fallback
  return Math.max(1, Math.min(100, Math.trunc(number)))
}

export class ArtServices {
  readonly root: string
  registry: Registry
  private settingsValue: ArtSettings
  private storeValue: KnowledgeStore | null = null
  private storeDataDir = ''

  constructor(options: ArtServicesOptions = {}) {
    this.root = options.root ?? resolveArtRoot()
    this.settingsValue = { ...DEFAULTS, ...readSettings(this.root), ...(options.settings ?? {}) }
    if (options.dataDir) this.settingsValue.dataDir = options.dataDir
    this.registry = new Registry(this.root, effectiveDataDir(this.root, this.settingsValue))
  }

  get settings(): ArtSettings { return { ...this.settingsValue } }
  get dataDir(): string { return effectiveDataDir(this.root, this.settingsValue) }
  get dbPath(): string { return join(this.dataDir, 'knowledge.sqlite3') }

  get store(): KnowledgeStore {
    if (this.storeValue && this.storeDataDir === this.dataDir) return this.storeValue
    this.storeValue?.close()
    this.storeValue = new KnowledgeStore(this.dbPath)
    this.storeDataDir = this.dataDir
    this.storeValue.ensureProject('prj_art_uiux', {
      title: 'DSH Art UI/UX Pro Max',
      goal: '建立 UI/UX 设计知识的可持续学习、可检索、可验证体系',
      domain: 'uiux',
    })
    return this.storeValue
  }

  close(): void {
    this.storeValue?.close()
    this.storeValue = null
  }

  updateSettings(patch: unknown): SettingsWriteResult {
    const before = this.dataDir
    const result = writeSettings(this.root, patch)
    if (result.settings) {
      this.settingsValue = result.settings
      if (this.dataDir !== before) {
        this.storeValue?.close()
        this.storeValue = null
        this.registry = new Registry(this.root, this.dataDir)
      }
    }
    return result
  }

  private client(minInterval = 800): HttpClient {
    if (!this.settingsValue.allowNetwork) throw new NetworkBlockedError('网络访问已在设置中关闭（allowNetwork=false）')
    return new HttpClient({
      allowPrivateNetworks: this.settingsValue.allowPrivateNetworks,
      minHostIntervalMs: minInterval,
    })
  }

  // ---------------------------------------------------------------- 注册表 / 学习

  taxonomy(): Record<string, unknown> { return describeTaxonomy() }

  registryList(input: { category?: string; type?: string; accessStatus?: string; limit?: number } = {}): Record<string, unknown> {
    let items = this.registry.view()
    if (input.category) items = items.filter((item) => item.primary_category === input.category)
    if (input.type) items = items.filter((item) => item.resource_type === input.type)
    if (input.accessStatus) items = items.filter((item) => item.access_status === input.accessStatus)
    const limit = Math.max(1, Math.min(500, Number(input.limit ?? 50)))
    return { total: items.length, resources: items.slice(0, limit), stats: this.registry.stats() }
  }

  async registryCheck(input: { resourceId?: string; resourceIds?: string[]; limit?: number; concurrency?: number; minIntervalMs?: number } = {}): Promise<Record<string, unknown>> {
    const all = this.registry.view()
    const ids = input.resourceIds && input.resourceIds.length > 0 ? input.resourceIds : input.resourceId ? [input.resourceId] : []
    let items = ids.length > 0 ? all.filter((item) => ids.includes(item.resource_id)) : all
    if (ids.length > 0 && items.length === 0) throw new NotFoundError(`未知 resource_id: ${ids.join(', ')}`)
    if (input.limit) items = items.slice(0, Math.max(1, input.limit))
    const client = this.client(input.minIntervalMs ?? 800)
    const results: Array<Record<string, unknown>> = []
    for (const item of items) {
      const probe = await client.probe(item.url)
      this.registry.recordCheck(item.resource_id, {
        accessStatus: probe.access_status,
        httpStatus: probe.http_status ?? null,
        finalUrl: probe.final_url,
        contentType: probe.content_type,
        bytesRead: probe.bytes_read,
        robotsAllowed: probe.robots_allowed,
        error: probe.error,
      })
      results.push({ resource_id: item.resource_id, status: probe.access_status, http: probe.http_status ?? null, robots: probe.robots_allowed, error: probe.error })
    }
    return { checked: results.length, results, stats: this.registry.stats() }
  }

  private chunkFromUnit(unit: KnowledgeUnit, resource: Resource, input: { documentId: string; sourceType: string }): ChunkInput {
    const mapped = summarizeUnit(unit, resource)
    return {
      chunk_id: shortId('chunk', `${resource.resource_id}:${unit.content_hash}`),
      project_id: 'prj_art_uiux',
      document_id: input.documentId,
      partition: unit.level === 'L2' ? 'uiux_knowledge' : 'pending_knowledge',
      domain: 'uiux',
      topic: mapped.topic,
      subtopic: mapped.subtopic,
      title: mapped.title,
      content: mapped.content,
      summary: mapped.summary,
      knowledge_type: 'best_practice',
      level: unit.level,
      source_id: shortId('src', resource.resource_id),
      source_url: resource.url,
      source_title: resource.name,
      source_type: input.sourceType,
      author_or_publisher: resource.name,
      language: 'en',
      content_hash: unit.content_hash,
      source_quality: QUALITY[resource.source_reliability] ?? 0.5,
      confidence: 0.35,
      confidence_basis: '规则提取，未经交叉验证或任务验证',
      verification_status: 'unverified',
      freshness_status: 'unknown',
      license_status: 'unknown',
      visibility: 'project',
      metadata: { ...mapped.metadata, classification_source: 'domain_prior' },
    }
  }

  /** 抓取一个资源并正式写入知识库；不是“预览后假装已学”。 */
  async learn(input: { resourceId: string; maxUnits?: number; minIntervalMs?: number }): Promise<LearnResult> {
    const resource = this.registry.get(input.resourceId)
    if (!resource) throw new NotFoundError(`未知 resource_id: ${input.resourceId}`)
    const maxUnits = clampMaxUnits(input.maxUnits, this.settingsValue.maxUnits)
    const client = this.client(input.minIntervalMs ?? 800)
    const probe = await client.probe(resource.url)
    if (probe.access_status !== 'reachable') {
      this.registry.recordCheck(resource.resource_id, {
        accessStatus: probe.access_status, httpStatus: probe.http_status ?? null, finalUrl: probe.final_url,
        contentType: probe.content_type, bytesRead: probe.bytes_read, robotsAllowed: probe.robots_allowed, error: probe.error,
      })
      return { resource_id: resource.resource_id, access_status: probe.access_status, sections: 0, units: 0, ingested: 0, duplicates: 0, skipped: 0, warnings: [`access=${probe.access_status}: ${probe.error}`] }
    }
    let fetched
    try {
      fetched = await client.fetchHtml(resource.url)
    } catch (error) {
      this.registry.recordLearning(resource.resource_id, { learnStatus: 'failed', chunks: 0, error: asError(error).message })
      throw error
    }
    const sections = sectionize(fetched.html)
    if (sections.length === 0) {
      this.registry.recordCheck(resource.resource_id, {
        accessStatus: 'restricted', httpStatus: fetched.status, finalUrl: fetched.finalUrl,
        contentType: fetched.contentType, bytesRead: fetched.bytes, robotsAllowed: true, error: '正文区块提取为空（可能是纯 JS 渲染）',
      })
      return { resource_id: resource.resource_id, access_status: 'restricted', sections: 0, units: 0, ingested: 0, duplicates: 0, skipped: 0, warnings: ['正文区块提取为空（可能是纯 JS 渲染）'] }
    }
    const sourceType = SOURCE_TYPE_MAP[resource.resource_type] ?? 'web_page'
    const documentId = shortId('doc', `${resource.resource_id}:${fetched.finalUrl}`)
    const minTerms = ['technical_tutorial', 'official_documentation', 'accessibility_standard'].includes(resource.resource_type) ? 2 : 3
    const chunks: ChunkInput[] = []
    let skipped = 0
    for (const section of sections.slice(0, maxUnits)) {
      const classified = classifyWithPrior(section.text, section.heading, resource.primary_category)
      const unit = buildUnit(section, { resource, category: classified.category, score: classified.score, matched: classified.matched, minDesignTerms: minTerms })
      if (!unit.ready_to_ingest) { skipped += 1; continue }
      const chunk = this.chunkFromUnit(unit, resource, { documentId, sourceType })
      chunk.metadata = { ...(chunk.metadata ?? {}), classification_source: classified.classification_source }
      chunks.push(chunk)
    }
    const result = this.store.addChunks(chunks)
    const learned = result.added + result.updated
    this.registry.recordLearning(resource.resource_id, {
      learnStatus: learned > 0 ? 'learned' : 'partial',
      chunks: learned,
      notes: `分节 ${sections.length} / 过门槛 ${chunks.length} / 跳过 ${skipped} / 重复 ${result.duplicates.length}`,
    })
    return {
      resource_id: resource.resource_id,
      access_status: 'reachable',
      sections: sections.length,
      units: chunks.length,
      ingested: learned,
      duplicates: result.duplicates.length,
      skipped,
      warnings: [`本次只完成规则提取（最高 L2），未经交叉验证或任务验证`, ...result.warnings],
    }
  }

  async ingestBatch(input: { limit?: number; only?: string[]; maxUnits?: number; minIntervalMs?: number; all?: boolean } = {}): Promise<{ total: number; results: LearnResult[]; stats: Record<string, unknown> }> {
    let items = this.registry.view().filter((item) => item.access_status === 'reachable')
    if (input.only && input.only.length > 0) items = items.filter((item) => input.only?.includes(item.resource_id))
    if (input.limit) items = items.slice(0, Math.max(1, input.limit))
    if (!input.all && !input.only?.length && !input.limit) items = items.slice(0, 5)
    const results: LearnResult[] = []
    for (const item of items) {
      try {
        results.push(await this.learn({ resourceId: item.resource_id, maxUnits: input.maxUnits, minIntervalMs: input.minIntervalMs }))
      } catch (error) {
        this.registry.recordLearning(item.resource_id, { learnStatus: 'failed', chunks: 0, error: asError(error).message })
        results.push({ resource_id: item.resource_id, access_status: 'failed', sections: 0, units: 0, ingested: 0, duplicates: 0, skipped: 0, warnings: [asError(error).message] })
      }
    }
    return { total: results.reduce((sum, item) => sum + item.ingested, 0), results, stats: this.store.stats() as unknown as Record<string, unknown> }
  }

  async caseAnalyze(input: { resourceId: string; maxUnits?: number; minIntervalMs?: number }): Promise<CaseResult> {
    const resource = this.registry.get(input.resourceId)
    if (!resource) throw new NotFoundError(`未知 resource_id: ${input.resourceId}`)
    const client = this.client(input.minIntervalMs ?? 800)
    const probe = await client.probe(resource.url)
    if (probe.access_status !== 'reachable') throw new ArtError(`资源不可达: ${probe.access_status} ${probe.error}`, { code: ERROR_CODES.NETWORK_FAILED })
    const fetched = await client.fetchHtml(resource.url)
    const analysis = analyzeHtml(fetched.html, { url: resource.url, product: resource.name, platform: resource.platform })
    const units = unitsFromCase(analysis, resource).slice(0, clampMaxUnits(input.maxUnits, 24))
    const documentId = shortId('doc', `case:${resource.url}`)
    const chunks: ChunkInput[] = units.map((unit) => ({
      chunk_id: shortId('chunk', `${resource.resource_id}:${unit.content_hash}`),
      project_id: 'prj_art_uiux',
      document_id: documentId,
      partition: unit.level === 'L2' ? 'uiux_knowledge' : 'pending_knowledge',
      domain: 'uiux',
      topic: unit.category,
      subtopic: unit.title.slice(0, 120),
      title: unit.title.slice(0, 160),
      content: unit.content,
      summary: unit.content.slice(0, 300),
      knowledge_type: 'case_study',
      level: unit.level,
      source_id: shortId('src', resource.resource_id),
      source_url: resource.url,
      source_title: resource.name,
      source_type: 'web_page',
      author_or_publisher: resource.name,
      language: 'en',
      content_hash: unit.content_hash,
      source_quality: 0.6,
      confidence: unit.confidence,
      confidence_basis: `case-analyzer:${unit.kind}`,
      verification_status: 'unverified',
      freshness_status: 'unknown',
      license_status: 'unknown',
      visibility: 'project',
      metadata: { case: analysis.product, evidence_kind: unit.kind, evidence_basis: unit.basis, resource_id: resource.resource_id, tech_stack: analysis.tech_stack },
    }))
    const result = this.store.addChunks(chunks)
    const existing = this.store.listChunks({ projectId: 'prj_art_uiux', topics: [...new Set(units.map((unit) => unit.category))], limit: 400 })
    const conflicts = compareWithExisting(numericRules(units.map((unit) => ({ content: unit.content, category: unit.category, url: unit.url }))), existing as unknown as Array<Record<string, unknown>>)
    const learned = result.added + result.updated
    this.registry.recordLearning(resource.resource_id, {
      learnStatus: learned > 0 ? 'learned' : 'partial', chunks: learned, notes: `case-analyzer: 单元 ${units.length} / 冲突 ${conflicts.length}`,
    })
    return {
      resource_id: resource.resource_id,
      case: analysis.product,
      url: fetched.finalUrl,
      tech_stack: analysis.tech_stack,
      sections: Object.fromEntries(Object.entries(analysis.sections).map(([key, items]) => [key, items.length])),
      metrics: analysis.metrics,
      units: units.length,
      ingested: learned,
      duplicates: result.duplicates.length,
      conflicts: conflicts.slice(0, 40),
      report: {
        generated_at: new Date().toISOString(),
        sections: analysis.sections,
        metrics: analysis.metrics,
        tech_stack: analysis.tech_stack,
        content_hash: analysis.content_hash,
      },
      warnings: ['案例结论基于静态 HTML；视觉判断、可用性、性能与转化结论未测'],
    }
  }

  // ---------------------------------------------------------------- 检索 / 工作流

  routeTask(text: string): Record<string, unknown> {
    const result = routeTask(text)
    return { ...result, label: TASK_TYPES[result.task_type]?.label ?? result.task_type }
  }

  search(input: { query: string; categories?: string[]; topK?: number; minLevel?: string; rerank?: 'rules' | 'ce'; bilingual?: boolean; platform?: string }): RetrieveResult {
    if (!input.query?.trim()) throw new ValidationError('query 不能为空')
    if (input.rerank !== undefined && input.rerank !== 'rules' && input.rerank !== 'ce') throw new ValidationError("rerank 必须是 rules 或 ce")
    if (input.minLevel !== undefined && !['L1', 'L2', 'L3', 'L4'].includes(input.minLevel)) throw new ValidationError('min_level 必须是 L1/L2/L3/L4')
    const categories = input.categories && input.categories.length > 0 ? input.categories : routeTask(input.query).categories
    return retrieve(this.store, input.query, {
      categories,
      topK: Math.max(1, Math.min(50, Number(input.topK ?? 6))),
      minLevel: input.minLevel,
      rerank: input.rerank ?? this.settingsValue.rerank,
      bilingual: input.bilingual ?? true,
      platform: input.platform,
    })
  }

  directions(input: { taskType?: string; count?: number } = {}): Record<string, unknown> {
    const count = Math.max(1, Math.min(4, Number(input.count ?? 3)))
    return { task_type: input.taskType ?? 'web_page', directions: proposeDirections(input.taskType ?? 'web_page', count) }
  }

  designSystem(input: { direction?: string; base?: Record<string, string> } = {}): Record<string, unknown> {
    const system = buildDesignSystem(input.direction ?? 'swiss_grid', input.base ?? {})
    return { direction: system.direction, tokens: system.tokens, css: tokensToCss(system), contrast: system.contrast, failing_pairs: system.failing_pairs, ui_component_failures: system.ui_component_failures, verified: system.verified, note: system.note }
  }

  audit(input: { html: string; direction?: string; tokens?: Record<string, unknown> }): Record<string, unknown> {
    if (typeof input.html !== 'string' || input.html.length === 0) throw new ValidationError('html 不能为空')
    const tokens = input.tokens ?? (buildDesignSystem(input.direction ?? 'swiss_grid').tokens as unknown as Record<string, unknown>)
    return auditHtml(input.html, tokens)
  }

  responsive(input: { html: string }): Record<string, unknown> {
    if (typeof input.html !== 'string' || input.html.length === 0) throw new ValidationError('html 不能为空')
    return responsiveMatrix(input.html)
  }

  backgrounds(input: { textColor?: string; count?: number } = {}): Record<string, unknown> {
    return { backgrounds: generateBackgrounds({ textColor: input.textColor, count: input.count }) }
  }

  stats(): Record<string, unknown> {
    return { registry: this.registry.stats(), knowledge: this.store.stats(), integrity: this.store.checkIntegrity(), settings: this.settings }
  }

  /** 七步工作流的可执行版本；返回数据，写文件由 CLI 决定。 */
  async designTask(input: { task: string; direction?: string; topK?: number }): Promise<Record<string, unknown>> {
    if (!input.task?.trim()) throw new ValidationError('task 不能为空')
    const routed = routeTask(input.task)
    const found = retrieve(this.store, input.task, { categories: routed.categories, topK: input.topK ?? 5 })
    const directions = proposeDirections(routed.task_type, 3)
    const chosen = directions.find((direction) => direction.key === input.direction) ?? (directions[0] as (typeof directions)[number])
    const system = buildDesignSystem(chosen.key)
    const isAndroid = routed.task_type === 'android_native'
    const html = isAndroid ? '' : prototypeHtml(routed.task_type, system)
    const code = isAndroid ? composeSnippet(system) : html
    const audit = isAndroid
      ? { items: [], counts: { unmeasured: 10 }, measured_items: 0, note: 'Android 代码未经真实构建与渲染，审计项全部 unmeasured' }
      : auditHtml(html, system.tokens as unknown as Record<string, unknown>)
    const feedback = feedbackUnit({ decision: `方向 ${chosen.name} 的 token 基线`, evidence: '对比度实算见报告；尚未经过真实用户或生产验证', scope: 'project', category: routed.categories[0] as string })
    return { task: input.task, routed, retrieved: found, directions, chosen, design_system: system, tokens_css: tokensToCss(system), prototype_html: html, code, code_ext: isAndroid ? 'kt' : 'html', audit, feedback }
  }

  // ---------------------------------------------------------------- 组件

  private async githubJson(url: string): Promise<Record<string, unknown>> {
    const target = await assertSafeHttpUrl(url, { allowPrivateNetworks: this.settingsValue.allowPrivateNetworks })
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 25_000)
    try {
      const response = await fetch(target, {
        signal: controller.signal,
        headers: {
          'user-agent': 'DSH-Art-UIUX-ProMax/1.0 (component learning; public data only)',
          accept: 'application/vnd.github+json',
          ...(process.env.GITHUB_TOKEN ? { authorization: `Bearer ${process.env.GITHUB_TOKEN}` } : {}),
        },
      })
      if (response.status === 403) throw new ArtError('GitHub API 限流（403），请稍后重试或分批运行', { code: ERROR_CODES.NETWORK_FAILED, retryable: true })
      if (!response.ok) throw new ArtError(`GitHub API HTTP ${response.status}`, { code: ERROR_CODES.NETWORK_FAILED })
      return await response.json() as Record<string, unknown>
    } finally {
      clearTimeout(timer)
    }
  }

  private async githubText(url: string): Promise<string> {
    const target = await assertSafeHttpUrl(url, { allowPrivateNetworks: this.settingsValue.allowPrivateNetworks })
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 25_000)
    try {
      const response = await fetch(target, { signal: controller.signal, headers: { 'user-agent': 'DSH-Art-UIUX-ProMax/1.0' } })
      if (!response.ok) throw new ArtError(`HTTP ${response.status}`, { code: ERROR_CODES.NETWORK_FAILED })
      return (await response.text()).slice(0, 40_000)
    } finally {
      clearTimeout(timer)
    }
  }

  async componentsLearn(input: { keys?: string[]; limit?: number; all?: boolean } = {}): Promise<Record<string, unknown>> {
    if (!this.settingsValue.allowNetwork) throw new NetworkBlockedError('网络访问已在设置中关闭（allowNetwork=false）')
    let sources: ComponentSource[] = COMPONENT_SOURCES
    if (input.keys && input.keys.length > 0) sources = sources.filter((source) => input.keys?.includes(source.key))
    if (input.limit) sources = sources.slice(0, Math.max(1, input.limit))
    const results: Array<RepositoryInfo | { repository: string; error: string }> = []
    for (const source of sources) {
      try {
        const meta = await this.githubJson(`https://api.github.com/repos/${source.owner}/${source.repo}`)
        let readme = ''
        for (const name of ['README.md', 'readme.md', 'README.MD', 'README.rst', 'README']) {
          try { readme = await this.githubText(`https://raw.githubusercontent.com/${source.owner}/${source.repo}/HEAD/${name}`); break } catch { /* try next */ }
        }
        const branch = String(meta.default_branch ?? 'HEAD')
        const tree = await this.githubJson(`https://api.github.com/repos/${source.owner}/${source.repo}/git/trees/${branch}?recursive=1`)
        const paths = ((tree.tree as Array<{ path: string; type: string }> | undefined) ?? []).filter((node) => node.type === 'blob').map((node) => node.path)
        const info = analyzeRepository(meta, readme, paths, { platform: source.platform, sourceKey: source.key })
        results.push(info)
        const chunk: ChunkInput = {
          chunk_id: shortId('chunk_comp', source.key),
          project_id: 'prj_art_uiux',
          document_id: shortId('doc_comp', source.key),
          partition: info.knowledge_level === 'L2' ? 'uiux_knowledge' : 'pending_knowledge',
          domain: 'uiux',
          topic: source.topic ?? (source.platform === 'web' ? 'design_system' : 'android_ui'),
          subtopic: 'component-library',
          title: `${info.repository} 组件库 · ${source.platform === 'web' ? 'Web' : 'Android'}`,
          content: `组件库 ${info.repository}：许可证 ${info.license}，语言 ${info.framework}，候选组件 ${info.component_count_candidates} 个，类别 ${Object.keys(info.components_by_category).sort().join(', ') || '未识别'}；测试文件 ${info.test_files} 个，示例目录 ${info.example_paths.length} 个；${info.limitations}`,
          summary: info.purpose.slice(0, 300),
          knowledge_type: 'best_practice',
          level: info.knowledge_level,
          source_url: `https://github.com/${source.owner}/${source.repo}`,
          source_title: info.repository,
          source_type: 'code_repo',
          author_or_publisher: source.owner,
          language: 'en',
          content_hash: sha1Hex(JSON.stringify(info)),
          source_quality: info.archived ? 0.5 : 0.8,
          confidence: 0.5,
          confidence_basis: '仓库元数据+README+文件树，未读组件源码正文',
          verification_status: 'unverified',
          license_status: 'unknown',
          visibility: 'project',
          metadata: { component_library: info, source_key: source.key },
        }
        this.store.addChunks([chunk])
      } catch (error) {
        results.push({ repository: source.key, error: asError(error).message })
      }
    }
    const ok = results.filter((item): item is RepositoryInfo => !('error' in item))
    return {
      learned: ok.length,
      failed: results.length - ok.length,
      results,
      comparisons: comparisons(ok),
      warnings: ['仓库级比较只包含可观测项，不构成“哪个更好”的结论'],
    }
  }

  async componentSource(input: { repo: string; file: string; name?: string }): Promise<Record<string, unknown>> {
    if (!this.settingsValue.allowNetwork) throw new NetworkBlockedError('网络访问已在设置中关闭（allowNetwork=false）')
    const source = COMPONENT_SOURCES.find((item) => item.key === input.repo)
    if (!source) throw new NotFoundError(`未知组件库 key: ${input.repo}`)
    if (!input.file?.trim()) throw new ValidationError('file 不能为空')
    const code = await this.githubText(`https://raw.githubusercontent.com/${source.owner}/${source.repo}/HEAD/${input.file}`)
    let license = 'unknown'
    let testFiles = 0
    try {
      const meta = await this.githubJson(`https://api.github.com/repos/${source.owner}/${source.repo}`)
      license = ((meta.license as Record<string, unknown> | null)?.spdx_id as string | undefined) ?? 'unknown'
      const branch = String(meta.default_branch ?? 'HEAD')
      const tree = await this.githubJson(`https://api.github.com/repos/${source.owner}/${source.repo}/git/trees/${branch}?recursive=1`)
      const paths = ((tree.tree as Array<{ path: string }> | undefined) ?? []).map((node) => node.path)
      testFiles = paths.filter((path) => /(test|spec)\./i.test(path)).length
    } catch { /* 许可证/测试数量缺失时保持 unknown，不阻塞源码分析 */ }
    const name = input.name || (input.file.split('/').pop() ?? input.file).replace(/\.[^.]+$/, '')
    const knowledge = parseComponentSource(name, code, { repo: input.repo, path: input.file, license, testFiles })
    knowledge.source_url = `https://github.com/${source.owner}/${source.repo}/blob/HEAD/${input.file}`
    this.store.addChunks([{
      chunk_id: knowledge.component_id,
      project_id: 'prj_art_uiux',
      document_id: shortId('doc_src', input.file),
      partition: 'uiux_knowledge',
      domain: 'uiux',
      topic: 'design_system',
      subtopic: 'component-source',
      title: `${source.repo} · ${name} 组件源码分析`,
      content: `组件 ${name}（${input.file}）：props ${knowledge.parameters.length} 个；状态 ${knowledge.component_states.join(', ') || '未检出'}；${knowledge.accessibility}；变体 ${knowledge.theme_customization}；事件 ${knowledge.interaction_behavior}`,
      summary: '源码级组件知识（props/状态/aria/变体），未运行未渲染',
      knowledge_type: 'code_example',
      level: 'L2',
      source_url: knowledge.source_url,
      source_title: `${source.owner}/${source.repo}`,
      source_type: 'code_repo',
      author_or_publisher: source.owner,
      language: 'en',
      content_hash: knowledge.content_hash,
      source_quality: 0.8,
      confidence: 0.55,
      confidence_basis: '只读源码文本；未构建、未测试、未渲染',
      verification_status: 'unverified',
      visibility: 'project',
      metadata: { component_knowledge: knowledge },
    }])
    return { knowledge, warnings: ['只读源码：没有构建、没有运行测试、没有渲染截图'] }
  }

  // ---------------------------------------------------------------- 评测

  evaluate(options: { topK?: number; write?: boolean } = {}): Record<string, unknown> {
    const data = JSON.parse(readFileSync(join(this.root, 'eval', 'qrels.json'), 'utf8')) as {
      annotator?: string
      queries: Array<{ qid: string; query: string; expected_topic: string; labels: Record<string, number> }>
    }
    const systems = ['vector', 'bm25', 'rrf', 'rerank', 'rerank_zh'] as const
    const perQuery = data.queries.map((query) => {
      const runs: Record<string, string[]> = {}
      for (const system of systems) runs[system] = rankedIds(this.store, query.query, { mode: system, topK: options.topK ?? 10 })
      const metrics: Record<string, Record<string, number>> = {}
      for (const system of systems) {
        const ranked = runs[system] as string[]
        metrics[system] = {
          'P@1': precisionAtK(ranked, query.labels, 1),
          'P@3': precisionAtK(ranked, query.labels, 3),
          'P@5': precisionAtK(ranked, query.labels, 5),
          'R@10': recallAtK(ranked, query.labels, 10),
          'MRR@10': mrrAtK(ranked, query.labels, 10),
          'nDCG@5': ndcgAtK(ranked, query.labels, 5),
        }
      }
      const docs = (runs.rerank_zh ?? []).map((chunkId) => this.store.getChunk(chunkId))
      for (const system of systems) {
        const bucket = metrics[system] ?? (metrics[system] = {})
        bucket['cat_purity@5'] = categoryPurity((runs[system] ?? []).slice(0, 5).map((chunkId) => ({ topic: this.store.getChunk(chunkId)?.topic ?? '' })), query.expected_topic, 5)
      }
      return { qid: query.qid, query: query.query, expected_topic: query.expected_topic, labels: query.labels, runs, metrics, docs: docs.length }
    })
    const aggregate: Record<string, Record<string, number>> = {}
    for (const system of systems) {
      aggregate[system] = Object.fromEntries(['P@1', 'P@3', 'P@5', 'R@10', 'MRR@10', 'nDCG@5', 'cat_purity@5'].map((key) => [key, mean(perQuery.map((query) => query.metrics[system]?.[key] ?? Number.NaN))]))
    }
    const zipped = (key: string): { a: number[]; b: number[] } => ({
      a: perQuery.map((query) => query.metrics.rerank_zh?.[key] ?? Number.NaN),
      b: perQuery.map((query) => query.metrics.rrf?.[key] ?? Number.NaN),
    })
    const delta = zipped('nDCG@5')
    return {
      aggregate,
      deltas_rerank_vs_rrf: { 'nDCG@5': bootstrapDiff(delta.a, delta.b) },
      per_query: perQuery,
      annotator: data.annotator ?? 'unknown',
      chunk_count: this.store.stats().chunks,
      cross_encoder_available: false,
      warnings: this.store.stats().chunks === 0 ? ['知识库为空：评测指标全部为 n/a；先运行 check + ingest'] : [],
    }
  }
}

function prototypeHtml(taskType: string, system: DesignSystem): string {
  const c = system.tokens.color
  const body = taskType === 'fintech_terminal'
    ? `<main class="terminal"><header class="terminal__bar"><h1>EURUSD · 行情终端</h1><span class="pill">已连接</span></header><section class="grid"><article class="card"><h2>EURUSD</h2><p class="num">1.0842</p><p class="delta up">+0.32%</p></article><article class="card"><h2>XAUUSD</h2><p class="num">2412.10</p><p class="delta down">−0.18%</p></article><article class="card"><h2>持仓</h2><p class="num">3</p><p class="delta">浮动 +128.40</p></article></section><section class="card table"><table><thead><tr><th>品种</th><th>方向</th><th>手数</th><th>盈亏</th></tr></thead><tbody><tr><td>EURUSD</td><td>多</td><td>0.50</td><td class="up">+62.10</td></tr><tr><td>XAUUSD</td><td>空</td><td>0.20</td><td class="down">−18.40</td></tr></tbody></table></section></main>`
    : `<main class="page"><h1>Design with intent</h1><p class="lede">A layout built from measured tokens rather than decoration.</p><section class="grid"><article class="card"><h2>Hierarchy</h2><p>Three type steps, one accent.</p></article><article class="card"><h2>Rhythm</h2><p>8px spacing scale.</p></article></section></main>`
  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${taskType} prototype</title>
<style>
${tokensToCss(system)}
body{margin:0;background:${c.bg ?? '#fff'};color:${c.fg ?? '#111'};font-family:Inter,system-ui,sans-serif}
h1{font-size:56px;line-height:1.1;margin:0 0 12px}
h2{font-size:20px;margin:0 0 8px}
p{font-size:16px;color:${c.muted ?? '#555'}}
.card{background:${c.surface ?? '#f5f5f5'};border-radius:12px;padding:24px;box-shadow:0 1px 2px rgba(0,0,0,.06)}
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));padding:24px}
.terminal__bar{display:flex;justify-content:space-between;align-items:center;padding:16px 24px;border-bottom:1px solid rgba(255,255,255,.08)}
.num{font-size:28px}
.up{color:${c.positive ?? '#1c6b3a'}}.down{color:${c.negative ?? '#a32118'}}
.pill{border:1px solid rgba(255,255,255,.2);border-radius:999px;padding:4px 10px;font-size:12px}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid rgba(255,255,255,.06)}
.card:hover{box-shadow:0 8px 24px rgba(0,0,0,.10)}
.card:focus-visible{outline:2px solid ${c.accent ?? '#4c9aff'};outline-offset:2px}
.card:disabled{opacity:.5}
.card:active{transform:translateY(1px)}
</style></head><body>${body}</body></html>`
}

function composeSnippet(system: DesignSystem): string {
  const c = system.tokens.color
  const hex = (value: string | undefined, fallback: string): string => (value ?? fallback).replace('#', '')
  return `// 由 DSH Art UI/UX Pro Max 生成的设计 token（Compose 侧）
// 说明：骨架示例，未接入具体工程的导航与状态管理。

private val ArtColors = lightColorScheme(
    primary = Color(0xFF${hex(c.accent, '#4c9aff')}),
    background = Color(0xFF${hex(c.bg, '#ffffff')}),
    onBackground = Color(0xFF${hex(c.fg, '#111111')}),
    surface = Color(0xFF${hex(c.surface, '#f5f5f5')}),
)

@Composable
fun ArtHomeScreen(modifier: Modifier = Modifier) {
    Scaffold(topBar = { TopAppBar(title = { Text("首页") }) }) { padding ->
        LazyColumn(
            modifier = modifier.padding(padding).fillMaxSize(),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item { Text("今日概览", style = MaterialTheme.typography.headlineSmall) }
            items(3) { index ->
                Card(shape = RoundedCornerShape(12.dp)) {
                    Column(Modifier.padding(16.dp)) {
                        Text("指标 " + (index + 1), style = MaterialTheme.typography.titleMedium)
                        Text("数值占位", style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }
        }
    }
}
`
}
