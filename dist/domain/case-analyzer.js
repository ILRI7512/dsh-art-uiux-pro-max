import { sha256Hex } from "../core/ids.js";
import { CATEGORY_KEYS } from "./taxonomy.js";
const HEX_RE = /#(?:[0-9a-fA-F]{3}){1,2}\b/g;
const FONT_RE = /font-family\s*:\s*([^;"'}]+)/gi;
const SIZE_RE = /font-size\s*:\s*([\d.]+)(px|rem|em)/gi;
const SPACE_RE = /(?:gap|padding|margin)(?:-\w+)?\s*:\s*([\d.]+)(px|rem)/gi;
const RADIUS_RE = /border-radius\s*:\s*([\d.]+)(px|rem|%)/gi;
const SHADOW_RE = /box-shadow\s*:\s*([^;"'}]+)/gi;
const GRADIENT_RE = /(linear-gradient|radial-gradient|conic-gradient)\s*\(/gi;
const DURATION_RE = /(?:transition|animation)(?:-duration)?\s*:\s*([^;"'}]+)/gi;
const MQ_RE = /@media[^{]{0,120}\{/gi;
const MAXW_RE = /max-width\s*:\s*([\d.]+)(px|rem)/gi;
const TECH_FINGERPRINTS = {
    'next.js': ['_next/static', '__NEXT_DATA__', '/_next/'],
    react: ['data-reactroot', 'react-dom', 'react.production'],
    vue: ['vue.js', 'data-v-', '__VUE__'],
    tailwind: ['tailwindcss', 'class="tw-'],
    'styled-components': ['styled-components', 'data-styled'],
    svelte: ['svelte-', '__svelte'],
    wordpress: ['wp-content', 'wp-includes'],
    gatsby: ['gatsby-', '___gatsby'],
};
function count(text, regex) {
    return [...text.matchAll(regex)].length;
}
function top(counter, n = 6) {
    return [...counter.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, n);
}
function addCounter(counter, key) {
    counter.set(key, (counter.get(key) ?? 0) + 1);
}
export function analyzeHtml(html, input) {
    const analysis = {
        url: input.url,
        product: input.product,
        platform: input.platform ?? 'web',
        tech_stack: [],
        sections: {},
        metrics: {},
        content_hash: sha256Hex(html),
    };
    const add = (section, statement, kind, confidence, basis) => {
        ;
        (analysis.sections[section] ??= []).push({ statement, kind, confidence, basis });
    };
    const low = html.toLowerCase();
    for (const [tech, marks] of Object.entries(TECH_FINGERPRINTS)) {
        if (marks.some((mark) => low.includes(mark.toLowerCase())))
            analysis.tech_stack.push(tech);
    }
    add('Layout Analysis', `检出技术栈指纹: ${analysis.tech_stack.join(', ') || '未检出'}`, 'fact', 0.8, 'HTML 中的静态指纹，非运行时确认');
    const colors = new Map();
    for (const match of html.matchAll(HEX_RE))
        addCounter(colors, (match[0] ?? '').toLowerCase());
    if (colors.size > 0) {
        const ranked = top(colors, 8);
        analysis.metrics.top_colors = ranked;
        add('Color Analysis', `页面出现频次最高的色值: ${ranked.map(([c, n]) => `${c}×${n}`).join(', ')}`, 'fact', 0.9, '正则统计 HTML/CSS 文本中的十六进制色值');
        add('Color Analysis', `文本中出现 ${colors.size} 种不同色值（含主题变量与第三方样式）`, 'fact', 0.7, '色值计数，含非品牌色');
        if (colors.size > 60)
            add('Color Analysis', '色值数量偏多，可能缺少统一的色彩约束层', 'inference', 0.4, '仅以色值计数推断，未核对设计 token 体系');
    }
    const gradients = [...html.matchAll(GRADIENT_RE)].map((m) => (m[1] ?? '').toLowerCase());
    const shadows = [...html.matchAll(SHADOW_RE)];
    if (gradients.length > 0 || shadows.length > 0) {
        add('Background Analysis', `渐变出现 ${gradients.length} 次、阴影规则 ${shadows.length} 条`, 'fact', 0.85, 'CSS 文本计数');
        if (gradients.length > 0) {
            const kinds = new Map();
            for (const kind of gradients)
                addCounter(kinds, kind);
            add('Background Analysis', `渐变类型分布: ${top(kinds).map(([k, v]) => `${k}×${v}`).join(', ')}`, 'fact', 0.8, 'CSS 关键字计数');
        }
    }
    if (/(noise|fractalNoise|feTurbulence|base64.*png)/i.test(html)) {
        add('Background Analysis', '疑似包含噪点/纹理层（噪声函数或内嵌位图）', 'inference', 0.45, '关键字命中，未做视觉确认');
    }
    const fonts = new Map();
    for (const match of html.matchAll(FONT_RE))
        addCounter(fonts, (match[1] ?? '').trim().replace(/^['"]|['"]$/g, ''));
    const sizes = new Map();
    for (const match of html.matchAll(SIZE_RE))
        addCounter(sizes, `${match[1]}${match[2]}`);
    if (fonts.size > 0) {
        const ranked = top(fonts, 5);
        analysis.metrics.font_families = ranked;
        add('Typography Analysis', `字体族: ${ranked.map(([f, n]) => `${f}×${n}`).join(', ')}`, 'fact', 0.85, 'font-family 声明统计');
    }
    if (sizes.size > 0) {
        const ranked = top(sizes, 10);
        analysis.metrics.font_sizes = ranked;
        add('Typography Analysis', `字号档位: ${ranked.map(([s, n]) => `${s}×${n}`).join(', ')}`, 'fact', 0.85, 'font-size 声明统计');
        const pxSizes = new Set([...html.matchAll(SIZE_RE)].filter((m) => m[2] === 'px').map((m) => Number(m[1])));
        if (pxSizes.size >= 6)
            add('Typography Analysis', `px 字号档位 ${pxSizes.size} 档，疑似缺少收敛的排版比例尺`, 'inference', 0.4, '档位数量启发式，需对照设计系统确认');
    }
    const mediaQueries = count(html, MQ_RE);
    const maxWidths = new Map();
    for (const match of html.matchAll(MAXW_RE))
        addCounter(maxWidths, `${match[1]}${match[2]}`);
    const gaps = new Map();
    for (const match of html.matchAll(SPACE_RE))
        addCounter(gaps, `${match[1]}${match[2]}`);
    analysis.metrics.media_queries = mediaQueries;
    analysis.metrics.max_widths = top(maxWidths, 5);
    analysis.metrics.spacing = top(gaps, 8);
    add('Layout Analysis', `响应式断点 ${mediaQueries} 个；容器最大宽度档位: ${top(maxWidths, 4).map(([w, n]) => `${w}×${n}`).join(', ') || '未检出'}`, 'fact', 0.8, '@media 与 max-width 声明统计');
    if (gaps.size > 0)
        add('Layout Analysis', `间距取值高频档位: ${top(gaps, 8).map(([g, n]) => `${g}×${n}`).join(', ')}`, 'fact', 0.75, 'gap/padding/margin 声明统计');
    add('Layout Analysis', '信息重心判断需要真实渲染截图，本工具未做渲染，因此不给结论', 'fact', 1, '能力边界声明');
    const radii = new Map();
    for (const match of html.matchAll(RADIUS_RE))
        addCounter(radii, `${match[1]}${match[2]}`);
    if (radii.size > 0) {
        analysis.metrics.radius = top(radii, 5);
        add('Component Analysis', `圆角档位: ${top(radii, 5).map(([r, n]) => `${r}×${n}`).join(', ')}`, 'fact', 0.8, 'border-radius 声明统计');
    }
    const durations = [...html.matchAll(DURATION_RE)].map((m) => (m[1] ?? '').trim()).filter((d) => /\d/.test(d));
    if (durations.length > 0)
        add('Interaction Analysis', `过渡/动画声明 ${durations.length} 条，示例: ${durations.slice(0, 8).join('; ')}`, 'fact', 0.8, 'CSS 文本统计');
    if (low.includes('prefers-reduced-motion'))
        add('Interaction Analysis', '声明了 prefers-reduced-motion 适配', 'fact', 0.95, '媒体查询命中');
    else
        add('Interaction Analysis', '未检出 prefers-reduced-motion 适配（可能在其他样式表）', 'inference', 0.4, '仅基于当前抓取的 HTML/CSS');
    const aria = count(html, /aria-[a-z]+=/gi);
    const roles = count(html, /role="[a-z]+"/gi);
    const images = html.match(/<img\b[^>]*>/gi) ?? [];
    const withAlt = images.filter((tag) => /\balt\s*=/i.test(tag));
    analysis.metrics.aria_attrs = aria;
    analysis.metrics.roles = roles;
    analysis.metrics.img_total = images.length;
    analysis.metrics.img_with_alt = withAlt.length;
    add('Accessibility Analysis', `aria 属性 ${aria} 个、role ${roles} 个；img ${images.length} 张，其中带 alt ${withAlt.length} 张（${images.length ? Math.round((withAlt.length / images.length) * 100) : 0}%）`, 'fact', 0.85, '静态标记统计，不等于无障碍达标');
    add('Accessibility Analysis', '对比度、焦点顺序、屏幕阅读器表现需要真实渲染与工具检测，本工具未测', 'fact', 1, '能力边界声明');
    if (low.includes('skip') && low.includes('content'))
        add('Accessibility Analysis', '疑似存在跳转到主内容的 skip link', 'inference', 0.5, '关键字命中');
    add('Visual Language', '整体风格判断（如极简/拟物/高对比）依赖视觉主观判断，需人工或视觉模型复核，本工具不下结论', 'fact', 1, '能力边界声明');
    return analysis;
}
export const SECTION_TO_CATEGORY = {
    'Layout Analysis': 'web_ui',
    'Color Analysis': 'color_system',
    'Background Analysis': 'background_design',
    'Typography Analysis': 'visual_aesthetics',
    'Component Analysis': 'design_system',
    'Interaction Analysis': 'motion_interaction',
    'Accessibility Analysis': 'ui_quality',
    'Visual Language': 'visual_aesthetics',
};
/** 只有 fact 才能作为可迁移规则入库；inference 标 L1；opinion 不入库。 */
export function unitsFromCase(analysis, resource) {
    const units = [];
    const structure = Object.entries(analysis.sections).filter(([, items]) => items.length > 0).map(([key, items]) => `${key} ${items.length} 条`).join('；');
    units.push({
        title: `${analysis.product} · 案例画像`,
        content: `${analysis.product} 案例画像：平台 ${analysis.platform}；技术栈 ${analysis.tech_stack.join('/') || '未检出'}；证据构成 ${Object.entries(analysis.sections).map(([key, items]) => `${key}=${items.length}`).join(', ')}；分节 ${structure}`,
        category: resource.primary_category,
        level: 'L1',
        kind: 'inference',
        confidence: 0.45,
        basis: '案例画像（由页面信号归纳，非实测）',
        case: analysis.product,
        url: analysis.url,
        content_hash: sha256Hex(`${analysis.product}${analysis.url}profile`),
        resource_id: resource.resource_id,
    });
    for (const [section, items] of Object.entries(analysis.sections)) {
        const category = SECTION_TO_CATEGORY[section] ?? 'uiux_principles';
        if (!CATEGORY_KEYS.includes(category))
            continue;
        for (const evidence of items) {
            if (evidence.kind === 'opinion')
                continue;
            if (evidence.basis.startsWith('能力边界声明'))
                continue;
            const level = evidence.kind === 'fact' ? 'L2' : 'L1';
            const text = `${section}｜${evidence.statement}`;
            units.push({
                title: `${analysis.product} · ${section}`,
                content: text,
                category,
                level,
                kind: evidence.kind,
                confidence: evidence.confidence,
                basis: evidence.basis,
                case: analysis.product,
                url: analysis.url,
                content_hash: sha256Hex(text),
                resource_id: resource.resource_id,
            });
        }
    }
    return units;
}
export function numericRules(units) {
    const out = {};
    for (const unit of units) {
        for (const match of unit.content.matchAll(/(\d+(?:\.\d+)?)\s*(px|rem|%)/g)) {
            const key = `${unit.category}|${match[2]}`;
            (out[key] ??= []).push({ url: unit.url, value: Number(match[1]) });
        }
    }
    return out;
}
export function compareWithExisting(rules, existing) {
    const conflicts = [];
    for (const chunk of existing) {
        const text = String(chunk.content ?? '');
        for (const match of text.matchAll(/(\d+(?:\.\d+)?)\s*(px|rem|%)/g)) {
            const key = `${String(chunk.topic)}|${match[2]}`;
            for (const candidate of rules[key] ?? []) {
                if (Math.abs(candidate.value - Number(match[1])) > 0.01) {
                    conflicts.push({
                        kind: 'numeric_mismatch',
                        key,
                        source_a: chunk.source_url,
                        value_a: Number(match[1]),
                        source_b: candidate.url,
                        value_b: candidate.value,
                        note: '仅记录差异，适用条件需人工判定；不覆盖任何一方',
                    });
                }
            }
        }
    }
    return conflicts;
}
