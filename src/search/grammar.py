"""
Search grammar: stages, keywords, thresholds, fuzzy config.

This file is the single source of truth for what the parser understands.
Adding a new query capability = adding a token here + a rule in parser.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.models import Stage


# ---------- stage aliases ----------

# Maps user-typed words -> canonical Stage
STAGE_ALIASES: dict[str, Stage] = {
    # Applied
    "applied": Stage.APPLIED,
    "application": Stage.APPLIED,
    "new": Stage.APPLIED,
    # Screening
    "screening": Stage.SCREENING,
    "screen": Stage.SCREENING,
    "screened": Stage.SCREENING,
    # Interview
    "interview": Stage.INTERVIEW,
    "interviewing": Stage.INTERVIEW,
    "interviews": Stage.INTERVIEW,
    # Offer
    "offer": Stage.OFFER,
    "offers": Stage.OFFER,
    "offered": Stage.OFFER,
    # Hired
    "hired": Stage.HIRED,
    "hire": Stage.HIRED,
    "hiring": Stage.HIRED,
}


# ---------- status keywords ----------

STATUS_ALIASES: dict[str, str] = {
    "rejected": "rejected",
    "reject": "rejected",
    "rejects": "rejected",
    "declined": "rejected",
    "active": "active",
    "hired": "hired",
}


# ---------- intent keywords ----------

# Words that signal a filter intent
KEYWORD_IN = {"in", "at", "currently"}
KEYWORD_STUCK = {"stuck", "waiting", "idle", "lingering"}
KEYWORD_SINCE = {"since", "after", "from"}
KEYWORD_MOVED = {"moved", "advanced", "progressed", "went"}
KEYWORD_REACHED = {"reached", "got", "made", "arrived"}
KEYWORD_EXCEPT = {"except", "excluding", "exclude", "not", "minus", "without"}
KEYWORD_DAYS = {"day", "days", "week", "weeks", "month", "months"}

# Words that signal "not hired" / "didn't get hired"
NOT_HIRED_PHRASES = [
    "not hired",
    "didn't get hired",
    "did not get hired",
    "no offer accepted",
    "not hired",
    "rejected at offer",
    "didnt hire",
]


# ---------- numeric + time parsing ----------

# "more than 7 days", "> 7 days", "over a week"
MORE_THAN_WORDS = {"more", "over", "greater", ">", "above", "past"}
LESS_THAN_WORDS = {"less", "under", "fewer", "<", "below"}

# Multipliers to convert any unit to days
UNIT_TO_DAYS: dict[str, float] = {
    "day": 1.0,
    "days": 1.0,
    "week": 7.0,
    "weeks": 7.0,
    "month": 30.0,
    "months": 30.0,
}

# Natural relative dates recognized directly
RELATIVE_DATES = {
    "today": 0,
    "yesterday": 1,
    "monday": None,     # handled by dateutil
    "tuesday": None,
    "wednesday": None,
    "thursday": None,
    "friday": None,
    "saturday": None,
    "sunday": None,
    "last week": 7,
    "last month": 30,
}


# ---------- fuzzy matching config ----------

@dataclass(frozen=True)
class FuzzyConfig:
    # minimum score (0-100) to accept a name match
    name_threshold: int = 70
    # rapidfuzz scorer to use
    scorer: str = "WRatio"
    # max candidates returned for a name-only query
    name_result_limit: int = 20


FUZZY = FuzzyConfig()


# ---------- default thresholds ----------

DEFAULT_STUCK_DAYS: float = 7.0


# ---------- grammar hints shown to the user on parse failure ----------

@dataclass(frozen=True)
class GrammarHint:
    example: str
    description: str


GRAMMAR_HINTS: list[GrammarHint] = [
    GrammarHint("Priya Sharma", "Find a candidate by name (typos OK)"),
    GrammarHint("in Interview", "Everyone currently in a stage"),
    GrammarHint("stuck in Screening > 7 days", "Too long in a stage"),
    GrammarHint("moved to Interview since Monday", "Stage change after a date"),
    GrammarHint("reached Offer but not hired", "Passed a stage, final outcome differs"),
    GrammarHint("everyone except rejected", "Exclude a status"),
]


# ---------- regex building blocks (compiled once) ----------

# A stage word (any alias)
STAGE_WORD_PATTERN = r"\b(" + "|".join(re.escape(k) for k in STAGE_ALIASES) + r")\b"

# A number + unit, e.g. "7 days", "a week"
QTY_UNIT_PATTERN = r"(\d+|a|an)\s*(day|days|week|weeks|month|months)"

# "more than 7 days" | "> 7 days" | "over a week"
MORE_THAN_PATTERN = re.compile(
    r"(?:more than|over|greater than|above|past|>)\s*" + QTY_UNIT_PATTERN,
    re.IGNORECASE,
)
LESS_THAN_PATTERN = re.compile(
    r"(?:less than|under|fewer than|below|<)\s*" + QTY_UNIT_PATTERN,
    re.IGNORECASE,
)
ANY_QTY_PATTERN = re.compile(QTY_UNIT_PATTERN, re.IGNORECASE)

# "since Monday" | "since last week" | "since 2024-01-01"
SINCE_PATTERN = re.compile(
    r"\b(?:since|after|from)\s+([A-Za-z0-9\-/ ]+?)(?=$|,|\band\b|\bexcept\b|\bnot\b)",
    re.IGNORECASE,
)

# "moved to Interview" | "advanced to Offer"
MOVED_TO_PATTERN = re.compile(
    r"\b(?:moved|advanced|progressed|went)\s+(?:to|into)\s+" + STAGE_WORD_PATTERN,
    re.IGNORECASE,
)

# "reached Offer"
REACHED_PATTERN = re.compile(
    r"\b(?:reached|got to|made it to|arrived at|got)\s+" + STAGE_WORD_PATTERN,
    re.IGNORECASE,
)

# "in Interview" | "currently at Screening"
IN_STAGE_PATTERN = re.compile(
    r"\b(?:in|at|currently in|currently at)\s+" + STAGE_WORD_PATTERN,
    re.IGNORECASE,
)

# "stuck in Screening" | "waiting in Offer"
STUCK_IN_PATTERN = re.compile(
    r"\b(?:stuck in|waiting in|idle in|lingering in)\s+" + STAGE_WORD_PATTERN,
    re.IGNORECASE,
)

# "except rejected" | "excluding hired" | "not rejected"
EXCEPT_PATTERN = re.compile(
    r"\b(?:except|excluding|exclude|without|minus|not)\s+"
    r"(rejected|reject|hired|hire|active)\b",
    re.IGNORECASE,
)

# "everyone" | "all" | "anyone" | "who"
UNIVERSAL_PATTERN = re.compile(
    r"\b(everyone|everybody|all|anyone|anybody|who|who's|whos)\b",
    re.IGNORECASE,
)

# "not hired" / "didn't get hired" (final-outcome filter)
NOT_HIRED_PATTERN = re.compile(
    r"\b(?:not hired|didn'?t get hired|did not get hired|no hire|not get hired)\b",
    re.IGNORECASE,
)


# ---------- canonical recognized phrases (for error reporting) ----------

def known_phrases() -> set[str]:
    """Return all multi-word phrases the parser recognizes. Used for diagnostics."""
    phrases: set[str] = set()
    phrases.update(STAGE_ALIASES.keys())
    phrases.update(STATUS_ALIASES.keys())
    phrases.update(KEYWORD_IN)
    phrases.update(KEYWORD_STUCK)
    phrases.update(KEYWORD_SINCE)
    phrases.update(KEYWORD_MOVED)
    phrases.update(KEYWORD_REACHED)
    phrases.update(KEYWORD_EXCEPT)
    phrases.update(KEYWORD_DAYS)
    phrases.update(RELATIVE_DATES.keys())
    phrases.update(NOT_HIRED_PHRASES)
    phrases.update(MORE_THAN_WORDS)
    phrases.update(LESS_THAN_WORDS)
    return phrases