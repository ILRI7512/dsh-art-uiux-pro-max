/**
 * 交叉编码器重排的兼容接口。
 *
 * TS 运行时默认不捆绑 transformer 模型（体积与 CPU 成本都高），因此：
 * - 空候选直接返回空；
 * - 有候选时抛 UNSUPPORTED，由检索层显式降级为规则重排并写入 warning；
 * 不返回伪造的 CE 分数。
 */
import { ArtError, ERROR_CODES } from '../core/errors.ts'

export const DEFAULT_MODEL = 'cross-encoder/mmarco-mMiniLMv2-L12-H384-v1'

export interface RerankResult {
  results: Array<Record<string, unknown>>
  model: string
  reranked: number
  latency_ms: number
  blend?: number
  note?: string
}

export function rerank(query: string, candidates: ReadonlyArray<Record<string, unknown>>, options: { topK?: number; modelName?: string; blend?: number } = {}): RerankResult {
  if (candidates.length === 0) return { results: [], model: options.modelName ?? DEFAULT_MODEL, reranked: 0, latency_ms: 0 }
  throw new ArtError('当前 TS 运行时未安装交叉编码器模型；请使用 rerank=rules', {
    code: ERROR_CODES.UNSUPPORTED,
    details: { model: options.modelName ?? DEFAULT_MODEL, query: query.slice(0, 80), candidates: candidates.length, top_k: options.topK ?? 5 },
  })
}
