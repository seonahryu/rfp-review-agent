import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"

const root = process.cwd()
const uiRoots = [
  path.join(root, "rfp-review-ui-clone"),
  path.join(root, "ui-rfp-review", "rfp-review-ui-main"),
].filter((candidate) => fs.existsSync(candidate))

for (const uiRoot of uiRoots) {
  const apiClient = fs.readFileSync(path.join(uiRoot, "lib", "api-client.ts"), "utf8")

  for (const endpoint of ["/api/parse", "/api/review/check"]) {
    assert(
      apiClient.includes(`fetch(\`${"${BACKEND_API_URL}"}${endpoint}`),
      `long-running endpoint ${endpoint} should try Render directly first`,
    )
  }
  assert(apiClient.includes('fetch("/api/parse"'), "parse should keep a same-origin fallback")
  assert(apiClient.includes('fetch("/api/review/check"'), "review check should keep a same-origin fallback")

  assert(
    apiClient.includes('fetch("/api/recommendations"'),
    "recommendation generation should use same-origin proxy to avoid browser CORS failures",
  )
  assert(
    apiClient.includes("fetch(`/api/documents/"),
    "document search should use same-origin proxy to avoid browser CORS failures",
  )

  assert(
    fs.existsSync(path.join(uiRoot, "app", "api", "documents", "[document_id]", "search", "route.ts")),
    "document search proxy route should exist",
  )
  assert(
    fs.existsSync(path.join(uiRoot, "app", "api", "recommendations", "route.ts")),
    "recommendation proxy route should exist",
  )
  assert(
    fs.existsSync(path.join(uiRoot, "app", "api", "parse", "route.ts")),
    "parse fallback proxy route should exist",
  )
  assert(
    fs.existsSync(path.join(uiRoot, "app", "api", "review", "check", "route.ts")),
    "review check fallback proxy route should exist",
  )
}

const renderYaml = fs.readFileSync(path.join(root, "render.yaml"), "utf8")
assert(
  renderYaml.includes("https://rfp-review-ui.vercel.app"),
  "Render CORS origins should include the production UI URL",
)

assert(
  fs.existsSync(path.join(root, "rfp-review-ui-clone", "app", "api", "backend-health", "route.ts")),
  "backend health diagnostic route should remain available",
)
