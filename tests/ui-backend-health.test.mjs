import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"

const root = process.cwd()
const routePath = path.join(
  root,
  "rfp-review-ui-clone",
  "app",
  "api",
  "backend-health",
  "route.ts",
)
const route = fs.readFileSync(routePath, "utf8")

assert(route.includes('`${BACKEND_API_URL}/health`'), "backend health route should call backend /health")
assert(route.includes("backendUrl"), "backend health route should expose the configured backend URL")
