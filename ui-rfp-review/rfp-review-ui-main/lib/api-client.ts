import { BACKEND_API_URL } from "@/lib/backend"
import type { ReviewItem, ReviewResponse, SearchHit, SearchResponse, UserFeedback } from "@/lib/types"

async function parseJsonResponse<T>(res: Response, fallbackMessage: string): Promise<T> {
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data?.detail || data?.error || `${fallbackMessage} (${res.status})`)
  }
  return data as T
}

function parseNetworkError(err: unknown, fallbackMessage: string): Error {
  if (err instanceof TypeError) {
    return new Error(`${fallbackMessage} 브라우저가 백엔드에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.`)
  }
  return err instanceof Error ? err : new Error(fallbackMessage)
}

export async function parsePdf(file: File): Promise<ReviewResponse> {
  const form = new FormData()
  form.append("file", file)

  try {
    const res = await fetch(`${BACKEND_API_URL}/api/parse`, {
      method: "POST",
      body: form,
    })
    return parseJsonResponse<ReviewResponse>(res, "PDF 파싱 요청에 실패했습니다.")
  } catch (err) {
    throw parseNetworkError(err, "PDF 파싱 요청에 실패했습니다.")
  }
}

export async function checkReview(documentId: string, items: string): Promise<ReviewResponse> {
  const body = JSON.stringify({
    document_id: Number(documentId),
    items: items.trim() || null,
  })

  try {
    const res = await fetch(`${BACKEND_API_URL}/api/review/check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    })
    return parseJsonResponse<ReviewResponse>(res, "검토 요청에 실패했습니다.")
  } catch (err) {
    try {
      const fallback = await fetch("/api/review/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      })
      return parseJsonResponse<ReviewResponse>(fallback, "검토 요청에 실패했습니다.")
    } catch (fallbackErr) {
      throw parseNetworkError(fallbackErr || err, "검토 요청에 실패했습니다.")
    }
  }
}

export async function generateRecommendations(
  documentId: string,
  results: ReviewItem[],
  feedback: Record<string, UserFeedback>,
): Promise<ReviewResponse> {
  const payloadResults = results.map((item) => ({
    item_no: String(item.item_no),
    review_result: item.review_result || "",
    normalized_result: item.normalized_result || "",
    final_status: item.final_status || "",
    is_target: item.is_target ?? null,
    confidence: item.confidence || 0,
    reason: item.reason || "",
    recommendation: item.recommendation || "",
    evidence_pages: item.evidence_pages || [],
    evidence_text: item.evidence_text || [],
    user_feedback: feedback[String(item.item_no)] || item.user_feedback || null,
    detailed_assessment: item.detailed_assessment ?? null,
  }))

  const res = await fetch("/api/recommendations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      document_id: Number(documentId),
      results: payloadResults,
    }),
  })
  return parseJsonResponse<ReviewResponse>(res, "권고 문장 생성 요청에 실패했습니다.")
}

export async function submitReview(file: File, items: string): Promise<ReviewResponse> {
  const parsed = await parsePdf(file)
  return checkReview(String(parsed.document_id), items)
}

export async function searchDocument(documentId: string, q: string): Promise<SearchHit[]> {
  const res = await fetch(`/api/documents/${encodeURIComponent(documentId)}/search?q=${encodeURIComponent(q)}`)
  const data = await parseJsonResponse<SearchResponse>(res, "검색 요청에 실패했습니다.")
  return data.results || data.hits || data.matches || []
}
