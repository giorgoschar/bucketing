# Official Greek supermarket price sources: research

Researched 2026-10-08. Method: public pages, search results and third-party repo READMEs only. Nothing was scraped, no access control was bypassed, and no call was made to a non-public endpoint beyond one plain GET of the public root URL `https://api.posokanei.gov.gr/`, which returned `{"status":"ok"}`.

**Caveat on evidence.** Several official sites (posokanei.gov.gr, data.gov.gr API pages) are JavaScript apps. The fetch tool saw only their shells, so some points rest on press coverage or third-party READMEs. Each is marked **[unverified]**. Check those by hand in a browser before building on them.

## Bottom line

There is **no officially documented, licensed, machine-readable feed** of current Greek supermarket prices. The Ministry's price observatory (PosoKanei, successor of e-Katanalotis) is a consumer web app and mobile app. I found no developer documentation, no bulk download and no stated reuse licence for it.

A JSON API at `api.posokanei.gov.gr` does exist and the web app uses it. Third parties already consume it, but it is **undocumented and unofficial**. I could not find any terms that permit or forbid automated reuse.

The only officially open dataset on data.gov.gr is old and stale, so it is not usable for current prices.

## Ranked recommendation

1. **Ask the Ministry for permission.** Email the Ministry's PosoKanei contact (find the address in the app or site footer) and request one of three things: a documented API with reuse terms, a licensed daily dump, or written confirmation that low-volume personal use of `api.posokanei.gov.gr` is fine. This is the only route that is both fresh and clearly permitted. It could also be filed through data.gov.gr's dataset-request form **[unverified: form not seen]**.
2. **Fallback, accepting the risk: read the PosoKanei API politely.** This only needs a plain HTTP client with no auth. It carries the legal and stability risk listed under Source B. Keep it to one request a day with caching, a descriptive User-Agent, and a kill switch. Do not ship it as a core feature until step 1 has a reply.
3. **Open Food Facts** for barcode to product name, brand and image only. It has no Greek price data worth relying on, but its licence is explicit.
4. **Manual entry** (user types prices, scans a barcode) as the baseline that always works. Design the app so every price source is optional.

**Concrete next step:** send the Ministry the email in option 1 and, in parallel, open posokanei.gov.gr in a browser and read its footer for "Όροι χρήσης" (terms of use) and any "API" or "Ανοιχτά δεδομένα" link. I could not read it from here.

---

## Source A: PosoKanei (formerly e-Katanalotis), the Ministry's price observatory

- **URLs:** `https://posokanei.gov.gr/` (web app). `https://e-katanalotis.gov.gr/` now 302-redirects to `https://posokanei.gov.gr/?from=ekatanalotis`. The Python scrapers mentioned in third-party results also reference an older mobile API at `app.ekatanalotis.gov.gr/api/mobile/v2/`.
- **Operator:** Ministry of Development (per press coverage of the June 2026 launch).
- **Data held** (press: keeptalkinggreece 2026-06-17, thetoc.gr, athens-times FAQ):
  - Roughly 9,000 to 10,000 product codes.
  - Prices per chain for ten chains: Galaxias, Sklavenitis, Halkiadakis, SYNKA, Masoutis, My Market, AB Vassilopoulos, Kritikos, Market In, Lidl.
  - Search by product name or barcode.
  - Price history.
  - Comparison prices from IT, FR, BE, RO, BG, CY and ES.
  - Categories "based on information provided by Circana".
  - Six chains supply data directly (Galaxias, SYNKA, Masoutis, AB Vassilopoulos, Market In, Lidl). The Ministry says four are collected by "automated web scraping" of their e-shops (athens-times FAQ).
- **Format:** HTML, plus native Android and iOS apps. No download or export was documented.
- **Update frequency:** daily. thetoc.gr: «Οι τιμές ενημερώνονται σε καθημερινή βάση» ("Prices are updated on a daily basis").
- **Licence or terms:** I could not retrieve the site's terms. The athens-times FAQ summary does not address reuse, open data or an API. One third-party archive README states «Δεδομένα © οι φορείς του posokanei.gov.gr» ("Data © the operators of posokanei.gov.gr"). That is the archive author's wording, not an official licence. **[terms unverified]**
- **Registration or token:** none for consumers. Press says "without needing to register or provide personal data".
- **Developer contact:** none found.
- **Daily retailer price lists:** I found no public per-retailer price file on any official page. Retailers' direct feeds seem to go to the Ministry privately. The "ημερήσια δελτία τιμών" files from your question are not published as downloads that I could find.
- **Suitability:** (a) name or barcode lookup, yes through the UI only. (b) Daily refresh, no sanctioned way.

