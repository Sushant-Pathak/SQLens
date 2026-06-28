from openai import OpenAI
from dotenv import load_dotenv
from state.state import GraphState

import os
import json

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

SQL_PROMPT = """
You are a Senior SQL Server (T-SQL) Query Writer.

You are part of a Text-to-SQL pipeline for an analytics company.

You will receive:
1. The original user question.
2. Time context — start_date, end_date, granularity.
3. Extracted business entities — metrics, filters, dimensions, group_by.
4. Metadata context — selected tables, columns per table, join criteria,
   filter conditions, and aggregation decided by the metadata selection step.

Your job:
Write ONE clean, correct, production-ready T-SQL SELECT query.

SQL WRITING RULES:

1.  Always use WITH (NOLOCK) on every table reference.
2.  Always use table alias (e.g. p for table1).
3.  Always qualify every column with its alias (p.id, not just id).
4.  Date filters must use:
      col >= 'start_date' AND col < DATEADD(DAY, 1, 'end_date')
5.  Never use SELECT *. Only select columns that answer the question.
6.  Always apply status_flag = 1 unless user explicitly asks for cancelled.
7. For COUNT of ids use COUNT(DISTINCT p.id).
8. Add ORDER BY only when user asks for ranking or top N.
9. Add TOP N only when user specifies a limit.
10. If grouping needed, every non-aggregated SELECT column must be in GROUP BY.
11. Format the SQL cleanly with indentation.
12. Do NOT add any explanation. Return SQL only inside the json field.
13. Do NOT wrap SQL in markdown code blocks.

COLUMN REFERENCE (use only columns confirmed in metadata context):

Common columns in table1:
  id, amount, value, createdat, bookingdate

Return STRICT JSON only. No markdown. No explanation.

Schema:

{
    "sql": "SELECT ... FROM ... WHERE ...",
    "tables_used": ["table1"],
    "columns_used": ["id", "BookingDate", "amount"],
    "filters_applied": ["Category = 'General'", "status_flag = 1"],
    "aggregation_used": "SUM(amount)",
    "confidence": "high",
    "notes": ""
}

confidence values:
  high   — all required columns found in metadata, query is straightforward
  medium — some assumptions made, minor ambiguity in request
  low    — significant assumptions made, user should verify output
"""


def generate_sql(state: GraphState) -> GraphState:

    user_query       = state.get("user_query", "")
    time_context     = state.get("time_context", {})
    entities         = state.get("entities", {})
    metadata_context = state.get("metadata_context", "")
    selected_tables  = state.get("selected_tables", [])
    selected_columns = state.get("selected_columns", [])
    join_criteria    = state.get("join_criteria", [])

    user_message = """
USER QUESTION:
{user_query}

TIME CONTEXT:
{time_context}

EXTRACTED ENTITIES:
{entities}

METADATA CONTEXT:
{metadata_context}

SELECTED TABLES  : {selected_tables}
SELECTED COLUMNS : {selected_columns}
JOIN CRITERIA    : {join_criteria}
""".format(
        user_query=user_query,
        time_context=json.dumps(time_context, indent=2),
        entities=json.dumps(entities, indent=2),
        metadata_context=metadata_context,
        selected_tables=selected_tables,
        selected_columns=selected_columns,
        join_criteria=json.dumps(join_criteria, indent=2),
    )

    response = client.chat.completions.create(
        model="gpt-4.1",
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": SQL_PROMPT
            },
            {
                "role": "user",
                "content": user_message
            }
        ]
    )

    result = json.loads(
        response.choices[0].message.content
    )

    state["generated_sql"]   = result.get("sql", "")
    state["validated_sql"]   = result.get("sql", "")

    print("\n===== GENERATED SQL =====")
    print(state["generated_sql"])

    print("\n===== SQL DETAILS =====")
    print(f"Tables used    : {result.get('tables_used', [])}")
    print(f"Columns used   : {result.get('columns_used', [])}")
    print(f"Filters applied: {result.get('filters_applied', [])}")
    print(f"Aggregation    : {result.get('aggregation_used', '')}")
    print(f"Confidence     : {result.get('confidence', '')}")
    if result.get("notes"):
        print(f"Notes          : {result.get('notes', '')}")

    return state