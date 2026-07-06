from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CandidatePage:
    page_no: int
    page_text: str
    text_length: int
    rfp_printed_page_no: int | None = None
    has_table_candidate: bool = False
    has_attachment_candidate: bool = False
    has_eval_table_candidate: bool = False
    has_toc_candidate: bool = False
    has_blind_candidate: bool = False
    has_commercial_sw_candidate: bool = False
    parser_warning: str | None = None


@dataclass
class ParsedDocument:
    document_id: int
    document_name: str
    pdf_path: Path | None
    total_pages: int
    parse_status: str
    pages: list[CandidatePage] = field(default_factory=list)
    audit_score: int | None = None
    audit_warnings: list["AuditWarning"] = field(default_factory=list)


@dataclass
class AuditWarning:
    warning_type: str
    message: str
    page_no: int | None = None
    severity: str = "medium"
    related_item_nos: list[str] = field(default_factory=list)


@dataclass
class RagHit:
    item_no: str | None
    source_type: str
    source_name: str
    title: str
    category: str | None
    snippet: str
    page_or_row: str | None = None
    score: float | None = None


@dataclass
class RagContext:
    item_no: str
    hits: list[RagHit] = field(default_factory=list)


@dataclass
class ReviewResult:
    item_no: str
    route_type: str
    result: str
    is_target: bool | None
    confidence: float
    evidence_pages: list[int]
    evidence_text: list[str]
    reason: str
    recommendation: str
    needs_human_review: bool
    source: str
    warnings: list[str] = field(default_factory=list)
    used_llm: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FinalReview:
    item_no: str
    final_status: str
    final_result: str
    is_target: bool | None
    confidence: float
    evidence_pages: list[int]
    evidence_text: list[str]
    reason: str
    recommendation: str
    reviews: list[ReviewResult]
    warnings: list[str] = field(default_factory=list)
    verification_audit: "VerificationAudit | None" = None
    compliance_content: "ComplianceContent | None" = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditFinding:
    finding_type: str
    severity: str
    message: str
    atomic_requirement_id: str | None = None
    evidence_observed: list[str] = field(default_factory=list)
    suggested_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationAudit:
    item_no: str
    audited_review_source: str
    can_auto_accept: bool
    requires_adjudication: bool
    findings: list[AuditFinding] = field(default_factory=list)
    audit_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FinalAdjudication:
    item_no: str
    final_result: str
    atomic_requirement_assessment: list[dict[str, Any]]
    reason: str
    recommendation: str
    evidence_pages: list[int]
    evidence_text: list[str]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ComplianceContent:
    item_no: str
    content_type: str
    primary_evidence_pages: list[int]
    used_evidence_pages: list[int]
    compliance_content: str
    tacit_knowledge_used: list[str]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineSummary:
    document_id: int
    parse_status: str
    audit_score: int
    audit_warnings: list[AuditWarning]
    final_reviews: list[FinalReview]
    excel_path: Path
    compliance_contents: list[ComplianceContent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["excel_path"] = str(self.excel_path)
        return data
