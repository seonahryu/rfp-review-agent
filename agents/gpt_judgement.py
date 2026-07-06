from __future__ import annotations

import json
import os
import re

from agents.models import CandidatePage, RagContext, ReviewResult


ROLE_GUIDANCE = {
    "rule": "문장형 법제도 기준의 의미 충족 여부를 판정한다.",
    "table": "평가표, 배점, 정량/정성 평가항목, 하도급계획 적정성 등 표 기반 기준을 중점 판정한다.",
    "attachment": "첨부, 별첨, 제안서 작성요령, 블라인드, 상용SW 직접구매 등 첨부/서식 기반 기준을 중점 판정한다.",
    "general": "문서 전체 맥락에서 일반 법제도 검토항목의 충족 여부를 판정한다.",
}


ITEM_8_COMMON_STATEMENT = (
    "「(계약예규) 용역계약일반조건」 제58조 제2항과 제3항에 따라, 정한 기한내에 하자가 발생하여 "
    "발주기관이 하자보수를 계약상대자에게 요청한 경우 하자를 조치하여야 함, 단 제58조 제2항 각 호의 경우는 "
    "유상 유지보수 또는 재개발로 봄, 또한 계약상대자는 제58조 제3항에 각호의 어느 하나의 사유로 인하여 "
    "발생한 하자에는 하자보수의 책임이 없음"
)


def gpt_review(
    *,
    llm_client: object,
    model_role: str,
    item_no: str,
    route_type: str,
    pages: list[CandidatePage],
    rag: RagContext,
) -> ReviewResult | None:
    if not getattr(llm_client, "is_configured", lambda: False)():
        return None
    data = llm_client.json_response(
        build_system_prompt(model_role),
        build_user_prompt(model_role, item_no, pages, rag),
        model_role=model_role,
        temperature=0,
    )
    evidence_text = [str(x) for x in data.get("evidence_text", [])]
    review = ReviewResult(
        item_no=str(item_no),
        route_type=route_type,
        result=normalize_result(data.get("result")),
        is_target=data.get("is_target"),
        confidence=float(data.get("confidence", 0.65)),
        evidence_pages=normalize_evidence_pages(data.get("evidence_pages", []), pages, evidence_text),
        evidence_text=evidence_text,
        reason=str(data.get("reason", "")),
        recommendation=str(data.get("recommendation", "")),
        needs_human_review=bool(data.get("needs_human_review", False)),
        source=f"openai_{model_role}",
        warnings=[str(x) for x in data.get("warnings", [])],
        used_llm=True,
    )
    remove_toc_evidence(review, pages)
    return keep_direct_judgement_evidence(review, rag, pages)


