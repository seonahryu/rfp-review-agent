"use client"

import { AlertTriangle, ArrowRight, CheckCircle2, ShieldCheck } from "lucide-react"
import { Button } from "@/components/ui/button"
import { StepHeader } from "@/components/step-header"
import { StatusBadge } from "@/components/status-badge"
import { normalizeStatus, type ReviewResponse } from "@/lib/types"
import { cn } from "@/lib/utils"

export function ProgressStep({
  response,
  onProceed,
}: {
  response: ReviewResponse
  onProceed: () => void
}) {
  const results = response.results ?? []
  const attentionCount = results.filter((r) => r.user_action_required || r.needs_user_attention).length

  return (
    <div>
      <StepHeader
        step={3}
        title="검토 진행"
        description="항목별 검토 진행 상태입니다. 검토가 완료된 항목을 확인하세요."
        actions={
          <Button onClick={onProceed} className="gap-1.5">
            검토결과 확인
            <ArrowRight className="size-4" />
          </Button>
        }
      />
      <div className="mx-auto max-w-4xl px-8 py-8">
        <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <SummaryTile label="전체 항목" value={results.length} />
          <SummaryTile label="검토 완료" value={results.length} accent="compliant" />
          <SummaryTile label="확인 필요" value={attentionCount} accent="attention" />
          <SummaryTile
            label="대상 항목"
            value={results.filter((r) => r.is_target !== false).length}
          />
        </div>

        <div className="overflow-hidden rounded-lg border border-border bg-card">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/50 text-left text-xs text-muted-foreground">
                <th className="px-4 py-2.5 font-medium">항목</th>
                <th className="px-4 py-2.5 font-medium">법령명</th>
                <th className="px-4 py-2.5 font-medium">상태</th>
                <th className="px-4 py-2.5 font-medium">진행</th>
              </tr>
            </thead>
            <tbody>
              {results.map((item) => {
                const attention = item.user_action_required || item.needs_user_attention
                return (
                  <tr key={String(item.item_no)} className="border-b border-border last:border-0">
                    <td className="px-4 py-2.5 font-mono text-xs text-muted-foreground">
                      {item.item_no}
                    </td>
                    <td className="px-4 py-2.5 font-medium text-foreground">{item.law_name}</td>
                    <td className="px-4 py-2.5">
                      <StatusBadge status={normalizeStatus(item)} />
                    </td>
                    <td className="px-4 py-2.5">
                      {attention ? (
                        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-status-attention">
                          <AlertTriangle className="size-3.5" /> 사용자 확인 필요
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 text-xs text-status-compliant">
                          <CheckCircle2 className="size-3.5" /> 완료
                        </span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        <p className="mt-4 flex items-center gap-1.5 text-xs text-muted-foreground">
          <ShieldCheck className="size-3.5" />
          검토·검증이 완료되었습니다. 다음 단계에서 각 항목을 개별적으로 확인·컨펌하세요.
        </p>
      </div>
    </div>
  )
}

function SummaryTile({
  label,
  value,
  accent,
}: {
  label: string
  value: number
  accent?: "compliant" | "attention"
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-1 text-2xl font-semibold tabular-nums",
          accent === "compliant" && "text-status-compliant",
          accent === "attention" && value > 0 && "text-status-attention",
          !accent && "text-foreground",
        )}
      >
        {value}
      </p>
    </div>
  )
}
