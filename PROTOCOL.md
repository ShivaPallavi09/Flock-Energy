# Urja Meter Ops — Legacy Protocol Discovery Document (`PROTOCOL.md`)

## 1. Executive Summary

During reconnaissance of `https://urja-ops.flockenergy.tech`, we conducted network inspection, static bundle analysis, and interactive HTTP probing. Rather than an older server-side-rendered PHP/JSP system, the "Urja Meter Ops" portal is an internal utility operations dashboard built using **SvelteKit** and **Better-Auth**.

While the user interface displays simple paginated tables, the frontend interacts with a combination of SvelteKit data endpoints, internal REST endpoints, and a cryptographically signed HMAC export route. Crucially, the portal conceals several architectural inconsistencies between meter generations and enforces strict Origin/CSRF protections.

This document records the exact protocol mechanics, authentication workflows, internal endpoints, schema quirks, and edge cases discovered during reverse-engineering.

---

## 2. Authentication & Session Management

### 2.1 The Login Mechanism
* **Endpoint:** `POST https://urja-ops.flockenergy.tech/login`
* **Form Action:** SvelteKit form action.
* **Payload Format:** `application/x-www-form-urlencoded`
* **Form Fields:**
  * `email`: `operator@urja.local` (*Surprise: the portal prompts for an email address rather than a generic username*).
  * `password`: `urja-ops-2026`

### 2.2 CSRF & Origin Verification Requirement
When invoking the login endpoint using standard HTTP client defaults (e.g. `curl` or unconfigured `httpx`), the server immediately rejects the request with:
```http
HTTP/1.1 403 Forbidden
Content-Length: 46

Cross-site POST form submissions are forbidden
```
**Discovery:** SvelteKit validates the `Origin` and `Referer` headers against its host header to prevent Cross-Site Request Forgery (CSRF). Any programmatic client must supply:
```http
Origin: https://urja-ops.flockenergy.tech
Referer: https://urja-ops.flockenergy.tech/login
```

### 2.3 Session Token & Cookie Lifecycle
* **Response:** Upon successful authentication, the server responds with:
  ```json
  {"type": "redirect", "status": 303, "location": "/meters"}
  ```
* **Session Cookie:** Sets an HTTP-only secure cookie:
  ```
  __Secure-better-auth.session_token=<token_id>.<signature>
  ```
* **Session Invalidation / Expiry Behavior:**
  * Requests to `/portal/*` API endpoints without a valid session return:
    ```http
    HTTP/1.1 401 Unauthorized
    {"error": "unauthorized", "message": "A valid session is required."}
    ```
  * Requests to HTML page routes (e.g. `/meters/J100000`) without a valid session return:
    ```http
    HTTP/1.1 302 Found
    Location: /login
    ```
  * **Adapter Handling:** The adapter intercepts both `401 Unauthorized` and `302 -> /login` redirects, triggers an automated thread-safe re-authentication, and replays the original request.

---

## 3. Discovered Endpoints & Protocols

### 3.1 Meter Search (`/portal/meters/search`)
* **URL:** `GET /portal/meters/search?q={query}&page={page}`
* **Auth:** Required (`__Secure-better-auth.session_token` cookie)
* **Query Parameters:**
  * `q` (string, optional): Text filter matching `meterId` prefix/substring or `serialNo`.
  * `page` (integer, default: 1): 1-indexed page number (returns 20 items per page).
* **Response Sample:**
  ```json
  {
    "data": [
      {
        "meterId": "J100000",
        "serialNo": "SE33962",
        "make": "HPL",
        "phaseType": "single",
        "installStatus": "Decommissioned",
        "dtCode": "DT-001"
      }
    ],
    "total": 403
  }
  ```

### 3.2 Distribution Transformers (`/portal/dts`)
* **URL:** `GET /portal/dts?page={page}`
* **Auth:** Required
* **Response Sample:**
  ```json
  {
    "data": [
      {
        "code": "DT-001",
        "name": "Malviya Nagar DT 1",
        "feederCode": "F-001",
        "capacityKva": 100
      }
    ],
    "total": 40
  }
  ```
* **Total Assets:** Exactly 40 Distribution Transformers across Jaipur distribution feeders.

### 3.3 Signing Keys Endpoint (`/portal/keys`)
* **URL:** `GET /portal/keys`
* **Auth:** Required
* **Response Sample:**
  ```json
  {
    "data": {
      "signingSecret": "I3dZPPf5CgTp7JyGNMI8i6z8LFR7TmSR"
    }
  }
  ```
* **Purpose:** Provides a rotating dynamic secret used to sign bulk export requests.

### 3.4 Cryptographically Signed Bulk Export (`/portal/export`)
* **URL:** `GET /portal/export?page=1`
* **Auth:** Session cookie + HMAC-SHA256 signature headers.
* **Signing Algorithm:**
  1. Retrieve `signingSecret` from `/portal/keys`.
  2. Compute Unix epoch timestamp: `timestamp = str(int(time.time()))`.
  3. Construct canonical signing message:
     ```
     METHOD\nPATH\nQUERY\nTIMESTAMP
     ```
     Example:
     ```
     GET\n/portal/export\npage=1\n1730000000
     ```
  4. Compute HMAC-SHA256 using `signingSecret` as key and canonical string as payload.
  5. Send HTTP request with headers:
     ```http
     x-timestamp: 1730000000
     x-signature: <hex_encoded_hmac_hash>
     ```
