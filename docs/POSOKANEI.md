# PosoKanei price lookups

Stock and shopping-list prices come from **PosoKanei** ("Πόσο κάνει"),
the Greek supermarket price observatory at <https://posokanei.gov.gr>.
Price data © its publishers; this app only reads it, shows its source on
the stock pages, and stores a daily snapshot per tracked product so it can
compute its own price advice.

> **Unofficial API.** There is no published contract for these endpoints.
> They may change, rate-limit or block third-party clients at any time.
> The app treats every failure as "prices unavailable" and keeps working.

## Endpoints used (`app/integrations/posokanei.py`)

| Function | Request | Notes |
|---|---|---|
| `search(query, page=1, page_size=20)` | `POST /products/search` body `{"query": q, "page": p, "page_size": n}` | add-product search box |
| `by_barcode(barcode)` | `GET /products/barcode/{barcode}` | 404 → `None`; non-digit codes never sent |
| `get(product_id, include_history=True)` | `GET /products/{id}?countries=GR&include_tax=true&include_history=true` | daily refresh; `history` (if present) backfills snapshots; 404 or an invalid id → `PosokaneiNotFound` |

Base URL `https://api.posokanei.gov.gr` (`POSOKANEI_BASE_URL`).

All responses map to `ProductSummary(id, name, brand, barcode, unit,
unit_quantity, image_url, retailer_prices[RetailerPrice(retailer,
display_name, price, unit_price, is_discount, discount_pct, last_updated)],
price_stats(min, max, avg), history)`. Money is `Decimal`.

## Politeness and failure handling

- User-Agent `expenses-app/1.0 (+APP_BASE_URL)`, 15 s timeout.
- One request at a time per process, ≥ 250 ms apart (≤ 4 req/s; the daily
  refresh relies on this).
- Successful responses are cached in-process for 5 minutes; failures are not.
- Timeouts, connection errors, non-200 responses, non-JSON bodies and
  unexpected shapes all raise `PosokaneiUnavailable`. Callers degrade:
  - `/stock` and `/stock/shopping` render from stored snapshots and say
    "prices unavailable" where there are none;
  - search / barcode lookups show "prices unavailable — add it manually";
  - the API proxies return `503`;
  - the scheduler's price-refresh stage logs and moves on.
- `POSOKANEI_ENABLED=false` turns every lookup into `PosokaneiUnavailable`
  without any network traffic.

## Daily refresh and alerts (`app/scheduler.py`)

Two stages run in the daily job (after the budget warnings):

- `_refresh_tracked_prices` — for every non-archived product with a
  `posokanei_id` whose stock item has `track_price`, call `get()` and store
  today's `price_snapshots` (skipped when a snapshot for today already
  exists), never-priced products first, then the stalest. A per-product
  miss (`PosokaneiNotFound`: 404 or invalid id) is skipped; after 3
  consecutive outage errors (timeouts, transport errors, 5xx, 403) it logs
  and stops for the day; the rest of the job still runs.
- `_notify_stock_and_prices` — `stock_low` (dedupe
  `stock_low:{item.id}:{today}`) when an item crossed down to its minimum
  since the start of yesterday; `price_drop` (dedupe
  `price_drop:{product.id}:{today}`) when today's cheapest price is ≤ 90 % of
  the 30-day median of daily minimums (needs ≥ 7 days of history).

## Price advice (estimates)

`app/services/stock.py` derives, per product, from the stored snapshots:
`buy_now` (within 2 % of the 90-day low, or on offer ≥ 10 % under the 30-day
median), `wait` (≥ 8 % above the 30-day median), else `neutral`; `unknown`
with fewer than 7 distinct snapshot days. A least-squares trend over the last
30 days gives "prices rising N %/month". Run-out prediction uses the last 60
days of "use" movements (≥ 2 needed, ≥ 7 days observed). All of this is
shown as an estimate.

## Observed behaviour (2026-10-01)

From the development machine (Greek IP), every request — `POST
/products/search` with `{"query": "γάλα"}`, `GET
/products/barcode/5201054017906`, `GET /`, `/docs`, `/openapi.json`, and
even the public site `https://posokanei.gov.gr/` with a browser User-Agent —
returned **HTTP 403** with a 134-byte HTML "403 Forbidden" page (behind a
WAF / bot filter). The live field shapes could therefore not be verified.

Consequences:

- The mapping reads exactly the specified keys; only the search container
  varies (a bare list, `results` or `items`). `price_stats` is derived from
  the retailer prices when absent. `is_discount` is parsed strictly
  (booleans, 0/1, "true"/"false"/"1"/"0"; anything else is false).
- Product ids must match `^[A-Za-z0-9._-]{1,64}$` (not `.`/`..`); they are
  validated when a product is added (400) and again in the client, which
  also URL-quotes them.
- A 403 is just another `PosokaneiUnavailable`, so in the observed state
  the feature runs in degraded mode: manual products, manual barcodes, no
  prices. Re-check the shapes once the endpoint answers and adjust
  `_map_product` if needed (tests in `tests/test_posokanei.py` pin the
  expected mapping).
