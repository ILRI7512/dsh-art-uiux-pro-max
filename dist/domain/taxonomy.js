/**
 * 12 个知识主分类（唯一主分类制）与 16 个提取字段。
 *
 * 主分类写入 chunk.topic，辅助标签写入 metadata.secondary_categories；
 * 分类校验是确定性的，错误分类不会被“猜一个”兜底。
 */
import { ValidationError } from "../core/errors.js";
import { TAXONOMY_DATA } from "./taxonomy-data.js";
const toCategory = (raw) => ({
    key: raw.key,
    label: raw.label,
    label_en: raw.label_en,
    description: raw.description,
    include_scope: [...raw.include_scope],
    exclude_scope: [...raw.exclude_scope],
    subcategories: [...raw.subcategories],
    keywords: [...raw.keywords],
    knowledge_types: [...raw.knowledge_types],
    related: [...raw.related],
    ingest_conditions: [...raw.ingest_conditions],
    quality_requirements: [...raw.quality_requirements],
});
export const CATEGORIES = Object.fromEntries(TAXONOMY_DATA.categories.map((item) => [item.key, toCategory(item)]));
export const CATEGORY_KEYS = TAXONOMY_DATA.categories.map((item) => item.key);
export const EXTRACTION_FIELDS = [...TAXONOMY_DATA.extraction_fields];
export const EXTRACTION_MINIMUM = [...TAXONOMY_DATA.extraction_minimum];
export class TaxonomyError extends ValidationError {
    constructor(message) {
        super(message);
        this.name = 'TaxonomyError';
    }
}
export function getCategory(key) {
    const category = CATEGORIES[key];
    if (!category)
        throw new TaxonomyError(`未知主分类 ${JSON.stringify(key)}，允许值: ${CATEGORY_KEYS.join(', ')}`);
    return category;
}
/** 校验主/辅分类；返回去重后的辅助标签，不做任何自动纠正。 */
export function validateAssignment(primary, secondary = []) {
    getCategory(primary);
    const seen = new Set();
    const cleaned = [];
    for (const item of secondary) {
        if (typeof item !== 'string')
            throw new TaxonomyError(`辅助分类必须是字符串，收到 ${String(item)}`);
        const key = item.trim();
        if (!key)
            continue;
        if (key === primary)
            throw new TaxonomyError(`辅助分类不能与主分类相同（${key}）`);
        getCategory(key);
        if (!seen.has(key)) {
            seen.add(key);
            cleaned.push(key);
        }
    }
    return cleaned;
}
export function describeTaxonomy() {
    return {
        primary_keys: CATEGORY_KEYS,
        categories: CATEGORY_KEYS.map((key) => {
            const c = CATEGORIES[key];
            return {
                key: c.key,
                label: c.label,
                label_en: c.label_en,
                description: c.description,
                include_scope: c.include_scope,
                exclude_scope: c.exclude_scope,
                subcategories: c.subcategories,
                keywords: c.keywords,
                knowledge_types: c.knowledge_types,
                related: c.related,
                ingest_conditions: c.ingest_conditions,
                quality_requirements: c.quality_requirements,
            };
        }),
        extraction_fields: EXTRACTION_FIELDS,
        extraction_minimum: EXTRACTION_MINIMUM,
    };
}
