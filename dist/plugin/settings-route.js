import { DEFAULTS, effectiveDataDir, settingsPath } from "../core/settings.js";
function send(res, status, body) {
    res.writeHead(status, { 'content-type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify(body));
}
async function readBody(req, limit = 64 * 1024) {
    const chunks = [];
    let total = 0;
    for await (const chunk of req) {
        total += chunk.byteLength;
        if (total > limit)
            throw new Error('payload too large');
        chunks.push(chunk);
    }
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}
export function settingsRoute(services) {
    return {
        name: 'art-uiux-settings',
        kind: 'exact',
        path: '/art-uiux/api/settings',
        async handler(req, res) {
            if (req.method === 'GET') {
                const settings = services.settings;
                send(res, 200, {
                    settings,
                    defaults: { ...DEFAULTS },
                    effectiveDataDir: effectiveDataDir(services.root, settings),
                    settingsPath: settingsPath(services.root),
                    notes: {
                        network: '关闭网络后，check/learn/case/组件学习都会被拒绝；私网默认禁止。',
                        apply: '设置当前调用即生效；数据目录变更会切换到新的 SQLite 库。',
                    },
                });
                return;
            }
            if (req.method !== 'POST') {
                res.writeHead(405).end();
                return;
            }
            try {
                const patch = await readBody(req);
                const result = services.updateSettings(patch);
                if (result.error) {
                    send(res, 400, { error: result.error });
                    return;
                }
                send(res, 200, {
                    settings: result.settings,
                    effectiveDataDir: result.settings ? effectiveDataDir(services.root, result.settings) : services.dataDir,
                    settingsPath: settingsPath(services.root),
                    savedAt: new Date().toISOString(),
                });
            }
            catch (error) {
                send(res, 400, { error: error instanceof Error ? error.message : String(error) });
            }
        },
    };
}
export function statsRoute(services) {
    return {
        name: 'art-uiux-stats',
        kind: 'exact',
        path: '/art-uiux/api/stats',
        async handler(req, res) {
            if (req.method !== 'GET') {
                res.writeHead(405).end();
                return;
            }
            try {
                send(res, 200, services.stats());
            }
            catch (error) {
                send(res, 500, { error: error instanceof Error ? error.message : String(error) });
            }
        },
    };
}
