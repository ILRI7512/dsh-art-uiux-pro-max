/**
 * 特征哈希向量化（确定性、离线，不是神经语义模型）。
 *
 * token 来自 tokenizer；每个 token 取 blake2b-64，index = value % dim，
 * sign = bit63；权重 1 + ln(tf)，最后 L2 归一化。与 Python 版完全一致，
 * 因此旧的 512 维索引可以直接比较。
 */
import { blake2bUint64 } from "./blake2b.js";
import { tokenize } from "./tokenizer.js";
export class HashingEmbedder {
    provider = 'hashing';
    model;
    dim;
    embedderId;
    constructor(dim = 512, model = 'hashed-ngram') {
        if (!Number.isInteger(dim) || dim <= 0)
            throw new Error('向量维度必须为正整数');
        this.dim = dim;
        this.model = model || 'hashed-ngram';
        this.embedderId = `${this.provider}:${this.model}:${this.dim}`;
    }
    hash(token) {
        const value = blake2bUint64(token);
        return {
            index: Number(value % BigInt(this.dim)),
            sign: ((value >> 63n) & 1n) === 1n ? 1 : -1,
        };
    }
    embed(texts) {
        const out = [];
        for (const text of texts) {
            const vector = new Float64Array(this.dim);
            const counts = new Map();
            for (const token of tokenize(text ?? ''))
                counts.set(token, (counts.get(token) ?? 0) + 1);
            for (const [token, count] of counts) {
                const { index, sign } = this.hash(token);
                vector[index] = vector[index] + sign * (1 + Math.log(count));
            }
            out.push(normalize(vector));
        }
        return out;
    }
    describe() {
        return {
            provider: this.provider,
            model: this.model,
            dim: this.dim,
            note: '本地特征哈希，非神经网络语义模型；可在离线环境确定性复现',
        };
    }
}
export function normalize(vector) {
    let norm = 0;
    for (const value of vector)
        norm += value * value;
    norm = Math.sqrt(norm);
    const out = new Float32Array(vector.length);
    if (norm === 0)
        return out;
    for (let i = 0; i < vector.length; i += 1)
        out[i] = vector[i] / norm;
    return out;
}
export function dot(a, b) {
    let sum = 0;
    const n = Math.min(a.length, b.length);
    for (let i = 0; i < n; i += 1)
        sum += a[i] * b[i];
    return sum;
}
