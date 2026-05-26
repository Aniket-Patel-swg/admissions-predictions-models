from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from pydantic import AliasChoices, BaseModel, Field, model_validator
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

_BASE = Path(__file__).resolve().parent
_REPO = _BASE.parent

# e.g. export RATE_LIMIT="60/minute"
RATE_LIMIT = os.environ.get("RATE_LIMIT", "30/minute")

# Training sample weights by session order in BOARD_DATA (oldest CSV first). Last two sessions
# get TRAIN_WEIGHT_RECENT_SESSIONS; earlier sessions get TRAIN_WEIGHT_OLDEST_SESSIONS (default 0.35 vs 1.0).
# For exactly 2 sessions loaded: first file → old, second → recent. Override via env if needed.
TRAIN_WEIGHT_OLDEST_SESSIONS = float(os.environ.get("TRAIN_WEIGHT_OLDEST_SESSIONS", "0.30"))
TRAIN_WEIGHT_RECENT_SESSIONS = float(os.environ.get("TRAIN_WEIGHT_RECENT_SESSIONS", "1.0"))

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Marks → percentile predictor")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Session CSV paths per board: prefer guject-percentile-predictor/data/, then repo root fallback.
BOARD_DATA: dict[str, list[Path]] = {
    "gujcet": [
        _BASE / "data" / "2023_GUJCET_marks_percentile.csv",
        _BASE / "data" / "2024_GUJCET_marks_percentile.csv",
        _BASE / "data" / "2025_GUJCET_marks_percentile.csv",
    ],
    "cbse": [
        _BASE / "data" / "cbse" / "2023-24_marks_percentile.csv",
        _BASE / "data" / "cbse" / "2024-25_marks_percentile.csv",
        _BASE / "data" / "cbse" / "2025-26_marks_percentile.csv",
        _REPO / "cbse" / "2023-24_marks_percentile.csv",
        _REPO / "cbse" / "2024-25_marks_percentile.csv",
        _REPO / "cbse" / "2025-26_marks_percentile.csv",
    ],
    "gseb": [
        _BASE / "data" / "gseb" / "2023-24_marks_percentile.csv",
        _BASE / "data" / "gseb" / "2024-25_marks_percentile.csv",
        _BASE / "data" / "gseb" / "2025-26_marks_percentile.csv",
        _REPO / "gseb" / "2023-24_marks_percentile.csv",
        _REPO / "gseb" / "2024-25_marks_percentile.csv",
        _REPO / "gseb" / "2025-26_marks_percentile.csv",
    ],
    "isce": [
        _BASE / "data" / "isce" / "2023-24_marks_percentile.csv",
        _BASE / "data" / "isce" / "2024-25_marks_percentile.csv",
        _BASE / "data" / "isce" / "2025-26_marks_percentile.csv",
        _REPO / "isce" / "2023-24_marks_percentile.csv",
        _REPO / "isce" / "2024-25_marks_percentile.csv",
        _REPO / "isce" / "2025-26_marks_percentile.csv",
    ],
}

OPTIMAL_DEGREE = 6
polys: dict[str, PolynomialFeatures] = {}
models: dict[str, LinearRegression] = {}


def _session_row_weight(session_idx: int, n_sessions: int) -> float:
    """Per-row weight for rows from the session_idx-th CSV (0 = oldest in BOARD_DATA)."""
    if n_sessions <= 1:
        return 1.0
    if n_sessions == 2:
        return TRAIN_WEIGHT_RECENT_SESSIONS if session_idx == 1 else TRAIN_WEIGHT_OLDEST_SESSIONS
    if session_idx < n_sessions - 2:
        return TRAIN_WEIGHT_OLDEST_SESSIONS
    return TRAIN_WEIGHT_RECENT_SESSIONS


def _existing_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        if not p.is_file():
            continue
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


