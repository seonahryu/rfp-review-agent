from __future__ import annotations

import re

from agents.gpt_judgement import gpt_review
from agents.llm_client import DisabledLlmClient
from agents.models import CandidatePage, RagContext, ReviewResult


RULE_KEYWORDS = {
    "1": ["과업심의위원회", "과업 심의", "심의위원회"],
    "3": ["중소 소프트웨어사업자의 사업 참여 지원", "대기업 및 중견기업", "입찰에 참여할 수 없음", "상호출자제한"],
    "4": ["하도급", "사전승인", "100분의 50", "하도급 계획서", "85점", "공동수급체", "관리감독", "시정요구"],
    "6": ["지식재산권의 활용", "S/W 산출물의 반출", "SW산출물의 반출", "누출금지", "제3자에게 제공", "사전승인"],
    "7": ["타 기관과 공동 활용", "공동 활용할 계획", "공동활용 할 계획", "공동활용 계획"],
    "14": ["요구사항 총괄표", "요구사항 고유번호", "요구사항 명칭", "상세 세부내용", "산출정보"],
    "18": ["SW사업정보", "소프트웨어 진흥법 제46조", "www.spir.kr", "SW 사업정보 저장소"],
}

TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")
STOPWORDS = {
    "관련",
    "검토",
    "기준",
    "내용",
    "확인",
    "경우",
    "또는",
    "하여",
    "하고",
    "한다",
    "대한",
    "등의",
    "법령",
}


class RuleReviewAgent:
    route_type = "rule_review"

    def __init__(self, llm_client: object | None = None) -> None:
        self.llm_client = llm_client or DisabledLlmClient()

    def review(self, item_no: str, pages: list[CandidatePage], rag: RagContext) -> ReviewResult:
        if str(item_no) == "14":
            structure_matches = evidence_for_requirement_detail_structure(pages)
            if structure_matches:
                return ReviewResult(
                    item_no=str(item_no),
                    route_type=self.route_type,
                    result="준수",
                    is_target=True,
                    confidence=0.88,
                    evidence_pages=[page for page, _ in structure_matches[:5]],
                    evidence_text=[text for _, text in structure_matches[:5]],
                    reason="요구사항 총괄표와 상세 요구사항 작성 구조가 RFP 본문에서 확인되었습니다.",
                    recommendation="",
                    needs_human_review=False,
                    source="python_rule_requirement_structure",
                    used_llm=False,
                )

        if str(item_no) == "3":
            matches = evidence_for_small_sw_participation(pages)
            if matches:
                return rule_success(str(item_no), self.route_type, matches)

        if str(item_no) == "4":
            disallow_matches = evidence_for_project_subcontract_disallowed(pages)
            if disallow_matches:
                return ReviewResult(
                    item_no=str(item_no),
                    route_type=self.route_type,
                    result="준수",
                    is_target=True,
                    confidence=0.88,
                    evidence_pages=[page for page, _ in disallow_matches[:1]],
                    evidence_text=[text for _, text in disallow_matches[:1]],
                    reason="본 사업의 하도급 불허가 직접 명시되어 있어 하도급 허용 사업에 적용되는 세부 기준은 case에 해당하지 않습니다.",
                    recommendation="",
                    needs_human_review=False,
                    source="python_rule_subcontract_disallowed",
                    used_llm=False,
                )
            matches = evidence_for_subcontract_terms(pages)
            if matches:
                return ReviewResult(
                    item_no=str(item_no),
                    route_type=self.route_type,
                    result="준수",
                    is_target=True,
                    confidence=0.88,
                    evidence_pages=[page for page, _ in matches[:3]],
                    evidence_text=[text for _, text in matches[:3]],
                    reason="하도급 허용 사업에 필요한 사전승인, 비율 제한, 계획서 제출, 적정성 판단, 공동수급체 구성, 관리감독 및 시정요구 문구가 확인되었습니다.",
                    recommendation="",
                    needs_human_review=False,
                    source="python_rule_subcontract_terms",
                    used_llm=False,
                )
            gpt_result = gpt_review(
                llm_client=self.llm_client,
                model_role="rule",
                item_no=item_no,
                route_type=self.route_type,
                pages=pages,
                rag=rag,
            )
            if gpt_result is not None:
                return gpt_result
            partial_matches = best_subcontract_terms_partial_evidence(pages)
            return rule_noncompliant(str(item_no), self.route_type, partial_matches)

        if str(item_no) == "6":
            matches = evidence_for_sw_output_reuse(pages, rag)
            if matches:
                return rule_success(str(item_no), self.route_type, matches)
            gpt_result = gpt_review(
                llm_client=self.llm_client,
                model_role="rule",
                item_no=item_no,
                route_type=self.route_type,
                pages=pages,
                rag=rag,
            )
            if gpt_result is not None:
                return gpt_result
            partial_matches = best_sw_output_reuse_partial_evidence(pages)
            return rule_noncompliant(str(item_no), self.route_type, partial_matches)

        matches = evidence_for_keywords(pages, RULE_KEYWORDS.get(str(item_no), []), radius=80)
        if matches:
            return rule_success(str(item_no), self.route_type, matches[:3])

        rag_match = best_rag_keyword_match(pages, rag)
        if rag_match and rag_match["coverage"] >= 0.7:
            coverage = rag_match["coverage"]
            return ReviewResult(
                item_no=str(item_no),
                route_type=self.route_type,
                result="준수",
                is_target=True,
                confidence=round(min(0.9, 0.45 + coverage * 0.5), 3),
                evidence_pages=[int(rag_match["page_no"])],
                evidence_text=[str(rag_match["evidence"])],
                reason=f"DB 기준문구 핵심 키워드의 {coverage:.0%}가 RFP 후보 페이지에서 확인되어 70% 기준을 충족했습니다.",
                recommendation="",
                needs_human_review=False,
                source="python_rule_rag_overlap",
                used_llm=False,
            )

        gpt_result = gpt_review(
            llm_client=self.llm_client,
            model_role="rule",
            item_no=item_no,
            route_type=self.route_type,
            pages=pages,
            rag=rag,
        )
        if gpt_result is not None:
            return gpt_result

        return ReviewResult(
            item_no=str(item_no),
            route_type=self.route_type,
            result="확인필요",
            is_target=True,
            confidence=0.52,
            evidence_pages=[],
            evidence_text=[],
            reason="규칙 기반 키워드와 DB 기준문구 70% 커버리지 조건을 충족하지 못했습니다.",
            recommendation="해당 검토항목의 필수 문구 반영 여부를 수동 확인하세요.",
            needs_human_review=True,
            source="python_rule",
            used_llm=False,
        )


