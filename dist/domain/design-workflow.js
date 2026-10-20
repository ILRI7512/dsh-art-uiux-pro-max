/**
 * 七步设计工作流（可调用模块）：
 * route → retrieve → directions → design system → implement → audit → feedback。
 *
 * 没有真实测试就标 unverified；审美判断不得冒充可用性结论。
 */
import { sha256Hex } from "../core/ids.js";
import { ValidationError } from "../core/errors.js";
import { getCategory } from "./taxonomy.js";
export const TASK_TYPES = {
    android_native: { label: 'Android 原生应用', categories: ['android_ui', 'motion_interaction', 'design_system'] },
    web_page: { label: 'Web 网页', categories: ['web_ui', 'visual_aesthetics', 'ui_quality'] },
    admin_console: { label: '管理后台', categories: ['web_ui', 'design_system', 'ui_quality'] },
    fintech_terminal: { label: '金融终端', categories: ['financial_dashboard', 'color_system', 'ui_quality'] },
    game_ui: { label: '游戏界面', categories: ['game_ui', 'motion_interaction', 'visual_aesthetics'] },
    data_viz: { label: '数据可视化', categories: ['financial_dashboard', 'color_system', 'design_system'] },
    design_system: { label: '设计系统', categories: ['design_system', 'color_system', 'ui_quality'] },
    background_asset: { label: '背景与视觉资产', categories: ['background_design', 'color_system', 'visual_assets'] },
    ui_refactor: { label: '现有 UI 改造', categories: ['ui_quality', 'web_ui', 'android_ui'] },
};
const TASK_KEYWORDS = {
    android_native: ['android', 'compose', 'kotlin', 'app 首页', '移动端原生'],
    admin_console: ['后台', '管理台', 'console', 'dashboard 表格', '权限管理'],
    fintech_terminal: ['金融', '行情', 'k线', '持仓', 'ticker', '外汇', '交易终端'],
    game_ui: ['游戏', 'hud', '技能', '背包', '关卡'],
    data_viz: ['图表', '可视化', '指标', '趋势图'],
    design_system: ['设计系统', 'token', '组件库', '主题'],
    background_asset: ['背景', '渐变', '纹理', '光晕', '插画', '图标'],
    ui_refactor: ['改造', '重构', '审计', '优化现有', '翻新'],
    web_page: ['网页', '官网', '落地页', 'landing', 'saas 页面'],
};
export function routeTask(text) {
    const low = text.toLowerCase();
    let best = 'web_page';
    let bestHits = [];
    for (const [task, keywords] of Object.entries(TASK_KEYWORDS)) {
        const hits = keywords.filter((keyword) => low.includes(keyword.toLowerCase()));
        if (hits.length > bestHits.length) {
            best = task;
            bestHits = hits;
        }
    }
    return {
        task_type: best,
        categories: [...(TASK_TYPES[best]?.categories ?? [])],
        basis: bestHits.length > 0 ? `命中关键词 ${bestHits.join(', ')}` : '无关键词，默认按网页任务处理',
    };
}
const DIRECTIONS = {
    editorial_light: {
        name: 'Editorial Light（编辑部留白）',
        idea: '以阅读节奏为第一优先级，靠留白与字号对比建立秩序',
        style: '纸感浅底、低饱和、强排版层级',
        color: '暖白底 + 近黑字 + 单一强调色（饱和度中等）',
        type: '衬线大标题 + 无衬线正文，字号跨度 3 档以上',
        layout: '单栏窄容器，长段落，弱化卡片边界',
        background: '纯色或极轻纸纹，无渐变',
        interaction: '轻微淡入与下划线反馈，时长 120–180ms',
        fits: '内容型站点、品牌官网、长文阅读',
        drawbacks: '信息密度低，不适合高频操作台',
    },
    swiss_grid: {
        name: 'Swiss Grid（瑞士栅格）',
        idea: '用严格栅格与对齐制造秩序感，装饰最小化',
        style: '高对比黑白 + 一个功能色，几何化',
        color: '白底/黑字 + 单一功能色，色板极窄',
        type: '单一无衬线，字号档位收敛到 5 档',
        layout: '12 栏栅格，强对齐，模块化区块',
        background: '纯色，允许细网格线',
        interaction: '状态用位移/底色变化表达，避免阴影',
        fits: '设计系统文档、作品集、数据型展示页',
        drawbacks: '对细节容错低，字体基线错误会非常明显',
    },
    industrial_dense: {
        name: 'Industrial Dense（工业高密度）',
        idea: '为高频操作优化，牺牲呼吸感换信息密度与确定性',
        style: '深灰/蓝灰中性底，细边框分区',
        color: '低饱和中性色阶 + 状态语义色（涨/跌/警告）',
        type: '系统无衬线，等宽数字用于数值列',
        layout: '多栏密集布局，固定表头，紧凑行高',
        background: '无渐变，允许极细分割线',
        interaction: '即时反馈优先，动效短（≤100ms），避免大位移',
        fits: '交易终端、监控台、后台管理系统',
        drawbacks: '视觉疲劳风险高，长时使用需要降对比选项',
    },
    soft_brutalist: {
        name: 'Soft Brutalist（柔性粗野）',
        idea: '以强烈形制与直白结构建立记忆点，同时保证可读',
        style: '大圆角、粗描边、块面撞色',
        color: '2–3 个高明度撞色 + 白/黑基色',
        type: '大字号无衬线，紧凑行距',
        layout: '错位栅格，模块尺寸差异大',
        background: '纯色块面拼接，可用粗噪点纹理',
        interaction: '按压反馈明显，允许 180–240ms 缓动',
        fits: '工具类产品、年轻化 C 端、活动页',
        drawbacks: '易过度设计；高饱和色会增加无障碍风险',
    },
};
export const FORBIDDEN_DEFAULTS = ['玻璃拟态', '深色背景', '蓝紫渐变', '发光边框'];
export function proposeDirections(taskType, count = 3, exclude = FORBIDDEN_DEFAULTS) {
    if (!Number.isInteger(count) || count < 1)
        throw new ValidationError('count 必须是正整数');
    let order = ['editorial_light', 'swiss_grid', 'industrial_dense', 'soft_brutalist'];
    if (['fintech_terminal', 'admin_console', 'data_viz'].includes(taskType))
        order = ['industrial_dense', 'swiss_grid', 'editorial_light', 'soft_brutalist'];
    else if (taskType === 'game_ui')
        order = ['soft_brutalist', 'industrial_dense', 'swiss_grid', 'editorial_light'];
    return order.slice(0, Math.min(count, order.length)).map((key) => ({
        key,
        ...DIRECTIONS[key],
        excluded_defaults_checked: [...exclude],
    }));
}
// ---------------------------------------------------------------- 对比度
const HEX_RE = /#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b/;
export function hexValues(text) {
    return new Set([...text.matchAll(/#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b/g)].map((m) => `#${(m[1] ?? '').toLowerCase()}`));
}
function toRgb(color) {
    const match = HEX_RE.exec(color.trim());
    if (!match)
        throw new Error(`不是十六进制颜色: ${JSON.stringify(color)}`);
    let hex = match[1];
    if (hex.length === 3)
        hex = [...hex].map((c) => c + c).join('');
    return [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)];
}
export function relativeLuminance(color) {
    const channel = (value) => {
        const s = value / 255;
        return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    };
    const [r, g, b] = toRgb(color);
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}
export function contrastRatio(fg, bg) {
    const l1 = relativeLuminance(fg);
    const l2 = relativeLuminance(bg);
    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}
export const WCAG_MIN = { AA_normal: 4.5, AA_large: 3, AAA_normal: 7, AAA_large: 4.5, ui_component: 3 };
export function checkPalette(pairs) {
    return pairs.map(([pair, fg, bg]) => {
        try {
            const ratio = contrastRatio(fg, bg);
            return {
                pair, fg, bg, ratio: Math.round(ratio * 100) / 100,
                AA_normal: ratio >= WCAG_MIN.AA_normal,
                AA_large: ratio >= WCAG_MIN.AA_large,
                AAA_normal: ratio >= WCAG_MIN.AAA_normal,
                ui_component: ratio >= WCAG_MIN.ui_component,
                measured: true,
            };
        }
        catch (error) {
            return { pair, fg, bg, error: error instanceof Error ? error.message : String(error) };
        }
    });
}
export const TYPE_SCALE = [12, 14, 16, 20, 28, 40, 56];
export const SPACE_SCALE = [4, 8, 12, 16, 24, 32, 48, 64];
export const RADIUS_SCALE = [0, 4, 8, 12, 16];
const PRESETS = {
    editorial_light: { bg: '#faf8f4', fg: '#15130f', muted: '#6b6459', accent: '#8a4b2a', surface: '#ffffff', positive: '#1c6b3a', negative: '#a32118', warning: '#8a5a00', border: '#8d8a9e' },
    swiss_grid: { bg: '#ffffff', fg: '#0a0a0a', muted: '#5c5c5c', accent: '#d4351c', surface: '#f2f2f2', positive: '#146b32', negative: '#b32113', warning: '#8a5a00', border: '#7a7a7a' },
    industrial_dense: { bg: '#14171c', fg: '#e6e9ee', muted: '#9aa3af', accent: '#4c9aff', surface: '#1c2027', positive: '#4ade80', negative: '#f87171', warning: '#fbbf24', border: '#6b7484' },
    soft_brutalist: { bg: '#fffdf6', fg: '#121212', muted: '#5f5a4e', accent: '#ff5c38', surface: '#ffe9a8', positive: '#1d6b3a', negative: '#a82a1c', warning: '#8a5a00', border: '#8a7a5c' },
};
export function buildDesignSystem(directionKey, base = {}) {
    const palette = (PRESETS[directionKey] ?? PRESETS.swiss_grid);
    const colors = { ...palette, ...base };
    const pick = (key, fallback) => colors[key] ?? fallback;
    const fg = pick('fg', '#111111');
    const bg = pick('bg', '#ffffff');
    const pairs = [
        ['正文/背景', fg, bg],
        ['次要文字/背景', pick('muted', '#555555'), bg],
        ['强调色/背景', pick('accent', '#4c9aff'), bg],
        ['正文/卡片面', fg, pick('surface', '#f5f5f5')],
        ['涨/正向', pick('positive', '#1c6b3a'), bg],
        ['跌/负向', pick('negative', '#a32118'), bg],
        ['边框/卡片面', pick('border', '#888888'), pick('surface', '#f5f5f5')],
    ];
    const contrast = checkPalette(pairs);
    const failing = contrast.filter((item) => item.measured && !item.AA_normal && item.pair !== '边框/卡片面');
    const componentFailures = contrast.filter((item) => item.pair === '边框/卡片面' && !item.ui_component);
    return {
        direction: directionKey,
        tokens: {
            color: colors,
            type_scale_px: [...TYPE_SCALE],
            space_scale_px: [...SPACE_SCALE],
            radius_px: [...RADIUS_SCALE],
            shadow: ['0 1px 2px rgba(0,0,0,.06)', '0 8px 24px rgba(0,0,0,.10)'],
            motion: { fast_ms: 120, base_ms: 180, easing: 'cubic-bezier(.2,.8,.2,1)', reduced_motion: '支持 prefers-reduced-motion' },
        },
        component_states: ['default', 'hover', 'active', 'focus-visible', 'disabled', 'loading', 'error'],
        responsive: ['compact <600', 'medium 600–1023', 'expanded ≥1024'],
        a11y: ['焦点可见（≥3:1 轮廓对比）', '触控目标 ≥44×44', '不依赖颜色单独传达状态'],
        contrast,
        failing_pairs: failing,
        ui_component_failures: componentFailures,
        verified: false,
        note: '对比度为公式实算；其余项为设计约定，尚未经真实任务验证',
    };
}
export function tokensToCss(system) {
    const c = system.tokens.color;
    const lines = [':root {'];
    for (const [key, value] of Object.entries(c))
        lines.push(`  --color-${key}: ${value};`);
    system.tokens.type_scale_px.forEach((size, index) => lines.push(`  --text-${index}: ${size}px;`));
    system.tokens.space_scale_px.forEach((size, index) => lines.push(`  --space-${index}: ${size}px;`));
    system.tokens.radius_px.forEach((size, index) => lines.push(`  --radius-${index}: ${size}px;`));
    lines.push(`  --motion-fast: ${system.tokens.motion.fast_ms}ms;`);
    lines.push(`  --motion-base: ${system.tokens.motion.base_ms}ms;`);
    lines.push(`  --easing-standard: ${system.tokens.motion.easing};`);
    lines.push('}');
    return lines.join('\n');
}
// ---------------------------------------------------------------- 审计
export const AUDIT_ITEMS = [
    'visual_hierarchy', 'decoration', 'consistency', 'component_language',
    'background_readability', 'responsive_overflow', 'interaction_states',
    'accessibility', 'motion_performance', 'design_drift',
];
export function auditHtml(html, tokens) {
    const low = html.toLowerCase();
    const findings = [];
    const push = (item, status, detail, evidence = {}) => {
        findings.push({ item, status, detail, evidence });
    };
    const sizes = [...new Set([...html.matchAll(/font-size\s*:\s*([\d.]+)px/g)].map((m) => Number(m[1])))].sort((a, b) => a - b);
    push('visual_hierarchy', sizes.length >= 3 ? 'pass' : sizes.length > 0 ? 'warn' : 'unmeasured', `字号档位 ${sizes.length} 档${sizes.length ? `：${sizes.map((s) => `${s}px`).join(', ')}` : '（未在内联样式声明）'}`, { font_sizes: sizes });
    const shadows = (html.match(/box-shadow/g) ?? []).length;
    const gradients = (html.match(/gradient\(/g) ?? []).length;
    push('decoration', shadows + gradients > 12 ? 'warn' : 'pass', `阴影 ${shadows} 处、渐变 ${gradients} 处`, { shadows, gradients });
    const colors = hexValues(html);
    const families = new Set([...html.matchAll(/font-family\s*:\s*([^;"'}]+)/g)].map((m) => (m[1] ?? '').trim()));
    push('consistency', colors.size <= 12 ? 'pass' : 'warn', `色值 ${colors.size} 个、字体族 ${families.size} 种`, { colors: [...colors].sort(), font_families: [...families].sort() });
    const radii = [...new Set([...html.matchAll(/border-radius\s*:\s*([\d.]+)%?/g)].map((m) => m[1]))].sort();
    push('component_language', radii.length <= 4 ? 'pass' : 'warn', `圆角档位 ${radii.length} 档: ${radii.join(', ') || '未声明'}`, { radii });
    if (tokens) {
        const c = (tokens.color ?? {});
        const pairs = [['正文/背景', c.fg, c.bg], ['次要/背景', c.muted, c.bg]].filter((p) => Boolean(p[1] && p[2]));
        const results = checkPalette(pairs).filter((r) => r.measured);
        const worst = results.length > 0 ? Math.min(...results.map((r) => r.ratio)) : null;
        push('background_readability', worst === null ? 'unmeasured' : worst >= 4.5 ? 'pass' : 'fail', worst === null ? '未提供配色，无法实测' : `正文对比度最低 ${worst.toFixed(2)}:1`, { results });
    }
    else {
        push('background_readability', 'unmeasured', '未提供 token 配色，无法实测对比度');
    }
    const fixed = [...html.matchAll(/width\s*:\s*(\d{3,4})px/g)].map((m) => Number(m[1]));
    const overflow = fixed.filter((w) => w > 360);
    push('responsive_overflow', overflow.length > 0 ? 'warn' : 'pass', overflow.length > 0 ? `存在 ${overflow.length} 处固定宽度 >360px，小屏可能溢出` : '未发现明显固定宽溢出', { fixed_widths: fixed });
    const states = Object.fromEntries([':hover', ':focus', ':active', ':disabled', 'focus-visible'].map((state) => [state, low.split(state).length - 1]));
    const missing = Object.entries(states).filter(([, count]) => count === 0).map(([state]) => state);
    push('interaction_states', missing.length > 0 ? 'warn' : 'pass', missing.length > 0 ? `缺失状态: ${missing.join(', ')}` : '关键交互状态齐全', { states });
    const images = html.match(/<img\b[^>]*>/gi) ?? [];
    const withAlt = images.filter((tag) => /\balt\s*=/i.test(tag));
    const aria = (html.match(/aria-[a-z]+=/gi) ?? []).length;
    const ratio = images.length > 0 ? withAlt.length / images.length : 1;
    let a11yStatus = 'pass';
    let a11yNote = '静态标记齐全';
    if (images.length > 0 && ratio < 1) {
        a11yStatus = 'fail';
        a11yNote = '存在无 alt 的图片';
    }
    else if (aria === 0) {
        a11yStatus = 'warn';
        a11yNote = '无 aria 标注（可能缺语义角色）';
    }
    push('accessibility', a11yStatus, `${a11yNote}；img alt 覆盖 ${Math.round(ratio * 100)}%（${withAlt.length}/${images.length}），aria 属性 ${aria} 个`, { aria, img: images.length, with_alt: withAlt.length });
    const durations = [...html.matchAll(/transition[^;]*?(\d+)ms/g)].map((m) => Number(m[1]));
    const heavy = (html.match(/transition\s*:\s*(?:all|width|height|top|left)/gi) ?? []).length;
    push('motion_performance', heavy > 0 || durations.some((d) => d > 400) ? 'warn' : 'pass', `过渡时长 ${durations.length ? durations.join(', ') : '未声明'}；触发布局动画 ${heavy} 处`, { durations, layout_animations: heavy });
    if (tokens) {
        const declared = new Set(Object.values((tokens.color ?? {})).map((value) => value.toLowerCase()));
        const drift = [...colors].filter((color) => !declared.has(color));
        push('design_drift', drift.length > 5 ? 'warn' : 'pass', `非 token 色值 ${drift.length} 个`, { drift_colors: drift.slice(0, 12) });
    }
    else {
        push('design_drift', 'unmeasured', '无 token 基线，无法判定实现偏差');
    }
    const counts = {};
    for (const finding of findings)
        counts[finding.status] = (counts[finding.status] ?? 0) + 1;
    return { items: findings, counts, measured_items: findings.filter((f) => f.status !== 'unmeasured').length, note: 'unmeasured 表示当前输入不足以判定；不得当作通过。' };
}
export function feedbackUnit(input) {
    if (input.scope !== 'project' && input.scope !== 'general')
        throw new ValidationError('scope 必须是 project 或 general');
    getCategory(input.category);
    const text = `${input.decision}｜${input.evidence}`;
    return {
        title: input.decision.slice(0, 120),
        content: text,
        category: input.category,
        scope: input.scope,
        partition: input.scope === 'project' ? 'project_knowledge' : 'pending_knowledge',
        level: input.scope === 'general' ? 'L3' : 'L2',
        verified: Boolean(input.source_url),
        source_url: input.source_url ?? '',
        content_hash: sha256Hex(text),
    };
}
