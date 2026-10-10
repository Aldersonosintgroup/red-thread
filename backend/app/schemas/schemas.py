from datetime import date, datetime
from typing import Optional, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Case / Subject ----------

class SubjectCreate(BaseModel):
    full_name: str
    aliases: list[str] = []
    date_of_birth: Optional[date] = None
    birth_place: Optional[str] = None
    notes: Optional[str] = None


class SubjectOut(ORMBase, SubjectCreate):
    id: str
    case_id: str


class CaseCreate(BaseModel):
    case_number: str
    title: str
    subject: SubjectCreate


class CaseSummary(ORMBase):
    id: str
    case_number: str
    title: str
    status: str
    created_at: datetime
    updated_at: datetime


class CaseDetail(CaseSummary):
    subject: Optional[SubjectOut] = None
    notes: Optional[str] = None


class CaseUpdate(BaseModel):
    notes: Optional[str] = None


# ---------- Actors ----------

class ActorOut(ORMBase):
    id: str
    case_id: str
    canonical_name: str
    aliases: list[str] = []
    role: Optional[str] = None
    notes: Optional[str] = None
    is_subject: bool = False
    custom_color: Optional[str] = None
    watchlist_match_id: Optional[str] = None
    watchlist_match_score: Optional[float] = None


class ActorUpdate(BaseModel):
    canonical_name: Optional[str] = None
    role: Optional[str] = None
    notes: Optional[str] = None
    custom_color: Optional[str] = None


class ActorMergeRequest(BaseModel):
    source_actor_id: str
    target_actor_id: str


class MergeSuggestion(BaseModel):
    actor_a: ActorOut
    actor_b: ActorOut
    score: float


class EdgeOut(ORMBase):
    id: str
    source_actor_id: str
    target_actor_id: str
    relationship_type: Optional[str] = None


# ---------- Documents / Extraction ----------

class ExtractedEntity(BaseModel):
    name: str
    role: Optional[str] = None
    page: Optional[int] = None  # 1-based PDF page the name was read from


class ExtractedPayment(BaseModel):
    amount: Optional[str] = None
    currency: Optional[str] = None
    description: Optional[str] = None
    linked_case_number: Optional[str] = None
    page: Optional[int] = None


class ExtractionResult(BaseModel):
    """Normalized shape the extraction service guarantees, regardless of what
    the vision model actually returned (fallback-filled if parsing fails)."""
    doc_type: Optional[str] = None
    names: list[ExtractedEntity] = []
    # [{"label": "...", "date": "YYYY-MM-DD" | None, "raw": original wording,
    #   "note": ambiguity/unreadable explanation, "page": 1-based PDF page}]
    dates: list[dict[str, Any]] = []
    financial_transactions: list[ExtractedPayment] = []
    legal_references: list[str] = []
    raw_text_notes: Optional[str] = None
    parse_warning: Optional[str] = None
    extracted_by: Optional[str] = None  # "<provider>:<model>" that read the document, for provenance


class DocumentOut(ORMBase):
    id: str
    case_id: str
    filename: str
    doc_type: Optional[str] = None
    upload_order: int
    status: str
    error_message: Optional[str] = None
    uploaded_at: datetime
    processed_at: Optional[datetime] = None
    raw_extraction: Optional[dict[str, Any]] = None
    edited_extraction: Optional[dict[str, Any]] = None
    committed: bool = False
    rotation: int = 0
    has_file: bool = True


class DuplicateDocumentSuggestion(BaseModel):
    document_a: DocumentOut
    document_b: DocumentOut
    distance: int


class DocumentCommitRequest(BaseModel):
    edited_extraction: ExtractionResult


class ManualDocumentCreate(BaseModel):
    label: str


# ---------- Timeline ----------

class TimelineEventOut(ORMBase):
    id: str
    event_type: str
    event_date: Optional[date] = None
    description: Optional[str] = None
    source_document_id: Optional[str] = None
    excluded: bool = False


class TimelineExcludeRequest(BaseModel):
    event_ids: list[str]
    excluded: bool


class TimelineCleanupRequest(BaseModel):
    redate: bool = True
    relabel: bool = True


# ---------- Flags ----------

class FlagOut(ORMBase):
    id: str
    flag_type: str
    severity: str
    title: str
    description: Optional[str] = None
    related_document_id: Optional[str] = None
    related_actor_id: Optional[str] = None
    legal_reference: Optional[str] = None
    created_at: datetime


# ---------- Statements (testimony and verified findings) ----------

StatementKind = Literal["testimony", "finding"]
StatementBasis = Literal["firsthand", "secondhand", "unknown"]
StatementStatus = Literal["unverified", "corroborated", "verified"]
StatementRelation = Literal["supports", "contradicts", "context"]
Severity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]


class StatementIn(BaseModel):
    kind: StatementKind
    statement: str = Field(min_length=1)
    source_name: Optional[str] = None
    source_relationship: Optional[str] = None
    statement_date: Optional[date] = None
    method: Optional[str] = None
    basis: Optional[StatementBasis] = None
    status: StatementStatus = "unverified"
    relation: StatementRelation = "context"
    related_document_ids: list[str] = []
    related_actor_ids: list[str] = []
    flag_severity: Optional[Severity] = None


class StatementOut(ORMBase):
    id: str
    case_id: str
    kind: str
    statement: str
    source_name: Optional[str] = None
    source_relationship: Optional[str] = None
    statement_date: Optional[date] = None
    method: Optional[str] = None
    basis: Optional[str] = None
    status: str
    relation: str
    related_document_ids: list[str] = []
    related_actor_ids: list[str] = []
    flag_severity: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


# ---------- Scoring ----------

class CaseScoreOut(ORMBase):
    timeline_score: float
    entity_match_score: float
    financial_score: float
    contradiction_score: float
    legal_score: float
    total_score: float
    computed_at: datetime


# ---------- Watchlist ----------

class WatchlistEntityCreate(BaseModel):
    name: str
    aliases: list[str] = []
    category: str
    entity_type: Optional[str] = None
    notes: Optional[str] = None


class WatchlistEntityOut(ORMBase, WatchlistEntityCreate):
    id: str
    is_seed: bool = False


# ---------- Settings ----------

class AppSettingsOut(BaseModel):
    ai_provider: str
    ollama_vision_model: str
    claude_vision_model: str
    gemini_vision_model: str
    openai_vision_model: str
    xai_model: str
    custom_base_url: str
    custom_model: str
    encryption_enabled: bool
    anthropic_key_configured: bool
    gemini_key_configured: bool
    openai_key_configured: bool
    xai_key_configured: bool
    custom_key_configured: bool


class AppSettingsUpdate(BaseModel):
    ai_provider: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    xai_api_key: Optional[str] = None
    custom_api_key: Optional[str] = None
    claude_vision_model: Optional[str] = None
    gemini_vision_model: Optional[str] = None
    openai_vision_model: Optional[str] = None
    xai_model: Optional[str] = None
    custom_base_url: Optional[str] = None
    custom_model: Optional[str] = None


class ProviderTestOut(BaseModel):
    ok: bool
    message: str


# ---------- Discrepancy engine ----------

class DiscrepancyRow(BaseModel):
    field: str
    document_id: str
    document_filename: str
    value: str


class DiscrepancyGroup(BaseModel):
    field: str
    rows: list[DiscrepancyRow]
    is_contradictory: bool
