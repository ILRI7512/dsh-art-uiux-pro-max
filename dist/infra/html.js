/**
 * HTML 解析与分节。
 *
 * 只依赖 parse5（纯 JS、无浏览器），把页面拆成「标题 + 段落」区块。
 * 明确丢弃导航/页脚/脚本等噪音；不执行页面脚本，不下载媒体。
 */
import { parse } from 'parse5';
const EXCLUDED = new Set(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form', 'noscript', 'svg', 'template', 'iframe']);
const HEADINGS = new Set(['h1', 'h2', 'h3', 'h4']);
const BLOCKS = new Set(['p', 'li', 'pre', 'code']);
function isElement(node) {
    return typeof node.tagName === 'string';
}
export function parseDocument(html) {
    return parse(html);
}
export function textOf(node) {
    if (node.nodeName === '#text')
        return node.value ?? '';
    if (!node.childNodes)
        return '';
    const parts = [];
    for (const child of node.childNodes) {
        if (isElement(child) && EXCLUDED.has(child.tagName))
            continue;
        parts.push(textOf(child));
    }
    return parts.join(' ');
}
export function cleanText(text) {
    return text.replace(/[ \t]+/g, ' ').replace(/\s*\n\s*/g, ' ').trim();
}
/** 把页面拆成正文区块；少于 minChars 的区块不返回。 */
export function sectionize(html, options = {}) {
    const minChars = options.minChars ?? 120;
    const maxChars = options.maxChars ?? 900;
    const root = parseDocument(html);
    const sections = [];
    let current = { heading: '', level: 0, text: '' };
    const flush = () => {
        if (current.text.length >= minChars)
            sections.push({ ...current, text: current.text.slice(0, maxChars).trim() });
    };
    const visit = (node) => {
        if (!node.childNodes)
            return;
        for (const child of node.childNodes) {
            if (!isElement(child))
                continue;
            const tag = child.tagName;
            if (EXCLUDED.has(tag))
                continue;
            if (HEADINGS.has(tag)) {
                flush();
                current = { heading: cleanText(textOf(child)).slice(0, 160), level: Number(tag.slice(1)), text: '' };
                continue;
            }
            if (BLOCKS.has(tag)) {
                const text = cleanText(textOf(child));
                if (text) {
                    const sep = tag === 'pre' || tag === 'code' ? '\n' : ' ';
                    current.text = current.text ? `${current.text}${sep}${text}`.trim() : text;
                }
                // 不在 p/li/pre 内继续遍历，避免子节点文本被重复收集。
                continue;
            }
            visit(child);
        }
    };
    visit(root);
    flush();
    return sections;
}
/** 只读 <title>，用于探测输出。 */
export function documentTitle(html) {
    const match = /<title[^>]*>([\s\S]*?)<\/title>/i.exec(html);
    return match ? cleanText(match[1] ?? '').replace(/&amp;/g, '&').slice(0, 160) : '';
}
