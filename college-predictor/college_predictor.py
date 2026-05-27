"""ACPC College Admission Predictor using YoY percentage-change trends.

CLI:  python college_predictor.py [path/to.csv]
API:  python college_predictor.py serve [--port 8010]
      POST /predict  JSON: {"user_rank": 8500, "user_branch": "COMPUTER ENGINEERING", "user_category": "OPEN"}
Env:  ACPC_CSV=path/to.csv (default: ./college-predictor/data/acpc_last_admitted_all_years.csv)
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent / "data"))
from data_cleaning import clean_dataframe, get_equivalent_branches  # noqa: E402

_ENGINE: pd.DataFrame | None = None
_ENGINE_ERROR: str | None = None
_engine_ready = threading.Event()


def _default_csv_path() -> Path:
    env = os.environ.get("ACPC_CSV")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent / "data" / "acpc_last_admitted_all_years.csv"


def load_and_clean(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = clean_dataframe(df)
    df = df.rename(columns={
        "Inst_Name": "Institute",
        "Branch_Name": "Branch",
        "Closing_Rank": "Rank",
    })
    return df


# ---------------------------------------------------------------------------
# Core prediction: YoY percentage-change method
# ---------------------------------------------------------------------------

def predict_cutoff(years: list[int], ranks: list[int]) -> dict[str, Any]:
    """Predict next-year cutoff from historical (year, rank) pairs.

    Returns dict with predicted_cutoff, pct_change, confidence, trend.
    """
    if len(years) == 1:
        return {
            "predicted_cutoff": float(ranks[0]),
            "pct_change": 0.0,
            "confidence": 0.3,
            "trend": "STABLE",
        }

    pct_changes: list[float] = []
    weights: list[float] = []
    for i in range(1, len(years)):
        gap = years[i] - years[i - 1]
        if gap < 1 or ranks[i - 1] <= 0:
            continue
        ratio = ranks[i] / ranks[i - 1]
        annual_change = ratio ** (1.0 / gap) - 1.0
        pct_changes.append(annual_change)
        weights.append(float(i))

    if not pct_changes:
        return {
            "predicted_cutoff": float(ranks[-1]),
            "pct_change": 0.0,
            "confidence": 0.3,
            "trend": "STABLE",
        }

    weighted_avg = sum(w * c for w, c in zip(weights, pct_changes)) / sum(weights)

    # Cap at +/- 30% to prevent runaway extrapolation
    weighted_avg = max(-0.30, min(0.30, weighted_avg))

    predicted = ranks[-1] * (1.0 + weighted_avg)
    predicted = max(predicted, 1.0)

    if weighted_avg < -0.02:
        trend = "INCREASING_DEMAND"
    elif weighted_avg > 0.02:
        trend = "DECREASING_DEMAND"
    else:
        trend = "STABLE"

    n_factor = {1: 0.3, 2: 0.6, 3: 0.8}.get(len(years), 1.0)
    all_same_dir = all(c >= 0 for c in pct_changes) or all(c <= 0 for c in pct_changes)
    consistency = 1.0 if all_same_dir else 0.5
    confidence = round(n_factor * consistency, 2)

    return {
        "predicted_cutoff": round(predicted, 1),
        "pct_change": round(weighted_avg * 100, 2),
        "confidence": confidence,
        "trend": trend,
    }


def build_prediction_engine(df: pd.DataFrame) -> pd.DataFrame:
    """Build per-(Institute, Branch, Category) predictions using YoY % change."""
    df = df.sort_values(["Institute", "Branch", "Category", "Year"])

    rows: list[dict[str, Any]] = []
    for (inst, branch, cat), grp in df.groupby(["Institute", "Branch", "Category"], sort=False):
        years = grp["Year"].tolist()
        ranks = grp["Rank"].tolist()
        result = predict_cutoff(years, ranks)

        history = {int(y): int(r) for y, r in zip(years, ranks)}

        rows.append({
            "Institute": inst,
            "Branch": branch,
            "Category": cat,
            "Predicted_Cutoff": result["predicted_cutoff"],
            "Last_Year_Rank": int(ranks[-1]),
            "Pct_Change": result["pct_change"],
            "Confidence": result["confidence"],
            "Trend": result["trend"],
            "History": history,
            "Data_Points": len(years),
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Student-facing prediction
# ---------------------------------------------------------------------------

def _classify_chance(user_rank: float, cutoff: float) -> str:
    if cutoff <= 0:
        return "UNLIKELY"
    if user_rank <= cutoff * 0.80:
        return "SAFE"
    if user_rank <= cutoff:
        return "MODERATE"
    if user_rank <= cutoff * 1.15:
        return "RISKY"
    return "UNLIKELY"


def predict_colleges(
    user_rank: float,
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
        lambda cutoff: _classify_chance(user_rank, cutoff)
    )

    results = results[results["Chance"] != "UNLIKELY"]

    return results.sort_values(by="Predicted_Cutoff", ascending=True).reset_index(drop=True)


def suggest_colleges(
    user_rank: float,
    user_category: str,
    engine_df: pd.DataFrame,
) -> pd.DataFrame:
    """Suggest college+branch combos across ALL branches whose cutoff is closest to user's rank.

    Returns matches where the user has a realistic chance, sorted by how closely the
    predicted cutoff matches the user's rank (best fit first).
    """
    cat_upper = user_category.strip().upper()

    results = engine_df[engine_df["Category"].str.upper() == cat_upper].copy()

    results["Chance"] = results["Predicted_Cutoff"].apply(
        lambda cutoff: _classify_chance(user_rank, cutoff)
    )
    results = results[results["Chance"] != "UNLIKELY"]

    results["Match_Distance"] = (results["Predicted_Cutoff"] - user_rank).abs()

    return results.sort_values(
        by=["Match_Distance", "Predicted_Cutoff"], ascending=[True, True]
    ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

def _load_engine_sync() -> None:
    global _ENGINE, _ENGINE_ERROR
    try:
        csv_path = _default_csv_path()
        if not csv_path.is_file():
            raise RuntimeError(
                f"ACPC CSV not found: {csv_path} (set ACPC_CSV or run extract script first)"
            )
        df = load_and_clean(str(csv_path))
        _ENGINE = build_prediction_engine(df)
        _ENGINE_ERROR = None
    except Exception as exc:
        _ENGINE = None
        _ENGINE_ERROR = str(exc)
    finally:
        _engine_ready.set()


app = FastAPI(title="ACPC College Cutoff Predictor")


@app.on_event("startup")
def startup_event() -> None:
    # Load synchronously before serving (see guject-percentile-predictor startup comment).
    _load_engine_sync()


class PredictRequest(BaseModel):
    user_rank: float = Field(..., gt=0, description="Candidate merit rank (lower is better)")
    user_branch: str = Field(..., min_length=1, description="Branch name, e.g. COMPUTER ENGINEERING")
    user_category: str = Field(..., min_length=1, description="Category, e.g. OPEN, EWS, SC, SEBC, ST, TFWS")
    top_n: int = Field(50, ge=1, le=500, description="Max rows to return")


class SuggestRequest(BaseModel):
    user_rank: float = Field(..., gt=0, description="Candidate merit rank (lower is better)")
    user_category: str = Field(..., min_length=1, description="Category, e.g. OPEN, EWS, SC, SEBC, ST, TFWS")
    top_n: int = Field(20, ge=1, le=200, description="Max rows to return")


@app.get("/health")
def health() -> dict[str, Any]:
    ready = _engine_ready.is_set() and _ENGINE is not None and _ENGINE_ERROR is None
    if _ENGINE_ERROR:
        status = "error"
    elif ready:
        status = "ok"
    elif _engine_ready.is_set():
        status = "partial"
    else:
        status = "warming"
    return {
        "status": status,
        "ready": ready,
        "engine_rows": int(len(_ENGINE)) if _ENGINE is not None else 0,
        "csv": str(_default_csv_path()),
        "load_error": _ENGINE_ERROR,
    }


def _format_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for r in records:
        r["Predicted_Cutoff"] = round(float(r["Predicted_Cutoff"]))
        r["Last_Year_Rank"] = int(r["Last_Year_Rank"])
        r["Confidence"] = float(r["Confidence"])
        if "Match_Distance" in r:
            r["Match_Distance"] = round(float(r["Match_Distance"]))
    return records


@app.post("/predict")
def predict(req: PredictRequest) -> dict[str, Any]:
    if _ENGINE_ERROR:
        raise HTTPException(status_code=503, detail=_ENGINE_ERROR)
    if _ENGINE is None:
        raise HTTPException(status_code=503, detail="Prediction engine not loaded yet")
    out = predict_colleges(req.user_rank, req.user_branch, req.user_category, _ENGINE)
    out = out.head(req.top_n)
    records = _format_records(out.to_dict(orient="records"))
    return {
        "user_rank": req.user_rank,
        "user_branch": req.user_branch,
        "user_category": req.user_category,
        "count": len(records),
        "predictions": records,
    }


@app.post("/suggest")
def suggest(req: SuggestRequest) -> dict[str, Any]:
    if _ENGINE_ERROR:
        raise HTTPException(status_code=503, detail=_ENGINE_ERROR)
    if _ENGINE is None:
        raise HTTPException(status_code=503, detail="Prediction engine not loaded yet")
    out = suggest_colleges(req.user_rank, req.user_category, _ENGINE)
    out = out.head(req.top_n)
    records = _format_records(out.to_dict(orient="records"))
    return {
        "user_rank": req.user_rank,
        "user_category": req.user_category,
        "count": len(records),
        "suggestions": records,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_demo() -> None:
    csv_path = sys.argv[1] if len(sys.argv) > 1 else str(_default_csv_path())
    df = load_and_clean(csv_path)
    engine = build_prediction_engine(df)

    user_rank = 8500
    user_branch = "COMPUTER ENGINEERING"
    user_category = "OPEN"
    print(f"\nPredictions for rank={user_rank}, branch={user_branch}, category={user_category}\n")

    out = predict_colleges(user_rank, user_branch, user_category, engine)
    if out.empty:
        print("No matching colleges found.")
        return

    for _, row in out.iterrows():
        conf_label = "HIGH" if row["Confidence"] >= 0.7 else "MEDIUM" if row["Confidence"] >= 0.4 else "LOW"
        print(
            f"  [{row['Chance']:8s}]  Cutoff: {int(row['Predicted_Cutoff']):>6d}  "
            f"Trend: {row['Trend']:18s} ({row['Pct_Change']:+.1f}%)  "
            f"Conf: {conf_label:6s}  {row['Institute']}"
        )
        history = row["History"]
        hist_str = "  ".join(f"{y}:{r}" for y, r in sorted(history.items()))
        print(f"             History: {hist_str}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        import uvicorn

        port = int(os.environ.get("PORT", "8010"))
        if len(sys.argv) > 2 and sys.argv[2].isdigit():
            port = int(sys.argv[2])
        uvicorn.run("college_predictor:app", host="0.0.0.0", port=port, reload=False)
    else:
        _cli_demo()
