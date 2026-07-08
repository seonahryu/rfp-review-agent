import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"

const root = process.cwd()
const apiMain = fs.readFileSync(path.join(root, "api", "main.py"), "utf8")
const apiClient = fs.readFileSync(path.join(root, "rfp-review-ui-clone", "lib", "api-client.ts"), "utf8")

assert(apiMain.includes('@app.post("/api/parse")'), "backend should keep direct parse endpoint")
assert(apiClient.includes("/api/parse`"), "UI should call the direct parse endpoint")
assert(!apiClient.includes("/api/parse/start"), "UI should not use async parse jobs")
assert(!apiClient.includes("/api/jobs/"), "UI should not poll parse jobs")
assert(!apiMain.includes('@app.post("/api/parse/start")'), "backend should not expose async parse jobs")
assert(!apiMain.includes('@app.get("/api/jobs/{job_id}")'), "backend should not expose job polling")
