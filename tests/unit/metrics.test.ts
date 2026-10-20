import assert from 'node:assert/strict'
import { test } from 'node:test'
import { bootstrapDiff, mrrAtK, ndcgAtK, precisionAtK, recallAtK } from '../../src/domain/metrics.ts'

test('P/R/MRR 在已知排序上可手算', () => {
  const ranked = ['a', 'b', 'c', 'd']
  const rel = { a: 2, c: 1 }
  assert.equal(precisionAtK(ranked, rel, 1), 1)
  assert.ok(Math.abs(precisionAtK(ranked, rel, 3) - 2 / 3) < 1e-9)
  assert.equal(recallAtK(ranked, rel, 2), 0.5)
  assert.equal(recallAtK(ranked, rel, 10), 1)
  assert.equal(mrrAtK(ranked, rel, 10), 1)
  assert.equal(mrrAtK(['b', 'a'], rel, 10), 0.5)
})

test('nDCG 与手算一致', () => {
  const rel = { a: 2, b: 1 }
  assert.ok(Math.abs(ndcgAtK(['a', 'b'], rel, 5) - 1) < 1e-9)
  const got = ndcgAtK(['b', 'a'], rel, 5)
  const ideal = (2 ** 2 - 1) + (2 ** 1 - 1) / 1.584962500721156
  const expected = ((2 ** 1 - 1) + (2 ** 2 - 1) / 1.584962500721156) / ideal
  assert.ok(Math.abs(got - expected) < 1e-6)
})

test('无答案查询是 NaN 而不是 0', () => {
  assert.ok(Number.isNaN(recallAtK(['x', 'y'], {}, 5)))
  assert.ok(Number.isNaN(ndcgAtK(['x'], {}, 5)))
})

test('bootstrap 给区间与样本数', () => {
  const out = bootstrapDiff([1, 0.8, 0.9, 0.7, 1], [0.5, 0.4, 0.6, 0.3, 0.5])
  assert.equal(out.n, 5)
  assert.ok(out.mean_diff > 0)
  assert.ok(out.lo <= out.mean_diff && out.mean_diff <= out.hi)
})