* **Response Sample:**
  ```json
  {
    "data": [
      {
        "meterId": "J100000",
        "serialNo": "SE33962",
        "make": "HPL",
        "phaseType": "single",
        "installStatus": "Decommissioned",
        "installType": "Whole Current",
        "build": "legacy",
        "dtCode": "DT-001",
        "hierarchy": {
          "zone": {"name": "Jaipur Zone 1", "code": "Z-01"},
          "circle": {"name": "Circle 1", "code": "C-01"},
          "division": {"name": "Division 1", "code": "D-01"},
          "subdivision": {"name": "Subdivision 1", "code": "SD-01"},
          "substation": {"name": "Substation 1", "code": "SS-01"},
          "feeder": {"name": "Feeder 1", "code": "F-001"},
          "dt": {"name": "Malviya Nagar DT 1", "code": "DT-001"}
        },
        "geo": {
          "lat": 26.938961002479868,
          "lng": 75.83095696146852
        }
      }
    ],
    "total": 403
  }
  ```
* **Significance:** This single endpoint yields the full fleet of 403 meters, complete with nested hierarchy and GPS coordinates, enabling pre-warmed caching and local spatial indexing.

### 3.5 Meter GPS Coordinates (`/portal/meters/{id}/geo`)
* **URL:** `GET /portal/meters/{meter_id}/geo`
* **Response Sample:**
  ```json
  {
    "data": {
      "latitude": "26.938961002479868",
      "longitude": "75.83095696146852"
    }
  }
  ```
* **Quirk:** Coordinates are returned as strings rather than floating-point numbers.

### 3.6 Meter Interval Energy Telemetry (`/portal/meters/{id}/energy`)
* **URL:** `GET /portal/meters/{meter_id}/energy?from={YYYY-MM-DD}&to={YYYY-MM-DD}`
* **Query Parameters:**
  * `from` (string, optional): Filters readings starting from `YYYY-MM-DD` (inclusive).
  * `to` (string, optional): Filters readings up to `YYYY-MM-DD` (inclusive).
* **Interval Cadence:** 30-minute interval smart-meter load profiles (48 readings per day).
* **Response Sample:**
  ```json
  {
    "data": [
      {
        "timestamp": "24/06/2026 00:00",
        "kwh": "48439.16",
        "kvah": "52314.29",
        "voltR": "229"
      }
    ]
  }
  ```

---

## 4. Architectural Quirks & Anomalies Discovered

### Quirk 1: Divergent Telemetry Schemas (`legacy` vs `v2`)
Inspection of all 403 meters revealed two distinct internal data builds:
* **`legacy` (238 meters):** Detail data is represented as an array of key-value pairs:
  ```json
  "detail": {
    "data": [
      {"parameterName": "Meter ID", "parameterValue": "J100000"},
      {"parameterName": "Serial No", "parameterValue": "SE33962"},
      {"parameterName": "Make", "parameterValue": "HPL"},
      {"parameterName": "Phase Type", "parameterValue": "single"},
      {"parameterName": "Installation Status", "parameterValue": "Decommissioned"},
      {"parameterName": "Installation Type", "parameterValue": "Whole Current"}
    ]
  }
  ```
* **`v2` (165 meters):** Detail data is represented as an embedded JSON string under `classData`:
  ```json
  "detail": {
    "classData": "{\"installed_meter\":{\"MeterId\":\"J100004\",\"SerialNo\":\"SE65293\",\"Make\":\"Genus\",\"PhaseType\":\"single\",\"InstallationStatus\":\"Faulty\",\"InstallationType\":\"CT Operated\"}}"
  }
  ```
* **Adapter Normalization:** The client adapter detects whether `classData` or `data` is present, parses the embedded string if necessary, and normalizes both into a unified `MeterDetail` schema with consistent field naming.

### Quirk 2: Non-Standard Date Formats
Telemetry timestamps are formatted as `DD/MM/YYYY HH:MM` (e.g. `24/06/2026 00:00`), whereas standard ISO-8601 APIs expect `YYYY-MM-DDTHH:MM:SSZ`. The adapter parses these using `dateutil` (with `dayfirst=True`) and serializes ISO timestamps.

### Quirk 3: Stringified Numerics
In both `/portal/meters/{id}/geo` and `/portal/meters/{id}/energy`, numeric values (latitude, longitude, kWh, kVAh, voltage) are serialized as string primitives rather than native floats. The wrapper coerces all metrics to typed floats.

### Quirk 4: Dual-Channel Fallback
In addition to the internal `/portal/*` REST endpoints, the HTML page `/meters/{id}` renders a `<dl>` element with nameplate parameters and a `<nav>` element with hierarchical breadcrumbs. The adapter includes a BeautifulSoup fallback parser to ensure resilience if internal endpoints undergo route changes.

---

## 5. Summary Table of Discovered Assets

| Asset Type | Count | Distribution / Notes |
| :--- | :--- | :--- |
| **Total Smart Meters** | 403 | `J100000` to `J100402` |
| **Telemetry Builds** | 403 | 238 `legacy`, 165 `v2` |
| **Manufacturers** | 5 | HPL (90), Genus (88), Secure (85), Allied (76), L&T (64) |
| **Phase Configurations** | 2 | Single Phase (277), Three Phase (126) |
| **Operational Statuses**| 3 | Installed (238), Faulty (90), Decommissioned (75) |
| **Distribution Transformers** | 40 | `DT-001` through `DT-040` (Capacities: 63 to 1000 kVA) |
| **Distribution Feeders** | 40 | `F-001` through `F-040` |
| **Substations** | 40 | `SS-01` through `SS-40` |
| **Divisions & Circles** | 5 | Jaipur Discom operations hierarchy |
