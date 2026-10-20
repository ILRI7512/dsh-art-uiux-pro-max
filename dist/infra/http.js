/**
 * 受控 HTTP 抓取：robots.txt 前置、同 host 节流、大小上限、私网默认拒绝。
 *
 * 与旧版差异：
 * - robots 判定与正文抓取共用同一个缓存，且重定向的每一跳都重新校验；
 * - 默认拒绝 loopback / 私网 / link-local，防止把资源 URL 变成 SSRF 入口；
 * - 明确区分 blocked / restricted / failed，2xx 但正文过短按 restricted 处理。
 */
import { lookup } from 'node:dns/promises';
import { isIP } from 'node:net';
import { ArtError, ERROR_CODES } from "../core/errors.js";
import { documentTitle } from "./html.js";
export const UA = 'DSH-Art-UIUX-ProMax/1.0 (+local design research agent; respects robots.txt)';
export const MAX_BYTES = 256 * 1024;
const ROBOTS_MAX_BYTES = 64 * 1024;
const ROBOTS_TTL_MS = 3_600_000;
export class NetworkBlockedError extends ArtError {
    constructor(message) {
        super(message, { code: ERROR_CODES.NETWORK_BLOCKED });
        this.name = 'NetworkBlockedError';
    }
}
function isPrivateIp(address) {
    const version = isIP(address);
    if (version === 4) {
        const parts = address.split('.').map(Number);
        const a = parts[0] ?? 0;
        const b = parts[1] ?? 0;
        if (parts.length !== 4 || parts.some((n) => !Number.isInteger(n) || n < 0 || n > 255))
            return true;
        if (a === 0 || a === 10 || a === 127)
            return true;
        if (a === 169 && b === 254)
            return true;
        if (a === 172 && b >= 16 && b <= 31)
            return true;
        if (a === 192 && b === 168)
            return true;
        if (a === 100 && b >= 64 && b <= 127)
            return true;
        if (a >= 224)
            return true;
        return false;
    }
    if (version === 6) {
        const lower = address.toLowerCase();
        if (lower === '::' || lower === '::1')
            return true;
        if (lower.startsWith('fe80:') || lower.startsWith('fc') || lower.startsWith('fd'))
            return true;
        // IPv4-mapped IPv6（含十六进制写法如 ::ffff:7f00:1）一律保守拒绝，
        // 避免用另一种表示绕过 loopback/私网判断。
        if (lower.startsWith('::ffff:') || lower.includes(':ffff:'))
            return true;
        if (lower.startsWith('64:ff9b:'))
            return true;
        return false;
    }
    return true;
}
/** 校验 URL 协议、凭据与目标地址；allowPrivateNetworks 只应由显式配置打开。 */
export async function assertSafeHttpUrl(raw, options = {}) {
    let url;
    try {
        url = new URL(raw);
    }
    catch {
        throw new NetworkBlockedError(`非法 URL: ${raw}`);
    }
    if (url.protocol !== 'http:' && url.protocol !== 'https:') {
        throw new NetworkBlockedError(`不支持的协议: ${url.protocol}`);
    }
    if (url.username || url.password)
        throw new NetworkBlockedError('URL 不允许携带凭据');
    const host = url.hostname.replace(/^\[|\]$/g, '').toLowerCase();
    if (!host)
        throw new NetworkBlockedError('URL 缺少 host');
    if (options.allowPrivateNetworks)
        return url;
    if (host === 'localhost' || host.endsWith('.localhost') || host === '0.0.0.0') {
        throw new NetworkBlockedError(`默认拒绝本机地址: ${host}（如确需抓取本地服务，请显式开启 allow_private_networks）`);
    }
    if (isIP(host)) {
        if (isPrivateIp(host))
            throw new NetworkBlockedError(`默认拒绝私网/保留地址: ${host}`);
        return url;
    }
    let addresses;
    try {
        addresses = await lookup(host, { all: true });
    }
    catch (error) {
        throw new NetworkBlockedError(`DNS 解析失败: ${error instanceof Error ? error.message : String(error)}`);
    }
    if (addresses.length === 0)
        throw new NetworkBlockedError(`DNS 无结果: ${host}`);
    for (const item of addresses) {
        if (isPrivateIp(item.address))
            throw new NetworkBlockedError(`域名解析到私网地址: ${host} → ${item.address}`);
    }
    return url;
}
function compileRobots(text, userAgent) {
    const lines = text.split(/\r?\n/);
    const groups = [];
    let current = null;
    let lastWasAgent = false;
    for (const raw of lines) {
        const line = raw.replace(/#.*$/, '').trim();
        if (!line)
            continue;
        const colon = line.indexOf(':');
        if (colon < 0)
            continue;
        const field = line.slice(0, colon).trim().toLowerCase();
        const value = line.slice(colon + 1).trim();
        if (field === 'user-agent') {
            if (!lastWasAgent || !current) {
                current = { agents: [], rules: [] };
                groups.push(current);
            }
            current.agents.push(value.toLowerCase());
            lastWasAgent = true;
            continue;
        }
        lastWasAgent = false;
        if (!current)
            continue;
        if (field === 'disallow' || field === 'allow') {
            current.rules.push({ allow: field === 'allow', pattern: value });
        }
    }
    const uaToken = userAgent.toLowerCase().split(/[\s/]/)[0] ?? '';
    const selected = [];
    let matchedSpecific = false;
    for (const group of groups) {
        const specific = group.agents.some((agent) => agent !== '*' && uaToken.startsWith(agent));
        if (specific) {
            selected.push(...group.rules);
            matchedSpecific = true;
        }
    }
    if (!matchedSpecific) {
        for (const group of groups)
            if (group.agents.includes('*'))
                selected.push(...group.rules);
    }
    return selected;
}
function robotsAllows(rules, path) {
    let best = null;
    for (const rule of rules) {
        if (!rule.pattern)
            continue;
        let pattern = rule.pattern;
        const anchored = pattern.endsWith('$');
        if (anchored)
            pattern = pattern.slice(0, -1);
        const escaped = pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*');
        const regex = new RegExp(anchored ? `^${escaped}$` : `^${escaped}`);
        if (!regex.test(path))
            continue;
        const length = rule.pattern.replace(/\*/g, '').length;
        if (!best || length > best.length || (length === best.length && rule.allow)) {
            best = { allow: rule.allow, length };
        }
    }
    return best ? best.allow : true;
}
export class HttpClient {
    options;
    robotsCache = new Map();
    nextSlot = new Map();
    constructor(options = {}) {
        this.options = {
            timeoutMs: options.timeoutMs ?? 20_000,
            maxBytes: options.maxBytes ?? MAX_BYTES,
            allowPrivateNetworks: options.allowPrivateNetworks ?? false,
            minHostIntervalMs: options.minHostIntervalMs ?? 800,
            userAgent: options.userAgent ?? UA,
        };
    }
    async throttle(host) {
        const interval = this.options.minHostIntervalMs;
        if (interval <= 0)
            return;
        const now = Date.now();
        const slot = Math.max(now, this.nextSlot.get(host) ?? 0);
        this.nextSlot.set(host, slot + interval);
        const wait = slot - now;
        if (wait > 0)
            await new Promise((resolve) => setTimeout(resolve, Math.min(wait, 3000)));
    }
    async robotsFor(origin) {
        const cached = this.robotsCache.get(origin);
        if (cached && cached.expires > Date.now())
            return cached.rules;
        let rules = null;
        try {
            await this.throttle(new URL(origin).host);
            const response = await this.fetchRaw(`${origin}/robots.txt`, 15_000);
            if (response.status === 200) {
                const buffer = new Uint8Array(await response.arrayBuffer()).slice(0, ROBOTS_MAX_BYTES);
                rules = compileRobots(new TextDecoder().decode(buffer), this.options.userAgent);
            }
            else if (response.status === 401 || response.status === 403) {
                rules = [{ allow: false, pattern: '/' }];
            }
        }
        catch {
            rules = null;
        }
        this.robotsCache.set(origin, { expires: Date.now() + ROBOTS_TTL_MS, rules });
        return rules;
    }
    /** 手动跟随重定向，每一跳都重新做 URL 安全校验。 */
    async fetchRaw(raw, timeoutMs = this.options.timeoutMs) {
        let current = await assertSafeHttpUrl(raw, { allowPrivateNetworks: this.options.allowPrivateNetworks });
        for (let hop = 0; hop < 6; hop += 1) {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), timeoutMs);
            let response;
            try {
                response = await fetch(current, {
                    redirect: 'manual',
                    signal: controller.signal,
                    headers: { 'user-agent': this.options.userAgent, accept: 'text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1' },
                });
            }
            catch (error) {
                clearTimeout(timer);
                const message = error instanceof Error ? error.message : String(error);
                throw new ArtError(message.includes('abort') ? '请求超时' : `请求失败: ${message}`, { code: ERROR_CODES.NETWORK_FAILED, retryable: true });
            }
            clearTimeout(timer);
            if (response.status >= 300 && response.status < 400) {
                const location = response.headers.get('location');
                if (!location)
                    return response;
                current = await assertSafeHttpUrl(new URL(location, current).toString(), { allowPrivateNetworks: this.options.allowPrivateNetworks });
                continue;
            }
            return response;
        }
        throw new ArtError('重定向次数过多', { code: ERROR_CODES.NETWORK_FAILED });
    }
    async readLimited(response, limit) {
        if (!response.body)
            return { bytes: new Uint8Array(), total: 0 };
        const reader = response.body.getReader();
        const chunks = [];
        let total = 0;
        while (true) {
            const { done, value } = await reader.read();
            if (done)
                break;
            chunks.push(value);
            total += value.byteLength;
            if (total >= limit) {
                await reader.cancel().catch(() => undefined);
                break;
            }
        }
        const merged = new Uint8Array(Math.min(total, limit));
        let offset = 0;
        for (const chunk of chunks) {
            const take = Math.min(chunk.byteLength, merged.byteLength - offset);
            if (take <= 0)
                break;
            merged.set(chunk.subarray(0, take), offset);
            offset += take;
        }
        return { bytes: merged, total: offset };
    }
    async probe(raw) {
        try {
            const url = await assertSafeHttpUrl(raw, { allowPrivateNetworks: this.options.allowPrivateNetworks });
            const origin = `${url.protocol}//${url.host}`;
            await this.throttle(url.host);
            const rules = await this.robotsFor(origin);
            if (rules && !robotsAllows(rules, `${url.pathname}${url.search}`)) {
                return { url: raw, access_status: 'blocked', final_url: raw, content_type: '', bytes_read: 0, robots_allowed: false, title: '', error: 'robots.txt 禁止抓取该路径' };
            }
            await this.throttle(url.host);
            const response = await this.fetchRaw(raw);
            const contentType = response.headers.get('content-type') ?? '';
            const { bytes, total } = await this.readLimited(response, this.options.maxBytes);
            const text = new TextDecoder('utf-8', { fatal: false }).decode(bytes);
            const finalUrl = response.url || raw;
            let access;
            if (response.status >= 200 && response.status < 300)
                access = total < 200 ? 'restricted' : 'reachable';
            else if ([401, 402, 403, 429].includes(response.status))
                access = 'restricted';
            else
                access = 'failed';
            return {
                url: raw,
                access_status: access,
                http_status: response.status,
                final_url: finalUrl,
                content_type: contentType,
                bytes_read: total,
                robots_allowed: true,
                title: documentTitle(text),
                error: access === 'reachable' ? '' : `HTTP ${response.status}${access === 'restricted' && total < 200 ? '（响应体过短，疑似软拦截）' : ''}`,
            };
        }
        catch (error) {
            return {
                url: raw,
                access_status: error instanceof NetworkBlockedError ? 'blocked' : 'failed',
                final_url: raw,
                content_type: '',
                bytes_read: 0,
                robots_allowed: null,
                title: '',
                error: error instanceof Error ? error.message : String(error),
            };
        }
    }
    /** 抓正文；robots 不允许或内容不是文本类时抛错，调用方必须如实记录。 */
    async fetchHtml(raw) {
        const url = await assertSafeHttpUrl(raw, { allowPrivateNetworks: this.options.allowPrivateNetworks });
        const origin = `${url.protocol}//${url.host}`;
        await this.throttle(url.host);
        const rules = await this.robotsFor(origin);
        if (rules && !robotsAllows(rules, `${url.pathname}${url.search}`)) {
            throw new NetworkBlockedError('robots.txt 禁止抓取该路径');
        }
        await this.throttle(url.host);
        const response = await this.fetchRaw(raw);
        if (response.status < 200 || response.status >= 300) {
            throw new ArtError(`抓取失败: HTTP ${response.status}`, { code: ERROR_CODES.NETWORK_FAILED });
        }
        const contentType = (response.headers.get('content-type') ?? '').toLowerCase();
        if (contentType && !contentType.includes('html') && !contentType.includes('xml') && !contentType.includes('text/plain')) {
            throw new ArtError(`不支持的内容类型: ${contentType}`, { code: ERROR_CODES.UNSUPPORTED });
        }
        const { bytes, total } = await this.readLimited(response, this.options.maxBytes);
        if (total < 200)
            throw new ArtError('响应体过短，无法作为正文学习', { code: ERROR_CODES.NETWORK_FAILED });
        return {
            html: new TextDecoder('utf-8', { fatal: false }).decode(bytes),
            finalUrl: response.url || raw,
            status: response.status,
            contentType,
            bytes: total,
        };
    }
    async probeMany(urls, concurrency = 4) {
        const results = new Array(urls.length);
        let next = 0;
        const workers = Array.from({ length: Math.max(1, Math.min(concurrency, urls.length)) }, async () => {
            while (true) {
                const index = next;
                next += 1;
                if (index >= urls.length)
                    return;
                results[index] = await this.probe(urls[index]);
            }
        });
        await Promise.all(workers);
        return results;
    }
}
