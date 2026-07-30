"""Portfolio report generation — PDF, Excel and PowerPoint.

All three formats render from one `ReportData` model so they agree on content,
ordering and rounding. See `report_data.py`; the per-format styling lives in
`pdf_report.py`, `excel_report.py` and `pptx_report.py`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from config.settings import PROJECT_ROOT
from services.reports.excel_report import excel_bytes as _excel_bytes
from services.reports.pdf_report import pdf_bytes as _pdf_bytes
from services.reports.pptx_report import pptx_bytes as _pptx_bytes
from services.reports.report_data import ReportData, build_report_data
from utils.logging_config import get_logger

logger = get_logger(__name__)

__all__ = ["ReportService", "build_report_data", "ReportData"]


def _stamp(extension: str, slug: str = "portfolio_report") -> str:
    return f"{slug}_{datetime.now():%Y%m%d_%H%M%S}.{extension}"


class ReportService:
    """Generate downloadable portfolio reports."""

    def __init__(self, output_dir: Optional[Path] = None) -> None:
        self.output_dir = Path(output_dir or (PROJECT_ROOT / "data" / "reports"))
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ bytes
    # Bytes are the primary API: Streamlit can hand them straight to a download
    # button, so a report needs one click rather than generate-then-download.
    def pdf_bytes(self, data: ReportData) -> bytes:
        return _pdf_bytes(data)

    def excel_bytes(self, data: ReportData) -> bytes:
        return _excel_bytes(data)

    def pptx_bytes(self, data: ReportData) -> bytes:
        return _pptx_bytes(data)

    def render(self, data: ReportData, fmt: str) -> tuple[bytes, str, str]:
        """(bytes, filename, mime) for 'pdf' | 'excel' | 'pptx'."""
        key = fmt.lower().strip()
        if key == "pdf":
            return self.pdf_bytes(data), _stamp("pdf"), "application/pdf"
        if key in {"excel", "xlsx"}:
            return (
                self.excel_bytes(data),
                _stamp("xlsx"),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        if key in {"pptx", "powerpoint"}:
            return (
                self.pptx_bytes(data),
                _stamp("pptx"),
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
        raise ValueError(f"Unknown report format: {fmt!r}")

    # ------------------------------------------------------------------ files
    def save(self, data: ReportData, fmt: str, filename: Optional[str] = None) -> Path:
        payload, default_name, _ = self.render(data, fmt)
        path = self.output_dir / (filename or default_name)
        path.write_bytes(payload)
        logger.info("{} report written to {}", fmt.upper(), path)
        return path

    def generate_pdf(self, data: ReportData, filename: Optional[str] = None) -> Path:
        return self.save(data, "pdf", filename)

    def generate_excel(self, data: ReportData, filename: Optional[str] = None) -> Path:
        return self.save(data, "excel", filename)

    def generate_pptx(self, data: ReportData, filename: Optional[str] = None) -> Path:
        return self.save(data, "pptx", filename)

    # ------------------------------------------------------------- convenience
    def from_analysis(
        self,
        analysis: Any,
        *,
        title: str = "Portfolio Analysis Report",
        subtitle: str = "",
        ai_summary: str = "",
        max_holdings: int = 40,
    ) -> ReportData:
        return build_report_data(
            analysis,
            title=title,
            subtitle=subtitle,
            ai_summary=ai_summary,
            max_holdings=max_holdings,
        )

    def holdings_csv(self, data: ReportData) -> bytes:
        """Raw holdings as CSV, for spreadsheets that are not Excel."""
        if not data.holdings_display:
            return b""
        return pd.DataFrame(data.holdings_display).to_csv(index=False).encode("utf-8")
