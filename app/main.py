import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse

from app.cache import FleetCache
from app.client import UrjaPortalClient
from app.config import get_settings
from app.models import (
    AnalyticsSummary,
    ConsumptionResponse,
    HealthResponse,
    MeterDetail,
    MeterSummary,
    PaginatedResponse,
    Transformer,
)
from app.query import QueryEngine

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("urja_api")

settings = get_settings()

# Client and Cache singletons
portal_client = UrjaPortalClient(settings=settings)
fleet_cache = FleetCache(client=portal_client, settings=settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for application startup and shutdown.
    Pre-warms portal session and caches meter fleet so subsequent requests are fast.
    """
    logger.info("Initializing Flock Energy Urja Meter Ops API service...")
    try:
        portal_client.login()
        fleet_cache.refresh(force=True)
        logger.info("Service initialized and fleet cache successfully warmed.")
    except Exception as exc:
        logger.warning(
            f"Initial portal warm-up failed (will retry on incoming request): {exc}"
        )
    yield
    logger.info("Shutting down Urja Meter Ops API service.")


app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    description=settings.api_description,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Enable CORS for downstream web consumers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =====================================================================
# Root & Dashboard Endpoints
# =====================================================================

@app.get("/", include_in_schema=False)
def root():
    """Redirect root path to interactive Swagger documentation."""
    return RedirectResponse(url="/docs")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Silence browser favicon requests."""
    from fastapi import Response
    return Response(status_code=204)



@app.get("/dashboard", response_class=HTMLResponse, tags=["Dashboard"], summary="Modern Web Client Dashboard")
def get_dashboard():
    """
    Interactive web application providing smart meter exploration,
    real-time interval consumption charts, and electrical hierarchy visualization.
    """
    import os
    dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    if os.path.exists(dashboard_path):
        with open(dashboard_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Dashboard not found</h1>", status_code=404)


# =====================================================================
# Health & Authentication
# =====================================================================

@app.get(
    "/api/v1/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Service and Upstream Health Check",
)
@app.get(
    "/health",
    response_model=HealthResponse,
    include_in_schema=False,
)
def health_check():
    """
    Check operational health of the wrapper service and connectivity to the Urja portal.
    """
    health = portal_client.check_health()
    cache_stats = fleet_cache.stats()
    is_healthy = health["portal_online"]

    return HealthResponse(
        status="healthy" if is_healthy else "degraded",
        portal_status="online" if health["portal_online"] else "offline",
        authenticated=health["authenticated"],
        cached_meters_count=cache_stats["cached_meters_count"],
        cached_transformers_count=cache_stats["cached_transformers_count"],
        cache_age_seconds=cache_stats["cache_age_seconds"],
    )


@app.post(
    "/api/v1/auth/login",
    tags=["Authentication"],
    summary="Trigger Portal Authentication / Re-auth",
)
def authenticate_portal():
    """
    Explicitly trigger or refresh session authentication against the Urja portal.
    (Note: Authentication and re-authentication are also handled transparently by the client).
    """
    try:
        success = portal_client.login()
        if not success:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Urja portal rejected credentials.",
            )
        return {
            "status": "authenticated",
            "message": "Session established with Urja Meter Ops portal.",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Portal authentication error: {str(e)}",
        )


@app.post(
    "/api/v1/cache/refresh",
    tags=["System"],
    summary="Force Refresh Fleet Cache",
)
def refresh_cache():
    """
    Force a re-sync of the smart meter and transformer fleet from the upstream portal.
    """
    try:
        refreshed = fleet_cache.refresh(force=True)
        stats = fleet_cache.stats()
        return {
            "refreshed": refreshed,
            "meters_indexed": stats["cached_meters_count"],
            "transformers_indexed": stats["cached_transformers_count"],
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Cache refresh failed: {str(e)}",
        )


# =====================================================================
# Smart Meters API
# =====================================================================

@app.get(
    "/api/v1/meters",
    response_model=PaginatedResponse[MeterSummary],
    tags=["Meters"],
    summary="List and Filter Smart Meters",
)
def list_meters(
    search: Optional[str] = Query(
        None, description="Search keyword matching meter ID or serial number (e.g. 'J100000' or 'SE33962')"
    ),
    status: Optional[str] = Query(
        None, description="Filter by operational status ('Installed', 'Faulty', 'Decommissioned')"
    ),
    make: Optional[str] = Query(
        None, description="Filter by meter manufacturer ('HPL', 'Genus', 'Secure', 'Allied', 'L&T')"
    ),
    phase_type: Optional[str] = Query(
        None, description="Filter by phase configuration ('single' or 'three')"
    ),
    dt_code: Optional[str] = Query(
        None, description="Filter by Distribution Transformer code ('DT-001')"
    ),
    feeder_code: Optional[str] = Query(
        None, description="Filter by Feeder line code ('F-001')"
    ),
    zone_code: Optional[str] = Query(
        None, description="Filter by Discom Zone code ('Z-01')"
    ),
    near_lat: Optional[float] = Query(
        None, description="Latitude for local spatial proximity search"
    ),
    near_lng: Optional[float] = Query(
        None, description="Longitude for local spatial proximity search"
    ),
    radius_km: Optional[float] = Query(
        5.0, description="Proximity radius in kilometers (default: 5.0 km)"
    ),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=500, description="Number of meters per page"),
):
    """
    Retrieve a paginated list of smart meters.
    Supports multi-attribute relational filtering, text search across IDs,
    and spatial proximity search using the Haversine distance engine.
    """
    all_meters = fleet_cache.get_all_meters()

    filtered = QueryEngine.filter_meters(
        meters=all_meters,
        search=search,
        status=status,
        make=make,
        phase_type=phase_type,
        dt_code=dt_code,
        feeder_code=feeder_code,
        zone_code=zone_code,
        near_lat=near_lat,
        near_lng=near_lng,
        radius_km=radius_km if (near_lat is not None and near_lng is not None) else None,
    )

    sliced, pagination = QueryEngine.paginate(filtered, page=page, page_size=page_size)

    # Cast to MeterSummary
    summaries = [
        MeterSummary(
            meter_id=m.meter_id,
            serial_number=m.serial_number,
            make=m.make,
            phase_type=m.phase_type,
            install_status=m.install_status,
            install_type=m.install_type,
            build=m.build,
            dt_code=m.dt_code,
            geo=m.geo,
            distance_km=m.distance_km,
        )
        for m in sliced
    ]

    return PaginatedResponse(data=summaries, pagination=pagination)


