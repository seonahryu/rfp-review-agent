import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"

const root = process.cwd()
const apiMain = fs.readFileSync(path.join(root, "api", "main.py"), "utf8")
const apiClient = fs.readFileSync(path.join(root, "rfp-review-ui-clone", "lib", "api-client.ts"), "utf8")
const uiRoots = [
  path.join(root, "rfp-review-ui-clone"),
  path.join(root, "ui-rfp-review", "rfp-review-ui-main"),
].filter((candidate) => fs.existsSync(candidate))

assert(apiMain.includes('@app.post("/api/parse")'), "backend should keep direct parse endpoint")
assert(apiMain.includes('@app.post("/api/parse/jobs")'), "backend should expose checkpointed parse jobs")
assert(apiMain.includes('@app.get("/api/parse/jobs/{job_id}")'), "backend should expose parse job polling")
assert(apiClient.includes("${BACKEND_API_URL}/api/parse"), "UI should call the Render backend parse endpoint")
assert(!apiClient.includes('fetch("/api/parse"'), "UI should not fall back to Vercel for PDF parsing")
for (const uiRoot of uiRoots) {
  assert(!fs.existsSync(path.join(uiRoot, "app", "api", "parse", "route.ts")), "Vercel parse proxy route should be removed")
}
assert(!apiMain.includes('@app.post("/api/parse/start")'), "backend should not expose async parse jobs")
assert(!apiMain.includes('@app.get("/api/jobs/{job_id}")'), "backend should keep parse job polling under /api/parse/jobs")