def build_system_prompt(model_role: str) -> str:
    return f"""당신은 RFP 법제도 검토 전문 에이전트입니다.
역할: {ROLE_GUIDANCE.get(model_role, ROLE_GUIDANCE["general"])}

RAG 기준 사용 규칙:
- rag_criteria는 법제도 판단의 기준자료입니다. 각 hit에는 item_no, 법제도명, 판단대상, legal_requirement의 모든 기준행이 포함됩니다.
- item_no가 2 또는 2-1이면 2번과 2-1번 기준을 함께 봅니다. 그 외 항목은 해당 item_no 기준만 봅니다.
- item_no가 14이면 legal_reference_example의 reference_type, reference_subtype, content도 판정 보조자료로 사용합니다.
- requirement_text는 실제 판정해야 하는 핵심 기준입니다.
- example_sentence는 참고 예시 문장입니다. RFP 문구가 example_sentence와 그대로 일치하지 않아도 됩니다.
- 다만 requirement_text에서 example_sentence에 해당하는 예시성 문장을 제외한 핵심 요건은 RFP에 의미상 80% 이상 반영되어야 합니다.
- 단, item_no가 8이고 category가 '명시'인 '공통명시' 기준은 예시 참고가 아니라 RFP에 의미상 포함되어야 하는 판정 기준입니다. 제58조 제2항·제3항에 따른 하자보수 요청 시 조치, 제58조 제2항 각 호는 유상 유지보수 또는 재개발로 본다는 점, 제58조 제3항 각 호 사유의 하자는 계약상대자 책임이 아니라는 점을 함께 확인합니다.
- case_text는 조건부 기준입니다. 해당 RFP가 그 case에 해당한다고 판단될 때만 적용합니다.
- 해당 case에 해당한다면 case_text의 취지와 의미상 80% 이상 일치하는 내용이 RFP에 있어야 합니다.

category별 판정 규칙:
- category가 '명시'이면 requirement_text의 핵심 요건이 RFP에 의미상 80% 이상 명시되어야 준수입니다.
- category가 '첨부'이면 requirement_text가 요구하는 서식, 산정서, 검토결과서, 구매계획 등 첨부/공개/제출 자료가 RFP에 포함되어야 합니다.
- category가 '첨부'이거나 agent_type이 'attachment'이면 첨부/별첨 목록, 목차, 제목, "첨부 예정" 취지의 안내, 빈 표지, 체크박스와 항목명만 있는 미작성 서식은 실제 첨부 본문으로 보지 않습니다.
- 첨부/별첨 준수는 실제 붙임 본문에 작성된 검토 결과, 산정 결과, 평가 내용, 구매계획 등 실질 내용이 확인될 때만 인정합니다.
- 별첨 목록에는 해당 자료명이 있으나 뒤쪽 별첨 본문에서 실질 내용이 없거나 미작성 양식만 있으면 미준수로 판단합니다.
- category가 '삭제'이면 requirement_text가 금지하거나 삭제하라고 한 내용이 RFP에 없어야 준수입니다.
- category가 '수정'이면 RFP의 관련 문구가 requirement_text의 취지에 맞게 수정되어 있어야 준수입니다.
- category가 비어 있거나 기타 값이면 requirement_text의 의미 충족 여부를 기준으로 판단합니다.

판정 결과 작성 규칙:
- result는 반드시 '준수', '미준수', '보완필요', '해당없음' 중 하나입니다.
- 반드시 1단계로 RFP가 해당 법제도 적용대상인지 먼저 판단합니다. target_text, case_text, 사업개요, 예산, 사업범위, 계약방식, 산정방식, 붙임/별지의 실제 내용을 함께 확인합니다.
- 2단계로 적용대상인 경우에만 requirement_text 기준의 준수/미준수/보완필요를 판단합니다.
- 적용대상 판단 근거와 준수/위반 판단 근거가 서로 다른 페이지에 있을 수 있으므로 rfp_pages 전체에서 근거를 찾습니다.
- 목차와 붙임 목록은 근거 위치를 찾기 위한 참고정보일 뿐, 그 자체만으로 준수 근거로 삼지 않습니다.
- evidence_pages에는 반드시 RFP 문서 본문 안에 자체적으로 인쇄된 쪽수(rfp_printed_page_no)를 사용합니다. PDF 파일의 물리적 페이지 순번(document_page_index)을 사용하지 않습니다.
- evidence_pages와 evidence_text에는 최종 준수/미준수/보완필요 판단의 직접 근거만 넣습니다. 적용대상 판단 페이지는 최종 판단 근거와 같은 페이지가 아니면 절대 넣지 않습니다.
- reason에는 적용대상 판단 근거를 설명할 수 있지만, evidence_pages에는 직접 준수/미준수/보완필요 근거 페이지만 사용합니다.
- 다만 result가 '해당없음'이면 적용대상이 아님을 판단한 직접 근거 페이지를 evidence_pages에 넣습니다.
- item_no가 16이면 이번 검토에서는 적용대상 여부만 판단합니다. 투입인력 요구 및 관리 금지 위반 여부, 삭제 권고, 미준수/준수 판단으로 더 들어가지 않습니다. 대상이면 is_target=true로 두고, result는 '보완필요'로 하되 reason에는 대상 여부 판단 근거만 씁니다.
- RFP에 적용대상이 아니면 '해당없음'으로 판단하고 이유를 씁니다.
- 기준은 적용되지만 근거가 부족하거나 일부만 충족하면 '보완필요'입니다.
- 명백히 기준에 반하면 '미준수'입니다.
- 준수 판단에는 RFP에서 찾은 실제 근거 문구와 페이지가 필요합니다.
- evidence_text에는 rfp_pages에서 찾은 실제 원문 근거만 넣습니다.
- recommendation은 관리자가 그대로 복사할 수 있는 한국어 문장으로 작성하되, "제안요청서 p.00" 같은 페이지 표기는 절대 넣지 않습니다. 페이지 표기는 evidence_pages만 사용하고, 보고서 문구 생성 단계에서 현재 RFP의 evidence_pages로 별도 결합합니다.
- 미준수/보완필요일 때 recommendation에는 누락되거나 보완해야 할 requirement_text, 필요한 경우 case_text 또는 example_sentence의 문구를 인용해 어떤 내용을 추가/수정/삭제/첨부해야 하는지 명시합니다.
- example_sentence는 '예시문 그대로 미기재'를 이유로 삼지 말고, 필요한 경우 권장 보완 문구로만 인용합니다.
- JSON 객체 하나만 반환합니다."""


