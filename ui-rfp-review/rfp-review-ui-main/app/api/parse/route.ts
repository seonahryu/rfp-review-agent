import { NextResponse } from "next/server"
import { BACKEND_API_URL } from "@/lib/backend"

export const runtime = "nodejs"
export const maxDuration = 300

export async function POST(request: Request) {
  try {
    const incoming = await request.formData()
    const file = incoming.get("file")
    if (!file || typeof file === "string") {
      return NextResponse.json({ error: "PDF 파일이 필요합니다." }, { status: 400 })
    }

    const forward = new FormData()
    forward.append("file", file, (file as File).name || "rfp.pdf")

    const res = await fetch(`${BACKEND_API_URL}/api/parse`, {
      method: "POST",
      body: forward,
    })
    const text = await res.text()

    if (!res.ok) {
      return NextResponse.json(
        { error: `PDF 파싱 요청이 실패했습니다. (${res.status})`, detail: text.slice(0, 2000) },
        { status: res.status },
      )
    }

    try {
      return NextResponse.json(JSON.parse(text))
    } catch {
      return NextResponse.json(
        { error: "PDF 파싱 응답을 해석할 수 없습니다.", detail: text.slice(0, 2000) },
        { status: 502 },
      )
    }
  } catch (err) {
    return NextResponse.json(
      { error: "PDF 파싱 중 오류가 발생했습니다.", detail: err instanceof Error ? err.message : String(err) },
      { status: 500 },
    )
  }
}