## Source B: `api.posokanei.gov.gr`, the web app's backend (unofficial use)

- **URL:** `https://api.posokanei.gov.gr`. A plain GET of the root returns `{"status":"ok"}`.
- **What I know** comes from third-party repos, not official docs:
  - `github.com/spyrosavl/posokanei` (daily archive) uses `/products?countries=all` with `page_size=100`, `/meta/retailers?countries=all` and `/meta/categories`. The products response already embeds per-chain prices. Results are capped at 10,000 per query, so the archiver walks one top-level category at a time. It states no auth is needed. It notes no explicit terms or robots restrictions, and says «Δεδομένα © οι φορείς του posokanei.gov.gr».
  - `github.com/charistas/posokanei-mcp` (MIT): "public, undocumented endpoints used by the PosoKanei web app", no auth, "not affiliated with, endorsed by, or operated by PosoKanei, gov.gr, or any Greek public authority", advises "keep requests modest and cache-friendly", and warns of "potential instability or changes". Its defaults are a 250 ms minimum request interval and a 5 minute cache.
  - I did not open or test these endpoints myself, so the shapes above are as reported.
- **Format:** JSON, with prices per chain and barcode lookup per the MCP README.
- **Update frequency:** daily, matching the site.
- **Licence:** none found. This is not a documented public API.
- **Registration or token:** none reported.
- **Suitability:** (a) technically yes, name and barcode search. (b) Technically yes: 50 products is a few requests a day. Not sanctioned. It could break or be restricted without notice, and it is unclear whether automated use breaches the site's terms. The Ministry's own data comes partly from scraping retailers, so that is an open policy question.
- **Decision for the app:** if used, make it an optional, off-by-default provider. Do not enumerate the catalogue (the archivers do this, and a household app should not). Query only the tracked products, cache for at least 24 hours, and honour any 429/403 by backing off.

## Source C: data.gov.gr (national open data portal) and its API

- **Portal:** `https://data.gov.gr/`. **Terms:** `https://data.gov.gr/pages/terms-of-use` (English: `https://data.gov.gr/en/pages/terms-of-use`). **FAQ:** `https://data.gov.gr/en/pages/faq`.
- **Supermarket dataset:** `https://data.gov.gr/dataset/stoixeia-timwn-trofimwn-apo-soype-market`, "Στοιχεία Τιμών Τροφίμων από σουπερ μάρκετ".
  - Holds about 1,500 food, beverage and industrial products from supermarket chains and municipal and street markets in Athens.
  - Publisher: Ministry of Economy & Development, General Secretariat of Commerce and Consumer Protection.
  - Primary resource link: `http://www.e-prices.gr` (a retired site).
  - Format: ZIP download.
  - Update frequency: "Not scheduled".
  - Time coverage field: 1900 to 2099 (a placeholder).
  - Access rights: "Public - open data". Specific licence not shown.
  - Traffic: 61 visits and 20 downloads in the last 12 months.
  - **Verdict: legacy and stale. No barcodes or current prices evident. Not useful.**
