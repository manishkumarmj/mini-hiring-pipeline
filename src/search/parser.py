"""
Natural-language search parser.

Turns free text into a typed SearchQuery that executor.py can run.

Design goals:
- Deterministic (no LLM): testable, fast, offline.
- Partial understanding: parse what we can, report what we couldn't.
- Never silently return zero results: unknown tokens trigger a ParseError
  with hints, unless the leftovers look like a name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from dateutil import parser as dateparser

from src.models import Stage
from src.search import grammar as g


# ---------- query object ----------

@dataclass
class SearchQuery:
    raw: str = ""

    # name match (fuzzy)
    name_query: str | None = None

    # stage filters
    in_stage: Stage | None = None            # "in Interview"
    stuck_in_stage: Stage | None = None      # "stuck in Screening"
    min_days_in_stage: float | None = None   # "> 7 days"
    max_days_in_stage: float | None = None   # "< 3 days"

    # event-based filters
    moved_to_stage: Stage | None = None      # "moved to Interview"
    moved_since: datetime | None = None      # "since Monday"
    reached_stage: Stage | None = None       # "reached Offer"

    # outcome filters
    not_hired: bool = False                  # "reached Offer but not hired"
    exclude_statuses: set[str] = field(default_factory=set)  # "except rejected"
    only_statuses: set[str] = field(default_factory=set)     # rare, "only hired"

    # meta
    universal: bool = False                  # "everyone", "who", "all"

    def is_empty(self) -> bool:
        return not any(
            [
                self.name_query,
                self.in_stage,
                self.stuck_in_stage,
                self.moved_to_stage,
                self.moved_since,
                self.reached_stage,
                self.not_hired,
                self.exclude_statuses,
                self.only_statuses,
            ]
        )

    def describe(self) -> list[str]:
        """Human-readable summary of what was understood. For UI chips."""
        parts: list[str] = []
        if self.name_query:
            parts.append(f"name ≈ '{self.name_query}'")
        if self.in_stage:
            parts.append(f"stage = {self.in_stage.value}")
        if self.stuck_in_stage:
            days = self.min_days_in_stage
            parts.append(
                f"stuck in {self.stuck_in_stage.value}"
                + (f" ≥ {days:g}d" if days else "")
            )
        if self.moved_to_stage:
            since = (
                self.moved_since.strftime("%Y-%m-%d")
                if self.moved_since
                else "any time"
            )
            parts.append(f"moved to {self.moved_to_stage.value} since {since}")
        if self.reached_stage:
            parts.append(f"reached {self.reached_stage.value}")
        if self.not_hired:
            parts.append("not hired")
        if self.exclude_statuses:
            parts.append("except " + ", ".join(sorted(self.exclude_statuses)))
        return parts


# ---------- errors ----------

@dataclass
class ParseError:
    message: str
    unknown_tokens: list[str] = field(default_factory=list)
    hints: list[g.GrammarHint] = field(default_factory=lambda: list(g.GRAMMAR_HINTS))


class ParserFailure(Exception):
    def __init__(self, error: ParseError):
        super().__init__(error.message)
        self.error = error


# ---------- helpers ----------

def _to_days(qty: str, unit: str) -> float:
    n = 1.0 if qty.lower() in ("a", "an") else float(qty)
    return n * g.UNIT_TO_DAYS[unit.lower()]


def _parse_since(text: str) -> datetime | None:
    """
    Parse 'Monday', 'last week', '2024-01-15', '3 days ago'.
    Returns timezone-aware UTC datetime or None.
    """
    text = text.strip().lower()
    now = datetime.now(timezone.utc)

    # "N days/weeks/months ago"
    m = re.match(r"(\d+|a|an)\s*(day|days|week|weeks|month|months)\s+ago", text)
    if m:
        return now - timedelta(days=_to_days(m.group(1), m.group(2)))

    # "last week" / "last month"
    if text in g.RELATIVE_DATES and g.RELATIVE_DATES[text] is not None:
        return now - timedelta(days=g.RELATIVE_DATES[text])  # type: ignore[arg-type]

    # weekday name or explicit date — let dateutil try
    try:
        dt = dateparser.parse(text, fuzzy=True, default=now.replace(hour=0, minute=0, second=0, microsecond=0))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, OverflowError):
        return None


def _consume(pattern: re.Pattern[str], text: str) -> tuple[re.Match[str] | None, str]:
    """Find first match; return (match, text_with_match_removed)."""
    m = pattern.search(text)
    if not m:
        return None, text
    return m, text[: m.start()] + " " + text[m.end() :]


def _looks_like_name(remainder: str) -> str | None:
    """
    After all intent patterns are consumed, decide if leftovers are a name.

    Rule: 1–3 tokens, letters/apostrophes/hyphens only, no digits,
    and at least one token that isn't a stopword.
    """
    tokens = [
        t
        for t in re.split(r"\s+", remainder.strip())
        if t and t.lower() not in {"the", "a", "an", "and", "or", "of", "for", "to"}
    ]
    if not tokens or len(tokens) > 3:
        return None
    for t in tokens:
        if not re.fullmatch(r"[A-Za-z'\-\.]+", t):
            return None
    return " ".join(tokens)


# ---------- main entry ----------

def parse(text: str) -> SearchQuery:
    """
    Parse free text into a SearchQuery.
    Raises ParserFailure if the input can't be understood.
    """
    original = text or ""
    q = SearchQuery(raw=original)
    work = f" {original.strip()} "

    if not work.strip():
        raise ParserFailure(
            ParseError(
                message="Type something to search — try a name, a stage, or a phrase.",
            )
        )

    # --- universal marker ---
    m, work = _consume(g.UNIVERSAL_PATTERN, work)
    if m:
        q.universal = True

    # --- "reached X but not hired" ---
    if g.NOT_HIRED_PATTERN.search(work):
        q.not_hired = True
        work = g.NOT_HIRED_PATTERN.sub(" ", work)

    # --- "moved to <stage>" (+ optional "since <date>") ---
    m, work = _consume(g.MOVED_TO_PATTERN, work)
    if m:
        stage_word = m.group(1).lower()
        q.moved_to_stage = g.STAGE_ALIASES[stage_word]
        since_m, work2 = _consume(g.SINCE_PATTERN, work)
        if since_m:
            dt = _parse_since(since_m.group(1))
            if dt is None:
                raise ParserFailure(
                    ParseError(
                        message=f"Couldn't understand the date after 'since': '{since_m.group(1).strip()}'.",
                    )
                )
            q.moved_since = dt
            work = work2

    # --- "reached <stage>" ---
    if q.moved_to_stage is None:
        m, work = _consume(g.REACHED_PATTERN, work)
        if m:
            q.reached_stage = g.STAGE_ALIASES[m.group(1).lower()]

    # --- "stuck in <stage>" (+ optional days) ---
    m, work = _consume(g.STUCK_IN_PATTERN, work)
    if m:
        q.stuck_in_stage = g.STAGE_ALIASES[m.group(1).lower()]

    # --- "in <stage>" (only if not already captured as stuck/moved/reached) ---
    if not any([q.in_stage, q.stuck_in_stage, q.moved_to_stage, q.reached_stage]):
        m, work = _consume(g.IN_STAGE_PATTERN, work)
        if m:
            q.in_stage = g.STAGE_ALIASES[m.group(1).lower()]

    # --- quantity: "more than 7 days", "< 3 weeks" ---
    m, work = _consume(g.MORE_THAN_PATTERN, work)
    if m:
        q.min_days_in_stage = _to_days(m.group(1), m.group(2))
    else:
        m, work = _consume(g.LESS_THAN_PATTERN, work)
        if m:
            q.max_days_in_stage = _to_days(m.group(1), m.group(2))

    # --- "except <status>" ---
    for em in g.EXCEPT_PATTERN.finditer(work):
        word = em.group(1).lower()
        status = g.STATUS_ALIASES.get(word)
        if status:
            q.exclude_statuses.add(status)
    work = g.EXCEPT_PATTERN.sub(" ", work)

    # --- bare status word ("rejected", "active") ---
    for status_word, status in g.STATUS_ALIASES.items():
        pat = re.compile(rf"\b{re.escape(status_word)}\b", re.IGNORECASE)
        if pat.search(work):
            # if preceded by "except"/"not", it was already handled; otherwise treat as filter
            if status not in q.exclude_statuses:
                q.only_statuses.add(status)
            work = pat.sub(" ", work)

    # --- whatever is left should be a name (or nothing) ---
    remainder = re.sub(r"\s+", " ", work).strip()
    if remainder:
        name = _looks_like_name(remainder)
        if name:
            q.name_query = name
        else:
            unknown = [t for t in remainder.split() if t]
            raise ParserFailure(
                ParseError(
                    message=(
                        "I understood part of that, but couldn't make sense of: "
                        + ", ".join(f"'{t}'" for t in unknown)
                        + ". Try one of the examples below."
                    ),
                    unknown_tokens=unknown,
                )
            )

    if q.is_empty():
        raise ParserFailure(
            ParseError(
                message="That didn't match any filter I know. Try one of the examples below.",
            )
        )

    return q