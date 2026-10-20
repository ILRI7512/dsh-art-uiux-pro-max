/** 中英设计术语桥接：确定性扩展，不依赖模型；扩展明细随结果返回。 */
import { LEXICON } from './bilingual-data.ts'

const CJK = /[\u4e00-\u9fff]/

export function expand(query: string): { query: string; hits: Array<{ zh: string; en: string }> } {
  if (!CJK.test(query ?? '')) return { query, hits: [] }
  const hits: Array<{ zh: string; en: string }> = []
  const extra: string[] = []
  for (const [zh, en] of Object.entries(LEXICON)) {
    if (query.includes(zh)) {
      hits.push({ zh, en })
      extra.push(en)
    }
  }
  if (extra.length === 0) return { query, hits: [] }
  return { query: `${query} ${extra.join(' ')}`.trim(), hits }
}
