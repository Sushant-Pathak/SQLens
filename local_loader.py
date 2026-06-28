"""
utils/local_loader.py
─────────────────────
Reads a local Excel file (.xlsx / .xls), parses every sheet,
and returns structured metadata ready for the GPT prompt.

No Google Drive. No service account. Just a file path.

Returned structure (list of dicts, one per sheet):

[
    {
        "sheet_name": "table1",
        "columns": [
            {
                "name":          "id",
                "dtype":         "int64",
                "sample_values": [776172964, 1008517004],
                "nullable":      False
            },
            ...
        ],
        "row_count_approx": 142000
    },
    ...
]
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# How many sample rows to pull per column for the GPT prompt
SAMPLE_ROW_COUNT = 5


# ── Parse ──────────────────────────────────────────────────────────────────────

def _safe_samples(series: pd.Series) -> list:
    """Return up to SAMPLE_ROW_COUNT non-null values that are JSON-safe."""
    raw = series.dropna().head(SAMPLE_ROW_COUNT).tolist()
    result = []
    for v in raw:
        if isinstance(v, (int, float, bool)):
            result.append(v)
        else:
            s = str(v)
            result.append(s[:60])       # cap long strings
    return result


def _parse_excel(file_path: str) -> List[Dict[str, Any]]:
    """
    Open the Excel file, read every sheet, return metadata list.
    Only SAMPLE_ROW_COUNT rows are loaded per sheet for speed —
    the full file is never fully loaded into memory.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Excel file not found: {file_path}")

    xl = pd.ExcelFile(file_path, engine="openpyxl")
    sheets = []

    for sheet_name in xl.sheet_names:
        try:
            # Sample rows only
            df_sample = xl.parse(sheet_name, nrows=SAMPLE_ROW_COUNT)

            # Approximate row count using only first column (fast)
            df_count = xl.parse(sheet_name, usecols=[0])
            approx_rows = len(df_count)

            columns = []
            for col in df_sample.columns:
                columns.append({
                    "name":          str(col),
                    "dtype":         str(df_sample[col].dtype),
                    "sample_values": _safe_samples(df_sample[col]),
                    "nullable":      bool(df_sample[col].isnull().any()),
                })

            sheets.append({
                "sheet_name":       sheet_name,
                "columns":          columns,
                "row_count_approx": approx_rows,
            })

            logger.info("Parsed sheet: %s (%d cols, ~%d rows)",
                        sheet_name, len(columns), approx_rows)

        except Exception as e:
            logger.warning("Skipping sheet '%s': %s", sheet_name, e)

    return sheets


# ── Cache ──────────────────────────────────────────────────────────────────────

def _save_cache(sheets: List[Dict[str, Any]], cache_path: str) -> None:
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(sheets, f, indent=2, default=str)
    logger.info("Metadata cached → %s", cache_path)


def _load_cache(cache_path: str) -> Optional[List[Dict[str, Any]]]:
    if not os.path.exists(cache_path):
        return None
    with open(cache_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Public function ────────────────────────────────────────────────────────────

def load_metadata_from_excel(
    file_path: str,
    cache_path: str  = "metadata_cache.json",
    force_refresh: bool = False,
) -> List[Dict[str, Any]]:
    """
    Main entry point called by the metadata node.

    Parameters
    ----------
    file_path     : Full local path to your .xlsx file
                    e.g. "C:/Users/you/Documents/metadata.xlsx"
                         "/home/you/data/metadata.xlsx"
    cache_path    : Where to store the parsed metadata as JSON.
                    Next run uses cache — Excel is not re-read unless forced.
    force_refresh : Set True to re-read the Excel file even if cache exists.

    Returns
    -------
    List of sheet metadata dicts.
    """
    if not force_refresh:
        cached = _load_cache(cache_path)
        if cached:
            logger.info("Loaded %d sheets from cache: %s",
                        len(cached), cache_path)
            return cached

    logger.info("Reading Excel file: %s", file_path)
    sheets = _parse_excel(file_path)
    _save_cache(sheets, cache_path)
    return sheets


# ── Format for GPT prompt ──────────────────────────────────────────────────────

def sheets_to_prompt_text(sheets: List[Dict[str, Any]]) -> str:
    """
    Convert sheet metadata into compact text that fits inside a GPT prompt.

    Example output:
        ## Table: PNLQuery_table
           Approx rows : 142000
           Columns:
             - leadid          (int64)    | nullable=False | samples: [776172964, ...]
             - BookingDate     (object)   | nullable=False | samples: [2025-02-04, ...]
    """
    lines = []
    for sheet in sheets:
        lines.append(f"## Table: {sheet['sheet_name']}")
        lines.append(f"   Approx rows : {sheet['row_count_approx']}")
        lines.append(f"   Columns:")
        for col in sheet["columns"]:
            samples = ", ".join(str(s) for s in col["sample_values"])
            lines.append(
                f"     - {col['name']:<30} ({col['dtype']:<10}) "
                f"| nullable={col['nullable']} "
                f"| samples: [{samples}]"
            )
        lines.append("")
    return "\n".join(lines)