def rule_success(item_no: str, route_type: str, matches: list[tuple[int, str]]) -> ReviewResult:
    return ReviewResult(
        item_no=item_no,
        route_type=route_type,
        result="준수",
        is_target=True,
        confidence=0.88,
        evidence_pages=[page for page, _ in matches],
        evidence_text=[text for _, text in matches],
        reason="규칙 기반 핵심 근거가 RFP 본문에서 확인되었습니다.",
        recommendation="",
        needs_human_review=False,
        source="python_rule",
        used_llm=False,
    )


def rule_uncertain(item_no: str, route_type: str) -> ReviewResult:
    return ReviewResult(
        item_no=item_no,
        route_type=route_type,
        result="확인필요",
        is_target=True,
        confidence=0.52,
        evidence_pages=[],
        evidence_text=[],
        reason="규칙 기반 필수 요건 세트가 RFP 근거 페이지에서 모두 확인되지 않았습니다.",
        recommendation="해당 검토항목의 필수 문구 반영 여부를 수동 확인하세요.",
        needs_human_review=True,
        source="python_rule",
        used_llm=False,
    )


def rule_noncompliant(item_no: str, route_type: str, matches: list[tuple[int, str]] | None = None) -> ReviewResult:
    matches = matches or []
    return ReviewResult(
        item_no=item_no,
        route_type=route_type,
        result="미준수",
        is_target=True,
        confidence=0.82,
        evidence_pages=[page for page, _ in matches],
        evidence_text=[text for _, text in matches],
        reason="필수 법제도 검토기준 중 일부가 RFP 본문에서 모두 확인되지 않았습니다.",
        recommendation="관련 문구를 모두 명시해야 준수로 판단됩니다. 누락된 필수 문구를 제안요청서에 보완하시기 바랍니다.",
        needs_human_review=False,
        source="python_rule",
        used_llm=False,
    )


