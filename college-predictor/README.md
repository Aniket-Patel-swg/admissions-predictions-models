# ACPC College Admission Predictor

Predicts engineering college admission chances for ACPC Gujarat counselling using
year-over-year closing-rank trends.

## Setup (one-time, from this folder)

```zsh
cd college-predictor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run the API

```zsh
cd college-predictor
source .venv/bin/activate
python college_predictor.py serve            # default port 8010
python college_predictor.py serve 8080       # custom port
```

Interactive docs available at `http://localhost:8010/docs`.

## Endpoints

### `POST /predict`
Returns colleges for a given branch + category that the student can realistically get,
sorted **tougher-first** (lowest predicted cutoff first).

```json
{
  "user_rank": 930,
  "user_branch": "COMPUTER ENGINEERING",
  "user_category": "OPEN",
  "top_n": 20
}
```

### `POST /suggest`
Cross-branch suggestions. Returns (college, branch) combos in the requested category
whose predicted cutoff is closest to the student's rank.

```json
{
  "user_rank": 1600,
  "user_category": "OPEN",
  "top_n": 20
}
```

### `GET /health`
Health check with row count.

## Frontend integration

`branches_enum.ts` contains TypeScript constants for all valid branch names,
categories, and equivalence groups. Import directly into your frontend project.
