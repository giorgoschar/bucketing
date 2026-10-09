# Open Food Facts barcode lookup

When a scanned barcode is not in the household's pantry and PosoKanei has no
product for it (not found, unavailable or disabled), the app asks
**Open Food Facts** (<https://world.openfoodfacts.org>) for the product's
name, brand and size. Barcode lookups only: no name search, no prices, no
images.

Lookup order: own pantry, PosoKanei, Open Food Facts, add by hand.

## Endpoint used (`app/integrations/openfoodfacts.py`)

`GET {OPENFOODFACTS_BASE_URL}/api/v2/product/{barcode}.json?fields=code,product_name,product_name_el,generic_name_el,brands,quantity,product_quantity,product_quantity_unit`

- Name: `product_name_el`, else `product_name`, else `generic_name_el` (none: treated as not found).
- Brand: the first of the comma-separated `brands`.
- Size: `product_quantity` + `product_quantity_unit` when both are numeric/known, otherwise the `quantity` text ("500 g", "1,5 l", "6 x 330 ml" gives 330 ml). Units are normalised to g, kg, ml or L; anything else gives no size.
- The returned `code` is never trusted: the barcode asked for is used.

## Politeness

- Honest `User-Agent: Tameio/1.0 (+<APP_BASE_URL>)`, never a browser string. `Accept-Encoding: identity`.
- Only 6 to 14 ASCII digits are ever sent.
- Spacing: 700 ms times the worker count between requests per process, and 1 request in flight per process when there is more than one worker (2 for a single worker). `WEB_CONCURRENCY` (default 2, the value `entrypoint.sh` starts uvicorn with) gives the worker count. The combined rate is therefore at most about 86 product reads a minute, under their limit of 100. **This is a per-process approximation**: each worker keeps its own slot clock, caches and breaker, with no shared store.
- A caller whose slot is more than 2 s away, or who finds the in-flight cap full, fails fast (treated as unavailable) instead of queueing. That is local congestion, not an outage.
- Per user, `GET /api/v1/products/barcode/{code}` allows 30 lookups a minute (429 with "Too many barcode lookups. Try again in a minute."), before any upstream call.
- 5 s deadline for the whole exchange (connect, headers and body, wall clock); at the deadline the connection is closed. No redirects.
- Response body read raw and capped at 64 kB; any `Content-Encoding` other than identity is refused (so nothing is inflated); JSON nested deeper than 32 is refused before parsing; any parsing surprise is "unavailable".
- Cache per barcode for 24 h, hits and "not found" alike, at most 2,000 entries (LRU).
- Failures are cached too: after an unavailable answer the barcode is not asked again for 60 s.
- Circuit breaker: 3 consecutive real outages (transport error, timeout, deadline, 5xx, 429) stop all lookups for 60 s. Then one probe is allowed: success closes the breaker, failure reopens it for another 60 s. Redirects, other 4xx and malformed records only enter the per-barcode failure cache.

## Licence and credit

The database is under the Open Database Licence (ODbL) and its contents under
the Database Contents Licence. Attribution is required: the barcode sheet
shows "Product data: Open Food Facts", linked to <https://world.openfoodfacts.org>,
on every result that came from them. Product images are not used.

## Settings

| Variable | Default |
|---|---|
| `OPENFOODFACTS_ENABLED` | `true` (`false` stops all outbound traffic) |
| `OPENFOODFACTS_BASE_URL` | `https://world.openfoodfacts.org` |

## Failure behaviour

A timeout, transport error, any non-200 other than 404, a non-JSON body, an
unexpected shape or the switch being off raises `OpenFoodFactsUnavailable`.
`GET /api/v1/products/barcode/{code}` then answers as if Open Food Facts had
not been asked: 503 when PosoKanei was unavailable too, otherwise 404.
`status: 0` or HTTP 404 from them is "not found" (404). In every case the
body carries `in_pantry`, and the user can still add the product by hand.

An Open Food Facts result is a 200 with `source: "openfoodfacts"`, `id`
`off:<barcode>` (not a PosoKanei id), empty `retailer_prices`, all-null
`price_stats`, empty `history` and no image.
