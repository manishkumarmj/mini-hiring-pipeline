"""
Seed the database with realistic candidates.

Run:
    python seed.py            # add seed data (skips if any candidates exist)
    python seed.py --reset    # drop and recreate everything first
    python seed.py --force    # insert even if candidates already exist

Covers every search query in the spec:
- name typo case          ("sharam" -> Priya Sharma)
- in Interview now
- stuck in Screening > 7 days
- moved to Interview since Monday
- reached Offer but not hired
- everyone except rejected
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from src.db import Base, engine, get_session
from src.models import (
    Candidate,
    CandidateStatus,
    EventType,
    Stage,
    StageEvent,
)


# ---------- time helpers ----------

def _days_ago(n: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=n)


def _last_monday() -> datetime:
    """Most recent Monday at 00:00 UTC."""
    now = datetime.now(timezone.utc)
    days_since_monday = now.weekday()  # Monday=0
    monday = now - timedelta(days=days_since_monday)
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


# ---------- seed recipes ----------
# Each recipe: (name, email, [ (event_type, from_stage, to_stage, days_ago, note) ])

def _recipes() -> list[dict]:
    return [
        # 1. Applied, fresh
        {
            "name": "Aarav Mehta",
            "email": "aarav@example.com",
            "events": [
                (EventType.CREATED, None, Stage.APPLIED, 1.0, "Applied via careers page"),
            ],
        },
        # 2. Applied, older
        {
            "name": "Nisha Verma",
            "email": "nisha@example.com",
            "events": [
                (EventType.CREATED, None, Stage.APPLIED, 12.0, "Referral"),
            ],
        },
        # 3. Screening, stuck 10 days
        {
            "name": "Rohan Iyer",
            "email": "rohan@example.com",
            "events": [
                (EventType.CREATED, None, Stage.APPLIED, 15.0, None),
                (EventType.MOVED, Stage.APPLIED, Stage.SCREENING, 10.0, "Passed resume screen"),
            ],
        },
        # 4. Screening, fresh (3 days)
        {
            "name": "Meera Nair",
            "email": "meera@example.com",
            "events": [
                (EventType.CREATED, None, Stage.APPLIED, 3.0, None),
                (EventType.MOVED, Stage.APPLIED, Stage.SCREENING, 3.0, None),
            ],
        },
        # 5. Interview, moved BEFORE Monday
        {
            "name": "Priya Sharma",
            "email": "priya@example.com",
            "events": [
                (EventType.CREATED, None, Stage.APPLIED, 20.0, None),
                (EventType.MOVED, Stage.APPLIED, Stage.SCREENING, 15.0, None),
                (EventType.MOVED, Stage.SCREENING, Stage.INTERVIEW, 10.0, "Strong phone screen"),
            ],
        },
        # 6. Interview, moved AFTER Monday
        {
            "name": "Kabir Singh",
            "email": "kabir@example.com",
            "events": [
                (EventType.CREATED, None, Stage.APPLIED, 9.0, None),
                (EventType.MOVED, Stage.APPLIED, Stage.SCREENING, 6.0, None),
                (EventType.MOVED, Stage.SCREENING, Stage.INTERVIEW, 0.5, "Moved after onsite"),
            ],
        },
        # 7. Interview, stuck 8 days
        {
            "name": "Divya Rao",
            "email": "divya@example.com",
            "events": [
                (EventType.CREATED, None, Stage.APPLIED, 30.0, None),
                (EventType.MOVED, Stage.APPLIED, Stage.SCREENING, 25.0, None),
                (EventType.MOVED, Stage.SCREENING, Stage.INTERVIEW, 8.0, None),
            ],
        },
        # 8. Offer, still active
        {
            "name": "Ananya Bose",
            "email": "ananya@example.com",
            "events": [
                (EventType.CREATED, None, Stage.APPLIED, 25.0, None),
                (EventType.MOVED, Stage.APPLIED, Stage.SCREENING, 20.0, None),
                (EventType.MOVED, Stage.SCREENING, Stage.INTERVIEW, 12.0, None),
                (EventType.MOVED, Stage.INTERVIEW, Stage.OFFER, 4.0, "Offer extended"),
            ],
        },
        # 9. Offer, then rejected
        {
            "name": "Vikram Joshi",
            "email": "vikram@example.com",
            "events": [
                (EventType.CREATED, None, Stage.APPLIED, 40.0, None),
                (EventType.MOVED, Stage.APPLIED, Stage.SCREENING, 35.0, None),
                (EventType.MOVED, Stage.SCREENING, Stage.INTERVIEW, 25.0, None),
                (EventType.MOVED, Stage.INTERVIEW, Stage.OFFER, 10.0, "Offer extended"),
                (EventType.REJECTED, Stage.OFFER, None, 5.0, "Declined offer"),
            ],
        },
        # 10. Hired — terminal success
        {
            "name": "Sneha Kulkarni",
            "email": "sneha@example.com",
            "events": [
                (EventType.CREATED, None, Stage.APPLIED, 60.0, None),
                (EventType.MOVED, Stage.APPLIED, Stage.SCREENING, 55.0, None),
                (EventType.MOVED, Stage.SCREENING, Stage.INTERVIEW, 45.0, None),
                (EventType.MOVED, Stage.INTERVIEW, Stage.OFFER, 30.0, None),
                (EventType.MOVED, Stage.OFFER, Stage.HIRED, 20.0, "Accepted offer"),
            ],
        },
        # 11. Rejected early
        {
            "name": "Arjun Das",
            "email": "arjun@example.com",
            "events": [
                (EventType.CREATED, None, Stage.APPLIED, 18.0, None),
                (EventType.REJECTED, Stage.APPLIED, None, 15.0, "Not a fit"),
            ],
        },
        # 12. Rejected from Screening
        {
            "name": "Pooja Reddy",
            "email": "pooja@example.com",
            "events": [
                (EventType.CREATED, None, Stage.APPLIED, 22.0, None),
                (EventType.MOVED, Stage.APPLIED, Stage.SCREENING, 20.0, None),
                (EventType.REJECTED, Stage.SCREENING, None, 14.0, "Failed screen"),
            ],
        },
    ]


# ---------- insertion ----------

def _insert_recipe(session, recipe: dict) -> None:
    """Insert one candidate with a hand-crafted event timeline."""
    first_days_ago = recipe["events"][0][3]

    candidate = Candidate(
        name=recipe["name"],
        email=recipe["email"],
        current_stage=Stage.APPLIED,
        status=CandidateStatus.ACTIVE,
        created_at=_days_ago(first_days_ago),
        stage_entered_at=_days_ago(first_days_ago),
    )
    session.add(candidate)
    session.flush()

    for event_type, from_stage, to_stage, days_ago, note in recipe["events"]:
        ts = _days_ago(days_ago)
        session.add(
            StageEvent(
                candidate_id=candidate.id,
                event_type=event_type,
                from_stage=from_stage,
                to_stage=to_stage,
                note=note,
                timestamp=ts,
            )
        )

    # Rebuild current_stage / status / stage_entered_at from the last event
    last_type, last_from, last_to, last_days_ago, _ = recipe["events"][-1]
    last_ts = _days_ago(last_days_ago)

    if last_type == EventType.REJECTED:
        candidate.status = CandidateStatus.REJECTED
        candidate.current_stage = last_from
        candidate.stage_entered_at = last_ts
    elif last_to == Stage.HIRED:
        candidate.status = CandidateStatus.HIRED
        candidate.current_stage = Stage.HIRED
        candidate.stage_entered_at = last_ts
    else:
        candidate.current_stage = last_to
        candidate.stage_entered_at = last_ts


# ---------- CLI ----------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Drop all tables first")
    parser.add_argument("--force", action="store_true", help="Seed even if data exists")
    args = parser.parse_args()

    if args.reset:
        Base.metadata.drop_all(bind=engine)
        print("Dropped all tables.")

    Base.metadata.create_all(bind=engine)

    session = get_session()
    try:
        existing = session.scalar(select(Candidate).limit(1))
        if existing and not args.force and not args.reset:
            print("Candidates already exist. Use --reset or --force to re-seed.")
            return

        recipes = _recipes()
        for recipe in recipes:
            _insert_recipe(session, recipe)
        session.commit()
        print(f"Seeded {len(recipes)} candidates.")
    finally:
        session.close()


if __name__ == "__main__":
    main()