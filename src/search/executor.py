"""
Execute a SearchQuery against the DB.

Pipeline:
1. Build a base SQLAlchemy select() from the structured filters.
2. Fetch matching candidates.
3. Apply fuzzy name scoring (rapidfuzz) if name_query is set.
4. Rank results and return them with a per-row score + reasons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from rapidfuzz import fuzz, process
from sqlalchemy import and_, exists, select
from sqlalchemy.orm import Session

from src.models import (
    Candidate,
    CandidateStatus,
    EventType,
    Stage,
    StageEvent,
    utcnow,
)
from src.search.grammar import FUZZY
from src.search.parser import SearchQuery


# ---------- result object ----------

@dataclass
class SearchHit:
    candidate: Candidate
    score: float                       # 0..100+, higher = better
    reasons: list[str] = field(default_factory=list)


# ---------- public entry ----------

def execute(session: Session, query: SearchQuery) -> list[SearchHit]:
    """Run the query and return ranked SearchHits."""

    # 1. SQL-level filters (cheap, indexed)
    stmt = select(Candidate)
    conditions = _build_conditions(query)

    if conditions:
        stmt = stmt.where(and_(*conditions))

    stmt = stmt.order_by(Candidate.stage_entered_at.asc())  # default tiebreak

    candidates: list[Candidate] = list(session.scalars(stmt).unique())

    # 2. If no name filter, we're done — score by specificity
    if not query.name_query:
        return [_score_structured(c, query) for c in candidates]

    # 3. Name filter: fuzzy score each candidate's name
    names = [c.name for c in candidates]
    matches = process.extract(
        query.name_query,
        names,
        scorer=getattr(fuzz, FUZZY.scorer),
        limit=None,
        score_cutoff=FUZZY.name_threshold,
    )

    hits: list[SearchHit] = []
    for name, score, idx in matches:
        c = candidates[idx]
        hit = _score_structured(c, query)
        # blend: name score dominates, structured filters add confidence
        hit.score = round(score + hit.score * 0.2, 2)
        hit.reasons.insert(0, f"name ≈ '{query.name_query}' ({score:.0f})")
        hits.append(hit)

    hits.sort(key=lambda h: (-h.score, h.candidate.name))
    return hits[: FUZZY.name_result_limit] if not query.universal else hits


# ---------- condition builder ----------

def _build_conditions(query: SearchQuery) -> list:
    """Translate SearchQuery into SQLAlchemy boolean conditions."""
    conds: list = []

    # --- stage filters ---
    if query.in_stage is not None:
        conds.append(Candidate.current_stage == query.in_stage)

    if query.stuck_in_stage is not None:
        conds.append(Candidate.current_stage == query.stuck_in_stage)
        # min/max days handled after fetch (uses stage_entered_at, timezone-aware)

    # --- outcome filters ---
    if query.exclude_statuses:
        for s in query.exclude_statuses:
            conds.append(Candidate.status != CandidateStatus(s))

    if query.only_statuses:
        conds.append(Candidate.status.in_([CandidateStatus(s) for s in query.only_statuses]))

    if query.not_hired:
        # exclude Hired; leave status as-is (could be active or rejected)
        conds.append(Candidate.status != CandidateStatus.HIRED)

    # --- "reached X" — candidate must have at least one event into X ---
    if query.reached_stage is not None:
        conds.append(
            exists().where(
                and_(
                    StageEvent.candidate_id == Candidate.id,
                    StageEvent.to_stage == query.reached_stage,
                )
            )
        )
        # "but not hired" already handled by not_hired above

    # --- "moved to X since Y" — event into X, timestamp >= Y ---
    if query.moved_to_stage is not None:
        evt_conds = [
            StageEvent.candidate_id == Candidate.id,
            StageEvent.to_stage == query.moved_to_stage,
        ]
        if query.moved_since is not None:
            evt_conds.append(StageEvent.timestamp >= query.moved_since)
        conds.append(exists().where(and_(*evt_conds)))

    return conds


# ---------- time-based filtering (needs timezone-aware math) ----------

def _days_in_stage(candidate: Candidate, now: datetime | None = None) -> float:
    now = now or utcnow()
    entered = candidate.stage_entered_at
    if entered.tzinfo is None:
        entered = entered.replace(tzinfo=timezone.utc)
    return (now - entered).total_seconds() / 86400.0


def _passes_day_window(candidate: Candidate, query: SearchQuery) -> bool:
    """min/max days applied in Python for timezone safety."""
    if query.min_days_in_stage is None and query.max_days_in_stage is None:
        return True
    days = _days_in_stage(candidate)
    if query.min_days_in_stage is not None and days < query.min_days_in_stage:
        return False
    if query.max_days_in_stage is not None and days > query.max_days_in_stage:
        return False
    return True


# ---------- scoring ----------

def _score_structured(candidate: Candidate, query: SearchQuery) -> SearchHit:
    """Score a candidate on structured filters alone (no name)."""
    score = 0.0
    reasons: list[str] = []

    if not _passes_day_window(candidate, query):
        # filtered out at SQL+Python boundary; caller shouldn't see it
        return SearchHit(candidate=candidate, score=-1, reasons=["outside day window"])

    if query.in_stage and candidate.current_stage == query.in_stage:
        score += 50
        reasons.append(f"in {candidate.current_stage.value}")

    if query.stuck_in_stage and candidate.current_stage == query.stuck_in_stage:
        days = _days_in_stage(candidate)
        # longer stuck = higher priority for the recruiter
        score += min(50, 20 + days)
        reasons.append(f"stuck in {candidate.current_stage.value} for {days:.1f}d")

    if query.moved_to_stage:
        score += 30
        reasons.append(f"moved to {query.moved_to_stage.value}")

    if query.reached_stage:
        score += 20
        reasons.append(f"reached {query.reached_stage.value}")

    if query.not_hired:
        score += 15
        reasons.append("not hired")

    if query.exclude_statuses:
        score += 5
        reasons.append("matches exclusion")

    return SearchHit(candidate=candidate, score=score, reasons=reasons)