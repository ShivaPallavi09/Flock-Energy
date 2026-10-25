import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoints():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "portal_status" in data
    assert "cached_meters_count" in data


def test_login_endpoint():
    response = client.post("/api/v1/auth/login")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "authenticated"


def test_list_meters():
    response = client.get("/api/v1/meters?page=1&page_size=10")
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "pagination" in data
    assert len(data["data"]) <= 10
    assert data["pagination"]["page"] == 1
    assert data["pagination"]["total"] > 0

    first_meter = data["data"][0]
    assert "meter_id" in first_meter
    assert "serial_number" in first_meter
    assert "make" in first_meter
    assert "phase_type" in first_meter


def test_filter_meters_by_search():
    response = client.get("/api/v1/meters?search=J100000")
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) >= 1
    assert data["data"][0]["meter_id"] == "J100000"


def test_filter_meters_by_status():
    response = client.get("/api/v1/meters?status=Installed")
    assert response.status_code == 200
    data = response.json()
    for m in data["data"]:
        assert m["install_status"] == "Installed"


def test_spatial_proximity_search():
    # Jaipur center: 26.938961, 75.830957
    response = client.get("/api/v1/meters?near_lat=26.938961&near_lng=75.830957&radius_km=10.0")
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) > 0
    # First item should be very close (< 1 km)
    assert data["data"][0]["distance_km"] is not None
    assert data["data"][0]["distance_km"] < 1.0


def test_get_meter_detail_success():
    response = client.get("/api/v1/meters/J100000")
    assert response.status_code == 200
    data = response.json()
    assert data["meter_id"] == "J100000"
    assert "hierarchy" in data
    assert "nameplate" in data
    assert len(data["nameplate"]) > 0


def test_get_meter_detail_404():
    response = client.get("/api/v1/meters/NON_EXISTENT_METER_XYZ")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data


def test_get_meter_consumption():
    response = client.get("/api/v1/meters/J100000/consumption")
    assert response.status_code == 200
    data = response.json()
    assert data["meter_id"] == "J100000"
    assert "summary" in data
    assert "readings" in data
    assert data["summary"]["total_readings"] > 0

    first_reading = data["readings"][0]
    assert "timestamp" in first_reading
    assert "kwh" in first_reading
    assert "volt_r" in first_reading
    assert isinstance(first_reading["kwh"], float)


def test_get_meter_consumption_date_filter():
    response = client.get("/api/v1/meters/J100000/consumption?from_date=2026-06-24&to_date=2026-06-25")
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["total_readings"] == 96


def test_transformers_endpoints():
    response = client.get("/api/v1/transformers?page=1&page_size=5")
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 5
    assert data["pagination"]["total"] == 40

    first_dt = data["data"][0]["code"]
    dt_resp = client.get(f"/api/v1/transformers/{first_dt}")
    assert dt_resp.status_code == 200
    assert dt_resp.json()["code"] == first_dt


def test_hierarchy_endpoint():
    response = client.get("/api/v1/hierarchy")
    assert response.status_code == 200
    data = response.json()
    assert "zones" in data
    assert len(data["zones"]) > 0


def test_analytics_summary():
    response = client.get("/api/v1/analytics/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["total_meters"] == 403
    assert data["total_transformers"] == 40
    assert "status_breakdown" in data
    assert "make_breakdown" in data
    assert "phase_breakdown" in data


def test_dashboard_page():
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "Flock Energy" in response.text
    assert "text/html" in response.headers["content-type"]
