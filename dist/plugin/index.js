/**
 * DSH 原生插件入口：注册 16 个工具 + 设置卡接口。
 *
 * 不再启动 Python/MCP 子进程；MCP 仅保留为可选兼容层（dist/mcp/server.js）。
 */
import { ArtServices } from "../application/services.js";
import { buildNativeTools } from "../application/tools.js";
import { resolveArtRoot } from "../core/paths.js";
import { settingsRoute, statsRoute } from "./settings-route.js";
/**
 * 读取可选服务。
 *
 * Cordis 对「未在 inject 中声明的服务」做属性取值会抛
 * `cannot get property "x" without inject`；`ctx.get(name)` 不受这条限制。
 * 这里先走 get()，再退回属性取值，两条路都兜住异常，
 * 这样 headless profile（没有 webServer）也能正常加载插件。
 */
function optionalService(ctx, name) {
    if (typeof ctx.get === 'function') {
        try {
            const value = ctx.get(name);
            if (value !== undefined)
                return value;
        }
        catch { /* 落到属性兜底 */ }
    }
    try {
        return ctx[name];
    }
    catch {
        return undefined;
    }
}
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
        // webServer 只在 web 部署存在。它不能用顶层 inject 声明：headless profile 会整体
        // 挂起，连带 16 个原生工具一起失效。正确做法是把「挂设置卡路由」放进子注入上下文，
        // 让 Cordis 等服务就绪后再执行（见 mcp-connector 的 injectWebRoutes）。
        const mountRoutes = (wctx) => {
            const server = optionalService(wctx, 'webServer');
            if (!server || typeof server.register !== 'function')
                return;
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
        };
        if (typeof ctx.inject === 'function') {
            try {
                ctx.inject(['webServer'], (wctx) => mountRoutes(wctx));
            }
            catch (error) {
                console.warn(`[art-uiux] webServer 注入失败，设置卡接口跳过: ${error instanceof Error ? error.message : String(error)}`);
            }
        }
        else {
            mountRoutes(ctx);
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
