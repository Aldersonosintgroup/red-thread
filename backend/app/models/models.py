import enum
import uuid
from datetime import datetime, date

from sqlalchemy import (
    Column, String, Float, Integer, Boolean, Date, DateTime, ForeignKey,
    Text, Enum as SAEnum, JSON,
)
from sqlalchemy.orm import relationship

from app.core.db import Base


def gen_id() -> str:
    return str(uuid.uuid4())


class DocumentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    EXTRACTED = "extracted"
    REVIEWED = "reviewed"
    ERROR = "error"


class FlagType(str, enum.Enum):
    TIMELINE_IRREGULARITY = "TIMELINE_IRREGULARITY"
    PRE_BIRTH_PETITION = "PRE_BIRTH_PETITION_ANOMALY"
    FINANCIAL_ANOMALY = "FINANCIAL_ANOMALY"
    ENTITY_MATCH = "ENTITY_MATCH"
    CONTRADICTION = "CONTRADICTION"
    LEGAL_VIOLATION = "LEGAL_NON_COMPLIANCE"
    # Raised by the investigator from a testimony or verified finding; shown
    # with the other flags but kept out of the document-based score.
    INVESTIGATOR_FINDING = "INVESTIGATOR_FINDING"


class FlagSeverity(str, enum.Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class WatchlistCategory(str, enum.Enum):
    RED = "RED"
    ORANGE = "ORANGE"
    YELLOW = "YELLOW"


class Case(Base):
    __tablename__ = "cases"

    id = Column(String, primary_key=True, default=gen_id)
    case_number = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=False)
    status = Column(String, default="active")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    subject = relationship("Subject", back_populates="case", uselist=False, cascade="all, delete-orphan")
    actors = relationship("Actor", back_populates="case", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="case", cascade="all, delete-orphan")
    timeline_events = relationship("TimelineEvent", back_populates="case", cascade="all, delete-orphan")
    flags = relationship("Flag", back_populates="case", cascade="all, delete-orphan")
    edges = relationship("ActorEdge", back_populates="case", cascade="all, delete-orphan")
    score = relationship("CaseScore", back_populates="case", uselist=False, cascade="all, delete-orphan")
    analyses = relationship("CaseAnalysis", cascade="all, delete-orphan")
    statements = relationship("Statement", back_populates="case", cascade="all, delete-orphan",
                              order_by="Statement.created_at")


class Subject(Base):
    """Mandatory case subject profile. Always the center node of the network map."""
    __tablename__ = "subjects"

    id = Column(String, primary_key=True, default=gen_id)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False)
    full_name = Column(String, nullable=False)
    aliases = Column(JSON, default=list)
    date_of_birth = Column(Date, nullable=True)
    birth_place = Column(String, nullable=True)
    notes = Column(Text, nullable=True)

    case = relationship("Case", back_populates="subject")


class Actor(Base):
    """A deduplicated person/organization node in the case network."""
    __tablename__ = "actors"

    id = Column(String, primary_key=True, default=gen_id)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False)
    canonical_name = Column(String, nullable=False)
    aliases = Column(JSON, default=list)  # raw name variants merged into this actor
    role = Column(String, nullable=True)  # Attorney, Judge, Hospital, Agency, Foster, Broker, etc.
    notes = Column(Text, nullable=True)
    is_subject = Column(Boolean, default=False)
    custom_color = Column(String, nullable=True)  # hex color, used when the map's color mode is "Custom"
    watchlist_match_id = Column(String, ForeignKey("watchlist_entities.id"), nullable=True)
    watchlist_match_score = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    case = relationship("Case", back_populates="actors")
    watchlist_match = relationship("WatchlistEntity")
    mentions = relationship("ActorMention", back_populates="actor", cascade="all, delete-orphan")


class ActorMention(Base):
    """One raw-text occurrence of an actor's name within a specific document."""
    __tablename__ = "actor_mentions"

    id = Column(String, primary_key=True, default=gen_id)
    actor_id = Column(String, ForeignKey("actors.id"), nullable=False)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    raw_text = Column(String, nullable=False)
    role_in_document = Column(String, nullable=True)

    actor = relationship("Actor", back_populates="mentions")


