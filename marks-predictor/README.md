# ACPC Marks-Based College Predictor

Predicts engineering college admission chances for ACPC Gujarat counselling using
year-over-year **merit-marks** trends (0-100 scale, higher = better).

This is a sibling project to `college-predictor/` (which uses closing rank instead).

## Setup (one-time, from this folder)

```zsh
cd marks-predictor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Generate the marks CSV from PDFs

The four ACPC PDFs must exist at the project root (one level up from this folder).

```zsh
python extract_acpc_marks_pdfs_to_csv.py
```

Output: `data/acpc_last_admitted_marks_all_years.csv`

## Run the API

```zsh
python marks_predictor.py serve            # default port 8011
python marks_predictor.py serve 8020       # custom port
```

Interactive docs at `http://localhost:8011/docs`.

## Endpoints

### `POST /predict`
Returns colleges for a given branch + category that the student can realistically
get, sorted **tougher-first** (highest marks cutoff first).

```json
{
  "user_marks": 92.5,
  "user_branch": "COMPUTER ENGINEERING",
  "user_category": "OPEN",
  "top_n": 20
}
```

### `POST /suggest`
Cross-branch suggestions. Returns (college, branch) combos in the requested
category whose predicted cutoff is closest to the student's marks.

```json
{
  "user_marks": 85.0,
  "user_category": "OPEN",
  "top_n": 20
}
```

### `GET /health`
Health check with row count.

## Classification rules

| Chance | Condition (user_marks - predicted_cutoff) |
| ------ | ----------------------------------------- |
| SAFE   | margin >= 10                              |
| MODERATE | margin 5 - 10                           |
| RISKY  | margin 0 - 5                              |
| UNLIKELY | margin < 0                              |

## Frontend integration

`branches_enum.ts` contains TypeScript constants for all valid branch names,
categories, and equivalence groups.
