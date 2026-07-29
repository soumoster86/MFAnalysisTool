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

## 3. Configuration

See `.env.example`:

- `MFAPI_BASE_URL`, `TIGZIG_NAV_URL`
- `HOLDINGS_CACHE_HOURS`, `NAV_CACHE_HOURS`
- `ALLOW_SYNTHETIC_NAV_FALLBACK`, `ALLOW_SAMPLE_HOLDINGS_FALLBACK`
- `PERSIST_NAV_TO_DB`, `PERSIST_HOLDINGS_TO_DB`

## 4. Caveats

- Groww APIs are **unofficial** and may change without notice; treat as best-effort.
- AMFI scheme codes after AMC mergers can split history; prefer the live Direct Growth code from AMFI search.
- Market-cap labels on holdings are frequently missing from the source payload.
- Not affiliated with AMFI, mfapi.in, TigZig, or Groww.
