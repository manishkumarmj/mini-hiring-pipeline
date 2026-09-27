"""
Candidate detail view.

Shows:
- header (name, email, current stage, status)
- time-in-current-stage
- full immutable history (rendered from stage_events)
- per-stage durations
- action buttons (Advance / Reject)
- a "back" button
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st
from sqlalchemy.orm import Session

from src.models import (
    STAGE_ORDER,
    Candidate,
    CandidateStatus,
    EventType,
    StageEvent,
)
from src.pipeline import (
    PipelineError,
    advance,
    history,
    reject,
    stage_durations,
)


# ---------- helpers ----------

def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _event_icon(evt: StageEvent) -> str:
    return {
        EventType.CREATED: "🆕",
        EventType.MOVED: "➡️",
        EventType.REJECTED: "🔴",
    }.get(evt.event_type, "•")


def _event_label(evt: StageEvent) -> str:
    if evt.event_type == EventType.CREATED:
        return f"Added to **{evt.to_stage.value}**"
    if evt.event_type == EventType.MOVED:
        return f"Moved **{evt.from_stage.value} → {evt.to_stage.value}**"
    if evt.event_type == EventType.REJECTED:
        return f"Rejected from **{evt.from_stage.value}**"
    return evt.event_type.value


def _do(session: Session, fn, candidate_id: int) -> None:
    try:
        fn(session, candidate_id)
        st.toast("Updated.", icon="✅")
    except PipelineError as e:
        st.toast(str(e), icon="⚠️")
    st.rerun()


# ---------- sections ----------

def _header(candidate: Candidate, on_back) -> None:
    col_back, col_title = st.columns([1, 8])
    with col_back:
        if st.button("← Back", use_container_width=True):
            on_back()
            st.rerun()
    with col_title:
        st.subheader(candidate.name)
        st.caption(candidate.email)


def _status_strip(candidate: Candidate) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Stage", candidate.current_stage.value)
    c2.metric("Status", candidate.status.value.title())
    c3.metric("Days in stage", f"{candidate.days_in_stage:.1f}")
    c4.metric("Total events", len(candidate.events))


def _actions(session: Session, candidate: Candidate) -> None:
    active = candidate.status == CandidateStatus.ACTIVE

    c1, c2, _ = st.columns([1, 1, 4])

    with c1:
        label = "Advance ▶"
        if candidate.current_stage.value == "Offer":
            label = "Hire 🎉"
        if st.button(
            label,
            key=f"detail_adv_{candidate.id}",
            disabled=not active,
            use_container_width=True,
            type="primary",
        ):
            _do(session, advance, candidate.id)

    with c2:
        if st.button(
            "Reject ✖",
            key=f"detail_rej_{candidate.id}",
            disabled=not active,
            use_container_width=True,
        ):
            _do(session, reject, candidate.id)

    if not active:
        st.info(
            "This candidate is in a terminal state. "
            "Final outcomes cannot be reversed."
        )


def _stage_progress(candidate: Candidate) -> None:
    """Visual progress bar across the 5 stages."""
    stages = [s.value for s in STAGE_ORDER]
    current_idx = STAGE_ORDER.index(candidate.current_stage)
    rejected = candidate.status == CandidateStatus.REJECTED

    labels: list[str] = []
    for i, s in enumerate(stages):
        if rejected and i == current_idx:
            labels.append(f"~~{s}~~ 🔴")
        elif i < current_idx:
            labels.append(f"~~{s}~~ ✅")
        elif i == current_idx:
            labels.append(f"**{s}** ◀")
        else:
            labels.append(s)

    st.markdown(" → ".join(labels))


def _history_section(session: Session, candidate: Candidate) -> None:
    st.markdown("### 📜 Audit trail")
    st.caption("Append-only. Entries are never edited or deleted.")

    events = history(session, candidate.id)
    if not events:
        st.caption("_No events yet._")
        return

    for evt in reversed(events):  # newest first
        with st.container(border=True):
            c1, c2 = st.columns([1, 5])
            with c1:
                st.markdown(f"### {_event_icon(evt)}")
            with c2:
                st.markdown(_event_label(evt))
                st.caption(_fmt_dt(evt.timestamp))
                if evt.note:
                    st.caption(f"📝 {evt.note}")


def _durations_section(session: Session, candidate: Candidate) -> None:
    st.markdown("### ⏱ Time per stage")

    durations = stage_durations(session, candidate.id)
    if not durations:
        st.caption("_No durations yet._")
        return

    for d in durations:
        label = d["stage"].value
        days = d["days"]
        ongoing = d["ongoing"]

        col1, col2, col3 = st.columns([2, 2, 4])
        col1.markdown(f"**{label}**")
        col2.markdown(f"{days:.1f} days" + (" _(ongoing)_" if ongoing else ""))
        with col3:
            st.progress(min(days / 30.0, 1.0))  # cap bar at 30 days


# ---------- main entry ----------

def render(session: Session, candidate_id: int, on_back) -> None:
    """Full candidate detail page."""
    candidate = session.get(Candidate, candidate_id)
    if not candidate:
        st.error("Candidate not found.")
        if st.button("← Back"):
            on_back()
            st.rerun()
        return

    _header(candidate, on_back)
    st.divider()

    _status_strip(candidate)
    st.markdown("")
    _stage_progress(candidate)
    st.markdown("")
    _actions(session, candidate)

    st.divider()

    left, right = st.columns([3, 2])
    with left:
        _history_section(session, candidate)
    with right:
        _durations_section(session, candidate)