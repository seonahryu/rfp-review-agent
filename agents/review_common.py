from __future__ import annotations

import re
from dataclasses import dataclass

from agents.models import CandidatePage, FinalReview


MANUAL_ATTACHMENT_ITEMS = {"2", "15", "17"}


@dataclass(frozen=True)
class AmountEvidence:
    page_no: int
    amount_won: int
    raw_text: str
    context: str


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def display_page_no(page: CandidatePage) -> int:
    return page.rfp_printed_page_no or page.page_no


def find_project_amount_evidence(pages: list[CandidatePage], threshold_won: int = 0) -> AmountEvidence | None:
    candidates: list[AmountEvidence] = []
    keywords = ["총사업금액", "총 사업금액", "사업금액", "사업 금액", "사업예산", "사업 예산", "추정가격", "예산"]
    for page in pages:
        if page.has_toc_candidate:
            continue
        source = str(page.page_text or "")
        for match in re.finditer(r"[\d,]+(?:\.\d+)?\s*(?:억원|억|천만원|천만|백만원|백만|만원|원)", source):
            start = max(0, match.start() - 90)
            end = min(len(source), match.end() + 90)
            context = source[start:end]
            if not any(keyword in context for keyword in keywords):
                continue
            amount = parse_korean_amount(match.group(0))
            if amount >= threshold_won:
                candidates.append(
                    AmountEvidence(
                        page_no=display_page_no(page),
                        amount_won=amount,
                        raw_text=match.group(0).strip(),
                        context=" ".join(context.split()),
                    )
                )
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.amount_won)


def parse_korean_amount(value: str) -> int:
    compact = str(value or "").replace(",", "").replace(" ", "")
    number_match = re.search(r"\d+(?:\.\d+)?", compact)
    if not number_match:
        return 0
    number = float(number_match.group(0))
    if "억원" in compact or "억" in compact:
        return int(number * 100_000_000)
    if "천만원" in compact or "천만" in compact:
        return int(number * 10_000_000)
    if "백만원" in compact or "백만" in compact:
        return int(number * 1_000_000)
    if "만원" in compact:
        return int(number * 10_000)
    if "원" in compact:
        return int(number)
    return 0


def format_amount_억원(amount_won: int) -> str:
    value = amount_won / 100_000_000
    if value.is_integer():
        return f"{int(value)}억 원"
    return f"{value:.1f}".rstrip("0").rstrip(".") + "억 원"


def has_commercial_sw_purchase_signal(pages: list[CandidatePage]) -> bool:
    for page in pages:
        if page.has_toc_candidate:
            continue
        compact = compact_text(page.page_text)
        if any(term in compact for term in ["상용SW구매내용은없음", "상용소프트웨어구매내용은없음", "상용SW없음", "상용소프트웨어없음"]):
            continue
        if any(term in compact for term in ["상용SW", "상용소프트웨어"]) and any(
            term in compact for term in ["직접구매", "분리발주", "구매"]
        ):
            if not any(term in compact for term in ["상용SW없음", "상용소프트웨어없음", "해당없음", "미포함"]):
                return True
    return False


def target_basis_sentence(item_no: str, pages: list[CandidatePage]) -> str:
    amount = find_project_amount_evidence(pages)
    if amount is None:
        return ""
    if str(item_no) == "2":
        return (
            f"대상: p.{amount.page_no}에 근거하여 총 사업금액 {format_amount_억원(amount.amount_won)}임이 확인되어, "
            "총 사업금액 3억원 이상이면서 직접구매 대상 상용SW를 구매하는 사업으로 볼 근거가 확인되었습니다."
        )
    if str(item_no) == "13":
        return (
            f"대상: p.{amount.page_no}에 근거하여 총 사업금액 {format_amount_억원(amount.amount_won)}임이 확인되어, "
            "제안서 보상 대상 여부 판단에 필요한 사업금액 근거가 확인되었습니다."
        )
    if str(item_no) == "18":
        return (
            f"대상: p.{amount.page_no}에 근거하여 총 사업금액 {format_amount_억원(amount.amount_won)}임이 확인되어, "
            "SW사업정보 제출 대상 여부 판단에 필요한 사업예산 근거가 확인되었습니다."
        )
    return (
        f"대상: p.{amount.page_no}에 근거하여 총 사업금액 {format_amount_억원(amount.amount_won)}임이 확인되어, "
        "대상 여부 판단에 필요한 사업금액 근거가 확인되었습니다."
    )


