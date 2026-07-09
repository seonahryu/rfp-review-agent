export const STEP_KEYS = [
  "upload",
  "parse",
  "progress",
  "results",
  "recommendation",
  "final",
] as const

export type StepKey = (typeof STEP_KEYS)[number]

export const STEPS: { key: StepKey; index: number; title: string; desc: string }[] = [
  { key: "upload", index: 1, title: "업로드", desc: "RFP PDF 업로드 및 검토 시작" },
  { key: "parse", index: 2, title: "PDF 파싱 검증", desc: "파싱 상태와 신뢰도 확인" },
  { key: "progress", index: 3, title: "검토 진행", desc: "항목별 검토 진행 상태" },
  { key: "results", index: 4, title: "검토결과 확인", desc: "항목별 결과와 근거 컨펌" },
  { key: "recommendation", index: 5, title: "권고 문장 생성", desc: "권고내용 생성 및 최종 컨펌" },
  { key: "final", index: 6, title: "최종 결과", desc: "HWP 표 구성 및 복사" },
]

export function stepIndexOf(key: StepKey): number {
  return STEP_KEYS.indexOf(key)
}