def evidence_for_small_sw_participation(pages: list[CandidatePage]) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for page in pages:
        if page.has_toc_candidate:
            continue
        text = page.page_text
        compact = "".join(text.split())
        has_budget_limit = "20" in compact and "미만" in compact
        has_company_limit = "대기업" in compact and "중견기업" in compact
        has_bid_restriction = "입찰" in compact and ("참여할수없음" in compact or "참여" in compact and "없음" in compact)
        if has_budget_limit and has_company_limit and has_bid_restriction:
            hits.append((rfp_display_page_no(page), evidence_window(text, "20", radius=420)))
    return hits[:1]


def evidence_for_project_subcontract_disallowed(pages: list[CandidatePage]) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for page in pages:
        if page.has_toc_candidate:
            continue
        text = page.page_text
        if is_project_subcontract_disallowed(text):
            hits.append((rfp_display_page_no(page), evidence_window(text, "하도급", radius=160)))
    return hits[:1]


def is_project_subcontract_disallowed(text: str) -> bool:
    compact = compact_for_match(text)
    if not ("하도급" in compact and ("불허" in compact or "허용하지" in compact)):
        return False
    direct_patterns = [
        r"(?:본사업|본과업|해당사업)(?:은|는)[^.;。]{0,100}하도급(?:은|을|이)?(?:원칙적으로)?(?:불허|허용하지않)",
        r"(?:본사업|본과업|해당사업)의하도급(?:은|을|이)?(?:원칙적으로)?(?:불허|허용하지않)",
    ]
    return any(re.search(pattern, compact) for pattern in direct_patterns)


def evidence_for_subcontract_terms(pages: list[CandidatePage]) -> list[tuple[int, str]]:
    required = {
        "oversight_correction",
        "prior_approval",
        "ratio_limit",
        "plan_submission",
        "approval_criteria",
        "joint_consortium",
    }
    covered: set[str] = set()
    candidates: list[tuple[CandidatePage, set[str]]] = []

    for page in pages:
        if page.has_toc_candidate:
            continue
        matched = subcontract_term_requirements(page.page_text)
        if not matched:
            continue
        covered.update(matched)
        candidates.append((page, matched))

    if required.issubset(covered):
        return select_subcontract_term_evidence_pages(candidates, required)
    return []


def subcontract_term_requirements(text: str) -> set[str]:
    compact = compact_for_match(text)
    matched: set[str] = set()

    if "하도급" in compact and "관리" in compact and "감독" in compact and "시정" in compact and "요구" in compact:
        matched.add("oversight_correction")
    if "하도급" in compact and "사전승인" in compact:
        matched.add("prior_approval")
    if "하도급" in compact and ("100분의50" in compact or "50%" in compact) and ("초과할수없" in compact or "초과할수없" in compact):
        matched.add("ratio_limit")
    if "하도급" in compact and "계획서" in compact and ("제출" in compact or "계약체결" in compact):
        matched.add("plan_submission")
    if "하도급" in compact and "적정성" in compact and "85점" in compact and ("승인" in compact or "판단" in compact):
        matched.add("approval_criteria")
    if "하도급" in compact and ("10%" in compact or "10퍼센트" in compact) and "공동수급체" in compact:
        matched.add("joint_consortium")

    return matched


def select_subcontract_term_evidence_pages(
    candidates: list[tuple[CandidatePage, set[str]]],
    required: set[str],
) -> list[tuple[int, str]]:
    selected: list[tuple[int, str]] = []
    remaining = set(required)
    for page, matched in sorted(candidates, key=lambda item: len(item[1]), reverse=True):
        useful = matched & remaining
        if not useful:
            continue
        selected.append((rfp_display_page_no(page), evidence_window(page.page_text, "하도급", radius=420)))
        remaining -= useful
        if not remaining:
            break
    return selected


def best_subcontract_terms_partial_evidence(pages: list[CandidatePage]) -> list[tuple[int, str]]:
    scored: list[tuple[int, CandidatePage]] = []
    for page in pages:
        if page.has_toc_candidate:
            continue
        matched = subcontract_term_requirements(page.page_text)
        if matched:
            scored.append((len(matched), page))
    scored.sort(key=lambda item: (-item[0], rfp_display_page_no(item[1])))
    return [
        (rfp_display_page_no(page), evidence_window(page.page_text, "하도급", radius=260))
        for _, page in scored[:3]
    ]


