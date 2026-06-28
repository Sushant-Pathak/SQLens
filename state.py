from typing import TypedDict, Optional, List, Dict, Any


class GraphState(TypedDict):
    user_query: str
    normalized_query: str
    request_id: str
    created_at: str
    start_date: Optional[str]
    end_date: Optional[str]
    intent: Optional[str]
    selected_tables: List[str]
    selected_columns: List[str]
    generated_sql: Optional[str]
    validated_sql: Optional[str]
    execution_status: Optional[str]
    result_dataframe_path: Optional[str]
    output_file: Optional[str]
    error: Optional[str]
    time_context: dict
    entities: Dict[str, Any]
    metadata_sheets: List[Dict[str, Any]]
    join_criteria: List[Dict[str, Any]]
    metadata_context: Optional[str]
    row_count: Optional[int]
    result_columns: List[str]
    result_data: List[Dict[str, Any]]
    csv_path: Optional[str]
    analysis_text: Optional[str]
    pdf_path: Optional[str]