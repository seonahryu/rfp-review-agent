import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"

const root = process.cwd()
const uiRoot = path.join(root, "rfp-review-ui-clone")
const apiClient = fs.readFileSync(path.join(uiRoot, "lib", "api-client.ts"), "utf8")

for (const endpoint of ["/api/parse", "/api/review/check", "/api/recommendations"]) {
  assert(
    apiClient.includes(`fetch(\`${"${BACKEND_API_URL}"}${endpoint}`),
    `long-running endpoint ${endpoint} should call Render directly instead of Vercel proxy`,
  )
}

assert(
  fs.existsSync(path.join(uiRoot, "app", "api", "backend-health", "route.ts")),
  "backend health diagnostic route should remain available",
)
