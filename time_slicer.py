from openai import OpenAI
from dotenv import load_dotenv
from state.state import GraphState

import os
import json

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

TIME_PROMPT = """
You are a Time Resolver for a SQL Agent.

Today's date is {today}.

Your task:

Convert user's time requirements into structured JSON.

Supported examples:

last month
this month
last 3 months
last 6 months
last year
this year
last 2 years
YTD
MTD
QTD
FY2025
FY2026
Apr 2025
between Apr 2025 and Jul 2025

Return STRICT JSON.

Schema:

{{
    "time_found": true,
    "start_date": "",
    "end_date": "",
    "granularity": "",
    "time_column_hint": ""
}}

User Query:
{query}
"""

def resolve_time(state: GraphState) -> GraphState:

    query = state.get("user_query", "")

    response = client.chat.completions.create(
        model="gpt-4.1",
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": TIME_PROMPT.format(
                    query=query,
                    today="2026-06-10"
                )
            }
        ]
    )

    state["time_context"] = json.loads(
        response.choices[0].message.content
    )

    return state