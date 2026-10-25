# Flock Energy — Urja Meter Ops Modern REST API Gateway

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![Tests](https://img.shields.io/badge/Tests-20%20Passed-brightgreen.svg)]()
[![OpenAPI](https://img.shields.io/badge/OpenAPI-3.1.0-green.svg)](openapi.json)

A modern, high-performance, well-documented REST API proxy and data normalization service built over the legacy **Urja Meter Ops** portal (`https://urja-ops.flockenergy.tech`).

This service automates session authentication, circumvents SvelteKit CSRF protections, signs HMAC-SHA256 export queries, normalizes divergent legacy and v2 telemetry schemas, reconstructs electrical distribution grid hierarchies, provides fast local spatial filtering (Haversine proximity), and serves an interactive web dashboard.

---

## 📑 Deliverables Quick Links
* **Protocol Reverse-Engineering Report:** [PROTOCOL.md](PROTOCOL.md) — Comprehensive technical write-up of portal internals, auth tokens, HMAC export signing, endpoints, and data anomalies.
* **OpenAPI 3.1 Specification:** [openapi.json](openapi.json) — Complete machine-readable schema for downstream clients.
* **Engineering Reflections:** [REFLECTION.md](REFLECTION.md) — Answers to the 5 required reflection questions (assumptions, challenges, mistakes, future work, self-critique).
* **Interactive API Documentation:** Available at `http://localhost:8000/docs` (Swagger UI) or `http://localhost:8000/redoc`.
* **Interactive Operations Dashboard:** Available at `http://localhost:8000/dashboard`.

---

## 🏗️ Architecture & Project Structure

The project is structured with strict separation of concerns between HTTP transport, session management, data normalization, query acceleration, and API routing:

```text
flock-energy-api/
├── app/
│   ├── __init__.py           # Package version definition
│   ├── config.py             # Configuration loaded via Pydantic Settings & environment variables
│   ├── models.py             # Strongly typed Pydantic v2 schemas and validation contracts
│   ├── client.py             # UrjaPortalClient: HTTP adapter, auto-reauth, and HMAC export signer
│   ├── cache.py              # FleetCache: In-memory cache manager with TTL and atomic thread-safe swaps
│   ├── query.py              # QueryEngine: Multi-attribute filtering, Haversine spatial indexing, and tree builder
│   ├── dashboard.html        # Interactive Single-Page Application (Tailwind CSS, Chart.js, FontAwesome)
│   └── main.py               # FastAPI application entrypoint and REST endpoint definitions
├── tests/
│   ├── __init__.py
│   ├── test_query.py         # Unit tests for Haversine math, filtering, pagination, and tree building
│   └── test_api.py           # Integration tests for all endpoints against live/mocked portal
├── PROTOCOL.md               # Reverse-engineering protocol report
├── REFLECTION.md             # Detailed engineering reflection answers
├── README.md                 # Primary project documentation
├── openapi.json              # Exported OpenAPI 3.1 specification
├── requirements.txt          # Python runtime dependencies
└── .gitignore                # Git ignore patterns
```

### Key Architectural Flow
```
[ Downstream Clients / Mobile / Operations Dashboard ]
                        │
                        ▼ (Clean Typed JSON)
             [ FastAPI Service Layer (main.py) ]
                        │
          ┌─────────────┴─────────────┐
          ▼                           ▼
[ QueryEngine / Index Layer ]   [ FleetCache (5-min TTL) ]
(Spatial Proximity & Filters)        │ (Pre-warmed on startup)
                                      ▼
                      [ UrjaPortalClient (client.py) ]
                      • Automatic Session Persistence
                      • Origin/Referer CSRF Bypass
                      • HMAC-SHA256 Export Signer
                      • Fallback BeautifulSoup Parser
                                      │
                                      ▼ (Raw HTTP / SvelteKit)
                   [ Legacy Urja Meter Ops Portal ]
```

---

## 🚀 Quickstart & Setup Instructions

### Prerequisites
* Python 3.10 or higher
* Internet connectivity (to communicate with the live portal)

### 1. Clone & Navigate to Project
```bash
git clone https://github.com/your-username/flock-energy-api.git
cd flock-energy-api
```

### 2. Create and Activate Virtual Environment
```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configuration (Optional)
The service operates out-of-the-box using the provided portal credentials. To customize settings, create a `.env` file:
```env
PORTAL_BASE_URL="https://urja-ops.flockenergy.tech"
PORTAL_EMAIL="operator@urja.local"
PORTAL_PASSWORD="urja-ops-2026"
CACHE_TTL_SECONDS=300
REQUEST_TIMEOUT=15.0
```

### 5. Start the API Service
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Once started, visit:
* **Interactive Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
* **ReDoc Documentation:** [http://localhost:8000/redoc](http://localhost:8000/redoc)
* **Fleet Operations Web App:** [http://localhost:8000/dashboard](http://localhost:8000/dashboard)

---

## 🧪 Running the Automated Test Suite

The repository contains 20 comprehensive automated unit and integration tests verifying authentication, normalization, spatial filtering, and all API endpoints:

```bash
python -m pytest tests/ -v
```

**Test Execution Output:**
```text
============================= test session starts =============================
platform win32 -- Python 3.13.9, pytest-9.1.1, pluggy-1.5.0
collected 20 items

tests/test_api.py::test_health_endpoints PASSED                          [  5%]
tests/test_api.py::test_login_endpoint PASSED                            [ 10%]
tests/test_api.py::test_list_meters PASSED                               [ 15%]
tests/test_api.py::test_filter_meters_by_search PASSED                   [ 20%]
tests/test_api.py::test_filter_meters_by_status PASSED                   [ 25%]
tests/test_api.py::test_spatial_proximity_search PASSED                  [ 30%]
tests/test_api.py::test_get_meter_detail_success PASSED                  [ 35%]
tests/test_api.py::test_get_meter_detail_404 PASSED                      [ 40%]
tests/test_api.py::test_get_meter_consumption PASSED                     [ 45%]
tests/test_api.py::test_get_meter_consumption_date_filter PASSED         [ 50%]
tests/test_api.py::test_transformers_endpoints PASSED                    [ 55%]
tests/test_api.py::test_hierarchy_endpoint PASSED                        [ 60%]
tests/test_api.py::test_analytics_summary PASSED                         [ 65%]
tests/test_api.py::test_dashboard_page PASSED                            [ 70%]
tests/test_query.py::test_haversine_distance PASSED                      [ 75%]
tests/test_query.py::test_normalize_legacy_meter PASSED                  [ 80%]
tests/test_query.py::test_normalize_v2_meter PASSED                      [ 85%]
tests/test_query.py::test_filter_meters PASSED                           [ 90%]
tests/test_query.py::test_pagination PASSED                              [ 95%]
tests/test_query.py::test_build_network_tree PASSED                      [100%]

============================= 20 passed in 2.40s ==============================
```

---

## 📡 API Reference & Sample Requests

### 1. Health & Portal Status
Check service operational status, upstream portal reachability, and cache diagnostics.

```bash
curl -X GET "http://localhost:8000/api/v1/health"
```
**Sample Response:**
```json
{
  "status": "healthy",
  "portal_status": "online",
  "authenticated": true,
  "cached_meters_count": 403,
  "cached_transformers_count": 40,
  "cache_age_seconds": 12.4
}
```

---

### 2. List & Filter Smart Meters
Retrieve a paginated list of meters with multi-attribute filtering (status, make, phase, DT) and search.

```bash
# Retrieve first 5 meters manufactured by HPL that are Installed
curl -X GET "http://localhost:8000/api/v1/meters?make=HPL&status=Installed&page=1&page_size=5"
```
**Sample Response:**
```json
{
  "data": [
    {
      "meter_id": "J100003",
      "serial_number": "GE97217",
      "make": "HPL",
      "phase_type": "single",
      "install_status": "Installed",
      "install_type": "Whole Current",
      "build": "legacy",
      "dt_code": "DT-004",
      "geo": {
        "latitude": 26.918961,
        "longitude": 75.820957
      },
      "distance_km": null
    }
  ],
  "pagination": {
    "total": 52,
    "page": 1,
    "page_size": 5,
    "total_pages": 11
  }
}
```

---

### 3. Spatial Proximity Search (Extension)
Find meters near specific GPS coordinates using the Haversine distance engine.

```bash
# Find meters within 3.5 km of Malviya Nagar, Jaipur
curl -X GET "http://localhost:8000/api/v1/meters?near_lat=26.938961&near_lng=75.830957&radius_km=3.5&page_size=3"
```
**Sample Response:**
```json
{
  "data": [
    {
      "meter_id": "J100000",
      "serial_number": "SE33962",
      "make": "HPL",
      "phase_type": "single",
      "install_status": "Decommissioned",
      "dt_code": "DT-001",
      "geo": {
        "latitude": 26.938961,
        "longitude": 75.830957
      },
      "distance_km": 0.0
    },
    {
      "meter_id": "J100001",
      "serial_number": "GE84132",
      "make": "L&T",
      "phase_type": "single",
      "install_status": "Installed",
      "dt_code": "DT-002",
      "geo": {
        "latitude": 26.93121,
        "longitude": 75.82504
      },
      "distance_km": 1.042
    }
  ],
  "pagination": {
    "total": 48,
    "page": 1,
    "page_size": 3,
    "total_pages": 16
  }
}
```

---

### 4. Get Meter Details & Nameplate
Fetches unified details for a meter, harmonizing `legacy` and `v2` builds.

```bash
curl -X GET "http://localhost:8000/api/v1/meters/J100000"
```
**Sample Response:**
```json
{
  "meter_id": "J100000",
  "serial_number": "SE33962",
  "make": "HPL",
  "phase_type": "single",
  "install_status": "Decommissioned",
  "install_type": "Whole Current",
  "build": "legacy",
  "dt_code": "DT-001",
  "geo": {
    "latitude": 26.938961002479868,
    "longitude": 75.83095696146852
  },
  "hierarchy": {
    "zone": {"name": "Jaipur Zone 1", "code": "Z-01"},
    "circle": {"name": "Circle 1", "code": "C-01"},
    "division": {"name": "Division 1", "code": "D-01"},
    "subdivision": {"name": "Subdivision 1", "code": "SD-01"},
    "substation": {"name": "Substation 1", "code": "SS-01"},
    "feeder": {"name": "Feeder 1", "code": "F-001"},
    "dt": {"name": "Malviya Nagar DT 1", "code": "DT-001"}
  },
  "nameplate": [
    {"label": "Meter ID", "value": "J100000"},
    {"label": "Serial Number", "value": "SE33962"},
    {"label": "Make", "value": "HPL"},
    {"label": "Phase Type", "value": "single"},
    {"label": "Installation Status", "value": "Decommissioned"},
    {"label": "Installation Type", "value": "Whole Current"},
    {"label": "DT Code", "value": "DT-001"},
    {"label": "Telemetry Build", "value": "legacy"}
  ]
}
```

---

### 5. Smart Meter Interval Consumption Telemetry
Fetches 30-minute interval telemetry with computed statistical summary and date filtering.

```bash
# Query intervals between 2026-06-24 and 2026-06-25
curl -X GET "http://localhost:8000/api/v1/meters/J100000/consumption?from_date=2026-06-24&to_date=2026-06-25"
```
**Sample Response:**
```json
{
  "meter_id": "J100000",
  "summary": {
    "total_readings": 96,
    "start_time": "2026-06-24T00:00:00",
    "end_time": "2026-06-25T23:30:00",
    "total_kwh_delta": 40.32,
    "min_kwh": 48439.16,
    "max_kwh": 48479.48,
    "avg_voltage_r": 227.45,
    "min_voltage_r": 218.0,
    "max_voltage_r": 235.0
  },
  "readings": [
    {
      "timestamp": "2026-06-24T00:00:00",
      "raw_timestamp": "24/06/2026 00:00",
      "kwh": 48439.16,
      "kvah": 52314.29,
      "volt_r": 229.0
    },
    {
      "timestamp": "2026-06-24T00:30:00",
      "raw_timestamp": "24/06/2026 00:30",
      "kwh": 48439.58,
      "kvah": 52314.75,
      "volt_r": 220.0
    }
  ]
}
```

---

### 6. Electrical Network Hierarchy Tree (Extension)
Reconstructs the hierarchical network tree: Zone &rarr; Circle &rarr; Division &rarr; Subdivision &rarr; Substation &rarr; Feeder &rarr; DT &rarr; Meters.

```bash
curl -X GET "http://localhost:8000/api/v1/hierarchy"
```
**Sample Response Structure:**
```json
{
  "name": "Urja Distribution Network",
  "type": "root",
  "zones": {
    "Z-01": {
      "code": "Z-01",
      "name": "Jaipur Zone 1",
      "circles": {
        "C-01": {
          "code": "C-01",
          "name": "Circle 1",
          "divisions": { ... }
        }
      }
    }
  }
}
```

---

### 7. Fleet Operational Analytics
Provides instant fleet-wide metrics without expensive DB queries.

```bash
curl -X GET "http://localhost:8000/api/v1/analytics/summary"
```
**Sample Response:**
```json
{
  "total_meters": 403,
  "total_transformers": 40,
  "total_capacity_kva": 14200.0,
  "status_breakdown": {
    "Installed": 238,
    "Faulty": 90,
    "Decommissioned": 75
  },
  "make_breakdown": {
    "HPL": 90,
    "Genus": 88,
    "Secure": 85,
    "Allied": 76,
    "L&T": 64
  },
  "phase_breakdown": {
    "single": 277,
    "three": 126
  },
  "build_breakdown": {
    "legacy": 238,
    "v2": 165
  }
}
```

---

## ⚖️ Architectural Decisions & Trade-offs

1. **In-Memory Cache vs Live Upstream Scraping:**
   * *Decision:* On startup, the service invokes the HMAC-signed export route to load all 403 meters into an in-memory index (`FleetCache`) with a 5-minute TTL.
   * *Trade-off:* Read latency drops from ~800ms (scraping multiple portal pages) to **< 2ms**, completely isolating downstream clients from portal rate limits. The trade-off is that fleet additions take up to 5 minutes to appear unless `/api/v1/cache/refresh` is triggered. Telemetry readings are always fetched on-demand.
2. **Bulk HMAC Export Route vs Paging HTML Scraping:**
   * *Decision:* Rather than parsing 21 pages of HTML tables on every request, we reverse-engineered the portal's HMAC-SHA256 signing secret endpoint (`/portal/keys` & `/portal/export`).
   * *Trade-off:* Incredibly fast, complete dataset extraction. If the portal alters its cryptographic signing algorithm, we maintain a secondary HTML fallback parser using BeautifulSoup.
3. **Session Interception vs Manual Token Passing:**
   * *Decision:* Session authentication is managed transparently behind the scenes with thread-safe auto-reauthentication upon encountering `401 Unauthorized` or `302/303 Redirect to /login`.
   * *Trade-off:* Downstream consumers do not need to manage upstream session cookies; they simply call the REST API cleanly.

---

## 🚫 What Was Intentionally Skipped & Why

1. **Write Operations (Creating/Modifying Meters):**
   * *Reason:* The assignment instructions explicitly state: *"Treat the portal as read-only. You don't need to (and shouldn't try to) attack or break it — everything you need to use it is available to a normal logged-in user."*
2. **Persistent External Database (Postgres/Redis):**
   * *Reason:* The take-home rules mandate that *"No paid services required. Everything can be built and run locally."* Adding a mandatory Postgres or Redis container would add setup friction for reviewers cloning the repo. The in-memory cache and query engine deliver blazing performance with zero external infrastructure dependencies.

---

## 🔮 What We'd Improve With More Time

* **Distributed Caching with Redis & Cache Invalidation Webhooks:** For multi-instance horizontal scaling.
* **Asynchronous Telemetry Streaming:** Adding Server-Sent Events (SSE) or WebSockets to stream real-time meter consumption readings and grid anomaly alerts.
* **Offline Mock Server Fixtures:** For CI/CD automation without relying on the live portal URL.

For more reflections, see [REFLECTION.md](REFLECTION.md).
