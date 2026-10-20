import { createHash } from 'node:crypto'

export function sha256Hex(text: string): string {
  return createHash('sha256').update(text).digest('hex')
}

export function sha1Hex(text: string): string {
  return createHash('sha1').update(text).digest('hex')
}

/** 稳定短 ID：同一输入永远得到同一 ID，便于重跑去重。 */
export function shortId(prefix: string, text: string, length = 16): string {
  return `${prefix}_${sha1Hex(text).slice(0, length)}`
}

export function nowIso(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z')
}

export function contentFingerprint(text: string): string {
  return sha256Hex(text.replace(/\s+/g, ' ').trim().toLowerCase())
}

export function hashObject(value: unknown): string {
  return sha256Hex(JSON.stringify(value))
}
