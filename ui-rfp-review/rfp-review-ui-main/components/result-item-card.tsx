"use client"

import { useState } from "react"
import { CheckCircle2, ChevronDown, Pencil, Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { StatusBadge, AttentionBadge } from "@/components/status-badge"
import {
  attentionReasonText,
  normalizeStatus,
  STATUS_LABEL,
  type EvidencePair,
  type ReviewItem,
  type StatusKey,
  type UserFeedback,
} from "@/lib/types"
import { cn } from "@/lib/utils"

const RESULT_OPTIONS = [
  { value: "준수", className: "border-status-compliant/40 text-status-compliant bg-status-compliant-bg" },
  { value: "미준수", className: "border-status-noncompliant/40 text-status-noncompliant bg-status-noncompliant-bg" },
  { value: "보완필요", className: "border-status-revision/40 text-status-revision bg-status-revision-bg" },
  { value: "해당없음", className: "border-status-na/40 text-status-na bg-status-na-bg" },
] as const

export function ResultItemCard({
  item,
  selected,
  confirmed,
  feedback,
  onSelect,
  onConfirm,
  onUnconfirm,
}: {
  item: ReviewItem
  selected: boolean
  confirmed: boolean
  feedback?: UserFeedback
  onSelect: () => void
  onConfirm: (fb: UserFeedback) => void
  onUnconfirm: () => void
}) {
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState(feedback?.comment ?? feedback?.note ?? "")
  const [pairs, setPairs] = useState<EvidencePair[]>(feedback?.corrected_evidence_pairs ?? [])
  const attention = item.user_action_required || item.needs_user_attention
  const status = normalizeStatus(item)
  const initialResult = status === "unknown" ? "" : STATUS_LABEL[status]
  const [correctedResult, setCorrectedResult] = useState(feedback?.corrected_result ?? initialResult)
  const displayStatus = statusFromResult(correctedResult) ?? status
  const confidencePct =
    typeof item.confidence === "number"
      ? Math.round(item.confidence <= 1 ? item.confidence * 100 : item.confidence)
      : null

  function addPair() {
    setPairs((p) => [...p, { page: "", text: "" }])
  }

  function updatePair(i: number, patch: Partial<EvidencePair>) {
    setPairs((p) => p.map((pair, idx) => (idx === i ? { ...pair, ...patch } : pair)))
  }

  function removePair(i: number) {
    setPairs((p) => p.filter((_, idx) => idx !== i))
  }

  function handleConfirm() {
    onConfirm({
      status: "submitted",
      comment: note.trim(),
      note: note.trim(),
      corrected_result: correctedResult,
      corrected_evidence_pairs: pairs.filter((p) => String(p.page ?? "").trim() || p.text.trim()),
      resolved: true,
    })
    setOpen(false)
  }

  return (
    <div
      onClick={onSelect}
      className={cn(
        "cursor-pointer rounded-lg border bg-card transition-colors",
        selected ? "border-primary ring-1 ring-primary/30" : "border-border hover:border-primary/40",
        attention && !confirmed && "border-l-4 border-l-status-attention",
        confirmed && "border-l-4 border-l-status-compliant",
      )}
    >
      <div className="flex items-start justify-between gap-3 p-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-muted-foreground">#{item.item_no}</span>
            <h3 className="text-sm font-semibold text-foreground">{item.law_name || "법제도명 없음"}</h3>
            <StatusBadge status={displayStatus} />
            {attention && !confirmed && <AttentionBadge />}
            {confirmed && (
              <span className="inline-flex items-center gap-1 text-xs font-medium text-status-compliant">
                <CheckCircle2 className="size-3.5" /> 확인 완료
              </span>
            )}
          </div>
          {item.reason && <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">{item.reason}</p>}
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            {confidencePct !== null && (
              <span>
                신뢰도{" "}
                <span className={cn("font-semibold", confidencePct < 70 ? "text-status-attention" : "text-foreground")}>
                  {confidencePct}%
                </span>
              </span>
            )}
            {!!(item.evidence_pairs?.length || item.evidence_pages?.length) && (
              <span>근거 {item.evidence_pairs?.length ?? item.evidence_pages?.length}건</span>
            )}
            {item.warnings && item.warnings.length > 0 && (
              <span className="text-status-attention">경고 {item.warnings.length}건</span>
            )}
          </div>
          {attention && item.attention_reasons && item.attention_reasons.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {item.attention_reasons.map((r) => (
                <span
                  key={r}
                  className="rounded border border-status-attention/30 bg-status-attention-bg px-1.5 py-0.5 text-xs text-status-attention"
                >
                  {attentionReasonText(r)}
                </span>
              ))}
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            setOpen((o) => !o)
          }}
          className="flex shrink-0 items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
          aria-expanded={open}
        >
          {confirmed ? <Pencil className="size-3.5" /> : "확인"}
          <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />
        </button>
      </div>

      {open && (
        <div className="border-t border-border p-4" onClick={(e) => e.stopPropagation()}>
          {item.recommendation && (
            <div className="mb-4 rounded-md bg-muted/50 p-3">
              <p className="text-xs font-medium text-muted-foreground">참고 권고(recommendation)</p>
              <p className="mt-1 text-sm text-foreground">{item.recommendation}</p>
            </div>
          )}

          <div>
            <Label className="text-sm font-medium">법령준수여부 수정</Label>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {RESULT_OPTIONS.map((option) => {
                const active = correctedResult === option.value
                return (
                  <button
                    key={option.value}
                    type="button"
                    aria-pressed={active}
                    onClick={() => setCorrectedResult(option.value)}
                    className={cn(
                      "h-9 rounded-md border px-2 text-sm font-medium transition-colors",
                      active ? option.className : "border-border bg-background text-muted-foreground hover:bg-muted",
                    )}
                  >
                    {option.value}
                  </button>
                )
              })}
            </div>
          </div>

          <Label className="mt-4 block text-sm font-medium">수정 의견</Label>
          <p className="mt-0.5 text-xs text-muted-foreground">
            페이지나 근거가 잘못되었다고 판단하면 의견을 남기고 아래에 수정 근거를 추가하세요.
          </p>
          <Textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="예: 근거 페이지가 p.14가 아니라 p.16으로 보입니다."
            className="mt-2 min-h-20"
          />

          <div className="mt-4 flex items-center justify-between">
            <Label className="text-sm font-medium">근거 수정(corrected_evidence_pairs)</Label>
            <Button type="button" variant="outline" size="sm" onClick={addPair} className="gap-1">
              <Plus className="size-3.5" /> 근거 추가
            </Button>
          </div>
          {pairs.length > 0 && (
            <div className="mt-2 space-y-2">
              {pairs.map((pair, i) => (
                <div key={i} className="flex items-start gap-2">
                  <Input
                    value={String(pair.page ?? "")}
                    onChange={(e) => updatePair(i, { page: e.target.value })}
                    placeholder="페이지"
                    className="w-24"
                  />
                  <Textarea
                    value={pair.text}
                    onChange={(e) => updatePair(i, { text: e.target.value })}
                    placeholder="근거 문장"
                    className="min-h-10 flex-1"
                  />
                  <button
                    type="button"
                    onClick={() => removePair(i)}
                    className="mt-2 text-muted-foreground hover:text-destructive"
                    aria-label="근거 삭제"
                  >
                    <Trash2 className="size-4" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="mt-4 flex justify-end gap-2">
            {confirmed && (
              <Button type="button" variant="ghost" size="sm" onClick={onUnconfirm}>
                확인 취소
              </Button>
            )}
            <Button type="button" size="sm" onClick={handleConfirm} className="gap-1.5">
              <CheckCircle2 className="size-4" /> 항목 확인 완료
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

function statusFromResult(result: string): StatusKey | null {
  if (result === "준수") return "compliant"
  if (result === "미준수") return "noncompliant"
  if (result === "보완필요") return "revision"
  if (result === "해당없음") return "na"
  return null
}
