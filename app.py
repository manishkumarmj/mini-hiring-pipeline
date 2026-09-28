"""
Mini Hiring Pipeline — Streamlit entry point.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from src.db import init_db, get_session
from src.models import Candidate, CandidateStatus, Stage
from src.pipeline import PipelineError, add_candidate
from src.ui import board, candidate, notes, searchbar

st.set_page_config(
    page_title="Mini Hiring Pipeline",
    page_icon="🧑‍💼",
    layout="wide",
)

# --- bootstrap ---
init_db()

if "selected_candidate_id" not in st.session_state:
    st.session_state.selected_candidate_id = None
if "stage_filter" not in st.session_state:
    st.session_state.stage_filter = None  # None | Stage | "rejected"


def _reset_selection() -> None:
    st.session_state.selected_candidate_id = None


def _set_filter(value) -> None:
    st.session_state.stage_filter = value
    st.session_state.selected_candidate_id = None


# --- sidebar ---
with st.sidebar:
    st.title("🧑‍💼 Hiring Pipeline")
    st.caption("One job · one recruiter")

    if st.button("🏠 Pipeline board", use_container_width=True):
        _set_filter(None)

    with st.expander("➕ Add candidate", expanded=False):
        with st.form("add_candidate_form", clear_on_submit=True):
            new_name = st.text_input("Name", placeholder="Priya Sharma")
            new_email = st.text_input("Email", placeholder="priya@example.com")
            submitted = st.form_submit_button("Add", use_container_width=True)

            if submitted:
                s = get_session()
                try:
                    c = add_candidate(s, name=new_name, email=new_email)
                    st.success(f"Added {c.name} at {c.current_stage.value}")
                    st.rerun()
                except PipelineError as e:
                    st.error(str(e))
                finally:
                    s.close()

    st.divider()
    st.markdown("**Views**")

    for stage in Stage:
        if st.button(stage.value, use_container_width=True, key=f"nav_{stage.value}"):
            _set_filter(stage)

    if st.button("🔴 Rejected", use_container_width=True, key="nav_rejected"):
        _set_filter("rejected")


# ---------- helper: row of clickable tabs ----------

def _stage_tabs(session, active) -> None:
    cols = st.columns(len(Stage) + 1)

    for col, stage in zip(cols, list(Stage)):
        count = (
            session.query(Candidate)
            .filter(Candidate.current_stage == stage)
            .filter(
                Candidate.status == CandidateStatus.HIRED
                if stage == Stage.HIRED
                else Candidate.status == CandidateStatus.ACTIVE
            )
            .count()
        )
        with col:
            is_active = active == stage
            label = f"{'▶ ' if is_active else ''}{stage.value} ({count})"
            if st.button(
                label,
                key=f"tab_{stage.value}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
            ):
                _set_filter(stage)

    with cols[-1]:
        count = (
            session.query(Candidate)
            .filter(Candidate.status == CandidateStatus.REJECTED)
            .count()
        )
        is_active = active == "rejected"
        label = f"{'▶ ' if is_active else ''}🔴 Rejected ({count})"
        if st.button(
            label,
            key="tab_rejected",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            _set_filter("rejected")


# ---------- helper: dedicated page for a single stage ----------

def _render_stage_page(session, stage_filter) -> None:
    if stage_filter == "rejected":
        st.subheader("🔴 Rejected candidates")
        notes.render(session, scope="stage:Rejected", title="📝 Rejected notes")
        st.divider()

        rows = (
            session.query(Candidate)
            .filter(Candidate.status == CandidateStatus.REJECTED)
            .order_by(Candidate.stage_entered_at.desc())
            .all()
        )
    else:
        stage: Stage = stage_filter
        st.subheader(f"{stage.value} candidates")
        notes.render(
            session,
            scope=f"stage:{stage.value}",
            title=f"📝 {stage.value} notes",
        )
        st.divider()

        q = session.query(Candidate).filter(Candidate.current_stage == stage)
        if stage == Stage.HIRED:
            q = q.filter(Candidate.status == CandidateStatus.HIRED)
        else:
            q = q.filter(Candidate.status == CandidateStatus.ACTIVE)
        rows = q.order_by(Candidate.stage_entered_at.asc()).all()

    st.caption(f"{len(rows)} candidate(s)")
    if not rows:
        st.info("No candidates here right now.")
        return

    cols = st.columns(3)
    for i, c in enumerate(rows):
        with cols[i % 3]:
            board._card(session, c)


# --- main ---
session = get_session()

try:
    if st.session_state.selected_candidate_id is not None:
        # ----- DETAIL VIEW -----
        candidate.render(
            session,
            candidate_id=st.session_state.selected_candidate_id,
            on_back=_reset_selection,
        )
    else:
        # ----- TAB ROW -----
        _stage_tabs(session, st.session_state.stage_filter)
        st.divider()

        if st.session_state.stage_filter is not None:
            # ----- SINGLE-STAGE PAGE -----
            _render_stage_page(session, st.session_state.stage_filter)
        else:
            # ----- BOARD + SEARCH -----
            query_result = searchbar.render(session)

            if query_result is not None:
                st.divider()
                notes.render(session, scope="search", title="📝 Search notes")
                st.divider()
                board.render(session, candidates=query_result)
            else:
                st.divider()
                board.render(session)
finally:
    session.close()