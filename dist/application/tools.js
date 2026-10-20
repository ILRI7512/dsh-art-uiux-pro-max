/**
 * 16 个 DSH 原生工具：参数 Schema + 运行时校验 + 结构化错误。
 * 与 MCP 适配层共用 ArtServices，避免两套行为。
 */
import { describeError, ValidationError } from "../core/errors.js";
const str = (description, extra = {}) => ({ type: 'string', description, ...extra });
const int = (description, extra = {}) => ({ type: 'integer', description, ...extra });
const strArray = (description) => ({ type: 'array', description, items: { type: 'string' } });
const object = (properties, required = []) => ({ type: 'object', properties, required, additionalProperties: false });
const OUTPUT = { type: 'object', additionalProperties: true };
const render = (value) => [{ type: 'text', text: JSON.stringify(value, null, 2) }];
function requireString(args, key) {
    const value = args[key];
    if (typeof value !== 'string' || value.trim() === '')
        throw new ValidationError(`${key} 必须是非空字符串`);
    return value;
}
function optionalString(args, key) {
    const value = args[key];
    if (value === undefined || value === null)
        return undefined;
    if (typeof value !== 'string')
        throw new ValidationError(`${key} 必须是字符串`);
    return value;
}
function optionalNumber(args, key) {
    const value = args[key];
    if (value === undefined || value === null)
        return undefined;
    const number = Number(value);
    if (!Number.isFinite(number))
        throw new ValidationError(`${key} 必须是数字`);
    return number;
}
function optionalStringArray(args, key) {
    const value = args[key];
    if (value === undefined || value === null)
        return undefined;
    if (!Array.isArray(value) || value.some((item) => typeof item !== 'string'))
        throw new ValidationError(`${key} 必须是字符串数组`);
    return value;
}
export function buildNativeTools(services) {
    const define = (name, description, parameters, handler) => ({
        name,
        description,
        parameters,
        output: { schema: OUTPUT, render },
        timeoutMs: 180_000,
        async execute(args) {
            try {
                return await handler(args ?? {});
            }
            catch (error) {
                return describeError(error);
            }
        },
    });
    return [
        define('art_taxonomy', '返回 12 个 UI/UX 主分类、每个分类的 12 项元数据与 16 个提取字段。', object({}), () => services.taxonomy()),
        define('art_registry_list', '列出资源注册表（种子 + 运行期状态），可按分类/类型/访问状态过滤。访问状态不等于学习完成。', object({ category: str('主分类 key'), type: str('资源类型'), access_status: str('访问状态'), limit: int('最多返回条数', { minimum: 1, maximum: 500 }) }), (args) => services.registryList({ category: optionalString(args, 'category'), type: optionalString(args, 'type'), accessStatus: optionalString(args, 'access_status'), limit: optionalNumber(args, 'limit') })),
        define('art_registry_check', '对资源做真实访问探测：robots 前置、HTTP 状态、私网防护；只写 access_status，不冒充学习完成。', object({ resource_id: str('留空则检查全部'), limit: int('最多检查条数', { minimum: 1, maximum: 62 }) }), (args) => services.registryCheck({ resourceId: optionalString(args, 'resource_id'), limit: optionalNumber(args, 'limit') })),
        define('art_learn', '抓取资源正文、分节、分类、套 16 字段模板并正式写入知识库；最高只到 L2，返回真实入库条数。', object({ resource_id: str('资源 ID'), max_units: int('最多处理的正文区块', { minimum: 1, maximum: 100 }) }, ['resource_id']), (args) => services.learn({ resourceId: requireString(args, 'resource_id'), maxUnits: optionalNumber(args, 'max_units') })),
        define('art_case_analyze', '分析真实页面：抽出事实/推断/观点三分证据，产出案例知识并登记数值冲突；未渲染不下可用性结论。', object({ resource_id: str('资源 ID'), max_units: int('最多入库单元', { minimum: 1, maximum: 100 }) }, ['resource_id']), (args) => services.caseAnalyze({ resourceId: requireString(args, 'resource_id'), maxUnits: optionalNumber(args, 'max_units') })),
        define('art_search', '混合检索（向量 + BM25 + RRF + 分类亲和度/词面重排），返回来源、等级、未核验告警；证据不足时明确说明。', object({ query: str('检索问题'), categories: strArray('限定主分类；留空则按任务路由'), top_k: int('返回条数', { minimum: 1, maximum: 50 }), min_level: str('最低知识等级', { enum: ['L1', 'L2', 'L3', 'L4'] }), rerank: str('重排策略', { enum: ['rules', 'ce'] }) }, ['query']), (args) => services.search({ query: requireString(args, 'query'), categories: optionalStringArray(args, 'categories'), topK: optionalNumber(args, 'top_k'), minLevel: optionalString(args, 'min_level'), rerank: optionalString(args, 'rerank') })),
        define('art_route_task', '识别 UI 设计需求的任务类型，并给出相关主分类与判定依据。', object({ text: str('需求原文') }, ['text']), (args) => services.routeTask(requireString(args, 'text'))),
        define('art_directions', '给出有实质区别的视觉方向；明确拒绝“不问场景就默认玻璃拟态/深色/蓝紫渐变”。', object({ task_type: str('任务类型'), count: int('方向数量', { minimum: 1, maximum: 4 }) }), (args) => services.directions({ taskType: optionalString(args, 'task_type'), count: optionalNumber(args, 'count') })),
        define('art_design_system', '产出 Design Tokens 与 CSS，并对关键配色做 WCAG 对比度实算；未验证项明确标注。', object({ direction: str('方向 key') }), (args) => services.designSystem({ direction: optionalString(args, 'direction') })),
        define('art_audit', '对 HTML/CSS 做 10 项设计审计；能算的算出来，不能测的标 unmeasured，不给假通过。', object({ html: str('待审计 HTML/CSS'), direction: str('用于取 token 的方向 key') }, ['html']), (args) => services.audit({ html: requireString(args, 'html'), direction: optionalString(args, 'direction') })),
        define('art_responsive', '输出多断点布局矩阵（静态推断）；实际重排与溢出需浏览器验证。', object({ html: str('待分析 HTML') }, ['html']), (args) => services.responsive({ html: requireString(args, 'html') })),
        define('art_backgrounds', '给出三种机制不同的背景方案，并实测每种方案上的文字对比度。', object({ text_color: str('正文色，十六进制'), count: int('方案数量', { minimum: 1, maximum: 3 }) }), (args) => services.backgrounds({ textColor: optionalString(args, 'text_color'), count: optionalNumber(args, 'count') })),
        define('art_recommend', '按产品/行业/关键词给出完整设计配方：产品类别、88 风格库匹配、16 色令牌、字体搭配、落地页、UX 规范、反模式与 1-10 设计旋钮。', object({ query: str('产品类型、行业或关键词（中英皆可）'), project_name: str('项目名（仅用于回显）'), variance: int('大胆度 1-10', { minimum: 1, maximum: 10 }), motion: int('动效强度 1-10', { minimum: 1, maximum: 10 }), density: int('信息密度 1-10', { minimum: 1, maximum: 10 }) }, ['query']), (args) => services.recommend({ query: requireString(args, 'query'), projectName: optionalString(args, 'project_name'), variance: optionalNumber(args, 'variance'), motion: optionalNumber(args, 'motion'), density: optionalNumber(args, 'density') })),
        define('art_review', '按 195 条 UX / Web / React 规范审查 UI，按严重度排序，附正确/错误代码与交付前检查清单；不冒充真实渲染测试。', object({ target: str('页面/组件 + 问题现象'), platform: str('目标平台', { enum: ['web', 'mobile', 'desktop', 'react-native', 'flutter'] }), max_rules: int('最多返回条数', { minimum: 1, maximum: 30 }) }, ['target']), (args) => services.review({ target: requireString(args, 'target'), platform: optionalString(args, 'platform'), maxRules: optionalNumber(args, 'max_rules') })),
        define('art_library_search', '按域检索内置设计智能库：88 风格 / 192 调色板 / 74 字体 / 25 图表 / 34 落地页 / 192 产品配方 / 195 规范。', object({ query: str('检索词（中英皆可）'), domain: str('限定域；留空则全库', { enum: ['style', 'color', 'chart', 'landing', 'product', 'ux', 'typography', 'react', 'web'] }), max_results: int('最多返回条数', { minimum: 1, maximum: 50 }) }, ['query']), (args) => services.librarySearch({ query: requireString(args, 'query'), domain: optionalString(args, 'domain'), maxResults: optionalNumber(args, 'max_results') })),
        define('art_stats', '知识库、注册表与设计智能库的真实统计：资源三态、片段数、等级/分类分布、索引完整性、设计库计数。', object({}), () => services.stats()),
    ];
}
