from __future__ import annotations

import argparse
import glob
import json
import sys
from dataclasses import fields
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.llm_client import DisabledLlmClient, OpenAILowCostClient
from agents.models import FinalReview, ReviewResult
from agents.verification_agent import FinalAdjudicationAgent, VerificationAuditAgent


def validate_payload(
    payload: dict[str, Any],
    *,
    llm_client: object,
    adjudicate: bool = False,
) -> dict[str, Any]:
    auditor = VerificationAuditAgent(llm_client)
    adjudicator = FinalAdjudicationAgent(llm_client)
    route_by_item = routes_by_item(payload)

    validated_reviews: list[dict[str, Any]] = []
    for raw_review in payload.get("merged_final_reviews", []):
        final = final_review_from_dict(raw_review)
        primary = primary_review_for_validation(final)
        audit = auditor.audit_review(
            item_no=str(final.item_no),
            review=primary,
            expected_route=route_by_item.get(str(final.item_no)),
            atomic_requirements=[],
        )
        final.verification_audit = audit
        if adjudicate and audit.requires_adjudication:
            adjudicated = adjudicator.adjudicate(
                item_no=str(final.item_no),
                primary_review=primary,
                audit=audit,
                atomic_requirements=[],
            )
            final.final_result = adjudicated.final_result
            final.reason = adjudicated.reason
            final.recommendation = adjudicated.recommendation
            final.evidence_pages = adjudicated.evidence_pages
            final.evidence_text = adjudicated.evidence_text
            final.confidence = adjudicated.confidence
        validated_reviews.append(final.to_dict())

    result = dict(payload)
    result["merged_final_reviews"] = validated_reviews
    result["validation"] = {
        "mode": "audit_and_adjudicate" if adjudicate else "audit_only",
        "use_gpt": bool(getattr(llm_client, "is_configured", lambda: False)()),
    }
    return result


def primary_review_for_validation(final: FinalReview) -> ReviewResult:
    if final.reviews:
        return max(final.reviews, key=lambda review: (bool(review.evidence_pages), review.confidence))
    return ReviewResult(
        item_no=str(final.item_no),
        route_type="final_review",
        result=final.final_result,
        is_target=final.is_target,
        confidence=final.confidence,
        evidence_pages=list(final.evidence_pages),
        evidence_text=list(final.evidence_text),
        reason=final.reason,
        recommendation=final.recommendation,
        needs_human_review=final.final_status != "자동 확정 가능",
        source="merged_final_review",
    )


def routes_by_item(payload: dict[str, Any]) -> dict[str, str]:
    result = {
        str(item.get("item_no", "")): str(item.get("route", ""))
        for item in payload.get("item_results", [])
        if item.get("item_no")
    }
    if "2-1" in result and "2" not in result:
        result["2"] = result["2-1"]
    return result


def final_review_from_dict(data: dict[str, Any]) -> FinalReview:
    allowed = {field.name for field in fields(FinalReview)}
    values = {key: value for key, value in data.items() if key in allowed and key != "reviews"}
    values["reviews"] = [review_result_from_dict(item) for item in data.get("reviews", [])]
    return FinalReview(**values)


def review_result_from_dict(data: dict[str, Any]) -> ReviewResult:
    allowed = {field.name for field in fields(ReviewResult)}
    values = {key: value for key, value in data.items() if key in allowed}
    return ReviewResult(**values)


def validate_file(path: Path, output_dir: Path, llm_client: object, adjudicate: bool) -> Path:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("merged_final_reviews"), list):
        raise ValueError(f"Not a review result JSON: {path}")
    validated = validate_payload(payload, llm_client=llm_client, adjudicate=adjudicate)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{path.stem}.validated.json"
    output.write_text(json.dumps(validated, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate existing review-result JSON files with verification agents.")
    parser.add_argument("--input-glob", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--adjudicate", action="store_true")
    parser.add_argument("--no-api", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    paths = [Path(path) for path in sorted(glob.glob(args.input_glob))]
    llm_client = DisabledLlmClient() if args.no_api else OpenAILowCostClient()
    outputs = [validate_file(path, args.output_dir, llm_client, args.adjudicate) for path in paths]
    print(f"inputs={len(paths)} outputs={len(outputs)}")
    for output in outputs:
        print(output)


if __name__ == "__main__":
    main()