def build_user_prompt(model_role: str, item_no: str, pages: list[CandidatePage], rag: RagContext) -> str:
    prompt_pages = select_prompt_pages(model_role, item_no, pages, rag)
    max_page_chars = int(os.getenv("RFP_GPT_PAGE_CHARS", "1800"))
    payload = {
        "item_no": item_no,
        "agent_type": model_role,
        "rag_criteria": [hit.__dict__ for hit in rag.hits[:10]],
        "rfp_pages": [
            {
                "document_page_index": page.page_no,
                "rfp_printed_page_no": rfp_printed_page_no(page),
                "page_text": trim_page_text(page.page_text, max_page_chars),
                "flags": {
                    "table": page.has_table_candidate,
                    "eval_table": page.has_eval_table_candidate,
                    "attachment": page.has_attachment_candidate,
                    "blind": page.has_blind_candidate,
                    "commercial_sw": page.has_commercial_sw_candidate,
                    "parser_warning": page.parser_warning,
                },
            }
            for page in prompt_pages
        ],
        "output_schema": {
            "result": "준수|미준수|보완필요|해당없음",
            "is_target": "boolean or null",
            "confidence": "0.0-1.0",
            "evidence_pages": ["RFP 본문에 자체 인쇄된 쪽수인 rfp_printed_page_no. document_page_index가 아님"],
            "evidence_text": ["rfp_pages에서 찾은 실제 원문 근거"],
            "reason": "판정 이유. 적용대상 여부를 먼저 판단한 근거와 requirement_text/example_sentence/case_text 해석을 포함",
            "recommendation": "관리자가 복사할 수 있는 보완 권고문. 미준수/보완필요일 때 필수",
            "needs_human_review": "boolean",
            "warnings": ["string"],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def select_prompt_pages(
    model_role: str,
    item_no: str,
    pages: list[CandidatePage],
    rag: RagContext,
) -> list[CandidatePage]:
    max_pages = int(os.getenv("RFP_GPT_MAX_PAGES", "12"))
    if len(pages) <= max_pages:
        return pages

    query_terms = {str(item_no)}
    for hit in rag.hits[:5]:
        for text in [hit.title, hit.category or "", hit.snippet]:
            query_terms.update(token.lower() for token in re.findall(r"[0-9A-Za-z가-힣]{2,}", text or "")[:12])

    scored: list[tuple[int, int, CandidatePage]] = []
    for page in pages:
        text = page.page_text or ""
        lowered = text.lower()
        score = sum(1 for term in query_terms if term and term.lower() in lowered)
        if page.has_toc_candidate:
            score -= 2
        if model_role == "table" and (page.has_eval_table_candidate or page.has_table_candidate):
            score += 8
        if model_role == "attachment" and (
            page.has_attachment_candidate or page.has_blind_candidate or page.has_commercial_sw_candidate
        ):
            score += 8
        if page.parser_warning:
            score -= 1
        if score > 0:
            scored.append((score, page.page_no, page))

    scored.sort(key=lambda item: (-item[0], item[1]))
    selected = [page for _, _, page in scored[:max_pages]]
    return selected or pages[:max_pages]


def trim_page_text(text: str, max_chars: int) -> str:
    normalized = str(text or "").strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars] + "\n[TRUNCATED]"


def rfp_printed_page_no(page: CandidatePage) -> int | None:
    if page.rfp_printed_page_no is not None:
        return page.rfp_printed_page_no
    matches = re.findall(r"(?:^|\n)\s*-\s*(\d{1,4})\s*-\s*$", page.page_text or "")
    return int(matches[-1]) if matches else None


def normalize_evidence_pages(
    values: object,
    pages: list[CandidatePage],
    evidence_texts: list[str] | None = None,
) -> list[int]:
    index_to_printed = {
        page.page_no: printed
        for page in pages
        if (printed := rfp_printed_page_no(page)) is not None
    }
    printed_pages = set(index_to_printed.values())
    result: list[int] = []
    for evidence_text in evidence_texts or []:
        matched_page = find_page_for_evidence_text(evidence_text, pages)
        if matched_page is not None:
            printed = rfp_printed_page_no(matched_page)
            if printed is not None and printed not in result:
                result.append(printed)
    for value in values or []:
        text = str(value).strip()
        if not text.isdigit():
            continue
        page_no = int(text)
        if page_no in printed_pages:
            normalized = page_no
        elif page_no in index_to_printed:
            normalized = index_to_printed[page_no]
        else:
            normalized = page_no
        if normalized not in result:
            result.append(normalized)
    return result


def find_page_for_evidence_text(evidence_text: str, pages: list[CandidatePage]) -> CandidatePage | None:
    normalized_evidence = normalize_for_search(evidence_text)
    if len(normalized_evidence) < 20:
        return None
    for page in pages:
        page_text = normalize_for_search(page.page_text)
        if normalized_evidence[:180] in page_text:
            return page
    chunks = [normalized_evidence[idx : idx + 80] for idx in range(0, max(len(normalized_evidence) - 80, 0), 80)]
    best: tuple[int, CandidatePage] | None = None
    for page in pages:
        page_text = normalize_for_search(page.page_text)
        score = sum(1 for chunk in chunks[:8] if chunk and chunk in page_text)
        if score and (best is None or score > best[0]):
            best = (score, page)
    return best[1] if best else None


def normalize_for_search(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def remove_toc_evidence(review: ReviewResult, pages: list[CandidatePage]) -> None:
    if not pages or str(review.result).strip() == "해당없음":
        return
    toc_page_numbers: set[int] = set()
    for page in pages:
        if not page.has_toc_candidate:
            continue
        toc_page_numbers.add(page.page_no)
        printed = rfp_printed_page_no(page)
        if printed is not None:
            toc_page_numbers.add(printed)

    if not toc_page_numbers:
        return

    kept: list[tuple[int, str]] = []
    for idx, page_no in enumerate(review.evidence_pages):
        text = review.evidence_text[idx] if idx < len(review.evidence_text) else ""
        if page_no in toc_page_numbers:
            continue
        kept.append((page_no, text))

    review.evidence_pages = [page for page, _ in kept]
    review.evidence_text = [text for _, text in kept]


def keep_direct_judgement_evidence(
    review: ReviewResult,
    rag: RagContext | None = None,
    pages: list[CandidatePage] | None = None,
) -> ReviewResult:
    item_no = str(review.item_no)
    if item_no == "16":
        review.result = "보완필요" if review.is_target is not False else "해당없음"
        review.recommendation = ""
        return review

    item_predicates = {
        "5": is_item_5_direct_evidence,
        "8": is_item_8_direct_evidence,
        "9": is_item_9_direct_evidence,
        "10": is_item_10_direct_evidence,
        "13": is_item_13_direct_evidence,
    }
    predicate = item_predicates.get(item_no)
    direct_terms = direct_requirement_terms(rag)
    scanned = find_direct_evidence_pages(item_no, pages or [], predicate, direct_terms)
    if scanned:
        review.evidence_pages = [page for page, _ in scanned]
        review.evidence_text = [text for _, text in scanned]
        enforce_item_5_missing_requirements(review)
        enforce_item_8_period_requirement(review)
        return review
    if str(review.result).strip() == "해당없음":
        return review

    pairs = list(zip(review.evidence_pages, review.evidence_text))
    kept = []
    for page, text in pairs:
        if predicate is not None:
            if predicate(text):
                kept.append((page, text))
            continue
        if is_target_only_evidence(text) and not has_direct_requirement_signal(text, direct_terms):
            continue
        kept.append((page, text))

    if item_no == "10":
        primary = [(page, text) for page, text in kept if is_item_10_direct_evidence(text)]
        if primary:
            kept = primary[:1]
        elif kept:
            kept = kept[:1]
    if not kept and item_no == "9":
        review.evidence_pages = []
        review.evidence_text = []
        return review
    if not kept:
        return review
    review.evidence_pages = [page for page, _ in kept]
    review.evidence_text = [text for _, text in kept]
    enforce_item_5_missing_requirements(review)
    enforce_item_8_period_requirement(review)
    return review


def find_direct_evidence_pages(
    item_no: str,
    pages: list[CandidatePage],
    predicate,
    direct_terms: set[str],
) -> list[tuple[int, str]]:
    if not pages:
        return []
    matches: list[tuple[int, str]] = []
    for page in pages:
        printed = rfp_printed_page_no(page)
        if printed is None:
            continue
        text = page.page_text
        if predicate is not None:
            if predicate(text):
                matches.append((printed, compact_page_evidence(text, item_no)))
            continue
        if page.has_toc_candidate:
            continue
        if is_target_only_evidence(text):
            continue
        if has_direct_requirement_signal(text, direct_terms):
            matches.append((printed, compact_page_evidence(text, item_no)))
    return prioritize_direct_matches(item_no, matches)


def prioritize_direct_matches(item_no: str, matches: list[tuple[int, str]]) -> list[tuple[int, str]]:
    if not matches:
        return []
    if item_no == "10":
        primary = [match for match in matches if is_item_10_direct_evidence(match[1])]
        return (primary or matches)[:1]
    if item_no == "8":
        return prioritize_item_8_matches(matches)
    if item_no == "13":
        return matches
    return matches


def prioritize_item_8_matches(matches: list[tuple[int, str]]) -> list[tuple[int, str]]:
    return matches


def item_8_evidence_aspects(text: str) -> set[str]:
    compact = "".join(str(text or "").split())
    aspects: set[str] = set()
    if any(term in compact for term in ["책임기간", "하자담보책임기간", "하자보수기간"]):
        aspects.add("period")
    if any(term in compact for term in ["제58조", "하자보수를요청", "하자를조치", "하자담보책임"]):
        aspects.add("responsibility_scope")
    if any(term in compact for term in ["유상유지보수", "재개발", "무상업그레이드", "유지관리"]):
        aspects.add("scope_limit")
    if "유지보수" in compact and "하자보수" in compact:
        aspects.add("terminology")
    return aspects


def compact_page_evidence(text: str, item_no: str) -> str:
    keywords = {
        "5": ["작업장소", "원격지", "보안요구사항", "사업예산 내 계상"],
        "8": ["하자담보", "하자보수", "책임기간"],
        "10": ["사업자 선정 방법", "낙찰자 결정방법", "협상에 의한 계약", "협상에 의한 계약체결"],
        "13": ["제안서 보상", "보상대상"],
    }.get(item_no, [])
    for keyword in keywords:
        if keyword in text:
            return evidence_window(text, keyword, radius=360)
    return re.sub(r"\s+", " ", str(text or "")).strip()[:500]


def evidence_window(text: str, keyword: str, radius: int = 260) -> str:
    idx = str(text or "").find(keyword)
    if idx < 0:
        return re.sub(r"\s+", " ", str(text or "")).strip()[:500]
    start = max(0, idx - radius)
    end = min(len(text), idx + len(keyword) + radius)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def direct_requirement_terms(rag: RagContext | None) -> set[str]:
    if rag is None:
        return set()
    text_parts = []
    for hit in rag.hits[:5]:
        snippet = hit.snippet or ""
        if "[REQUIRED_CRITERIA]" in snippet:
            snippet = snippet.split("[REQUIRED_CRITERIA]", 1)[1]
        text_parts.append(hit.title or "")
        text_parts.append(snippet)
    text = " ".join(text_parts)
    raw_terms = re.findall(r"[0-9A-Za-z가-힣]{2,}", text)
    stopwords = {
        "관련",
        "검토",
        "기준",
        "내용",
        "사업",
        "경우",
        "또는",
        "따라",
        "대한",
        "제안요청서",
        "하여야",
        "합니다",
        "명시",
        "여부",
        "대상",
    }
    return {term for term in raw_terms if term not in stopwords}


def has_direct_requirement_signal(text: str, direct_terms: set[str]) -> bool:
    if not direct_terms:
        return False
    compact = str(text or "")
    matched = [term for term in direct_terms if term in compact]
    return len(matched) >= 2


def is_target_only_evidence(text: str) -> bool:
    compact = "".join(str(text or "").split())
    target_markers = [
        "사업명",
        "사업기간",
        "사업예산",
        "총사업금액",
        "사업금액",
        "사업목적",
        "사업개요",
        "부가가치세",
        "기능점수",
        "FP",
        "사업대가",
        "개발사업",
        "재개발",
    ]
    direct_markers = [
        "하자담보",
        "하자보수",
        "협상에의한계약",
        "제안서보상",
        "보상대상",
        "작업장소",
        "원격지",
        "특정규격",
        "상표",
        "모델명",
        "중소소프트웨어사업자",
        "중소SW사업자",
        "대기업",
        "중견기업",
        "입찰참여",
        "산출물",
        "영향평가",
        "SW사업정보",
        "소프트웨어사업정보",
    ]
    return any(marker in compact for marker in target_markers) and not any(
        marker in compact for marker in direct_markers
    )


def is_item_8_direct_evidence(text: str) -> bool:
    compact = "".join(str(text or "").split())
    if looks_like_requirement_overview_for_item_8(compact):
        return False
    if looks_like_bidder_plan_or_evaluation_for_item_8(compact):
        return False
    if looks_like_blank_form_for_item_8(compact):
        return False
    if looks_like_joint_contract_form_for_item_8(compact):
        return False
    has_warranty_topic = any(term in compact for term in ["하자담보", "하자보수", "용역계약일반조건"])
    has_responsibility_context = any(term in compact for term in ["책임기간", "책임", "기간", "제58조"])
    return has_warranty_topic and has_responsibility_context


def looks_like_requirement_overview_for_item_8(compact: str) -> bool:
    requirement_codes = re.findall(r"[A-Z]{2,5}-\d{3}", compact, flags=re.IGNORECASE)
    if len(set(requirement_codes)) >= 3 and "하자보수" in compact:
        return True
    return "요구사항총괄표" in compact and "하자보수" in compact


def looks_like_bidder_plan_or_evaluation_for_item_8(compact: str) -> bool:
    if "하자보수계획" not in compact:
        return False
    proposal_markers = ["제시하여야", "제시하였는지", "제안서", "기술평가", "평가한다", "적정성", "평가항목"]
    return any(marker in compact for marker in proposal_markers)


def looks_like_blank_form_for_item_8(compact: str) -> bool:
    form_markers = ["서식", "별지", "자기평가표", "210mm×297mm", "백상지"]
    if not any(marker in compact for marker in form_markers):
        return False
    field_markers = ["사업명", "계약기간", "계약금액", "하도급", "하자담보책임기간"]
    return sum(1 for marker in field_markers if marker in compact) >= 3


def looks_like_joint_contract_form_for_item_8(compact: str) -> bool:
    joint_markers = ["공동수급체", "공동수급협정", "출자비율", "구성원"]
    if sum(1 for marker in joint_markers if marker in compact) < 2:
        return False
    return "하자담보책임" in compact and "공사" in compact


def enforce_item_8_period_requirement(review: ReviewResult) -> None:
    if str(review.item_no) != "8":
        return
    if str(review.result).strip() != "준수":
        return
    evidence = " ".join(str(text or "") for text in review.evidence_text)
    missing_requirements = item_8_missing_requirements(evidence)
    if not missing_requirements:
        return
    review.result = "보완필요"
    review.reason = item_8_missing_reason(missing_requirements)
    review.recommendation = item_8_missing_recommendation(missing_requirements)
    for warning in item_8_missing_warnings(missing_requirements):
        if warning not in review.warnings:
            review.warnings.append(warning)


def item_8_missing_requirements(text: str) -> set[str]:
    missing: set[str] = set()
    if not has_item_8_valid_period(text):
        missing.add("period")
    if not has_item_8_common_statement(text):
        missing.add("common_statement")
    return missing


def item_8_missing_reason(missing: set[str]) -> str:
    if missing == {"period"}:
        return "하자담보 책임 관련 내용은 확인되나, 하자담보 책임기간이 미작성되어 있습니다."
    if missing == {"common_statement"}:
        return "하자담보 책임기간은 확인되나, 용역계약일반조건 제58조 제2항·제3항에 따른 하자보수 조치 및 책임 범위에 관한 공통명시 내용이 미작성되어 있습니다."
    return "하자담보 책임 관련 내용은 일부 확인되나, 하자담보 책임기간 및 용역계약일반조건 제58조 제2항·제3항에 따른 공통명시 내용이 미작성되어 있습니다."


def item_8_missing_recommendation(missing: set[str]) -> str:
    recommendations: list[str] = []
    if "period" in missing:
        recommendations.append("SW 하자담보 책임기간을 ‘1년’ 또는 ‘1년 이내’로 명시")
    if "common_statement" in missing:
        recommendations.append(f"{ITEM_8_COMMON_STATEMENT}을 명시")
    return " 및 ".join(recommendations) + "하시기 바랍니다."


def item_8_missing_warnings(missing: set[str]) -> list[str]:
    warnings: list[str] = []
    if "period" in missing:
        warnings.append("item_8_missing_valid_warranty_period")
    if "common_statement" in missing:
        warnings.append("item_8_missing_common_statement")
    return warnings


def has_item_8_valid_period(text: str) -> bool:
    compact = "".join(str(text or "").split())
    has_period_context = any(term in compact for term in ["책임기간", "하자담보책임기간", "하자보수기간"])
    has_allowed_period = any(term in compact for term in ["1년이내", "1년", "12개월"])
    return has_period_context and has_allowed_period


def has_item_8_common_statement(text: str) -> bool:
    compact = "".join(str(text or "").split())
    has_basis = "제58조" in compact or "용역계약일반조건" in compact
    has_repair_action = any(term in compact for term in ["하자보수를요청", "하자보수요청", "하자를조치"])
    has_paid_maintenance = any(term in compact for term in ["유상유지보수", "유상유지관리", "재개발"])
    has_responsibility_exclusion = any(
        term in compact
        for term in ["하자보수의책임이없", "하자보수책임이없", "책임이없", "책임없"]
    )
    return has_basis and has_repair_action and has_paid_maintenance and has_responsibility_exclusion


def is_item_5_direct_evidence(text: str) -> bool:
    compact = "".join(str(text or "").split())
    if "작업장소" not in compact and "원격지" not in compact:
        return False
    work_place = any(term in compact for term in ["상호협의", "사업예산내계상", "관련비용", "제안가격"])
    remote_procedure = any(term in compact for term in ["원격지개발", "개발방법", "구체적인방안", "발주기관의검토"])
    security = any(term in compact for term in ["보안요구사항", "보안관리", "보안대책", "출입보안", "출입통제"])
    return work_place or remote_procedure or security


def enforce_item_5_missing_requirements(review: ReviewResult) -> None:
    if str(review.item_no) != "5":
        return
    if str(review.result).strip() == "준수":
        return
    evidence = " ".join(str(text or "") for text in review.evidence_text)
    missing = item_5_missing_requirements(evidence)
    if not missing:
        return
    review.recommendation = item_5_missing_recommendation(missing)


def item_5_missing_requirements(text: str) -> set[str]:
    compact = "".join(str(text or "").split())
    missing: set[str] = set()
    has_workplace_agreement = "작업장소" in compact and any(term in compact for term in ["협의", "상호협의", "결정"])
    has_cost_accounting = "작업장소" in compact and any(
        term in compact for term in ["비용", "사업예산", "계상", "제안가격", "제안사가부담"]
    )
    has_supplier_review = any(term in compact for term in ["공급자", "계약상대자", "제안사"]) and any(
        term in compact for term in ["작업장소를제시", "작업장소제시", "제시된작업장소", "우선검토", "검토절차"]
    )
    has_remote_security = any(term in compact for term in ["원격개발", "원격지"]) and any(
        term in compact for term in ["보안사고", "위험요인", "대응방안", "보안요구사항"]
    )
    if not (has_workplace_agreement and has_cost_accounting):
        missing.add("workplace_cost")
    if not has_supplier_review:
        missing.add("supplier_review")
    if not has_remote_security:
        missing.add("remote_security")
    return missing


def item_5_missing_recommendation(missing: set[str]) -> str:
    parts: list[str] = []
    if "workplace_cost" in missing:
        parts.append("작업장소 상호협의 또는 제공여부와 작업장소 관련 비용 계상 여부를 명시")
    if "supplier_review" in missing:
        parts.append("공급자가 작업장소를 제시할 수 있는 절차와 발주기관의 검토절차를 명시")
    if "remote_security" in missing:
        parts.append("원격개발에 따른 보안사고 등 위험요인 식별 및 대응방안 제시 요구사항을 명시")
    return "제안요청서에 " + "하고, ".join(parts) + "하시기 바랍니다."


def is_item_9_direct_evidence(text: str) -> bool:
    compact = "".join(str(text or "").split())
    has_specific_spec_topic = any(
        term in compact
        for term in ["특정규격", "특정상표", "특정모델", "특정제품", "특정회사", "모델명"]
    )
    has_prohibition_context = any(
        term in compact
        for term in ["금지", "명시금지", "지정하여", "동등이상", "입찰에부치는경우"]
    )
    return has_specific_spec_topic and has_prohibition_context


def is_item_10_direct_evidence(text: str) -> bool:
    compact = "".join(str(text or "").split())
    has_contract_method = "협상에의한계약" in compact or "협상에의한계약체결" in compact
    has_selection_context = any(
        term in compact
        for term in ["사업자선정방법", "낙찰자결정방법", "협상적격자", "계약체결기준", "계약체결방법"]
    )
    has_legal_basis = any(term in compact for term in ["제49조", "시행령제44조", "제44조제1항"])
    has_application = any(term in compact for term in ["방법을적용", "적용한다", "체결방법"])
    return has_contract_method and (has_selection_context or (has_legal_basis and has_application))


def is_item_13_direct_evidence(text: str) -> bool:
    compact = str(text or "")
    return "제안서 보상" in compact or "보상대상" in compact


def normalize_result(value: object) -> str:
    text = str(value or "").strip()
    aliases = {
        "적합": "준수",
        "충족": "준수",
        "비대상": "해당없음",
        "해당 없음": "해당없음",
        "근거부족": "보완필요",
        "확인필요": "보완필요",
        "부분준수": "보완필요",
        "불충족": "미준수",
    }
    if text in {"준수", "미준수", "보완필요", "해당없음"}:
        return text
    return aliases.get(text, "보완필요")
