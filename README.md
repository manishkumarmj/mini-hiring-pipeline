https://minihiring.streamlit.app/


# Mini Hiring Pipeline

A small web app that helps a recruiter run candidates through a single hiring pipeline and find who she needs with one search box.


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



