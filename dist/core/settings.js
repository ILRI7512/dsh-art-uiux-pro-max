/**
 * 插件设置：与 CLI / 原生工具 / 设置卡共用一份 JSON，避免两套真相。
 * 只持久化少量可验证字段；读取时做范围校验并保留未知字段（向前兼容）。
 */
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join } from 'node:path';
export const DEFAULTS = Object.freeze({
    dataDir: '',
    allowNetwork: true,
    allowPrivateNetworks: false,
    maxUnits: 10,
    rerank: 'rules',
});
export function settingsPath(root) {
    return join(root, 'data', 'settings.json');
}
export function normalizeSettings(raw) {
    const out = { ...DEFAULTS };
    if (!raw || typeof raw !== 'object')
        return out;
    const input = raw;
    if (typeof input.dataDir === 'string')
        out.dataDir = input.dataDir.trim();
    if (typeof input.allowNetwork === 'boolean')
        out.allowNetwork = input.allowNetwork;
    if (typeof input.allowPrivateNetworks === 'boolean')
        out.allowPrivateNetworks = input.allowPrivateNetworks;
    const maxUnits = Number(input.maxUnits);
    if (Number.isInteger(maxUnits) && maxUnits >= 1 && maxUnits <= 100)
        out.maxUnits = maxUnits;
    if (input.rerank === 'rules' || input.rerank === 'ce')
        out.rerank = input.rerank;
    return out;
}
export function readSettings(root) {
    try {
        return normalizeSettings(JSON.parse(readFileSync(settingsPath(root), 'utf8')));
    }
    catch {
        return { ...DEFAULTS };
    }
}
export function writeSettings(root, patch) {
    if (!patch || typeof patch !== 'object' || Array.isArray(patch))
        return { error: 'settings payload must be an object' };
    const input = patch;
    if (input.dataDir !== undefined) {
        if (typeof input.dataDir !== 'string')
            return { error: 'dataDir must be a string' };
        const value = input.dataDir.trim();
        if (value && !isAbsolute(value))
            return { error: 'dataDir must be an absolute path, or empty to use the default' };
    }
    for (const key of ['allowNetwork', 'allowPrivateNetworks']) {
        if (input[key] !== undefined && typeof input[key] !== 'boolean')
            return { error: `${key} must be a boolean` };
    }
    if (input.maxUnits !== undefined) {
        const value = Number(input.maxUnits);
        if (!Number.isInteger(value) || value < 1 || value > 100)
            return { error: 'maxUnits must be an integer between 1 and 100' };
    }
    if (input.rerank !== undefined && input.rerank !== 'rules' && input.rerank !== 'ce')
        return { error: "rerank must be 'rules' or 'ce'" };
    const next = normalizeSettings({ ...readSettings(root), ...input });
    const file = settingsPath(root);
    const body = {
        ...next,
        updatedAt: new Date().toISOString(),
        revision: createHash('sha256').update(JSON.stringify(next)).digest('hex').slice(0, 16),
    };
    try {
        mkdirSync(dirname(file), { recursive: true });
        const tmp = `${file}.tmp`;
        writeFileSync(tmp, `${JSON.stringify(body, null, 2)}\n`, 'utf8');
        renameSync(tmp, file);
    }
    catch (error) {
        return { error: `failed to persist settings: ${error instanceof Error ? error.message : String(error)}` };
    }
    return { settings: next };
}
export function effectiveDataDir(root, settings) {
    return settings.dataDir || join(root, 'data');
}
export function settingsFileExists(root) {
    return existsSync(settingsPath(root));
}
