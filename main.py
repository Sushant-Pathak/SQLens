from nodes.intake            import user_query_intake
from nodes.entity            import extract_entities
from nodes.time_slicer       import resolve_time
from nodes.metadata          import retrieve_metadata
from nodes.sql_generator     import generate_sql
from nodes.execute_sql       import execute_sql           # ← NEW
from nodes.analyse_and_report import analyse_and_report   # ← NEW

from state.state import GraphState


def main():

    query = input("\nAsk your business question:\n\n> ")

    state: GraphState = {
        "user_query":            query,
        "normalized_query":      "",
        "request_id":            "",
        "created_at":            "",
        "start_date":            None,
        "end_date":              None,
        "intent":                None,
        "selected_tables":       [],
        "selected_columns":      [],
        "generated_sql":         None,
        "validated_sql":         None,
        "execution_status":      None,
        "result_dataframe_path": None,
        "output_file":           None,
        "error":                 None,
        "time_context":          None,
        "entities":              {},
        "metadata_sheets":       [],
        "join_criteria":         [],
        "metadata_context":      None,
        # New keys
        "row_count":             None,
        "result_columns":        [],
        "result_data":           [],
        "csv_path":              None,
        "analysis_text":         None,
        "pdf_path":              None,
    }

    # ── Step 1: Intake ─────────────────────────────────────────────────────────
    state = user_query_intake(state)

    print("\nSTATE AFTER NODE\n")
    print(state)

    # ── Step 2: Entity extraction ──────────────────────────────────────────────
    state = extract_entities(state)

    print("\nExtracted Entities")
    print(state.get("entities"))

    # ── Step 3: Time resolution ────────────────────────────────────────────────
    state = resolve_time(state)

    print("\nReturned from resolve_time():")
    print(state.get("time_context"))

    print("\nState time_context:")
    print(state.get("time_context"))

    # ── Step 4: Metadata retrieval ─────────────────────────────────────────────
    state = retrieve_metadata(state)

    print("\nReturned from retrieve_metadata():")
    print("Selected tables  :", state.get("selected_tables"))
    print("Selected columns :", state.get("selected_columns"))
    print("Join criteria    :", state.get("join_criteria"))

    # ── Step 5: SQL generation ─────────────────────────────────────────────────
    state = generate_sql(state)

    print("\nReturned from generate_sql():")
    print("Generated SQL :", state.get("generated_sql"))

    # ── Step 6: Execute SQL against MS SQL Server ──────────────────────────────
    state = execute_sql(state)                            # ← NEW

    print("\nReturned from execute_sql():")
    print("Execution status :", state.get("execution_status"))
    print("Row count        :", state.get("row_count"))
    print("CSV path         :", state.get("csv_path"))

    if state.get("execution_status") != "success":
        print("\nERROR:", state.get("error"))
        return

    # ── Step 7: AI analysis + PDF report ──────────────────────────────────────
    state = analyse_and_report(state)                     # ← NEW

    print("\nReturned from analyse_and_report():")
    print("PDF path         :", state.get("pdf_path"))
    print("CSV path         :", state.get("csv_path"))

    print("\n" + "=" * 80)
    print("PIPELINE COMPLETE")
    print("=" * 80)
    print(f"  CSV report  → {state.get('csv_path')}")
    print(f"  PDF report  → {state.get('pdf_path')}")
    print("=" * 80)


if __name__ == "__main__":
    main()