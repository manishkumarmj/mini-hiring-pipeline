# Mini Hiring Pipeline

A small web app that helps a recruiter run candidates through a single hiring pipeline and find who she needs with one search box.

**Stack:** Python 3.11+ · Streamlit · SQLAlchemy 2.0 · SQLite (Postgres-ready)
**Search:** deterministic rule-based NL parser (no LLM)

---

## Table of contents

- [What it does](#what-it-does)
- [How to run](#how-to-run)
- [Architecture](#architecture)
- [Data model](#data-model)
- [Search grammar](#search-grammar)
- [Decisions and why](#decisions-and-why)
- [One place I disagreed with the AI](#one-place-i-disagreed-with-the-ai)
- [What I'd do with more time](#what-id-do-with-more-time)
- [Project layout](#project-layout)

---

## What it does

**Pipeline management**
- Add candidates; they start at `Applied`.
- Everyone is shown grouped by their current stage.
- Move a candidate **one stage at a time**: `Applied → Screening → Interview → Offer → Hired`.
- Reject from any stage before `Hired`. Skipping stages and reversing final outcomes are blocked.
- Open a candidate to see their **complete, immutable history** and time spent in each stage.

**Search** — one box, plain English:
- `Priya Sharma` (typos OK: `sharam` → Priya Sharma)
- `who's in Interview`
- `stuck in Screening > 7 days`
- `moved to Interview since Monday`
- `reached Offer but not hired`
- `everyone except rejected`
- Combine them: `Priya stuck in Interview for over 5 days`
- When the input makes no sense, the app explains what it didn't understand and shows examples.

---

## How to run

**Requirements:** Python 3.11 or newer.

```bash
# 1. Clone
git clone <your-repo-url>
cd mini-hiring-pipeline

# 2. Create a virtual environment
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows
.venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Seed sample data (12 candidates covering every query)
python seed.py --reset

# 5. Run the app
streamlit run app.py