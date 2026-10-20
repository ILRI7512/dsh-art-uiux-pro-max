/**
 * 知识存储：SQLite 行 + 倒排 token + 512 维特征向量。
 *
 * 设计取舍：本项目语料规模是百条级，向量用暴力点积即可（无 ANN 依赖）；
 * 倒排与行在同一事务写入，避免“有行无索引”。所有检索先限定 project/topic/level，
 * 再排序，禁止跨项目泄漏。
 */
import { mkdirSync } from 'node:fs'
import { dirname } from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import { StorageError } from '../core/errors.ts'
import { contentFingerprint, nowIso } from '../core/ids.ts'
import type { ChunkInput, ChunkRow, SearchFilters, SearchHit } from '../core/types.ts'
import { HashingEmbedder, dot, type Embedder } from './embedder.ts'
import { tokenize } from './tokenizer.ts'

interface StoredChunkRow {
  chunk_id: string
  project_id: string
  document_id: string
  partition: string
  domain: string
  topic: string
  subtopic: string
  title: string
  content: string
  summary: string
  knowledge_type: string
  level: string
  source_id: string
  source_url: string
  source_title: string
  source_type: string
  author_or_publisher: string
  accessed_at: string
  language: string
  content_hash: string
  source_quality: number
  confidence: number
  confidence_basis: string
  verification_status: string
  freshness_status: string
  license_status: string
  visibility: string
  metadata: string
  created_at: string
  updated_at: string
}

export interface StoreStats {
  chunks: number
  projects: number
  partitions: Array<{ partition: string; total: number }>
  levels: Record<string, number>
  topics: Record<string, number>
  verification: Record<string, number>
  embedder: Record<string, unknown>
  db_path: string
}

export interface AddResult {
  added: number
  updated: number
  duplicates: string[]
  warnings: string[]
}

export interface RankedId { chunkId: string; score: number }

const SCHEMA = `
CREATE TABLE IF NOT EXISTS projects (
  project_id TEXT PRIMARY KEY,
  title TEXT NOT NULL DEFAULT '',
  goal TEXT NOT NULL DEFAULT '',
  domain TEXT NOT NULL DEFAULT 'uiux',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
  chunk_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  document_id TEXT NOT NULL DEFAULT '',
  partition TEXT NOT NULL DEFAULT 'pending_knowledge',
  domain TEXT NOT NULL DEFAULT 'uiux',
  topic TEXT NOT NULL,
  subtopic TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  knowledge_type TEXT NOT NULL DEFAULT 'best_practice',
  level TEXT NOT NULL DEFAULT 'L1',
  source_id TEXT NOT NULL DEFAULT '',
  source_url TEXT NOT NULL DEFAULT '',
  source_title TEXT NOT NULL DEFAULT '',
  source_type TEXT NOT NULL DEFAULT '',
  author_or_publisher TEXT NOT NULL DEFAULT '',
  accessed_at TEXT NOT NULL DEFAULT '',
  language TEXT NOT NULL DEFAULT 'en',
  content_hash TEXT NOT NULL,
  source_quality REAL NOT NULL DEFAULT 0.5,
  confidence REAL NOT NULL DEFAULT 0.35,
  confidence_basis TEXT NOT NULL DEFAULT '',
  verification_status TEXT NOT NULL DEFAULT 'unverified',
  freshness_status TEXT NOT NULL DEFAULT 'unknown',
  license_status TEXT NOT NULL DEFAULT 'unknown',
  visibility TEXT NOT NULL DEFAULT 'project',
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_project ON chunks(project_id);
CREATE INDEX IF NOT EXISTS idx_chunks_topic ON chunks(topic);
CREATE INDEX IF NOT EXISTS idx_chunks_level ON chunks(level);
CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(project_id, content_hash);
CREATE TABLE IF NOT EXISTS chunk_tokens (
  chunk_id TEXT NOT NULL,
  token TEXT NOT NULL,
  tf INTEGER NOT NULL,
  PRIMARY KEY (chunk_id, token)
);
CREATE INDEX IF NOT EXISTS idx_chunk_tokens_token ON chunk_tokens(token);
CREATE TABLE IF NOT EXISTS chunk_vectors (
  chunk_id TEXT PRIMARY KEY,
  dim INTEGER NOT NULL,
  vector BLOB NOT NULL
);
`

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