def evidence_for_sw_output_reuse(
    pages: list[CandidatePage],
    rag: RagContext | None = None,
) -> list[tuple[int, str]]:
    required = sw_output_reuse_required_requirements(rag)
    covered: set[str] = set()
    candidates: list[tuple[CandidatePage, set[str]]] = []

    for page in pages:
        if page.has_toc_candidate:
            continue
        matched = sw_output_reuse_requirements(page.page_text)
        if not matched:
            continue
        covered.update(matched)
        candidates.append((page, matched))

    if required.issubset(covered):
        return select_sw_output_reuse_evidence_pages(candidates, required)
    return []


def sw_output_reuse_required_requirements(rag: RagContext | None = None) -> set[str]:
    return {
        "ip_ownership",
        "export_allowed",
        "export_request",
        "secret_removal",
        "confirmation_letter",
        "third_party_approval",
        "bid_restriction",
    }


def sw_output_reuse_requirements(text: str) -> set[str]:
    source = str(text or "")
    compact = compact_for_match(source)
    matched: set[str] = set()

    if has_ip_ownership_requirement(compact):
        matched.add("ip_ownership")
    if has_export_allowed_requirement(compact):
        matched.add("export_allowed")
    if has_export_request_requirement(compact):
        matched.add("export_request")
    if has_sw_output_context(compact) and has_secret_removal_requirement(compact):
        matched.add("secret_removal")
    if has_sw_output_context(compact) and has_confirmation_letter_requirement(compact):
        matched.add("confirmation_letter")
    if has_sw_output_context(compact) and has_third_party_approval_requirement(compact):
        matched.add("third_party_approval")
    if has_sw_output_context(compact) and has_bid_restriction_requirement(compact):
        matched.add("bid_restriction")
    return matched


def has_ip_ownership_requirement(compact_text: str) -> bool:
    has_ip = "지식재산권" in compact_text or "계약목적물" in compact_text
    has_joint = any(term in compact_text for term in ["공동소유", "공동으로소유", "공동귀속"]) or (
        "공동" in compact_text and any(term in compact_text for term in ["활용", "소유", "귀속"])
    )
    has_owner = "귀속" in compact_text and any(term in compact_text for term in ["발주기관", "주관기관", "계약상대자"])
    return has_ip and (has_joint or has_owner)


def has_export_allowed_requirement(compact_text: str) -> bool:
    has_output = has_sw_output_term(compact_text)
    return has_output and "반출" in compact_text and any(term in compact_text for term in ["요청할수", "가능", "제공", "반출할수"])


def has_export_request_requirement(compact_text: str) -> bool:
    has_output = has_sw_output_term(compact_text)
    return has_output and "반출" in compact_text and any(term in compact_text for term in ["요청", "절차", "검토", "통보"])


def has_secret_removal_requirement(compact_text: str) -> bool:
    if "누출금지정보" not in compact_text:
        return False
    positive_terms = ["삭제하고", "삭제후", "삭제한후", "삭제하여", "삭제해야", "삭제하여야", "제거하고", "제거하여"]
    return any(term in compact_text for term in positive_terms)


def has_confirmation_letter_requirement(compact_text: str) -> bool:
    if "확약서" not in compact_text or not any(term in compact_text for term in ["제출", "제시"]):
        return False
    return "대표명의" in compact_text or "대표자명의" in compact_text or (
        "공급자" in compact_text and any(term in compact_text for term in ["명의", "대표"])
    )


def has_third_party_approval_requirement(compact_text: str) -> bool:
    if "제3자" not in compact_text:
        return False
    return "사전승인" in compact_text or "사전승낙" in compact_text or "발주기관의승인" in compact_text


def has_bid_restriction_requirement(compact_text: str) -> bool:
    if "입찰참가자격" not in compact_text or "제한" not in compact_text:
        return False
    has_bad_act = any(
        term in compact_text
        for term in ["무단유출", "무단으로유출", "누출되는경우", "누출금지정보를삭제하지", "삭제하지않고활용"]
    )
    return has_bad_act and has_sw_output_term(compact_text)


def has_sw_output_term(compact_text: str) -> bool:
    normalized = compact_text.replace("S/W", "SW")
    return "SW산출물" in normalized or "소프트웨어산출물" in normalized or "계약산출물" in normalized


