from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
import os
import re
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse as BaseJSONResponse
from pydantic import BaseModel, Field

from agents.internal_assessment import build_internal_assessment
from agents.models import ComplianceContent, FinalReview, ReviewResult
from agents.gpt_parser_agent import GptParserAgent, GptParserConfig
from agents.parse_bundle import (
    candidate_page_to_dict,
    import_pages_to_db,
    import_parse_bundle_to_db,
    replace_document_pages_in_db,
)
from agents.parse_job_orchestrator import ParseJobRunner
from orchestrator import (
    DEFAULT_ITEM_NOS,
    RfpReviewPipeline,
    attach_compliance_contents,
    merge_final_reviews,
    parse_fail_review,
    parse_items,
)


class JSONResponse(BaseJSONResponse):
    media_type = "application/json; charset=utf-8"


app = FastAPI(title="RFP Legal Review API", default_response_class=JSONResponse)
LOW_CONFIDENCE_THRESHOLD = float(os.getenv("RFP_LOW_CONFIDENCE_THRESHOLD", "0.75"))
CHUNK_PARSE_TIMEOUT_SECONDS = int(os.getenv("OPENAI_PDF_CHUNK_TIMEOUT_SECONDS", "90"))
CHUNK_PARSE_MAX_RETRIES = int(os.getenv("OPENAI_PDF_CHUNK_MAX_RETRIES", "0"))
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "RFP_ALLOWED_ORIGINS",
        "http://localhost:3000,https://*.vercel.app,https://v0.dev,https://v0.app",
    ).split(",")
    if origin.strip()
]
ALLOWED_ORIGIN_SET = set(ALLOWED_ORIGINS)
ALLOWED_ORIGIN_REGEX = r"https://.*\.vercel\.app"

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class ReviewCheckRequest(BaseModel):
    document_id: int
    items: str | list[str] | None = None


class EvidencePairInput(BaseModel):
    page: int | None = None
    text: str = ""


class UserFeedbackInput(BaseModel):
    comment: str = ""
    corrected_result: str = ""
    manual_compliance_content: str = ""
    corrected_evidence_pairs: list[EvidencePairInput] = Field(default_factory=list)
    internal_assessment_overrides: dict[str, str] = Field(default_factory=dict)
    resolved: bool = False


class RecommendationReviewInput(BaseModel):
    item_no: str
    review_result: str = ""
    normalized_result: str = ""
    final_status: str = ""
    is_target: bool | None = None
    confidence: float = 0.0
    reason: str = ""
    recommendation: str = ""
    evidence_pages: list[int] = Field(default_factory=list)
    evidence_text: list[str] = Field(default_factory=list)
    user_feedback: UserFeedbackInput | None = None
    detailed_assessment: dict[str, Any] | None = None


class RecommendationRequest(BaseModel):
    document_id: int
    results: list[RecommendationReviewInput]


class ParsedPageInput(BaseModel):
    page_no: int
    page_text: str = ""
    text_length: int | None = None
    rfp_printed_page_no: int | None = None
    has_table_candidate: bool = False
    has_attachment_candidate: bool = False
    has_eval_table_candidate: bool = False
    has_toc_candidate: bool = False
    has_blind_candidate: bool = False
    has_commercial_sw_candidate: bool = False
    parser_warning: str | None = None


class ImportPagesRequest(BaseModel):
    document_name: str
    total_pages: int
    pages: list[ParsedPageInput]


class ReplacePagesRequest(BaseModel):
    pages: list[ParsedPageInput]


def default_db_path() -> Path:
    configured = os.getenv("RFP_DB_PATH")
    if configured:
        return Path(configured)
    for candidate in (
        Path("rfp 법제도 검토항목.db"),
        Path("clean_legal_rag.db"),
    ):
        if candidate.exists():
            return candidate
    return Path("rfp 법제도 검토항목.db")


def output_dir_path() -> Path:
    return Path(os.getenv("RFP_OUTPUT_DIR", "outputs"))


def load_item_titles(db_path: Path) -> dict[str, str]:
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='legal_item'"
        ).fetchone()
        if table is None:
            return {}
        return {
            str(row["item_no"]): row["title"] or ""
            for row in conn.execute("SELECT item_no, title FROM legal_item")
        }
    finally:
        conn.close()


def load_item_criteria(db_path: Path) -> dict[str, dict[str, Any]]:
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        legal_item = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='legal_item'"
        ).fetchone()
        if legal_item is None:
            return {}
        criteria: dict[str, dict[str, Any]] = {}
        for row in conn.execute("SELECT item_no, title, target_text FROM legal_item"):
            criteria[str(row["item_no"])] = {
                "title": row["title"] or "",
                "target_text": row["target_text"] or "",
                "requirement_texts": [],
            }

        legal_requirement = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='legal_requirement'"
        ).fetchone()
        if legal_requirement is not None:
            for row in conn.execute(
                "SELECT item_no, requirement_text FROM legal_requirement ORDER BY item_no, rowid"
            ):
                item_no = str(row["item_no"])
                criteria.setdefault(
                    item_no,
                    {"title": "", "target_text": "", "requirement_texts": []},
                )
                requirement_text = row["requirement_text"] or ""
                if requirement_text:
                    criteria[item_no]["requirement_texts"].append(requirement_text)
        return criteria
    finally:
        conn.close()


