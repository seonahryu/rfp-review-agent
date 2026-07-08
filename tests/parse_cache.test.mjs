import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"

const apiMain = fs.readFileSync(path.join(process.cwd(), "api", "main.py"), "utf8")

assert(apiMain.includes("hashlib"), "backend should hash uploaded PDFs")
assert(apiMain.includes("parse_cache_path"), "backend should define a persistent parse cache path")
assert(apiMain.includes("load_parse_cache"), "backend should load cached parse results")
assert(apiMain.includes("save_parse_cache"), "backend should persist parse results")
assert(apiMain.includes("file_hash"), "parse jobs should expose the uploaded file hash")
