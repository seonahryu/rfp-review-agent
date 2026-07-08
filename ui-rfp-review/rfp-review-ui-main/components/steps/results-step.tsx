"use client"

import { ArrowRight, CheckCircle2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { StepHeader } from "@/components/step-header"
import { ResultItemCard } from "@/components/result-item-card"
import { itemKey } from "@/components/console"
import type { ReviewResponse, UserFeedback } from "@/lib/types"

export function ResultsStep({
  response,
  confirmedItems,
  feedback,
  selectedKey,
  onSelect,
  onConfirmItem,
  onUnconfirmItem,
  allConfirmed,
  canGenerate,
  onProceed,
}: {
  response: ReviewResponse
  confirmedItems: Record<string, boolean>
  feedback: Record<string, UserFeedback>
  selectedKey: string | null
  onSelect: (key: string) => void
  onConfirmItem: (key: string, fb: UserFeedback) => void
  onUnconfirmItem: (key: string) => void
  allConfirmed: boolean
  canGenerate: boolean
  onProceed: () => void
}) {
  const results = response.results ?? []
  const confirmedCount = results.filter((r) => confirmedItems[itemKey(r)]).length

  return (
    <div>
      <StepHeader
        step={4}
        title="검토결과 확인"
        description="항목별 결과와 근거를 확인하고 각 항목을 컨펌하세요."
        actions={
          <>
            <span className="text-sm text-muted-foreground">
              확인 <span className="font-semibold text-foreground tabular-nums">{confirmedCount}</span>
              {" / "}
              {results.length}
            </span>
            <Button onClick={onProceed} disabled={!allConfirmed || !canGenerate} className="gap-1.5">
              권고 문장 생성
              <ArrowRight className="size-4" />
            </Button>
          </>
        }
      />
      <div className="mx-auto max-w-4xl px-8 py-6">
        {!allConfirmed && (
          <p className="mb-4 rounded-md border border-status-attention/30 bg-status-attention-bg px-3 py-2 text-sm text-foreground">
            확인하지 않은 항목이 있습니다. 모든 검토 항목을 확인해야 권고 문장 생성 단계로 넘어갈 수 있습니다.
          </p>
        )}
        {allConfirmed && canGenerate && (
          <p className="mb-4 flex items-center gap-1.5 rounded-md border border-status-compliant/30 bg-status-compliant-bg px-3 py-2 text-sm text-foreground">
            <CheckCircle2 className="size-4 text-status-compliant" />
            모든 항목이 확인되었습니다. 권고 문장 생성 단계로 진행할 수 있습니다.
          </p>
        )}

        <div className="space-y-3">
          {results.map((item) => {
            const key = itemKey(item)
            return (
              <ResultItemCard
                key={key}
                item={item}
                selected={selectedKey === key}
                confirmed={Boolean(confirmedItems[key])}
                feedback={feedback[key]}
                onSelect={() => onSelect(key)}
                onConfirm={(fb) => onConfirmItem(key, fb)}
                onUnconfirm={() => onUnconfirmItem(key)}
              />
            )
          })}
        </div>
      </div>
    </div>
  )
}
