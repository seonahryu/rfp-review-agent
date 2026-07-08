import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"

const root = process.cwd()
const uiRoots = [
  path.join(root, "rfp-review-ui-clone"),
  path.join(root, "ui-rfp-review", "rfp-review-ui-main"),
].filter((candidate) => fs.existsSync(candidate))

const apiMain = fs.readFileSync(path.join(root, "api", "main.py"), "utf8")

assert(apiMain.includes("printed_page_select"), "search should choose printed RFP page column dynamically")
assert(apiMain.includes("NULL AS rfp_printed_page_no"), "search should tolerate older rfp_page schemas")
assert(apiMain.includes('"page": row["rfp_printed_page_no"] or row["page_no"]'), "search should prefer printed RFP page")
assert(apiMain.includes('"pdf_page": row["page_no"]'), "search should expose original PDF page separately")
assert(!apiMain.includes('lines = [\n        "검토의견"'), "review opinion copy text should not start with a label")

for (const uiRoot of uiRoots) {
  const finalStep = fs.readFileSync(path.join(uiRoot, "components", "steps", "final-step.tsx"), "utf8")
  const recommendationStep = fs.readFileSync(path.join(uiRoot, "components", "steps", "recommendation-step.tsx"), "utf8")
  const itemDetailPanel = fs.readFileSync(path.join(uiRoot, "components", "item-detail-panel.tsx"), "utf8")
  const consoleView = fs.readFileSync(path.join(uiRoot, "components", "console.tsx"), "utf8")
  const types = fs.readFileSync(path.join(uiRoot, "lib", "types.ts"), "utf8")

  assert(finalStep.includes("법령준수 개선권고 주요항목"), "final table should keep the legal item column")
  assert(finalStep.includes(">법령준수 여부<"), "final table should keep 법령준수 여부 column")
  assert(!finalStep.includes("법령준수여부 복사"), "final step should not show row-level legal compliance copy")
  assert(!finalStep.includes("권고내용 복사"), "final step should not show row-level recommendation copy")
  assert(recommendationStep.includes("법령준수여부 복사"), "recommendation step should include 법령준수여부 복사")
  assert(finalStep.includes(">권고내용<"), "final table should show recommendation content column")
  assert(finalStep.includes("<RotateCcw"), "final step should show a new-review action")
  assert(finalStep.includes("새 검토"), "final confirmation should be replaced with 새 검토")
  assert(!finalStep.includes("최종 결과 확인"), "final confirmation text should be removed")
  assert(!finalStep.includes("검토의견 전체 복사"), "duplicate opinion copy button should be removed")
  assert(!finalStep.includes("개선권고 관련 법적 근거"), "old legal basis heading should be removed from UI")

  assert(itemDetailPanel.includes("onClose"), "detail panel should accept a close handler")
  assert(itemDetailPanel.includes("항목 상세 닫기"), "detail panel should expose a close button")
  assert(itemDetailPanel.includes("HighlightedText"), "search results should highlight matching keywords")
  assert(itemDetailPanel.includes("PDF {hit.pdf_page}"), "search results should show PDF page when different")
  assert(consoleView.includes("detailPanelOpen"), "console should track detail panel visibility")

  assert(types.includes("pdf_page?: number | string"), "search hit type should include pdf_page")
}
