/**
 * 12 个知识主分类（唯一主分类制）与 16 个提取字段。
 *
 * 主分类写入 chunk.topic，辅助标签写入 metadata.secondary_categories；
 * 分类校验是确定性的，错误分类不会被“猜一个”兜底。
 */
import { ValidationError } from '../core/errors.ts'
import { TAXONOMY_DATA } from './taxonomy-data.ts'

export interface Category {
  key: string
  label: string
  label_en: string
  description: string
  include_scope: string[]
  exclude_scope: string[]
  subcategories: string[]
  keywords: string[]
  knowledge_types: string[]
  related: string[]
  ingest_conditions: string[]
  quality_requirements: string[]
}

interface RawCategory {
  key: string
  label: string
  label_en: string
  description: string
  include_scope: readonly string[]
  exclude_scope: readonly string[]
  subcategories: readonly string[]
  keywords: readonly string[]
  knowledge_types: readonly string[]
  related: readonly string[]
  ingest_conditions: readonly string[]
  quality_requirements: readonly string[]
}

const toCategory = (raw: RawCategory): Category => ({
  key: raw.key,
  label: raw.label,
  label_en: raw.label_en,
  description: raw.description,
  include_scope: [...raw.include_scope],
  exclude_scope: [...raw.exclude_scope],
  subcategories: [...raw.subcategories],
  keywords: [...raw.keywords],
  knowledge_types: [...raw.knowledge_types],
  related: [...raw.related],
  ingest_conditions: [...raw.ingest_conditions],
  quality_requirements: [...raw.quality_requirements],
})

export const CATEGORIES: Record<string, Category> = Object.fromEntries(
  TAXONOMY_DATA.categories.map((item) => [item.key, toCategory(item)]),
)

export const CATEGORY_KEYS: string[] = TAXONOMY_DATA.categories.map((item) => item.key)
export const EXTRACTION_FIELDS: string[] = [...TAXONOMY_DATA.extraction_fields]
export const EXTRACTION_MINIMUM: string[] = [...TAXONOMY_DATA.extraction_minimum]

export class TaxonomyError extends ValidationError {
  constructor(message: string) {
    super(message)
    this.name = 'TaxonomyError'
  }
}

export function getCategory(key: string): Category {
  const category = CATEGORIES[key]
  if (!category) throw new TaxonomyError(`未知主分类 ${JSON.stringify(key)}，允许值: ${CATEGORY_KEYS.join(', ')}`)
  return category
}

/** 校验主/辅分类；返回去重后的辅助标签，不做任何自动纠正。 */
export function validateAssignment(primary: string, secondary: readonly string[] = []): string[] {
  getCategory(primary)
  const seen = new Set<string>()
  const cleaned: string[] = []
  for (const item of secondary) {
    if (typeof item !== 'string') throw new TaxonomyError(`辅助分类必须是字符串，收到 ${String(item)}`)
    const key = item.trim()
    if (!key) continue
    if (key === primary) throw new TaxonomyError(`辅助分类不能与主分类相同（${key}）`)
    getCategory(key)
    if (!seen.has(key)) {
      seen.add(key)
      cleaned.push(key)
    }
  }
  return cleaned
}

export function describeTaxonomy(): Record<string, unknown> {
  return {
    primary_keys: CATEGORY_KEYS,
    categories: CATEGORY_KEYS.map((key) => {
      const c = CATEGORIES[key] as Category
      return {
        key: c.key,
        label: c.label,
        label_en: c.label_en,
        description: c.description,
        include_scope: c.include_scope,
        exclude_scope: c.exclude_scope,
        subcategories: c.subcategories,
        keywords: c.keywords,
        knowledge_types: c.knowledge_types,
        related: c.related,
        ingest_conditions: c.ingest_conditions,
        quality_requirements: c.quality_requirements,
      }
    }),
    extraction_fields: EXTRACTION_FIELDS,
    extraction_minimum: EXTRACTION_MINIMUM,
  }
}
