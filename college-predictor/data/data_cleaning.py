"""Clean and normalize ACPC closing-rank data for cross-year analysis.

Handles three classes of issues present in the raw PDF-extracted CSV:
  1. Branch name inconsistencies (case, mid-word spaces from PDF, truncation)
  2. Category name differences across years (HS-round suffix, TFW variants, AI quota)
  3. Duplicate (institute, branch, category, year) keys
"""
from __future__ import annotations

import re

import pandas as pd

# ---------------------------------------------------------------------------
# Branch-name normalization
# ---------------------------------------------------------------------------

_TRUNCATION_MAP: dict[str, str] = {
    "ARTIFICIAL INTELLIGENCE(AI) AND MACHINE LEARNI":
        "ARTIFICIAL INTELLIGENCE (AI) AND MACHINE LEARNING",
    "ARTIFICIAL INTELLIGENCE(A I) AND MACHINE LEARNING":
        "ARTIFICIAL INTELLIGENCE (AI) AND MACHINE LEARNING",
    "ARTIFICIAL INTELLIGENCE(AI) AND MACHINE LEARNING":
        "ARTIFICIAL INTELLIGENCE (AI) AND MACHINE LEARNING",
    "CHEMICAL ENGINEERING (GREEN TECHNOLOGY AND":
        "CHEMICAL ENGINEERING (GREEN TECHNOLOGY AND SUSTAINABILITY ENGINEERING)",
    "COMPUTER ENGINEERING (ARTIFICIAL INTELLIGENC":
        "COMPUTER ENGINEERING (ARTIFICIAL INTELLIGENCE AND MACHINE LEARNING)",
    "COMPUTER ENGINEERING (MACHINE LEARNING & A":
        "COMPUTER ENGINEERING (MACHINE LEARNING & ARTIFICIAL INTELLIGENCE)",
    "COMPUTER ENGINEERING (SOFTWARE ENGINEERIN":
        "COMPUTER ENGINEERING (SOFTWARE ENGINEERING)",
    "COMPUTER SCIENCE & ENGINEERING (ARTIFICIAL IN":
        "COMPUTER SCIENCE & ENGINEERING (ARTIFICIAL INTELLIGENCE AND MACHINE LEARNING)",
    "COMPUTER SCIENCE & ENGINEERING (ARTIFICIAL INTELLIGENCE AND MACHINE":
        "COMPUTER SCIENCE & ENGINEERING (ARTIFICIAL INTELLIGENCE AND MACHINE LEARNING)",
    "COMPUTER SCIENCE & ENGINEERING ARTIFICIAL IN":
        "COMPUTER SCIENCE & ENGINEERING (ARTIFICIAL INTELLIGENCE AND MACHINE LEARNING)",
    "COMPUTER SCIENCE & ENGINEERING (BIG DATA AN":
        "COMPUTER SCIENCE & ENGINEERING (BIG DATA ANALYTICS)",
    "COMPUTER SCIENCE & ENGINEERING (BLOCK CHAIN":
        "COMPUTER SCIENCE & ENGINEERING (BLOCK CHAIN TECHNOLOGY)",
    "COMPUTER SCIENCE & ENGINEERING (CLOUD COMP":
        "COMPUTER SCIENCE & ENGINEERING (CLOUD COMPUTING)",
    "COMPUTER SCIENCE & ENGINEERING (CYBER SECUR":
        "COMPUTER SCIENCE & ENGINEERING (CYBER SECURITY)",
    "COMPUTER SCIENCE & ENGINEERING (DATA SCIENC":
        "COMPUTER SCIENCE & ENGINEERING (DATA SCIENCE)",
    "COMPUTER SCIENCE & ENGINEERING (INTERNET OF THINGS & CYBER SECURITY":
        "COMPUTER SCIENCE & ENGINEERING (INTERNET OF THINGS & CYBER SECURITY INCLUDING BLOCK CHAIN TECHNOLOGY)",
    "COMPUTER SCIENCE & ENGINEERING (INTERNET OF":
        "COMPUTER SCIENCE & ENGINEERING (INTERNET OF THINGS & CYBER SECURITY INCLUDING BLOCK CHAIN TECHNOLOGY)",
    "HONS. IN ICT WITH MINOR IN COMPUTATIONAL SCI":
        "HONS. IN ICT WITH MINOR IN COMPUTATIONAL SCIENCE (CS)",
    "HONS. IN ICT WITH MINOR IN COMPUTATION AL SCIENCE (CS)":
        "HONS. IN ICT WITH MINOR IN COMPUTATIONAL SCIENCE (CS)",
    "INFORMATION TECHNOLOGY (ARTIFICIAL INTELLIGE":
        "INFORMATION TECHNOLOGY (ARTIFICIAL INTELLIGENCE)",
    "ELECTRONICS ENGINEERING ( VLSI DESIGN AND TECHNOLOGY)":
        "ELECTRONICS ENGINEERING (VLSI DESIGN AND TECHNOLOGY)",
    "FIRE AND ENVIRONMENT HEALTH SAFETY ENGINEERING":
        "FIRE AND ENVIRONMENT, HEALTH, SAFETY ENGINEERING",
    "WATER MANAGEMENT ***":
        "WATER MANAGEMENT",
    "BACHELOR OF TECHNOLOGY (HONS) IN CIVIL ENGINEERING (BCE)":
        "CIVIL ENGINEERING (HONS)",
}


