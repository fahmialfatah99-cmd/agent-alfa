"""Query SQL read-only terhadap SQLite lokal."""
import logging
import os
import sqlite3
from typing import Any

from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.Integrations")

@register_tool(category="system")
def query_database(db_path: str, sql_query: str) -> dict[str, Any]:
    """
    Execute a SQL query on a local SQLite database file and return the results as a table.

    Args:
        db_path: Path to the SQLite database file (e.g. '~/data/app.db', 'bot_database.db').
        sql_query: SQL query to execute (SELECT, INSERT, UPDATE, DELETE, etc.).

    Security Note: This function accepts raw SQL queries. Ensure input is validated
    before calling this function to prevent SQL injection attacks.
    """
    try:
        expanded = os.path.expanduser(db_path)
        if not os.path.exists(expanded):
            return {
                "status": "error",
                "message": f"Database file tidak ditemukan: {db_path}",
            }

        # Security validation: Block dangerous statements
        query_upper = sql_query.strip().upper()
        dangerous_keywords = [
            "DROP ",
            "DELETE FROM ",
            "TRUNCATE",
            "ALTER ",
            "CREATE INDEX",
            "DETACH DATABASE",
            "ATTACH DATABASE",
        ]
        for keyword in dangerous_keywords:
            if keyword in query_upper:
                return {
                    "status": "error",
                    "message": f"Potensi SQL injection terdeteksi: '{keyword}' tidak diizinkan.",
                }

        conn = sqlite3.connect(expanded)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(sql_query)

        query_upper = sql_query.strip().upper()
        if (
            query_upper.startswith("SELECT")
            or query_upper.startswith("PRAGMA")
            or query_upper.startswith("WITH")
        ):
            rows = cursor.fetchall()
            columns = (
                [desc[0] for desc in cursor.description] if cursor.description else []
            )
            data = [dict(row) for row in rows[:100]]
            conn.close()
            return {
                "status": "success",
                "columns": columns,
                "row_count": len(data),
                "total_available": (
                    len(rows)
                    if len(rows) <= 100
                    else f"{len(rows)}+ (showing first 100)"
                ),
                "data": data,
            }
        else:
            conn.commit()
            affected = cursor.rowcount
            conn.close()
            return {
                "status": "success",
                "message": f"Query berhasil dieksekusi. {affected} baris terpengaruh.",
            }
    except Exception as e:
        return {"status": "error", "message": f"SQL error: {str(e)}"}
