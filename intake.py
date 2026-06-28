import uuid
from datetime import datetime

from state.state import GraphState


def user_query_intake(state: GraphState) -> GraphState:
    """
    First node of graph.
    Cleans and validates incoming query.
    """

    query = state.get("user_query", "").strip()

    if not query:
        state["error"] = "User query cannot be empty"
        return state

    state["request_id"] = str(uuid.uuid4())

    state["created_at"] = datetime.utcnow().isoformat()

    state["user_query"] = query

    print("\n" + "=" * 80)
    print("USER QUERY RECEIVED")
    print("=" * 80)
    print(f"Request ID : {state['request_id']}")
    print(f"Query      : {query}")
    print("=" * 80)

    return state