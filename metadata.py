"""
nodes/metadata.py
─────────────────
Metadata selection node.

Same pattern as entity.py and time_slicer.py:
  - Takes GraphState
  - Does its work
  - Writes results back into state
  - Returns state

What this node does:
  1. Reads sheet metadata from a local Excel file (path set in .env).
  2. Sends metadata catalog + user query + time_context + entities to GPT.
  3. GPT returns which tables, which columns, how to join, what filters.
  4. Writes everything into state for the SQL generation node.

State keys written:
  metadata_sheets   → raw list of all sheet metadata from Excel
  selected_tables   → ["table_name"]
  selected_columns  → ["table.leadid", "table.amount", ...]
  join_criteria     → [] or [{left_table, right_table, left_key, right_key, join_type}]
  metadata_context  → full structured text the SQL node reads to build the query
"""

import json
import os

from openai import OpenAI
from dotenv import load_dotenv

from state.state import GraphState
from utils.local_loader import load_metadata_from_excel, sheets_to_prompt_text

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

# ── Config — set these in your .env file ──────────────────────────────────────
EXCEL_FILE_PATH   = os.getenv("METADATA_EXCEL_PATH",   "metadata.xlsx")
METADATA_CACHE    = os.getenv("METADATA_CACHE_PATH",    "metadata_cache.json")
FORCE_REFRESH     = os.getenv("FORCE_REFRESH_METADATA", "false").lower() == "true"


# ── GPT prompt ─────────────────────────────────────────────────────────────────

METADATA_PROMPT = """
You are a senior SQL data engineer for an analytics company.

You will be given:
1. A user's business question.
2. Time context (start date, end date, granularity).
3. Extracted business entities (metrics, filters, dimensions).
4. A catalog of available database tables with column names, data types, and sample values.

Your job:
  A. Choose the MINIMUM tables needed to answer the question.
  B. For each table, list only the columns actually needed.
  C. If more than one table is needed, provide join instructions.
  D. Identify filter conditions based on entities and table knowledge.
  E. Identify the aggregation needed.

Business rules you must know:
  -specify business rules here 

Return STRICT JSON only. No markdown. No extra text.

Schema:

{
    "selected_tables": ["TableName1"],
    "selected_columns": {
        "TableName1": ["col1", "col2", "col3"],
        "TableName2": ["col1", "col4"]
    },
    "join_criteria": [
        {
            "left_table":  "TableName1",
            "right_table": "TableName2",
            "left_key":    "leadid",
            "right_key":   "leadid",
            "join_type":   "INNER"
        }
    ],
    "time_column": "BookingDate",
    "time_table":  "TableName1",
    "filter_conditions": [
        "BU = 'Motor'",
        "status_flag = 1"
    ],
    "aggregation": {
        "metric_column": "amount",
        "agg_function":  "SUM",
        "alias":         "Total_amount"
    },
    "group_by_columns": [],
    "reasoning": "Brief explanation of table and column choices."
}

If only one table is needed, set join_criteria to [].
If no grouping is needed, set group_by_columns to [].
"""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _call_gpt(
    user_query:    str,
    time_context:  dict,
    entities:      dict,
    metadata_text: str
) -> dict:
    """Send everything to GPT, return parsed JSON dict."""

    user_message = f"""
USER QUESTION:
{user_query}

TIME CONTEXT:
{json.dumps(time_context, indent=2)}

EXTRACTED ENTITIES:
{json.dumps(entities, indent=2)}

AVAILABLE TABLES (metadata catalog):
{metadata_text}
"""

    response = client.chat.completions.create(
        model="gpt-4.1",
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": METADATA_PROMPT
            },
            {
                "role": "user",
                "content": user_message
            }
        ]
    )

    return json.loads(response.choices[0].message.content)


def _flatten_columns(selected_columns_dict: dict) -> list:
    """
    {"T1": ["a", "b"], "T2": ["c"]}
    → ["T1.a", "T1.b", "T2.c"]
    """
    flat = []
    for table, cols in selected_columns_dict.items():
        for col in cols:
            flat.append(f"{table}.{col}")
    return flat


