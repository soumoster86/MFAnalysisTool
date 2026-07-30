# Reports

Three formats — PDF, Excel, PowerPoint — rendered from one shared model.

## Architecture

```
PortfolioAnalysis
   └─ report_data.build_report_data()  ->  ReportData
                                             ├─ pdf_report.py    (reportlab)
                                             ├─ excel_report.py  (openpyxl)
                                             └─ pptx_report.py   (python-pptx)
```

`ReportData` holds KPIs, holdings, allocations, risk, overlap, notes, AI review
and the provenance disclosure. Every renderer reads it, so the three files
agree on content, ordering and rounding. Before this, each renderer picked its
own columns and the same portfolio read differently depending on which button
was pressed.

Values are carried as **raw numbers and display strings**. Excel needs the
number so its cell formats, totals and charts work; the PDF and deck want the
formatted text. Formatting the same figure twice in two places is how a report
ends up quoting two different values for one holding.

## Charts

Each format uses its **native** chart facility — no kaleido, no image
rendering, no new dependency:

| Format | Charts |
|--------|--------|
| PDF | `reportlab.graphics` — vector donuts and horizontal bars |
| Excel | `openpyxl` pie and bar charts — live and editable in Excel |
| PowerPoint | `python-pptx` doughnut charts — editable in PowerPoint |

## PDF

A4, with a running header band, accent rule, footer disclaimer and page
numbers on every page. Sections: KPI cards, risk & return, allocation donuts,
look-through bar chart, fund overlap, a paginated holdings table with gains and
losses coloured, the AI review, analysis notes, and a data-source audit trail.

**Fonts.** reportlab's built-in Helvetica has no rupee glyph. It still reports a
width for U+20B9, so nothing errors — the character just draws as a hollow box
and every currency figure looks broken. `fonts.py` searches for a Unicode TTF
(matplotlib's bundled DejaVu, then the usual Linux/Windows/macOS paths) and
registers it. If none is found it writes `Rs` instead: an honest ASCII prefix
beats a box.

## Excel

Four sheets — **Summary**, **Holdings**, **Allocation**, **Data sources**.

Numbers are written as numbers with cell formats applied, never as
pre-rendered strings, so the recipient can sort, total and chart them — the
only reason to want a spreadsheet rather than a PDF. The Holdings sheet has
frozen panes, an auto-filter, banded rows and a live `=SUM()` total row.
Fabricated data sources are flagged in red on the audit sheet.

## PowerPoint

16:9, built from blank layouts rather than the stock title/bullet placeholders,
which produce a generic deck. Title slide, KPI cards, risk table, one chart
slide per allocation (doughnut plus a readable weight table), look-through
holdings, overlap and the AI review.

## Data disclosure

A generated file is read away from the app, so an on-screen banner protects
nobody. When any figure derives from a synthetic NAV path or sample holdings,
the warning is rendered **inside** all three files — a panel in the PDF, a
highlighted row in Excel, a panel on the PPTX KPI slide — and the per-fund
source list is included as an audit trail.

## Two data bugs this work surfaced

Building the report on real data exposed defects that predated it:

- **Sector and market-cap weights were wildly inflated** — one sector showed
  537%, a market-cap bucket 2370%. The analyzer decided fraction-vs-percent
  scale *per row*, so a legitimate 0.8% holding was read as a fraction and
  multiplied by 100. It now judges the scale once per fund from the column
  total. The same defect was in `change_detector`, where it would have invented
  sector-shift alerts.
- **`Financial` and `Financials`** arrived as separate buckets from an
  inconsistent provider, showing one exposure twice. Exact singular/plural
  variants are now merged; genuinely different buckets such as `Consumer` and
  `Consumer Discretionary` stay apart.
