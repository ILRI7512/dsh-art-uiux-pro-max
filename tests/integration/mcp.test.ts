import assert from 'node:assert/strict'
import { test } from 'node:test'
import { join } from 'node:path'
import { createServer } from '../../src/mcp/server.ts'
import { ArtServices } from '../../src/application/services.ts'
import { cleanup, makeRoot, seedResource } from '../helpers.ts'

test('MCP 握手、工具清单与调用可用', async () => {
  const root = makeRoot([seedResource()])
  const services = new ArtServices({ root, dataDir: join(root, 'data') })
  const server = createServer(services)
  try {
    const init = JSON.parse((await server.handle(JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2024-11-05' } }))) ?? '{}')
    assert.equal(init.result.serverInfo.name, 'dsh-art-uiux-pro-max')
    assert.equal(init.result.capabilities.tools.listChanged, false)
    const list = JSON.parse((await server.handle(JSON.stringify({ jsonrpc: '2.0', id: 2, method: 'tools/list' }))) ?? '{}')
    assert.equal(list.result.tools.length, 13)
    const call = JSON.parse((await server.handle(JSON.stringify({ jsonrpc: '2.0', id: 3, method: 'tools/call', params: { name: 'art_taxonomy', arguments: {} } }))) ?? '{}')
    assert.equal(call.result.isError, false)
    const payload = JSON.parse(call.result.content[0].text)
    assert.equal(payload.categories.length, 12)
    const unknown = JSON.parse((await server.handle(JSON.stringify({ jsonrpc: '2.0', id: 4, method: 'tools/call', params: { name: 'nope', arguments: {} } }))) ?? '{}')
    assert.equal(unknown.error.code, -32602)
  } finally { server.close(); cleanup(root) }
})
