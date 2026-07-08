from __future__ import annotations

import asyncio
from dataclasses import asdict
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from agents.models import FinalReview, ReviewResult
from orchestrator import (
    DEFAULT_ITEM_NOS,
    RfpReviewPipeline,
    attach_compliance_contents,
    merge_final_reviews,
    parse_fail_review,
    parse_items,
)


app = FastAPI(title="RFP Legal Review API")
LOW_CONFIDENCE_THRESHOLD = float(os.getenv("RFP_LOW_CONFIDENCE_THRESHOLD", "0.75"))
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "RFP_ALLOWED_ORIGINS",
        "http://localhost:3000,https://*.vercel.app,https://v0.dev,https://v0.app",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",
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
    corrected_evidence_pairs: list[EvidencePairInput] = Field(default_factory=list)
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


class RecommendationRequest(BaseModel):
    document_id: int
    results: list[RecommendationReviewInput]


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


def review_for_ui(review, item_titles: dict[str, str]) -> dict[str, Any]:
    compliance = review.compliance_content
    verification = review.verification_audit
    normalized_result = normalize_result_label(review.final_result)
    compliance_text = compliance.compliance_content if compliance is not None else ""
    return {
        "item_no": review.item_no,
        "law_name": item_titles.get(str(review.item_no)),
        "review_result": review.final_result,
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


def summary_for_ui(summary, db_path: Path) -> dict[str, Any]:
    item_titles = load_item_titles(db_path)
    results = [review_for_ui(review, item_titles) for review in summary.final_reviews]
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
    item_titles = load_item_titles(db_path)
    results = [review_for_ui(review, item_titles) for review in final_reviews]
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

    result = item.normalized_result or item.review_result
    review = ReviewResult(
        item_no=str(item.item_no),
        route_type="user_confirmed",
        result=result,
        is_target=item.is_target,
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
        is_target=item.is_target,
        confidence=item.confidence,
        evidence_pages=evidence_pages,
        evidence_text=evidence_text,
        reason=reason,
        recommendation=recommendation,
        reviews=[review],
        warnings=warnings,
    )


def generate_recommendations(payload: RecommendationRequest) -> dict[str, Any]:
    db_path = default_db_path()
    output_dir = output_dir_path()
    pipeline = RfpReviewPipeline(db_path=db_path, output_dir=output_dir)
    document = pipeline.parser.load(payload.document_id)
    audited = pipeline.audit.audit(document)
    pipeline.rag.ensure_schema()
    final_reviews = [final_review_from_payload(item) for item in payload.results]
    final_reviews = attach_compliance_contents(
        merge_final_reviews(final_reviews),
        pipeline.rag,
        pipeline.compliance_content,
    )
    excel_path = pipeline.report.write_excel(
        audited.document_id,
        list(final_reviews),
        audited.audit_warnings,
    )
    from agents.models import PipelineSummary

    summary = PipelineSummary(
        document_id=audited.document_id,
        parse_status=audited.parse_status,
        audit_score=audited.audit_score or 0,
        audit_warnings=audited.audit_warnings,
        final_reviews=list(final_reviews),
        excel_path=excel_path,
        compliance_contents=[
            review.compliance_content for review in final_reviews if review.compliance_content is not None
        ],
    )
    data = summary_for_ui(summary, db_path)
    data["workflow_gates"]["recommendation_generation_mode"] = "split_endpoint"
    data["next_step"] = "final_results"
    return data


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
        rows = conn.execute(
            """
            SELECT page_no, rfp_printed_page_no, page_text
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