def evidence_pairs(review) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    max_len = max(len(review.evidence_pages), len(review.evidence_text))
    for idx in range(max_len):
        pairs.append(
            {
                "page": review.evidence_pages[idx] if idx < len(review.evidence_pages) else None,
                "text": review.evidence_text[idx] if idx < len(review.evidence_text) else "",
            }
        )
    return pairs


def needs_user_attention(review) -> bool:
    verification = review.verification_audit
    return any(
        [
            review.confidence < LOW_CONFIDENCE_THRESHOLD,
            not review.evidence_pages,
            not review.evidence_text,
            bool(review.warnings),
            verification is not None and verification.requires_adjudication,
        ]
    )


def user_feedback_template() -> dict[str, Any]:
    return {
        "status": "not_submitted",
        "comment": "",
        "corrected_result": "",
        "manual_compliance_content": "",
        "corrected_evidence_pairs": [],
        "resolved": False,
    }


def attention_reasons(review) -> list[str]:
    reasons: list[str] = []
    if review.confidence < LOW_CONFIDENCE_THRESHOLD:
        reasons.append("confidence_low")
    if not review.evidence_pages or not review.evidence_text:
        reasons.append("evidence_missing")
    if review.warnings:
        reasons.append("review_warnings")
    verification = review.verification_audit
    if verification is not None and verification.requires_adjudication:
        reasons.append("verification_requires_adjudication")
    return reasons


def normalize_result_label(value: str) -> str:
    text = value or ""
    if "미준수" in text:
        return "미준수"
    if "보완" in text:
        return "보완필요"
    if "해당없" in text or "해당 없음" in text:
        return "해당없음"
    if "준수" in text:
        return "준수"
    return text


def normalize_result_label(value: str) -> str:
    text = str(value or "").strip()
    if "미준수" in text:
        return "미준수"
    if "보완" in text:
        return "보완필요"
    if "해당없음" in text or "해당 없음" in text:
        return "해당없음"
    if "준수" in text:
        return "준수"
    return text


