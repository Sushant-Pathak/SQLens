from openai import OpenAI
from dotenv import load_dotenv
from state.state import GraphState

import os
import json
import textwrap
from datetime import datetime

import pandas as pd
import matplotlib
matplotlib.use("Agg")                      
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.backends.backend_pdf import PdfPages

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "outputs")

ANALYSIS_PROMPT = """
You are a Senior Business Intelligence Analyst at  company.

You will receive:
1. The original user question.
2. The SQL query that was executed.
3. A sample of the data returned (up to 100 rows as JSON).
4. Column names and row count.

Your job:
Write a clear, structured business analysis report of the data.

Report must contain these sections:

EXECUTIVE SUMMARY
  - What the data shows in 2-3 sentences.
  - Key headline number(s).

KEY FINDINGS
  - 3 to 6 bullet points of the most important observations.
  - Mention specific numbers from the data.

TRENDS & PATTERNS
  - Any visible trends, highs, lows, or anomalies.
  - Compare segments if grouping exists.

BUSINESS IMPLICATIONS
  - What does this mean for the business.
  - Any risks or opportunities visible in the data.

RECOMMENDATIONS
  - 2 to 4 actionable recommendations based on the data.

Rules:
- Be specific. Use actual numbers from the data.
- Do not make up numbers not present in the data.
- Keep language professional and concise.
- If data is empty or insufficient, say so clearly.

Return STRICT JSON only. No markdown. No extra text.

Schema:
{
    "executive_summary": "",
    "key_findings": [],
    "trends_and_patterns": "",
    "business_implications": "",
    "recommendations": []
}
"""


# ── Chart helpers ──────────────────────────────────────────────────────────────

def _try_bar_chart(df: pd.DataFrame, pdf: PdfPages, user_query: str) -> bool:
    """
    Draw a bar chart if data has one text column + one numeric column.
    Returns True if chart was drawn.
    """
    text_cols    = [c for c in df.columns if df[c].dtype == object]
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]

    if not text_cols or not numeric_cols:
        return False

    label_col  = text_cols[0]
    value_col  = numeric_cols[0]

    plot_df = df[[label_col, value_col]].dropna().head(20)
    plot_df = plot_df.sort_values(value_col, ascending=False)

    fig, ax = plt.subplots(figsize=(12, 6))
    bars = ax.barh(
        plot_df[label_col].astype(str),
        plot_df[value_col],
        color="#2E75B6",
        edgecolor="white"
    )

    ax.set_xlabel(value_col, fontsize=11)
    ax.set_title(f"{value_col} by {label_col}", fontsize=13, fontweight="bold")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: f"{x:,.0f}"
    ))
    ax.invert_yaxis()

    for bar in bars:
        w = bar.get_width()
        ax.text(
            w * 1.01, bar.get_y() + bar.get_height() / 2,
            f"{w:,.0f}", va="center", fontsize=8
        )

    plt.tight_layout()
    pdf.savefig(fig)
    plt.close(fig)
    return True


def _try_line_chart(df: pd.DataFrame, pdf: PdfPages) -> bool:
    """
    Draw a line chart if data has a date/month column + numeric column.
    Returns True if chart was drawn.
    """
    date_cols    = [c for c in df.columns if any(
        kw in c.lower() for kw in ["date", "month", "year", "period", "week"]
    )]
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]

    if not date_cols or not numeric_cols:
        return False

    date_col  = date_cols[0]
    value_col = numeric_cols[0]

    plot_df = df[[date_col, value_col]].dropna().copy()
    plot_df[date_col] = pd.to_datetime(plot_df[date_col], errors="coerce")
    plot_df = plot_df.dropna(subset=[date_col]).sort_values(date_col)

    if len(plot_df) < 2:
        return False

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(
        plot_df[date_col], plot_df[value_col],
        marker="o", linewidth=2, color="#2E75B6", markersize=5
    )
    ax.fill_between(plot_df[date_col], plot_df[value_col], alpha=0.1, color="#2E75B6")
    ax.set_title(f"{value_col} Over Time", fontsize=13, fontweight="bold")
    ax.set_xlabel(date_col, fontsize=11)
    ax.set_ylabel(value_col, fontsize=11)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    plt.xticks(rotation=45)
    plt.tight_layout()
    pdf.savefig(fig)
    plt.close(fig)
    return True


