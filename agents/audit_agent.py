from __future__ import annotations

import json
import re

from agents.llm_client import DisabledLlmClient
from agents.models import AuditWarning, ParsedDocument


REQUIRED_SECTION_PATTERNS = {
    "사업개요": re.compile(r"사업\s*개요|과업\s*개요"),
    "제안요청사항": re.compile(r"제안\s*요청|요구\s*사항|과업\s*내용"),
    "평가기준": re.compile(r"평가\s*기준|평가\s*항목|배점"),
}


class ParseAuditAgent:
    """Python objective checks + GPT semantic checks for parsed RFP pages."""

    def __init__(self, llm_client: object | None = None, use_gpt: bool = True) -> None:
        self.llm_client = llm_client or DisabledLlmClient()
        self.use_gpt = use_gpt

    def audit(self, document: ParsedDocument) -> ParsedDocument:
        warnings = self.python_audit(document)
        if self.use_gpt and getattr(self.llm_client, "is_configured", lambda: False)():
            warnings.extend(self.gpt_audit(document))
        warnings = filter_expected_index_page_warnings(document, warnings)

        quality = audit_quality_summary(document.total_pages, warnings)
        document.audit_score = int(quality["audit_score"])
        document.audit_warnings = warnings
        document.parse_status = parse_status_from_quality(quality, warnings)
        return document

    def python_audit(self, document: ParsedDocument) -> list[AuditWarning]:
        warnings: list[AuditWarning] = []
        all_text = "\n".join(page.page_text for page in document.pages)
        parsed_page_numbers = {page.page_no for page in document.pages}
        partial_parse = len(parsed_page_numbers) < document.total_pages

        for label in expected_sections_for_pages(parsed_page_numbers, partial_parse):
            if not REQUIRED_SECTION_PATTERNS[label].search(all_text):
                warnings.append(
                    AuditWarning(
                        warning_type="required_section_missing",
                        message=f"필수 섹션 후보를 찾지 못했습니다: {label}",
                        severity="medium",
                    )
                )

        for page in document.pages:
            if is_attachment_or_form_index_page(page.page_text):
                continue
            if page.parser_warning:
                warnings.append(
                    AuditWarning(
                        warning_type="parser_warning",
                        message=page.parser_warning,
                        page_no=page.page_no,
                        severity="medium",
                    )
                )
            if page.text_length == 0:
                warnings.append(
                    AuditWarning(
                        warning_type="empty_page",
                        message="문자가 추출되지 않은 페이지입니다.",
                        page_no=page.page_no,
                        severity="high",
                    )
                )
            elif page.text_length < 30:
                warnings.append(
                    AuditWarning(
                        warning_type="low_text_density",
                        message="추출 문자량이 매우 적어 OCR 또는 레이아웃 누락 가능성이 있습니다.",
                        page_no=page.page_no,
                        severity="low",
                    )
                )
            if has_suspicious_unicode_noise(page.page_text):
                warnings.append(
                    AuditWarning(
                        warning_type="suspicious_unicode_noise",
                        message="한글 RFP 본문에 비정상 유니코드 문자가 섞여 있어 PDF 문자 추출 오염 가능성이 있습니다.",
                        page_no=page.page_no,
                        severity="medium",
                    )
                )

        if not partial_parse:
            if not any(page.has_eval_table_candidate for page in document.pages):
                warnings.append(
                    AuditWarning(
                        warning_type="eval_table_not_found",
                        message="전체 문서에서 평가표 후보 페이지를 찾지 못했습니다.",
                        severity="medium",
                        related_item_nos=["4", "11", "12"],
                    )
                )
            if not any(page.has_attachment_candidate for page in document.pages):
                warnings.append(
                    AuditWarning(
                        warning_type="attachment_not_found",
                        message="전체 문서에서 붙임/별첨/서식 후보 페이지를 찾지 못했습니다.",
                        severity="medium",
                        related_item_nos=["2", "15", "17"],
                    )
                )
        return warnings

    def gpt_audit(self, document: ParsedDocument) -> list[AuditWarning]:
        payload = build_gpt_audit_payload(document)
        data = self.llm_client.json_response(
            GPT_AUDIT_SYSTEM_PROMPT,
            json.dumps(payload, ensure_ascii=False, indent=2),
            model_role="parse_audit",
            temperature=0,
        )
        apply_page_overrides(document, data.get("page_overrides", []))
        return [
            AuditWarning(
                warning_type=str(item.get("warning_type", "gpt_parse_audit")),
                message=str(item.get("message", "")),
                page_no=parse_optional_int(item.get("page_no")),
                severity=str(item.get("severity", "medium")),
                related_item_nos=[str(x) for x in item.get("related_item_nos", [])],
            )
            for item in data.get("warnings", [])
            if isinstance(item, dict)
        ]

    def pages_to_reparse(self, document: ParsedDocument, threshold: int = 70) -> list[int]:
        if (document.audit_score or 100) >= threshold:
            return []
        pages = [warning.page_no for warning in document.audit_warnings if warning.page_no]
        return sorted(set(pages))