def build_review_opinion(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    non_compliant = [item for item in results if item["normalized_result"] == "미준수"]
    needs_revision = [item for item in results if item["normalized_result"] == "보완필요"]
    lines = [
        f"총 {total}개 항목 중 {len(non_compliant)}개 항목 미준수 및 {len(needs_revision)}개 항목 보완 권고",
        "",
    ]
    for item in non_compliant + needs_revision:
        title = item["law_name"] or f"{item['item_no']}번 항목"
        content = item["compliance_content"] or item["recommendation"] or item["reason"]
        lines.append(f"{item['item_no']}. {title}")
        lines.append(f" - {content}")
    return {
        "total_count": total,
        "non_compliant_count": len(non_compliant),
        "needs_revision_count": len(needs_revision),
        "copy_text": "\n".join(lines).rstrip(),
    }


def review_result_column_text(results: list[dict[str, Any]]) -> str:
    return "\n".join(item["normalized_result"] for item in results)


def review_for_ui(review, item_criteria: dict[str, dict[str, Any]]) -> dict[str, Any]:
    compliance = review.compliance_content
    verification = review.verification_audit
    detailed_assessment = build_internal_assessment(
        str(review.item_no),
        list(review.evidence_pages),
        list(review.evidence_text),
    )
    normalized_result = (
        detailed_assessment["final_result"]
        if detailed_assessment is not None
        else normalize_result_label(review.final_result)
    )
    compliance_text = compliance.compliance_content if compliance is not None else ""
    criteria = item_criteria.get(str(review.item_no), {})
    return {
        "item_no": review.item_no,
        "law_name": criteria.get("title"),
        "target_text": criteria.get("target_text", ""),
        "requirement_texts": criteria.get("requirement_texts", []),
        "review_result": normalized_result if detailed_assessment is not None else review.final_result,
        "normalized_result": normalized_result,
        "final_status": review.final_status,
        "is_target": review.is_target,
        "confidence": review.confidence,
        "reason": review.reason,
        "recommendation": review.recommendation,
        "evidence_pages": review.evidence_pages,
        "evidence_text": review.evidence_text,
        "evidence_pairs": evidence_pairs(review),
        "warnings": review.warnings,
        "verification": asdict(verification) if verification is not None else None,
        "compliance_content": compliance_text,
        "compliance": asdict(compliance) if compliance is not None else None,
        "detailed_assessment": detailed_assessment,
        "needs_user_attention": needs_user_attention(review),
        "user_action_required": needs_user_attention(review),
        "attention_reasons": attention_reasons(review),
        "user_feedback": user_feedback_template(),
        "copy_texts": {
            "review_result": normalized_result,
            "compliance_content": compliance_text,
        },
        "raw_reviews": [item.to_dict() for item in review.reviews],
    }


def build_review_opinion(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    non_compliant = [item for item in results if item["normalized_result"] == "미준수"]
    needs_revision = [item for item in results if item["normalized_result"] == "보완필요"]
    if needs_revision:
        first_line = f"ㅇ 총 {total}개 항목 중 {len(non_compliant)}개 항목 미준수, {len(needs_revision)}개 항목 보완필요"
    else:
        first_line = f"ㅇ 총 {total}개 항목 중 {len(non_compliant)}개 항목 미준수"

    lines = [first_line]
    for item in non_compliant + needs_revision:
        title = item["law_name"] or f"{item['item_no']}번 항목"
        content = item["compliance_content"] or item["recommendation"] or item["reason"]
        lines.append(f"{item['item_no']}. {title}")
        lines.append(f"  - {summarize_opinion_content(str(item['item_no']), content)}")

    return {
        "total_count": total,
        "non_compliant_count": len(non_compliant),
        "needs_revision_count": len(needs_revision),
        "copy_text": "\n".join(lines).rstrip(),
    }


def summarize_opinion_content(item_no: str, content: str) -> str:
    text = " ".join(str(content or "").split())
    text = text.replace("→", " ")
    text = re.sub(r"제안요청서\s*p{1,2}\.\s*\d+(?:\s*[-~]\s*\d+)?(?:\s*,\s*)*", "", text)
    text = re.sub(r"p{1,2}\.\s*\d+(?:\s*[-~]\s*\d+)?(?:\s*,\s*)*", "", text)
    text = text.replace("제안요청서에 ", "")
    text = text.replace("제안요청서 내 ", "")
    text = text.replace("제안요청서 ", "")
    text = text.replace("작성하여 첨부하시기 바랍니다.", "첨부 필요")
    text = text.replace("첨부하시기 바랍니다.", "첨부 필요")
    text = text.replace("명시하시기 바랍니다.", "명시 필요")
    text = text.replace("하시기 바랍니다.", "필요")
    text = text.replace("하여야 합니다.", "필요")
    text = re.sub(r"^\s*(일부\s*)?명시\s*", "", text).strip()
    if item_no == "17" and "영향평가" in text and "결과서" in text:
        return "SW사업 영향평가 결과서 첨부 필요"
    return concise_summary_without_ellipsis(text) or "보완 필요"


def concise_summary_without_ellipsis(text: str, limit: int = 90) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    parts = re.split(r"(?:,| 및 | 또한 | 그리고 |\.|\n)", cleaned)
    kept: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        candidate = ", ".join([*kept, part]) if kept else part
        if len(candidate) > limit:
            break
        kept.append(part)
    if kept:
        return ", ".join(kept)
    return cleaned[:limit].rstrip()


def review_for_ui(review, item_criteria: dict[str, dict[str, Any]]) -> dict[str, Any]:
    compliance = review.compliance_content
    verification = review.verification_audit
    detailed_assessment = build_internal_assessment(
        str(review.item_no),
        list(review.evidence_pages),
        list(review.evidence_text),
    )
    normalized_result = (
        detailed_assessment["final_result"]
        if detailed_assessment is not None
        else normalize_result_label(review.final_result)
    )
    compliance_text = compliance.compliance_content if compliance is not None else ""
    if detailed_assessment is not None:
        compliance_text = internal_assessment_compliance_text(detailed_assessment, list(review.evidence_pages))
    criteria = item_criteria.get(str(review.item_no), {})
    return {
        "item_no": review.item_no,
        "law_name": criteria.get("title"),
        "target_text": criteria.get("target_text", ""),
        "requirement_texts": criteria.get("requirement_texts", []),
        "review_result": normalized_result if detailed_assessment is not None else review.final_result,
        "normalized_result": normalized_result,
        "final_status": review.final_status,
        "is_target": review.is_target,
        "confidence": review.confidence,
        "reason": detailed_assessment.get("reason") if detailed_assessment is not None else review.reason,
        "recommendation": review.recommendation,
        "evidence_pages": review.evidence_pages,
        "evidence_text": review.evidence_text,
        "evidence_pairs": evidence_pairs(review),
        "warnings": review.warnings,
        "verification": asdict(verification) if verification is not None else None,
        "compliance_content": compliance_text,
        "compliance": asdict(compliance) if compliance is not None else None,
        "detailed_assessment": detailed_assessment,
        "needs_user_attention": needs_user_attention(review),
        "user_action_required": needs_user_attention(review),
        "attention_reasons": attention_reasons(review),
        "user_feedback": user_feedback_template(),
        "copy_texts": {
            "review_result": normalized_result,
            "compliance_content": compliance_text,
            "internal_assessment": internal_assessment_copy_text(review, detailed_assessment)
            if detailed_assessment is not None
            else "",
        },
        "raw_reviews": [item.to_dict() for item in review.reviews],
    }


def internal_assessment_compliance_text(assessment: dict[str, Any], evidence_pages: list[int] | None = None) -> str:
    if assessment["final_result"] == "준수":
        page_text = format_pages_for_text(evidence_pages or [])
        return f"제안요청서 {page_text} 명시" if page_text else "관련 문구 명시"
    return str(assessment.get("recommendation") or assessment.get("reason") or "미명시 항목을 보완하시기 바랍니다.").strip()


def format_pages_for_text(pages: list[int]) -> str:
    unique = sorted({int(page) for page in pages if isinstance(page, int)})
    if not unique:
        return ""
    ranges: list[str] = []
    start = previous = unique[0]
    for page in unique[1:]:
        if page == previous + 1:
            previous = page
            continue
        ranges.append(f"p.{start}" if start == previous else f"pp.{start}-{previous}")
        start = previous = page
    ranges.append(f"p.{start}" if start == previous else f"pp.{start}-{previous}")
    return ", ".join(ranges)


def internal_assessment_copy_text(review, assessment: dict[str, Any] | None) -> str:
    if assessment is None:
        return ""
    lines = [
        f"{review.item_no}. {assessment.get('title', '')}",
        "",
        "구분\t내용\t명시 여부",
    ]
    for row in assessment.get("rows", []):
        lines.append(
            f"{row.get('no', '')}\t{row.get('title', '')}\n"
            f"{row.get('content', '')}\t{row.get('explicit_status', '')}"
        )
    lines.extend(["", f"최종 판단\t{assessment.get('final_result', '')}"])
    if assessment.get("reason"):
        lines.append(f"판단 근거\t{assessment['reason']}")
    return "\n".join(lines).strip()


def summary_for_ui(summary, db_path: Path) -> dict[str, Any]:
    item_criteria = load_item_criteria(db_path)
    results = [review_for_ui(review, item_criteria) for review in summary.final_reviews]
    user_action_required_count = sum(1 for item in results if item["user_action_required"])
    return {
        "document_id": summary.document_id,
        "parse_status": summary.parse_status,
        "audit_score": summary.audit_score,
        "audit_warnings": [asdict(warning) for warning in summary.audit_warnings],
        "parse_needs_user_confirmation": summary.parse_status != "ok"
        or summary.audit_score < 80
        or bool(summary.audit_warnings),
        "excel_path": str(summary.excel_path),
        "results": results,
        "review_result_column_text": review_result_column_text(results),
        "review_opinion": build_review_opinion(results),
        "workflow_gates": {
            "required_confirmations": [
                "parse_verification_confirmed",
                "review_results_confirmed",
                "recommendation_generation_confirmed",
                "final_results_confirmed",
            ],
            "can_generate_recommendations": user_action_required_count == 0,
            "user_action_required_count": user_action_required_count,
            "recommendation_generation_mode": "currently_generated_in_pipeline",
            "future_split_endpoint": "POST /api/recommendations",
        },
        "all_items_complete": all(
            item["normalized_result"] and item["compliance_content"] for item in results
        ),
    }


async def run_review_pipeline(file: UploadFile, items: str | None):
    db_path = default_db_path()
    output_dir = output_dir_path()
    suffix = Path(file.filename or "rfp.pdf").suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        pdf_path = Path(handle.name)
        handle.write(await file.read())

    try:
        pipeline = RfpReviewPipeline(db_path=db_path, output_dir=output_dir)
        return await pipeline.run(pdf_path, parse_items(items))
    finally:
        pdf_path.unlink(missing_ok=True)


async def parse_uploaded_file(file: UploadFile):
    db_path = default_db_path()
    output_dir = output_dir_path()
    suffix = Path(file.filename or "rfp.pdf").suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        pdf_path = Path(handle.name)
        handle.write(await file.read())

    try:
        pipeline = RfpReviewPipeline(db_path=db_path, output_dir=output_dir)
        document = pipeline.parser.parse(pdf_path)
        audited = pipeline.audit.audit(document)
        return pipeline, audited
    finally:
        pdf_path.unlink(missing_ok=True)


async def save_temp_upload(file: UploadFile, default_name: str) -> Path:
    suffix = Path(file.filename or default_name).suffix or Path(default_name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        upload_path = Path(handle.name)
        handle.write(await file.read())
    return upload_path


def parse_worker_page_numbers(value: str) -> list[int]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="page_numbers must be a JSON array") from exc
    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail="page_numbers must be a JSON array")
    page_numbers: list[int] = []
    for item in parsed:
        if isinstance(item, bool):
            raise HTTPException(status_code=400, detail="page_numbers must contain integers")
        try:
            page_no = int(item)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="page_numbers must contain integers") from exc
        if page_no <= 0:
            raise HTTPException(status_code=400, detail="page_numbers must be positive")
        page_numbers.append(page_no)
    if not page_numbers:
        raise HTTPException(status_code=400, detail="page_numbers cannot be empty")
    return page_numbers


