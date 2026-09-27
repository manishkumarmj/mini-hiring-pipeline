"""
Tests for src.pipeline — the transition rules.

Run:
    pytest tests/test_pipeline.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db import Base
from src.models import (
    Candidate,
    CandidateStatus,
    EventType,
    Stage,
)
from src.pipeline import (
    InvalidTransitionError,
    PipelineError,
    TerminalStateError,
    add_candidate,
    advance,
    history,
    next_stage,
    reject,
    stage_durations,
)


# ---------- fixtures ----------

@pytest.fixture()
def session():
    """Fresh in-memory SQLite per test."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, future=True)
    s = Session()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def candidate(session):
    return add_candidate(session, name="Priya Sharma", email="priya@example.com")


# ---------- next_stage ----------

def test_next_stage_walks_pipeline():
    assert next_stage(Stage.APPLIED) == Stage.SCREENING
    assert next_stage(Stage.SCREENING) == Stage.INTERVIEW
    assert next_stage(Stage.INTERVIEW) == Stage.OFFER
    assert next_stage(Stage.OFFER) == Stage.HIRED
    assert next_stage(Stage.HIRED) is None


# ---------- add_candidate ----------

def test_add_candidate_starts_at_applied(session):
    c = add_candidate(session, name="Aarav Mehta", email="aarav@example.com")
    assert c.current_stage == Stage.APPLIED
    assert c.status == CandidateStatus.ACTIVE
    assert len(history(session, c.id)) == 1
    assert history(session, c.id)[0].event_type == EventType.CREATED


def test_add_candidate_rejects_blank_name(session):
    with pytest.raises(PipelineError):
        add_candidate(session, name="  ", email="x@example.com")


def test_add_candidate_rejects_bad_email(session):
    with pytest.raises(PipelineError):
        add_candidate(session, name="X Y", email="not-an-email")


def test_add_candidate_rejects_duplicate_email(session, candidate):
    with pytest.raises(PipelineError):
        add_candidate(session, name="Priya Again", email="priya@example.com")


# ---------- advance: happy path ----------

def test_advance_moves_one_stage(session, candidate):
    advance(session, candidate.id)
    session.refresh(candidate)
    assert candidate.current_stage == Stage.SCREENING
    assert candidate.status == CandidateStatus.ACTIVE


def test_advance_all_the_way_to_hired(session, candidate):
    for _ in range(4):  # Applied → Screening → Interview → Offer → Hired
        advance(session, candidate.id)
    session.refresh(candidate)
    assert candidate.current_stage == Stage.HIRED
    assert candidate.status == CandidateStatus.HIRED


def test_advance_sets_hired_status_on_final_move(session, candidate):
    for _ in range(3):
        advance(session, candidate.id)
    session.refresh(candidate)
    assert candidate.current_stage == Stage.OFFER
    assert candidate.status == CandidateStatus.ACTIVE  # not hired yet
    advance(session, candidate.id)
    session.refresh(candidate)
    assert candidate.status == CandidateStatus.HIRED


def test_advance_writes_event(session, candidate):
    advance(session, candidate.id)
    events = history(session, candidate.id)
    assert len(events) == 2
    moved = events[-1]
    assert moved.event_type == EventType.MOVED
    assert moved.from_stage == Stage.APPLIED
    assert moved.to_stage == Stage.SCREENING


def test_advance_updates_stage_entered_at(session, candidate):
    before = candidate.stage_entered_at
    advance(session, candidate.id)
    session.refresh(candidate)
    assert candidate.stage_entered_at >= before


# ---------- advance: guardrails ----------

def test_cannot_advance_past_hired(session, candidate):
    for _ in range(4):
        advance(session, candidate.id)
    with pytest.raises(TerminalStateError):
        advance(session, candidate.id)


def test_cannot_advance_rejected(session, candidate):
    reject(session, candidate.id)
    with pytest.raises(TerminalStateError):
        advance(session, candidate.id)


