export type EvidencePair = {
  page: number | string | null
  text: string
}

export type CopyTexts = {
  review_result?: string
  compliance_content?: string
  [key: string]: string | undefined
}

export type ReviewItem = {
  item_no: number | string
  law_name?: string | null
  target_text?: string
  requirement_texts?: string[]
  review_result?: string
  normalized_result?: string
  final_status?: string
  is_target?: boolean | null
  confidence?: number
  reason?: string
  recommendation?: string
  evidence_pages?: (number | string)[]
  evidence_text?: string[] | string
  evidence_pairs?: EvidencePair[]
  warnings?: string[]
  verification?: unknown
  compliance_content?: string
  needs_user_attention?: boolean
  user_action_required?: boolean
  attention_reasons?: string[]
  user_feedback?: UserFeedback | null
  copy_texts?: CopyTexts
}

export type UserFeedback = {
  status?: string
  comment?: string
  note?: string
  corrected_result?: string
  corrected_evidence_pairs?: EvidencePair[]
  resolved?: boolean
}

export type WorkflowGates = {
  can_generate_recommendations?: boolean
  user_action_required_count?: number
  recommendation_generation_mode?: string
  next_endpoint?: string
  [key: string]: boolean | number | string | string[] | undefined
}

export type ReviewOpinion = {
  total_count?: number
  non_compliant_count?: number
  needs_revision_count?: number
  copy_text?: string
}

export type ReviewResponse = {
  document_id: string | number
  document_name?: string
  total_pages?: number
  parse_status?: string
  audit_score?: number
  audit_warnings?: unknown[]
  parse_needs_user_confirmation?: boolean
  workflow_gates?: WorkflowGates
  review_result_column_text?: string
  review_opinion?: ReviewOpinion
  all_items_complete?: boolean
  results: ReviewItem[]
}

export type SearchHit = {
  page: number | string
  pdf_page?: number | string
  text: string
  score?: number
}

export type SearchResponse = {
  results?: SearchHit[]
  hits?: SearchHit[]
  matches?: SearchHit[]
}

export type StatusKey = "compliant" | "noncompliant" | "revision" | "na" | "unknown"

export function normalizeStatus(item: ReviewItem): StatusKey {
  const raw = (item.normalized_result || item.final_status || item.review_result || "")
    .toString()
    .trim()
  if (!raw) return "unknown"
  if (item.is_target === false) return "na"
  if (/미준수|위반|non[-_ ]?compliant|noncompliant/i.test(raw)) return "noncompliant"
  if (/보완|수정|revision|needs?[-_ ]?revision/i.test(raw)) return "revision"
  if (/해당\s?없음|해당없음|not[-_ ]?applicable|n\/?a/i.test(raw)) return "na"
  if (/준수|적합|compliant|pass/i.test(raw)) return "compliant"
  return "unknown"
}

export const STATUS_LABEL: Record<StatusKey, string> = {
  compliant: "준수",
  noncompliant: "미준수",
  revision: "보완필요",
  na: "해당없음",
  unknown: "판단대기",
}

export const ATTENTION_REASON_LABEL: Record<string, string> = {
  confidence_low: "신뢰도 낮음",
  evidence_missing: "근거 부족",
  review_warnings: "검토 경고 있음",
  verification_requires_adjudication: "검증 단계에서 추가 판단 필요",
}

export function attentionReasonText(reason: string): string {
  return ATTENTION_REASON_LABEL[reason] ?? reason
}