def apply_target_basis(review: FinalReview, pages: list[CandidatePage]) -> None:
    if review.is_target is not True:
        return
    if str(review.item_no) not in {"2", "13", "18"}:
        return
    sentence = target_basis_sentence(str(review.item_no), pages)
    if not sentence or sentence in str(review.reason or ""):
        return
    review.reason = f"{sentence}\n{review.reason}".strip()


def is_allowed_subcontract_evidence_page(page: CandidatePage) -> bool:
    compact = compact_text(page.page_text)
    if page.has_toc_candidate:
        return False
    if any(marker in compact for marker in ["서식", "별지", "붙임"]) and not any(
        marker in compact for marker in ["상세요구사항", "기타사항", "사업요구사항", "제안안내사항", "제안안내"]
    ):
        return False
    return True


def attachment_review_pages(item_no: str, pages: list[CandidatePage]) -> list[CandidatePage]:
    item = str(item_no)
    terms_by_item = {
        "2": ["직접구매대상상용소프트웨어구매계획", "상용소프트웨어구매계획", "상용SW직접구매"],
        "14": ["요구사항상세", "요구사항총괄표", "요구사항정의서"],
        "15": ["적정사업기간종합산정서", "사업기간종합산정서"],
        "17": ["소프트웨어사업영향평가", "SW사업영향평가", "영향평가검토결과서"],
    }
    terms = terms_by_item.get(item, [])
    hits: list[CandidatePage] = []
    for page in pages:
        compact = compact_text(page.page_text)
        if not (page.has_attachment_candidate or "붙임" in compact or "별첨" in compact or "서식" in compact):
            continue
        if any(term in compact for term in terms):
            hits.append(page)
    return hits


def manual_attachment_instruction(item_no: str, page: CandidatePage) -> str:
    page_no = display_page_no(page)
    if str(item_no) == "2":
        return f"p.{page_no}의 직접구매 대상 상용소프트웨어 구매계획 첨부파일을 확인 후 검토의견을 수정해주세요."
    if str(item_no) == "14":
        return f"p.{page_no}의 요구사항 상세/총괄 첨부파일에서 요구사항 작성 항목 누락 여부를 확인 후 검토의견을 수정해주세요."
    if str(item_no) == "15":
        return f"p.{page_no}의 적정 사업기간 종합산정서 첨부파일에서 서명 블라인드 처리 여부를 확인 후 검토의견을 수정해주세요."
    if str(item_no) == "17":
        return f"p.{page_no}의 소프트웨어사업 영향평가 검토결과서 첨부파일에서 기관장 날인 여부를 확인 후 검토의견을 수정해주세요."
    return f"p.{page_no}의 첨부파일을 육안 확인 후 검토의견을 수정해주세요."


def apply_manual_attachment_gate(review: FinalReview, pages: list[CandidatePage]) -> None:
    if str(review.item_no) not in MANUAL_ATTACHMENT_ITEMS:
        return
    if str(review.item_no) in {"15", "17"} and str(review.final_result).strip() != "준수":
        return
    hits = attachment_review_pages(str(review.item_no), pages)
    if not hits:
        return
    first = hits[0]
    instruction = manual_attachment_instruction(str(review.item_no), first)
    review.final_result = "확인요망"
    review.final_status = "사람 확인 필요"
    review.is_target = True if review.is_target is not False else review.is_target
    review.evidence_pages = [display_page_no(page) for page in hits[:3]]
    review.evidence_text = [page.page_text[:260] for page in hits[:3]]
    review.reason = f"{review.reason}\n{instruction}".strip()
    review.recommendation = instruction
    if "attachment_manual_review_required" not in review.warnings:
        review.warnings.append("attachment_manual_review_required")


def postprocess_final_review(review: FinalReview, pages: list[CandidatePage]) -> FinalReview:
    apply_target_basis(review, pages)
    apply_manual_attachment_gate(review, pages)
    return review