async def save_upload_for_parse_job(file: UploadFile) -> Path:
    suffix = Path(file.filename or "rfp.pdf").suffix or ".pdf"
    upload_dir = output_dir_path() / "parse_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    target_path = upload_dir / f"{os.urandom(8).hex()}{suffix}"
    target_path.write_bytes(await file.read())
    return target_path


def run_parse_job_background(job_id: str) -> None:
    runner = ParseJobRunner(default_db_path())
    runner.run_job(job_id)


def parse_job_response(job_id: str) -> dict[str, Any]:
    db_path = default_db_path()
    runner = ParseJobRunner(db_path)
    snapshot = runner.snapshot(job_id).to_dict()
    if snapshot["status"] == "succeeded":
        pipeline = RfpReviewPipeline(db_path=db_path, output_dir=output_dir_path())
        document = pipeline.parser.load(snapshot["document_id"])
        audited = pipeline.audit.audit(document)
        snapshot["document"] = parsed_document_response(audited)
    return snapshot


def parsed_document_response(document) -> dict[str, Any]:
    return {
        "document_id": document.document_id,
        "document_name": document.document_name,
        "total_pages": document.total_pages,
        "parse_status": document.parse_status,
        "audit_score": document.audit_score or 0,
        "audit_warnings": [asdict(warning) for warning in document.audit_warnings],
        "parse_needs_user_confirmation": document.parse_status != "ok"
        or (document.audit_score or 0) < 80
        or bool(document.audit_warnings),
        "confirmations": {
            "parse_verification_confirmed": False,
            "review_results_confirmed": False,
            "recommendation_generation_confirmed": False,
            "final_results_confirmed": False,
        },
        "next_step": "review_check",
    }


