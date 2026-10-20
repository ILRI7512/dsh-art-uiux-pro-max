/** IR 指标最小实现；无答案查询返回 NaN，不伪装成 0。 */
export function precisionAtK(ranked, rel, k) {
    const top = ranked.slice(0, k);
    return top.length === 0 ? 0 : top.filter((doc) => (rel[doc] ?? 0) >= 1).length / top.length;
}
export function recallAtK(ranked, rel, k) {
    const targets = new Set(Object.entries(rel).filter(([, grade]) => grade >= 1).map(([doc]) => doc));
    if (targets.size === 0)
        return Number.NaN;
    const got = ranked.slice(0, k).filter((doc) => targets.has(doc));
    return got.length / targets.size;
}
export function mrrAtK(ranked, rel, k) {
    const index = ranked.slice(0, k).findIndex((doc) => (rel[doc] ?? 0) >= 2);
    return index < 0 ? 0 : 1 / (index + 1);
}
function dcg(gains) {
    return gains.reduce((sum, gain, index) => sum + (2 ** gain - 1) / Math.log2(index + 2), 0);
}
export function ndcgAtK(ranked, rel, k) {
    const gains = ranked.slice(0, k).map((doc) => rel[doc] ?? 0);
    const ideal = Object.values(rel).sort((a, b) => b - a).slice(0, k);
    const idcg = dcg(ideal);
    return idcg === 0 ? Number.NaN : dcg(gains) / idcg;
}
export function categoryPurity(ranked, expectedTopic, k) {
    const top = ranked.slice(0, k);
    return top.length === 0 ? 0 : top.filter((doc) => doc.topic === expectedTopic).length / top.length;
}
function mulberry32(seed) {
    let state = seed >>> 0;
    return () => {
        state = (state + 0x6d2b79f5) >>> 0;
        let t = state;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}
export function bootstrapDiff(a, b, iters = 2000, seed = 7) {
    const pairs = a.map((x, i) => [x, b[i]]).filter((pair) => typeof pair[0] === 'number' && typeof pair[1] === 'number' && !Number.isNaN(pair[0]) && !Number.isNaN(pair[1]));
    if (pairs.length === 0)
        return { mean_diff: 0, lo: 0, hi: 0, n: 0 };
    const random = mulberry32(seed);
    const diffs = [];
    for (let i = 0; i < iters; i += 1) {
        let sum = 0;
        for (let j = 0; j < pairs.length; j += 1) {
            const [x, y] = pairs[Math.floor(random() * pairs.length)];
            sum += x - y;
        }
        diffs.push(sum / pairs.length);
    }
    diffs.sort((x, y) => x - y);
    const mean = pairs.reduce((sum, [x, y]) => sum + (x - y), 0) / pairs.length;
    return { mean_diff: mean, lo: diffs[Math.floor(0.025 * iters)], hi: diffs[Math.floor(0.975 * iters) - 1], n: pairs.length };
}
export function mean(values) {
    const valid = values.filter((v) => !Number.isNaN(v));
    return valid.length === 0 ? Number.NaN : valid.reduce((a, b) => a + b, 0) / valid.length;
}
