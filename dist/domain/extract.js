import { contentFingerprint } from "../core/ids.js";
import { CATEGORIES, EXTRACTION_FIELDS, EXTRACTION_MINIMUM, getCategory } from "./taxonomy.js";
export const DESIGN_TERMS = [
    'layout', 'spacing', 'padding', 'margin', 'grid', 'align', 'hierarchy', 'whitespace',
    'typography', 'font', 'line-height', 'type scale', 'baseline',
    'color', 'contrast', 'palette', 'tint', 'shade', 'dark mode', 'theme',
    'component', 'variant', 'token', 'design system', 'component library',
    'motion', 'animation', 'transition', 'easing', 'duration', 'gesture',
    'radius', 'corner', 'shadow', 'elevation', 'border', 'divider',
    'gradient', 'noise', 'texture', 'blur', 'glow', 'opacity',
    'accessib', 'aria', 'focus', 'screen reader', 'wcag', 'a11y',
    'responsive', 'breakpoint', 'viewport', 'media query', 'adaptive',
    'icon', 'illustration', 'svg', 'asset',
    'usability', 'heuristic', 'cognitive', 'affordance', 'feedback',
    '布局', '间距', '留白', '层级', '排版', '字体', '字号', '色彩', '对比度', '主题',
    '组件', '变体', '设计 token', '动效', '缓动', '圆角', '阴影', '渐变', '纹理',
    '无障碍', '焦点', '响应式', '断点', '图标', '素材', '可用性', '启发式',
];
export const MARKETING_TERMS = [
    'pricing', 'contact sales', 'sign up', 'get started', 'subscribe', 'free trial',
    'customers', 'case study', 'roi', 'revenue', 'processes billions', 'trusted by',
    'learn more', 'book a demo', 'talk to sales',
];
export const MIN_DESIGN_TERMS = 3;
/** 设计相关度 = 设计词命中数 / 营销词命中数 / 千字密度；阈值是硬门槛，不靠模型感觉。 */
export function designRelevance(text, minTerms = MIN_DESIGN_TERMS) {
    const low = text.toLowerCase();
    const hits = [...new Set(DESIGN_TERMS.filter((term) => low.includes(term)))].sort();
    const marketing = [...new Set(MARKETING_TERMS.filter((term) => low.includes(term)))].sort();
    return {
        design_terms: hits,
        design_term_count: hits.length,
        marketing_terms: marketing,
        density_per_1k: Math.round((hits.length * 1000 * 100) / Math.max(low.length, 1)) / 100,
        relevant: hits.length >= minTerms && marketing.length <= 2,
    };
}
function scoreAll(text, heading = '') {
    const blob = `${heading} ${text}`.toLowerCase();
    const headingLow = heading.toLowerCase();
    const out = {};
    for (const [key, category] of Object.entries(CATEGORIES)) {
        const matched = category.keywords.filter((kw) => blob.includes(kw.toLowerCase()));
        if (matched.length === 0)
            continue;
        let score = matched.reduce((sum, kw) => sum + (headingLow.includes(kw.toLowerCase()) ? 2 : 1), 0);
        score += 0.15 * Math.max(...matched.map((kw) => kw.length));
        out[key] = { score, matched };
    }
    return out;
}
/** 关键词分类；同一文本永远得到同一分类。 */
export function classify(text, heading = '') {
    const scores = scoreAll(text, heading);
    const entries = Object.entries(scores);
    if (entries.length === 0)
        return { category: 'uiux_principles', score: 0, matched: [] };
    let bestKey = entries[0]?.[0];
    let best = entries[0]?.[1];
    for (const [key, value] of entries)
        if (value.score > best.score) {
            bestKey = key;
            best = value;
        }
    const total = entries.reduce((sum, [, value]) => sum + value.score, 0) || 1;
    return { category: bestKey, score: Math.round((best.score / total) * 1000) / 1000, matched: best.matched };
}
/** 领域先验：资源声明的主分类进入前二时采用它，避免“游戏 HUD”被分到 web_ui。 */
export function classifyWithPrior(text, heading, primaryCategory) {
    const scores = scoreAll(text, heading);
    const entries = Object.entries(scores);
    if (entries.length === 0)
        return { category: primaryCategory, score: 0, matched: [], classification_source: 'fallback_primary' };
    entries.sort((a, b) => b[1].score - a[1].score);
    const total = entries.reduce((sum, [, value]) => sum + value.score, 0) || 1;
    const topKeys = entries.slice(0, 2).map(([key]) => key);
    if (topKeys.includes(primaryCategory)) {
        const hit = scores[primaryCategory];
        return { category: primaryCategory, score: Math.round((hit.score / total) * 1000) / 1000, matched: hit.matched, classification_source: 'domain_prior' };
    }
    const [bestKey, best] = entries[0];
    return { category: bestKey, score: Math.round((best.score / total) * 1000) / 1000, matched: best.matched, classification_source: 'keyword' };
}
export function firstSentences(text, limit = 240) {
    const parts = text.trim().split(/(?<=[。！？.!?])\s+/);
    let out = '';
    for (const part of parts) {
        if (!part)
            continue;
        out = `${out} ${part}`.trim();
        if (out.length >= limit)
            break;
    }
    return out.slice(0, limit);
}
export function buildUnit(section, input) {
    const { resource, category, score, matched } = input;
    const knowledge = Object.fromEntries(EXTRACTION_FIELDS.map((field) => [field, '']));
    knowledge.core_principle = firstSentences(section.text);
    const normative = /(should|must|recommend|建议|应当|必须|不要|避免|prefer|avoid)/i.test(section.text);
    if (normative)
        knowledge.applicable_context = '正文给出显式约束或建议的场合（文本推断，未做任务验证）';
    else if (section.heading)
        knowledge.applicable_context = `原文小节语境：${section.heading.slice(0, 80)}`;
    if (/(\d+(\.\d+)?\s*(px|dp|sp|rem|em|%))/.test(section.text)) {
        knowledge.layout_rule = `正文包含具体尺寸/间距数值：${(section.text.match(/\d+(?:\.\d+)?\s*(?:px|dp|sp|rem|em|%)/g) ?? []).slice(0, 6).join(', ')}`;
    }
    if (/#(?:[0-9a-f]{3}|[0-9a-f]{6})\b|rgb\(|hsl\(/i.test(section.text)) {
        knowledge.color_rule = `正文包含颜色值：${(section.text.match(/#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b|rgba?\([^)]*\)|hsla?\([^)]*\)/g) ?? []).slice(0, 4).join(', ')}`;
    }
    if (/(gradient|渐变|noise|噪|blur|光晕|shadow|纹理)/i.test(section.text))
        knowledge.background_method = '正文涉及渐变/噪点/光影等背景手法的处理方式';
    if (/(contrast|accessible|wcag|aria|无障碍|对比度)/i.test(section.text))
        knowledge.a11y_requirement = '正文涉及可访问性或对比度要求（具体阈值需回查原文核对）';
    if (/(animation|transition|easing|动效|缓动)/i.test(section.text))
        knowledge.interaction_rule = '正文涉及动效或过渡的实现/时长说明';
    if (/(performance|latency|jank|fps|性能|卡顿)/i.test(section.text))
        knowledge.performance_note = '正文涉及性能或流畅度约束';
    if (/(don't|avoid|never|反模式|避免|错误做法)/i.test(section.text))
        knowledge.anti_pattern = '正文提到应当避免的做法（原文措辞，未做效果验证）';
    knowledge.source_ref = resource.url;
    knowledge.license_note = resource.license_notes;
    const level = knowledge.core_principle && normative ? 'L2' : 'L1';
    knowledge.evidence_level = level;
    const filled = EXTRACTION_FIELDS.filter((field) => knowledge[field]);
    const complete = EXTRACTION_MINIMUM.every((field) => knowledge[field]);
    const relevance = designRelevance(section.text, input.minDesignTerms ?? MIN_DESIGN_TERMS);
    return {
        category,
        relevance,
        category_score: score,
        matched_keywords: [...matched],
        heading: section.heading,
        text: section.text,
        knowledge,
        fields_filled: filled,
        extraction_gaps: EXTRACTION_FIELDS.filter((field) => !knowledge[field]),
        level,
        ready_to_ingest: complete && relevance.relevant,
        content_hash: contentFingerprint(section.text),
    };
}
export function summarizeUnit(unit, resource) {
    const category = getCategory(unit.category);
    return {
        topic: unit.category,
        subtopic: unit.heading.slice(0, 120),
        title: (unit.heading || resource.name).slice(0, 160),
        content: unit.text,
        summary: (unit.knowledge.core_principle ?? '').slice(0, 400),
        metadata: {
            secondary_categories: resource.secondary_categories.filter((key) => key !== unit.category),
            resource_id: resource.resource_id,
            category_label: category.label,
            category_score: unit.category_score,
            matched_keywords: unit.matched_keywords,
            extraction: unit.knowledge,
            extraction_gaps: unit.extraction_gaps,
            fields_filled: unit.fields_filled,
        },
    };
}
