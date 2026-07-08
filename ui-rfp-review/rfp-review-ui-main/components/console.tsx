"use client"

import { useCallback, useMemo, useState } from "react"
import { toast } from "sonner"
import type { ReviewItem, ReviewResponse, UserFeedback } from "@/lib/types"
import { generateRecommendations } from "@/lib/api-client"
import { type StepKey, stepIndexOf } from "@/lib/steps"
import { StepSidebar } from "@/components/step-sidebar"
import { UploadStep } from "@/components/steps/upload-step"
import { ParseStep } from "@/components/steps/parse-step"
import { ProgressStep } from "@/components/steps/progress-step"
import { ResultsStep } from "@/components/steps/results-step"
import { RecommendationStep } from "@/components/steps/recommendation-step"
import { FinalStep } from "@/components/steps/final-step"
import { ItemDetailPanel } from "@/components/item-detail-panel"

export function itemKey(item: ReviewItem): string {
  return String(item.item_no)
}

export function Console() {
  const [response, setResponse] = useState<ReviewResponse | null>(null)
  const [current, setCurrent] = useState<StepKey>("upload")
  const [maxReached, setMaxReached] = useState<StepKey>("upload")

  const [parseConfirmed, setParseConfirmed] = useState(false)
  const [confirmedItems, setConfirmedItems] = useState<Record<string, boolean>>({})
  const [feedback, setFeedback] = useState<Record<string, UserFeedback>>({})
  const [recommendationConfirmed, setRecommendationConfirmed] = useState(false)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [detailPanelOpen, setDetailPanelOpen] = useState(true)
  const [generatingRecommendations, setGeneratingRecommendations] = useState(false)

  const results = response?.results ?? []
  const confirmableItems = results
  const allConfirmed = useMemo(
    () => confirmableItems.length > 0 && confirmableItems.every((r) => confirmedItems[itemKey(r)]),
    [confirmableItems, confirmedItems],
  )
  const canGenerate = allConfirmed && !generatingRecommendations
  const allComplete = response?.all_items_complete === true
  const selectedItem = results.find((r) => itemKey(r) === selectedKey) ?? null

  const advanceTo = useCallback((key: StepKey) => {
    setCurrent(key)
    setMaxReached((prev) => (stepIndexOf(key) > stepIndexOf(prev) ? key : prev))
  }, [])

  const navigate = useCallback(
    (key: StepKey) => {
      if (stepIndexOf(key) <= stepIndexOf(maxReached)) setCurrent(key)
    },
    [maxReached],
  )

  const handleReviewComplete = useCallback((resp: ReviewResponse) => {
    setResponse(resp)
    setParseConfirmed(false)
    setConfirmedItems({})
    setFeedback({})
    setRecommendationConfirmed(false)
    setGeneratingRecommendations(false)
    const first = resp.results?.[0]
    setSelectedKey(first ? itemKey(first) : null)
    setDetailPanelOpen(true)
    setCurrent("parse")
    setMaxReached("parse")
  }, [])

  const handleReset = useCallback(() => {
    setResponse(null)
    setParseConfirmed(false)
    setConfirmedItems({})
    setFeedback({})
    setRecommendationConfirmed(false)
    setGeneratingRecommendations(false)
    setSelectedKey(null)
    setDetailPanelOpen(true)
    setCurrent("upload")
    setMaxReached("upload")
  }, [])

  const confirmParse = useCallback(() => {
    setParseConfirmed(true)
    advanceTo("progress")
    toast.success("PDF 파싱 검증 결과를 확인했습니다.")
  }, [advanceTo])

  const confirmItem = useCallback((key: string, fb: UserFeedback) => {
    setConfirmedItems((prev) => ({ ...prev, [key]: true }))
    setFeedback((prev) => ({ ...prev, [key]: { ...fb, resolved: true, status: "submitted" } }))
  }, [])

  const unconfirmItem = useCallback((key: string) => {
    setConfirmedItems((prev) => ({ ...prev, [key]: false }))
  }, [])

  const toRecommendation = useCallback(async () => {
    if (!response) return
    if (!allConfirmed) {
      toast.error("확인하지 않은 항목이 있습니다. 모든 항목을 확인해 주세요.")
      return
    }

    setGeneratingRecommendations(true)
    try {
      const next = await generateRecommendations(String(response.document_id), response.results ?? [], feedback)
      setResponse(next)
      const first = next.results?.[0]
      setSelectedKey(first ? itemKey(first) : null)
      setDetailPanelOpen(true)
      advanceTo("recommendation")
      toast.success("권고 문장 생성이 완료되었습니다.")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "권고 문장 생성에 실패했습니다.")
    } finally {
      setGeneratingRecommendations(false)
    }
  }, [allConfirmed, response, feedback, advanceTo])

  const confirmRecommendation = useCallback(() => {
    if (!allComplete) {
      toast.error("모든 항목의 판단결과와 권고내용이 완성되어야 최종 결과로 이동할 수 있습니다.")
      return
    }
    setRecommendationConfirmed(true)
    advanceTo("final")
    toast.success("권고 문장 생성 결과를 확인했습니다.")
  }, [allComplete, advanceTo])

  const showDetailPanel = current === "results" || current === "recommendation" || current === "final"
  const selectItem = useCallback((key: string) => {
    setSelectedKey(key)
    setDetailPanelOpen(true)
  }, [])
  const selectedIndex = selectedKey ? results.findIndex((r) => itemKey(r) === selectedKey) : -1
  const selectRelativeItem = useCallback(
    (offset: number) => {
      if (results.length === 0) return
      const baseIndex = selectedIndex >= 0 ? selectedIndex : 0
      const nextIndex = Math.min(results.length - 1, Math.max(0, baseIndex + offset))
      const next = results[nextIndex]
      if (next) selectItem(itemKey(next))
    },
    [results, selectedIndex, selectItem],
  )

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-background text-foreground">
      <StepSidebar current={current} maxReached={maxReached} onNavigate={navigate} />

      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto">
          {current === "upload" && <UploadStep onComplete={handleReviewComplete} />}
          {current === "parse" && response && (
            <ParseStep response={response} confirmed={parseConfirmed} onConfirm={confirmParse} onReset={handleReset} />
          )}
          {current === "progress" && response && (
            <ProgressStep response={response} onProceed={() => advanceTo("results")} />
          )}
          {current === "results" && response && (
            <ResultsStep
              response={response}
              confirmedItems={confirmedItems}
              feedback={feedback}
              selectedKey={selectedKey}
              onSelect={selectItem}
              onConfirmItem={confirmItem}
              onUnconfirmItem={unconfirmItem}
              allConfirmed={allConfirmed}
              canGenerate={canGenerate}
              onProceed={toRecommendation}
            />
          )}
          {current === "recommendation" && response && (
            <RecommendationStep
              response={response}
              feedback={feedback}
              confirmed={recommendationConfirmed}
              allComplete={allComplete}
              onConfirm={confirmRecommendation}
              onBack={() => setCurrent("results")}
            />
          )}
          {current === "final" && response && (
            <FinalStep response={response} onReset={handleReset} />
          )}
        </div>
      </main>

      {showDetailPanel && response && detailPanelOpen && (
        <ItemDetailPanel
          item={selectedItem}
          documentId={String(response.document_id)}
          confirmed={selectedItem ? Boolean(confirmedItems[itemKey(selectedItem)]) : false}
          position={selectedIndex >= 0 ? selectedIndex + 1 : 0}
          total={results.length}
          onPrevious={() => selectRelativeItem(-1)}
          onNext={() => selectRelativeItem(1)}
          onClose={() => setDetailPanelOpen(false)}
        />
      )}
    </div>
  )
}
