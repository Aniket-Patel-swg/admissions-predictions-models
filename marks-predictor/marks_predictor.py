"""ACPC College Admission Predictor (MARKS-based) using YoY percentage-change trends.

Uses merit marks (0-100, higher = better) instead of closing rank. The algorithm
mirrors college-predictor/college_predictor.py but with reversed trend direction,
tighter dampening, and absolute-margin classification.

CLI:  python marks_predictor.py [path/to.csv]
API:  python marks_predictor.py serve [--port 8011]
      POST /predict             JSON: {"user_marks": 92.5, "user_branch": "COMPUTER ENGINEERING", "user_category": "OPEN"}
      POST /suggest             JSON: {"user_marks": 85.0, "user_category": "OPEN"}
      POST /merit-wise-college  JSON: {"user_category": "OPEN", "page": 1, "page_size": 50}
Env:  ACPC_MARKS_CSV=path/to.csv (default: ./data/acpc_last_admitted_marks_all_years.csv)
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent / "data"))
from data_cleaning import clean_dataframe, get_equivalent_branches  # noqa: E402

_ENGINE: pd.DataFrame | None = None


def _default_csv_path() -> Path:
    env = os.environ.get("ACPC_MARKS_CSV")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent / "data" / "acpc_last_admitted_marks_all_years.csv"


def load_and_clean(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = clean_dataframe(df)
    df = df.rename(columns={
        "Inst_Name": "Institute",
        "Branch_Name": "Branch",
        "Closing_Marks": "Marks",
    })
    return df


# ---------------------------------------------------------------------------
# Core prediction: YoY percentage-change method (adjusted for marks)
# ---------------------------------------------------------------------------

def predict_cutoff_marks(years: list[int], marks: list[float]) -> dict[str, Any]:
    """Predict next-year cutoff marks from historical (year, marks) pairs.

    Returns dict with predicted_cutoff, pct_change, confidence, trend.

    Differences vs rank-based predictor:
      - Trend direction reversed: marks rising => demand INCREASING (harder)
      - Dampening capped at +/- 5% per year (marks move slowly, bounded 0-100)
      - Predicted value clamped to [0, 100]
    """
    if len(years) == 1:
        return {
            "predicted_cutoff": float(marks[0]),
            "pct_change": 0.0,
            "confidence": 0.3,
            "trend": "STABLE",
        }

    pct_changes: list[float] = []
    weights: list[float] = []
    for i in range(1, len(years)):
        gap = years[i] - years[i - 1]
        if gap < 1 or marks[i - 1] <= 0:
            continue
        ratio = marks[i] / marks[i - 1]
        annual_change = ratio ** (1.0 / gap) - 1.0
        pct_changes.append(annual_change)
        weights.append(float(i))

    if not pct_changes:
        return {
            "predicted_cutoff": float(marks[-1]),
            "pct_change": 0.0,
            "confidence": 0.3,
            "trend": "STABLE",
        }

    weighted_avg = sum(w * c for w, c in zip(weights, pct_changes)) / sum(weights)

    # Tighter cap for marks (bounded scale): +/- 5% per year
    weighted_avg = max(-0.05, min(0.05, weighted_avg))

    predicted = marks[-1] * (1.0 + weighted_avg)
    predicted = min(max(predicted, 0.0), 100.0)

    # Direction FLIPPED vs rank predictor: marks UP = harder
    if weighted_avg > 0.005:
        trend = "INCREASING_DEMAND"
    elif weighted_avg < -0.005:
        trend = "DECREASING_DEMAND"
    else:
        trend = "STABLE"

    n_factor = {1: 0.3, 2: 0.6, 3: 0.8}.get(len(years), 1.0)
    all_same_dir = all(c >= 0 for c in pct_changes) or all(c <= 0 for c in pct_changes)
    consistency = 1.0 if all_same_dir else 0.5
    confidence = round(n_factor * consistency, 2)

    return {
        "predicted_cutoff": round(predicted, 2),
        "pct_change": round(weighted_avg * 100, 2),
        "confidence": confidence,
        "trend": trend,
    }


def build_prediction_engine(df: pd.DataFrame) -> pd.DataFrame:
    """Build per-(Institute, Branch, Category) predictions using YoY % change on marks."""
    df = df.sort_values(["Institute", "Branch", "Category", "Year"])

    rows: list[dict[str, Any]] = []
    for (inst, branch, cat), grp in df.groupby(["Institute", "Branch", "Category"], sort=False):
        years = grp["Year"].tolist()
        marks = grp["Marks"].tolist()
        result = predict_cutoff_marks(years, marks)

        history = {int(y): round(float(m), 2) for y, m in zip(years, marks)}

        rows.append({
            "Institute": inst,
            "Branch": branch,
            "Category": cat,
            "Predicted_Cutoff": result["predicted_cutoff"],
            "Last_Year_Marks": round(float(marks[-1]), 2),
            "Pct_Change": result["pct_change"],
            "Confidence": result["confidence"],
            "Trend": result["trend"],
            "History": history,
            "Data_Points": len(years),
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Student-facing prediction (absolute-margin classification)
# ---------------------------------------------------------------------------

def _classify_chance(user_marks: float, cutoff: float) -> str:
    """Margin-based classification (better metric for bounded 0-100 marks scale).

    The RISKY band extends 2 marks below the predicted cutoff to absorb
    projection uncertainty (especially for competitive colleges near the
    100-mark ceiling where small YoY changes still push the predicted
    cutoff above the student's marks)."""
    margin = user_marks - cutoff
    if margin >= 10:
        return "SAFE"
    if margin >= 5:
        return "MODERATE"
    if margin >= -2.5:
        return "RISKY"
    return "UNLIKELY"


def predict_colleges(
    user_marks: float,
    user_branch: str,
    user_category: str,
    engine_df: pd.DataFrame,
) -> pd.DataFrame:
    equivalent_branches = {b.upper() for b in get_equivalent_branches(user_branch)}
    cat_upper = user_category.strip().upper()

    results = engine_df[
        (engine_df["Branch"].str.upper().isin(equivalent_branches))
        & (engine_df["Category"].str.upper() == cat_upper)
    ].copy()

    results["Chance"] = results["Predicted_Cutoff"].apply(
        lambda cutoff: _classify_chance(user_marks, cutoff)
    )

    results = results[results["Chance"] != "UNLIKELY"]

    # Sort DESCENDING by predicted cutoff -- highest cutoff = toughest college first
    return results.sort_values(by="Predicted_Cutoff", ascending=False).reset_index(drop=True)


def suggest_colleges(
    user_marks: float,
    user_category: str,
    engine_df: pd.DataFrame,
) -> pd.DataFrame:
    """Suggest college+branch combos across ALL branches whose cutoff is closest to user's marks."""
    cat_upper = user_category.strip().upper()

    results = engine_df[engine_df["Category"].str.upper() == cat_upper].copy()

    results["Chance"] = results["Predicted_Cutoff"].apply(
        lambda cutoff: _classify_chance(user_marks, cutoff)
    )
    results = results[results["Chance"] != "UNLIKELY"]

    results["Match_Distance"] = (results["Predicted_Cutoff"] - user_marks).abs()

    return results.sort_values(
        by=["Match_Distance", "Predicted_Cutoff"], ascending=[True, False]
    ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ENGINE
    csv_path = _default_csv_path()
    if not csv_path.is_file():
        raise RuntimeError(
            f"ACPC marks CSV not found: {csv_path} "
            f"(set ACPC_MARKS_CSV env or run extract_acpc_marks_pdfs_to_csv.py first)"
        )
    df = load_and_clean(str(csv_path))
    _ENGINE = build_prediction_engine(df)
    yield
    _ENGINE = None


app = FastAPI(title="ACPC College Cutoff Predictor (Marks-based)", lifespan=lifespan)


class PredictRequest(BaseModel):
    user_marks: float = Field(..., ge=0, le=100, description="Candidate merit marks (0-100, higher is better)")
    user_branch: str = Field(..., min_length=1, description="Branch name, e.g. COMPUTER ENGINEERING")
    user_category: str = Field(..., min_length=1, description="Category, e.g. OPEN, EWS, SC, SEBC, ST, TFWS")
    top_n: int = Field(50, ge=1, le=500, description="Max rows to return")


class SuggestRequest(BaseModel):
    user_marks: float = Field(..., ge=0, le=100, description="Candidate merit marks (0-100, higher is better)")
    user_category: str = Field(..., min_length=1, description="Category, e.g. OPEN, EWS, SC, SEBC, ST, TFWS")
    top_n: int = Field(20, ge=1, le=200, description="Max rows to return")


class MeritWiseRequest(BaseModel):
    user_category: str | None = Field(
        None,
        min_length=1,
        description="Optional category filter (OPEN, EWS, SC, SEBC, ST, TFWS). Omit to include all categories.",
    )
    page: int = Field(1, ge=1, description="1-indexed page number")
    page_size: int = Field(50, ge=1, le=200, description="Rows per page")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok" if _ENGINE is not None else "starting",
        "engine_rows": int(len(_ENGINE)) if _ENGINE is not None else 0,
        "csv": str(_default_csv_path()),
    }


def _format_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for r in records:
        r["Predicted_Cutoff"] = round(float(r["Predicted_Cutoff"]), 2)
        r["Last_Year_Marks"] = round(float(r["Last_Year_Marks"]), 2)
        r["Confidence"] = float(r["Confidence"])
        if "Match_Distance" in r:
            r["Match_Distance"] = round(float(r["Match_Distance"]), 2)
    return records


@app.post("/predict")
def predict(req: PredictRequest) -> dict[str, Any]:
    if _ENGINE is None:
        raise HTTPException(status_code=503, detail="Prediction engine not loaded yet")
    out = predict_colleges(req.user_marks, req.user_branch, req.user_category, _ENGINE)
    out = out.head(req.top_n)
    records = _format_records(out.to_dict(orient="records"))
    return {
        "user_marks": req.user_marks,
        "user_branch": req.user_branch,
        "user_category": req.user_category,
        "count": len(records),
        "predictions": records,
    }


@app.post("/suggest")
def suggest(req: SuggestRequest) -> dict[str, Any]:
    if _ENGINE is None:
        raise HTTPException(status_code=503, detail="Prediction engine not loaded yet")
    out = suggest_colleges(req.user_marks, req.user_category, _ENGINE)
    out = out.head(req.top_n)
    records = _format_records(out.to_dict(orient="records"))
    return {
        "user_marks": req.user_marks,
        "user_category": req.user_category,
        "count": len(records),
        "suggestions": records,
    }


@app.post("/merit-wise-college")
def merit_wise_college(req: MeritWiseRequest) -> dict[str, Any]:
    """Return all (college, branch) rows sorted by highest predicted merit cutoff first.

    Useful for browsing colleges ranked by toughness. Supports pagination and an
    optional category filter.
    """
    if _ENGINE is None:
        raise HTTPException(status_code=503, detail="Prediction engine not loaded yet")

    out = _ENGINE.copy()
    if req.user_category:
        cat_upper = req.user_category.strip().upper()
        out = out[out["Category"].str.upper() == cat_upper]

    out = out.sort_values(by="Predicted_Cutoff", ascending=False).reset_index(drop=True)

    total = int(len(out))
    total_pages = (total + req.page_size - 1) // req.page_size if total else 0
    start = (req.page - 1) * req.page_size
    end = start + req.page_size
    page_df = out.iloc[start:end]
    records = _format_records(page_df.to_dict(orient="records"))

    return {
        "user_category": req.user_category,
        "page": req.page,
        "page_size": req.page_size,
        "total": total,
        "total_pages": total_pages,
        "count": len(records),
        "colleges": records,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_demo() -> None:
    csv_path = sys.argv[1] if len(sys.argv) > 1 else str(_default_csv_path())
    df = load_and_clean(csv_path)
    engine = build_prediction_engine(df)

    user_marks = 92.0
    user_branch = "COMPUTER ENGINEERING"
    user_category = "OPEN"
    print(f"\nPredictions for marks={user_marks}, branch={user_branch}, category={user_category}\n")

    out = predict_colleges(user_marks, user_branch, user_category, engine)
    if out.empty:
        print("No matching colleges found.")
        return

    for _, row in out.head(20).iterrows():
        conf_label = "HIGH" if row["Confidence"] >= 0.7 else "MEDIUM" if row["Confidence"] >= 0.4 else "LOW"
        print(
            f"  [{row['Chance']:8s}]  Cutoff: {row['Predicted_Cutoff']:>6.2f}  "
            f"Trend: {row['Trend']:18s} ({row['Pct_Change']:+.2f}%)  "
            f"Conf: {conf_label:6s}  {row['Institute']}"
        )
        history = row["History"]
        hist_str = "  ".join(f"{y}:{m}" for y, m in sorted(history.items()))
        print(f"             History: {hist_str}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        import uvicorn

        port = int(os.environ.get("PORT", "8011"))
        if len(sys.argv) > 2 and sys.argv[2].isdigit():
            port = int(sys.argv[2])
        uvicorn.run("marks_predictor:app", host="0.0.0.0", port=port, reload=False)
    else:
        _cli_demo()
