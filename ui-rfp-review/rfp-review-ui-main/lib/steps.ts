export const STEP_KEYS = [
  "upload",
  "results",
  "recommendation",
  "final",
] as const

export type StepKey = (typeof STEP_KEYS)[number]

export const STEPS: { key: StepKey; index: number; title: string; desc: string }[] = [
  { key: "upload", index: 1, title: "업로드", desc: "RFP PDF 업로드 및 검토 시작" },
  { key: "results", index: 2, title: "검토결과 확인", desc: "항목별 결과와 근거 확인" },
  { key: "recommendation", index: 3, title: "권고 문장 생성", desc: "권고내용 확인" },
  { key: "final", index: 4, title: "최종 결과", desc: "HWP 표 구성 및 복사" },
]

export function stepIndexOf(key: StepKey): number {
  return STEP_KEYS.indexOf(key)
}