def normalize_items(value: str | list[str] | None) -> list[str]:
    if value is None:
        return DEFAULT_ITEM_NOS
    if isinstance(value, str):
        return parse_items(value) or DEFAULT_ITEM_NOS
    return [str(item).strip() for item in value if str(item).strip()] or DEFAULT_ITEM_NOS


async def run_review_check(document_id: int, items: list[str]) -> dict[str, Any]:
    db_path = default_db_path()
    output_dir = output_dir_path()
    pipeline = RfpReviewPipeline(db_path=db_path, output_dir=output_dir)
    document = pipeline.parser.load(document_id)
    audited = pipeline.audit.audit(document)
    if audited.parse_status == "fail":
        final_reviews = [parse_fail_review(item_no, audited) for item_no in items]
    else:
        pipeline.rag.ensure_schema()
        semaphore = asyncio.Semaphore(pipeline.review_concurrency)
        tasks = [pipeline._review_item_limited(item_no, audited, semaphore) for item_no in items]
        final_reviews = merge_final_reviews(await asyncio.gather(*tasks))
    return review_check_response(audited, final_reviews, db_path)


def review_check_response(document, final_reviews: list[FinalReview], db_path: Path) -> dict[str, Any]:
    item_criteria = load_item_criteria(db_path)
    results = [review_for_ui(review, item_criteria) for review in final_reviews]
    user_action_required_count = sum(1 for item in results if item["user_action_required"])
    return {
        "document_id": document.document_id,
        "parse_status": document.parse_status,
        "audit_score": document.audit_score or 0,
        "audit_warnings": [asdict(warning) for warning in document.audit_warnings],
        "results": results,
        "workflow_gates": {
            "required_confirmations": [
                "parse_verification_confirmed",
                "review_results_confirmed",
                "recommendation_generation_confirmed",
                "final_results_confirmed",
            ],
            "can_generate_recommendations": user_action_required_count == 0,
            "user_action_required_count": user_action_required_count,
            "recommendation_generation_mode": "split_endpoint",
            "next_endpoint": "POST /api/recommendations",
        },
        "next_step": "recommendations",
    }


