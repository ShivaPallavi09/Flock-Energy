# Engineering Reflection (`REFLECTION.md`)

This document answers the five required engineering reflection questions for the Flock Energy Take-Home Assignment.

---

### 1. What assumptions did you make?

* **Read-Heavy Invariant:** We assumed that the Urja Meter Ops portal is predominantly read-only for field operators and downstream analytics pipelines. Consequently, our service treats the portal as an upstream data lake, optimizing for read performance through in-memory caching and index acceleration.
* **Bulk Export Availability & Staleness:** We observed that `/portal/export` reliably exports all 403 meters along with full network hierarchy and coordinates. We assumed that smart meter fleet configurations (serial numbers, makes, transformer associations) change relatively infrequently compared to interval consumption telemetry. Therefore, we chose a 5-minute cache TTL (`cache_ttl_seconds = 300`) for the fleet metadata while fetching consumption telemetry on-demand with optional date filters.
* **Date Parsing Assumption:** We assumed interval timestamps formatted as `DD/MM/YYYY HH:MM` (e.g. `24/06/2026 00:00`) adhere strictly to Indian standard date notation (`dayfirst = True`), rather than American `MM/DD/YYYY` which would fail for days greater than 12.
* **Single Discom Scope:** We assumed the current installation operates within a single electricity distribution company (Jaipur Discom) and that meter IDs follow the alphanumeric format `J100xxx`.

---

### 2. Which part was the most difficult, and how did you get unstuck?

* **The SvelteKit CSRF Protection:** The initial programmatic login attempts consistently failed with `403 Forbidden` and the message `"Cross-site POST form submissions are forbidden"`. Because the assignment prompt suggested traditional form-POST scraping, receiving a 403 CSRF block was an initial roadblock.
* **How We Got Unstuck:** Rather than brute-forcing credentials, we inspected the client-side JavaScript bundles loaded by the portal (`app.*.js` and `start.*.js`). This revealed that the portal runs on SvelteKit with Vite bundling. SvelteKit's built-in CSRF protection checks the `Origin` and `Referer` headers for any cross-site form POST. By setting `Origin: https://urja-ops.flockenergy.tech` and `Referer: https://urja-ops.flockenergy.tech/login`, authentication immediately succeeded with a 200/303 response and set the `__Secure-better-auth.session_token` cookie.
* **Discovering the HMAC Export Route:** Deciphering how the frontend "Export all meters" button worked required reverse-engineering the SvelteKit component bundle `4.2Bgc2kUI.js`. We traced the Web Crypto API calls to discover the HMAC-SHA256 signing secret endpoint (`/portal/keys`) and reconstructed the canonical message format (`METHOD\nPATH\nQUERY\nTIMESTAMP`) in Python.

---

### 3. If you had another day, what would you improve?

* **Persistent Distributed Caching with Redis:** While our in-memory `FleetCache` is fast and thread-safe for a single instance, scaling horizontally across multiple replicas would benefit from a shared Redis cache with cache invalidation pub/sub.
* **Webhook & Stale Cache Event Streaming:** We would add Server-Sent Events (SSE) or WebSockets to stream real-time meter consumption readings and grid anomaly alerts (e.g., undervoltage events below 210V or sudden spikes in kVAh).
* **Comprehensive Mock Server for CI/CD:** Although our tests currently execute against the live portal instance, we would build a full wiremock or `pytest-httpx` fixture suite that simulates all legacy portal quirks offline, ensuring automated CI runs without depending on external portal availability.
* **Database Mirror & Historical Trend Analytics:** Storing historical 30-minute interval readings in a TimescaleDB / DuckDB database would allow downstream users to perform long-term load-flow analysis, peak demand forecasting, and DT overload detection over multi-month windows.

---

### 4. What mistake did you make while solving this (there's always one)?

* **Initial Form Field Naming:** During initial reconnaissance, our script posted `{"username": "operator@urja.local", ...}` assuming traditional username/password semantics as mentioned in the prompt. The server ignored the field because the actual HTML `<input name="email">` expected `email`.
* **Stringified Numeric Parsing:** When first writing the consumption summary calculations, we attempted arithmetic directly on the raw API fields before realizing that `kwh`, `kvah`, and `voltR` were serialized as string types in the JSON response (e.g., `"48439.16"` instead of `48439.16`). This resulted in a `TypeError: unsupported operand type(s) for -: 'str' and 'str'`. We quickly resolved this by adding explicit float coercion and validation in Pydantic models.

---

### 5. If you were reviewing your own submission, what would you criticise?

* **In-Memory Cache Scaling Trade-off:** The decision to pull all 403 meters into an in-memory dictionary during cache warm-up works for a fleet of several hundred to a few thousand meters (query execution in <1ms). However, if the utility expands to hundreds of thousands or millions of smart meters, holding the full fleet in Python memory would cause high memory pressure. At that scale, an indexed database (PostgreSQL with PostGIS for spatial indexing) should replace the in-memory `QueryEngine`.
* **Synchronous HTTP Client vs Pure Async:** While FastAPI is asynchronous, `UrjaPortalClient` currently utilizes `httpx.Client` with thread locks. While this guarantees deterministic re-authentication across thread pools, an `httpx.AsyncClient` implementation with an `asyncio.Lock` would offer higher concurrency under thousands of simultaneous requests.
* **Coupling to Specific Portal Quirks:** The HMAC export route relies on `/portal/keys` and `/portal/export` remaining unchanged. If upstream developers modify the signing canonical format, our bulk path would fail, necessitating fallback to paginated scraping. We mitigated this by implementing the BeautifulSoup HTML fallback parser, but runtime telemetry on fallback frequency would make this even more observable.
