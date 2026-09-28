"""
Mini Hiring Pipeline — Streamlit entry point.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from src.db import init_db, get_session
from src.pipeline import PipelineError, add_candidate
from src.ui import board, candidate, searchbar

st.set_page_config(
    page_title="Mini Hiring Pipeline",
    page_icon="🧑‍💼",
    layout="wide",
)

# --- bootstrap ---
init_db()

if "selected_candidate_id" not in st.session_state:
    st.session_state.selected_candidate_id = None


def _reset_selection() -> None:
    st.session_state.selected_candidate_id = None


# --- sidebar / nav ---
with st.sidebar:
    st.title("🧑‍💼 Hiring Pipeline")
    st.caption("One job · one recruiter")

    if st.button("🏠 Pipeline board", use_container_width=True):
        _reset_selection()

    if st.button("🔎 Search", use_container_width=True):
        _reset_selection()

    st.divider()

    # ---- ADD CANDIDATE FORM ----
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
    st.caption("Stages: Applied → Screening → Interview → Offer → Hired")
    st.caption("Rejection possible at any pre-Hire stage.")


# --- main area ---
session = get_session()

try:
    if st.session_state.selected_candidate_id is not None:
        candidate.render(
            session,
            candidate_id=st.session_state.selected_candidate_id,
            on_back=_reset_selection,
        )
    else:
        query_result = searchbar.render(session)
        st.divider()

        if query_result is not None:
            board.render(session, candidates=query_result)
        else:
            board.render(session)
finally:
    session.close()