def final_review_from_payload(item: RecommendationReviewInput) -> FinalReview:
    evidence_pages = list(item.evidence_pages)
    evidence_text = list(item.evidence_text)
    feedback = item.user_feedback
    if feedback and feedback.corrected_evidence_pairs:
        evidence_pages = [
            pair.page for pair in feedback.corrected_evidence_pairs if pair.page is not None
        ]
        evidence_text = [pair.text for pair in feedback.corrected_evidence_pairs]

    reason = item.reason
    recommendation = item.recommendation
    warnings: list[str] = []
    if feedback and feedback.comment:
        warnings.append("user_feedback_applied")
        reason = f"{reason}\n\n사용자 수정 의견: {feedback.comment}".strip()

    corrected_result = feedback.corrected_result.strip() if feedback else ""
    result = corrected_result or item.normalized_result or item.review_result
    is_target = corrected_is_target(corrected_result, item.is_target)
    if corrected_result in {"미준수", "보완필요"} and not recommendation.strip():
        recommendation = (
            feedback.comment.strip()
            if feedback and feedback.comment.strip()
            else "해당 법제도 준수 항목을 반영하여 제안요청서를 보완하시기 바랍니다."
        )
    review = ReviewResult(
        item_no=str(item.item_no),
        route_type="user_confirmed",
        result=result,
        is_target=is_target,
        confidence=item.confidence,
        evidence_pages=evidence_pages,
        evidence_text=evidence_text,
        reason=reason,
        recommendation=recommendation,
        needs_human_review=not (feedback.resolved if feedback else True),
        source="ui_confirmed_review",
        warnings=warnings,
        used_llm=False,
    )
    return FinalReview(
        item_no=str(item.item_no),
        final_status=item.final_status or "사용자 확인 완료",
        final_result=result,
        is_target=is_target,
        confidence=item.confidence,
        evidence_pages=evidence_pages,
        evidence_text=evidence_text,
        reason=reason,
        recommendation=recommendation,
        reviews=[review],
        warnings=warnings,
    )


def corrected_is_target(corrected_result: str, original: bool | None) -> bool | None:
    if corrected_result == "해당없음":
        return False
    if corrected_result in {"준수", "미준수", "보완필요"}:
        return True
    return original


def generate_recommendations(payload: RecommendationRequest) -> dict[str, Any]:
    db_path = default_db_path()
    output_dir = output_dir_path()
    pipeline = RfpReviewPipeline(db_path=db_path, output_dir=output_dir)
    parse_status = "ok"
    audit_score = 100
    audit_warnings = []
    try:
        document = pipeline.parser.load(payload.document_id)
        audited = pipeline.audit.audit(document)
        parse_status = audited.parse_status
        audit_score = audited.audit_score or 0
        audit_warnings = audited.audit_warnings
    except RuntimeError as exc:
        if "document_id not found" not in str(exc):
            raise
    pipeline.rag.ensure_schema()
    final_reviews = [final_review_from_payload(item) for item in payload.results]
    final_reviews = attach_compliance_contents(
        merge_final_reviews(final_reviews),
        pipeline.rag,
        pipeline.compliance_content,
    )
    final_reviews = apply_manual_compliance_contents(final_reviews, payload)
    excel_path = pipeline.report.write_excel(
        payload.document_id,
        list(final_reviews),
        audit_warnings,
    )
    from agents.models import PipelineSummary

    summary = PipelineSummary(
        document_id=payload.document_id,
        parse_status=parse_status,
        audit_score=audit_score,
        audit_warnings=audit_warnings,
        final_reviews=list(final_reviews),
        excel_path=excel_path,
        compliance_contents=[
            review.compliance_content for review in final_reviews if review.compliance_content is not None
        ],
    )
    data = summary_for_ui(summary, db_path)
    apply_internal_assessment_feedback(data, payload)
    data["workflow_gates"]["recommendation_generation_mode"] = "split_endpoint"
    data["next_step"] = "final_results"
    return data


def apply_internal_assessment_feedback(data: dict[str, Any], payload: RecommendationRequest) -> None:
    feedback_by_item = {
        str(item.item_no): item.user_feedback.internal_assessment_overrides
        for item in payload.results
        if item.user_feedback and item.user_feedback.internal_assessment_overrides
    }
    if not feedback_by_item:
        return

    for item in data.get("results", []):
        assessment = item.get("detailed_assessment")
        overrides = feedback_by_item.get(str(item.get("item_no")))
        if not assessment or not overrides:
            continue
        for row in assessment.get("rows", []):
            row_no = str(row.get("no", ""))
            if row_no in overrides:
                row["explicit_status"] = overrides[row_no]
        assessment["final_result"] = internal_final_result_from_rows(assessment.get("rows", []))
        assessment["reason"] = internal_reason_from_rows(assessment.get("rows", []), assessment["final_result"])
        assessment["recommendation"] = internal_recommendation_from_rows(assessment.get("rows", []))
        item["normalized_result"] = assessment["final_result"]
        item["review_result"] = assessment["final_result"]
        item["reason"] = assessment["reason"]
        item["compliance_content"] = internal_assessment_compliance_text(
            assessment,
            [page for page in item.get("evidence_pages", []) if isinstance(page, int)],
        )
        item.setdefault("copy_texts", {})
        item["copy_texts"]["review_result"] = assessment["final_result"]
        item["copy_texts"]["compliance_content"] = item["compliance_content"]
        item["copy_texts"]["internal_assessment"] = internal_assessment_copy_text_from_result(item, assessment)

    data["review_result_column_text"] = review_result_column_text(data.get("results", []))
    data["review_opinion"] = build_review_opinion(data.get("results", []))
    data["all_items_complete"] = all(
        item.get("normalized_result") and item.get("compliance_content")
        for item in data.get("results", [])
    )


