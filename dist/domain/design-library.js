/**
 * 设计智能库：88 风格 / 192 调色板 / 74 字体搭配 / 192 产品配方 / 195 规范。
 *
 * 数据来自 dsh-ui-ux-pro-max v1.4.1（MIT），其上游为
 * nextlevelbuilder/ui-ux-pro-max-skill@56ea9cf；随包静态发布，不联网更新。
 * 检索是本仓库自己的 BM25 实现，中文查询经领域别名扩展；不复制上游代码。
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { resolveArtRoot } from "../core/paths.js";
import { tokenize } from "../infra/tokenizer.js";
import { ValidationError } from "../core/errors.js";
export const LIBRARY_DOMAINS = ['style', 'color', 'chart', 'landing', 'product', 'ux', 'typography', 'react', 'web'];
let cachedLibrary = null;
let cachedAliases = null;
const indexes = new Map();
function readJson(name) {
    const path = join(resolveArtRoot(), 'resources', name);
    return JSON.parse(readFileSync(path, 'utf8'));
}
export function library() {
    if (!cachedLibrary)
        cachedLibrary = readJson('design-library.json');
    return cachedLibrary;
}
export function aliases() {
    if (!cachedAliases)
        cachedAliases = readJson('design-aliases.json');
    return cachedAliases;
}
const CJK = /[\u4e00-\u9fff]/;
/** 确定性中文扩展：命中领域词就追加英文等价词；单字查询只用短词典。 */
export function expandQuery(query) {
    if (!CJK.test(query))
        return { query, hits: [] };
    const data = aliases();
    const hits = [];
    const extra = [];
    if (query.replace(/[^\u4e00-\u9fff]/g, '').length === 1) {
        for (const [key, values] of Object.entries(data.short)) {
            if (query.includes(key)) {
                hits.push(key);
                extra.push(...values);
            }
        }
    }
    if (hits.length === 0) {
        for (const [key, values] of Object.entries(data.aliases)) {
            if (query.includes(key)) {
                hits.push(key);
                extra.push(...values);
            }
        }
    }
    if (extra.length === 0)
        return { query, hits: [] };
    return { query: `${query} ${[...new Set(extra)].join(' ')}`, hits };
}
class Bm25Index {
    docs;
    tokens;
    lengths;
    avgLength;
    idf = new Map();
    constructor(docs) {
        this.docs = docs;
        this.tokens = docs.map((row) => tokenize(Object.values(row).join(' ')));
        this.lengths = this.tokens.map((tokens) => tokens.length);
        this.avgLength = this.lengths.reduce((sum, value) => sum + value, 0) / Math.max(docs.length, 1) || 1;
        const df = new Map();
        for (const tokens of this.tokens) {
            for (const token of new Set(tokens))
                df.set(token, (df.get(token) ?? 0) + 1);
        }
        for (const [token, count] of df) {
            this.idf.set(token, Math.log((docs.length - count + 0.5) / (count + 0.5) + 1));
        }
    }
    score(query) {
        const queryTokens = [...new Set(tokenize(query))];
        const scores = [];
        for (let index = 0; index < this.docs.length; index += 1) {
            const docTokens = this.tokens[index];
            const tf = new Map();
            for (const token of docTokens)
                tf.set(token, (tf.get(token) ?? 0) + 1);
            let score = 0;
            for (const token of queryTokens) {
                const idf = this.idf.get(token);
                if (idf === undefined)
                    continue;
                const freq = tf.get(token) ?? 0;
                if (freq === 0)
                    continue;
                const dl = this.lengths[index];
                score += idf * ((freq * 2.5) / (freq + 1.5 * (1 - 0.75 + 0.75 * dl / this.avgLength)));
            }
            if (score > 0)
                scores.push({ index, score });
        }
        return scores.sort((a, b) => b.score - a.score);
    }
}
function indexFor(domain) {
    const existing = indexes.get(domain);
    if (existing)
        return existing;
    const rows = library().domains[domain] ?? [];
    const created = new Bm25Index(rows);
    indexes.set(domain, created);
    return created;
}
function isDeprecated(row) {
    return String(row.Status ?? '').toLowerCase() === 'deprecated';
}
export function searchDomain(domain, query, limit = 5, includeDeprecated = false) {
    if (!LIBRARY_DOMAINS.includes(domain))
        throw new ValidationError(`未知设计库域: ${domain}`);
    const expanded = expandQuery(query);
    const include = includeDeprecated || /\b(legacy|deprecated)\b/i.test(query);
    return indexFor(domain).score(expanded.query)
        .filter(({ index }) => include || !isDeprecated(indexFor(domain).docs[index]))
        .slice(0, limit)
        .map(({ index, score }) => ({ row: indexFor(domain).docs[index], score: Math.round(score * 1000) / 1000, domain }));
}
function splitList(value) {
    return String(value ?? '').split(/\s*[+,]\s*/).map((item) => item.trim()).filter(Boolean);
}
const COLOR_FIELDS = [
    ['Primary', 'primary'], ['On Primary', 'on-primary'], ['Secondary', 'secondary'],
    ['On Secondary', 'on-secondary'], ['Accent', 'accent'], ['On Accent', 'on-accent'],
    ['Background', 'background'], ['Foreground', 'foreground'], ['Card', 'card'],
    ['Card Foreground', 'card-foreground'], ['Muted', 'muted'], ['Muted Foreground', 'muted-foreground'],
    ['Border', 'border'], ['Destructive', 'destructive'], ['On Destructive', 'on-destructive'], ['Ring', 'ring'],
];
export function colorTokens(row) {
    return Object.fromEntries(COLOR_FIELDS.filter(([key]) => row[key]).map(([key, token]) => [token, row[key]]));
}
function clampKnob(value) {
    if (value === undefined || value === null || value === '')
        return null;
    const number = Math.round(Number(value));
    if (!Number.isFinite(number) || number < 1 || number > 10)
        throw new ValidationError('旋钮必须是 1-10 的整数');
    return number;
}
function spacingFor(density) {
    if (density === null)
        return [4, 8, 12, 16, 24, 32, 48, 64];
    if (density >= 8)
        return [2, 4, 6, 8, 12, 16, 24, 32];
    if (density <= 3)
        return [8, 12, 16, 24, 32, 48, 64, 96];
    return [4, 8, 12, 16, 24, 32, 48, 64];
}
const GENERIC_UX = ['Accessibility', 'Layout', 'Forms', 'Feedback', 'Navigation', 'Interaction'];
const SEVERITY = { Critical: 0, High: 1, Medium: 2, Low: 3 };
export function recommend(input) {
    if (!input.query?.trim())
        throw new ValidationError('query 不能为空');
    const variance = clampKnob(input.variance);
    const motion = clampKnob(input.motion);
    const density = clampKnob(input.density);
    const productHits = searchDomain('product', input.query, 3);
    const category = productHits[0]?.row['Product Type'] ?? 'General';
    const reasoning = library().reasoning.find((row) => row.UI_Category === category)
        ?? library().reasoning.find((row) => String(row.UI_Category).toLowerCase().includes(category.toLowerCase()))
        ?? {};
    const stylePriority = splitList(reasoning.Style_Priority);
    if (variance !== null && variance >= 8)
        stylePriority.unshift('bold', 'high contrast');
    const styleHits = searchDomain('style', `${input.query} ${stylePriority.slice(0, 2).join(' ')}`, 5);
    const styles = styleHits.map(({ row, score }, index) => ({
        rank: index + 1,
        id: row['Style ID'] ?? '',
        name: row['Style Category'] ?? '',
        type: row.Type ?? '',
        score,
        keywords: row.Keywords ?? '',
        best_for: row['Best For'] ?? '',
        avoid: row['Do Not Use For'] ?? '',
        effects: row['Effects & Animation'] ?? '',
        accessibility: row.Accessibility ?? '',
        complexity: row.Complexity ?? '',
        status: row.Status ?? '',
    }));
    const colorRow = (library().domains.color ?? []).find((row) => row['Product Type'] === category)
        ?? searchDomain('color', input.query, 1)[0]?.row ?? {};
    const typography = searchDomain('typography', input.query, 1)[0]?.row
        ?? searchDomain('typography', stylePriority.join(' '), 1)[0]?.row ?? {};
    const landing = searchDomain('landing', input.query, 1)[0]?.row
        ?? searchDomain('landing', String(reasoning.Recommended_Pattern ?? ''), 1)[0]?.row ?? {};
    const uxHits = searchDomain('ux', input.query, 6);
    const seen = new Set(uxHits.map(({ row }) => `${row.Category}|${row.Issue}`));
    if (uxHits.length < 4) {
        const fallback = (library().domains.ux ?? [])
            .slice()
            .sort((a, b) => {
            const ai = GENERIC_UX.indexOf(a.Category ?? '');
            const bi = GENERIC_UX.indexOf(b.Category ?? '');
            return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi) || (SEVERITY[a.Severity ?? ''] ?? 9) - (SEVERITY[b.Severity ?? ''] ?? 9);
        });
        for (const row of fallback) {
            if (seen.size >= 6)
                break;
            const key = `${row.Category}|${row.Issue}`;
            if (seen.has(key))
                continue;
            seen.add(key);
            uxHits.push({ row, score: 0, domain: 'ux' });
        }
    }
    return {
        projectName: input.projectName || input.query,
        category,
        styles,
        palette: { tokens: colorTokens(colorRow), notes: colorRow.Notes ?? '', source_row: colorRow['Product Type'] ?? '' },
        typography: {
            pairing: typography['Font Pairing Name'] ?? '',
            heading: typography['Heading Font'] ?? 'Inter',
            body: typography['Body Font'] ?? 'Inter',
            mood: typography['Mood/Style Keywords'] ?? '',
            css_import: typography['CSS Import'] ?? '',
            tailwind: typography['Tailwind Config'] ?? '',
            notes: typography.Notes ?? '',
        },
        landing: {
            pattern: landing['Pattern Name'] ?? reasoning.Recommended_Pattern ?? '',
            sections: landing['Section Order'] ?? '',
            cta: landing['Primary CTA Placement'] ?? '',
            color_strategy: landing['Color Strategy'] ?? '',
            conversion: landing['Conversion Optimization'] ?? '',
        },
        key_effects: styles[0]?.effects || reasoning.Key_Effects || '',
        anti_patterns: splitList(reasoning.Anti_Patterns),
        decision_rules: splitList(reasoning.Decision_Rules),
        reasoning: {
            color_mood: reasoning.Color_Mood ?? '',
            typography_mood: reasoning.Typography_Mood ?? '',
            severity: reasoning.Severity ?? '',
            confidence: reasoning.Confidence ?? '',
            style_priority: stylePriority,
        },
        ux_guidelines: uxHits.map(({ row, score }) => ({
            category: row.Category ?? '', issue: row.Issue ?? '', platform: row.Platform ?? '',
            description: row.Description ?? '', do: row.Do ?? '', dont: row["Don't"] ?? '', severity: row.Severity ?? '', score,
        })),
        knobs: {
            variance: variance ?? 5, motion: motion ?? 5, density: density ?? 5,
            spacing_scale_px: spacingFor(density),
            motion_note: motion !== null && motion >= 7 ? '可加入编排式动效；必须提供 prefers-reduced-motion 兜底' : '动效保持克制，优先状态反馈',
        },
        provenance: {
            library: 'dsh-ui-ux-pro-max v1.4.1 (MIT)',
            upstream: library().upstream,
            upstreamRef: library().upstreamRef,
            note: '静态数据快照；调色板与规则未经本项目逐条重测，W3C 对比度仍需按 art_design_system 实算',
        },
    };
}
const PLATFORM_DOMAINS = {
    web: ['ux', 'web'],
    mobile: ['ux', 'web'],
    desktop: ['ux', 'web'],
    'react-native': ['ux', 'react'],
    flutter: ['ux', 'react'],
};
export function review(input) {
    if (!input.target?.trim())
        throw new ValidationError('target 不能为空');
    const platform = input.platform ?? 'web';
    if (!PLATFORM_DOMAINS[platform])
        throw new ValidationError(`未知 platform: ${platform}`);
    const limit = Math.max(1, Math.min(30, Number(input.maxRules ?? 10)));
    const domains = PLATFORM_DOMAINS[platform];
    const found = [];
    for (const domain of domains) {
        for (const hit of searchDomain(domain, input.target, 20)) {
            const rowPlatform = String(hit.row.Platform ?? 'All').toLowerCase();
            if (rowPlatform !== 'all' && rowPlatform !== platform && !(platform === 'react-native' && rowPlatform === 'mobile'))
                continue;
            found.push({ ...hit, domain });
        }
    }
    const seen = new Set();
    const rules = found
        .filter(({ row }) => {
        const key = `${row.Category}|${row.Issue}`;
        if (seen.has(key))
            return false;
        seen.add(key);
        return true;
    })
        .sort((a, b) => (SEVERITY[a.row.Severity ?? ''] ?? 9) - (SEVERITY[b.row.Severity ?? ''] ?? 9))
        .slice(0, limit)
        .map(({ domain, row, score }) => ({
        domain, category: row.Category ?? '', issue: row.Issue ?? '', platform: row.Platform ?? '',
        severity: row.Severity ?? 'Medium', description: row.Description ?? '',
        do: row.Do ?? '', dont: row["Don't"] ?? '',
        code_good: row['Code Example Good'] ?? '', code_bad: row['Code Example Bad'] ?? '', score,
    }));
    return {
        target: input.target, platform,
        rules,
        counts: {
            Critical: rules.filter((rule) => rule.severity === 'Critical').length,
            High: rules.filter((rule) => rule.severity === 'High').length,
            Medium: rules.filter((rule) => rule.severity === 'Medium').length,
            Low: rules.filter((rule) => rule.severity === 'Low').length,
        },
        checklist: [
            '主操作在首屏可见，且只有一个主 CTA',
            '所有输入有 label，错误信息与字段关联',
            '键盘可完成主流程，焦点可见且顺序合理',
            '触控目标 ≥44×44，文本对比度按 WCAG 实算',
            '加载/空/错误/禁用状态都有明确反馈',
            '尊重 prefers-reduced-motion',
            '小屏无横向溢出，长文本可换行',
            '图片有 alt，装饰图 alt=""',
            '动画只改变合成属性，避免布局抖动',
            '交付前用真实设备/浏览器复核，不只看静态代码',
        ],
        warnings: rules.length === 0 ? ['没有命中规则：目标描述可能缺少可检索的界面/交互关键词'] : [],
        provenance: { library: 'dsh-ui-ux-pro-max v1.4.1 (MIT)', upstream: library().upstream, upstreamRef: library().upstreamRef },
    };
}
export function librarySearch(input) {
    if (!input.query?.trim())
        throw new ValidationError('query 不能为空');
    const limit = Math.max(1, Math.min(50, Number(input.maxResults ?? 8)));
    const domains = input.domain ? [input.domain] : LIBRARY_DOMAINS;
    for (const domain of domains)
        if (!LIBRARY_DOMAINS.includes(domain))
            throw new ValidationError(`未知设计库域: ${domain}`);
    const hits = domains.flatMap((domain) => searchDomain(domain, input.query, limit, input.includeDeprecated ?? false))
        .sort((a, b) => b.score - a.score)
        .slice(0, limit);
    return {
        query: input.query,
        expanded: expandQuery(input.query),
        count: hits.length,
        results: hits.map(({ domain, row, score }) => ({ domain, score, row })),
        warnings: hits.length === 0 ? ['设计库没有命中；可换用英文关键词或更具体的产品/风格名'] : [],
    };
}
export function librarySummary() {
    return {
        version: library().version,
        generated: library().generated,
        counts: library().counts,
        upstream: library().upstream,
        upstreamRef: library().upstreamRef,
        courses: LIBRARY_DOMAINS,
    };
}
