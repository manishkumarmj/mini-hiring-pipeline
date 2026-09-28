"""
ORM models.

Three tables:
- candidates   : current state of each candidate (mutable row)
- stage_events : append-only audit trail (never updated, never deleted)
- notes        : append-only scoped notes (board / stage / search / candidate)
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base


# ---------- enums ----------

class Stage(str, enum.Enum):
    APPLIED = "Applied"
    SCREENING = "Screening"
    INTERVIEW = "Interview"
    OFFER = "Offer"
    HIRED = "Hired"


STAGE_ORDER = [Stage.APPLIED, Stage.SCREENING, Stage.INTERVIEW, Stage.OFFER, Stage.HIRED]


class CandidateStatus(str, enum.Enum):
    ACTIVE = "active"
    REJECTED = "rejected"
    HIRED = "hired"


class EventType(str, enum.Enum):
    CREATED = "created"
    MOVED = "moved"
    REJECTED = "rejected"


# ---------- helpers ----------

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------- models ----------

class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)

    current_stage: Mapped[Stage] = mapped_column(
        SAEnum(Stage, native_enum=False, length=20),
        nullable=False,
        default=Stage.APPLIED,
        index=True,
    )
    status: Mapped[CandidateStatus] = mapped_column(
        SAEnum(CandidateStatus, native_enum=False, length=20),
        nullable=False,
        default=CandidateStatus.ACTIVE,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    stage_entered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    events: Mapped[list["StageEvent"]] = relationship(
        "StageEvent",
        back_populates="candidate",
        order_by="StageEvent.timestamp",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def days_in_stage(self) -> float:
        entered = self.stage_entered_at
        if entered.tzinfo is None:
            entered = entered.replace(tzinfo=timezone.utc)
        delta = utcnow() - entered
        return delta.total_seconds() / 86400.0

    @property
    def is_terminal(self) -> bool:
        return self.status in (CandidateStatus.REJECTED, CandidateStatus.HIRED)

    def __repr__(self) -> str:
        return (
            f"<Candidate {self.id} {self.name!r} "
            f"stage={self.current_stage.value} status={self.status.value}>"
        )


class StageEvent(Base):
    """Append-only audit trail. Never UPDATE, never DELETE."""
    __tablename__ = "stage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )

    event_type: Mapped[EventType] = mapped_column(
        SAEnum(EventType, native_enum=False, length=20), nullable=False
    )
    from_stage: Mapped[Stage | None] = mapped_column(
        SAEnum(Stage, native_enum=False, length=20), nullable=True
    )
    to_stage: Mapped[Stage | None] = mapped_column(
        SAEnum(Stage, native_enum=False, length=20), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    candidate: Mapped[Candidate] = relationship("Candidate", back_populates="events")

    __table_args__ = (Index("ix_stage_events_to_stage_ts", "to_stage", "timestamp"),)

    def __repr__(self) -> str:
        return (
            f"<StageEvent {self.id} cand={self.candidate_id} "
            f"{self.event_type.value} {self.from_stage}->{self.to_stage} @{self.timestamp}>"
        )


class Note(Base):
    """
    Append-only scoped notes.

    scope examples:
      - "board"               → notes on the full pipeline board
      - "stage:Interview"     → notes on the Interview section
      - "stage:Rejected"      → notes on the Rejected section
      - "search"              → notes on the search page
      - "candidate:7"         → notes for a specific candidate
    """
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    def __repr__(self) -> str:
        return f"<Note {self.id} scope={self.scope!r} @{self.created_at}>"