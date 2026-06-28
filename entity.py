from openai import OpenAI
from state.state import GraphState
from dotenv import load_dotenv

import json
import os

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

ENTITY_PROMPT = """
You are a Principal Data Analyst.

You are helping build a Text-to-SQL system.

Your task is to understand the user's business intent and extract all analytical entities.

Rules:

1. Never generate SQL.
2. Never assume table names.
3. Only identify analytical intent.
4. Convert relative dates into structured form.
5. Identify business metrics.
6. Identify dimensions.
7. Identify filters.
8. Identify grouping requirements.
9. Identify sorting requirements.
10. Identify output requirements.

Possible metrics:
APE
Revenue
Premium
Policy Count
Login Count
Issued Count
Conversion
Payout
Commission

Return STRICT JSON only.

Required JSON Schema:

{
    "user_intent":"",
    "metrics":[],
    "dimensions":[],
    "filters":{},
    "aggregation":"",
    "time_filter":{},
    "group_by":[],
    "order_by":[],
    "limit":null,
    "output":"table"
}
"""

def extract_entities(state: GraphState) -> GraphState:

    query = state.get("user_query", "").strip()

    response = client.chat.completions.create(
        model="gpt-4.1",
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": ENTITY_PROMPT
            },
            {
                "role": "user",
                "content": query
            }
        ]
    )

    entities = json.loads(
        response.choices[0].message.content
    )

    state["entities"] = entities

    print("\n===== EXTRACTED ENTITIES =====")
    print(json.dumps(entities, indent=4))

    return state