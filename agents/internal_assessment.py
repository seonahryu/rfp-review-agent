from __future__ import annotations

from typing import Any


ITEM_4_ROWS = [
    {
        "no": "1",
        "title": "<하도급 사전 승인>",
        "content": "하도급 계약시 발주기관으로부터 하도급 사전 승인을 받도록 안내",
        "requirements": [["하도급", "사전승인"]],
        "missing_action": "하도급 계약 시 발주기관으로부터 하도급 사전 승인을 받도록 안내하시기 바랍니다.",
    },
    {
        "no": "2",
        "title": "<하도급 비율 제한>",
        "content": "하도급 허용시 하도급 비율은 50%를 초과할 수 없음을 안내",
        "requirements": [["하도급", "50", "초과할수없"], ["하도급", "100분의50"]],
        "missing_action": "하도급 허용 시 하도급 비율은 50%를 초과할 수 없음을 안내하시기 바랍니다.",
    },
    {
        "no": "3",
        "title": "<재하도급 원칙적 불허>",
        "content": "하도급 허용시 재하도급을 원칙적으로 불허함을 안내",
        "requirements": [["재하도급", "불허"], ["다시하도급", "불허"], ["하도급", "원칙적으로불허"]],
        "missing_action": "하도급 허용 시 재하도급을 원칙적으로 불허함을 안내하시기 바랍니다.",
    },
    {
        "no": "4",
        "title": "<하도급 계획서 제출>",
        "content": "계약체결시 (원)도급자는 발주기관에게 하도급 계획서를 제출하도록 안내",
        "requirements": [["하도급", "계획서", "제출"], ["계약체결", "하도급계획서"]],
        "missing_action": "계약체결 시 (원)도급자가 발주기관에게 하도급 계획서를 제출하도록 안내하시기 바랍니다.",
    },
    {
        "no": "5",
        "title": "<하도급 계획 적정성 확인서 제출>",
        "content": (
            "'하도급계획 적정성'을 기술성 평가항목에 포함하는 사업으로, 입찰 시 (원)도급자는 "
            '발주기관에게 "소프트웨어사업 하도급 계획 적정성 확인서"를 제출하도록 안내'
        ),
        "requirements": [
            ["하도급계획적정성확인서"],
            ["하도급", "적정성", "평가항목"],
            ["하도급계약", "적정성", "세부기준"],
        ],
        "missing_action": '입찰 시 "소프트웨어사업 하도급 계획 적정성 확인서" 제출 안내를 명시하시기 바랍니다.',
    },
    {
        "no": "6",
        "title": "<하도급 계약 적정성 판단기준>",
        "content": "발주기관은 하도급 계약의 적정성 판단기준을 사전에 정하여 안내",
        "requirements": [["하도급", "적정성", "판단"], ["하도급계약", "적정성", "세부기준"]],
        "missing_action": "하도급 계약의 적정성 판단기준을 사전에 정하여 안내하시기 바랍니다.",
    },
]


ITEM_5_ROWS = [
    {
        "no": "1",
        "title": "<작업장소 상호협의 등>",
        "content": (
            "제안요청서 등에 작업장소 상호협의 또는 제공여부 등을 명시하고 있는지 여부"
            "(작업장소 등 관련 비용 계상여부 포함)"
        ),
        "requirements": [
            ["작업장소", "상호", "협의"],
            ["작업장소", "제공"],
            ["작업장소", "비용"],
            ["제안가격", "포함"],
        ],
        "missing_action": "작업장소 상호협의 또는 제공여부와 작업장소 관련 비용 계상여부를 명시하시기 바랍니다.",
    },
    {
        "no": "2",
        "title": "<원격지 개발 장소 제시·검토 절차>",
        "content": (
            "제안요청서 등에 공급자에 의한 작업장소 제시 및 그에 따른 발주기관의 "
            "검토절차 등을 명시하고 있는지 여부"
        ),
        "requirements": [
            ["원격지", "개발", "장소", "제시"],
            ["작업장소", "제시"],
            ["발주기관", "검토"],
            ["검토", "절차"],
        ],
        "missing_action": "공급자의 원격지 개발 장소 제시와 발주기관의 검토절차를 명시하시기 바랍니다.",
    },
    {
        "no": "3",
        "title": "<원격지 개발 장소 보안요구사항>",
        "content": "제안요청서 내에 작업장소 관련 보안요구사항을 명시하고 있는지 여부",
        "requirements": [
            ["원격지", "보안"],
            ["작업장소", "보안"],
            ["보안", "요구사항"],
            ["출입", "통제"],
            ["저장매체", "반출"],
        ],
        "missing_action": "원격지 개발 장소 및 작업장소 관련 보안요구사항을 명시하시기 바랍니다.",
    },
]


