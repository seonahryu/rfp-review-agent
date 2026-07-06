from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from agents.llm_client import DisabledLlmClient
from agents.models import AuditFinding, FinalAdjudication, FinalReview, ReviewResult, VerificationAudit


IGNORED_SOURCES = {"llm_disabled"}
AUTO_FINAL_RESULTS = {"준수", "미준수", "보완필요", "해당없음", "비대상"}


class VerificationAuditAgent:
    """Pass 2 auditor that finds defects without replacing the primary result."""

    def __init__(self, llm_client: object | None = None) -> None:
        self.llm_client = llm_client or DisabledLlmClient()

    def audit_review(
        self,
        *,
        item_no: str,
        review: ReviewResult,
        pages: list[object] | None = None,
        expected_route: str | None = None,
        atomic_requirements: list[dict[str, Any]] | None = None,
    ) -> VerificationAudit:
        findings = self.rule_based_findings(
            item_no=item_no,
            review=review,
            pages=pages or [],
            expected_route=expected_route,
            atomic_requirements=atomic_requirements or [],
        )
        if getattr(self.llm_client, "is_configured", lambda: False)():
            findings.extend(
                self.llm_findings(
                    item_no=item_no,
                    review=review,
                    atomic_requirements=atomic_requirements or [],
                )
            )
        blocking = [finding for finding in findings if finding.severity in {"high", "medium"}]
        return VerificationAudit(
            item_no=str(item_no),
            audited_review_source=review.source,
            can_auto_accept=not blocking,
            requires_adjudication=any(finding.severity == "high" for finding in findings),
            findings=findings,
            audit_summary=summarize_findings(findings),
        )

    def rule_based_findings(
        self,
        *,
        item_no: str,
        review: ReviewResult,
        pages: list[object],
        expected_route: str | None,
        atomic_requirements: list[dict[str, Any]],
    ) -> list[AuditFinding]:
        findings: list[AuditFinding] = []
        evidence_text = " ".join(str(text or "") for text in review.evidence_text)
        reason_text = str(review.reason or "")

        if len(review.evidence_pages) != len(review.evidence_text):
            findings.append(
                AuditFinding(
                    finding_type="schema_or_consistency_error",
                    severity="medium",
                    message="evidence_pages and evidence_text counts are not aligned.",
                    suggested_action="Re-check evidence page/text pairs before final use.",
                )
            )

        if expected_route and not route_matches(expected_route, review.route_type):
            findings.append(
                AuditFinding(
                    finding_type="invalid_routing",
                    severity="high",
                    message=f"Expected {expected_route} route, but primary review route was {review.route_type}.",
                    suggested_action="Run the correct primary review route or adjudicate.",
                )
            )

        page_text_by_number = page_text_lookup(pages)
        for idx, evidence_page in enumerate(review.evidence_pages):
            if idx >= len(review.evidence_text):
                continue
            text = review.evidence_text[idx]
            page_text = page_text_by_number.get(evidence_page, "")
            if text and page_text and normalize(text)[:80] not in normalize(page_text):
                findings.append(
                    AuditFinding(
                        finding_type="invalid_evidence_page",
                        severity="high",
                        message=f"Evidence text was not found on page {evidence_page}.",
                        evidence_observed=[text],
                        suggested_action="Use a page/text pair that directly contains the cited evidence.",
                    )
                )

        for requirement in atomic_requirements:
            requirement_id = str(requirement.get("id") or "")
            requirement_text = str(requirement.get("text") or requirement.get("requirement") or "")
            if not requirement_text:
                continue
            if not requirement_is_supported(requirement_text, evidence_text):
                findings.append(
                    AuditFinding(
                        finding_type="missing_required_requirement",
                        severity="high" if is_compliant_result(review.result) else "medium",
                        atomic_requirement_id=requirement_id or None,
                        message=f"Required atomic requirement is not supported by evidence_text: {requirement_text}",
                        evidence_observed=review.evidence_text,
                        suggested_action="Final adjudicator must reassess this requirement before accepting the result.",
                    )
                )

        if reason_text and evidence_text:
            reason_terms = important_terms(reason_text)
            evidence_terms = set(important_terms(evidence_text))
            missing_reason_terms = [term for term in reason_terms if term not in evidence_terms]
            if len(missing_reason_terms) >= 2:
                findings.append(
                    AuditFinding(
                        finding_type="evidence_reason_mismatch",
                        severity="medium",
                        message="Reason contains important claims that are not visible in evidence_text.",
                        evidence_observed=missing_reason_terms[:5],
                        suggested_action="Align reason with evidence or send to adjudication.",
                    )
                )

        if is_compliant_result(review.result) and any(
            finding.finding_type in {"missing_required_requirement", "invalid_evidence_page"}
            for finding in findings
        ):
            findings.append(
                AuditFinding(
                    finding_type="overstated_judgement_strength",
                    severity="high",
                    message="Primary result is compliant, but required support is missing or invalid.",
                    suggested_action="Do not auto-accept; run final adjudication.",
                )
            )

        return findings

    def llm_findings(
        self,
        *,
        item_no: str,
        review: ReviewResult,
        atomic_requirements: list[dict[str, Any]],
    ) -> list[AuditFinding]:
        prompt = json.dumps(
            {
                "task": "audit primary RFP legal-review result",
                "instruction": "Do not make a new final judgement. Only find errors in the primary review.",
                "audit_types": [
                    "missing_required_requirement",
                    "evidence_reason_mismatch",
                    "invalid_evidence_page",
                    "invalid_routing",
                    "overstated_judgement_strength",
                ],
                "item_no": item_no,
                "primary_review": review.to_dict(),
                "atomic_requirements": atomic_requirements,
                "output_schema": {
                    "findings": [
                        {
                            "finding_type": "string",
                            "severity": "low|medium|high",
                            "message": "string",
                            "atomic_requirement_id": "string or null",
                            "evidence_observed": ["string"],
                            "suggested_action": "string",
                        }
                    ]
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        data = self.llm_client.json_response(
            "You are an auditor. Do not decide the final result; only find defects in the primary review.",
            prompt,
            model_role="verification_audit",
            temperature=0,
        )
        return [
            AuditFinding(
                finding_type=str(item.get("finding_type", "schema_or_consistency_error")),
                severity=str(item.get("severity", "medium")),
                message=str(item.get("message", "")),
                atomic_requirement_id=item.get("atomic_requirement_id"),
                evidence_observed=[str(value) for value in item.get("evidence_observed", [])],
                suggested_action=str(item.get("suggested_action", "")),
            )
            for item in data.get("findings", [])
        ]


class FinalAdjudicationAgent:
    """Pass 3 adjudicator used only when Pass 2 finds blocking issues."""

    def __init__(self, llm_client: object | None = None) -> None:
        self.llm_client = llm_client or DisabledLlmClient()

    def adjudicate(
        self,
        *,
        item_no: str,
        primary_review: ReviewResult,
        audit: VerificationAudit,
        atomic_requirements: list[dict[str, Any]],
    ) -> FinalAdjudication:
        if not getattr(self.llm_client, "is_configured", lambda: False)():
            return fallback_adjudication(item_no, primary_review, atomic_requirements)
        prompt = json.dumps(
            {
                "task": "final RFP legal-review adjudication after audit findings",
                "instruction": "Fill every atomic requirement assessment before returning final_result.",
                "item_no": item_no,
                "primary_review": primary_review.to_dict(),
                "verification_audit": audit.to_dict(),
                "atomic_requirements": atomic_requirements,
                "output_schema": {
                    "atomic_requirement_assessment": [
                        {
                            "id": "string",
                            "status": "met|partially_met|not_found|not_applicable",
                            "evidence_pages": ["int"],
                            "evidence_text": ["string"],
                            "reason": "string",
                        }
                    ],
                    "final_result": "준수|미준수|보완필요|해당없음",
                    "reason": "string",
                    "recommendation": "string",
                    "evidence_pages": ["int"],
                    "evidence_text": ["string"],
                    "confidence": "0.0-1.0",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        data = self.llm_client.json_response(
            "You are the final adjudicator. You must complete the atomic requirement table first.",
            prompt,
            escalation=True,
            temperature=0,
        )
        assessment = list(data.get("atomic_requirement_assessment", []))
        expected_ids = {str(item.get("id")) for item in atomic_requirements if item.get("id")}
        returned_ids = {str(item.get("id")) for item in assessment if item.get("id")}
        if expected_ids and expected_ids - returned_ids:
            raise ValueError(f"Final adjudication omitted atomic requirements: {sorted(expected_ids - returned_ids)}")
        return FinalAdjudication(
            item_no=str(item_no),
            final_result=str(data.get("final_result", primary_review.result)),
            atomic_requirement_assessment=assessment,
            reason=str(data.get("reason", primary_review.reason)),
            recommendation=str(data.get("recommendation", primary_review.recommendation)),
            evidence_pages=[int(value) for value in data.get("evidence_pages", []) if str(value).isdigit()],
            evidence_text=[str(value) for value in data.get("evidence_text", [])],
            confidence=float(data.get("confidence", primary_review.confidence)),
        )


class VerificationAgent:
    def __init__(self, llm_client: object | None = None, conflict_threshold: int = 2) -> None:
        self.llm_client = llm_client or DisabledLlmClient()
        self.conflict_threshold = conflict_threshold

    def verify(self, item_no: str, reviews: list[ReviewResult], *, parse_status: str) -> FinalReview:
        warnings: list[str] = []
        active_reviews = [review for review in reviews if review.source not in IGNORED_SOURCES]
        if not active_reviews:
            warnings.append("활성화된 검토 결과가 없어 자동 확정하지 않습니다.")
            return choose_final(item_no, "사람 확인 필요", reviews, warnings)

        if parse_status == "fail":
            warnings.append("파싱 상태가 fail이므로 자동 확정하지 않습니다.")
            return choose_final(item_no, "파싱 문제로 판단 보류", active_reviews, warnings)

        non_target = [
            review
            for review in active_reviews
            if review.is_target is False or str(review.result).strip() == "해당없음"
        ]
        if non_target and len(non_target) == len(active_reviews):
            best = max(non_target, key=lambda review: review.confidence)
            if not best.needs_human_review and best.confidence >= 0.7:
                return choose_final(item_no, "자동 확정 가능", [best], warnings)

        grounded = [review for review in active_reviews if review.evidence_pages and review.evidence_text]
        if not grounded:
            warnings.append("근거 페이지 또는 근거 문구가 부족합니다.")
            return choose_final(item_no, "근거 부족", active_reviews, warnings)

        vote_key_counts = Counter((review.result, review.is_target) for review in grounded)
        (result, _is_target), count = vote_key_counts.most_common(1)[0]
        conflicts = len({(review.result, review.is_target) for review in grounded})

        if conflicts >= self.conflict_threshold and getattr(self.llm_client, "is_configured", lambda: False)():
            escalated = self.escalate(item_no, grounded)
            attach_grounded_evidence(escalated, grounded)
            return choose_final(item_no, "상위 GPT 최종 판정", active_reviews + [escalated], warnings)

        if len(grounded) == 1:
            only = grounded[0]
            if only.result in AUTO_FINAL_RESULTS and not only.needs_human_review and only.confidence >= 0.7:
                return choose_final(item_no, "자동 확정 가능", grounded, warnings)
            return choose_final(item_no, "사람 확인 필요", grounded, warnings)

        if count >= 2 and result in AUTO_FINAL_RESULTS:
            matching = [review for review in grounded if (review.result, review.is_target) == (result, _is_target)]
            if not any(review.needs_human_review for review in matching):
                return choose_final(item_no, "자동 확정 가능", matching, warnings)

        if conflicts > 1:
            warnings.append("리뷰 에이전트 간 판단이 불일치합니다.")
            return choose_final(item_no, "검토 결과 불일치", grounded, warnings)

        return choose_final(item_no, "사람 확인 필요", grounded, warnings)

    def escalate(self, item_no: str, reviews: list[ReviewResult]) -> ReviewResult:
        prompt = json.dumps(
            {
                "task": "RFP 법제도 검토 결과 충돌 최종 판정",
                "instruction": "제공된 각 판단의 근거만 사용해 최종 판정을 고르세요.",
                "allowed_results": ["준수", "미준수", "보완필요", "해당없음"],
                "reviews": [review.to_dict() for review in reviews],
                "output_schema": {
                    "result": "준수|미준수|보완필요|해당없음",
                    "is_target": "boolean or null",
                    "confidence": "0.0-1.0",
                    "evidence_pages": ["page number"],
                    "evidence_text": ["verbatim evidence"],
                    "reason": "short reason",
                    "recommendation": "copy-paste recommendation when needed",
                    "needs_human_review": "boolean",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        data = self.llm_client.json_response(
            "당신은 RFP 법제도 검토 최종 검증자입니다. JSON 객체 하나만 반환하세요.",
            prompt,
            escalation=True,
            temperature=0,
        )
        return ReviewResult(
            item_no=item_no,
            route_type="verification_escalation",
            result=str(data.get("result", "보완필요")),
            is_target=data.get("is_target"),
            confidence=float(data.get("confidence", 0.6)),
            evidence_pages=[int(x) for x in data.get("evidence_pages", []) if str(x).isdigit()],
            evidence_text=[str(x) for x in data.get("evidence_text", [])],
            reason=str(data.get("reason", "")),
            recommendation=str(data.get("recommendation", "")),
            needs_human_review=bool(data.get("needs_human_review", True)),
            source="openai_escalation",
            used_llm=True,
        )


def attach_grounded_evidence(escalated: ReviewResult, grounded: list[ReviewResult]) -> None:
    matching = [
        review
        for review in grounded
        if (review.result, review.is_target) == (escalated.result, escalated.is_target)
    ]
    source_reviews = matching or grounded
    page_text_by_page: dict[int, str] = {}
    for review in source_reviews:
        for idx, page in enumerate(review.evidence_pages):
            if page in page_text_by_page:
                continue
            text = review.evidence_text[idx] if idx < len(review.evidence_text) else ""
            page_text_by_page[page] = text
    escalated.evidence_pages = sorted(page_text_by_page)
    escalated.evidence_text = [page_text_by_page[page] for page in escalated.evidence_pages]


def choose_final(
    item_no: str,
    status: str,
    reviews: list[ReviewResult],
    warnings: list[str],
) -> FinalReview:
    chosen = max(reviews, key=lambda review: (bool(review.evidence_pages), review.confidence))
    confidence = chosen.confidence if status in {"자동 확정 가능", "상위 GPT 최종 판정"} else min(chosen.confidence, 0.69)
    return FinalReview(
        item_no=item_no,
        final_status=status,
        final_result=chosen.result,
        is_target=chosen.is_target,
        confidence=round(confidence, 3),
        evidence_pages=chosen.evidence_pages,
        evidence_text=chosen.evidence_text,
        reason=chosen.reason,
        recommendation=chosen.recommendation,
        reviews=reviews,
        warnings=warnings,
    )


def summarize_findings(findings: list[AuditFinding]) -> str:
    if not findings:
        return "No audit findings."
    counts = Counter(finding.finding_type for finding in findings)
    return ", ".join(f"{finding_type}: {count}" for finding_type, count in sorted(counts.items()))


def route_matches(expected_route: str, actual_route_type: str) -> bool:
    expected = str(expected_route or "").strip()
    actual = str(actual_route_type or "").strip()
    if not expected:
        return True
    return actual == expected or actual.startswith(expected) or f"{expected}_" in actual


def page_text_lookup(pages: list[object]) -> dict[int, str]:
    result: dict[int, str] = {}
    for page in pages:
        text = str(getattr(page, "page_text", "") or "")
        for number in [getattr(page, "page_no", None), getattr(page, "rfp_printed_page_no", None)]:
            if isinstance(number, int):
                result[number] = text
    return result


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def important_terms(text: str) -> list[str]:
    stopwords = {
        "및",
        "또는",
        "모두",
        "확인",
        "확인됨",
        "한다",
        "있음",
        "내용",
        "관련",
        "the",
        "and",
        "for",
    }
    terms = re.findall(r"[0-9A-Za-z가-힣]{2,}", str(text or ""))
    return [term for term in terms if term not in stopwords]


def requirement_is_supported(requirement_text: str, evidence_text: str) -> bool:
    requirement_terms = important_terms(requirement_text)
    if not requirement_terms:
        return True
    evidence = normalize(evidence_text)
    matched = [term for term in requirement_terms if normalize(term) in evidence]
    if len(requirement_terms) == 1:
        return bool(matched)
    return len(matched) >= max(1, int(len(requirement_terms) * 0.7 + 0.5))


def is_compliant_result(result: str) -> bool:
    text = str(result or "").strip()
    return text in {"준수", "以??"} or text.startswith("以")


def fallback_adjudication(
    item_no: str,
    primary_review: ReviewResult,
    atomic_requirements: list[dict[str, Any]],
) -> FinalAdjudication:
    evidence_text = " ".join(primary_review.evidence_text)
    assessment = []
    for requirement in atomic_requirements:
        requirement_id = str(requirement.get("id") or "")
        requirement_text = str(requirement.get("text") or requirement.get("requirement") or "")
        supported = requirement_is_supported(requirement_text, evidence_text)
        assessment.append(
            {
                "id": requirement_id,
                "status": "met" if supported else "not_found",
                "evidence_pages": list(primary_review.evidence_pages) if supported else [],
                "evidence_text": list(primary_review.evidence_text) if supported else [],
                "reason": "Supported by primary evidence." if supported else "Not found in primary evidence.",
            }
        )
    return FinalAdjudication(
        item_no=str(item_no),
        final_result=primary_review.result,
        atomic_requirement_assessment=assessment,
        reason=primary_review.reason,
        recommendation=primary_review.recommendation,
        evidence_pages=list(primary_review.evidence_pages),
        evidence_text=list(primary_review.evidence_text),
        confidence=primary_review.confidence,
    )
