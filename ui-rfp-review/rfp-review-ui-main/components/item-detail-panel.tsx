"use client"

import { useState } from "react"
import { CheckCircle2, ChevronLeft, ChevronRight, FileSearch, Loader2, Search, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import { StatusBadge, AttentionBadge } from "@/components/status-badge"
import { searchDocument } from "@/lib/api-client"
import { normalizeStatus, type ReviewItem, type SearchHit, type StatusKey } from "@/lib/types"
import { cn } from "@/lib/utils"
import { toast } from "sonner"

export function ItemDetailPanel({
  item,
  documentId,
  confirmed,
  correctedResult,
  position,
  total,
  onPrevious,
  onNext,
  onClose,
}: {
  item: ReviewItem | null
  documentId: string
  confirmed: boolean
  correctedResult?: string
  position: number
  total: number
  onPrevious: () => void
  onNext: () => void
  onClose: () => void
}) {
  const [query, setQuery] = useState("")
  const [hits, setHits] = useState<SearchHit[] | null>(null)
  const [searching, setSearching] = useState(false)

  async function runSearch(e: React.FormEvent) {
    e.preventDefault()
    if (!query.trim()) return
    setSearching(true)
    try {
      const res = await searchDocument(documentId, query)
      setHits(res)
      if (res.length === 0) toast.info("검색 결과가 없습니다.")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "검색에 실패했습니다.")
    } finally {
      setSearching(false)
    }
  }

  const confidencePct =
    item && typeof item.confidence === "number"
      ? Math.round(item.confidence <= 1 ? item.confidence * 100 : item.confidence)
      : null
  const displayResult = correctedResult || item?.normalized_result || item?.review_result || "-"
  const displayStatus = statusFromResult(correctedResult || "") ?? (item ? normalizeStatus(item) : "unknown")

  return (
    <aside className="flex w-[22rem] shrink-0 flex-col border-l border-border bg-card">
      <div className="border-b border-border px-5 py-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-foreground">항목 상세</h3>
            {total > 0 && (
              <p className="mt-0.5 text-xs text-muted-foreground">
                {position} / {total}
              </p>
            )}
          </div>
          <div className="flex items-center gap-1">
            <Button type="button" variant="ghost" size="icon" onClick={onPrevious} disabled={position <= 1} aria-label="이전 항목">
              <ChevronLeft className="size-4" />
            </Button>
            <Button type="button" variant="ghost" size="icon" onClick={onNext} disabled={position >= total} aria-label="다음 항목">
              <ChevronRight className="size-4" />
            </Button>
            <Button type="button" variant="ghost" size="icon" onClick={onClose} aria-label="항목 상세 닫기">
              <X className="size-4" />
            </Button>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {!item ? (
          <div className="flex h-40 items-center justify-center px-6 text-center text-sm text-muted-foreground">
            좌측에서 항목을 선택하면 상세 정보가 표시됩니다.
          </div>
        ) : (
          <div className="px-5 py-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-muted-foreground">#{item.item_no}</span>
              <StatusBadge status={displayStatus} />
              {(item.user_action_required || item.needs_user_attention) && !confirmed && <AttentionBadge />}
              {confirmed && (
                <span className="inline-flex items-center gap-1 text-xs font-medium text-status-compliant">
                  <CheckCircle2 className="size-3.5" /> 확인됨
                </span>
              )}
            </div>
            <h4 className="mt-2 text-sm font-semibold text-foreground">{item.law_name || "법제도명 없음"}</h4>

            <DetailRow label="판단결과">{displayResult}</DetailRow>
            {confidencePct !== null && (
              <DetailRow label="신뢰도">
                <span className={cn(confidencePct < 70 && "text-status-attention font-semibold")}>
                  {confidencePct}%
                </span>
              </DetailRow>
            )}
            {item.reason && <DetailRow label="사유">{item.reason}</DetailRow>}
            {item.target_text && <DetailRow label="대상">{item.target_text}</DetailRow>}
            {item.requirement_texts && item.requirement_texts.length > 0 && (
              <div className="mt-4">
                <p className="text-xs font-medium text-muted-foreground">준수 항목</p>
                <ul className="mt-2 space-y-2">
                  {item.requirement_texts.map((requirement, i) => (
                    <li key={i} className="rounded-md border border-border bg-muted/40 p-2 text-sm leading-relaxed text-foreground">
                      {requirement}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {item.recommendation && <DetailRow label="참고 권고">{item.recommendation}</DetailRow>}
            {item.compliance_content && <DetailRow label="권고내용">{item.compliance_content}</DetailRow>}

            {(item.evidence_pairs?.length ?? 0) > 0 ? (
              <div className="mt-4">
                <p className="text-xs font-medium text-muted-foreground">근거</p>
                <ul className="mt-2 space-y-2">
                  {item.evidence_pairs!.map((p, i) => (
                    <li key={i} className="rounded-md border border-border bg-muted/40 p-2 text-sm">
                      <span className="font-semibold text-primary">p.{p.page ?? "-"}</span>
                      <span className="text-foreground">: {p.text}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : item.evidence_text ? (
              <DetailRow label="근거">
                {item.evidence_pages && item.evidence_pages.length > 0 && (
                  <span className="mr-1 font-semibold text-primary">p.{item.evidence_pages.join(", ")}</span>
                )}
                {Array.isArray(item.evidence_text) ? item.evidence_text.join("\n") : item.evidence_text}
              </DetailRow>
            ) : null}

            {item.warnings && item.warnings.length > 0 && (
              <div className="mt-4">
                <p className="text-xs font-medium text-status-attention">검토 경고</p>
                <ul className="mt-1 list-disc space-y-1 pl-4 text-sm text-foreground">
                  {item.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            )}

            {item.verification != null && (
              <DetailRow label="검증">
                <pre className="whitespace-pre-wrap break-words font-mono text-xs text-muted-foreground">
                  {typeof item.verification === "string"
                    ? item.verification
                    : JSON.stringify(item.verification, null, 2)}
                </pre>
              </DetailRow>
            )}
          </div>
        )}

        <Separator />

        <div className="px-5 py-4">
          <div className="flex items-center gap-1.5">
            <FileSearch className="size-4 text-primary" />
            <p className="text-sm font-semibold text-foreground">RFP 본문 검색</p>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            모델 판단의 근거가 실제 RFP 문서에 있는지 확인하세요.
          </p>
          <form onSubmit={runSearch} className="mt-3 flex gap-2">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="RFP 본문에서 근거 문장 검색"
              className="flex-1"
            />
            <Button type="submit" size="icon" disabled={searching || !query.trim()}>
              {searching ? <Loader2 className="size-4 animate-spin" /> : <Search className="size-4" />}
              <span className="sr-only">검색</span>
            </Button>
          </form>

          {hits !== null && (
            <div className="mt-3 space-y-2">
              {hits.length === 0 ? (
                <p className="text-sm text-muted-foreground">검색 결과가 없습니다.</p>
              ) : (
                hits.map((hit, i) => (
                  <div key={i} className="rounded-md border border-border bg-muted/40 p-2 text-sm">
                    <span className="font-semibold text-primary">p.{hit.page}</span>
                    {hit.pdf_page != null && String(hit.pdf_page) !== String(hit.page) && (
                      <span className="ml-1 text-xs text-muted-foreground">(PDF {hit.pdf_page})</span>
                    )}
                    <span className="text-foreground">: <HighlightedText text={hit.text} query={query} /></span>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      </div>
    </aside>
  )
}

function statusFromResult(result: string): StatusKey | null {
  if (result === "준수") return "compliant"
  if (result === "미준수") return "noncompliant"
  if (result === "보완필요") return "revision"
  if (result === "해당없음") return "na"
  return null
}

function HighlightedText({ text, query }: { text: string; query: string }) {
  const needle = query.trim()
  if (!needle) return <>{text}</>
  const lowerText = text.toLowerCase()
  const lowerNeedle = needle.toLowerCase()
  const parts: React.ReactNode[] = []
  let cursor = 0
  let index = lowerText.indexOf(lowerNeedle)

  while (index >= 0) {
    if (index > cursor) parts.push(text.slice(cursor, index))
    parts.push(
      <mark key={`${index}-${needle}`} className="rounded-sm bg-status-attention-bg px-0.5 font-semibold text-foreground">
        {text.slice(index, index + needle.length)}
      </mark>,
    )
    cursor = index + needle.length
    index = lowerText.indexOf(lowerNeedle, cursor)
  }

  if (cursor < text.length) parts.push(text.slice(cursor))
  return <>{parts}</>
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mt-4">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <div className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-foreground">{children}</div>
    </div>
  )
}
