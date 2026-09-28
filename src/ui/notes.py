"""
Reusable sticky-note panel.

Usage:
    from src.ui import notes
    notes.render(session, scope="stage:Interview", title="📝 Interview notes")
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st
from sqlalchemy.orm import Session

from src.pipeline import PipelineError, add_note, list_notes


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def render(session: Session, scope: str, *, title: str = "📝 Notes") -> None:
    """Render the sticky-note panel for a given scope."""
    st.markdown(f"### {title}")
    st.caption("Append-only. Notes here are never edited or deleted.")

    # --- add form ---
    with st.form(f"note_form_{scope}", clear_on_submit=True):
        text = st.text_area(
            "New note",
            placeholder="Type a note for this section…",
            height=80,
            label_visibility="collapsed",
            key=f"note_text_{scope}",
        )
        col1, _ = st.columns([1, 5])
        with col1:
            submitted = st.form_submit_button("Add note", use_container_width=True)
        if submitted:
            try:
                add_note(session, scope=scope, text=text)
                st.toast("Note added.", icon="✅")
                st.rerun()
            except PipelineError as e:
                st.error(str(e))

    # --- existing notes ---
    rows = list_notes(session, scope)
    if not rows:
        st.caption("_No notes yet._")
        return

    for n in rows:
        with st.container(border=True):
            st.markdown(n.text)
            meta = _fmt(n.created_at)
            if n.author:
                meta += f" · {n.author}"
            st.caption(meta)