export class KnowledgeStore {
  readonly dbPath: string
  readonly embedder: Embedder
  private readonly db: DatabaseSync
  private vectorCache: Map<string, Float32Array> | null = null

  constructor(dbPath: string, embedder: Embedder = new HashingEmbedder(512)) {
    this.dbPath = dbPath
    this.embedder = embedder
    try {
      mkdirSync(dirname(dbPath), { recursive: true })
      this.db = new DatabaseSync(dbPath)
      this.db.exec('PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA foreign_keys=ON;')
      this.db.exec(SCHEMA)
    } catch (error) {
      throw new StorageError(`打开知识库失败: ${error instanceof Error ? error.message : String(error)}`, { path: dbPath })
    }
  }

  close(): void {
    try { this.db.close() } catch { /* already closed */ }
  }

  private transaction<T>(fn: () => T): T {
    this.db.exec('BEGIN IMMEDIATE')
    try {
      const value = fn()
      this.db.exec('COMMIT')
      return value
    } catch (error) {
      try { this.db.exec('ROLLBACK') } catch { /* ignore */ }
      throw error
    }
  }

  ensureProject(projectId: string, input: { title?: string; goal?: string; domain?: string } = {}): void {
    this.db.prepare('INSERT INTO projects(project_id,title,goal,domain,created_at) VALUES(?,?,?,?,?) ON CONFLICT(project_id) DO NOTHING')
      .run(projectId, input.title ?? '', input.goal ?? '', input.domain ?? 'uiux', nowIso())
  }

