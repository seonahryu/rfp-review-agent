from __future__ import annotations

from dataclasses import asdict
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from orchestrator import RfpReviewPipeline, parse_items


app = FastAPI(title="RFP Legal Review API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def review_for_ui(review) -> dict[str, Any]:
    compliance = review.compliance_content
    verification = review.verification_audit
    return {
        "item_no": review.item_no,
        "law_name": None,
        "review_result": review.final_result,
        "final_status": review.final_status,
        "is_target": review.is_target,
        "confidence": review.confidence,
        "reason": review.reason,
        "recommendation": review.recommendation,
        "evidence_pages": review.evidence_pages,
        "evidence_text": review.evidence_text,
        "warnings": review.warnings,
        "verification": asdict(verification) if verification is not None else None,
        "compliance_content": compliance.compliance_content if compliance is not None else "",
        "compliance": asdict(compliance) if compliance is not None else None,
        "raw_reviews": [item.to_dict() for item in review.reviews],
    }


def summary_for_ui(summary) -> dict[str, Any]:
    return {
        "document_id": summary.document_id,
        "parse_status": summary.parse_status,
        "audit_score": summary.audit_score,
        "audit_warnings": [asdict(warning) for warning in summary.audit_warnings],
        "excel_path": str(summary.excel_path),
        "results": [review_for_ui(review) for review in summary.final_reviews],
    }


async def run_review_pipeline(file: UploadFile, items: str | None):
    db_path = Path(os.getenv("RFP_DB_PATH", "rfp 법제도 검토항목.db"))
    output_dir = Path(os.getenv("RFP_OUTPUT_DIR", "outputs"))
    suffix = Path(file.filename or "rfp.pdf").suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        pdf_path = Path(handle.name)
        handle.write(await file.read())

    try:
        pipeline = RfpReviewPipeline(db_path=db_path, output_dir=output_dir)
        return await pipeline.run(pdf_path, parse_items(items))
    finally:
        pdf_path.unlink(missing_ok=True)


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
    return JSONResponse(summary_for_ui(summary))