def normalize_branch_name(name: str) -> str:
    """Normalize a raw branch name to a canonical upper-case form."""
    s = name.strip().upper()
    s = re.sub(r"\s+", " ", s)

    if s in _TRUNCATION_MAP:
        return _TRUNCATION_MAP[s]

    # Fix mid-word spaces inserted by PDF extraction (e.g. "COMMUNICATI ON" -> "COMMUNICATION")
    # Known patterns where a space breaks a word
    fixes = [
        ("COMMUNICATI ON", "COMMUNICATION"),
        ("INFRASTRUCTU RE", "INFRASTRUCTURE"),
        ("INSTRUMENTAT ION", "INSTRUMENTATION"),
        ("ENVIRONMENT AL", "ENVIRONMENTAL"),
        ("COMPUTATION AL", "COMPUTATIONAL"),
        ("METALLURGICA L", "METALLURGICAL"),
        ("PETROCHEMICA L", "PETROCHEMICAL"),
        ("PHARMACEUTIC AL", "PHARMACEUTICAL"),
        ("BIOINFORMATIC S", "BIOINFORMATICS"),
        ("BIOTECHNOLOG Y", "BIOTECHNOLOGY"),
    ]
    for bad, good in fixes:
        s = s.replace(bad, good)

    return s


# ---------------------------------------------------------------------------
# Category normalization
# ---------------------------------------------------------------------------

_CATEGORY_MAP: dict[str, str] = {
    # 2023 HS-round suffixes -> base category
    "OPEN_HS": "OPEN",
    "EWS_HS": "EWS",
    "SC_HS": "SC",
    "SEBC_HS": "SEBC",
    "ST_HS": "ST",
    "TFWS_HS": "TFWS",
    "ESM_HS": "ESM",
    # 2022 variants
    "TFW_LAST_ADM": "TFWS",
    # AI-quota unification
    "AI-OP": "AI-OPEN",
    "OPEN_AI": "AI-OPEN",
    "OPEN_AI_RANK": "AI-OPEN",
    "AI_RANK": "AI-OPEN",
    "TFWS_AI_RANK": "AI-TFWS",
}


def normalize_category(cat: str) -> str:
    """Map a raw category string to its canonical form."""
    c = cat.strip().upper()
    return _CATEGORY_MAP.get(c, c)


# ---------------------------------------------------------------------------
# Branch equivalence groups (treated as same when searching)
# ---------------------------------------------------------------------------

# Each group lists branch names that should be considered equivalent in queries.
# Data stays separate (so individual cutoffs are preserved), but a search for
# any member returns matches for all members in the group.
BRANCH_EQUIVALENCE_GROUPS: list[set[str]] = [
    {
        "COMPUTER ENGINEERING",
        "COMPUTER SCIENCE & ENGINEERING",
        "COMPUTER SCIENCE & TECHNOLOGY",
        "COMPUTER TECHNOLOGY",
    },
    {
        "INFORMATION TECHNOLOGY",
        "INFORMATION & COMMUNICATION TECHNOLOGY",
        "INFORMATION TECHNOLOGY & ENGINEERING",
    },
    {
        "ELECTRONICS & COMMUNICATION ENGINEERING",
        "ELECTRONICS ENGINEERING",
    },
]


def get_equivalent_branches(branch: str) -> set[str]:
    """Return all branches considered equivalent to the given branch (including itself)."""
    b = normalize_branch_name(branch)
    for group in BRANCH_EQUIVALENCE_GROUPS:
        if b in group:
            return set(group)
    return {b}


# ---------------------------------------------------------------------------
# Full cleaning pipeline
# ---------------------------------------------------------------------------

def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Return a cleaned copy of the raw ACPC CSV dataframe.

    Steps:
      1. Normalize Branch_Name (case, typos, truncation)
      2. Normalize Category across years
      3. Deduplicate (keep lower rank = more conservative cutoff)
      4. Filter out AI-rank scale rows (Closing_Rank > 100_000)
    """
    out = df.copy()

    out["Branch_Name"] = out["Branch_Name"].apply(normalize_branch_name)
    out["Category"] = out["Category"].apply(normalize_category)

    key_cols = ["Inst_Code", "Inst_Name", "Branch_Name", "Category", "Year"]
    out = out.sort_values(key_cols + ["Closing_Rank"])
    out = out.drop_duplicates(subset=key_cols, keep="first")

    out = out[out["Closing_Rank"] <= 100_000].copy()

    out = out.sort_values(key_cols).reset_index(drop=True)
    return out
