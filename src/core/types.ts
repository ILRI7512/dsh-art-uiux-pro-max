/** 跨层共享的数据形状。字段命名跟随 Python 版与 DSH 工具输出，便于旧数据迁移。 */

export type ArtLevel = 'L0' | 'L1' | 'L2' | 'L3' | 'L4'
export type AccessStatus = 'unchecked' | 'reachable' | 'restricted' | 'blocked' | 'failed'
export type LearnStatus = 'not_started' | 'partial' | 'learned' | 'failed'

export interface Resource {
  resource_id: string
  name: string
  url: string
  resource_type: string
  primary_category: string
  secondary_categories: string[]
  platform: string
  learning_objectives: string[]
  access_status: AccessStatus
  last_checked: string
  last_learned: string
  license_notes: string
  source_reliability: 'high' | 'medium' | 'low' | 'unknown'
  learning_priority: number
  crawl_policy: string
}

export interface ResourceView extends Resource {
  learn_status: LearnStatus
  learned_chunks: number
  learn_notes: string
  last_error: string
  updated_at?: string
  last_http_status?: number | null
  last_final_url?: string
  last_content_type?: string
  last_bytes?: number
  robots_allowed?: boolean | null
}

export interface Section {
  heading: string
  level: number
  text: string
}

export interface Evidence {
  statement: string
  kind: 'fact' | 'inference' | 'opinion'
  confidence: number
  basis: string
}

export interface CaseAnalysis {
  url: string
  product: string
  platform: string
  tech_stack: string[]
  sections: Record<string, Evidence[]>
  metrics: Record<string, unknown>
  content_hash: string
}

export interface ChunkInput {
  chunk_id: string
  project_id: string
  document_id?: string
  partition: string
  domain?: string
  topic: string
  subtopic?: string
  title: string
  content: string
  summary?: string
  knowledge_type?: string
  level: ArtLevel
  source_id?: string
  source_url: string
  source_title: string
  source_type?: string
  author_or_publisher?: string
  accessed_at?: string
  language?: string
  content_hash?: string
  source_quality?: number
  confidence?: number
  confidence_basis?: string
  verification_status?: string
  freshness_status?: string
  license_status?: string
  visibility?: string
  metadata?: Record<string, unknown>
}

export type ChunkRow = ChunkInput & Required<Pick<ChunkInput,
  'document_id' | 'domain' | 'subtopic' | 'summary' | 'knowledge_type' | 'source_id' | 'source_type' |
  'author_or_publisher' | 'accessed_at' | 'language' | 'content_hash' | 'source_quality' | 'confidence' |
  'confidence_basis' | 'verification_status' | 'freshness_status' | 'license_status' | 'visibility' | 'metadata'>> & {
  created_at: string
  updated_at: string
}

export interface SearchFilters {
  projectId?: string
  topics?: string[]
  levels?: string[]
  verificationStatuses?: string[]
  partitions?: string[]
  limit?: number
}

export interface SearchHit {
  chunk_id: string
  title: string
  summary: string
  content: string
  score: number
  base_score: number
  category_affinity: number
  lexical_overlap: number
  final_score: number
  topic: string
  subtopic: string
  level: string
  verification_status: string
  confidence: number
  source: { url: string; title: string; type: string }
  warnings: string[]
  metadata: Record<string, unknown>
}

export interface SearchOutcome {
  query: string
  count: number
  candidates: number
  results: SearchHit[]
  evidence_sufficient: boolean
  answer_if_empty: string
  rerank: { applied: boolean; affinity: Record<string, number>; mode: string }
  bilingual: { applied: boolean; hits: Array<{ zh: string; en: string }>; expanded_query: string }
  unverified: boolean | null
  warnings: string[]
  elapsed_ms: number
}
