"""Data Analysis Tools for ALFA Agent."""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def analyze_dataset_csv_json(
    file_path: str, 
    chart_type: str = "bar", 
    x_column: str = "", 
    y_column: str = "", 
    title: str = "Data Analysis"
) -> Dict[str, Any]:
    """Analyze CSV or JSON dataset and generate insights with charts."""
    try:
        import pandas as pd
        import os
        
        # Load data
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        elif file_path.endswith('.json'):
            df = pd.read_json(file_path)
        else:
            return {"status": "error", "message": "Unsupported file format"}
        
        # Basic statistics
        stats = {
            "rows": len(df),
            "columns": len(df.columns),
            "column_names": list(df.columns),
            "null_counts": df.isnull().sum().to_dict(),
            "numeric_summary": {}
        }
        
        # Generate summary for numeric columns
        numeric_cols = df.select_dtypes(include=['number']).columns
        for col in numeric_cols:
            stats["numeric_summary"][col] = {
                "mean": float(df[col].mean()),
                "median": float(df[col].median()),
                "std": float(df[col].std()),
                "min": float(df[col].min()),
                "max": float(df[col].max())
            }
        
        # Generate chart if columns specified
        chart_path = None
        if x_column and y_column and x_column in df.columns and y_column in df.columns:
            import matplotlib.pyplot as plt
            
            output_dir = os.path.join(os.path.dirname(__file__), "..", "storage", "charts")
            os.makedirs(output_dir, exist_ok=True)
            chart_path = os.path.join(output_dir, f"{title.replace(' ', '_')}.png")
            
            plt.figure(figsize=(10, 6))
            
            if chart_type == "bar":
                plt.bar(df[x_column].astype(str), df[y_column])
            elif chart_type == "line":
                plt.plot(df[x_column], df[y_column])
            elif chart_type == "scatter":
                plt.scatter(df[x_column], df[y_column])
            
            plt.xlabel(x_column)
            plt.ylabel(y_column)
            plt.title(title)
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig(chart_path)
            plt.close()
        
        return {
            "status": "success",
            "message": f"Analyzed {len(df)} rows, {len(df.columns)} columns",
            "statistics": stats,
            "chart_path": chart_path
        }
    except Exception as e:
        logger.error(f"Data analysis error: {e}")
        return {"status": "error", "error": str(e)}
