/**
 * 检索重排层：混合检索（向量 + BM25 + RRF）之后，按“查询→分类亲和度”与词面重叠
 * 做可解释重排。分类亲和度只加成，不改变已显式指定的分类过滤。
 */
import type { SearchFilters, SearchHit, SearchOutcome } from '../core/types.ts'
import type { KnowledgeStore } from '../infra/store.ts'
import { tokenize } from '../infra/tokenizer.ts'
import { CATEGORIES, getCategory } from './taxonomy.ts'
import { expand as bilingualExpand } from './bilingual.ts'
import { rerank as crossEncoderRerank } from './rerank.ts'
import { ArtError, ERROR_CODES } from '../core/errors.ts'

const STOP = new Set(['the', 'a', 'an', 'and', 'or', 'of', 'to', 'in', 'is', 'are', 'for', 'with', 'on', 'how', 'what', 'best', 'good', 'use', 'using', 'should', 'minimum'])

function tokenSet(text: string): Set<string> {
  return new Set((text.toLowerCase().match(/[a-z\u4e00-\u9fff]{2,}/g) ?? []).filter((word) => !STOP.has(word)))
}

/** 查询对各分类的亲和度：关键词命中数 / 该分类关键词总数，按最大值归一化。 */
export function categoryAffinity(query: string): Record<string, number> {
  const tokens = tokenSet(query)
  const low = query.toLowerCase()
  const raw: Record<string, number> = {}
  for (const [key, category] of Object.entries(CATEGORIES)) {
    let hits = 0
    for (const keyword of category.keywords) {
      const k = keyword.toLowerCase()
      if (low.includes(k) || [...tokens].some((token) => token.includes(k) || k.includes(token))) hits += 1
    }
    hits += 0.25 * [...tokenSet(category.description)].filter((word) => tokens.has(word)).length
    if (hits > 0) raw[key] = hits
  }
  const values = Object.values(raw)
  if (values.length === 0) return {}
  const top = Math.max(...values)
  return Object.fromEntries(Object.entries(raw).map(([key, value]) => [key, Math.round((value / top) * 1000) / 1000]))
}

export interface RetrieveOptions {
  categories?: readonly string[]
  platform?: string
  topK?: number
  minLevel?: string
  rerank?: 'rules' | 'ce'
  bilingual?: boolean
  filters?: SearchFilters
}

export interface RetrieveResult extends Omit<SearchOutcome, 'results'> {
  hits: SearchHit[]
  results: SearchHit[]
  categories: string[]
  count: number
  level_spread: Record<string, number>
  query_expanded: boolean
}

function buildFilters(options: RetrieveOptions): SearchFilters {
  const filters: SearchFilters = { projectId: 'prj_art_uiux', ...(options.filters ?? {}) }
  if (options.categories && options.categories.length > 0) filters.topics = [...options.categories]
  if (options.minLevel) filters.levels = [options.minLevel]
  return filters
}

/** 分类关键词扩展：中文提问 + 英文语料召不回时的确定性兜底。 */
function keywordFallback(store: KnowledgeStore, categories: readonly string[], filters: SearchFilters, topK: number): SearchHit[] {
  const terms: string[] = []
  for (const category of categories) {
    try { terms.push(...getCategory(category).keywords.slice(0, 6)) } catch { /* 未知分类由调用方校验 */ }
  }
  if (terms.length === 0) return []
  return store.search(terms.join(' '), { topK, filters }).hits
}