class ActorEdge(Base):
    """A relationship/connection between two actors (or an actor and the subject)."""
    __tablename__ = "actor_edges"

    id = Column(String, primary_key=True, default=gen_id)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False)
    source_actor_id = Column(String, ForeignKey("actors.id"), nullable=False)
    target_actor_id = Column(String, ForeignKey("actors.id"), nullable=False)
    relationship_type = Column(String, nullable=True)
    document_id = Column(String, ForeignKey("documents.id"), nullable=True)

    case = relationship("Case", back_populates="edges")


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=gen_id)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False)
    filename = Column(String, nullable=False)
    filepath = Column(String, nullable=False)
    doc_type = Column(String, nullable=True)  # inferred: petition, decree, receipt, correspondence, etc.
    upload_order = Column(Integer, nullable=False)
    status = Column(SAEnum(DocumentStatus), default=DocumentStatus.PENDING)
    error_message = Column(Text, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    raw_extraction = Column(JSON, nullable=True)   # unedited AI output
    edited_extraction = Column(JSON, nullable=True)  # user-edited, committed version
    committed = Column(Boolean, default=False)
    phash = Column(String, nullable=True)  # perceptual hash, for duplicate-image detection
    rotation = Column(Integer, default=0)  # degrees clockwise applied so far, for display only

    case = relationship("Case", back_populates="documents")

    @property
    def has_file(self) -> bool:
        # Manual entries (no scanned source) store filepath as "" rather than
        # NULL, so a migration to relax the NOT NULL constraint isn't needed.
        return bool(self.filepath)


class TimelineEvent(Base):
    __tablename__ = "timeline_events"

    id = Column(String, primary_key=True, default=gen_id)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False)
    event_type = Column(String, nullable=False)  # birth, petition_filed, decree_issued, payment, other
    event_date = Column(Date, nullable=True)
    description = Column(Text, nullable=True)
    source_document_id = Column(String, ForeignKey("documents.id"), nullable=True)
    # Excluded by the investigator as noise (e.g. a certified copy's issue
    # date): kept on record, but left out of the timeline flags.
    excluded = Column(Boolean, default=False, nullable=False)

    case = relationship("Case", back_populates="timeline_events")


class Flag(Base):
    __tablename__ = "flags"

    id = Column(String, primary_key=True, default=gen_id)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False)
    flag_type = Column(SAEnum(FlagType), nullable=False)
    severity = Column(SAEnum(FlagSeverity), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    related_document_id = Column(String, ForeignKey("documents.id"), nullable=True)
    related_actor_id = Column(String, ForeignKey("actors.id"), nullable=True)
    legal_reference = Column(String, nullable=True)  # e.g. "Decree 2465 (1979)"
    created_at = Column(DateTime, default=datetime.utcnow)

    case = relationship("Case", back_populates="flags")


class Statement(Base):
    """Evidence that isn't a scanned document: testimony (what a person said)
    or a finding the investigator verified (e.g. by DNA test or a registry
    check). Entered by a person, so it needs no review step."""
    __tablename__ = "statements"

    id = Column(String, primary_key=True, default=gen_id)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False)
    kind = Column(String, nullable=False)  # testimony | finding
    statement = Column(Text, nullable=False)
    source_name = Column(String, nullable=True)  # who said it / who verified it
    source_relationship = Column(String, nullable=True)  # e.g. adoptive mother, investigator
    statement_date = Column(Date, nullable=True)  # when it was said or verified
    method = Column(String, nullable=True)  # interview, sworn statement, DNA test, registry check...
    basis = Column(String, nullable=True)  # testimony: firsthand | secondhand | unknown
    status = Column(String, nullable=False, default="unverified")  # unverified | corroborated | verified
    relation = Column(String, nullable=False, default="context")  # supports | contradicts | context
    related_document_ids = Column(JSON, default=list)
    related_actor_ids = Column(JSON, default=list)
    flag_severity = Column(String, nullable=True)  # CRITICAL/HIGH/MEDIUM/LOW raises a flag; None doesn't
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    case = relationship("Case", back_populates="statements")


class CaseAnalysis(Base):
    """A saved AI analysis of a case, with what it was based on."""
    __tablename__ = "case_analyses"

    id = Column(String, primary_key=True, default=gen_id)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    language = Column(String, nullable=False)
    model = Column(String, nullable=False)
    input_hash = Column(String, nullable=False)  # SHA-256 of the exact case record analysed
    document_count = Column(Integer, nullable=False)
    report = Column(JSON, nullable=False)
    citation_check = Column(JSON, nullable=False)
    disclaimer = Column(Text, nullable=False)
    dossier = Column(Text, nullable=False)  # the case record as sent, for audit


class CaseScore(Base):
    __tablename__ = "case_scores"

    id = Column(String, primary_key=True, default=gen_id)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False, unique=True)
    timeline_score = Column(Float, default=0.0)
    entity_match_score = Column(Float, default=0.0)
    financial_score = Column(Float, default=0.0)
    contradiction_score = Column(Float, default=0.0)
    legal_score = Column(Float, default=0.0)
    total_score = Column(Float, default=0.0)
    computed_at = Column(DateTime, default=datetime.utcnow)

    case = relationship("Case", back_populates="score")


class WatchlistEntity(Base):
    """User-editable, private, local BOLO list of previously-investigated entities."""
    __tablename__ = "watchlist_entities"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    aliases = Column(JSON, default=list)
    category = Column(SAEnum(WatchlistCategory), nullable=False)
    entity_type = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    is_seed = Column(Boolean, default=False)  # seeded default vs user-added


class CrossCaseDecision(Base):
    """The investigator's call on whether two actors in different cases are
    the same person. Keyed by case and folded name (not actor id) so it
    survives Re-read all, which recreates a case's actors."""
    __tablename__ = "cross_case_decisions"

    id = Column(String, primary_key=True, default=gen_id)
    case_a_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    name_a = Column(String, nullable=False)
    case_b_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    name_b = Column(String, nullable=False)
    decision = Column(String, nullable=False)  # "confirmed" | "rejected"
    created_at = Column(DateTime, default=datetime.utcnow)