ITEM_6_ROWS = [
    {
        "no": "1",
        "title": "<지식재산권 공동귀속>",
        "content": (
            "제안요청서 등에 지식재산의 공동귀속 적용 여부. 발주기관 귀속의 경우 "
            "계약목적물의 특수성에 따른 구체적 사유가 명시되어 있는지 여부"
        ),
        "requirements": [
            ["지식재산", "공동귀속"],
            ["지식재산", "공동소유"],
            ["지식재산권", "공동"],
            ["계약목적물", "지식재산권"],
            ["공동", "귀속"],
            ["공동", "소유"],
        ],
        "missing_action": "지식재산권 공동귀속 적용 여부를 명시하시기 바랍니다.",
    },
    {
        "no": "2",
        "title": "<SW산출물 반출 절차 등>",
        "content": (
            "제안요청서 내 SW산출물 활용촉진을 위한 반출절차 적용 여부, 반출 요청절차, "
            "누출금지정보 삭제 및 확약서 제출, 제3자 제공 시 사전승인, 위반 시 입찰참가자격 제한 명시 여부"
        ),
        "requirements": [
            ["SW산출물", "반출", "요청"],
            ["산출물", "반출", "절차"],
            ["누출금지정보", "삭제"],
            ["확약서", "제출"],
            ["제3자", "사전승인"],
            ["입찰참가자격", "제한"],
        ],
        "full_match_count": 5,
        "missing_action": (
            "SW산출물 반출 요청절차, 누출금지정보 삭제 및 확약서 제출, 제3자 제공 시 사전승인, "
            "위반 시 입찰참가자격 제한 내용을 명시하시기 바랍니다."
        ),
    },
]


def build_internal_assessment(
    item_no: str,
    evidence_pages: list[int],
    evidence_text: list[str],
) -> dict[str, Any] | None:
    item = str(item_no).strip()
    if item == "4":
        rows = ITEM_4_ROWS
        title = "하도급 제도"
    elif item == "5":
        rows = ITEM_5_ROWS
        title = "SW사업 작업장소(원격개발)"
    elif item == "6":
        rows = ITEM_6_ROWS
        title = "SW사업 산출물 활용 보장"
    else:
        return None

    assessed_rows = [assess_row(row, evidence_pages, evidence_text) for row in rows]
    final_result = final_result_from_rows(assessed_rows)
    return {
        "item_no": item,
        "title": title,
        "columns": ["구분", "내용", "명시 여부"],
        "rows": assessed_rows,
        "final_result": final_result,
        "reason": reason_from_rows(assessed_rows, final_result),
        "recommendation": recommendation_from_rows(assessed_rows),
    }


def assess_row(row: dict[str, Any], evidence_pages: list[int], evidence_text: list[str]) -> dict[str, Any]:
    matched_requirements: list[str] = []
    evidence_pairs: list[dict[str, Any]] = []
    for terms in row["requirements"]:
        for idx, text in enumerate(evidence_text):
            if contains_all(text, terms):
                label = " ".join(terms)
                if label not in matched_requirements:
                    matched_requirements.append(label)
                evidence_pairs.append(
                    {
                        "page": evidence_pages[idx] if idx < len(evidence_pages) else None,
                        "text": compact_text(text),
                    }
                )
                break

    required_for_full = int(row.get("full_match_count") or 1)
    if len(matched_requirements) >= required_for_full:
        explicit_status = "명시"
    elif matched_requirements:
        explicit_status = "일부명시"
    else:
        explicit_status = "미명시"

    return {
        "no": row["no"],
        "title": row["title"],
        "content": row["content"],
        "explicit_status": explicit_status,
        "matched_requirements": matched_requirements,
        "missing_action": row["missing_action"],
        "evidence_pairs": dedupe_evidence_pairs(evidence_pairs),
    }


def final_result_from_rows(rows: list[dict[str, Any]]) -> str:
    statuses = [row["explicit_status"] for row in rows]
    if all(status == "명시" for status in statuses):
        return "준수"
    if any(status in {"명시", "일부명시"} for status in statuses):
        return "보완필요"
    return "미준수"


def reason_from_rows(rows: list[dict[str, Any]], final_result: str) -> str:
    if final_result == "준수":
        return "내부 검토표의 모든 항목이 RFP 근거에서 명시로 확인되었습니다."
    missing = [f"{row['no']}. {row['title']}({row['explicit_status']})" for row in rows if row["explicit_status"] != "명시"]
    return "명시가 부족한 내부 항목: " + ", ".join(missing)


def recommendation_from_rows(rows: list[dict[str, Any]]) -> str:
    actions = [row["missing_action"] for row in rows if row["explicit_status"] != "명시"]
    return "\n".join(dict.fromkeys(actions))


def contains_all(text: str, terms: list[str]) -> bool:
    normalized = normalize(text)
    return all(normalize(term) in normalized for term in terms)


def normalize(text: str) -> str:
    return "".join(str(text or "").split()).lower()


def compact_text(text: str, limit: int = 240) -> str:
    compacted = " ".join(str(text or "").split())
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 3].rstrip() + "..."


def dedupe_evidence_pairs(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, str]] = set()
    result: list[dict[str, Any]] = []
    for pair in pairs:
        key = (pair.get("page"), pair.get("text"))
        if key in seen:
            continue
        seen.add(key)
        result.append(pair)
    return result[:5]
