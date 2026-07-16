from __future__ import annotations

import re

from agents.models import ComplianceContent, FinalReview, RagContext


class ComplianceContentAgent:
    """Creates short report-ready wording for each legal-review item."""

    def generate(self, review: FinalReview, rag: RagContext) -> ComplianceContent:
        label = result_label(review)
        tacit = tacit_knowledge(rag)

        if label == "해당없음":
            return ComplianceContent(
                item_no=str(review.item_no),
                content_type="compliance_statement",
                primary_evidence_pages=[],
                used_evidence_pages=[],
                compliance_content="해당없음",
                tacit_knowledge_used=tacit,
                warnings=[],
            )

        if str(review.item_no) == "14" and label == "준수":
            first_page = min(review.evidence_pages) if review.evidence_pages else None
            content = f"제안요청서 p.{first_page} 이하 명시" if first_page is not None else ""
            return ComplianceContent(
                item_no=str(review.item_no),
                content_type="compliance_statement",
                primary_evidence_pages=[first_page] if first_page is not None else [],
                used_evidence_pages=[first_page] if first_page is not None else [],
                compliance_content=content,
                tacit_knowledge_used=tacit,
                warnings=[] if content else ["missing_evidence_pages"],
            )

        direct_pages = direct_legal_review_pages(review)
        if str(review.item_no) == "16":
            recommendation = str(review.recommendation or "").strip()
            if recommendation and label in {"보완필요", "미준수"}:
                prefix = f"제안요청서 {format_pages(direct_pages)}에 투입인력 요구사항이 확인됩니다.\n" if direct_pages else ""
                content = prefix + "-> " + recommendation
            elif review.is_target is True:
                content = f"제안요청서 {format_pages(direct_pages)} 기준 대상 사업으로 판단" if direct_pages else "대상 사업으로 판단"
            elif review.is_target is False:
                content = f"제안요청서 {format_pages(direct_pages)} 기준 비대상 사업으로 판단" if direct_pages else "비대상 사업으로 판단"
            else:
                content = "대상여부 확인필요"
            return ComplianceContent(
                item_no=str(review.item_no),
                content_type="compliance_statement",
                primary_evidence_pages=direct_pages,
                used_evidence_pages=direct_pages,
                compliance_content=content,
                tacit_knowledge_used=tacit,
                warnings=[],
            )

        if str(review.item_no) == "9" and label == "준수":
            return ComplianceContent(
                item_no=str(review.item_no),
                content_type="compliance_statement",
                primary_evidence_pages=[],
                used_evidence_pages=[],
                compliance_content="특정규격 명시 없음",
                tacit_knowledge_used=tacit,
                warnings=[],
            )

        if label == "준수":
            content = f"제안요청서 {format_pages(direct_pages)} 명시" if direct_pages else ""
            return ComplianceContent(
                item_no=str(review.item_no),
                content_type="compliance_statement",
                primary_evidence_pages=direct_pages,
                used_evidence_pages=direct_pages,
                compliance_content=content,
                tacit_knowledge_used=tacit,
                warnings=[] if content else ["missing_evidence_pages"],
            )

        if label in {"보완필요", "미준수"}:
            recommendation = concrete_recommendation(review, rag)
            if not recommendation:
                return empty_content(review, tacit, "missing_recommendation")
            page_text = format_pages(direct_pages)
            if not page_text:
                if label == "미준수":
                    return ComplianceContent(
                        item_no=str(review.item_no),
                        content_type="compliance_statement",
                        primary_evidence_pages=[],
                        used_evidence_pages=[],
                        compliance_content=recommendation,
                        tacit_knowledge_used=tacit,
                        warnings=[],
                    )
                return empty_content(review, tacit, "missing_direct_evidence_pages")
            if label == "보완필요" or has_partial_context(review):
                content = partial_supplement_content(page_text, review, recommendation)
            else:
                content = join_page_prefix_and_recommendation(page_text, recommendation)
            return ComplianceContent(
                item_no=str(review.item_no),
                content_type="compliance_statement",
                primary_evidence_pages=direct_pages,
                used_evidence_pages=direct_pages,
                compliance_content=content,
                tacit_knowledge_used=tacit,
                warnings=[],
            )

        return empty_content(review, tacit, "unknown_result")


def empty_content(review: FinalReview, tacit: list[str], warning: str) -> ComplianceContent:
    return ComplianceContent(
        item_no=str(review.item_no),
        content_type="compliance_statement",
        primary_evidence_pages=[],
        used_evidence_pages=[],
        compliance_content="",
        tacit_knowledge_used=tacit,
        warnings=[warning],
    )


