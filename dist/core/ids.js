import { createHash } from 'node:crypto';
export function sha256Hex(text) {
    return createHash('sha256').update(text).digest('hex');
}
export function sha1Hex(text) {
    return createHash('sha1').update(text).digest('hex');
}
/** 稳定短 ID：同一输入永远得到同一 ID，便于重跑去重。 */
export function shortId(prefix, text, length = 16) {
    return `${prefix}_${sha1Hex(text).slice(0, length)}`;
}
export function nowIso() {
    return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
}
export function contentFingerprint(text) {
    return sha256Hex(text.replace(/\s+/g, ' ').trim().toLowerCase());
}
export function hashObject(value) {
    return sha256Hex(JSON.stringify(value));
}
