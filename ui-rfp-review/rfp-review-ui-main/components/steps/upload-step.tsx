"use client"

import { useRef, useState } from "react"
import { AlertTriangle, FileText, Loader2, UploadCloud, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { StepHeader } from "@/components/step-header"
import { checkReview, parsePdfInBrowserChunks, retryFailedPdfPages } from "@/lib/api-client"
import type { ReviewResponse } from "@/lib/types"
import { cn } from "@/lib/utils"

const ITEMS_HELP =
  "입력하지 않으면 전체 18개 항목을 검토합니다. 일부 항목만 테스트하려면 1,2,3처럼 번호를 입력하세요."

export function UploadStep({ onComplete }: { onComplete: (r: ReviewResponse) => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [items, setItems] = useState("")
  const [dragging, setDragging] = useState(false)
  const [loading, setLoading] = useState(false)
  const [reviewing, setReviewing] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [status, setStatus] = useState("")
  const [pageCount, setPageCount] = useState(0)
  const [parsedPages, setParsedPages] = useState(0)
  const [failedPages, setFailedPages] = useState<number[]>([])
  const [selectedFailedPages, setSelectedFailedPages] = useState<number[]>([])
  const [pendingParsed, setPendingParsed] = useState<ReviewResponse | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  function resetParseState() {
    setPageCount(0)
    setParsedPages(0)
    setFailedPages([])
    setSelectedFailedPages([])
    setPendingParsed(null)
  }

  function pickFile(f: File | null | undefined) {
    if (!f) return
    if (f.type !== "application/pdf" && !f.name.toLowerCase().endsWith(".pdf")) {
      toast.error("PDF 파일만 업로드할 수 있습니다.")
      return
    }
    setFile(f)
    resetParseState()
  }

  async function runReview(parsed: ReviewResponse) {
    setReviewing(true)
    try {
      setStatus("파싱 결과를 기준으로 법제도 검토를 진행하고 있습니다.")
      const reviewed = await checkReview(String(parsed.document_id), items)
      toast.success("검토가 완료되었습니다.")
      onComplete({
        ...reviewed,
        parse_status: reviewed.parse_status || parsed.parse_status,
        audit_score: reviewed.audit_score ?? parsed.audit_score,
        audit_warnings: reviewed.audit_warnings || parsed.audit_warnings,
        parse_needs_user_confirmation:
          reviewed.parse_needs_user_confirmation ?? parsed.parse_needs_user_confirmation,
        chunk_parse_summary: parsed.chunk_parse_summary,
      })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "검토 요청에 실패했습니다.")
    } finally {
      setReviewing(false)
      setStatus("")
    }
  }

  async function handleSubmit() {
    if (!file) {
      toast.error("먼저 PDF 파일을 업로드해 주세요.")
      return
    }
    setLoading(true)
    resetParseState()
    try {
      setStatus("PDF를 1쪽씩 나누어 병렬 파싱하고 있습니다.")
      const parsed = await parsePdfInBrowserChunks(file, (progress) => {
        setPageCount(progress.total)
        setParsedPages(progress.completed)
        setFailedPages(progress.failedPages || [])
        if (progress.failedPage) {
          setStatus(`${progress.failedPage}쪽 파싱 실패 (${progress.completed}/${progress.total}페이지 처리)`)
        } else if (progress.startedPage) {
          setStatus(`${progress.startedPage}쪽 파싱 시작 (${progress.completed}/${progress.total}페이지 완료)`)
        } else if (progress.currentPage) {
          setStatus(`${progress.currentPage}쪽 처리 완료 (${progress.completed}/${progress.total}페이지 완료)`)
        }
      })

      const summary = parsed.chunk_parse_summary
      if (summary?.failed_pages?.length) {
        setPendingParsed(parsed)
        setFailedPages(summary.failed_pages)
        setSelectedFailedPages(summary.failed_pages)
        setStatus("")
        toast.warning("일부 페이지 파싱에 실패했습니다. 실패 페이지를 확인한 뒤 계속 진행해 주세요.")
        return
      }

      await runReview(parsed)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "검토 요청에 실패했습니다.")
    } finally {
      setLoading(false)
    }
  }

  function toggleFailedPageSelection(pageNo: number) {
    setSelectedFailedPages((current) =>
      current.includes(pageNo)
        ? current.filter((page) => page !== pageNo)
        : [...current, pageNo].sort((a, b) => a - b),
    )
  }

  async function handleRetryFailedPages() {
    if (!file || !pendingParsed || failedPages.length === 0) return
    if (selectedFailedPages.length === 0) {
      toast.error("재파싱할 실패 페이지를 1개 이상 선택해 주세요.")
      return
    }
    setRetrying(true)
    setParsedPages(0)
    try {
      const pagesToRetry = [...selectedFailedPages]
      setStatus(`선택한 ${pagesToRetry.length}페이지를 다시 파싱하고 있습니다.`)
      const reparsed = await retryFailedPdfPages(file, pendingParsed.document_id, pagesToRetry, (progress) => {
        setParsedPages(progress.completed)
        if (progress.failedPage) {
          setStatus(`${progress.failedPage}쪽 재파싱 실패 (${progress.completed}/${progress.total}페이지 처리)`)
        } else if (progress.startedPage) {
          setStatus(`${progress.startedPage}쪽 재파싱 시작 (${progress.completed}/${progress.total}페이지 완료)`)
        } else if (progress.currentPage) {
          setStatus(`${progress.currentPage}쪽 재파싱 완료 (${progress.completed}/${progress.total}페이지 완료)`)
        }
      })

      const retryStillFailed = reparsed.chunk_parse_summary?.failed_pages || []
      const unselectedFailed = failedPages.filter((page) => !pagesToRetry.includes(page))
      const remainingFailed = [...new Set([...unselectedFailed, ...retryStillFailed])].sort((a, b) => a - b)
      const totalPages = reparsed.chunk_parse_summary?.total_pages || pageCount
      setPendingParsed({
        ...reparsed,
        chunk_parse_summary: {
          total_pages: totalPages,
          successful_pages: totalPages - remainingFailed.length,
          failed_pages: remainingFailed,
        },
        parse_status: remainingFailed.length > 0 ? "warning" : reparsed.parse_status,
        parse_needs_user_confirmation:
          remainingFailed.length > 0 ? true : reparsed.parse_needs_user_confirmation,
      })
      setFailedPages(remainingFailed)
      setSelectedFailedPages(remainingFailed)
      setPageCount(totalPages)
      if (remainingFailed.length === 0) {
        toast.success("실패 페이지 재파싱이 완료되었습니다.")
      } else {
        toast.warning("일부 페이지는 다시 파싱해도 실패했습니다. 원문 확인 후 계속할 수 있습니다.")
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "실패 페이지 재파싱에 실패했습니다.")
    } finally {
      setRetrying(false)
      setParsedPages(0)
      setStatus("")
    }
  }

  const progressPercent = pageCount > 0 ? Math.round((parsedPages / pageCount) * 100) : 0
  const busy = loading || reviewing || retrying
  const failedPageLabel = failedPages.map((page) => `p.${page}`).join(", ")
  const successfulPages = pageCount > 0 ? pageCount - failedPages.length : parsedPages
  const allFailedPagesSelected =
    failedPages.length > 0 && failedPages.every((page) => selectedFailedPages.includes(page))

  return (
    <div>
      <StepHeader step={1} title="업로드" description="RFP PDF를 업로드하면 바로 법제도 검토를 진행합니다." />
      <div className="mx-auto max-w-2xl px-8 py-8">
        <div className="rounded-lg border border-border bg-card p-6">
          <Label className="text-sm font-medium">RFP PDF 파일</Label>
          <div
            role="button"
            tabIndex={0}
            aria-disabled={busy}
            onClick={() => !busy && inputRef.current?.click()}
            onKeyDown={(e) => {
              if ((e.key === "Enter" || e.key === " ") && !busy) inputRef.current?.click()
            }}
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              if (!busy) pickFile(e.dataTransfer.files?.[0])
            }}
            className={cn(
              "mt-2 flex cursor-pointer flex-col items-center justify-center gap-2 rounded-md border-2 border-dashed px-6 py-10 text-center transition-colors",
              dragging ? "border-primary bg-accent" : "border-border hover:border-primary/50 hover:bg-muted/50",
              busy && "pointer-events-none opacity-60",
            )}
          >
            <UploadCloud className="size-8 text-muted-foreground" />
            <p className="text-sm font-medium text-foreground">PDF 파일을 끌어오거나 클릭하여 선택</p>
            <p className="text-xs text-muted-foreground">RFP PDF 파일 1개를 업로드합니다.</p>
            <input
              ref={inputRef}
              type="file"
              accept="application/pdf,.pdf"
              className="hidden"
              onChange={(e) => pickFile(e.target.files?.[0])}
            />
          </div>

          {file && (
            <div className="mt-3 flex items-center justify-between gap-3 rounded-md border border-border bg-muted/40 px-3 py-2">
              <div className="flex min-w-0 items-center gap-2">
                <FileText className="size-4 shrink-0 text-primary" />
                <span className="truncate text-sm text-foreground">{file.name}</span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {(file.size / 1024 / 1024).toFixed(2)} MB
                </span>
              </div>
              <button
                type="button"
                onClick={() => {
                  setFile(null)
                  resetParseState()
                }}
                disabled={busy}
                className="text-muted-foreground hover:text-foreground"
                aria-label="파일 제거"
              >
                <X className="size-4" />
              </button>
            </div>
          )}

          <div className="mt-6">
            <Label htmlFor="items" className="text-sm font-medium">
              검토할 항목 번호
            </Label>
            <Input
              id="items"
              value={items}
              onChange={(e) => setItems(e.target.value)}
              placeholder="예: 1,2,3"
              inputMode="numeric"
              disabled={busy}
              className="mt-2"
            />
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{ITEMS_HELP}</p>
          </div>

          <Button onClick={handleSubmit} disabled={busy || !file} className="mt-6 w-full">
            {busy ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                {reviewing ? "검토 진행 중..." : retrying ? "재파싱 진행 중..." : "파싱 진행 중..."}
              </>
            ) : (
              "검토 시작"
            )}
          </Button>

          {pendingParsed && failedPages.length > 0 && (
            <div className="mt-4 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950">
              <div className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                <div className="min-w-0">
                  <p className="font-semibold">
                    총 {pageCount}페이지 중 {successfulPages}페이지 파싱 성공, {failedPages.length}페이지 파싱 실패
                    {failedPageLabel ? `: ${failedPageLabel}` : ""}
                  </p>
                  <p className="mt-1 text-xs leading-relaxed">
                    실패 페이지는 검토 근거에서 제외될 수 있으므로 원문 확인이 필요합니다.
                  </p>
                </div>
              </div>

              <div className="mt-3 rounded-md border border-amber-200 bg-white/60 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs font-semibold">재파싱할 페이지 선택</p>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setSelectedFailedPages(allFailedPagesSelected ? [] : [...failedPages])}
                    disabled={retrying}
                  >
                    {allFailedPagesSelected ? "전체 해제" : "전체 선택"}
                  </Button>
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {failedPages.map((page) => (
                    <label
                      key={page}
                      className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-amber-300 bg-white px-2 py-1 text-xs font-medium"
                    >
                      <input
                        type="checkbox"
                        checked={selectedFailedPages.includes(page)}
                        onChange={() => toggleFailedPageSelection(page)}
                        disabled={retrying}
                        className="size-3.5"
                      />
                      p.{page}
                    </label>
                  ))}
                </div>
                <p className="mt-2 text-xs">선택한 페이지 {selectedFailedPages.length}개만 다시 파싱합니다.</p>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleRetryFailedPages}
                  disabled={retrying || selectedFailedPages.length === 0}
                >
                  {retrying ? "선택한 페이지 다시 파싱 중..." : "선택한 페이지 다시 파싱"}
                </Button>
                <Button type="button" size="sm" onClick={() => runReview(pendingParsed)}>
                  실패 페이지 제외하고 계속
                </Button>
              </div>
            </div>
          )}

          {pendingParsed && failedPages.length === 0 && !loading && (
            <div className="mt-4 rounded-md border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm text-emerald-950">
              <p className="font-semibold">총 {pageCount}페이지 파싱이 완료되었습니다.</p>
              <p className="mt-1 text-xs leading-relaxed">
                실패했던 페이지가 모두 재파싱되어 기존 파싱 결과에 반영되었습니다.
              </p>
              <Button type="button" size="sm" className="mt-3" onClick={() => runReview(pendingParsed)}>
                검토 계속
              </Button>
            </div>
          )}

          {(loading || reviewing || retrying) && (
            <div className="mt-3">
              {pageCount > 0 && (
                <div className="mb-2 h-2 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-primary transition-all"
                    style={{ width: `${progressPercent}%` }}
                  />
                </div>
              )}
              <p className="text-center text-xs text-muted-foreground">
                {status || "문서 분량에 따라 시간이 걸릴 수 있습니다. 페이지를 닫지 마세요."}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
