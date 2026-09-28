"""
Pipeline board.

Two modes:
- Full board: everyone grouped by stage column (default)
- Filtered:  search results, ranked, with "why it matched" reasons

Each card exposes: Open, Advance, Reject.
"""

from __future__ import annotations

import streamlit as st
from sqlalchemy.orm import Session

from src.models import (
    STAGE_ORDER,
    Candidate,
    CandidateStatus,
    Stage,
)
from src.pipeline import PipelineError, advance, reject
from src.search.executor import SearchHit


# ---------- helpers ----------

def _select(candidate_id: int) -> None:
    st.session_state.selected_candidate_id = candidate_id


def _card(
    session: Session,
    candidate: Candidate,
    *,
    reasons: list[str] | None = None,
) -> None:
    """One candidate card with actions."""
    with st.container(border=True):
        st.markdown(f"**{candidate.name}**")
        st.caption(candidate.email)

        # stage + status badges
        badge = f"`{candidate.current_stage.value}`"
        if candidate.status == CandidateStatus.REJECTED:
            badge += "  🔴 rejected"
        elif candidate.status == CandidateStatus.HIRED:
            badge += "  🟢 hired"

        days = candidate.days_in_stage
        st.markdown(f"{badge}  ·  {days:.1f}d in stage")

        if reasons:
            with st.expander("Why it matched", expanded=False):
                for r in reasons:
                    st.markdown(f"- {r}")

        # actions
        c1, c2, c3 = st.columns(3)

        with c1:
            if st.button("Open", key=f"open_{candidate.id}", use_container_width=True):
                _select(candidate.id)
                st.rerun()

        can_act = candidate.status == CandidateStatus.ACTIVE

        with c2:
            if st.button(
                "Advance ▶",
                key=f"adv_{candidate.id}",
                use_container_width=True,
                disabled=not can_act,
            ):
                _do(session, advance, candidate.id)

        with c3:
            if st.button(
                "Reject ✖",
                key=f"rej_{candidate.id}",
                use_container_width=True,
                disabled=not can_act,
            ):
                _do(session, reject, candidate.id)


def _do(session: Session, fn, candidate_id: int) -> None:
    """Run a pipeline action; surface errors as toasts."""
    try:
        fn(session, candidate_id)
        st.toast("Updated.", icon="✅")
    except PipelineError as e:
        st.toast(str(e), icon="⚠️")
    st.rerun()


# ---------- full board ----------

def _render_full(session: Session) -> None:
    st.subheader("Pipeline")

    cols = st.columns(len(STAGE_ORDER))
    for col, stage in zip(cols, STAGE_ORDER):
        q = session.query(Candidate).filter(Candidate.current_stage == stage)

        if stage == Stage.HIRED:
            q = q.filter(Candidate.status == CandidateStatus.HIRED)
        else:
            q = q.filter(Candidate.status == CandidateStatus.ACTIVE)

        candidates = q.order_by(Candidate.stage_entered_at.asc()).all()

        with col:
            st.markdown(f"### {stage.value}")
            st.caption(f"{len(candidates)} candidate(s)")
            if not candidates:
                st.caption("_empty_")
                continue
            for c in candidates:
                _card(session, c)

    # rejected pile (collapsed)
    rejected = (
        session.query(Candidate)
        .filter(Candidate.status == CandidateStatus.REJECTED)
        .order_by(Candidate.stage_entered_at.desc())
        .all()
    )
    if rejected:
        with st.expander(f"🔴 Rejected ({len(rejected)})"):
            sub = st.columns(3)
            for i, c in enumerate(rejected):
                with sub[i % 3]:
                    _card(session, c)


# ---------- filtered / search results ----------

def _render_hits(session: Session, hits: list[SearchHit]) -> None:
    st.subheader("Search results")

    if not hits:
        return

    # group by stage for readability
    grouped: dict[Stage, list[SearchHit]] = {s: [] for s in STAGE_ORDER}
    rejected_hits: list[SearchHit] = []

    for h in hits:
        if h.candidate.status == CandidateStatus.REJECTED:
            rejected_hits.append(h)
        else:
            grouped[h.candidate.current_stage].append(h)

    cols = st.columns(len(STAGE_ORDER))
    for col, stage in zip(cols, STAGE_ORDER):
        with col:
            st.markdown(f"### {stage.value}")
            bucket = grouped[stage]
            st.caption(f"{len(bucket)} match(es)")
            if not bucket:
                st.caption("_none_")
                continue
            for h in bucket:
                _card(session, h.candidate, reasons=h.reasons)

    if rejected_hits:
        with st.expander(f"🔴 Rejected matches ({len(rejected_hits)})"):
            sub = st.columns(3)
            for i, h in enumerate(rejected_hits):
                with sub[i % 3]:
                    _card(session, h.candidate, reasons=h.reasons)


# ---------- main entry ----------

def render(
    session: Session,
    candidates: list[SearchHit] | None = None,
) -> None:
    """
    candidates=None → full board
    candidates=[]   → searched, zero results (caller already showed message)
    candidates=[..] → filtered results
    """
    if candidates is None:
        _render_full(session)
    else:
        _render_hits(session, candidates)