- **Other price datasets** seen in search results: bi-weekly consumer product price surveys from the General Secretariat (reported as published on data.gov.gr and extractable), Thessaloniki and Kilkis supermarket price sampling, fuel prices, and Pricescope (telecom). I did not open them. They are surveys of sampled prices, not barcode-level chain prices. **[unverified]** I found no data.gov.gr dataset carrying the PosoKanei catalogue.
- **Terms, verbatim quotes** (the terms fetch was summarised by the tool, so check the exact wording on the page):
  - Art. 3: users may «επαναχρησιμοποιεί δεδομένα για οποιονδήποτε νόμιμο σκοπό» ("reuse data for any lawful purpose"), including commercial exploitation. API use for automated extraction is permitted. Access requires no account.
  - Art. 3.4: «Όλα τα σύνολα δεδομένων διατίθενται υπό τους τύπους αδειών που προβλέπει ο νόμος» ("All datasets are made available under the licence types provided for by law"). Common ones are CC0 and CC BY 4.0.
  - Art. 4.4: «γενικός περιορισμός συχνότητας κλήσεων 2.000 ανά λεπτό ανά διεύθυνση IP» ("general call-rate limit of 2,000 per minute per IP address").
  - Art. 4 also forbids system overloading and "excessive automated data extraction".
  - FAQ: «CC0 provides complete waiver of rights and is recommended for machine-readable data… CC BY 4.0 allows commercial and non-commercial use, modification and distribution provided source attribution.»
- **API and token:** the docs page `/docs/` returned 404 and `/api` returned only `{"version": 1}`.
  - **Conflict:** third-party tutorials and an SDK README say you register through a form at `https://www.data.gov.gr/token/` and send `Authorization: Token <token>`. That URL returned 404 when I fetched it. The current terms page does not mention tokens. **[token requirement unverified]**
  - Check whether the token is still needed once you find a dataset worth calling.
- **Suitability:** (a) no, the supermarket dataset has no barcode or current coverage. (b) no.

## Source D: other open or openly licensed sources

- **Open Food Facts** (`https://world.openfoodfacts.org/`). Product identity by barcode: name, brand, quantity, images. Licences (`/terms-of-use`):
  - Database: «The Open Food Facts database is available under the Open Database License».
  - Contents: «Individual contents of the database are available under the Database Contents License».
  - Images: «Products images are available under the Creative Commons Attribution ShareAlike licence».
  - Re-users must «mention the licence and to attribute the authorship to Open Food Facts with a link».
  - API rules (User-Agent, rate limits) are in its API docs, which I did not read. Needs no registration for reads, as far as I know **[unverified]**.
  - Suitability: (a) barcode lookup, yes, though Greek coverage is partial. (b) No price data, so no.
- **Open Prices** (`https://prices.openfoodfacts.org/`). Crowdsourced, receipt-based prices from the same project. The page content was not readable here, so its licence and API are **unverified**. Greek coverage is likely thin. Worth checking.
- **EU level:** I found no EU open dataset of supermarket shelf prices. The EU HICP and Eurostat series are aggregate indices, not product prices.
- **Retailer sites and apps:** out of scope. No retailer API was found. Not investigated further to avoid anything resembling scraping.

## Summary table

| Source | Official | Documented | Current prices | Barcode | Licence stated | Token | Fits lookup | Fits daily 50-item refresh |
|---|---|---|---|---|---|---|---|---|
| PosoKanei UI | yes | n/a | yes, daily | yes | not found | no | UI only | no |
| `api.posokanei.gov.gr` | de facto | no | yes, daily | yes (reported) | none found | no | technically | technically, unsanctioned |
| data.gov.gr supermarket dataset | yes | partly | no (stale) | no | "open data", unspecific | possibly | no | no |
| Open Food Facts | no (community) | yes | no | yes | ODbL / DbCL / CC BY-SA | no | partial | no |
| Open Prices | no (community) | unverified | sparse | yes | unverified | unverified | unverified | unlikely |

## Sources

- https://data.gov.gr/dataset/stoixeia-timwn-trofimwn-apo-soype-market
- https://data.gov.gr/pages/terms-of-use and https://data.gov.gr/en/pages/faq
- https://github.com/ppapapetrou76/go-data-gov-gr-sdk (token form reference)
- https://www.keeptalkinggreece.com/2026/06/17/posokanei-digital-pltform-supermarkets-prices-comparison-consumers/
- https://athens-times.com/posokanei-22-faqs-from-the-ministry-of-development-on-the-new-price-comparison-platform/
- https://www.thetoc.gr/oikonomia/article/posokaneigovgr-pos-leitourgei-i-platforma---apo-poia-souper-market-proerxontai-oi-times-posa-proionta-perilambanei/
- https://github.com/spyrosavl/posokanei and https://github.com/charistas/posokanei-mcp
- https://world.openfoodfacts.org/terms-of-use
