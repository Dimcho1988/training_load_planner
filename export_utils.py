"""Export utilities."""

from __future__ import annotations

from io import BytesIO
from typing import Dict

import pandas as pd


def dataframes_to_excel_bytes(sheets: Dict[str, pd.DataFrame]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            safe_name = sheet_name[:31]
            (df if df is not None else pd.DataFrame()).to_excel(writer, sheet_name=safe_name, index=False)
            worksheet = writer.sheets[safe_name]
            for column_cells in worksheet.columns:
                max_len = 10
                col_letter = column_cells[0].column_letter
                for cell in column_cells:
                    try:
                        max_len = max(max_len, len(str(cell.value)))
                    except Exception:
                        pass
                worksheet.column_dimensions[col_letter].width = min(max_len + 2, 45)
    return output.getvalue()
