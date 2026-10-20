/**
 * DSH 原生插件入口：注册 16 个工具 + 设置卡接口。
 *
 * 不再启动 Python/MCP 子进程；MCP 仅保留为可选兼容层（dist/mcp/server.js）。
 */
import { ArtServices } from '../application/services.ts'
import { buildNativeTools } from '../application/tools.ts'
import { resolveArtRoot } from '../core/paths.ts'
import { settingsRoute, statsRoute } from './settings-route.ts'

interface ToolRegistry {
  register: (tool: unknown) => (() => void) | void
}

interface WebServerLike {
  register: (route: unknown) => (() => void) | void
}

interface PluginContextLike {
  tools?: ToolRegistry
  webServer?: WebServerLike
  effect?: (callback: () => (() => void) | void, label?: string) => unknown
}

export interface PluginConfig {
  home?: string
  dataDir?: string
}

export const inject = ['tools']

export function apply(ctx: PluginContextLike, config: PluginConfig = {}): (() => void) | void {
  if (!ctx?.tools || typeof ctx.tools.register !== 'function') {
    console.warn('[art-uiux] ctx.tools 不可用：原生工具未注册')
    return
  }
  const root = config.home ?? resolveArtRoot()
  let services: ArtServices
  try {
    services = new ArtServices({ root, dataDir: config.dataDir })
  } catch (error) {
    console.error(`[art-uiux] 服务启动失败: ${error instanceof Error ? error.message : String(error)}`)
    return
  }

  const tools = buildNativeTools(services)

  const dispose = (): void => {
    services.close()
  }

  const register = (): (() => void) => {
    const disposers: Array<() => void> = []
    for (const tool of tools) {
      try {
        const off = ctx.tools?.register(tool)
        if (typeof off === 'function') disposers.push(off)
      } catch (error) {
        console.error(`[art-uiux] 工具注册失败 ${tool.name}: ${error instanceof Error ? error.message : String(error)}`)
      }
    }
    const offRoutes: Array<() => void> = []
    if (ctx.webServer && typeof ctx.webServer.register === 'function') {
      for (const route of [settingsRoute(services), statsRoute(services)]) {
        try {
          const off = ctx.webServer.register(route)
          if (typeof off === 'function') offRoutes.push(off)
        } catch (error) {
          console.warn(`[art-uiux] 路由注册失败 ${route.path}: ${error instanceof Error ? error.message : String(error)}`)
        }
      }
    }
    console.log(`[art-uiux] 原生工具已注册: ${tools.length} 个；数据目录 ${services.dataDir}`)
    return () => {
      for (const off of offRoutes) { try { off() } catch { /* 已注销 */ } }
      for (const off of disposers) {
        try { off() } catch { /* 已注销 */ }
      }
    }
  }

  if (typeof ctx.effect === 'function') {
    ctx.effect(() => {
      const unregister = register()
      return () => {
        unregister()
        dispose()
      }
    }, 'art-uiux: knowledge engine + native tools')
    return
  }
  const unregister = register()
  return () => {
    unregister()
    dispose()
  }
}

export { buildNativeTools, settingsRoute, statsRoute }