  /** 写入/更新；同项目同 content_hash 视为重复，不重复计数。 */
  addChunks(inputs: readonly ChunkInput[]): AddResult {
    if (inputs.length === 0) return { added: 0, updated: 0, duplicates: [], warnings: [] }
    const warnings: string[] = []
    let added = 0
    let updated = 0
    const duplicates: string[] = []
    this.transaction(() => {
      for (const input of inputs) {
        const hash = input.content_hash || contentFingerprint(input.content)
        const duplicate = this.db.prepare('SELECT chunk_id FROM chunks WHERE project_id=? AND content_hash=? AND chunk_id<>? LIMIT 1')
          .get(input.project_id, hash, input.chunk_id) as { chunk_id?: string } | undefined
        if (duplicate?.chunk_id) {
          duplicates.push(duplicate.chunk_id)
          continue
        }
        const exists = this.db.prepare('SELECT chunk_id FROM chunks WHERE chunk_id=?').get(input.chunk_id)
        const now = nowIso()
        const metadata = JSON.stringify(input.metadata ?? {})
        if (exists) {
          this.db.prepare(`UPDATE chunks SET project_id=?,document_id=?,partition=?,domain=?,topic=?,subtopic=?,title=?,content=?,summary=?,
            knowledge_type=?,level=?,source_id=?,source_url=?,source_title=?,source_type=?,author_or_publisher=?,accessed_at=?,language=?,
            content_hash=?,source_quality=?,confidence=?,confidence_basis=?,verification_status=?,freshness_status=?,license_status=?,visibility=?,metadata=?,updated_at=?
            WHERE chunk_id=?`).run(
            input.project_id, input.document_id ?? '', input.partition, input.domain ?? 'uiux', input.topic, input.subtopic ?? '',
            input.title, input.content, input.summary ?? '', input.knowledge_type ?? 'best_practice', input.level,
            input.source_id ?? '', input.source_url, input.source_title, input.source_type ?? '',
            input.author_or_publisher ?? '', input.accessed_at ?? now, input.language ?? 'en', hash,
            clamp(input.source_quality ?? 0.5, 0, 1), clamp(input.confidence ?? 0.35, 0, 1), input.confidence_basis ?? '',
            input.verification_status ?? 'unverified', input.freshness_status ?? 'unknown', input.license_status ?? 'unknown',
            input.visibility ?? 'project', metadata, now, input.chunk_id,
          )
          updated += 1
        } else {
          this.db.prepare(`INSERT INTO chunks(chunk_id,project_id,document_id,partition,domain,topic,subtopic,title,content,summary,
            knowledge_type,level,source_id,source_url,source_title,source_type,author_or_publisher,accessed_at,language,content_hash,
            source_quality,confidence,confidence_basis,verification_status,freshness_status,license_status,visibility,metadata,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(
            input.chunk_id, input.project_id, input.document_id ?? '', input.partition, input.domain ?? 'uiux', input.topic,
            input.subtopic ?? '', input.title, input.content, input.summary ?? '', input.knowledge_type ?? 'best_practice', input.level,
            input.source_id ?? '', input.source_url, input.source_title, input.source_type ?? '', input.author_or_publisher ?? '',
            input.accessed_at ?? now, input.language ?? 'en', hash, clamp(input.source_quality ?? 0.5, 0, 1),
            clamp(input.confidence ?? 0.35, 0, 1), input.confidence_basis ?? '', input.verification_status ?? 'unverified',
            input.freshness_status ?? 'unknown', input.license_status ?? 'unknown', input.visibility ?? 'project', metadata, now, now,
          )
          added += 1
        }
        this.reindex({ ...input, content_hash: hash })
      }
    })
    this.vectorCache = null
    return { added, updated, duplicates, warnings }
  }

  private reindex(input: ChunkInput): void {
    this.db.prepare('DELETE FROM chunk_tokens WHERE chunk_id=?').run(input.chunk_id)
    const counts = new Map<string, number>()
    const text = `${input.title}\n${input.content}\n${input.summary ?? ''}`
    for (const token of tokenize(text)) counts.set(token, (counts.get(token) ?? 0) + 1)
    const insert = this.db.prepare('INSERT INTO chunk_tokens(chunk_id,token,tf) VALUES(?,?,?)')
    for (const [token, tf] of counts) insert.run(input.chunk_id, token, tf)
    const embedding = (this.embedder.embed([`${input.title} ${input.content} ${input.summary ?? ''}`])[0] as Float32Array)
    const bytes = new Uint8Array(embedding.buffer, embedding.byteOffset, embedding.byteLength)
    this.db.prepare('INSERT INTO chunk_vectors(chunk_id,dim,vector) VALUES(?,?,?) ON CONFLICT(chunk_id) DO UPDATE SET dim=excluded.dim,vector=excluded.vector')
      .run(input.chunk_id, embedding.length, bytes)
  }

  private rowToChunk(row: StoredChunkRow): ChunkRow {
    return {
      chunk_id: row.chunk_id,
      project_id: row.project_id,
      document_id: row.document_id,
      partition: row.partition,
      domain: row.domain,
      topic: row.topic,
      subtopic: row.subtopic,
      title: row.title,
      content: row.content,
      summary: row.summary,
      knowledge_type: row.knowledge_type,
      level: row.level as ChunkRow['level'],
      source_id: row.source_id,
      source_url: row.source_url,
      source_title: row.source_title,
      source_type: row.source_type,
      author_or_publisher: row.author_or_publisher,
      accessed_at: row.accessed_at,
      language: row.language,
      content_hash: row.content_hash,
      source_quality: row.source_quality,
      confidence: row.confidence,
      confidence_basis: row.confidence_basis,
      verification_status: row.verification_status,
      freshness_status: row.freshness_status,
      license_status: row.license_status,
      visibility: row.visibility,
      metadata: JSON.parse(row.metadata || '{}') as Record<string, unknown>,
      created_at: row.created_at,
      updated_at: row.updated_at,
    }
  }

  private where(filters: SearchFilters): { sql: string; params: Array<string | number> } {
    const clauses: string[] = []
    const params: Array<string | number> = []
    if (filters.projectId) { clauses.push('project_id=?'); params.push(filters.projectId) }
    if (filters.topics && filters.topics.length > 0) {
      clauses.push(`topic IN (${filters.topics.map(() => '?').join(',')})`)
      params.push(...filters.topics)
    }
    if (filters.levels && filters.levels.length > 0) {
      clauses.push(`level IN (${filters.levels.map(() => '?').join(',')})`)
      params.push(...filters.levels)
    }
    if (filters.verificationStatuses && filters.verificationStatuses.length > 0) {
      clauses.push(`verification_status IN (${filters.verificationStatuses.map(() => '?').join(',')})`)
      params.push(...filters.verificationStatuses)
    }
    if (filters.partitions && filters.partitions.length > 0) {
      clauses.push(`partition IN (${filters.partitions.map(() => '?').join(',')})`)
      params.push(...filters.partitions)
    }
    return { sql: clauses.length > 0 ? `WHERE ${clauses.join(' AND ')}` : '', params }
  }

  listChunks(filters: SearchFilters = {}): ChunkRow[] {
    const { sql, params } = this.where(filters)
    const limit = filters.limit && filters.limit > 0 ? ` LIMIT ${Math.trunc(filters.limit)}` : ''
    const rows = this.db.prepare(`SELECT * FROM chunks ${sql} ORDER BY created_at, chunk_id${limit}`).all(...params) as unknown as StoredChunkRow[]
    return rows.map((row) => this.rowToChunk(row))
  }

  getChunk(chunkId: string): ChunkRow | null {
    const row = this.db.prepare('SELECT * FROM chunks WHERE chunk_id=?').get(chunkId) as unknown as StoredChunkRow | undefined
    return row ? this.rowToChunk(row) : null
  }

  /** 纯向量检索（cosine；向量已归一化，点积即余弦）。 */
  vectorSearch(query: string, filters: SearchFilters = {}, topK = 10): RankedId[] {
    const rows = this.listChunks(filters)
    if (rows.length === 0) return []
    const queryVector = this.embedder.embed([query])[0] as Float32Array
    const scores: RankedId[] = []
    const vectors = this.loadVectors()
    for (const row of rows) {
      const vector = vectors.get(row.chunk_id)
      if (!vector || vector.length !== queryVector.length) continue
      const score = dot(queryVector, vector)
      if (score > 0) scores.push({ chunkId: row.chunk_id, score })
    }
    return scores.sort((a, b) => b.score - a.score).slice(0, topK)
  }

  /** BM25（k1=1.5,b=0.75），只在过滤后的集合内统计 df。 */
  bm25Search(query: string, filters: SearchFilters = {}, topK = 10): RankedId[] {
    const terms = [...new Set(tokenize(query))]
    if (terms.length === 0) return []
    const rows = this.listChunks(filters)
    if (rows.length === 0) return []
    const allowed = new Set(rows.map((row) => row.chunk_id))
    const lengths = new Map<string, number>()
    const freqs = new Map<string, Map<string, number>>()
    const placeholders = terms.map(() => '?').join(',')
    const tokenRows = this.db.prepare(`SELECT chunk_id,token,tf FROM chunk_tokens WHERE token IN (${placeholders})`).all(...terms) as Array<{ chunk_id: string; token: string; tf: number }>
    for (const tokenRow of tokenRows) {
      if (!allowed.has(tokenRow.chunk_id)) continue
      let map = freqs.get(tokenRow.chunk_id)
      if (!map) { map = new Map(); freqs.set(tokenRow.chunk_id, map) }
      map.set(tokenRow.token, tokenRow.tf)
    }
    for (const row of rows) {
      const map = freqs.get(row.chunk_id)
      lengths.set(row.chunk_id, map ? [...map.values()].reduce((a, b) => a + b, 0) : 0)
    }
    const totalDocs = rows.length
    const avgLength = [...lengths.values()].reduce((a, b) => a + b, 0) / Math.max(totalDocs, 1) || 1
    const df = new Map<string, number>()
    for (const term of terms) {
      let count = 0
      for (const map of freqs.values()) if (map.has(term)) count += 1
      df.set(term, count)
    }
    const scored: RankedId[] = []
    for (const [chunkId, map] of freqs) {
      const dl = lengths.get(chunkId) || 1
      let score = 0
      for (const term of terms) {
        const tf = map.get(term) ?? 0
        if (tf === 0) continue
        const n = df.get(term) ?? 0
        const idf = Math.log(1 + (totalDocs - n + 0.5) / (n + 0.5))
        score += (idf * (tf * 2.5)) / (tf + 1.5 * (1 - 0.75 + (0.75 * dl) / avgLength))
      }
      if (score > 0) scored.push({ chunkId, score })
    }
    return scored.sort((a, b) => b.score - a.score).slice(0, topK)
  }

  hybridSearch(query: string, filters: SearchFilters = {}, topK = 10): RankedId[] {
    const pool = Math.max(topK * 4, 40)
    const vector = this.vectorSearch(query, filters, pool)
    const bm25 = this.bm25Search(query, filters, pool)
    const fused = new Map<string, number>()
    const add = (items: readonly RankedId[]): void => {
      items.forEach((item, index) => fused.set(item.chunkId, (fused.get(item.chunkId) ?? 0) + 1 / (60 + index + 1)))
    }
    add(vector)
    add(bm25)
    return [...fused.entries()].map(([chunkId, score]) => ({ chunkId, score })).sort((a, b) => b.score - a.score).slice(0, topK)
  }

  private loadVectors(): Map<string, Float32Array> {
    if (this.vectorCache) return this.vectorCache
    const cache = new Map<string, Float32Array>()
    const rows = this.db.prepare('SELECT chunk_id,dim,vector FROM chunk_vectors').all() as Array<{ chunk_id: string; dim: number; vector: Uint8Array }>
    for (const row of rows) {
      const copy = new Uint8Array(row.vector)
      const floats = new Float32Array(copy.buffer, copy.byteOffset, copy.byteLength / 4)
      cache.set(row.chunk_id, floats)
    }
    this.vectorCache = cache
    return cache
  }

  private hit(row: ChunkRow, score: number): SearchHit {
    const warnings: string[] = []
    if (row.verification_status !== 'verified') warnings.push(`unverified: ${row.verification_status || 'unverified'}（未经过交叉验证或任务验证）`)
    if (row.level === 'L1') warnings.push('level L1：仅解析/归类，未形成可执行原则')
    if (row.confidence < 0.5) warnings.push(`confidence ${row.confidence.toFixed(2)}：低于 0.5`)
    return {
      chunk_id: row.chunk_id,
      title: row.title,
      summary: row.summary,
      content: row.content,
      score,
      base_score: score,
      category_affinity: 0,
      lexical_overlap: 0,
      final_score: score,
      topic: row.topic,
      subtopic: row.subtopic,
      level: row.level,
      verification_status: row.verification_status,
      confidence: row.confidence,
      source: { url: row.source_url, title: row.source_title, type: row.source_type },
      warnings,
      metadata: row.metadata ?? {},
    }
  }

  /** 混合检索 + 分类亲和度/词面重叠重排；调用方仍需做双语扩展与 rerank 策略编排。 */
  search(query: string, options: { topK?: number; filters?: SearchFilters } = {}): { hits: SearchHit[]; candidates: number } {
    const topK = options.topK ?? 5
    const filters = options.filters ?? {}
    const ranked = this.hybridSearch(query, filters, Math.max(topK * 3, topK))
    const rows = new Map(this.listChunks(filters).map((row) => [row.chunk_id, row]))
    const hits = ranked.flatMap((item) => {
      const row = rows.get(item.chunkId)
      return row ? [this.hit(row, item.score)] : []
    })
    return { hits, candidates: hits.length }
  }

  stats(): StoreStats {
    const chunks = Number((this.db.prepare('SELECT COUNT(*) AS n FROM chunks').get() as { n: number }).n)
    const projects = Number((this.db.prepare('SELECT COUNT(*) AS n FROM projects').get() as { n: number }).n)
    const group = (column: string): Record<string, number> => Object.fromEntries(
      (this.db.prepare(`SELECT ${column} AS key, COUNT(*) AS n FROM chunks GROUP BY ${column} ORDER BY ${column}`).all() as Array<{ key: string; n: number }>).map((row) => [row.key, Number(row.n)]),
    )
    const partitions = (this.db.prepare('SELECT partition, COUNT(*) AS total FROM chunks GROUP BY partition ORDER BY partition').all() as Array<{ partition: string; total: number }>).map((row) => ({ partition: row.partition, total: Number(row.total) }))
    return {
      chunks,
      projects,
      partitions,
      levels: group('level'),
      topics: group('topic'),
      verification: group('verification_status'),
      embedder: this.embedder.describe(),
      db_path: this.dbPath,
    }
  }

  /** 仅用于诊断/迁移：检查 token/vector 与行是否一致。 */
  checkIntegrity(): { missing_tokens: string[]; missing_vectors: string[] } {
    const missingTokens = (this.db.prepare('SELECT c.chunk_id FROM chunks c LEFT JOIN chunk_tokens t ON t.chunk_id=c.chunk_id WHERE t.chunk_id IS NULL').all() as Array<{ chunk_id: string }>).map((row) => row.chunk_id)
    const missingVectors = (this.db.prepare('SELECT c.chunk_id FROM chunks c LEFT JOIN chunk_vectors v ON v.chunk_id=c.chunk_id WHERE v.chunk_id IS NULL').all() as Array<{ chunk_id: string }>).map((row) => row.chunk_id)
    return { missing_tokens: missingTokens, missing_vectors: missingVectors }
  }
}
