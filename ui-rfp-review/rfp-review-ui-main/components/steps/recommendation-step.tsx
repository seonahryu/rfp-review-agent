"use client"

import { AlertTriangle, ArrowLeft, CheckCircle2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { StepHeader } from "@/components/step-header"
import { StatusBadge } from "@/components/status-badge"
import { CopyButton } from "@/components/copy-button"
import { normalizeStatus, type ReviewResponse, type UserFeedback } from "@/lib/types"
import { cn } from "@/lib/utils"

export function RecommendationStep({
  response,
  feedback,
  confirmed,
  allComplete,
  onConfirm,
  onBack,
}: {
  response: ReviewResponse
  feedback: Record<string, UserFeedback>
  confirmed: boolean
  allComplete: boolean
  onConfirm: () => void
  onBack: () => void
}) {
  const results = response.results ?? []
  const displayItems = results
  const feedbackCount = Object.values(feedback).filter(
    (f) => f?.comment || f?.note || f?.corrected_result || f?.corrected_evidence_pairs?.length,
  ).length
  const emptyContent = displayItems.filter((r) => !((r.compliance_content ?? "").trim()))

  return (
    <div>
      <StepHeader
        step={5}
        title="권고 문장 생성"
        description="확인 완료된 항목의 권고내용을 검토하고 최종 컨펌합니다."
        actions={
          <Button variant="ghost" size="sm" onClick={onBack} className="gap-1.5">
            <ArrowLeft className="size-4" />
            검토결과로
          </Button>
        }
      />
      <div className="mx-auto max-w-4xl px-8 py-6">
        <div className="mb-4 grid grid-cols-3 gap-3">
          <Tile label="전체 항목" value={displayItems.length} />
          <Tile label="수정 의견 반영" value={feedbackCount} />
          <Tile label="권고내용 누락" value={emptyContent.length} accent={emptyContent.length > 0} />
        </div>

        {emptyContent.length > 0 && (
          <p className="mb-4 flex items-center gap-1.5 rounded-md border border-status-attention/40 bg-status-attention-bg px-3 py-2 text-sm text-foreground">
            <AlertTriangle className="size-4 text-status-attention" />
            권고내용이 비어 있는 항목이 있습니다. 최종 결과 단계에서는 비어 있는 항목이 없어야 합니다.
          </p>
        )}

        <div className="space-y-3">
          {displayItems.map((item) => (
            <div key={String(item.item_no)} className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs text-muted-foreground">#{item.item_no}</span>
                <h3 className="text-sm font-semibold text-foreground">{item.law_name || "법제도명 없음"}</h3>
                <StatusBadge status={normalizeStatus(item)} />
              </div>
              <div className="mt-2 rounded-md bg-muted/50 p-3">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-medium text-muted-foreground">권고내용</p>
                  <div className="flex flex-wrap items-center justify-end gap-1.5">
                    <CopyButton label="법령준수여부 복사" text={item.copy_texts?.review_result ?? item.normalized_result} />
                    <CopyButton label="권고내용 복사" text={item.copy_texts?.compliance_content ?? item.compliance_content} />
                  </div>
                </div>
                <p
                  className={cn(
                    "mt-1.5 whitespace-pre-wrap text-sm leading-relaxed",
                    (item.compliance_content ?? "").trim() ? "text-foreground" : "text-status-attention",
                  )}
                >
                  {(item.compliance_content ?? "").trim() || "권고내용이 비어 있습니다."}
                </p>
              </div>
            </div>
          ))}
        </div>

        <div className="mt-6 flex items-center justify-end gap-3">
          {!allComplete && (
            <span className="mr-auto flex items-center gap-1.5 text-sm text-status-attention">
              <AlertTriangle className="size-4" />
              판단결과와 권고내용이 완성되어야 최종 결과로 이동할 수 있습니다.
            </span>
          )}
          {confirmed && (
            <span className="inline-flex items-center gap-1.5 text-sm text-status-compliant">
              <CheckCircle2 className="size-4" /> 최종 컨펌 완료
            </span>
          )}
          <Button onClick={onConfirm} disabled={!allComplete} className="gap-1.5">
            <CheckCircle2 className="size-4" />
            권고 문장 생성 결과 컨펌
          </Button>
        </div>
      </div>
    </div>
  )
}

function Tile({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("mt-1 text-2xl font-semibold tabular-nums", accent ? "text-status-attention" : "text-foreground")}>
        {value}
      </p>
    </div>
  )
}
