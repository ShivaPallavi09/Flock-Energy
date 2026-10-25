from datetime import datetime
from typing import Dict, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field


# Generic TypeVar for paginated lists
T = TypeVar("T")


class GeoLocation(BaseModel):
    """Geographic coordinates for a smart meter."""
    latitude: float = Field(..., description="Latitude in decimal degrees", examples=[26.938961])
    longitude: float = Field(..., description="Longitude in decimal degrees", examples=[75.830957])


class HierarchyNode(BaseModel):
    """An individual level entity in the utility distribution hierarchy."""
    name: str = Field(..., description="Entity name", examples=["Jaipur Zone 1"])
    code: str = Field(..., description="Entity code", examples=["Z-01"])


class NetworkHierarchy(BaseModel):
    """Full distribution utility hierarchy path from Zone down to Distribution Transformer."""
    zone: Optional[HierarchyNode] = Field(None, description="Discom zone")
    circle: Optional[HierarchyNode] = Field(None, description="Operational circle")
    division: Optional[HierarchyNode] = Field(None, description="Operating division")
    subdivision: Optional[HierarchyNode] = Field(None, description="Subdivision")
    substation: Optional[HierarchyNode] = Field(None, description="Electrical substation")
    feeder: Optional[HierarchyNode] = Field(None, description="Distribution feeder line")
    dt: Optional[HierarchyNode] = Field(None, description="Distribution transformer")


class NameplateParameter(BaseModel):
    """Normalized nameplate attribute extracted from legacy portal schemas."""
    label: str = Field(..., description="Parameter name", examples=["Installation Type"])
    value: str = Field(..., description="Parameter value", examples=["Whole Current"])


class MeterSummary(BaseModel):
    """Summary view of a smart meter."""
    meter_id: str = Field(..., description="Unique meter identifier", examples=["J100000"])
    serial_number: str = Field(..., description="Physical meter serial number", examples=["SE33962"])
    make: str = Field(..., description="Meter manufacturer (e.g., HPL, Genus, Secure, L&T, Allied)", examples=["HPL"])
    phase_type: str = Field(..., description="Phase configuration (single or three)", examples=["single"])
    install_status: str = Field(..., description="Operating status (Installed, Faulty, Decommissioned)", examples=["Installed"])
    install_type: Optional[str] = Field(None, description="Installation category (Whole Current, CT Operated)", examples=["Whole Current"])
    build: Optional[str] = Field(None, description="Internal telemetry architecture build (legacy or v2)", examples=["legacy"])
    dt_code: Optional[str] = Field(None, description="Associated Distribution Transformer code", examples=["DT-001"])
    geo: Optional[GeoLocation] = Field(None, description="Geographic coordinates")
    distance_km: Optional[float] = Field(None, description="Distance in kilometers from queried location (if proximity search)", examples=[1.24])


class MeterDetail(MeterSummary):
    """Comprehensive details for a smart meter including hierarchy and nameplate specifications."""
    hierarchy: Optional[NetworkHierarchy] = Field(None, description="Structured location in the electrical distribution grid")
    nameplate: List[NameplateParameter] = Field(default_factory=list, description="All nameplate parameters normalized from legacy portal")


class ConsumptionReading(BaseModel):
    """A single normalized smart meter telemetry interval reading."""
    timestamp: datetime = Field(..., description="Standard ISO-8601 UTC/local reading timestamp", examples=["2026-06-24T00:00:00"])
    raw_timestamp: str = Field(..., description="Original raw timestamp as formatted in the Urja portal", examples=["24/06/2026 00:00"])
    kwh: float = Field(..., description="Cumulative Active Energy in kWh", examples=[48439.16])
    kvah: float = Field(..., description="Cumulative Apparent Energy in kVAh", examples=[52314.29])
    volt_r: float = Field(..., description="R-Phase voltage in Volts (V)", examples=[229.0])


class ConsumptionSummary(BaseModel):
    """Aggregated analytical statistics computed over the interval readings."""
    total_readings: int = Field(..., description="Total number of reading intervals returned")
    start_time: Optional[datetime] = Field(None, description="Earliest reading timestamp in the window")
    end_time: Optional[datetime] = Field(None, description="Latest reading timestamp in the window")
    total_kwh_delta: Optional[float] = Field(None, description="Net active energy consumption across the window (kWh)")
    min_kwh: Optional[float] = Field(None, description="Minimum recorded cumulative kWh")
    max_kwh: Optional[float] = Field(None, description="Maximum recorded cumulative kWh")
    avg_voltage_r: Optional[float] = Field(None, description="Average R-phase voltage across all intervals")
    min_voltage_r: Optional[float] = Field(None, description="Minimum recorded R-phase voltage")
    max_voltage_r: Optional[float] = Field(None, description="Maximum recorded R-phase voltage")


class ConsumptionResponse(BaseModel):
    """Response containing smart meter interval consumption history and summary analytics."""
    meter_id: str = Field(..., description="Meter identifier", examples=["J100000"])
    summary: ConsumptionSummary = Field(..., description="Statistical summary for the queried window")
    readings: List[ConsumptionReading] = Field(default_factory=list, description="Chronological interval readings")


class Transformer(BaseModel):
    """Distribution Transformer (DT) metadata."""
    code: str = Field(..., description="Unique DT code", examples=["DT-001"])
    name: str = Field(..., description="DT descriptive name / location", examples=["Malviya Nagar DT 1"])
    feeder_code: str = Field(..., description="Parent feeder line code", examples=["F-001"])
    capacity_kva: float = Field(..., description="Transformer power capacity rating in kVA", examples=[100.0])


class PaginationMeta(BaseModel):
    """Standardized pagination metadata."""
    total: int = Field(..., description="Total items matching the query", examples=[403])
    page: int = Field(..., description="Current page number (1-indexed)", examples=[1])
    page_size: int = Field(..., description="Number of items per page", examples=[20])
    total_pages: int = Field(..., description="Total number of pages", examples=[21])


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic envelope for paginated response collections."""
    data: List[T] = Field(..., description="List of items for the requested page")
    pagination: PaginationMeta = Field(..., description="Pagination metadata")


class AnalyticsSummary(BaseModel):
    """Fleet-wide distribution operational statistics."""
    total_meters: int = Field(..., description="Total number of smart meters under management")
    total_transformers: int = Field(..., description="Total number of distribution transformers")
    total_capacity_kva: float = Field(..., description="Total distribution transformer capacity in kVA")
    status_breakdown: Dict[str, int] = Field(..., description="Meter count grouped by installation status")
    make_breakdown: Dict[str, int] = Field(..., description="Meter count grouped by manufacturer make")
    phase_breakdown: Dict[str, int] = Field(..., description="Meter count grouped by phase type")
    build_breakdown: Dict[str, int] = Field(..., description="Meter count grouped by telemetry build")


class HealthResponse(BaseModel):
    """System and upstream portal health status."""
    status: str = Field(..., description="Overall service status (healthy/degraded)", examples=["healthy"])
    portal_status: str = Field(..., description="Upstream Urja portal connectivity status", examples=["online"])
    authenticated: bool = Field(..., description="Whether a valid active session is held", examples=[True])
    cached_meters_count: int = Field(..., description="Number of meters currently indexed in cache", examples=[403])
    cached_transformers_count: int = Field(..., description="Number of transformers indexed in cache", examples=[40])
    cache_age_seconds: Optional[float] = Field(None, description="Age of the local cache in seconds")
