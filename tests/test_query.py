import pytest
from app.models import GeoLocation, HierarchyNode, MeterDetail, NetworkHierarchy, Transformer
from app.query import (
    QueryEngine,
    haversine_distance,
    normalize_exported_meter,
)


def test_haversine_distance():
    # Distance between Jaipur central (26.9124, 75.7873) and Malviya Nagar (26.8524, 75.8143) is ~7.1 km
    dist = haversine_distance(26.9124, 75.7873, 26.8524, 75.8143)
    assert 6.5 < dist < 7.5
    # Distance from point to itself is 0
    assert haversine_distance(26.9124, 75.7873, 26.9124, 75.7873) == 0.0


def test_normalize_legacy_meter():
    raw = {
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
            "dt": {"name": "Malviya Nagar DT 1", "code": "DT-001"},
        },
        "geo": {"lat": 26.938961, "lng": 75.830957},
    }

    meter = normalize_exported_meter(raw)
    assert meter.meter_id == "J100000"
    assert meter.serial_number == "SE33962"
    assert meter.make == "HPL"
    assert meter.phase_type == "single"
    assert meter.install_status == "Decommissioned"
    assert meter.dt_code == "DT-001"
    assert meter.geo.latitude == 26.938961
    assert meter.geo.longitude == 75.830957
    assert meter.hierarchy.zone.code == "Z-01"
    assert meter.hierarchy.feeder.code == "F-001"
    assert len(meter.nameplate) >= 5


def test_normalize_v2_meter():
    raw = {
        "meterId": "J100004",
        "serialNo": "SE65293",
        "make": "Genus",
        "phaseType": "single",
        "installStatus": "Faulty",
        "installType": "CT Operated",
        "build": "v2",
        "dtCode": "DT-005",
        "hierarchy": {
            "zone": {"name": "Jaipur Zone 2", "code": "Z-02"},
            "dt": {"name": "Bani Park DT 5", "code": "DT-005"},
        },
        "geo": {"lat": 26.920, "lng": 75.790},
    }

    meter = normalize_exported_meter(raw)
    assert meter.meter_id == "J100004"
    assert meter.build == "v2"
    assert meter.install_type == "CT Operated"
    assert meter.hierarchy.zone.name == "Jaipur Zone 2"


def test_filter_meters():
    m1 = MeterDetail(
        meter_id="J100001",
        serial_number="GE84132",
        make="L&T",
        phase_type="single",
        install_status="Installed",
        dt_code="DT-001",
        geo=GeoLocation(latitude=26.9389, longitude=75.8309),
    )
    m2 = MeterDetail(
        meter_id="J100002",
        serial_number="SE99999",
        make="Genus",
        phase_type="three",
        install_status="Faulty",
        dt_code="DT-002",
        geo=GeoLocation(latitude=28.7041, longitude=77.1025),  # Delhi, far away
    )

    meters = [m1, m2]

    # Search filter
    res = QueryEngine.filter_meters(meters, search="GE84")
    assert len(res) == 1
    assert res[0].meter_id == "J100001"

    # Status filter
    res = QueryEngine.filter_meters(meters, status="Faulty")
    assert len(res) == 1
    assert res[0].meter_id == "J100002"

    # Make filter
    res = QueryEngine.filter_meters(meters, make="L&T")
    assert len(res) == 1
    assert res[0].meter_id == "J100001"

    # Phase filter
    res = QueryEngine.filter_meters(meters, phase_type="three")
    assert len(res) == 1
    assert res[0].meter_id == "J100002"

    # Spatial proximity search around Jaipur (radius 10 km)
    res = QueryEngine.filter_meters(
        meters, near_lat=26.9389, near_lng=75.8309, radius_km=10.0
    )
    assert len(res) == 1
    assert res[0].meter_id == "J100001"
    assert res[0].distance_km is not None
    assert res[0].distance_km < 1.0


def test_pagination():
    items = list(range(100))
    sliced, meta = QueryEngine.paginate(items, page=1, page_size=20)
    assert len(sliced) == 20
    assert sliced[0] == 0
    assert meta.total == 100
    assert meta.page == 1
    assert meta.total_pages == 5

    sliced_p5, meta_p5 = QueryEngine.paginate(items, page=5, page_size=20)
    assert len(sliced_p5) == 20
    assert sliced_p5[-1] == 99


def test_build_network_tree():
    m = MeterDetail(
        meter_id="J100001",
        serial_number="GE84132",
        make="L&T",
        phase_type="single",
        install_status="Installed",
        dt_code="DT-001",
        hierarchy=NetworkHierarchy(
            zone=HierarchyNode(name="Jaipur Zone 1", code="Z-01"),
            circle=HierarchyNode(name="Circle 1", code="C-01"),
            feeder=HierarchyNode(name="Feeder 1", code="F-001"),
            dt=HierarchyNode(name="Malviya Nagar DT 1", code="DT-001"),
        ),
    )
    transformer = Transformer(
        code="DT-001",
        name="Malviya Nagar DT 1",
        feeder_code="F-001",
        capacity_kva=100.0,
    )

    tree = QueryEngine.build_network_tree([m], [transformer])
    assert "zones" in tree
    assert "Z-01" in tree["zones"]
    zone = tree["zones"]["Z-01"]
    assert "C-01" in zone["circles"]
