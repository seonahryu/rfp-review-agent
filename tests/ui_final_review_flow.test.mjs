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
assert(apiMain.includes("corrected_result: str ="), "backend feedback model should accept corrected legal compliance result")
assert(apiMain.includes("load_item_criteria"), "backend should load legal target and requirement criteria from DB")
assert(apiMain.includes('"target_text": criteria.get("target_text", "")'), "UI result should include legal target text")
assert(apiMain.includes('"requirement_texts": criteria.get("requirement_texts", [])'), "UI result should include legal requirement texts")
assert(
  apiMain.includes("item_criteria = load_item_criteria(db_path)"),
  "review check response should load full legal criteria, not only item titles",
)
assert(apiMain.includes("def corrected_is_target"), "backend should update target status from corrected legal compliance result")
assert(apiMain.includes('corrected_result in {"미준수", "보완필요"}'), "backend should backfill recommendation when user changes result to action-needed")
assert(
  apiMain.includes("result = corrected_result or item.normalized_result or item.review_result"),
  "backend recommendation input should prefer corrected legal compliance result",
)

for (const uiRoot of uiRoots) {
  const finalStep = fs.readFileSync(path.join(uiRoot, "components", "steps", "final-step.tsx"), "utf8")
  const recommendationStep = fs.readFileSync(path.join(uiRoot, "components", "steps", "recommendation-step.tsx"), "utf8")
  const itemDetailPanel = fs.readFileSync(path.join(uiRoot, "components", "item-detail-panel.tsx"), "utf8")
  const consoleView = fs.readFileSync(path.join(uiRoot, "components", "console.tsx"), "utf8")
  const types = fs.readFileSync(path.join(uiRoot, "lib", "types.ts"), "utf8")
  const resultItemCard = fs.readFileSync(path.join(uiRoot, "components", "result-item-card.tsx"), "utf8")
  const apiClient = fs.readFileSync(path.join(uiRoot, "lib", "api-client.ts"), "utf8")

  assert(finalStep.includes("법령준수 개선권고 주요항목"), "final table should keep the legal item column")
  assert(finalStep.includes(">법령준수 여부<"), "final table should keep 법령준수 여부 column")
  assert(finalStep.includes("법령준수 여부 복사"), "final step should show row-level legal compliance copy")
  assert(finalStep.includes("권고내용 복사"), "final step should show row-level recommendation copy")
  assert(finalStep.includes("const displayItems = results"), "final step should show every reviewed item")
  assert(!finalStep.includes("results.filter((r: ReviewItem) => r.is_target !== false)"), "final step should not hide not-applicable items")
  assert(recommendationStep.includes("법령준수여부 복사"), "recommendation step should include 법령준수여부 복사")
  assert(recommendationStep.includes("const displayItems = results"), "recommendation step should show not-applicable items too")
  assert(!recommendationStep.includes("results.filter((r: ReviewItem) => r.is_target !== false)"), "recommendation step should not hide not-applicable items")
  assert(finalStep.includes(">권고내용<"), "final table should show recommendation content column")
  assert(finalStep.includes("<RotateCcw"), "final step should show a new-review action")
  assert(finalStep.includes("새 검토"), "final confirmation should be replaced with 새 검토")
  assert(!finalStep.includes("최종 결과 확인"), "final confirmation text should be removed")
  assert(!finalStep.includes("검토의견 전체 복사"), "duplicate opinion copy button should be removed")
  assert(!finalStep.includes("개선권고 관련 법적 근거"), "old legal basis heading should be removed from UI")

  assert(itemDetailPanel.includes("onClose"), "detail panel should accept a close handler")
  assert(itemDetailPanel.includes("항목 상세 닫기"), "detail panel should expose a close button")
  assert(itemDetailPanel.includes("onPrevious"), "detail panel should support previous item navigation")
  assert(itemDetailPanel.includes("onNext"), "detail panel should support next item navigation")
  assert(itemDetailPanel.includes("correctedResult"), "detail panel should receive corrected legal compliance result")
  assert(itemDetailPanel.includes("displayResult"), "detail panel should show corrected legal compliance result")
  assert(itemDetailPanel.includes("HighlightedText"), "search results should highlight matching keywords")
  assert(itemDetailPanel.includes("PDF {hit.pdf_page}"), "search results should show PDF page when different")
  assert(consoleView.includes("detailPanelOpen"), "console should track detail panel visibility")

  assert(types.includes("pdf_page?: number | string"), "search hit type should include pdf_page")
  assert(types.includes("target_text?: string"), "review item type should include legal target text")
  assert(types.includes("requirement_texts?: string[]"), "review item type should include legal requirement texts")
  assert(types.includes("corrected_result?: string"), "feedback type should include corrected legal compliance result")
  assert(resultItemCard.includes("법령준수여부 수정"), "result confirmation card should let users correct legal compliance result")
  assert(resultItemCard.includes("RESULT_OPTIONS.map"), "legal compliance correction should use four explicit choice buttons")
  assert(resultItemCard.includes("aria-pressed={active}"), "legal compliance correction buttons should expose selected state")
  assert(resultItemCard.includes("statusFromResult(correctedResult)"), "result card badge should update from corrected legal compliance result")
  assert(resultItemCard.includes("corrected_result: correctedResult"), "result confirmation should submit corrected legal compliance result")
  assert(!resultItemCard.includes("수정 의견"), "review card should not show a separate free-form correction comment")
  assert(!resultItemCard.includes("comment: note.trim()"), "review card should not submit correction comments")
  assert(!resultItemCard.includes("note: note.trim()"), "review card should not submit correction notes")
  assert(resultItemCard.includes("참고 권고"), "review card should show draft recommendation for reviewer context")
  assert(!resultItemCard.includes("corrected_evidence_pairs)"), "review card should not show corrected evidence pair internals")
  assert(!resultItemCard.includes("근거 추가"), "review card should not allow corrected evidence pair editing")
  assert(!itemDetailPanel.includes("HighlightedEvidence"), "judgement evidence should not be specially highlighted")
  assert(itemDetailPanel.includes('DetailRow label="참고 권고"'), "detail panel should show draft recommendation for reviewer context")
  assert(itemDetailPanel.includes('DetailRow label="대상"'), "detail panel should show legal target criteria")
  assert(itemDetailPanel.includes("준수 항목"), "detail panel should show legal requirement criteria")
  assert(consoleView.includes("const confirmableItems = results"), "console should require confirmation for every reviewed item")
  assert(consoleView.includes("selectRelativeItem"), "console should let detail panel move between reviewed items")
  assert(consoleView.includes("selectedFeedback?.corrected_result"), "console should pass corrected result into detail panel")
  const globals = fs.readFileSync(path.join(uiRoot, "app", "globals.css"), "utf8")
  assert(globals.includes("overflow: hidden"), "page-level scrolling should be locked")
  assert(apiClient.includes("user_feedback: feedback[String(item.item_no)]"), "recommendation generation should send item feedback")
}
