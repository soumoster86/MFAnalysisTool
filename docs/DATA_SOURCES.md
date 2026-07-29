# Data Sources — Historical NAV & Holdings

## 1. Historical NAV

### Primary: mfapi.in

```
GET https://api.mfapi.in/mf/{amfi_scheme_code}
GET https://api.mfapi.in/mf/{amfi_scheme_code}/latest
GET https://api.mfapi.in/mf/{amfi_scheme_code}?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD
```

- Free, no API key
- Full daily NAV history for open-ended schemes
- Client: `services/data/mfapi_client.py`
- Cache: `data/cache/nav_history/nav_{code}.csv`

### Fallback: TigZig AMFI API

```
GET https://api.tigzig.com/mf/v1/nav?scheme={amfi_code}
GET https://api.tigzig.com/mf/v1/nav?scheme={amfi_code}&since=2020-01-01
```

- Free, no API key, 300 req/min
- Cite: https://www.tigzig.com/apis/mf-nav

### Fallback chain in `FundService.get_nav_history`

1. Memory cache  
2. Fresh disk cache / mfapi  
3. TigZig  
4. SQLite `fund_navs`  
5. Synthetic path (if `ALLOW_SYNTHETIC_NAV_FALLBACK=true`)

## 2. Portfolio holdings

### Groww (unofficial web API)

```
# Search
GET https://groww.in/v1/api/search/v3/query/global/st_p_query?query=...&entity_type=scheme

# Detail + holdings (structured)
GET https://groww.in/v1/api/data/mf/web/v2/scheme/search/{search_id}
```

Fields used:

| Groww field | Our field |
|-------------|-----------|
| `company_name` | `security_name` |
| `corpus_per` | `weight_pct` |
| `sector_name` | `sector` |
| `nature_name` / instrument | `asset_type` |
| `market_cap` | `market_cap` (often null → Unclassified) |
| `expense_ratio`, `aum`, `fund_manager` | fund meta enrichment |

Client: `services/data/holdings_client.py`  
Cache: `data/cache/holdings/`

### Fallback

Deterministic sample holdings (`services/data/sample_data.py`) if Groww is blocked or scheme cannot be resolved.

## 3. NSE and BSE market data

Client: `services/data/market_client.py` · Cache: `data/cache/market/`

Two exchanges, because neither serves everything:

| Source | Endpoint | Used for |
|--------|----------|----------|
| NSE | `/api/allIndices` | Live board of ~139 indices (Dashboard strip, benchmark levels) |
| BSE | `MktRGainerLoserData` | ~2,700-row equity snapshot; doubles as the name → scrip code index |
| BSE | `getScripHeaderData` | Per-scrip quote when the snapshot lacks a price |

NSE requires the cookies its home page sets before any API call will succeed.
Its per-symbol `quote-equity` endpoint returns **403** to programmatic clients
regardless of priming, so stock quotes come from BSE instead.

Fund holdings are matched to listed companies by normalising the company name
(dropping `Ltd`, `Limited`, punctuation). An unmatched holding is left with no
price rather than being given a near-match's quote.

Every method degrades to `None` or an empty frame instead of raising, and
serves the last cached board when an exchange blocks — market data enriches the
UI and must never take a page down.

## 4. Dividend / IDCW history

Module: `services/data/dividends.py`

| Source | `source` value | Trust |
|--------|----------------|-------|
| Provider `dividend` field | `provider` | Reported, authoritative |
| NAV divergence vs the Growth sibling | `derived` | **Estimated** |

Groww's search only surfaces Direct Growth plans, and Growth plans never
distribute, so the provider field is empty in practice. The derivation uses the
fact that an IDCW plan and its Growth sibling hold the same portfolio: when the
IDCW NAV falls materially further on the same day, the gap is a distribution.

Siblings are matched on the fund's identity tokens — the name minus plan
wording — because AMFI names carry irregular spacing and inconsistent plan
suffixes that defeat a substring match. Direct/Regular status must also match,
since that pair differs by TER and would drift apart for reasons that are not
distributions.

Derived figures are estimates and are labelled as such in the UI. Never present
one as a reported payout.

## 5. Configuration

See `.env.example`:

- `MFAPI_BASE_URL`, `TIGZIG_NAV_URL`
- `HOLDINGS_CACHE_HOURS`, `NAV_CACHE_HOURS`
- `ALLOW_SYNTHETIC_NAV_FALLBACK`, `ALLOW_SAMPLE_HOLDINGS_FALLBACK`
- `PERSIST_NAV_TO_DB`, `PERSIST_HOLDINGS_TO_DB`

## 6. Caveats

- Groww, NSE and BSE APIs are all **unofficial** and may change or block without
  notice; every caller treats them as best-effort.
- AMFI scheme codes after AMC mergers can split history; prefer the live Direct Growth code from AMFI search.
- Market-cap labels on holdings are frequently missing from the source payload.
- Not affiliated with AMFI, mfapi.in, TigZig, Groww, NSE, or BSE.