def has_sw_output_context(compact_text: str) -> bool:
    context_terms = [
        "SW사업산출물활용보장",
        "계약목적물",
        "계약산출물",
        "지식재산권",
        "계약상대자",
        "공급자",
        "활용승인",
    ]
    return has_sw_output_term(compact_text) or any(term in compact_text for term in context_terms)


def select_sw_output_reuse_evidence_pages(
    candidates: list[tuple[CandidatePage, set[str]]],
    required: set[str],
) -> list[tuple[int, str]]:
    dense_candidates = [
        (page, matched)
        for page, matched in candidates
        if len(matched) >= 4 and has_direct_sw_output_section_signal(page.page_text, matched)
    ]
    complete_candidates = [
        (page, matched)
        for page, matched in dense_candidates
        if required.issubset(matched)
    ]
    if complete_candidates:
        page, matched = sorted(
            complete_candidates,
            key=lambda item: (-sw_output_reuse_page_score(item[0], item[1]), item[0].page_no),
        )[0]
        return [(rfp_display_page_no(page), sw_output_reuse_evidence_window(page.page_text, matched))]

    selected: list[tuple[CandidatePage, set[str]]] = []
    selected_covered: set[str] = set()
    ordered_candidates = sorted(
        candidates,
        key=lambda item: (
            0 if item in dense_candidates else 1,
            -sw_output_reuse_page_score(item[0], item[1]),
            item[0].page_no,
        ),
    )
    for page, matched in ordered_candidates:
        missing = matched - selected_covered
        if not missing:
            continue
        selected.append((page, matched))
        selected_covered.update(matched)
        if required.issubset(selected_covered):
            break

    if not required.issubset(selected_covered):
        return []

    return [
        (rfp_display_page_no(page), sw_output_reuse_evidence_window(page.page_text, matched))
        for page, matched in sorted(selected, key=lambda item: item[0].page_no)
    ]


def has_direct_sw_output_section_signal(text: str, matched: set[str]) -> bool:
    compact = compact_for_match(text)
    if "SW사업산출물활용보장" in compact:
        return True
    if "산출물활용" in compact and "지식재산권" in compact:
        return True
    return {"ip_ownership", "export_allowed"}.issubset(matched) and (
        "계약목적물" in compact or "계약산출물" in compact or "계약상대자" in compact or "공급자" in compact
    )


def sw_output_reuse_page_score(page: CandidatePage, matched: set[str]) -> int:
    compact = compact_for_match(page.page_text)
    score = len(matched) * 10
    if "SW사업산출물활용보장" in compact:
        score += 20
    if "산출물활용" in compact:
        score += 8
    if "계약목적물" in compact or "계약산출물" in compact:
        score += 6
    if "제재요건" in compact:
        score += 4
    return score


def sw_output_reuse_evidence_window(text: str, matched: set[str]) -> str:
    keyword_by_requirement = [
        ("ip_ownership", "지식재산권"),
        ("export_allowed", "산출물"),
        ("export_request", "반출"),
        ("secret_removal", "누출금지"),
        ("confirmation_letter", "확약서"),
        ("third_party_approval", "제3자"),
        ("bid_restriction", "입찰참가자격"),
    ]
    for requirement, keyword in keyword_by_requirement:
        if requirement in matched and loose_contains(text, keyword):
            return evidence_window(text, keyword, radius=420)
    return evidence_window(text, "", radius=420)


def best_sw_output_reuse_partial_evidence(pages: list[CandidatePage]) -> list[tuple[int, str]]:
    candidates: list[tuple[CandidatePage, set[str]]] = []
    for page in pages:
        if page.has_toc_candidate:
            continue
        matched = sw_output_reuse_requirements(page.page_text)
        if not matched:
            continue
        if len(matched) >= 3 and has_direct_sw_output_section_signal(page.page_text, matched):
            candidates.append((page, matched))
    if not candidates:
        return []
    page, matched = sorted(
        candidates,
        key=lambda item: (-sw_output_reuse_page_score(item[0], item[1]), item[0].page_no),
    )[0]
    return [(rfp_display_page_no(page), sw_output_reuse_evidence_window(page.page_text, matched))]


