"""
Mini Hiring Pipeline — Streamlit entry point.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from src.db import init_db, get_session
from src.ui import board, candidate, searchbar

st.set_page_config(
    page_title="Mini Hiring Pipeline",
    page_icon="🧑‍💼",
    layout="wide",
)

# --- bootstrap ---
init_db()  # creates tables if they don't exist

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
    st.caption("Stages: Applied → Screening → Interview → Offer → Hired")
    st.caption("Rejection possible at any pre-Hire stage.")


# --- main area ---
session = get_session()

try:
    if st.session_state.selected_candidate_id is not None:
        # Candidate detail view (history + stage actions)
        candidate.render(
            session,
            candidate_id=st.session_state.selected_candidate_id,
            on_back=_reset_selection,
        )
    else:
        # Search bar always visible at top
        query_result = searchbar.render(session)

        st.divider()

        if query_result is not None:
            # Search returned a filtered result set
            board.render(session, candidates=query_result)
        else:
            # Default: full board grouped by stage
            board.render(session)
finally:
    session.close()