def result_label(review: FinalReview) -> str:
    if review.is_target is False:
        return "해당없음"
    text = str(review.final_result or "").strip()
    if text in {"준수", "미준수", "보완필요", "해당없음"}:
        return text
    if looks_like_legacy_compliant(text):
        return "준수"
    if looks_like_legacy_non_compliant(text):
        return "미준수"
    if looks_like_legacy_needs_supplement(text):
        return "보완필요"
    if looks_like_legacy_not_applicable(text):
        return "해당없음"
    return text


def direct_legal_review_pages(review: FinalReview) -> list[int]:
    pages: list[int] = []
    for idx, page in enumerate(review.evidence_pages):
        text = review.evidence_text[idx] if idx < len(review.evidence_text) else ""
        if not isinstance(page, int):
            continue
        if is_target_only_or_context(text):
            continue
        if page not in pages:
            pages.append(page)
    return sorted(pages)


def format_pages(pages: list[int]) -> str:
    unique = sorted(dict.fromkeys(pages))
    if not unique:
        return ""
    parts: list[str] = []
    start = previous = unique[0]
    for page in unique[1:]:
        if page == previous + 1:
            previous = page
            continue
        parts.append(format_page_part(start, previous))
        start = previous = page
    parts.append(format_page_part(start, previous))
    return ", ".join(parts)


def format_page_part(start: int, end: int) -> str:
    if start == end:
        return f"p.{start}"
    return f"pp.{start}-{end}"


def tacit_knowledge(rag: RagContext) -> list[str]:
    return [hit.snippet for hit in rag.hits if hit.source_type == "tacit_knowledge" and hit.snippet]


def concrete_recommendation(review: FinalReview, rag: RagContext) -> str:
    recommendation = str(review.recommendation or review.reason or "").strip()
    if str(review.item_no) == "17":
        compact = normalize(recommendation)
        if "영향평가" in compact and "결과서" in compact:
            return "SW사업 영향평가 결과서를 작성하여 첨부하시기 바랍니다."
    if recommendation and not is_generic_recommendation(recommendation):
        return strip_rfp_page_references(recommendation)
    requirement = missing_requirement_from_rag(rag)
    if requirement:
        return f"제안요청서에 ‘{requirement}’에 관하여 명시하시기 바랍니다."
    return strip_rfp_page_references(recommendation)


def recommendation_after_page_prefix(recommendation: str) -> str:
    cleaned = str(recommendation or "").strip()
    cleaned = re.sub(r"^\s*제안요청서에\s*", "", cleaned)
    return cleaned.strip()


def join_page_prefix_and_recommendation(page_text: str, recommendation: str) -> str:
    action = recommendation_after_page_prefix(concise_partial_action(recommendation))
    particle = "" if starts_with_section_target(action) else "에"
    return f"제안요청서 {page_text}{particle} {action}"


def partial_supplement_content(page_text: str, review: FinalReview, recommendation: str) -> str:
    action = concise_partial_action(recommendation)
    return f"제안요청서 {page_text} 일부 명시\n→ {action}"


def has_partial_context(review: FinalReview) -> bool:
    text = " ".join([str(review.reason or ""), *direct_evidence_texts(review)])
    compact = normalize(text)
    if any(signal in compact for signal in ["제목만", "빈문서", "실제산정내용이없는", "실제검토내용이없는", "실제검토내용이확인되지"]):
        return False
    partial_signals = ["일부", "있으나", "확인되나", "제목만", "미흡", "부족"]
    return any(signal in compact for signal in partial_signals)


def direct_evidence_texts(review: FinalReview) -> list[str]:
    texts: list[str] = []
    for idx, page in enumerate(review.evidence_pages):
        text = review.evidence_text[idx] if idx < len(review.evidence_text) else ""
        if not isinstance(page, int):
            continue
        if is_target_only_or_context(text):
            continue
        if text:
            texts.append(str(text))
    return texts


def concise_partial_action(recommendation: str) -> str:
    action = strip_rfp_page_references(recommendation)
    action = remove_example_explanation(action)
    compact = normalize(action)
    if ("소프트웨어사업영향평가" in compact or "sw사업영향평가" in compact) and "결과서" in compact:
        return "SW사업 영향평가 결과서를 작성하여 첨부하시기 바랍니다."
    return action


def remove_example_explanation(text: str) -> str:
    cleaned = str(text or "").strip()
    return re.split(r"\s*(?:예를\s*들어|예시(?:로|:)?|예컨대)\s*", cleaned, maxsplit=1)[0].strip()


def starts_with_section_target(text: str) -> bool:
    compact = str(text or "").lstrip()
    return compact.startswith(("제안서", "제안요청서", "평가항목", "배점표"))