def internal_final_result_from_rows(rows: list[dict[str, Any]]) -> str:
    statuses = [str(row.get("explicit_status", "")) for row in rows]
    if all(status == "명시" for status in statuses):
        return "준수"
    if any(status in {"명시", "일부명시"} for status in statuses):
        return "보완필요"
    return "미준수"


def internal_reason_from_rows(rows: list[dict[str, Any]], final_result: str) -> str:
    if final_result == "준수":
        return "내부 검토표의 모든 항목이 명시되어 있습니다."
    missing = [
        f"{row.get('no')}. {row.get('title')}({row.get('explicit_status')})"
        for row in rows
        if row.get("explicit_status") != "명시"
    ]
    return "명시가 부족한 내부 항목: " + ", ".join(missing)


def internal_recommendation_from_rows(rows: list[dict[str, Any]]) -> str:
    actions: list[str] = []
    for row in rows:
        if row.get("explicit_status") == "명시":
            continue
        action = str(row.get("missing_action") or "").strip()
        if action and action not in actions:
            actions.append(action)
    return "\n".join(actions)


def internal_assessment_copy_text_from_result(item: dict[str, Any], assessment: dict[str, Any]) -> str:
    lines = [
        f"{item.get('item_no')}. {item.get('law_name') or assessment.get('title', '')}",
        "",
        "구분\t내용\t명시 여부",
    ]
    for row in assessment.get("rows", []):
        lines.append(
            f"{row.get('no', '')}\t{row.get('title', '')}\n"
            f"{row.get('content', '')}\t{row.get('explicit_status', '')}"
        )
    lines.extend(["", f"최종 판단\t{assessment.get('final_result', '')}"])
    if assessment.get("reason"):
        lines.append(f"판단 근거\t{assessment['reason']}")
    return "\n".join(lines).strip()


def apply_manual_compliance_contents(
    final_reviews: list[FinalReview], payload: RecommendationRequest
) -> list[FinalReview]:
    manual_by_item = {
        str(item.item_no): item.user_feedback.manual_compliance_content.strip()
        for item in payload.results
        if item.user_feedback and item.user_feedback.manual_compliance_content.strip()
    }
    if not manual_by_item:
        return final_reviews

    for review in final_reviews:
        manual_content = manual_by_item.get(str(review.item_no))
        if not manual_content:
            continue
        review.compliance_content = ComplianceContent(
            item_no=str(review.item_no),
            content_type="user_entered_compliance_content",
            primary_evidence_pages=list(review.evidence_pages),
            used_evidence_pages=list(review.evidence_pages),
            compliance_content=manual_content,
            tacit_knowledge_used=[],
            warnings=["user_entered"],
        )
    return final_reviews