@app.get(
    "/api/v1/meters/{meter_id}",
    response_model=MeterDetail,
    tags=["Meters"],
    summary="Get Smart Meter Details",
)
def get_meter_detail(meter_id: str):
    """
    Retrieve comprehensive details for a specific smart meter.
    Normalizes divergent legacy and v2 telemetry schemas, parses nameplate specifications,
    and reconstructs grid hierarchy path.
    """
    meter = fleet_cache.get_meter(meter_id)
    if not meter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Smart meter with ID '{meter_id}' not found.",
        )
    return meter


@app.get(
    "/api/v1/meters/{meter_id}/consumption",
    response_model=ConsumptionResponse,
    tags=["Consumption"],
    summary="Get Meter Interval Consumption History",
)
def get_meter_consumption(
    meter_id: str,
    from_date: Optional[str] = Query(
        None, description="Start date filter in 'YYYY-MM-DD' format (e.g. '2026-06-24')"
    ),
    to_date: Optional[str] = Query(
        None, description="End date filter in 'YYYY-MM-DD' format (e.g. '2026-06-25')"
    ),
):
    """
    Retrieve interval telemetry readings for a smart meter.
    Returns normalized kWh active energy, kVAh apparent energy, R-phase voltage,
    standardized ISO timestamps, and computed aggregate statistics.
    """
    try:
        return portal_client.get_meter_energy(
            meter_id=meter_id, from_date=from_date, to_date=to_date
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meter with ID '{meter_id}' not found.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch consumption history from Urja portal: {str(e)}",
        )


# =====================================================================
# Transformers & Network Hierarchy API
# =====================================================================

@app.get(
    "/api/v1/transformers",
    response_model=PaginatedResponse[Transformer],
    tags=["Hierarchy"],
    summary="List Distribution Transformers (DTs)",
)
def list_transformers(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
):
    """
    Retrieve all distribution transformers with their feeder connections and kVA capacities.
    """
    transformers = fleet_cache.get_all_transformers()
    sliced, pagination = QueryEngine.paginate(transformers, page=page, page_size=page_size)
    return PaginatedResponse(data=sliced, pagination=pagination)


@app.get(
    "/api/v1/transformers/{code}",
    response_model=Transformer,
    tags=["Hierarchy"],
    summary="Get Transformer by Code",
)
def get_transformer(code: str):
    """Retrieve details for a specific Distribution Transformer."""
    dt = fleet_cache.get_transformer(code)
    if not dt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transformer with code '{code}' not found.",
        )
    return dt


@app.get(
    "/api/v1/hierarchy",
    tags=["Hierarchy"],
    summary="Get Full Electrical Distribution Network Tree",
)
def get_network_hierarchy():
    """
    Reconstruct the full electrical network distribution hierarchy:
    Zone -> Circle -> Division -> Subdivision -> Substation -> Feeder -> DT -> Meters.
    """
    meters = fleet_cache.get_all_meters()
    transformers = fleet_cache.get_all_transformers()
    return QueryEngine.build_network_tree(meters, transformers)


@app.get(
    "/api/v1/analytics/summary",
    response_model=AnalyticsSummary,
    tags=["Analytics"],
    summary="Fleet Operational Analytics Summary",
)
def get_fleet_analytics():
    """
    Calculate aggregate operational statistics across all smart meters and transformers.
    Includes breakdown by operational status, meter make, phase type, and telemetry build.
    """
    meters = fleet_cache.get_all_meters()
    transformers = fleet_cache.get_all_transformers()
    return QueryEngine.compute_analytics(meters, transformers)
