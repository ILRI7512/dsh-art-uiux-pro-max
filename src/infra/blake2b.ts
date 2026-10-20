/**
 * BLAKE2b（RFC 7693，可配置输出长度）。
 *
 * 从同作者的 dsh-autolearn TypeScript 引擎移植；移除跨语言迁移注释，
 * 保留“8 字节摘要与 Python hashlib.blake2b 对拍”这一实现事实。
 *
 * 为什么自己实现：Python 版用 `hashlib.blake2b(digest_size=8)` 做特征哈希，
 * Node 内置只有 blake2b512（输出长度改变摘要本身），无法截断复用。
 * 本实现与 Python 逐字节一致（见 tests/unit/blake2b.test.ts 的对拍向量），
 * 因此跨语言向量索引可以互读。
 */

const IV: readonly bigint[] = [
  0x6a09e667f3bcc908n, 0xbb67ae8584caa73bn, 0x3c6ef372fe94f82bn, 0xa54ff53a5f1d36f1n,
  0x510e527fade682d1n, 0x9b05688c2b3e6c1fn, 0x1f83d9abfb41bd6bn, 0x5be0cd19137e2179n,
]

const SIGMA: ReadonlyArray<readonly number[]> = [
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
  [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
  [11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4],
  [7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8],
  [9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13],
  [2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9],
  [12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11],
  [13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10],
  [6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5],
  [10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0],
]

const MASK64 = (1n << 64n) - 1n

function rotr(x: bigint, n: bigint): bigint {
  return ((x >> n) | (x << (64n - n))) & MASK64
}

function add(...values: bigint[]): bigint {
  let sum = 0n
  for (const value of values) sum = (sum + value) & MASK64
  return sum
}

export function blake2b(input: Uint8Array, outLen = 64): Uint8Array {
  if (!Number.isInteger(outLen) || outLen < 1 || outLen > 64) {
    throw new Error('blake2b: outLen must be an integer in 1..64')
  }
  const h = IV.slice()
  h[0] = (h[0] as bigint) ^ BigInt(0x01010000 ^ outLen)
  const block = new Uint8Array(128)
  let offset = 0
  let counter = 0n

  const compress = (last: boolean): void => {
    const view = new DataView(block.buffer, block.byteOffset, block.byteLength)
    const m: bigint[] = []
    for (let i = 0; i < 16; i += 1) m.push(view.getBigUint64(i * 8, true))
    const v: bigint[] = [...h, ...IV]
    v[12] = (v[12] as bigint) ^ (counter & MASK64)
    v[13] = (v[13] as bigint) ^ ((counter >> 64n) & MASK64)
    if (last) v[14] = ~(v[14] as bigint) & MASK64

    const g = (a: number, b: number, c: number, d: number, x: bigint, y: bigint): void => {
      v[a] = add(v[a] as bigint, v[b] as bigint, x)
      v[d] = rotr((v[d] as bigint) ^ (v[a] as bigint), 32n)
      v[c] = add(v[c] as bigint, v[d] as bigint)
      v[b] = rotr((v[b] as bigint) ^ (v[c] as bigint), 24n)
      v[a] = add(v[a] as bigint, v[b] as bigint, y)
      v[d] = rotr((v[d] as bigint) ^ (v[a] as bigint), 16n)
      v[c] = add(v[c] as bigint, v[d] as bigint)
      v[b] = rotr((v[b] as bigint) ^ (v[c] as bigint), 63n)
    }

    for (let round = 0; round < 12; round += 1) {
      const s = SIGMA[round % 10] as readonly number[]
      g(0, 4, 8, 12, m[s[0] as number] as bigint, m[s[1] as number] as bigint)
      g(1, 5, 9, 13, m[s[2] as number] as bigint, m[s[3] as number] as bigint)
      g(2, 6, 10, 14, m[s[4] as number] as bigint, m[s[5] as number] as bigint)
      g(3, 7, 11, 15, m[s[6] as number] as bigint, m[s[7] as number] as bigint)
      g(0, 5, 10, 15, m[s[8] as number] as bigint, m[s[9] as number] as bigint)
      g(1, 6, 11, 12, m[s[10] as number] as bigint, m[s[11] as number] as bigint)
      g(2, 7, 8, 13, m[s[12] as number] as bigint, m[s[13] as number] as bigint)
      g(3, 4, 9, 14, m[s[14] as number] as bigint, m[s[15] as number] as bigint)
    }
    for (let i = 0; i < 8; i += 1) h[i] = (h[i] as bigint) ^ (v[i] as bigint) ^ (v[i + 8] as bigint)
  }

  while (offset + 128 < input.length) {
    block.set(input.subarray(offset, offset + 128))
    offset += 128
    counter = (counter + 128n) & MASK64
    compress(false)
  }
  const remaining = input.length - offset
  block.fill(0)
  block.set(input.subarray(offset))
  counter = (counter + BigInt(remaining)) & MASK64
  compress(true)

  const out = new Uint8Array(64)
  const outView = new DataView(out.buffer)
  for (let i = 0; i < 8; i += 1) outView.setBigUint64(i * 8, h[i] as bigint, true)
  return out.slice(0, outLen)
}

/** 8 字节摘要 → 无符号 64 位整数（小端），供特征哈希使用。 */
export function blake2bUint64(token: string): bigint {
  const digest = blake2b(new TextEncoder().encode(token), 8)
  let value = 0n
  for (let i = 7; i >= 0; i -= 1) value = (value << 8n) | BigInt(digest[i] as number)
  return value
}