@app.post("/review")
async def review(
    file: UploadFile = File(...),
    items: str | None = Form(default=None),
    return_excel: bool = Form(default=True),
):
    summary = await run_review_pipeline(file, items)
    if return_excel:
        return FileResponse(
            summary.excel_path,
            filename=summary.excel_path.name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    return JSONResponse(summary.to_dict())


@app.post("/api/review")
async def review_json(
    file: UploadFile = File(...),
    items: str | None = Form(default=None),
):
    summary = await run_review_pipeline(file, items)
    return JSONResponse(summary_for_ui(summary, default_db_path()))


@app.post("/api/parse")
async def parse_pdf(file: UploadFile = File(...)):
    _, document = await parse_uploaded_file(file)
    return JSONResponse(parsed_document_response(document))


@app.get("/api/worker/health")
def worker_health() -> dict[str, Any]:
    parser = GptParserAgent(default_db_path())
    return {
        "status": "ok",
        "openai_configured": parser.is_configured(),
        "chunk_proxy": True,
    }


@app.post("/api/parse/chunk")
async def parse_pdf_chunk(
    file: UploadFile = File(...),
    page_numbers: str = Form(...),
):
    selected_pages = parse_worker_page_numbers(page_numbers)
    chunk_path = await save_temp_upload(file, "chunk.pdf")
    started_at = time.monotonic()
    print(
        f"[parse/chunk] start pages={selected_pages} file={file.filename} "
        f"timeout={CHUNK_PARSE_TIMEOUT_SECONDS}s retries={CHUNK_PARSE_MAX_RETRIES}",
        flush=True,
    )
    try:
        parser = GptParserAgent(
            default_db_path(),
            config=GptParserConfig(
                model=os.getenv("OPENAI_PDF_CHUNK_MODEL", os.getenv("OPENAI_PDF_MODEL", "gpt-4.1")),
                pages_per_call=1,
                timeout_seconds=CHUNK_PARSE_TIMEOUT_SECONDS,
                max_retries=CHUNK_PARSE_MAX_RETRIES,
            ),
        )
        pages = await run_in_threadpool(parser.extract_chunk, chunk_path, selected_pages)
        elapsed = time.monotonic() - started_at
        print(f"[parse/chunk] done pages={selected_pages} elapsed={elapsed:.1f}s", flush=True)
        by_page = {page.page_no: page for page in pages}
        missing_pages = [page_no for page_no in selected_pages if page_no not in by_page]
        if missing_pages:
            raise HTTPException(
                status_code=502,
                detail=f"GPT parser returned no page result for PDF pages: {missing_pages}",
            )
        return JSONResponse(
            {
                "page_numbers": selected_pages,
                "pages": [candidate_page_to_dict(by_page[page_no]) for page_no in selected_pages],
            }
        )
    except RuntimeError as exc:
        elapsed = time.monotonic() - started_at
        print(f"[parse/chunk] failed pages={selected_pages} elapsed={elapsed:.1f}s error={exc}", flush=True)
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    finally:
        chunk_path.unlink(missing_ok=True)


@app.post("/api/parse/import")
async def import_parse_bundle(file: UploadFile = File(...)):
    bundle_path = await save_temp_upload(file, "parse_bundle.zip")
    try:
        document = import_parse_bundle_to_db(bundle_path, default_db_path())
        pipeline = RfpReviewPipeline(db_path=default_db_path(), output_dir=output_dir_path())
        audited = pipeline.audit.audit(document)
        return JSONResponse(parsed_document_response(audited))
    finally:
        bundle_path.unlink(missing_ok=True)


@app.post("/api/parse/import-pages")
async def import_parsed_pages(payload: ImportPagesRequest):
    if not payload.pages:
        raise HTTPException(status_code=400, detail="pages cannot be empty")
    document = import_pages_to_db(
        default_db_path(),
        document_name=payload.document_name,
        total_pages=payload.total_pages,
        pages_data=[page.model_dump() for page in payload.pages],
        file_path=None,
    )
    pipeline = RfpReviewPipeline(db_path=default_db_path(), output_dir=output_dir_path())
    audited = pipeline.audit.audit(document)
    return JSONResponse(parsed_document_response(audited))


@app.post("/api/parse/documents/{document_id}/pages")
async def replace_parsed_document_pages(document_id: int, payload: ReplacePagesRequest):
    if not payload.pages:
        raise HTTPException(status_code=400, detail="pages cannot be empty")
    try:
        document = replace_document_pages_in_db(
            default_db_path(),
            document_id=document_id,
            pages_data=[page.model_dump() for page in payload.pages],
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    pipeline = RfpReviewPipeline(db_path=default_db_path(), output_dir=output_dir_path())
    audited = pipeline.audit.audit(document)
    return JSONResponse(parsed_document_response(audited))


@app.post("/api/parse/jobs")
async def create_parse_job(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    pdf_path = await save_upload_for_parse_job(file)
    runner = ParseJobRunner(default_db_path())
    snapshot = runner.create_job(pdf_path)
    background_tasks.add_task(run_parse_job_background, snapshot.job_id)
    return JSONResponse(snapshot.to_dict())


@app.get("/api/parse/jobs/{job_id}")
async def get_parse_job(job_id: str):
    return JSONResponse(parse_job_response(job_id))


@app.post("/api/review/check")
async def review_check(payload: ReviewCheckRequest):
    data = await run_review_check(payload.document_id, normalize_items(payload.items))
    return JSONResponse(data)


@app.post("/api/recommendations")
async def recommendations(payload: RecommendationRequest):
    return JSONResponse(generate_recommendations(payload))


@app.get("/api/documents/{document_id}/search")
async def search_document(document_id: int, q: str):
    db_path = default_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(rfp_page)").fetchall()
        }
        printed_page_select = (
            "rfp_printed_page_no"
            if "rfp_printed_page_no" in columns
            else "NULL AS rfp_printed_page_no"
        )
        rows = conn.execute(
            f"""
            SELECT page_no, {printed_page_select}, page_text
            FROM rfp_page
            WHERE document_id = ?
              AND page_text LIKE ?
            ORDER BY page_no
            LIMIT 25
            """,
            (document_id, f"%{q}%"),
        ).fetchall()
        return {
            "document_id": document_id,
            "query": q,
            "results": [
                {
                    "page": row["rfp_printed_page_no"] or row["page_no"],
                    "pdf_page": row["page_no"],
                    "text": make_snippet(row["page_text"], q),
                }
                for row in rows
            ],
        }
    finally:
        conn.close()


def make_snippet(text: str, query: str, radius: int = 160) -> str:
    if not query:
        return text[: radius * 2]
    lower_text = text.lower()
    lower_query = query.lower()
    idx = lower_text.find(lower_query)
    if idx < 0:
        return text[: radius * 2]
    start = max(0, idx - radius)
    end = min(len(text), idx + len(query) + radius)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"
