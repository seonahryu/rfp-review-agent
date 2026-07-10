import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"

const root = process.cwd()
const uiRoot = path.join(root, "ui-rfp-review", "rfp-review-ui-main")
const apiClient = fs.readFileSync(path.join(uiRoot, "lib", "api-client.ts"), "utf8")
const uploadStep = fs.readFileSync(path.join(uiRoot, "components", "steps", "upload-step.tsx"), "utf8")
const types = fs.readFileSync(path.join(uiRoot, "lib", "types.ts"), "utf8")
const apiMain = fs.readFileSync(path.join(root, "api", "main.py"), "utf8")
const deployedUiRoot = path.join(root, "rfp-review-ui-clone")
const deployedUploadStep = fs.existsSync(deployedUiRoot)
  ? fs.readFileSync(path.join(deployedUiRoot, "components", "steps", "upload-step.tsx"), "utf8")
  : uploadStep

assert(
  apiClient.includes("failedPages"),
  "browser chunk parsing should track failed page numbers instead of throwing away successful pages",
)
assert(
  apiClient.includes("failedParsedPage"),
  "browser chunk parsing should create importable failed-page placeholders",
)
assert(
  apiClient.includes("parse_chunk_failed"),
  "failed chunk placeholders should be machine-identifiable",
)
assert(
  apiClient.includes("catch((err)") || apiClient.includes("catch (err)"),
  "per-page chunk failures should be caught before Promise.all can reject the whole parse",
)
assert(
  types.includes("chunk_parse_summary"),
  "review responses should expose chunk parse summary metadata to the UI",
)
assert(
  uploadStep.includes("파싱 성공") && uploadStep.includes("파싱 실패"),
  "upload UI should show visible success and failure page counts",
)
assert(
  uploadStep.includes("실패 페이지 제외하고 계속"),
  "upload UI should require an explicit continue action when pages failed",
)
assert(
  apiClient.includes("retryFailedPdfPages"),
  "UI should expose a retry function for failed pages",
)
assert(
  apiClient.includes("/api/parse/documents/") && apiClient.includes("/pages"),
  "failed-page retry should update selected pages on the existing parsed document",
)
assert(
  uploadStep.includes("handleRetryFailedPages") && uploadStep.includes("retryFailedPdfPages"),
  "failed-page retry button should call the retry flow",
)
assert(
  uploadStep.includes("selectedFailedPages"),
  "upload UI should track which failed pages the user selected for retry",
)
assert(
  uploadStep.includes("toggleFailedPageSelection"),
  "upload UI should let the user toggle individual failed pages",
)
assert(
  uploadStep.includes("pagesToRetry = [...selectedFailedPages]"),
  "failed-page retry should send only the selected failed pages",
)
assert(
  uploadStep.includes("선택한 페이지"),
  "failed-page retry UI should label the selected-page retry action",
)
assert(
  deployedUploadStep.includes("selectedFailedPages") &&
    deployedUploadStep.includes("pagesToRetry = [...selectedFailedPages]") &&
    deployedUploadStep.includes("선택한 페이지"),
  "deployed UI repo should also include selected failed-page retry controls",
)
assert(
  apiMain.includes('@app.post("/api/parse/documents/{document_id}/pages")'),
  "backend should expose an endpoint to overwrite selected parsed pages",
)
assert(
  apiMain.includes("replaced_page_numbers"),
  "backend should report which selected pages were overwritten",
)
assert(
  apiMain.includes('OPENAI_PDF_CHUNK_MAX_RETRIES", "0"'),
  "initial chunk parser should default to one backend attempt",
)
assert(
  apiClient.includes("parsePageChunk(file.name, sourcePdf, pageNo, totalPages).catch"),
  "initial browser chunk pass should try each page once and collect failures",
)
assert(
  apiClient.includes("parsePageChunkWithRetry(file.name, sourcePdf, pageNo, totalPages).catch"),
  "failed-page retry should retry only the collected failed pages",
)