export function retrieve(store: KnowledgeStore, query: string, options: RetrieveOptions = {}): RetrieveResult {
  const started = Date.now()
  const topK = options.topK ?? 6
  const categories = [...(options.categories ?? [])]
  for (const category of categories) getCategory(category)
  if (options.minLevel && !['L1', 'L2', 'L3', 'L4'].includes(options.minLevel)) throw new ArtError('minLevel 必须是 L1/L2/L3/L4', { code: ERROR_CODES.VALIDATION_FAILED })
  const filters = buildFilters(options)
  const expanded = options.bilingual !== false ? bilingualExpand(query) : { query, hits: [] as Array<{ zh: string; en: string }> }
  const searchQuery = expanded.query

  let raw = store.search(searchQuery, { topK: Math.max(topK * 3, topK), filters })
  let hits = raw.hits
  let queryExpanded = false
  if (hits.length === 0 && categories.length > 0) {
    hits = keywordFallback(store, categories, filters, Math.max(topK * 3, topK))
    queryExpanded = hits.length > 0
  }

  const affinity = categories.length > 0 ? {} : categoryAffinity(query)
  const qTokens = new Set([...tokenSet(query), ...tokenSet(searchQuery)])
  const ranked = hits.map((hit) => {
    const aff = affinity[hit.topic] ?? 0
    const body = `${hit.title} ${hit.content} ${hit.summary}`.toLowerCase()
    const bodyTokens = tokenSet(body)
    const overlap = qTokens.size > 0 ? [...qTokens].filter((token) => bodyTokens.has(token)).length / qTokens.size : 0
    const finalScore = hit.base_score * (1 + 0.35 * aff) * (1 + 0.6 * overlap)
    return { ...hit, category_affinity: aff, lexical_overlap: Math.round(overlap * 1000) / 1000, final_score: Math.round(finalScore * 1e6) / 1e6 }
  })
  ranked.sort((a, b) => b.final_score - a.final_score)

  let mode = options.rerank ?? 'rules'
  const warnings: string[] = []
  let top = ranked.slice(0, topK)
  if (mode === 'ce') {
    try {
      const ce = crossEncoderRerank(query, ranked.slice(0, Math.max(12, topK)), { topK })
      top = ce.results as unknown as SearchHit[]
    } catch (error) {
      mode = 'rules'
      warnings.push(error instanceof ArtError && error.code === ERROR_CODES.UNSUPPORTED
        ? '交叉编码器在当前 TS 运行时不可用，已降级为规则重排'
        : `交叉编码器重排失败，已降级为规则重排：${error instanceof Error ? error.message : String(error)}`)
    }
  }
  if (options.platform) {
    const matched = top.filter((hit) => (hit.source.url ?? '').includes(options.platform as string))
    if (matched.length > 0) top = matched
  }

  const levels = top.map((hit) => hit.level)
  const levelSpread: Record<string, number> = {}
  for (const level of levels) levelSpread[level] = (levelSpread[level] ?? 0) + 1
  const unverified = top.length > 0 ? top.every((hit) => hit.verification_status !== 'verified') : null
  if (unverified) warnings.push('命中结果全部 unverified，不得当作既定事实')
  if (top.length === 0) warnings.push('知识库暂无足够证据：该分类尚未学到相关内容，建议先补学习任务')

  return {
    query,
    categories,
    count: top.length,
    candidates: hits.length,
    hits: top,
    results: top,
    evidence_sufficient: top.length > 0,
    answer_if_empty: top.length > 0 ? '' : '知识库暂无足够证据：该分类尚未学到相关内容，建议先补学习任务',
    level_spread: levelSpread,
    query_expanded: queryExpanded,
    rerank: { applied: Object.keys(affinity).length > 0, affinity, mode },
    bilingual: { applied: expanded.hits.length > 0, hits: expanded.hits, expanded_query: expanded.hits.length > 0 ? searchQuery : '' },
    unverified,
    warnings,
    elapsed_ms: Date.now() - started,
  }
}

/** 评测用：固定返回 top-k chunk id，不改变生产检索语义。 */
export function rankedIds(store: KnowledgeStore, query: string, options: { mode: 'vector' | 'bm25' | 'rrf' | 'rerank' | 'rerank_zh' | 'rerank_ce'; topK?: number; filters?: SearchFilters }): string[] {
  const topK = options.topK ?? 10
  const filters = options.filters ?? { projectId: 'prj_art_uiux' }
  if (options.mode === 'vector') return store.vectorSearch(query, filters, topK).map((item) => item.chunkId)
  if (options.mode === 'bm25') return store.bm25Search(query, filters, topK).map((item) => item.chunkId)
  if (options.mode === 'rrf') return store.hybridSearch(query, filters, topK).map((item) => item.chunkId)
  const result = retrieve(store, query, { topK, filters, bilingual: options.mode === 'rerank_zh' || options.mode === 'rerank_ce', rerank: options.mode === 'rerank_ce' ? 'ce' : 'rules' })
  return result.hits.map((hit) => hit.chunk_id)
}