def _try_pie_chart(df: pd.DataFrame, pdf: PdfPages) -> bool:
    """
    Draw a pie chart if data has one text + one numeric column and <= 10 rows.
    Returns True if chart was drawn.
    """
    text_cols    = [c for c in df.columns if df[c].dtype == object]
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]

    if not text_cols or not numeric_cols or len(df) > 10:
        return False

    label_col  = text_cols[0]
    value_col  = numeric_cols[0]

    plot_df = df[[label_col, value_col]].dropna()
    plot_df = plot_df[plot_df[value_col] > 0]

    if len(plot_df) < 2:
        return False

    fig, ax = plt.subplots(figsize=(9, 7))
    ax.pie(
        plot_df[value_col],
        labels=plot_df[label_col].astype(str),
        autopct="%1.1f%%",
        startangle=140,
        colors=plt.cm.Set3.colors
    )
    ax.set_title(f"{value_col} Share by {label_col}", fontsize=13, fontweight="bold")
    plt.tight_layout()
    pdf.savefig(fig)
    plt.close(fig)
    return True


# ── PDF builder ────────────────────────────────────────────────────────────────

def _build_pdf(
    pdf_path:     str,
    user_query:   str,
    sql:          str,
    df:           pd.DataFrame,
    analysis:     dict,
    request_id:   str,
):
    """
    Build a multi-page PDF:
      Page 1  — Cover + Executive Summary
      Page 2  — Key Findings + Trends + Implications + Recommendations
      Page 3  — Data table (first 50 rows)
      Page 4+ — Charts (bar / line / pie, whichever apply)
    """
    with PdfPages(pdf_path) as pdf:

        # ── Page 1: Cover + Executive Summary ─────────────────────────────────
        fig = plt.figure(figsize=(12, 9))
        fig.patch.set_facecolor("#1F4E79")

        fig.text(0.5, 0.82, "Business Intelligence Report",
                 ha="center", fontsize=26, fontweight="bold", color="white")
        fig.text(0.5, 0.74, user_query,
                 ha="center", fontsize=14, color="#BDD7EE",
                 wrap=True, style="italic")
        fig.text(0.5, 0.66,
                 f"Generated: {datetime.now().strftime('%d %b %Y  %H:%M')}  |  "
                 f"Request: {request_id[:8]}",
                 ha="center", fontsize=10, color="#9DC3E6")

        # Divider
        fig.add_axes([0.1, 0.60, 0.8, 0.002]).set_facecolor("white")
        plt.gca().set_visible(False)

        fig.text(0.1, 0.55, "EXECUTIVE SUMMARY",
                 fontsize=13, fontweight="bold", color="white")
        summary_text = textwrap.fill(
            analysis.get("executive_summary", ""), width=110
        )
        fig.text(0.1, 0.35, summary_text,
                 fontsize=11, color="#BDD7EE", va="top", linespacing=1.6)

        fig.text(0.1, 0.22,
                 f"Total rows returned: {len(df):,}   |   "
                 f"Columns: {', '.join(df.columns.tolist()[:6])}",
                 fontsize=10, color="#9DC3E6")

        pdf.savefig(fig, facecolor=fig.get_facecolor())
        plt.close(fig)

        # ── Page 2: Findings + Trends + Implications + Recommendations ─────────
        fig, ax = plt.subplots(figsize=(12, 9))
        ax.axis("off")

        y = 0.97
        line_gap = 0.032

        def section(title, body_lines):
            nonlocal y
            ax.text(0.0, y, title,
                    fontsize=12, fontweight="bold", color="#1F4E79",
                    transform=ax.transAxes)
            y -= line_gap
            for line in body_lines:
                wrapped = textwrap.wrap(line, width=120)
                for wl in wrapped:
                    ax.text(0.02, y, wl,
                            fontsize=9.5, color="#222222",
                            transform=ax.transAxes)
                    y -= 0.026
            y -= 0.015

        section(
            "KEY FINDINGS",
            [f"• {f}" for f in analysis.get("key_findings", [])]
        )
        section(
            "TRENDS & PATTERNS",
            textwrap.wrap(analysis.get("trends_and_patterns", ""), width=120)
        )
        section(
            "BUSINESS IMPLICATIONS",
            textwrap.wrap(analysis.get("business_implications", ""), width=120)
        )
        section(
            "RECOMMENDATIONS",
            [f"{i+1}. {r}" for i, r in enumerate(analysis.get("recommendations", []))]
        )

        pdf.savefig(fig)
        plt.close(fig)

        # ── Page 3: Data table ─────────────────────────────────────────────────
        table_df = df.head(50)
        n_cols   = len(table_df.columns)
        fig_w    = max(12, n_cols * 1.8)
        fig, ax  = plt.subplots(figsize=(fig_w, max(6, len(table_df) * 0.32 + 2)))
        ax.axis("off")

        ax.set_title(
            f"Data Preview — first {len(table_df)} of {len(df):,} rows",
            fontsize=12, fontweight="bold", color="#1F4E79", pad=14
        )

        col_labels = list(table_df.columns)
        cell_text  = [
            [str(v)[:30] if pd.notna(v) else "" for v in row]
            for row in table_df.values
        ]

        tbl = ax.table(
            cellText=cell_text,
            colLabels=col_labels,
            loc="center",
            cellLoc="center"
        )
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(8)
        tbl.auto_set_column_width(col=list(range(n_cols)))

        for (r, c), cell in tbl.get_celld().items():
            if r == 0:
                cell.set_facecolor("#1F4E79")
                cell.set_text_props(color="white", fontweight="bold")
            elif r % 2 == 0:
                cell.set_facecolor("#EBF3FB")
            cell.set_edgecolor("#CCCCCC")

        plt.tight_layout()
        pdf.savefig(fig)
        plt.close(fig)

        # ── Page 4+: Charts ───────────────────────────────────────────────────
        _try_line_chart(df, pdf)
        _try_bar_chart(df, pdf, user_query)
        _try_pie_chart(df, pdf)

        # ── PDF metadata ──────────────────────────────────────────────────────
        info = pdf.infodict()
        info["Title"]   = f"BI Report — {user_query[:60]}"
        info["Author"]  = "Analytics SQL Agent"
        info["Subject"] = "Auto-generated business intelligence report"


