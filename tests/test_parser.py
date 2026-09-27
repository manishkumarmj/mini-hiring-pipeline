"""
Tests for src.search.parser.

Run:
    pytest tests/test_parser.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.models import Stage
from src.search.parser import ParserFailure, parse


# ---------- fixtures / helpers ----------

@pytest.fixture()
def now():
    return datetime.now(timezone.utc)


# ---------- 1. name queries ----------

def test_bare_name():
    q = parse("Priya Sharma")
    assert q.name_query == "Priya Sharma"
    assert q.is_empty() is False


def test_name_with_typo_is_passed_through():
    """Parser doesn't fuzzy-match — executor does. Parser just keeps the token."""
    q = parse("sharam")
    assert q.name_query == "sharam"


def test_single_name():
    q = parse("Priya")
    assert q.name_query == "Priya"


def test_name_ignores_stopwords():
    q = parse("the Priya")
    assert q.name_query == "Priya"


def test_name_and_stage_combined():
    q = parse("Priya in Interview")
    assert q.name_query == "Priya"
    assert q.in_stage == Stage.INTERVIEW


# ---------- 2. "in <stage>" ----------

def test_in_stage_simple():
    q = parse("in Interview")
    assert q.in_stage == Stage.INTERVIEW


def test_in_stage_alias_screen():
    q = parse("in Screening")
    assert q.in_stage == Stage.SCREENING


def test_in_stage_alias_screened():
    q = parse("at screened")
    assert q.in_stage == Stage.SCREENING


def test_who_is_in_stage_sets_universal():
    q = parse("who's in Interview")
    assert q.universal is True
    assert q.in_stage == Stage.INTERVIEW


def test_everyone_in_stage():
    q = parse("everyone in Offer")
    assert q.universal is True
    assert q.in_stage == Stage.OFFER


# ---------- 3. "stuck in <stage> > N days" ----------

def test_stuck_in_stage_with_symbol():
    q = parse("stuck in Screening > 7 days")
    assert q.stuck_in_stage == Stage.SCREENING
    assert q.min_days_in_stage == 7.0


def test_stuck_in_stage_with_words():
    q = parse("stuck in Screening for more than a week")
    assert q.stuck_in_stage == Stage.SCREENING
    assert q.min_days_in_stage == 7.0


def test_stuck_in_stage_no_threshold_uses_none():
    q = parse("stuck in Screening")
    assert q.stuck_in_stage == Stage.SCREENING
    assert q.min_days_in_stage is None


def test_stuck_in_stage_a_month():
    q = parse("stuck in Applied for over a month")
    assert q.stuck_in_stage == Stage.APPLIED
    assert q.min_days_in_stage == 30.0


def test_stuck_in_stage_less_than():
    q = parse("stuck in Screening < 3 days")
    assert q.stuck_in_stage == Stage.SCREENING
    assert q.max_days_in_stage == 3.0


# ---------- 4. "moved to <stage> since <date>" ----------

def test_moved_to_stage_since_weekday(now):
    q = parse("moved to Interview since Monday")
    assert q.moved_to_stage == Stage.INTERVIEW
    assert q.moved_since is not None
    # should be within the last 7 days
    assert (now - q.moved_since).days <= 7


def test_moved_to_stage_since_date():
    q = parse("moved to Interview since 2024-01-15")
    assert q.moved_to_stage == Stage.INTERVIEW
    assert q.moved_since.year == 2024
    assert q.moved_since.month == 1
    assert q.moved_since.day == 15


def test_moved_to_stage_since_relative():
    q = parse("moved to Interview since 3 days ago")
    assert q.moved_to_stage == Stage.INTERVIEW
    assert q.moved_since is not None


def test_moved_to_stage_no_date():
    q = parse("moved to Interview")
    assert q.moved_to_stage == Stage.INTERVIEW
    assert q.moved_since is None


def test_moved_to_stage_since_last_week():
    q = parse("moved to Offer since last week")
    assert q.moved_to_stage == Stage.OFFER
    assert q.moved_since is not None


# ---------- 5. "reached <stage> but not hired" ----------

def test_reached_offer_not_hired():
    q = parse("reached Offer but not hired")
    assert q.reached_stage == Stage.OFFER
    assert q.not_hired is True


def test_reached_offer_didnt_get_hired():
    q = parse("reached Offer but didn't get hired")
    assert q.reached_stage == Stage.OFFER
    assert q.not_hired is True


def test_reached_without_not_hired():
    q = parse("reached Offer")
    assert q.reached_stage == Stage.OFFER
    assert q.not_hired is False


# ---------- 6. "except <status>" ----------

def test_everyone_except_rejected():
    q = parse("everyone except rejected")
    assert q.universal is True
    assert "rejected" in q.exclude_statuses


def test_excluding_rejected():
    q = parse("excluding rejected")
    assert "rejected" in q.exclude_statuses


def test_not_rejected():
    q = parse("not rejected")
    assert "rejected" in q.exclude_statuses


def test_except_hired():
    q = parse("everyone except hired")
    assert "hired" in q.exclude_statuses


# ---------- 7. combinations ----------

def test_name_plus_stuck():
    q = parse("Priya stuck in Interview for over 5 days")
    assert q.name_query == "Priya"
    assert q.stuck_in_stage == Stage.INTERVIEW
    assert q.min_days_in_stage == 5.0


def test_stuck_plus_except():
    q = parse("stuck in Screening > 7 days except rejected")
    assert q.stuck_in_stage == Stage.SCREENING
    assert q.min_days_in_stage == 7.0
    assert "rejected" in q.exclude_statuses


def test_moved_since_plus_stage():
    q = parse("who moved to Interview since Monday")
    assert q.universal is True
    assert q.moved_to_stage == Stage.INTERVIEW
    assert q.moved_since is not None


# ---------- 8. error cases ----------

def test_empty_input_raises():
    with pytest.raises(ParserFailure) as exc:
        parse("")
    assert "type something" in exc.value.error.message.lower()


def test_whitespace_input_raises():
    with pytest.raises(ParserFailure):
        parse("   ")


def test_gibberish_raises_with_unknown_tokens():
    with pytest.raises(ParserFailure) as exc:
        parse("asdf 123 !!!")
    assert exc.value.error.unknown_tokens
    assert len(exc.value.error.unknown_tokens) > 0


def test_error_carries_hints():
    with pytest.raises(ParserFailure) as exc:
        parse("asdf 123 !!!")
    assert len(exc.value.error.hints) > 0


def test_too_many_leftover_tokens_raises():
    with pytest.raises(ParserFailure):
        parse("alpha beta gamma delta epsilon")


def test_invalid_since_date_raises():
    with pytest.raises(ParserFailure):
        parse("moved to Interview since whenver")


# ---------- 9. describe() ----------

def test_describe_reports_understood_parts():
    q = parse("Priya in Interview")
    parts = q.describe()
    assert any("Priya" in p for p in parts)
    assert any("Interview" in p for p in parts)


def test_describe_stuck_query():
    q = parse("stuck in Screening > 7 days")
    parts = q.describe()
    joined = " ".join(parts)
    assert "Screening" in joined
    assert "7" in joined