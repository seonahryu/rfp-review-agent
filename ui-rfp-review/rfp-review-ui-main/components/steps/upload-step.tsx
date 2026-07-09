"use client"

import { useRef, useState } from "react"
import { FileText, Loader2, UploadCloud, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { StepHeader } from "@/components/step-header"
import { parsePdf, checkReview } from "@/lib/api-client"
import type { ReviewResponse } from "@/lib/types"
import { cn } from "@/lib/utils"

const ITEMS_HELP =
  "입력하지 않으면 전체 18개 항목을 검토합니다. 일부 법제도 항목만 테스트하려면 해당 법제도 항목 번호를 1,2,3처럼 입력하세요."

export function UploadStep({ onComplete }: { onComplete: (r: ReviewResponse) => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [items, setItems] = useState("")
  const [dragging, setDragging] = useState(false)
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState("")
  const inputRef = useRef<HTMLInputElement>(null)

  function pickFile(f: File | null | undefined) {
    if (!f) return
    if (f.type !== "application/pdf" && !f.name.toLowerCase().endsWith(".pdf")) {
      toast.error("PDF 파일만 업로드할 수 있습니다.")
      return
    }
    setFile(f)
  }

  async function handleSubmit() {
    if (!file) {
      toast.error("먼저 PDF 파일을 업로드해 주세요.")
      return
    }
    setLoading(true)
    try {
      setStatus("PDF를 파싱하고 있습니다.")
      const parsed = await parsePdf(file)
      setStatus("법제도 검토와 검증을 진행하고 있습니다.")
      const reviewed = await checkReview(String(parsed.document_id), items)
      toast.success("검토 요청이 완료되었습니다.")
      onComplete({
        ...reviewed,
        parse_status: reviewed.parse_status || parsed.parse_status,
        audit_score: reviewed.audit_score ?? parsed.audit_score,
        audit_warnings: reviewed.audit_warnings || parsed.audit_warnings,
        parse_needs_user_confirmation:
          reviewed.parse_needs_user_confirmation ?? parsed.parse_needs_user_confirmation,
      })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "검토 요청에 실패했습니다.")
    } finally {
      setLoading(false)
      setStatus("")
    }
  }

  return (
    <div>
      <StepHeader step={1} title="업로드" description="RFP PDF를 업로드하고 검토를 시작합니다." />
      <div className="mx-auto max-w-2xl px-8 py-8">
        <div className="rounded-lg border border-border bg-card p-6">
          <Label className="text-sm font-medium">RFP PDF 파일</Label>
          <div
            role="button"
            tabIndex={0}
            aria-disabled={loading}
            onClick={() => !loading && inputRef.current?.click()}
            onKeyDown={(e) => {
              if ((e.key === "Enter" || e.key === " ") && !loading) inputRef.current?.click()
            }}
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              if (!loading) pickFile(e.dataTransfer.files?.[0])
            }}
            className={cn(
              "mt-2 flex cursor-pointer flex-col items-center justify-center gap-2 rounded-md border-2 border-dashed px-6 py-10 text-center transition-colors",
              dragging ? "border-primary bg-accent" : "border-border hover:border-primary/50 hover:bg-muted/50",
              loading && "pointer-events-none opacity-60",
            )}
          >
            <UploadCloud className="size-8 text-muted-foreground" />
            <p className="text-sm font-medium text-foreground">
              PDF 파일을 여기에 끌어오거나 클릭하여 선택
            </p>
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
                onClick={() => setFile(null)}
                disabled={loading}
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
              disabled={loading}
              className="mt-2"
            />
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{ITEMS_HELP}</p>
          </div>

          <Button onClick={handleSubmit} disabled={loading || !file} className="mt-6 w-full">
            {loading ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                검토 진행 중...
              </>
            ) : (
              "검토 시작"
            )}
          </Button>
          {loading && (
            <p className="mt-2 text-center text-xs text-muted-foreground">
              {status || "문서 분량에 따라 시간이 걸릴 수 있습니다. 페이지를 닫지 마세요."}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
