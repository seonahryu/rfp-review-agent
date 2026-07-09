import type { DetailedAssessment, InternalAssessmentOverrides, ReviewItem, UserFeedback } from "@/lib/types"

export const INTERNAL_STATUS_OPTIONS = ["명시", "일부명시", "미명시"] as const

export function applyFeedbackToItems(items: ReviewItem[], feedback: Record<string, UserFeedback>): ReviewItem[] {
  return items.map((item) => applyInternalAssessmentOverrides(item, feedback[String(item.item_no)]?.internal_assessment_overrides))
}

export function applyInternalAssessmentOverrides(
  item: ReviewItem,
  overrides?: InternalAssessmentOverrides,
): ReviewItem {
  if (!item.detailed_assessment || !overrides || Object.keys(overrides).length === 0) return item

  const assessment: DetailedAssessment = {
    ...item.detailed_assessment,
    rows: item.detailed_assessment.rows.map((row) => ({
      ...row,
      explicit_status: overrides[row.no] ?? row.explicit_status,
    })),
  }
  assessment.final_result = finalResultFromAssessment(assessment)
  assessment.reason = reasonFromAssessment(assessment)
  assessment.recommendation = recommendationFromAssessment(assessment)

  const complianceContent = complianceTextFromAssessment(assessment, item.evidence_pages)
  return {
    ...item,
    detailed_assessment: assessment,
    normalized_result: assessment.final_result,
    review_result: assessment.final_result,
    reason: assessment.reason,
    compliance_content: complianceContent,
    copy_texts: {
      ...item.copy_texts,
      review_result: assessment.final_result,
      compliance_content: complianceContent,
      internal_assessment: internalAssessmentCopyText(item, assessment),
    },
  }
}

export function finalResultFromAssessment(assessment: DetailedAssessment): string {
  const statuses = assessment.rows.map((row) => row.explicit_status)
  if (statuses.every((status) => status === "명시")) return "준수"
  if (statuses.some((status) => status === "명시" || status === "일부명시")) return "보완필요"
  return "미준수"
}

export function reasonFromAssessment(assessment: DetailedAssessment): string {
  if (assessment.final_result === "준수") {
    return "내부 검토표의 모든 항목이 명시되어 있습니다."
  }
  const missing = assessment.rows
    .filter((row) => row.explicit_status !== "명시")
    .map((row) => `${row.no}. ${row.title}(${row.explicit_status})`)
  return `명시가 부족한 내부 항목: ${missing.join(", ")}`
}

export function recommendationFromAssessment(assessment: DetailedAssessment): string {
  return assessment.rows
    .filter((row) => row.explicit_status !== "명시")
    .map((row) => row.missing_action)
    .filter(Boolean)
    .filter((value, index, values) => values.indexOf(value) === index)
    .join("\n")
}

export function complianceTextFromAssessment(
  assessment: DetailedAssessment,
  evidencePages?: (number | string)[],
): string {
  if (assessment.final_result === "준수") {
    const pageText = formatPages(evidencePages)
    return pageText ? `제안요청서 ${pageText} 명시` : "관련 문구 명시"
  }
  return assessment.recommendation || assessment.reason || "미명시 항목을 보완하시기 바랍니다."
}

export function internalAssessmentCopyText(item: ReviewItem, assessment = item.detailed_assessment): string {
  if (!assessment) return ""
  const lines = [`${item.item_no}. ${item.law_name || assessment.title}`, "", "구분\t내용\t명시 여부"]
  for (const row of assessment.rows) {
    lines.push(`${row.no}\t${row.title}\n${row.content}\t${row.explicit_status}`)
  }
  lines.push("", `최종 판단\t${assessment.final_result}`)
  if (assessment.reason) lines.push(`판단 근거\t${assessment.reason}`)
  return lines.join("\n")
}

export function formatPages(pages?: (number | string)[]): string {
  const nums = [...new Set((pages ?? []).map((page) => Number(page)).filter((page) => Number.isFinite(page)))]
    .sort((a, b) => a - b)
  if (nums.length === 0) return ""

  const parts: string[] = []
  let start = nums[0]
  let previous = nums[0]
  for (const page of nums.slice(1)) {
    if (page === previous + 1) {
      previous = page
      continue
    }
    parts.push(start === previous ? `p.${start}` : `pp.${start}-${previous}`)
    start = previous = page
  }
  parts.push(start === previous ? `p.${start}` : `pp.${start}-${previous}`)
  return parts.join(", ")
}