def test_advance_unknown_candidate(session):
    with pytest.raises(PipelineError):
        advance(session, 9999)


# ---------- reject: happy path ----------

def test_reject_from_applied(session, candidate):
    reject(session, candidate.id)
    session.refresh(candidate)
    assert candidate.status == CandidateStatus.REJECTED
    assert candidate.current_stage == Stage.APPLIED  # stays on last stage
    assert candidate.is_terminal


def test_reject_from_offer(session, candidate):
    for _ in range(3):
        advance(session, candidate.id)
    reject(session, candidate.id)
    session.refresh(candidate)
    assert candidate.status == CandidateStatus.REJECTED
    assert candidate.current_stage == Stage.OFFER


def test_reject_writes_event(session, candidate):
    reject(session, candidate.id, note="No fit")
    events = history(session, candidate.id)
    assert len(events) == 2
    rej = events[-1]
    assert rej.event_type == EventType.REJECTED
    assert rej.from_stage == Stage.APPLIED
    assert rej.to_stage is None
    assert rej.note == "No fit"


# ---------- reject: guardrails ----------

def test_cannot_reject_twice(session, candidate):
    reject(session, candidate.id)
    with pytest.raises(TerminalStateError):
        reject(session, candidate.id)


def test_cannot_reject_hired(session, candidate):
    for _ in range(4):
        advance(session, candidate.id)
    with pytest.raises(TerminalStateError):
        reject(session, candidate.id)


def test_reject_unknown_candidate(session):
    with pytest.raises(PipelineError):
        reject(session, 9999)


# ---------- history ----------

def test_history_is_append_only(session, candidate):
    """Every action adds a row; nothing is ever modified or removed."""
    advance(session, candidate.id)
    advance(session, candidate.id)
    reject(session, candidate.id)

    events = history(session, candidate.id)
    types = [e.event_type for e in events]
    assert types == [
        EventType.CREATED,
        EventType.MOVED,
        EventType.MOVED,
        EventType.REJECTED,
    ]


def test_history_ordered_oldest_first(session, candidate):
    advance(session, candidate.id)
    advance(session, candidate.id)
    events = history(session, candidate.id)
    timestamps = [e.timestamp for e in events]
    assert timestamps == sorted(timestamps)


# ---------- stage_durations ----------

def test_stage_durations_for_active_candidate(session, candidate):
    advance(session, candidate.id)
    durations = stage_durations(session, candidate.id)

    # one closed (Applied) + one ongoing (Screening)
    assert len(durations) == 2
    assert durations[0]["stage"] == Stage.APPLIED
    assert durations[0]["ongoing"] is False
    assert durations[1]["stage"] == Stage.SCREENING
    assert durations[1]["ongoing"] is True


def test_stage_durations_does_not_add_row_for_rejection(session, candidate):
    reject(session, candidate.id)
    durations = stage_durations(session, candidate.id)
    # Only "Applied" is counted; rejection has no to_stage
    assert len(durations) == 1
    assert durations[0]["stage"] == Stage.APPLIED
    assert durations[0]["ongoing"] is True  # still counted as last known stage


def test_stage_durations_accumulates_correctly(session, candidate):
    """Backdate events and verify day math."""
    now = datetime.now(timezone.utc)
    advance(session, candidate.id, ts=now - timedelta(days=5))
    advance(session, candidate.id, ts=now - timedelta(days=2))

    durations = stage_durations(session, candidate.id)
    by_stage = {d["stage"]: d for d in durations}

    # Applied: entered at creation, left 5 days ago → ~0 days
    assert by_stage[Stage.APPLIED]["days"] < 0.1
    # Screening: entered 5d ago, left 2d ago → ~3 days
    assert 2.9 < by_stage[Stage.SCREENING]["days"] < 3.1
    # Interview: entered 2d ago, ongoing
    assert by_stage[Stage.INTERVIEW]["ongoing"] is True
    assert 1.9 < by_stage[Stage.INTERVIEW]["days"] < 2.1