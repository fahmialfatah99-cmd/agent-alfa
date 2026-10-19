"""
Deterministic Tabular Data Analyzer for Document Spreadsheets and Tables.
Provides exact numerical calculations, aggregations, filtering, and summarization
using Pandas so the agent never hallucinates numbers from document tables:
- Supports CSV, TSV, XLSX, XLS.
- Exact arithmetic operations: SUM, MEAN, MIN, MAX, COUNT, GROUP BY.
- Generates clean Markdown tables for immediate LLM response.
"""

import logging
import os
from typing import Any

logger = logging.getLogger("TableAnalyzer")

_TAB_ERR = (
    OSError,
    ValueError,
    RuntimeError,
    TypeError,
    KeyError,
    AttributeError,
    ImportError,
)


def _load_dataframe(file_path: str, sheet_name: str | None = None) -> Any:
    """Load a spreadsheet or CSV file into a pandas DataFrame safely."""
    import pandas as pd

    ext = os.path.splitext(file_path)[1].lower().lstrip(".")
    if ext in ("csv", "txt"):
        return pd.read_csv(file_path, on_bad_lines="skip")
    if ext == "tsv":
        return pd.read_csv(file_path, sep="\t", on_bad_lines="skip")
    if ext in ("xlsx", "xls", "xlsm", "ods"):
        return pd.read_excel(file_path, sheet_name=sheet_name or 0)
    raise ValueError(f"Format file '{ext}' tidak didukung untuk analisis tabel.")


def inspect_table_structure(
    file_path: str, sheet_name: str | None = None
) -> dict[str, Any]:
    """
    Inspects columns, row counts, data types, and sheet names of a tabular document.
    """
    if not os.path.isfile(file_path):
        return {"status": "error", "message": f"Berkas '{file_path}' tidak ditemukan."}

    try:
        import pandas as pd

        ext = os.path.splitext(file_path)[1].lower().lstrip(".")
        available_sheets = []
        if ext in ("xlsx", "xls", "xlsm", "ods"):
            xl = pd.ExcelFile(file_path)
            available_sheets = xl.sheet_names

        df = _load_dataframe(file_path, sheet_name=sheet_name)
        cols_info = []
        for col in df.columns:
            cols_info.append({
                "column": str(col),
                "dtype": str(df[col].dtype),
                "non_null_count": int(df[col].count()),
            })

        preview_md = df.head(5).fillna("").to_markdown(index=False)

        return {
            "status": "success",
            "file": os.path.basename(file_path),
            "total_rows": len(df),
            "total_columns": len(df.columns),
            "sheets": available_sheets,
            "columns": cols_info,
            "preview_markdown": preview_md,
        }
    except _TAB_ERR as e:
        logger.error(f"Error inspecting table {file_path}: {e}")
        return {"status": "error", "message": f"Gagal memeriksa tabel: {str(e)}"}


def analyze_tabular_data(
    file_path: str,
    operation: str = "summary",
    sheet_name: str | None = None,
    filter_column: str | None = None,
    filter_value: Any = None,
    group_by: str | None = None,
    agg_column: str | None = None,
    agg_func: str = "sum",
    sort_column: str | None = None,
    ascending: bool = False,
    limit: int = 20,
) -> dict[str, Any]:
    """
    Performs deterministic mathematical and statistical analysis on document tables.

    Operations:
    - 'summary': Descriptive statistics for numeric columns.
    - 'filter': Filter rows where `filter_column` matches `filter_value`.
    - 'aggregate': Group by a column and compute sum/mean/min/max/count.
    - 'top_n': Sort rows by `sort_column`.
    """
    if not os.path.isfile(file_path):
        return {"status": "error", "message": f"Berkas '{file_path}' tidak ditemukan."}

    try:

        df = _load_dataframe(file_path, sheet_name=sheet_name)
        if df.empty:
            return {"status": "error", "message": "Tabel dalam dokumen kosong."}

        op = operation.lower().strip()

        # 1. SUMMARY STATS
        if op == "summary":
            desc = df.describe().round(2).reset_index()
            md_res = desc.to_markdown(index=False)
            return {
                "status": "success",
                "operation": "summary",
                "total_rows": len(df),
                "markdown_result": md_res,
                "message": f"Statistik deskriptif berhasil dihitung untuk {len(df)} baris.",
            }

        # 2. FILTER ROWS
        if op == "filter":
            if not filter_column or filter_column not in df.columns:
                return {
                    "status": "error",
                    "message": f"Kolom filter '{filter_column}' tidak ditemukan. Kolom tersedia: {list(df.columns)}",
                }
            filtered_df = df[df[filter_column].astype(str).str.contains(str(filter_value), case=False, na=False)]
            md_res = filtered_df.head(limit).fillna("").to_markdown(index=False)
            return {
                "status": "success",
                "operation": "filter",
                "matched_rows": len(filtered_df),
                "markdown_result": md_res,
                "message": f"Ditemukan {len(filtered_df)} baris yang cocok dengan '{filter_column} == {filter_value}'.",
            }

        # 3. AGGREGATION / GROUP BY
        if op == "aggregate":
            if not group_by or group_by not in df.columns:
                return {
                    "status": "error",
                    "message": f"Kolom group_by '{group_by}' tidak valid.",
                }
            if not agg_column or agg_column not in df.columns:
                return {
                    "status": "error",
                    "message": f"Kolom agg_column '{agg_column}' tidak valid.",
                }

            grouped = df.groupby(group_by)[agg_column].agg(agg_func).reset_index()
            if isinstance(grouped[agg_column].iloc[0], (int, float)):
                grouped[agg_column] = grouped[agg_column].round(2)
            md_res = grouped.head(limit).to_markdown(index=False)
            return {
                "status": "success",
                "operation": "aggregate",
                "grouped_by": group_by,
                "agg_func": agg_func,
                "markdown_result": md_res,
                "message": f"Agregasi {agg_func.upper()}({agg_column}) berdasarkan '{group_by}' berhasil.",
            }

        # 4. TOP N
        if op == "top_n":
            col = sort_column or df.columns[0]
            if col not in df.columns:
                return {
                    "status": "error",
                    "message": f"Kolom pengurutan '{col}' tidak ditemukan.",
                }
            sorted_df = df.sort_values(by=col, ascending=ascending).head(limit)
            md_res = sorted_df.fillna("").to_markdown(index=False)
            return {
                "status": "success",
                "operation": "top_n",
                "sorted_by": col,
                "markdown_result": md_res,
                "message": f"{limit} baris teratas diurutkan berdasarkan '{col}'.",
            }

        return {
            "status": "error",
            "message": f"Operasi '{operation}' tidak dikenal. Pilih: 'summary', 'filter', 'aggregate', atau 'top_n'.",
        }

    except _TAB_ERR as e:
        logger.error(f"Error analyzing tabular data {file_path}: {e}")
        return {"status": "error", "message": f"Gagal menganalisis data tabel: {str(e)}"}
