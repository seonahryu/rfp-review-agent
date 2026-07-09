"use client"

import { RotateCcw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { StepHeader } from "@/components/step-header"
import { StatusBadge } from "@/components/status-badge"
import { CopyButton } from "@/components/copy-button"
import { normalizeStatus, type ReviewItem, type ReviewResponse } from "@/lib/types"

export function FinalStep({
  response,
  onReset,
}: {
  response: ReviewResponse
  onReset: () => void
}) {
  const displayItems = response.results ?? []
  const opinion = response.review_opinion

  return (
    <div>
      <StepHeader
        step={6}
        title="최종 결과"
        description="HWP 표에 붙여넣기 쉬운 형태로 정리한 최종 검토결과입니다."
      />
      <div className="mx-auto max-w-5xl px-8 py-6">
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          <p className="leading-relaxed">
            <span className="font-medium text-foreground">전체 검토결과 복사</span>는 법령준수여부 열에 붙여넣기 위한 값입니다.
          </p>
          <CopyButton label="전체 검토결과 복사" text={response.review_result_column_text} variant="secondary" />
        </div>

        <div className="overflow-hidden rounded-lg border border-border bg-card">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/60 text-left text-xs text-muted-foreground">
                <th className="w-12 border-r border-border px-3 py-2.5 font-medium">번호</th>
                <th className="border-r border-border px-3 py-2.5 font-medium">법령준수 개선권고 주요항목</th>
                <th className="w-28 border-r border-border px-3 py-2.5 font-medium">법령준수 여부</th>
                <th className="border-r border-border px-3 py-2.5 font-medium">권고내용</th>
                <th className="w-40 px-3 py-2.5 font-medium">복사</th>
              </tr>
            </thead>
            <tbody>
              {displayItems.map((item) => (
                <tr key={String(item.item_no)} className="border-b border-border align-top last:border-0">
                  <td className="border-r border-border px-3 py-3 font-mono text-xs text-muted-foreground">
                    {item.item_no}
                  </td>
                  <td className="border-r border-border px-3 py-3">
                    <p className="font-medium text-foreground">{item.law_name || "법제도명 없음"}</p>
                  </td>
                  <td className="border-r border-border px-3 py-3">
                    <StatusBadge status={normalizeStatus(item)} />
                  </td>
                  <td className="border-r border-border px-3 py-3">
                    {item.detailed_assessment && <DetailedAssessmentTable item={item} />}
                    <p className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-foreground">
                      {(item.compliance_content ?? "").trim() || "-"}
                    </p>
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex flex-col gap-1.5">
                      <CopyButton label="법령준수여부 복사" text={item.copy_texts?.review_result ?? item.normalized_result} />
                      <CopyButton label="권고내용 복사" text={item.copy_texts?.compliance_content ?? item.compliance_content} />
                      {item.detailed_assessment && (
                        <CopyButton label="전체 명시 여부 복사" text={item.copy_texts?.internal_assessment ?? internalAssessmentCopyText(item)} />
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <section className="mt-6 rounded-lg border border-border bg-card p-5">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-foreground">검토의견</h3>
            <CopyButton label="검토의견 복사" text={opinion?.copy_text} />
          </div>
          <pre className="mt-3 max-h-96 overflow-y-auto whitespace-pre-wrap rounded-md border border-border bg-muted/40 p-4 font-sans text-sm leading-relaxed text-foreground">
            {opinion?.copy_text?.trim() || "검토의견이 없습니다."}
          </pre>
        </section>

        <div className="mt-6 flex items-center justify-end">
          <Button onClick={onReset} className="gap-1.5">
            <RotateCcw className="size-4" />
            새 검토
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
    <div className="overflow-hidden rounded-md border border-border">
      <table className="w-full table-fixed border-collapse text-xs">
        <thead>
          <tr className="bg-muted/60 text-muted-foreground">
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