@app.on_event("startup")
def startup_event() -> None:
    for board, path_list in BOARD_DATA.items():
        paths = _existing_paths(path_list)
        n_sess = len(paths)
        data_frames: list[pd.DataFrame] = []
        weight_chunks: list[np.ndarray] = []
        for session_idx, p in enumerate(paths):
            try:
                df = pd.read_csv(p).dropna()
            except Exception as e:
                print(f"Skipping {p}: {e}")
                continue
            if len(df) == 0:
                continue
            w = _session_row_weight(session_idx, n_sess)
            data_frames.append(df)
            weight_chunks.append(np.full(len(df), w, dtype=float))

        if not data_frames:
            print(f"No data for board {board}; skipping")
            continue

        try:
            combined_df = pd.concat(data_frames, ignore_index=True)
            sample_weight = np.concatenate(weight_chunks)
            if len(sample_weight) != len(combined_df):
                raise RuntimeError("sample_weight length mismatch after concat")

            valid = combined_df[["Marks", "Percentile"]].notna().all(axis=1)
            combined_df = combined_df.loc[valid].reset_index(drop=True)
            sample_weight = sample_weight[valid.to_numpy()]
            X = combined_df[["Marks"]].values.astype(float)
            y = combined_df["Percentile"].values.astype(float)

            poly = PolynomialFeatures(degree=OPTIMAL_DEGREE)
            poly.fit(np.zeros((1, 1), dtype=float))
            X_poly = poly.transform(X)
            model = LinearRegression()
            model.fit(X_poly, y, sample_weight=sample_weight)

            polys[board] = poly
            models[board] = model
            print(
                f"Combined model trained for {board} using {len(combined_df)} rows "
                f"(weights old={TRAIN_WEIGHT_OLDEST_SESSIONS} recent={TRAIN_WEIGHT_RECENT_SESSIONS})."
            )
        except Exception as e:
            print(f"Failed to train model for board {board}: {e}")


class PredictBody(BaseModel):
    """Each board in `boards` must supply the matching `*_marks` field (e.g. gujcet → gujcet_marks or guject_marks)."""

    boards: list[str] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Board ids to run (e.g. gujcet, cbse, gseb, isce)",
    )
    gujcet_marks: float | None = Field(
        None,
        validation_alias=AliasChoices("gujcet_marks", "guject_marks"),
        description="Required when `gujcet` is in `boards` (accepts JSON key gujcet_marks or guject_marks)",
    )
    cbse_marks: float | None = Field(None, description="Required when `cbse` is in `boards`")
    gseb_marks: float | None = Field(None, description="Required when `gseb` is in `boards`")
    isce_marks: float | None = Field(None, description="Required when `isce` is in `boards`")

    @model_validator(mode="after")
    def marks_required_for_listed_boards(self) -> PredictBody:
        seen: list[str] = []
        seen_set: set[str] = set()
        for b in self.boards:
            if b not in seen_set:
                seen_set.add(b)
                seen.append(b)

        unknown = [b for b in seen if b not in BOARD_DATA]
        if unknown:
            raise ValueError(
                f"Unknown board(s): {unknown}. Configured: {list(BOARD_DATA.keys())}"
            )

        for b in seen:
            field_name = f"{b}_marks"
            val = getattr(self, field_name, None)
            if val is None:
                raise ValueError(
                    f"`{field_name}` is required when board '{b}' is listed in `boards`"
                )
        return self


def _predict_one(board_id: str, marks: float) -> dict[str, Any]:
    if board_id not in models or board_id not in polys:
        return {"error": "Board model not found or not trained"}
    X_input = polys[board_id].transform([[marks]])
    raw = float(models[board_id].predict(X_input)[0])
    clipped = float(np.clip(raw, 0.0, 100.0))
    return {"predicted_percentile": round(clipped, 2)}


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "boards_trained": list(models.keys()),
        "rate_limit": RATE_LIMIT,
        "training_sample_weights": {
            "oldest_sessions": TRAIN_WEIGHT_OLDEST_SESSIONS,
            "last_two_sessions": TRAIN_WEIGHT_RECENT_SESSIONS,
        },
    }


@app.post("/predict")
@limiter.limit(RATE_LIMIT)
def predict_multi(request: Request, body: PredictBody) -> dict[str, Any]:
    """Predict using per-board marks fields (`gujcet_marks`, `cbse_marks`, …) matching `boards`."""
    seen: set[str] = set()
    board_order: list[str] = []
    for b in body.boards:
        if b not in seen:
            seen.add(b)
            board_order.append(b)

    boards_out: dict[str, Any] = {}
    input_by_board: dict[str, float] = {}
    for bid in board_order:
        marks = float(getattr(body, f"{bid}_marks"))
        input_by_board[bid] = marks
        out = _predict_one(bid, marks)
        boards_out[bid] = {**out, "input_marks": marks}

    return {
        "input_marks_by_board": input_by_board,
        "boards": boards_out,
        "note": (
            "Each value is from one model fit on combined sessions for that board; "
            "the last two sessions in training are up-weighted vs the oldest session."
        ),
    }