def strip_rfp_page_references(text: str) -> str:
    """Keep example wording, but never keep example RFP page numbers."""
    cleaned = str(text or "").strip()
    if "->" in cleaned:
        cleaned = cleaned.split("->", 1)[1].strip()
    cleaned = re.sub(
        r"^\s*제안요청서\s+"
        r"(?:p{1,2}\.\s*\d+(?:\s*[-~]\s*\d+)?(?:\s*,\s*)?)+"
        r"(?:에|에는|의|에서)?\s*",
        "",
        cleaned,
    ).strip()
    cleaned = re.sub(
        r"^\s*제안요청서에\s*",
        "제안요청서에 ",
        cleaned,
    ).strip()
    cleaned = re.sub(
        r"^\s*제안요청서\s+등에\s*",
        "제안요청서에 ",
        cleaned,
    ).strip()
    cleaned = re.sub(r"([‘'\"])\s*제안요청서\s+등에\s*", r"\1", cleaned)
    return cleaned


def is_generic_recommendation(text: str) -> bool:
    compact = normalize(text)
    generic_terms = [
        "관련문구",
        "필수문구",
        "누락된",
        "누락",
        "모두명시",
        "보완하시기",
        "준수로판단",
    ]
    return sum(1 for term in generic_terms if normalize(term) in compact) >= 2


def missing_requirement_from_rag(rag: RagContext) -> str:
    for key in ["core_requirement_text", "requirement_text"]:
        for hit in rag.hits:
            if hit.source_type == "tacit_knowledge":
                continue
            extracted = extract_tagged_value(str(hit.snippet or ""), key)
            if extracted:
                return cleanup_requirement_text(extracted)
    return ""


def extract_tagged_value(text: str, key: str) -> str:
    pattern = rf"(?m)^\s*{re.escape(key)}\s*:\s*(.+?)(?=\n\s*[A-Za-z_]+_?text\s*:|\n\s*\[[A-Z ]+\]|\Z)"
    match = re.search(pattern, text, flags=re.DOTALL)
    return match.group(1).strip() if match else ""


def cleanup_requirement_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    cleaned = re.split(r"\s*(?:※|단,|다만,)\s*", cleaned, maxsplit=1)[0].strip()
    cleaned = re.sub(r"^제안요청서\s*등에\s*", "", cleaned).strip()
    cleaned = re.sub(r"^제안요청서에\s*", "", cleaned).strip()
    cleaned = re.sub(r"^(ㅁ|ㅇ|-)\s*", "", cleaned).strip()
    cleaned = re.sub(r"(을|를)?\s*명시\s*$", "", cleaned).strip()
    return cleaned


def is_target_only_or_context(text: str) -> bool:
    compact = normalize(text)
    if is_non_substantive_reference(text):
        return True
    context_terms = ["사업개요", "사업명", "예산", "사업기간", "계약대상", "대상확인", "추진배경"]
    direct_terms = [
        "하자",
        "책임기간",
        "보안",
        "산출물",
        "누출금지",
        "확약서",
        "작업장소",
        "원격지",
        "평가",
        "명시",
        "제출",
        "협의",
    ]
    return any(normalize(term) in compact for term in context_terms) and not any(
        normalize(term) in compact for term in direct_terms
    )


def is_non_substantive_reference(text: str) -> bool:
    compact = normalize(text)
    if not compact:
        return True
    if "요구사항총괄표" in compact and any(term in compact for term in ["목록", "리스트", "일람"]):
        return True
    if looks_like_requirement_overview(compact):
        return True
    if looks_like_attachment_title_only(text, compact):
        return True
    if any(term in compact for term in ["빈서식", "빈양식", "작성서식", "작성양식"]):
        return True
    form_terms = ["서식", "양식"]
    substantive_terms = ["명시", "제출", "첨부", "작성하여첨부", "평가", "계약", "보안", "하자", "산출물"]
    if any(term in compact for term in form_terms) and not any(term in compact for term in substantive_terms):
        return True
    return False


def looks_like_requirement_overview(compact: str) -> bool:
    requirement_codes = re.findall(r"[a-z]{2,5}-\d{3}", compact, flags=re.IGNORECASE)
    return len(set(requirement_codes)) >= 3 and any(term in compact for term in ["요구사항", "분류", "고유번호"])


def looks_like_attachment_title_only(text: str, compact: str) -> bool:
    visible = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(visible) > 80:
        return False
    return compact.startswith(("별첨", "별지", "붙임")) and not any(
        term in compact for term in ["작성하여첨부", "제출하여야", "명시하여야", "하여야함", "○", "□"]
    )


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def looks_like_legacy_compliant(text: str) -> bool:
    return text.startswith("以") or text.startswith("餓")


def looks_like_legacy_non_compliant(text: str) -> bool:
    return text.startswith("誘") or text.startswith("미")


def looks_like_legacy_needs_supplement(text: str) -> bool:
    return text.startswith("蹂") or text.startswith("보완")


def looks_like_legacy_not_applicable(text: str) -> bool:
    return text.startswith("?대떦") or text.startswith("해당") or text.startswith("鍮")
