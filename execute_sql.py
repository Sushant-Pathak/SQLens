from dotenv import load_dotenv
from state.state import GraphState

import os
import re
import time
import pyodbc
import pandas as pd

load_dotenv()

# ── DB config — all values from .env ──────────────────────────────────────────
DB_DRIVER   = os.getenv("DB_DRIVER",   "{ODBC Driver 17 for SQL Server}")
DB_HOST     = os.getenv("DB_HOST",     "")
DB_NAME     = os.getenv("DB_NAME",     "")
DB_USER     = os.getenv("DB_USER",     "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

# ── Blocked SQL keywords — any of these = hard stop ───────────────────────────
BLOCKED_KEYWORDS = [
    "DROP",
    "DELETE",
    "ALTER",
    "TRUNCATE",
    "UPDATE",
    "INSERT",
    "MERGE",
    "EXEC",
    "EXECUTE",
    "CREATE",
    "REPLACE",
    "RENAME",
]


# ── Safety check ───────────────────────────────────────────────────────────────

def _check_sql_safety(sql: str) -> tuple:
    """
    Scan the SQL string for any blocked keywords.

    Returns
    -------
    (True, "")           — safe to execute
    (False, reason_msg)  — blocked, reason explains which keyword was found

    How it works:
    - Strips comments (-- single line and /* block */) before scanning
      so commented-out DROP etc. do not trigger a false positive.
    - Uses word-boundary regex so 'DROPSHIP' or 'DELETED_AT' do not match.
    - Case-insensitive.
    """

    # Remove single-line comments
    sql_clean = re.sub(r"--[^\n]*", " ", sql)

    # Remove block comments
    sql_clean = re.sub(r"/\*.*?\*/", " ", sql_clean, flags=re.DOTALL)

    for keyword in BLOCKED_KEYWORDS:
        pattern = rf"\b{keyword}\b"
        if re.search(pattern, sql_clean, flags=re.IGNORECASE):
            reason = (
                f"BLOCKED: SQL contains forbidden keyword '{keyword}'. "
                f"Only SELECT statements are permitted. "
                f"DROP / DELETE / ALTER / TRUNCATE / UPDATE / INSERT "
                f"and other write operations are not allowed."
            )
            return False, reason

    return True, ""


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _get_connection():
    conn = pyodbc.connect(
        driver=DB_DRIVER,
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )
    return conn


def _run_query(query: str) -> pd.DataFrame:
    input_time = time.time()

    conn = _get_connection()
    print("Connected to DB")

    df = pd.read_sql_query(query, con=conn)

    print("Number of rows in Data - " + str(df.shape[0]))

    final_time = time.time()
    print("Data retrieved in " + str(round(final_time - input_time, 2)) + " seconds")

    conn.close()

    return df


# ── Main node function ─────────────────────────────────────────────────────────

def execute_sql(state: GraphState) -> GraphState:

    sql = state.get("validated_sql", "") or state.get("generated_sql", "")

    if not sql:
        state["error"]            = "No SQL found in state to execute"
        state["execution_status"] = "failed"
        return state

    print("\n===== EXECUTING SQL =====")
    print(sql)

    # ── Safety check BEFORE touching the DB ───────────────────────────────────
    is_safe, block_reason = _check_sql_safety(sql)

    if not is_safe:
        print("\n===== SQL BLOCKED =====")
        print(block_reason)

        state["error"]            = block_reason
        state["execution_status"] = "blocked"
        state["row_count"]        = 0
        state["result_data"]      = []
        state["result_columns"]   = []
        state["csv_path"]         = None
        return state

    # ── Safe — execute ─────────────────────────────────────────────────────────
    try:
        df = _run_query(sql)

        output_dir = os.getenv("OUTPUT_DIR", "outputs")
        os.makedirs(output_dir, exist_ok=True)

        request_id = state.get("request_id", "result")
        csv_path   = os.path.join(output_dir, f"{request_id}_data.csv")
        df.to_csv(csv_path, index=False)

        state["execution_status"] = "success"
        state["row_count"]        = len(df)
        state["result_columns"]   = list(df.columns)
        state["result_data"]      = df.head(500).to_dict(orient="records")
        state["csv_path"]         = csv_path
        state["output_file"]      = csv_path

        print("\n===== EXECUTION RESULT =====")
        print(f"Status   : success")
        print(f"Rows     : {len(df)}")
        print(f"Columns  : {list(df.columns)}")
        print(f"CSV saved: {csv_path}")
        print(df.head(10).to_string(index=False))

    except Exception as e:
        state["error"]            = f"SQL execution failed: {str(e)}"
        state["execution_status"] = "failed"
        state["row_count"]        = 0
        state["result_data"]      = []
        state["result_columns"]   = []
        print(f"\n===== EXECUTION FAILED =====\n{e}")

    return state