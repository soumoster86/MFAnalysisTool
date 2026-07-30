"""Polished PDF rendering with reportlab.

Charts are drawn with `reportlab.graphics` rather than embedded as images:
kaleido is not installed, and native vector charts stay sharp at any zoom and
add no dependency.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Rect
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from services.reports import branding as B
from services.reports.fonts import money_text, register_unicode_font
from services.reports.report_data import HOLDING_COLUMNS, ReportData

PAGE_W, PAGE_H = A4
MARGIN = 16 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


def _c(hex_string: str) -> colors.Color:
    return colors.HexColor(f"#{hex_string}")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    # Helvetica has no rupee glyph and silently draws a box in its place, so
    # every money figure would look broken. Resolve a Unicode face first.
    font, font_bold, _ = register_unicode_font()
    for style in base.byName.values():
        try:
            style.fontName = font_bold if "Bold" in str(style.fontName) else font
        except Exception:
            pass
    return {
        "title": ParagraphStyle(
            "RTitle", parent=base["Title"], fontName=font_bold, fontSize=22, leading=26,
            textColor=_c(B.INK), alignment=TA_LEFT, spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "RSub", parent=base["Normal"], fontName=font, fontSize=9.5, leading=13,
            textColor=_c(B.MUTED),
        ),
        "h2": ParagraphStyle(
            "RH2", parent=base["Heading2"], fontName=font_bold, fontSize=13, leading=16,
            textColor=_c(B.INK), spaceBefore=14, spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "RBody", parent=base["BodyText"], fontName=font, fontSize=9.5, leading=13.5,
            textColor=_c(B.INK),
        ),
        "muted": ParagraphStyle(
            "RMuted", parent=base["BodyText"], fontName=font, fontSize=8.5, leading=11.5,
            textColor=_c(B.MUTED),
        ),
        "warn": ParagraphStyle(
            "RWarn", parent=base["BodyText"], fontName=font, fontSize=9, leading=12.5,
            textColor=_c(B.WARNING_INK),
        ),
        "kpi_label": ParagraphStyle(
            "KLabel", parent=base["Normal"], fontName=font, fontSize=7.5, leading=9,
            textColor=_c(B.MUTED), alignment=TA_CENTER,
        ),
        "cell": ParagraphStyle(
            "RCell", parent=base["Normal"], fontName=font, fontSize=7.6, leading=9.5,
            textColor=_c(B.INK),
        ),
        "cell_head": ParagraphStyle(
            "RCellH", parent=base["Normal"], fontName=font_bold, fontSize=7.6, leading=9.5,
            textColor=colors.white,
        ),
    }


class _Doc(BaseDocTemplate):
    """Adds the running header band, footer rule and page numbers."""

    def __init__(self, target: Any, data: ReportData, **kw: Any) -> None:
        super().__init__(target, pagesize=A4, **kw)
        self.report = data
        frame = Frame(
            MARGIN, MARGIN + 10 * mm, CONTENT_W,
            PAGE_H - MARGIN - 26 * mm - 10 * mm, id="body",
        )
        self.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=self._decorate)])

    def _decorate(self, canvas: Any, _doc: Any) -> None:
        canvas.saveState()
        # Header band
        canvas.setFillColor(_c(B.INK))
        canvas.rect(0, PAGE_H - 18 * mm, PAGE_W, 18 * mm, stroke=0, fill=1)
        canvas.setFillColor(_c(B.ACCENT))
        canvas.rect(0, PAGE_H - 19.2 * mm, PAGE_W, 1.2 * mm, stroke=0, fill=1)

        canvas.setFillColor(colors.white)
        canvas.setFont(register_unicode_font()[1], 10)
        canvas.drawString(MARGIN, PAGE_H - 11.5 * mm, "MF Analysis Tool")
        canvas.setFont(register_unicode_font()[0], 8)
        canvas.setFillColor(_c(B.RULE))
        canvas.drawRightString(
            PAGE_W - MARGIN, PAGE_H - 11.5 * mm,
            self.report.generated_at.strftime("%d %b %Y, %H:%M"),
        )

        # Footer
        canvas.setStrokeColor(_c(B.RULE))
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, 16 * mm, PAGE_W - MARGIN, 16 * mm)
        canvas.setFont(register_unicode_font()[0], 6.8)
        canvas.setFillColor(_c(B.MUTED))
        canvas.drawString(MARGIN, 11.5 * mm, B.FOOTER_NOTE[:110])
        canvas.setFont(register_unicode_font()[1], 8)
        canvas.setFillColor(_c(B.INK))
        canvas.drawRightString(PAGE_W - MARGIN, 11.5 * mm, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()


def _kpi_cards(data: ReportData, st: dict[str, ParagraphStyle]) -> Table:
    """KPI strip: three across, two rows, each a bordered card."""
    cards = []
    for kpi in data.kpis[:6]:
        cards.append(
            Table(
                [
                    [Paragraph(kpi.label.upper(), st["kpi_label"])],
                    [
                        Paragraph(
                            f'<font size="14" color="#{B.tone_colour(kpi.tone)}">'
                            f"<b>{kpi.value}</b></font>",
                            ParagraphStyle(
                                "v", fontName=register_unicode_font()[1],
                                alignment=TA_CENTER, leading=17,
                            ),
                        )
                    ],
                    [Paragraph(kpi.caption or "&nbsp;", st["kpi_label"])],
                ],
                colWidths=[CONTENT_W / 3 - 4],
                style=TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), _c(B.BAND)),
                        ("BOX", (0, 0), (-1, -1), 0.6, _c(B.RULE)),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ]
                ),
            )
        )
    while len(cards) % 3:
        cards.append("")

    grid = [cards[i : i + 3] for i in range(0, len(cards), 3)]
    return Table(
        grid,
        colWidths=[CONTENT_W / 3] * 3,
        style=TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        ),
    )


def _donut(mapping: dict[str, float], width: float = 240, height: float = 130) -> Drawing:
    """Allocation donut with a legend."""
    drawing = Drawing(width, height)
    pie = Pie()
    pie.x, pie.y = 6, 8
    pie.width = pie.height = height - 16
    pie.data = [max(float(v), 0.01) for v in mapping.values()]
    pie.labels = None
    pie.innerRadiusFraction = 0.55
    pie.slices.strokeWidth = 0.6
    pie.slices.strokeColor = colors.white
    for i in range(len(pie.data)):
        pie.slices[i].fillColor = _c(B.series_colour(i))
    drawing.add(pie)

    legend = Legend()
    legend.x = height + 4
    legend.y = height - 14
    legend.fontName = "Helvetica"
    legend.fontSize = 6.8
    legend.dx = legend.dy = 5
    legend.dxTextSpace = 4
    legend.deltay = 8.5
    legend.columnMaximum = 8
    legend.colorNamePairs = [
        (_c(B.series_colour(i)), f"{k[:26]} {v:.1f}%")
        for i, (k, v) in enumerate(mapping.items())
    ]
    drawing.add(legend)
    return drawing


def _bar_chart(pairs: list[tuple[str, float]], width: float = CONTENT_W, height: float = 150) -> Drawing:
    """Horizontal bars for look-through top holdings."""
    drawing = Drawing(width, height)
    chart = HorizontalBarChart()
    chart.x, chart.y = 118, 12
    chart.width = width - 140
    chart.height = height - 24
    chart.data = [[round(v, 2) for _, v in pairs]]
    chart.categoryAxis.categoryNames = [n[:30] for n, _ in pairs]
    chart.categoryAxis.labels.fontName = "Helvetica"
    chart.categoryAxis.labels.fontSize = 6.6
    chart.categoryAxis.labels.dx = -3
    chart.categoryAxis.strokeColor = _c(B.RULE)
    chart.valueAxis.valueMin = 0
    chart.valueAxis.labels.fontName = "Helvetica"
    chart.valueAxis.labels.fontSize = 6.6
    chart.valueAxis.strokeColor = _c(B.RULE)
    chart.valueAxis.gridStrokeColor = _c(B.RULE)
    chart.valueAxis.gridStrokeWidth = 0.3
    chart.valueAxis.visibleGrid = 1
    chart.bars[0].fillColor = _c(B.ACCENT)
    chart.bars[0].strokeColor = None
    chart.barWidth = 3
    chart.groupSpacing = 4
    drawing.add(chart)
    return drawing


def _kv_table(rows: list[tuple[str, str]], st: dict[str, ParagraphStyle]) -> Table:
    data = [
        [Paragraph(money_text(k), st["cell"]), Paragraph(money_text(v), st["cell"])]
        for k, v in rows
    ]
    return Table(
        data,
        colWidths=[CONTENT_W * 0.62, CONTENT_W * 0.38],
        style=TableStyle(
            [
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, _c(B.BAND)]),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, _c(B.RULE)),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        ),
    )


def _holdings_table(data: ReportData, st: dict[str, ParagraphStyle]) -> Table:
    headers = [label for _, label, _ in HOLDING_COLUMNS]
    body = [[Paragraph(f"<b>{h}</b>", st["cell_head"]) for h in headers]]
    for row in data.holdings_display:
        body.append(
            [Paragraph(money_text(str(row.get(h, "—"))), st["cell"]) for h in headers]
        )

    widths = [
        CONTENT_W * w for w in (0.28, 0.12, 0.10, 0.12, 0.13, 0.12, 0.08, 0.05)
    ]
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), _c(B.INK)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _c(B.BAND)]),
        ("GRID", (0, 0), (-1, -1), 0.25, _c(B.RULE)),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    # Colour gains and losses so the eye finds the losers immediately.
    gain_col = headers.index("Gain / loss")
    ret_col = headers.index("Return")
    for i, row in enumerate(data.holdings, start=1):
        gain = row.get("gain")
        if gain is None:
            continue
        tone = _c(B.POSITIVE) if gain >= 0 else _c(B.NEGATIVE)
        style.append(("TEXTCOLOR", (gain_col, i), (ret_col, i), tone))

    return Table(body, colWidths=widths, repeatRows=1, style=TableStyle(style))


def _warning_panel(text: str, st: dict[str, ParagraphStyle]) -> Table:
    return Table(
        [[Paragraph(f"<b>Data quality notice.</b> {text}", st["warn"])]],
        colWidths=[CONTENT_W],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _c(B.WARNING_FILL)),
                ("BOX", (0, 0), (-1, -1), 0.6, _c(B.WARNING_INK)),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        ),
    )


def _rule(st: dict[str, ParagraphStyle]) -> Drawing:
    d = Drawing(CONTENT_W, 3)
    d.add(Rect(0, 1, CONTENT_W, 0.8, fillColor=_c(B.ACCENT), strokeColor=None))
    return d


def build_pdf(data: ReportData, target: Any) -> Any:
    """Render `data` to `target` (path or file-like)."""
    st = _styles()
    doc = _Doc(target, data, leftMargin=MARGIN, rightMargin=MARGIN)
    story: list[Any] = [
        Paragraph(data.title, st["title"]),
        Paragraph(data.subtitle, st["subtitle"]),
        Spacer(1, 4),
        _rule(st),
        Spacer(1, 10),
    ]

    if data.has_warning:
        story += [_warning_panel(data.data_warning, st), Spacer(1, 10)]

    story += [Paragraph("Portfolio at a glance", st["h2"]), _kpi_cards(data, st)]

    if data.risk.rows:
        story += [
            Paragraph("Risk &amp; return", st["h2"]),
            _kv_table(data.risk.rows, st),
            Spacer(1, 4),
            Paragraph(data.risk.note, st["muted"]),
        ]

    for name, mapping in data.allocations.items():
        story.append(
            KeepTogether([Paragraph(name, st["h2"]), _donut(mapping, CONTENT_W, 140)])
        )

    if data.top_holdings:
        story.append(
            KeepTogether(
                [
                    Paragraph("Largest look-through holdings", st["h2"]),
                    Paragraph(
                        "Stock weights after looking through every fund — this is "
                        "where concentration actually sits.",
                        st["muted"],
                    ),
                    Spacer(1, 4),
                    _bar_chart(data.top_holdings),
                ]
            )
        )

    if data.overlap_rows:
        story += [
            Paragraph("Fund overlap", st["h2"]),
            _kv_table(data.overlap_rows, st),
        ]

    if data.holdings_display:
        story += [
            PageBreak(),
            Paragraph("Holdings", st["h2"]),
            _holdings_table(data, st),
        ]

    if data.ai_summary:
        story += [
            Paragraph("AI review", st["h2"]),
            Paragraph(data.ai_summary.replace("\n", "<br/>"), st["body"]),
        ]

    if data.notes:
        story += [Paragraph("Analysis notes", st["h2"])]
        for note in data.notes:
            story.append(Paragraph(f"• {note}", st["muted"]))

    if data.source_rows:
        story += [
            Paragraph("Data sources", st["h2"]),
            Paragraph(
                "Where each figure came from. Anything marked synthetic or sample "
                "was generated because a live provider failed.",
                st["muted"],
            ),
            Spacer(1, 4),
            _kv_table(data.source_rows, st),
        ]

    doc.build(story)
    return target


def pdf_bytes(data: ReportData) -> bytes:
    buffer = BytesIO()
    build_pdf(data, buffer)
    return buffer.getvalue()