# ── Main node function ─────────────────────────────────────────────────────────

def analyse_and_report(state: GraphState) -> GraphState:

    if state.get("execution_status") != "success":
        state["error"] = "Cannot analyse: SQL execution did not succeed"
        return state

    result_data    = state.get("result_data", [])
    result_columns = state.get("result_columns", [])
    user_query     = state.get("user_query", "")
    sql            = state.get("validated_sql", "") or state.get("generated_sql", "")
    request_id     = state.get("request_id", "result")
    row_count      = state.get("row_count", 0)

    df = pd.DataFrame(result_data, columns=result_columns)

    # ── Step 1: AI analysis ────────────────────────────────────────────────────
    print("\n===== GENERATING AI ANALYSIS =====")

    sample_rows = df.head(100).to_dict(orient="records")

    user_message = """
USER QUESTION:
{user_query}

SQL EXECUTED:
{sql}

ROW COUNT: {row_count}
COLUMNS  : {columns}

DATA SAMPLE (up to 100 rows):
{sample}
""".format(
        user_query=user_query,
        sql=sql,
        row_count=row_count,
        columns=result_columns,
        sample=json.dumps(sample_rows, indent=2, default=str)
    )

    response = client.chat.completions.create(
        model="gpt-4.1",
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": ANALYSIS_PROMPT
            },
            {
                "role": "user",
                "content": user_message
            }
        ]
    )

    analysis = json.loads(response.choices[0].message.content)

    print("\n===== AI ANALYSIS =====")
    print("Executive Summary :", analysis.get("executive_summary", ""))
    print("Key Findings      :")
    for f in analysis.get("key_findings", []):
        print(f"  • {f}")
    print("Recommendations   :")
    for r in analysis.get("recommendations", []):
        print(f"  → {r}")

    # ── Step 2: Build PDF ──────────────────────────────────────────────────────
    print("\n===== BUILDING PDF REPORT =====")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    pdf_path = os.path.join(OUTPUT_DIR, f"{request_id}_report.pdf")

    _build_pdf(
        pdf_path=pdf_path,
        user_query=user_query,
        sql=sql,
        df=df,
        analysis=analysis,
        request_id=request_id,
    )

    print(f"PDF saved: {pdf_path}")

    # ── Step 3: Write into state ───────────────────────────────────────────────
    state["analysis_text"] = json.dumps(analysis, indent=2)
    state["pdf_path"]      = pdf_path

    print("\n===== OUTPUTS READY =====")
    print(f"CSV    : {state.get('csv_path')}")
    print(f"PDF    : {pdf_path}")

    return state