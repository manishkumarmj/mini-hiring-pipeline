"""
Pipeline rules. All stage transitions MUST go through here.

Invariants enforced:
1. Forward-only, one stage at a time.
2. Terminal states (Rejected, Hired) can never be left.
3. Every transition writes an append-only StageEvent.
4. Rejection is allowed from any non-terminal stage.
5. Hired is reachable only from Offer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import (
    STAGE_ORDER,
    Candidate,
    CandidateStatus,
    EventType,
    Stage,
    StageEvent,
    utcnow,
)


# ---------- errors ----------

class PipelineError(Exception):
    """Base for rule violations. Message is user-facing."""


class TerminalStateError(PipelineError):
    pass


class InvalidTransitionError(PipelineError):
    pass


# ---------- result object ----------

@dataclass(frozen=True)
class TransitionResult:
    candidate_id: int
    from_stage: Stage | None
    to_stage: Stage | None
    event_type: EventType
    timestamp: datetime


# ---------- helpers ----------

def next_stage(stage: Stage) -> Stage | None:
    """Return the next stage in order, or None if terminal."""
    idx = STAGE_ORDER.index(stage)
    if idx + 1 >= len(STAGE_ORDER):
        return None
    return STAGE_ORDER[idx + 1]


def is_valid_move(current: Stage, target: Stage) -> bool:
    """Only the immediate next stage is allowed."""
    return next_stage(current) == target


def _record(
    session: Session,
    candidate: Candidate,
    *,
    event_type: EventType,
    from_stage: Stage | None,
    to_stage: Stage | None,
    note: str | None = None,
    ts: datetime | None = None,
) -> StageEvent:
    """Append one immutable event row. Never updates existing rows."""
    evt = StageEvent(
        candidate_id=candidate.id,
        event_type=event_type,
        from_stage=from_stage,
        to_stage=to_stage,
        note=note,
        timestamp=ts or utcnow(),
    )
    session.add(evt)
    return evt


def _assert_active(candidate: Candidate) -> None:
    if candidate.status == CandidateStatus.REJECTED:
        raise TerminalStateError(
            f"{candidate.name} was rejected and cannot move further."
        )
    if candidate.status == CandidateStatus.HIRED:
        raise TerminalStateError(
            f"{candidate.name} is already Hired. Final outcome cannot be reversed."
        )


# ---------- public API ----------

def add_candidate(
    session: Session,
    *,
    name: str,
    email: str,
    note: str | None = None,
) -> Candidate:
    """Create a candidate at Applied, with a CREATED event."""
    name = name.strip()
    email = email.strip().lower()
    if not name:
        raise PipelineError("Candidate name is required.")
    if not email or "@" not in email:
        raise PipelineError("A valid email is required.")

    existing = session.scalar(select(Candidate).where(Candidate.email == email))
    if existing:
        raise PipelineError(f"A candidate with email {email} already exists.")

    candidate = Candidate(
        name=name,
        email=email,
        current_stage=Stage.APPLIED,
        status=CandidateStatus.ACTIVE,
    )
    session.add(candidate)
    session.flush()  # get id

    _record(
        session,
        candidate,
        event_type=EventType.CREATED,
        from_stage=None,
        to_stage=Stage.APPLIED,
        note=note or "Candidate added.",
    )
    session.commit()
    session.refresh(candidate)
    return candidate


def advance(
    session: Session,
    candidate_id: int,
    *,
    note: str | None = None,
    ts: datetime | None = None,
) -> TransitionResult:
    """Move candidate exactly one stage forward."""
    candidate = session.get(Candidate, candidate_id)
    if not candidate:
        raise PipelineError(f"Candidate {candidate_id} not found.")

    _assert_active(candidate)

    target = next_stage(candidate.current_stage)
    if target is None:
        raise InvalidTransitionError(
            f"{candidate.name} is already at the final stage ({candidate.current_stage.value})."
        )

    from_stage = candidate.current_stage
    candidate.current_stage = target
    candidate.stage_entered_at = ts or utcnow()

    if target == Stage.HIRED:
        candidate.status = CandidateStatus.HIRED

    _record(
        session,
        candidate,
        event_type=EventType.MOVED,
        from_stage=from_stage,
        to_stage=target,
        note=note,
        ts=ts,
    )
    session.commit()
    session.refresh(candidate)

    return TransitionResult(
        candidate_id=candidate.id,
        from_stage=from_stage,
        to_stage=target,
        event_type=EventType.MOVED,
        timestamp=candidate.stage_entered_at,
    )


def reject(
    session: Session,
    candidate_id: int,
    *,
    note: str | None = None,
    ts: datetime | None = None,
) -> TransitionResult:
    """Reject a candidate from any non-terminal stage."""
    candidate = session.get(Candidate, candidate_id)
    if not candidate:
        raise PipelineError(f"Candidate {candidate_id} not found.")

    _assert_active(candidate)

    from_stage = candidate.current_stage
    candidate.status = CandidateStatus.REJECTED
    candidate.stage_entered_at = ts or utcnow()

    _record(
        session,
        candidate,
        event_type=EventType.REJECTED,
        from_stage=from_stage,
        to_stage=None,
        note=note,
        ts=ts,
    )
    session.commit()
    session.refresh(candidate)

    return TransitionResult(
        candidate_id=candidate.id,
        from_stage=from_stage,
        to_stage=None,
        event_type=EventType.REJECTED,
        timestamp=candidate.stage_entered_at,
    )


def history(session: Session, candidate_id: int) -> list[StageEvent]:
    """Return the full audit trail, oldest → newest."""
    return list(
        session.scalars(
            select(StageEvent)
            .where(StageEvent.candidate_id == candidate_id)
            .order_by(StageEvent.timestamp.asc(), StageEvent.id.asc())
        )
    )


def stage_durations(session: Session, candidate_id: int) -> list[dict]:
    """
    Compute how long the candidate spent in each stage.
    Last row (if candidate is still active) is ongoing.
    """
    events = history(session, candidate_id)
    durations: list[dict] = []
    now = utcnow()

    def _aware(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    for i, evt in enumerate(events):
        if evt.to_stage is None:
            continue  # rejection event closes previous stage, no new stage entered
        entered = _aware(evt.timestamp)
        if i + 1 < len(events):
            left = _aware(events[i + 1].timestamp)
            ongoing = False
        else:
            left = now
            ongoing = True
        durations.append(
            {
                "stage": evt.to_stage,
                "entered_at": entered,
                "left_at": None if ongoing else left,
                "days": (left - entered).total_seconds() / 86400.0,
                "ongoing": ongoing,
            }
        )
    return durations