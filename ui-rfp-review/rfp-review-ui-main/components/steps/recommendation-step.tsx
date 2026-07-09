"use client"

import { AlertTriangle, ArrowLeft, CheckCircle2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { StepHeader } from "@/components/step-header"
import { StatusBadge } from "@/components/status-badge"
import { CopyButton } from "@/components/copy-button"
import { normalizeStatus, type ReviewItem, type ReviewResponse, type UserFeedback } from "@/lib/types"
import { cn } from "@/lib/utils"

export function RecommendationStep({
  response,
  feedback,
  selectedKey,
  confirmed,
  allComplete,
  onSelect,
  onConfirm,
  onBack,
}: {
  response: ReviewResponse
  feedback: Record<string, UserFeedback>
  selectedKey: string | null
  confirmed: boolean
  allComplete: boolean
  onSelect: (key: string) => void
  onConfirm: () => void
  onBack: () => void
}) {
  const displayItems = response.results ?? []
  const feedbackCount = Object.values(feedback).filter(
    (f) => f?.corrected_result || f?.manual_compliance_content,
  ).length
  const emptyContent = displayItems.filter((r) => !((r.compliance_content ?? "").trim()))

  return (
    <div>
      <StepHeader
        step={3}
        title="권고 문장 생성"
        description="확정된 검토결과를 기준으로 권고내용을 확인합니다."
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
          <Tile label="수정/직접 입력" value={feedbackCount} />
          <Tile label="권고내용 누락" value={emptyContent.length} accent={emptyContent.length > 0} />
        </div>

        {emptyContent.length > 0 && (
          <p className="mb-4 flex items-center gap-1.5 rounded-md border border-status-attention/40 bg-status-attention-bg px-3 py-2 text-sm text-foreground">
            <AlertTriangle className="size-4 text-status-attention" />
            권고내용이 비어 있는 항목이 있습니다.
          </p>
        )}

        <div className="space-y-3">
          {displayItems.map((item) => {
            const key = String(item.item_no)
            const selected = selectedKey === key
            return (
              <div
                key={key}
                role="button"
                tabIndex={0}
                onClick={() => onSelect(key)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault()
                    onSelect(key)
                  }
                }}
                className={cn(
                  "cursor-pointer rounded-lg border bg-card p-4 transition-colors",
                  selected ? "border-primary ring-1 ring-primary/30" : "border-border hover:border-primary/40",
                )}
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-muted-foreground">#{item.item_no}</span>
                  <h3 className="text-sm font-semibold text-foreground">{item.law_name || "법제도명 없음"}</h3>
                  <StatusBadge status={normalizeStatus(item)} />
                </div>

                {item.detailed_assessment && <DetailedAssessmentTable item={item} />}

                <div className="mt-3 rounded-md bg-muted/50 p-3">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-medium text-muted-foreground">권고내용</p>
                    <div className="flex flex-wrap items-center justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
                      <CopyButton label="법령준수여부 복사" text={item.copy_texts?.review_result ?? item.normalized_result} />
                      <CopyButton label="권고내용 복사" text={item.copy_texts?.compliance_content ?? item.compliance_content} />
                      {item.detailed_assessment && (
                        <CopyButton label="전체 명시 여부 복사" text={item.copy_texts?.internal_assessment ?? internalAssessmentCopyText(item)} />
                      )}
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
            )
          })}
        </div>

        <div className="mt-6 flex items-center justify-end gap-3">
          {!allComplete && (
            <span className="mr-auto flex items-center gap-1.5 text-sm text-status-attention">
              <AlertTriangle className="size-4" />
              판단결과와 권고내용이 모두 있어야 최종 결과로 이동할 수 있습니다.
            </span>
          )}
          {confirmed && (
            <span className="inline-flex items-center gap-1.5 text-sm text-status-compliant">
              <CheckCircle2 className="size-4" /> 최종 확인 완료
            </span>
          )}
          <Button onClick={onConfirm} disabled={!allComplete} className="gap-1.5">
            <CheckCircle2 className="size-4" />
            권고 문장 생성 결과 확인
          </Button>
        </div>
      </div>
    </div>
  )
}

function DetailedAssessmentTable({ item }: { item: ReviewItem }) {
  const assessment = item.detailed_assessment
  if (!assessment) return null
  return (
    <div className="mt-3 overflow-hidden rounded-md border border-border">
      <table className="w-full table-fixed border-collapse text-xs">
        <thead className="bg-muted/70 text-muted-foreground">
          <tr>
            <th className="w-12 border border-border px-2 py-1.5 font-medium">구분</th>
            <th className="border border-border px-2 py-1.5 font-medium">내용</th>
            <th className="w-20 border border-border px-2 py-1.5 font-medium">명시 여부</th>
          </tr>
        </thead>
        <tbody>
          {assessment.rows.map((row) => (
            <tr key={row.no} className="align-top">
              <td className="border border-border px-2 py-1.5 text-center font-mono text-muted-foreground">{row.no}</td>
              <td className="border border-border px-2 py-1.5 text-foreground">
                <p className="font-medium">{row.title}</p>
                <p className="mt-1 leading-relaxed text-muted-foreground">{row.content}</p>
              </td>
              <td className="border border-border px-2 py-1.5 text-center font-semibold text-foreground">{row.explicit_status}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="border-t border-border px-2 py-1.5 text-xs font-medium text-foreground">
        최종 판단: {assessment.final_result}
      </p>
    </div>
  )
}

function internalAssessmentCopyText(item: ReviewItem): string {
  const assessment = item.detailed_assessment
  if (!assessment) return ""
  const lines = [`${item.item_no}. ${item.law_name || assessment.title}`, "", "구분\t내용\t명시 여부"]
  for (const row of assessment.rows) {
    lines.push(`${row.no}\t${row.title}\n${row.content}\t${row.explicit_status}`)
  }
  lines.push("", `최종 판단\t${assessment.final_result}`)
  if (assessment.reason) lines.push(`판단 근거\t${assessment.reason}`)
  return lines.join("\n")
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
