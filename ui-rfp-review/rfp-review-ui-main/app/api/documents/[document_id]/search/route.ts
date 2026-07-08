import { NextResponse } from "next/server"
import { BACKEND_API_URL } from "@/lib/backend"

export const runtime = "nodejs"

export async function GET(
  request: Request,
  { params }: { params: Promise<{ document_id: string }> },
) {
  const { document_id } = await params
  const { searchParams } = new URL(request.url)
  const q = searchParams.get("q") ?? ""

  if (!q.trim()) {
    return NextResponse.json({ results: [] })
  }

  try {
    const url = `${BACKEND_API_URL}/api/documents/${encodeURIComponent(
      document_id,
    )}/search?q=${encodeURIComponent(q)}`
    const res = await fetch(url)
    const text = await res.text()

    if (!res.ok) {
      return NextResponse.json(
        { error: `검색 요청이 실패했습니다. (${res.status})`, detail: text.slice(0, 1000) },
        { status: res.status },
      )
    }

    try {
      return NextResponse.json(JSON.parse(text))
    } catch {
      return NextResponse.json({ error: "검색 응답을 해석할 수 없습니다." }, { status: 502 })
    }
  } catch (err) {
    return NextResponse.json(
      { error: "검색 중 오류가 발생했습니다.", detail: err instanceof Error ? err.message : String(err) },
      { status: 500 },
    )
  }
}