def _build_metadata_context(gpt_result: dict) -> str:
    """
    Build the structured text block the SQL generation node will read.
    Contains tables, columns, joins, filters, aggregation — all in one place.
    """
    selected_tables    = gpt_result.get("selected_tables",    [])
    selected_cols_dict = gpt_result.get("selected_columns",   {})
    join_criteria      = gpt_result.get("join_criteria",      [])
    time_column        = gpt_result.get("time_column",        "BookingDate")
    time_table         = gpt_result.get("time_table",         "")
    filter_conditions  = gpt_result.get("filter_conditions",  [])
    aggregation        = gpt_result.get("aggregation",        {})
    group_by_columns   = gpt_result.get("group_by_columns",   [])
    reasoning          = gpt_result.get("reasoning",          "")

    lines = [
        "=== METADATA CONTEXT FOR SQL GENERATION ===",
        "",
        f"SELECTED TABLES : {', '.join(selected_tables)}",
        "",
        "COLUMNS PER TABLE:",
    ]

    for table, cols in selected_cols_dict.items():
        lines.append(f"  {table} → {', '.join(cols)}")

    lines.append("")

    if join_criteria:
        lines.append("JOIN CRITERIA:")
        for j in join_criteria:
            lines.append(
                f"  {j['join_type']} JOIN {j['right_table']} "
                f"ON {j['left_table']}.{j['left_key']} = "
                f"{j['right_table']}.{j['right_key']}"
            )
        lines.append("")

    lines.append(f"TIME COLUMN     : {time_table}.{time_column}")
    lines.append("")

    if filter_conditions:
        lines.append("FILTER CONDITIONS:")
        for f in filter_conditions:
            lines.append(f"  {f}")
        lines.append("")

    if aggregation:
        lines.append("AGGREGATION:")
        lines.append(
            f"  {aggregation.get('agg_function', 'SUM')}"
            f"({aggregation.get('metric_column', 'master_payout')}) "
            f"AS {aggregation.get('alias', 'Total_Value')}"
        )
        lines.append("")

    if group_by_columns:
        lines.append(f"GROUP BY        : {', '.join(group_by_columns)}")
        lines.append("")

    lines.append(f"REASONING       : {reasoning}")
    lines.append("")
    lines.append("===========================================")

    return "\n".join(lines)


# ── Main node function ─────────────────────────────────────────────────────────

def retrieve_metadata(state: GraphState) -> GraphState:
    """
    Metadata selection node.

    Reads  : state["user_query"], state["time_context"], state["entities"]
    Writes : state["metadata_sheets"], state["selected_tables"],
             state["selected_columns"], state["join_criteria"],
             state["metadata_context"]
    """

    # Step 1 — Load sheet metadata from local Excel (or cache)
    sheets_meta = load_metadata_from_excel(
        file_path=EXCEL_FILE_PATH,
        cache_path=METADATA_CACHE,
        force_refresh=FORCE_REFRESH,
    )

    # Step 2 — Convert to prompt-friendly text
    metadata_text = sheets_to_prompt_text(sheets_meta)

    # Step 3 — Call GPT with full context
    gpt_result = _call_gpt(
        user_query=state.get("user_query", ""),
        time_context=state.get("time_context", {}),
        entities=state.get("entities", {}),
        metadata_text=metadata_text,
    )

    # Step 4 — Pull results out of GPT response
    selected_tables    = gpt_result.get("selected_tables", [])
    selected_cols_dict = gpt_result.get("selected_columns", {})
    join_criteria      = gpt_result.get("join_criteria", [])

    # Step 5 — Build metadata_context for SQL node
    metadata_context = _build_metadata_context(gpt_result)

    # Step 6 — Write into state (same pattern as entity.py / time_slicer.py)
    state["metadata_sheets"]  = sheets_meta
    state["selected_tables"]  = selected_tables
    state["selected_columns"] = _flatten_columns(selected_cols_dict)
    state["join_criteria"]    = join_criteria
    state["metadata_context"] = metadata_context

    # Step 7 — Print summary
    print("\n===== METADATA SELECTION =====")
    print(f"Tables    : {selected_tables}")
    print(f"Joins     : {join_criteria}")
    print(f"Filters   : {gpt_result.get('filter_conditions', [])}")
    print(f"Agg       : {gpt_result.get('aggregation', {})}")
    print(f"Reasoning : {gpt_result.get('reasoning', '')}")
    print("\n--- Metadata Context (passed to SQL node) ---")
    print(metadata_context)

    return state