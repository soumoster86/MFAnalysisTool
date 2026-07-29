# MFCentral CAS Upload

Import your **MFCentral Consolidated Account Summary** PDF into the portfolio analyzer.

## Supported file

- MFCentral **CAS Summary** PDF (`MFCentralCASSummary_v2.x`, e.g. `cas_summary_report_YYYY_MM_DD_HHMMSS.pdf`)
- Sections:
  - **SoA Holdings** — folio, scheme, invested, units, NAV, market value
  - **Demat Holdings** — client id, scheme, units, market value (invested often `0.00`)

Password-protected detailed CAS e-mail statements are **not** supported in Phase 1 (upload the Summary PDF from MFCentral).

## UI

Streamlit → **Upload CAS**

1. Choose SoA / Demat inclusion  
2. Upload PDF → **Parse & map holdings**  
3. Review AMFI matches (edit codes if needed)  
4. **Apply to portfolio**  
5. Open **Dashboard** / **Portfolio Analyzer**

## API

```http
POST /api/v1/portfolio/import-cas
Content-Type: multipart/form-data

file: <cas.pdf>
include_soa: true
include_demat: true
merge_duplicates: true
min_match_score: 0.45
```

Response includes masked PAN, holdings, match confidence, and `portfolio_holdings` ready for `/api/v1/portfolio/analyze`.

## Mapping logic

1. Parse tables with `pdfplumber` (`services/data/cas_parser.py`)  
2. Drop zero-balance lines  
3. Fuzzy-match scheme names to AMFI via search + token similarity (`services/portfolio/import_service.py`)  
4. Prefer Direct Growth when CAS name implies Direct  
5. Optionally merge same AMFI code across SoA + Demat  
6. Demat with `invested=0` uses market value as invested weight for analytics

## Privacy

- PAN is **masked** (`ABCXXXXZ`) in UI/API responses  
- PDF is **not** stored on disk by default (in-memory parse)  
- Session holds only scheme-level portfolio rows  

## CSV fallback

On the Upload CAS page you can also paste CSV:

```csv
scheme_name,units,invested_amount,amfi_code
Parag Parikh Flexi Cap Fund - Direct Plan - Growth,100,50000,
```
