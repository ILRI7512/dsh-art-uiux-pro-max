/**
 * 分词器：确定性分词规则（BM25 召回的基础）。
 *
 * 为什么不用 FTS5 分词：SQLite 的 unicode61 不切中文；这里用拉丁词 + 中文
 * 二元组构造确定性的倒排表，离线、可测、可解释。
 */
const LATIN_RE = /[a-zA-Z0-9_+#./\u2014-]+/g;
const CJK_RE = /[\u4e00-\u9fff]+/g;
const STOPWORDS = new Set([
    'the', 'a', 'an', 'of', 'to', 'and', 'or', 'in', 'on', 'for', 'with', 'is',
    'are', 'was', 'were', 'be', 'been', 'it', 'this', 'that', 'as', 'by', 'at',
    '的', '了', '和', '与', '是', '在', '有', '对', '把', '被', '为', '从', '就',
    '都', '也', '而', '及', '或', '一个', '我们', '可以', '这个', '那个',
]);
export function tokenize(text) {
    if (!text)
        return [];
    const tokens = [];
    const lowered = text.toLowerCase();
    for (const match of lowered.matchAll(LATIN_RE)) {
        const word = match[0].replace(/^[._\-/]+|[._\-/]+$/g, '');
        if (word.length >= 2 && !STOPWORDS.has(word))
            tokens.push(word);
    }
    for (const match of text.matchAll(CJK_RE)) {
        const run = match[0];
        if (run.length === 1) {
            if (!STOPWORDS.has(run))
                tokens.push(run);
            continue;
        }
        for (let i = 0; i < run.length - 1; i += 1) {
            const bigram = run.slice(i, i + 2);
            if (!STOPWORDS.has(bigram))
                tokens.push(bigram);
        }
    }
    return tokens;
}
export function termFrequencies(text) {
    const counts = new Map();
    for (const token of tokenize(text))
        counts.set(token, (counts.get(token) ?? 0) + 1);
    return counts;
}
export const DEFAULT_BM25 = { k1: 1.5, b: 0.75 };
export function expandQuery(query) {
    return [...new Set(tokenize(query))];
}
/** 纯函数 BM25：与 SQL 版公式一致，用于单测与无库场景。 */
export function bm25Scores(queryTokens, docs, docLengths, totalDocs, avgLength, params = DEFAULT_BM25) {
    const terms = [...new Set(queryTokens)].filter(Boolean);
    const scores = new Map();
    if (terms.length === 0 || totalDocs <= 0)
        return scores;
    const df = new Map();
    for (const term of terms) {
        let count = 0;
        for (const freqs of docs.values())
            if (freqs.has(term))
                count += 1;
        df.set(term, count);
    }
    const avgdl = avgLength || 1;
    for (const [docId, freqs] of docs) {
        let docLen = docLengths.get(docId) ?? 0;
        if (!docLen) {
            let sum = 0;
            for (const value of freqs.values())
                sum += value;
            docLen = sum;
        }
        if (!docLen)
            docLen = 1;
        let score = 0;
        for (const term of terms) {
            const tf = freqs.get(term) ?? 0;
            if (!tf)
                continue;
            const n = df.get(term) ?? 0;
            const idf = Math.log(1 + (totalDocs - n + 0.5) / (n + 0.5));
            const denom = tf + params.k1 * (1 - params.b + (params.b * docLen) / avgdl);
            score += (idf * (tf * (params.k1 + 1))) / denom;
        }
        if (score > 0)
            scores.set(docId, score);
    }
    return scores;
}
export function jaccard(a, b) {
    const sa = new Set(a);
    const sb = new Set(b);
    if (sa.size === 0 || sb.size === 0)
        return 0;
    let intersection = 0;
    for (const item of sa)
        if (sb.has(item))
            intersection += 1;
    return intersection / (sa.size + sb.size - intersection);
}
