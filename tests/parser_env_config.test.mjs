import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"

const root = process.cwd()
const parser = fs.readFileSync(path.join(root, "agents", "gpt_parser_agent.py"), "utf8")
const render = fs.readFileSync(path.join(root, "render.yaml"), "utf8")

assert(parser.includes("OPENAI_PDF_TIMEOUT_SECONDS"), "parser should read timeout seconds from env")
assert(parser.includes("OPENAI_PDF_MAX_RETRIES"), "parser should read max retries from env")
assert(render.includes("OPENAI_PDF_PAGES_PER_CALL"), "Render config should set parser page chunk size")
assert(render.includes("OPENAI_PDF_TIMEOUT_SECONDS"), "Render config should set parser timeout")
assert(render.includes("OPENAI_PDF_MAX_RETRIES"), "Render config should set parser retry count")
