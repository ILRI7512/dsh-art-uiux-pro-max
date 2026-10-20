/**
 * DSH 原生插件入口：注册 16 个工具 + 设置卡接口。
 *
 * 不再启动 Python/MCP 子进程；MCP 仅保留为可选兼容层（dist/mcp/server.js）。
 */
import { ArtServices } from "../application/services.js";
import { buildNativeTools } from "../application/tools.js";
import { resolveArtRoot } from "../core/paths.js";
import { settingsRoute, statsRoute } from "./settings-route.js";
export const inject = ['tools'];
export function apply(ctx, config = {}) {
    if (!ctx?.tools || typeof ctx.tools.register !== 'function') {
        console.warn('[art-uiux] ctx.tools 不可用：原生工具未注册');
        return;
    }
    const root = config.home ?? resolveArtRoot();
    let services;
    try {
        services = new ArtServices({ root, dataDir: config.dataDir });
    }
    catch (error) {
        console.error(`[art-uiux] 服务启动失败: ${error instanceof Error ? error.message : String(error)}`);
        return;
    }
    const tools = buildNativeTools(services);
    const dispose = () => {
        services.close();
    };
    const register = () => {
        const disposers = [];
        for (const tool of tools) {
            try {
                const off = ctx.tools?.register(tool);
                if (typeof off === 'function')
                    disposers.push(off);
            }
            catch (error) {
                console.error(`[art-uiux] 工具注册失败 ${tool.name}: ${error instanceof Error ? error.message : String(error)}`);
            }
        }
        const offRoutes = [];
        // webServer 是可选服务：Cordis 对未 inject 的服务取值会抛错，
        // 因此这里必须包一层 try/catch；headless profile 下只跳过设置卡接口。
        try {
            const server = ctx.webServer;
            if (server && typeof server.register === 'function') {
                for (const route of [settingsRoute(services), statsRoute(services)]) {
                    try {
                        const off = server.register(route);
                        if (typeof off === 'function')
                            offRoutes.push(off);
                    }
                    catch (error) {
                        console.warn(`[art-uiux] 路由注册失败 ${route.path}: ${error instanceof Error ? error.message : String(error)}`);
                    }
                }
            }
        }
        catch (error) {
            console.warn(`[art-uiux] webServer 不可用，设置卡接口跳过: ${error instanceof Error ? error.message : String(error)}`);
        }
        console.log(`[art-uiux] 原生工具已注册: ${tools.length} 个；数据目录 ${services.dataDir}`);
        return () => {
            for (const off of offRoutes) {
                try {
                    off();
                }
                catch { /* 已注销 */ }
            }
            for (const off of disposers) {
                try {
                    off();
                }
                catch { /* 已注销 */ }
            }
        };
    };
    if (typeof ctx.effect === 'function') {
        ctx.effect(() => {
            const unregister = register();
            return () => {
                unregister();
                dispose();
            };
        }, 'art-uiux: knowledge engine + native tools');
        return;
    }
    const unregister = register();
    return () => {
        unregister();
        dispose();
    };
}
export { buildNativeTools, settingsRoute, statsRoute };