def expected_sections_for_pages(parsed_page_numbers: set[int], partial_parse: bool) -> list[str]:
    if not parsed_page_numbers:
        return ["사업개요"]
    if not partial_parse:
        return list(REQUIRED_SECTION_PATTERNS)

    max_page = max(parsed_page_numbers)
    expected = ["사업개요"]
    if max_page >= 8:
        expected.append("제안요청사항")
    if max_page >= 25:
        expected.append("평가기준")
    return expected


GPT_AUDIT_SYSTEM_PROMPT = """당신은 RFP PDF 파싱 검증 에이전트입니다.
Python 규칙 검사가 어려운 부분만 검증합니다.

검증 기준:
- 추출 텍스트가 의미 있는 한국어 RFP 텍스트인지 확인합니다.
- 깨진 문자, 누락된 표, 레이아웃 붕괴, OCR 실패 의심을 찾습니다.
- 목차 페이지, 단순 참조 문구의 '붙임6' 같은 표현은 실제 붙임/별첨 본문으로 보지 않습니다.
- 이미지가 배치용 표 안에 들어간 페이지는 법제도 검토용 데이터 표로 보지 않습니다.
- 평가표 후보는 실제 평가항목, 배점, 정량/정성 평가 기준이 있는 페이지에만 표시합니다.
- partial parse인 경우, 아직 읽지 않은 뒤쪽 페이지의 평가기준/별첨 부재는 경고하지 않습니다.

출력은 JSON 객체 하나만 반환하세요."""


def build_gpt_audit_payload(document: ParsedDocument) -> dict:
    return {
        "document_name": document.document_name,
        "total_pages": document.total_pages,
        "parsed_pages": [page.page_no for page in document.pages],
        "pages": [
            {
                "page_no": page.page_no,
                "text_length": page.text_length,
                "page_text_sample": page.page_text[:1800],
                "flags": {
                    "has_table_candidate": page.has_table_candidate,
                    "has_eval_table_candidate": page.has_eval_table_candidate,
                    "has_attachment_candidate": page.has_attachment_candidate,
                    "has_toc_candidate": page.has_toc_candidate,
                    "has_blind_candidate": page.has_blind_candidate,
                    "has_commercial_sw_candidate": page.has_commercial_sw_candidate,
                    "parser_warning": page.parser_warning,
                },
            }
            for page in document.pages[:20]
        ],
        "output_schema": {
            "page_overrides": [
                {
                    "page_no": "number",
                    "has_table_candidate": "boolean or omitted",
                    "has_eval_table_candidate": "boolean or omitted",
                    "has_attachment_candidate": "boolean or omitted",
                    "reason": "short reason",
                }
            ],
            "warnings": [
                {
                    "warning_type": "meaningless_text|layout_error|table_false_positive|attachment_false_positive|parser_warning",
                    "page_no": "number or null",
                    "severity": "low|medium|high",
                    "message": "short Korean message",
                    "related_item_nos": ["optional item numbers"],
                }
            ],
        },
    }


