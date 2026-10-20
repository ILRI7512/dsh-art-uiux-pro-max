#!/usr/bin/env node
/**
 * 可选 MCP 兼容层（stdio，JSON-RPC 2.0 逐行）。
 *
 * 原生 DSH 工具已直接注册，本进程只服务于其他 MCP 客户端；
 * 与原生工具共用 ArtServices，行为一致。
 */
import { createInterface } from 'node:readline';
import { ArtServices } from "../application/services.js";
import { buildNativeTools } from "../application/tools.js";
import { resolveArtRoot } from "../core/paths.js";
import { describeError } from "../core/errors.js";
export function createServer(services = new ArtServices({ root: resolveArtRoot() })) {
    const tools = buildNativeTools(services);
    const byName = new Map(tools.map((tool) => [tool.name, tool]));
    const handle = async (line) => {
        const trimmed = line.trim();
        if (!trimmed)
            return null;
        let request;
        try {
            request = JSON.parse(trimmed);
        }
        catch {
            return JSON.stringify({ jsonrpc: '2.0', id: null, error: { code: -32700, message: 'Parse error' } });
        }
        const id = request.id ?? null;
        const respond = (result) => JSON.stringify({ jsonrpc: '2.0', id, result });
        const error = (code, message, data) => JSON.stringify({ jsonrpc: '2.0', id, error: { code, message, ...(data === undefined ? {} : { data }) } });
        try {
            if (!request.method)
                return error(-32600, 'Invalid Request');
            if (request.method === 'notifications/initialized' || request.method.startsWith('notifications/'))
                return null;
            if (request.method === 'initialize') {
                return respond({
                    protocolVersion: String(request.params?.protocolVersion ?? '2024-11-05'),
                    capabilities: { tools: { listChanged: false } },
                    serverInfo: { name: 'dsh-art-uiux-pro-max', version: '1.0.0' },
                });
            }
            if (request.method === 'ping')
                return respond({});
            if (request.method === 'tools/list') {
                return respond({ tools: tools.map((tool) => ({ name: tool.name, description: tool.description, inputSchema: tool.parameters })) });
            }
            if (request.method === 'tools/call') {
                const name = String(request.params?.name ?? '');
                const tool = byName.get(name);
                if (!tool)
                    return error(-32602, `Unknown tool: ${name}`);
                const args = (request.params?.arguments ?? {});
                const value = await tool.execute(args);
                const failed = typeof value === 'object' && value !== null && value.success === false;
                return respond({
                    content: [{ type: 'text', text: JSON.stringify(value, null, 2) }],
                    isError: failed,
                });
            }
            return error(-32601, `Method not found: ${request.method}`);
        }
        catch (caught) {
            const described = describeError(caught);
            return error(-32603, String(described.error.message ?? 'Internal error'), described.error);
        }
    };
    return { handle, close: () => services.close() };
}
export async function main() {
    const server = createServer();
    const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
    for await (const line of rl) {
        const response = await server.handle(line);
        if (response !== null)
            process.stdout.write(`${response}\n`);
    }
    server.close();
}
const invokedDirectly = process.argv[1] ? /mcp[\\/]server\.(js|ts)$/.test(process.argv[1]) : false;
if (invokedDirectly) {
    main().catch((error) => {
        process.stderr.write(`art-uiux MCP fatal: ${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
        process.exitCode = 1;
    });
}
