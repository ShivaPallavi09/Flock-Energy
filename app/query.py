import math
from typing import Any, Dict, List, Optional, Tuple
from app.models import (
    AnalyticsSummary,
    GeoLocation,
    HierarchyNode,
    MeterDetail,
    MeterSummary,
    NameplateParameter,
    NetworkHierarchy,
    PaginationMeta,
    Transformer,
)


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great-circle distance between two points on the Earth in kilometers
    using the Haversine formula.
    """
    R = 6371.0  # Earth's radius in kilometers
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(R * c, 3)


def normalize_exported_meter(raw: Dict[str, Any]) -> MeterDetail:
    """
    Normalize raw meter JSON dictionary from /portal/export into standardized MeterDetail model.
    Handles legacy vs v2 build differences and standardizes fields.
    """
    meter_id = raw.get("meterId") or raw.get("meter_id", "UNKNOWN")
    serial_no = raw.get("serialNo") or raw.get("serial_number", "UNKNOWN")
    make = raw.get("make", "UNKNOWN")
    phase_type = raw.get("phaseType", "single")
    install_status = raw.get("installStatus", "Installed")
    install_type = raw.get("installType")
    build = raw.get("build")
    dt_code = raw.get("dtCode")

    # Normalize Geo coordinates
    geo = None
    raw_geo = raw.get("geo")
    if raw_geo and "lat" in raw_geo and "lng" in raw_geo:
        try:
            geo = GeoLocation(
                latitude=float(raw_geo["lat"]),
                longitude=float(raw_geo["lng"]),
            )
        except (ValueError, TypeError):
            geo = None

    # Normalize Hierarchy structure
    hierarchy_obj = None
    raw_hier = raw.get("hierarchy")
    if raw_hier and isinstance(raw_hier, dict):
        def parse_node(k: str) -> Optional[HierarchyNode]:
            item = raw_hier.get(k)
            if item and isinstance(item, dict) and "name" in item and "code" in item:
                return HierarchyNode(name=item["name"], code=item["code"])
            return None

        hierarchy_obj = NetworkHierarchy(
            zone=parse_node("zone"),
            circle=parse_node("circle"),
            division=parse_node("division"),
            subdivision=parse_node("subdivision"),
            substation=parse_node("substation"),
            feeder=parse_node("feeder"),
            dt=parse_node("dt"),
        )

    # Build standardized nameplate parameter list
    nameplate: List[NameplateParameter] = [
        NameplateParameter(label="Meter ID", value=meter_id),
        NameplateParameter(label="Serial Number", value=serial_no),
        NameplateParameter(label="Make", value=make),
        NameplateParameter(label="Phase Type", value=phase_type),
        NameplateParameter(label="Installation Status", value=install_status),
    ]
    if install_type:
        nameplate.append(NameplateParameter(label="Installation Type", value=install_type))
    if dt_code:
        nameplate.append(NameplateParameter(label="DT Code", value=dt_code))
    if build:
        nameplate.append(NameplateParameter(label="Telemetry Build", value=build))

    return MeterDetail(
        meter_id=meter_id,
        serial_number=serial_no,
        make=make,
        phase_type=phase_type,
        install_status=install_status,
        install_type=install_type,
        build=build,
        dt_code=dt_code,
        geo=geo,
        hierarchy=hierarchy_obj,
        nameplate=nameplate,
    )


class QueryEngine:
    """
    In-memory spatial and relational query engine.
    Allows fast multi-attribute filtering, geo-proximity queries, network tree construction,
    and fleet summary aggregation over the cached meter dataset.
    """

    @staticmethod
    def filter_meters(
        meters: List[MeterDetail],
        search: Optional[str] = None,
        status: Optional[str] = None,
        make: Optional[str] = None,
        phase_type: Optional[str] = None,
        dt_code: Optional[str] = None,
        feeder_code: Optional[str] = None,
        zone_code: Optional[str] = None,
        near_lat: Optional[float] = None,
        near_lng: Optional[float] = None,
        radius_km: Optional[float] = None,
    ) -> List[MeterDetail]:
        """Apply filters and spatial proximity calculations to meter collection."""
        results: List[Tuple[MeterDetail, Optional[float]]] = []

        q_lower = search.strip().lower() if search else None
        status_lower = status.strip().lower() if status else None
        make_lower = make.strip().lower() if make else None
        phase_lower = phase_type.strip().lower() if phase_type else None
        dt_lower = dt_code.strip().lower() if dt_code else None
        feeder_lower = feeder_code.strip().lower() if feeder_code else None
        zone_lower = zone_code.strip().lower() if zone_code else None

        for m in meters:
            # Text search on meter_id or serial_number
            if q_lower:
                if q_lower not in m.meter_id.lower() and q_lower not in m.serial_number.lower():
                    continue

            # Exact or case-insensitive attribute filters
            if status_lower and m.install_status.lower() != status_lower:
                continue

            if make_lower and m.make.lower() != make_lower:
                continue

            if phase_lower and m.phase_type.lower() != phase_lower:
                continue

            if dt_lower and (not m.dt_code or m.dt_code.lower() != dt_lower):
                continue

            if feeder_lower:
                m_feeder = m.hierarchy.feeder.code if (m.hierarchy and m.hierarchy.feeder) else None
                if not m_feeder or m_feeder.lower() != feeder_lower:
                    continue

            if zone_lower:
                m_zone = m.hierarchy.zone.code if (m.hierarchy and m.hierarchy.zone) else None
                if not m_zone or m_zone.lower() != zone_lower:
                    continue

            # Spatial distance filter (Haversine proximity)
            dist = None
            if near_lat is not None and near_lng is not None:
                if not m.geo:
                    continue  # Exclude meters without coordinates if proximity search is requested
                dist = haversine_distance(near_lat, near_lng, m.geo.latitude, m.geo.longitude)
                if radius_km is not None and dist > radius_km:
                    continue

            results.append((m, dist))

        # Sort: if spatial proximity was queried, sort by distance ascending
        if near_lat is not None and near_lng is not None:
            results.sort(key=lambda x: x[1] if x[1] is not None else float("inf"))

        # Attach distance_km to MeterDetail
        output: List[MeterDetail] = []
        for m, dist in results:
            if dist is not None:
                m_copy = m.model_copy()
                m_copy.distance_km = dist
                output.append(m_copy)
            else:
                output.append(m)

        return output

    @staticmethod
    def paginate(items: List[Any], page: int = 1, page_size: int = 20) -> Tuple[List[Any], PaginationMeta]:
        """Slice collection into requested page and produce standardized PaginationMeta."""
        page = max(1, page)
        page_size = max(1, min(page_size, 500))  # Cap page size between 1 and 500
        total = len(items)
        total_pages = math.ceil(total / page_size) if total > 0 else 1

        offset = (page - 1) * page_size
        sliced_items = items[offset : offset + page_size]

        meta = PaginationMeta(
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )
        return sliced_items, meta

    @staticmethod
    def build_network_tree(meters: List[MeterDetail], transformers: List[Transformer]) -> Dict[str, Any]:
        """
        Reconstruct the full electrical distribution network hierarchy from meter and DT datasets:
        Discom -> Zone -> Circle -> Division -> Subdivision -> Substation -> Feeder -> DT -> Meters
        """
        tree: Dict[str, Any] = {
            "name": "Urja Distribution Network",
            "type": "root",
            "zones": {},
        }

        # Build lookup for DT details
        dt_map = {dt.code: dt for dt in transformers}

        for m in meters:
            if not m.hierarchy:
                continue

            h = m.hierarchy
            zone_key = h.zone.code if h.zone else "UNKNOWN_ZONE"
            zone_name = h.zone.name if h.zone else "Unknown Zone"

            circle_key = h.circle.code if h.circle else "UNKNOWN_CIRCLE"
            circle_name = h.circle.name if h.circle else "Unknown Circle"

            div_key = h.division.code if h.division else "UNKNOWN_DIV"
            div_name = h.division.name if h.division else "Unknown Division"

            subdiv_key = h.subdivision.code if h.subdivision else "UNKNOWN_SUBDIV"
            subdiv_name = h.subdivision.name if h.subdivision else "Unknown Subdivision"

            substation_key = h.substation.code if h.substation else "UNKNOWN_SUBSTATION"
            substation_name = h.substation.name if h.substation else "Unknown Substation"

            feeder_key = h.feeder.code if h.feeder else "UNKNOWN_FEEDER"
            feeder_name = h.feeder.name if h.feeder else "Unknown Feeder"

            dt_key = h.dt.code if h.dt else (m.dt_code or "UNKNOWN_DT")
            dt_name = h.dt.name if h.dt else (dt_map[dt_key].name if dt_key in dt_map else dt_key)

            # Traverse / populate tree
            zones = tree["zones"]
            if zone_key not in zones:
                zones[zone_key] = {"code": zone_key, "name": zone_name, "circles": {}}

            circles = zones[zone_key]["circles"]
            if circle_key not in circles:
                circles[circle_key] = {"code": circle_key, "name": circle_name, "divisions": {}}

            divisions = circles[circle_key]["divisions"]
            if div_key not in divisions:
                divisions[div_key] = {"code": div_key, "name": div_name, "subdivisions": {}}

            subdivisions = divisions[div_key]["subdivisions"]
            if subdiv_key not in subdivisions:
                subdivisions[subdiv_key] = {"code": subdiv_key, "name": subdiv_name, "substations": {}}

            substations = subdivisions[subdiv_key]["substations"]
            if substation_key not in substations:
                substations[substation_key] = {"code": substation_key, "name": substation_name, "feeders": {}}

            feeders = substations[substation_key]["feeders"]
            if feeder_key not in feeders:
                feeders[feeder_key] = {"code": feeder_key, "name": feeder_name, "transformers": {}}

            dts = feeders[feeder_key]["transformers"]
            if dt_key not in dts:
                capacity = dt_map[dt_key].capacity_kva if dt_key in dt_map else None
                dts[dt_key] = {
                    "code": dt_key,
                    "name": dt_name,
                    "capacity_kva": capacity,
                    "meters": [],
                }

            dts[dt_key]["meters"].append({
                "meter_id": m.meter_id,
                "serial_number": m.serial_number,
                "make": m.make,
                "phase_type": m.phase_type,
                "install_status": m.install_status,
                "geo": {"lat": m.geo.latitude, "lng": m.geo.longitude} if m.geo else None,
            })

        return tree

    @staticmethod
    def compute_analytics(meters: List[MeterDetail], transformers: List[Transformer]) -> AnalyticsSummary:
        """Compute aggregated operational metrics over the meter fleet."""
        status_counts: Dict[str, int] = {}
        make_counts: Dict[str, int] = {}
        phase_counts: Dict[str, int] = {}
        build_counts: Dict[str, int] = {}

        for m in meters:
            status_counts[m.install_status] = status_counts.get(m.install_status, 0) + 1
            make_counts[m.make] = make_counts.get(m.make, 0) + 1
            phase_counts[m.phase_type] = phase_counts.get(m.phase_type, 0) + 1
            b = m.build or "unknown"
            build_counts[b] = build_counts.get(b, 0) + 1

        total_cap = sum(t.capacity_kva for t in transformers)

        return AnalyticsSummary(
            total_meters=len(meters),
            total_transformers=len(transformers),
            total_capacity_kva=round(total_cap, 2),
            status_breakdown=status_counts,
            make_breakdown=make_counts,
            phase_breakdown=phase_counts,
            build_breakdown=build_counts,
        )