def apply_page_overrides(document: ParsedDocument, overrides: object) -> None:
    if not isinstance(overrides, list):
        return
    by_page = {page.page_no: page for page in document.pages}
    for item in overrides:
        if not isinstance(item, dict):
            continue
        page = by_page.get(parse_optional_int(item.get("page_no")) or -1)
        if page is None:
            continue
        for field_name in [
            "has_table_candidate",
            "has_eval_table_candidate",
            "has_attachment_candidate",
        ]:
            if field_name in item and isinstance(item[field_name], bool):
                setattr(page, field_name, item[field_name])


def parse_optional_int(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def filter_expected_index_page_warnings(
    document: ParsedDocument,
    warnings: list[AuditWarning],
) -> list[AuditWarning]:
    index_pages = {
        page.page_no
        for page in document.pages
        if is_attachment_or_form_index_page(page.page_text)
    }
    if not index_pages:
        return warnings
    return [
        warning
        for warning in warnings
        if warning.page_no not in index_pages
        or warning.warning_type
        not in {
            "parser_warning",
            "low_text_density",
            "layout_error",
            "meaningless_text",
            "gpt_parse_audit",
        }
    ]


def is_attachment_or_form_index_page(text: str) -> bool:
    source = str(text or "")
    compact = re.sub(r"\s+", "", source)
    if not compact:
        return False
    has_section_marker = any(marker in compact for marker in ["별첨", "붙임", "서식"])
    has_index_shape = (
        len(re.findall(r"(?:별첨|붙임|서식)\s*\d+", source)) >= 2
        or ("목차" in compact and has_section_marker)
    )
    return has_section_marker and has_index_shape


SUSPICIOUS_UNICODE_RE = re.compile(r"[\u0900-\u097F\u0980-\u09FF\u0C00-\u0C7F\uFFFD]")


def has_suspicious_unicode_noise(text: str) -> bool:
    source = str(text or "")
    if not source:
        return False
    matches = SUSPICIOUS_UNICODE_RE.findall(source)
    if len(matches) >= 2:
        return True
    return bool(matches) and len(matches) / max(1, len(source)) >= 0.005


SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
PAGE_PENALTY = {"info": 0, "low": 1, "medium": 4, "high": 10, "critical": 20}


def audit_quality_summary(total_pages: int, warnings: list[AuditWarning]) -> dict[str, object]:
    page_severities: dict[int, str] = {}
    document_penalty = 0
    for warning in warnings:
        severity = normalized_severity(warning.severity)
        if warning.page_no is None:
            document_penalty += PAGE_PENALTY.get(severity, 4)
            continue
        current = page_severities.get(warning.page_no, "info")
        if SEVERITY_RANK[severity] > SEVERITY_RANK[current]:
            page_severities[warning.page_no] = severity

    page_penalty = sum(PAGE_PENALTY[severity] for severity in page_severities.values())
    affected_page_count = sum(1 for severity in page_severities.values() if severity != "low")
    all_affected_page_count = len(page_severities)
    critical_page_count = sum(1 for severity in page_severities.values() if severity in {"high", "critical"})
    affected_ratio = affected_page_count / total_pages if total_pages else 0
    return {
        "audit_warning_count": len(warnings),
        "affected_page_count": affected_page_count,
        "all_affected_page_count": all_affected_page_count,
        "critical_page_count": critical_page_count,
        "high_severity_page_count": critical_page_count,
        "affected_ratio": affected_ratio,
        "audit_score": max(0, 100 - page_penalty - document_penalty),
        "page_severities": page_severities,
    }


def parse_status_from_quality(quality: dict[str, object], warnings: list[AuditWarning]) -> str:
    if not warnings:
        return "ok"
    critical_page_count = int(quality.get("critical_page_count", 0))
    affected_ratio = float(quality.get("affected_ratio", 0))
    if critical_page_count >= 5 or affected_ratio >= 0.15:
        return "fail"
    return "warning"


def normalized_severity(value: str | None) -> str:
    severity = str(value or "medium").strip().lower()
    return severity if severity in SEVERITY_RANK else "medium"
