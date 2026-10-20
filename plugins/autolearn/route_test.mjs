import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { Readable } from "node:stream"
import { settingsRoute } from "./index.js"

const dir = mkdtempSync(join(tmpdir(), "al-route-"))
const env = { ...process.env, DSH_AL_SETTINGS_FILE: join(dir, "settings.json") }
const route = settingsRoute(env)

function call(method, body) {
  return new Promise((resolve) => {
    const req = body === undefined ? { method } : Object.assign(Readable.from([Buffer.from(JSON.stringify(body))]), { method })
    let status = 0
    let payload = ""
    const res = {
      writeHead(code) { status = code; return this },
      end(text) { payload = text || ""; resolve({ status, body: payload ? JSON.parse(payload) : null }) },
    }
    route.handler(req, res)
  })
}

console.log("route:", route.path, route.kind)
const g = await call("GET")
console.log("GET", g.status, JSON.stringify(g.body.settings), "effective:", g.body.effectiveDataDir)
const p = await call("POST", { mode: "lab", dailyBudgetUsd: 4.5 })
console.log("POST", p.status, JSON.stringify(p.body.settings))
const bad = await call("POST", { mode: "nope" })
console.log("POST invalid", bad.status, bad.body.error)
const rel = await call("POST", { dataDir: "rel/path" })
console.log("POST relative", rel.status, rel.body.error)
const put = await call("PUT")
console.log("PUT", put.status)
rmSync(dir, { recursive: true, force: true })
