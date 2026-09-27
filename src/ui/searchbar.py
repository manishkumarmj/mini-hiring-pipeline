"""
Search bar UI.

Renders:
- a text input
- example hints when empty
- parse errors + suggestions when input is nonsense
- "what I understood" chips on success
- returns ranked SearchHits (or None when idle)
"""

from __future__ import annotations

import streamlit as st
from sqlalchemy.orm import Session

from src.search import executor, parser
from src.search.grammar import GRAMMAR_HINTS
from src.search.parser import ParserFailure, SearchQuery


# ---------- session state keys ----------

_KEY_QUERY = "search_query_text"
_KEY_RESULTS = "search_results"
_KEY_ERROR = "search_error"
_KEY_UNDERSTOOD = "search_understood"


def _clear() -> None:
    st.session_state[_KEY_QUERY] = ""
    st.session_state[_KEY_RESULTS] = None
    st.session_state[_KEY_ERROR] = None
    st.session_state[_KEY_UNDERSTOOD] = None


def _run(session: Session, text: str) -> None:
    """Parse + execute, stash results / errors in session_state."""
    try:
        q: SearchQuery = parser.parse(text)
    except ParserFailure as pf:
        st.session_state[_KEY_RESULTS] = None
        st.session_state[_KEY_UNDERSTOOD] = None
        st.session_state[_KEY_ERROR] = pf.error
        return

    hits = executor.execute(session, q)
    st.session_state[_KEY_RESULTS] = hits
    st.session_state[_KEY_UNDERSTOOD] = q.describe()
    st.session_state[_KEY_ERROR] = None


# ---------- render sub-pieces ----------

def _render_hints() -> None:
    st.caption("Try one of these:")
    cols = st.columns(2)
    for i, hint in enumerate(GRAMMAR_HINTS):
        with cols[i % 2]:
            st.markdown(f"**`{hint.example}`** — {hint.description}")


def _render_error(err) -> None:
    st.error(f"❌ {err.message}")
    if err.unknown_tokens:
        st.markdown(
            "**Unrecognized:** "
            + ", ".join(f"`{t}`" for t in err.unknown_tokens)
        )
    with st.expander("Show examples that work", expanded=True):
        for hint in err.hints:
            st.markdown(f"- **`{hint.example}`** — {hint.description}")


def _render_understood(parts: list[str]) -> None:
    if not parts:
        return
    chips = " · ".join(f"`{p}`" for p in parts)
    st.caption(f"Understood as: {chips}")


# ---------- main entry ----------

def render(session: Session) -> list[executor.SearchHit] | None:
    """
    Render the search bar. Returns ranked hits if a query is active,
    or None if idle (caller should show the full board).
    """
    st.subheader("🔎 Search candidates")

    col_input, col_run, col_clear = st.columns([6, 1, 1])

    with col_input:
        text = st.text_input(
            label="Search",
            key=_KEY_QUERY,
            placeholder='e.g. "stuck in Screening > 7 days" or "Priya in Interview"',
            label_visibility="collapsed",
        )

    with col_run:
        run_clicked = st.button("Search", use_container_width=True, type="primary")

    with col_clear:
        if st.button("Clear", use_container_width=True):
            _clear()
            st.rerun()

    # Enter key also triggers search
    triggered = run_clicked or (
        text
        and text != st.session_state.get("_last_ran", "")
        and st.session_state.get("_enter_hint", False)
    )

    if run_clicked:
        st.session_state["_last_ran"] = text
        _run(session, text)

    # --- results area ---
    err = st.session_state.get(_KEY_ERROR)
    understood = st.session_state.get(_KEY_UNDERSTOOD)
    results = st.session_state.get(_KEY_RESULTS)

    if err is not None:
        _render_error(err)
        st.divider()
        _render_hints()
        return []

    if results is not None:
        _render_understood(understood or [])
        if not results:
            st.info(
                "No candidates matched — but the query was understood. "
                "Try loosening a filter."
            )
        else:
            st.caption(f"{len(results)} match(es)")
        return results

    # idle state
    _render_hints()
    return None