def evidence_for_keywords(pages: list[CandidatePage], keywords: list[str], radius: int = 80) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for page in pages:
        if page.has_toc_candidate:
            continue
        for keyword in keywords:
            if keyword and loose_contains(page.page_text, keyword):
                hits.append((rfp_display_page_no(page), evidence_window(page.page_text, keyword, radius=radius)))
                break
    return hits


def evidence_for_requirement_detail_structure(pages: list[CandidatePage]) -> list[tuple[int, str]]:
    detail_hits: list[tuple[int, str]] = []
    summary_hits: list[tuple[int, str]] = []
    for page in pages:
        if page.has_toc_candidate:
            continue
        text = page.page_text
        has_summary = "요구사항 총괄표" in text and count_present(
            text,
            [
                "기능 요구사항",
                "성능 요구사항",
                "데이터 요구사항",
                "보안 요구사항",
                "품질 요구사항",
                "제약사항",
                "프로젝트관리 요구사항",
                "프로젝트지원 요구사항",
            ],
        ) >= 4
        has_detail = count_present(
            text,
            ["요구사항 고유번호", "요구사항 명칭", "정의", "상세 세부내용", "산출정보"],
        ) >= 4
        if has_detail:
            keyword = "요구사항 상세 내역" if "요구사항 상세 내역" in text else "요구사항 고유번호"
            detail_hits.append((rfp_display_page_no(page), evidence_window(text, keyword)))
        elif has_summary:
            summary_hits.append((rfp_display_page_no(page), evidence_window(text, "요구사항 총괄표")))
    return detail_hits or summary_hits


def count_present(text: str, keywords: list[str]) -> int:
    return sum(1 for keyword in keywords if loose_contains(text, keyword))


def rfp_display_page_no(page: CandidatePage) -> int:
    if page.rfp_printed_page_no is not None:
        return page.rfp_printed_page_no
    matches = re.findall(r"(?:^|\n)\s*-\s*(\d{1,4})\s*-\s*$", page.page_text or "")
    if matches:
        return int(matches[-1])
    return page.page_no


def best_rag_keyword_match(pages: list[CandidatePage], rag: RagContext) -> dict[str, object] | None:
    best: dict[str, object] | None = None
    for hit in rag.hits:
        criteria_text = " ".join(part for part in [hit.title, hit.snippet] if part)
        criteria_tokens = content_tokens(criteria_text)
        if len(criteria_tokens) < 3:
            continue
        criteria_set = set(criteria_tokens)
        for page in pages:
            if page.has_toc_candidate:
                continue
            page_set = set(content_tokens(page.page_text))
            overlap = sorted(criteria_set.intersection(page_set))
            coverage = len(overlap) / len(criteria_set)
            if best is None or coverage > float(best["coverage"]):
                keyword = overlap[0] if overlap else ""
                best = {
                    "coverage": coverage,
                    "page_no": rfp_display_page_no(page),
                    "evidence": evidence_window(page.page_text, keyword) if keyword else page.page_text[:180],
                    "matched_tokens": overlap,
                }
    return best


def content_tokens(text: str) -> list[str]:
    tokens = []
    for token in TOKEN_RE.findall(text):
        normalized = token.strip().lower()
        if len(normalized) < 2 or normalized in STOPWORDS:
            continue
        tokens.append(normalized)
    return tokens


def evidence_window(text: str, keyword: str, radius: int = 80) -> str:
    span = loose_find_span(text, keyword) if keyword else None
    if span is None:
        return re.sub(r"\s+", " ", text).strip()[:180]
    idx, end_idx = span
    start = max(0, idx - radius)
    end = min(len(text), end_idx + radius)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def loose_contains(text: str, keyword: str) -> bool:
    return loose_find_span(text, keyword) is not None


def loose_find_span(text: str, keyword: str) -> tuple[int, int] | None:
    compact_text_value, index_map = compact_with_index_map(text)
    compact_keyword = compact_for_match(keyword)
    if not compact_keyword:
        return None
    compact_idx = compact_text_value.lower().find(compact_keyword.lower())
    if compact_idx < 0:
        return None
    start = index_map[compact_idx]
    end = index_map[compact_idx + len(compact_keyword) - 1] + 1
    return start, end


def compact_for_match(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def compact_with_index_map(text: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    index_map: list[int] = []
    for idx, char in enumerate(str(text or "")):
        if char.isspace():
            continue
        chars.append(char)
        index_map.append(idx)
    return "".join(chars), index_map
