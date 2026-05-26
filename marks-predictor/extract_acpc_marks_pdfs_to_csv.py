#!/usr/bin/env python3
"""Extract ACPC 'Last Admitted Rank Institute wise' PDFs to a CLOSING-MARKS CSV.

The same PDFs contain merit-marks columns adjacent to the rank columns. This
extractor pulls only the marks (skipping the rank entirely). Output columns:
  Inst_Code, Inst_Name, Branch_Name, Category, Year, Closing_Marks

Usage:
  python extract_acpc_marks_pdfs_to_csv.py
  python extract_acpc_marks_pdfs_to_csv.py --out data/acpc_last_admitted_marks_all_years.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Any

try:
    import pdfplumber
except ImportError:
    print("Install pdfplumber: pip install pdfplumber", file=sys.stderr)
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent

DEFAULT_PDFS: list[tuple[int, Path]] = [
    (2022, PROJECT_ROOT / "Last Admitted Rank Institue wise 2022.pdf"),
    (2023, PROJECT_ROOT / "Last Admitted Rank Institue wise 2023.pdf"),
    (2024, PROJECT_ROOT / "Last Admitted Rank Institue wise 2024.pdf"),
    (2025, PROJECT_ROOT / "Last Admitted Rank Institue wise 2025.pdf"),
]


def _norm(s: str | None) -> str:
    if s is None:
        return ""
    t = str(s).replace("\n", " ").strip()
    t = re.sub(r"\s+", " ", t)
    return t


def parse_marks(cell: Any) -> float | None:
    """Parse a merit-marks cell. Returns None for missing/invalid values."""
    if cell is None:
        return None
    s = str(cell).strip().upper()
    if not s or s in ("VAC", "------", "--------", "-----", "----", "--"):
        return None
    if "*" in s or s == "******":
        return None
    try:
        v = float(s.replace(",", ""))
        if v <= 0 or v > 100:
            return None
        return round(v, 4)
    except (TypeError, ValueError):
        return None


def _emit_row(
    out: list[dict[str, Any]],
    year: int,
    inst: str,
    branch: str,
    category: str,
    marks: float | None,
) -> None:
    if marks is None:
        return
    cat = _norm(category)
    if not cat:
        return
    out.append(
        {
            "Inst_Name": _norm(inst),
            "Branch_Name": _norm(branch),
            "Category": cat,
            "Year": year,
            "Closing_Marks": marks,
        }
    )


def extract_2022(path: Path, year: int) -> list[dict[str, Any]]:
    """2022 layout: Institute Name / Course Name; (rank, marks) pairs."""
    rows_out: list[dict[str, Any]] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table or len(table) < 3:
                continue
            if not table[0] or "Institute Name" not in str(table[0][0]):
                continue
            for row in table[2:]:
                if not row or len(row) < 12:
                    continue
                inst, branch = row[0], row[1]
                if not inst or not branch:
                    continue
                if "Institute" in str(inst) and "Name" in str(inst):
                    continue
                for cat, i_m in [
                    ("OPEN", 3),
                    ("SC", 5),
                    ("ST", 7),
                    ("SEBC", 9),
                    ("EWS", 11),
                ]:
                    if i_m < len(row):
                        _emit_row(rows_out, year, inst, branch, cat, parse_marks(row[i_m]))
    return rows_out


def extract_2023(path: Path, year: int) -> list[dict[str, Any]]:
    """2023: Name of Institute / Program; OPEN_HS, SC_HS, ... pairs in row 0."""
    rows_out: list[dict[str, Any]] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table or len(table) < 2:
                continue
            if not table[0] or "Name of Institute" not in str(table[0][0]):
                continue
            header = table[0]
            pairs: list[tuple[str, int]] = []
            for j in range(2, len(header), 2):
                if j + 1 >= len(header):
                    break
                h = header[j]
                if not h:
                    continue
                cat = _norm(h).replace(" ", "_")
                pairs.append((cat, j + 1))
            for row in table[1:]:
                if not row or len(row) < 4:
                    continue
                inst, branch = row[0], row[1]
                if not inst or not branch:
                    continue
                if "Name of Institute" in str(inst):
                    continue
                for cat, j_m in pairs:
                    if j_m >= len(row):
                        continue
                    _emit_row(rows_out, year, inst, branch, cat, parse_marks(row[j_m]))
    return rows_out


def extract_2024(path: Path, year: int) -> list[dict[str, Any]]:
    """2024 layout: INSTITUTE_NAME / BRANCH_NAME; marks at rank_col + 1."""
    rows_out: list[dict[str, Any]] = []
    mark_cols = [
        ("OPEN", 3),
        ("SC", 5),
        ("ST", 7),
        ("SEBC", 9),
        ("EWS", 11),
        ("AI-OPEN", 13),
    ]
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table or len(table) < 4:
                continue
            start = None
            for i, row in enumerate(table):
                if not row or len(row) < 3:
                    continue
                a0 = str(row[0] or "").upper().replace("_", " ")
                if "INSTITUTE" in a0 and "NAME" in a0:
                    start = i + 2
                    break
            if start is None:
                continue
            for row in table[start:]:
                if not row or len(row) < 14:
                    continue
                inst, branch = row[0], row[1]
                if not inst or not branch:
                    continue
                if "INSTITUTE" in str(inst).upper() and "NAME" in str(inst).upper():
                    continue
                for cat, idx in mark_cols:
                    if idx < len(row):
                        _emit_row(rows_out, year, inst, branch, cat, parse_marks(row[idx]))
    return rows_out


def extract_2025(path: Path, year: int) -> list[dict[str, Any]]:
    """2025 layout: INSTITUTE NAME / COURSE / OPEN H_Rank columns. Marks at rank_col + 1."""
    rows_out: list[dict[str, Any]] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table or len(table) < 3:
                continue
            if not table[0] or "INSTITUTE NAME" not in str(table[0][0]).upper():
                continue
            for row in table[2:]:
                if not row or len(row) < 17:
                    continue
                inst, branch = row[0], row[2]
                if not inst or not branch:
                    continue
                if "INSTITUTE" in str(inst).upper() and "NAME" in str(inst).upper():
                    continue
                cats = [
                    ("OPEN", 4),
                    ("SC", 6),
                    ("ST", 8),
                    ("SEBC", 10),
                    ("EWS", 12),
                    ("ESM", 14),
                    ("TFWS", 16),
                ]
                for cat, idx in cats:
                    if idx < len(row):
                        _emit_row(rows_out, year, inst, branch, cat, parse_marks(row[idx]))
    return rows_out


def extract_for_year(path: Path, year: int) -> list[dict[str, Any]]:
    if year == 2022:
        return extract_2022(path, year)
    if year == 2023:
        return extract_2023(path, year)
    if year == 2024:
        return extract_2024(path, year)
    if year == 2025:
        return extract_2025(path, year)
    return extract_2024(path, year)


def assign_inst_codes(records: list[dict[str, Any]]) -> None:
    names: list[str] = []
    seen: set[str] = set()
    for r in records:
        k = r["Inst_Name"]
        if k and k not in seen:
            seen.add(k)
            names.append(k)
    names.sort()
    code_map = {n: i + 1 for i, n in enumerate(names)}
    for r in records:
        r["Inst_Code"] = code_map.get(r["Inst_Name"], 0)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=ROOT / "data" / "acpc_last_admitted_marks_all_years.csv")
    args = p.parse_args()

    all_rows: list[dict[str, Any]] = []
    for year, pdf in DEFAULT_PDFS:
        if not pdf.is_file():
            print(f"SKIP missing: {pdf.name}", file=sys.stderr)
            continue
        try:
            rows = extract_for_year(pdf, year)
        except Exception as e:
            print(f"FAIL {pdf.name}: {e}", file=sys.stderr)
            continue
        print(f"OK {pdf.name}: {len(rows)} marks rows")
        all_rows.extend(rows)

    if not all_rows:
        print("No rows extracted.", file=sys.stderr)
        return 1

    assign_inst_codes(all_rows)
    cols = ["Inst_Code", "Inst_Name", "Branch_Name", "Category", "Year", "Closing_Marks"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    all_rows.sort(key=lambda r: (r["Year"], r["Inst_Code"], r["Branch_Name"], r["Category"]))
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_rows)
    print(f"Wrote {len(all_rows)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
