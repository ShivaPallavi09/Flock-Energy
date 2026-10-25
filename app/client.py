import hmac
import hashlib
import time
import json
import logging
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import dateutil.parser
import httpx
from bs4 import BeautifulSoup

from app.config import Settings, get_settings
from app.models import (
    ConsumptionReading,
    ConsumptionResponse,
    ConsumptionSummary,
    GeoLocation,
    HierarchyNode,
    MeterDetail,
    MeterSummary,
    NameplateParameter,
    NetworkHierarchy,
    Transformer,
)

logger = logging.getLogger("urja_client")
logger.setLevel(logging.INFO)


class UrjaPortalClient:
    """
    Robust HTTP Adapter layer for interacting with the legacy Urja Meter Ops portal.
    Handles session cookies, SvelteKit CSRF/Origin requirements, HMAC-SHA256 authenticated export,
    automatic re-authentication, and schema normalization across legacy and v2 meter models.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.base_url = self.settings.portal_base_url.rstrip("/")
        self.email = self.settings.portal_email
        self.password = self.settings.portal_password
        self.timeout = self.settings.request_timeout

        self._auth_lock = Lock()
        self._is_authenticated = False
        self._last_auth_time: Optional[float] = None

        # Headers required to satisfy SvelteKit CSRF / origin protection
        self.default_headers = {
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/login",
            "User-Agent": "FlockEnergy-UrjaAPI/1.0 (Integration Gateway; +https://flockenergy.tech)",
            "Accept": "application/json, text/html, */*",
        }

        # Persistent HTTP client with cookie jar
        self.http_client = httpx.Client(
            base_url=self.base_url,
            headers=self.default_headers,
            timeout=self.timeout,
            follow_redirects=False,  # We inspect redirects explicitly to catch session expiry
        )

    def login(self) -> bool:
        """
        Authenticate against the Urja portal login endpoint.
        SvelteKit uses Better-Auth session tokens and enforces Origin/Referer verification.
        """
        with self._auth_lock:
            login_url = "/login"
            payload = {
                "email": self.email,
                "password": self.password,
            }

            try:
                logger.info(f"Authenticating against {self.base_url}{login_url} as {self.email}...")
                response = self.http_client.post(
                    login_url,
                    data=payload,
                    headers={
                        "Origin": self.base_url,
                        "Referer": f"{self.base_url}/login",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )

                # SvelteKit returns 200 with JSON redirect or 303 redirect
                if response.status_code in (200, 302, 303):
                    # Check if session token cookie is stored
                    cookies = dict(self.http_client.cookies)
                    has_session = any("session_token" in k for k in cookies.keys())
                    if has_session or response.status_code == 200:
                        self._is_authenticated = True
                        self._last_auth_time = time.time()
                        logger.info("Successfully authenticated with Urja portal.")
                        return True

                logger.error(
                    f"Authentication failed with status {response.status_code}: {response.text[:200]}"
                )
                self._is_authenticated = False
                return False

            except Exception as exc:
                logger.error(f"Error during Urja portal authentication: {exc}")
                self._is_authenticated = False
                raise

    def _ensure_authenticated(self):
        """Ensure that the client currently holds an active session."""
        if not self._is_authenticated:
            success = self.login()
            if not success:
                raise RuntimeError("Failed to authenticate with the legacy Urja portal.")

    def _request_with_reauth(
        self, method: str, url: str, retry_on_auth_fail: bool = True, **kwargs
    ) -> httpx.Response:
        """
        Execute an HTTP request with automatic session re-authentication.
        Detects 401 Unauthorized or 302/303 Redirect to /login, re-authenticates, and retries.
        """
        self._ensure_authenticated()

        resp = self.http_client.request(method, url, **kwargs)

        # Detect session expiration (401 or redirect to login)
        is_session_expired = (
            resp.status_code == 401
            or (resp.status_code in (302, 303) and "/login" in resp.headers.get("location", ""))
        )

        if is_session_expired and retry_on_auth_fail:
            logger.warning(
                f"Session expired while calling {url} (status {resp.status_code}). Re-authenticating..."
            )
            self._is_authenticated = False
            self.login()
            # Retry request once
            return self.http_client.request(method, url, **kwargs)

        return resp

    # ==========================================
    # Portal Endpoints & Operations
    # ==========================================

    def get_signing_secret(self) -> str:
        """Fetch the cryptographic HMAC signing secret from /portal/keys."""
        resp = self._request_with_reauth("GET", "/portal/keys")
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch export signing secret: {resp.status_code} {resp.text}")
        data = resp.json()
        secret = data.get("data", {}).get("signingSecret")
        if not secret:
            raise ValueError(f"No signingSecret found in response: {data}")
        return secret

    def export_all_meters(self) -> List[Dict[str, Any]]:
        """
        Fetch the complete meter fleet using the signed export endpoint (/portal/export).
        Generates HMAC-SHA256 signature required by the legacy portal backend.
        """
        secret = self.get_signing_secret()
        timestamp = str(int(time.time()))
        query_str = "page=1"
        method = "GET"
        path = "/portal/export"

        # HMAC signature message specification: METHOD\nPATH\nQUERY\nTIMESTAMP
        message = f"{method}\n{path}\n{query_str}\n{timestamp}".encode("utf-8")
        signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()

        headers = {
            "x-timestamp": timestamp,
            "x-signature": signature,
        }

        resp = self._request_with_reauth("GET", f"{path}?{query_str}", headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"Export request failed with status {resp.status_code}: {resp.text}")

        data = resp.json()
        return data.get("data", [])

    def search_meters_live(self, query: str = "", page: int = 1) -> Tuple[List[Dict[str, Any]], int]:
        """
        Directly invoke the portal's search endpoint:
        GET /portal/meters/search?q={query}&page={page}
        """
        url = f"/portal/meters/search?q={query}&page={page}"
        resp = self._request_with_reauth("GET", url)
        if resp.status_code != 200:
            raise RuntimeError(f"Meters search failed: {resp.status_code} {resp.text}")

        res = resp.json()
        return res.get("data", []), res.get("total", 0)

    def get_transformers_page(self, page: int = 1) -> Tuple[List[Transformer], int]:
        """
        Fetch a page of distribution transformers:
        GET /portal/dts?page={page}
        """
        url = f"/portal/dts?page={page}"
        resp = self._request_with_reauth("GET", url)
        if resp.status_code != 200:
            raise RuntimeError(f"Transformers fetch failed: {resp.status_code} {resp.text}")

        res = resp.json()
        raw_items = res.get("data", [])
        total = res.get("total", 0)

        transformers = [
            Transformer(
                code=item["code"],
                name=item["name"],
                feeder_code=item.get("feederCode", ""),
                capacity_kva=float(item.get("capacityKva", 0.0)),
            )
            for item in raw_items
        ]
        return transformers, total

    def get_all_transformers(self) -> List[Transformer]:
        """Fetch all distribution transformers across all pages."""
        transformers = []
        page = 1
        page_size = 20

        first_page, total = self.get_transformers_page(page=1)
        transformers.extend(first_page)

        total_pages = (total + page_size - 1) // page_size if total > 0 else 1
        for p in range(2, total_pages + 1):
            page_data, _ = self.get_transformers_page(page=p)
            transformers.extend(page_data)

        return transformers

    def get_meter_geo(self, meter_id: str) -> Optional[GeoLocation]:
        """
        Retrieve geographic coordinates for a given meter:
        GET /portal/meters/{meter_id}/geo
        """
        url = f"/portal/meters/{meter_id}/geo"
        resp = self._request_with_reauth("GET", url)

        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch meter geo: {resp.status_code} {resp.text}")

        data = resp.json().get("data", {})
        if not data:
            return None

        try:
            return GeoLocation(
                latitude=float(data.get("latitude")),
                longitude=float(data.get("longitude")),
            )
        except (TypeError, ValueError):
            return None

    def get_meter_energy(
        self,
        meter_id: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> ConsumptionResponse:
        """
        Fetch and normalize interval consumption telemetry for a given meter:
        GET /portal/meters/{meter_id}/energy?from={from}&to={to}
        """
        params = {}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        url = f"/portal/meters/{meter_id}/energy"
        resp = self._request_with_reauth("GET", url, params=params)

        if resp.status_code == 404:
            raise KeyError(f"Meter with ID '{meter_id}' not found.")
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch meter energy: {resp.status_code} {resp.text}")

        raw_readings = resp.json().get("data", [])
        normalized_readings: List[ConsumptionReading] = []

        total_kwh_values: List[float] = []
        volt_values: List[float] = []

        for item in raw_readings:
            raw_ts = item.get("timestamp", "")
            # Legacy format is "DD/MM/YYYY HH:MM"
            parsed_dt = None
            try:
                # dateutil parses dayfirst=True for DD/MM/YYYY format
                parsed_dt = dateutil.parser.parse(raw_ts, dayfirst=True)
            except Exception:
                try:
                    parsed_dt = datetime.strptime(raw_ts, "%d/%m/%Y %H:%M")
                except Exception:
                    parsed_dt = datetime.utcnow()

            # Normalize numeric fields from string
            kwh = float(item.get("kwh", 0.0) or 0.0)
            kvah = float(item.get("kvah", 0.0) or 0.0)
            volt_r = float(item.get("voltR", 0.0) or 0.0)

            total_kwh_values.append(kwh)
            if volt_r > 0:
                volt_values.append(volt_r)

            normalized_readings.append(
                ConsumptionReading(
                    timestamp=parsed_dt,
                    raw_timestamp=raw_ts,
                    kwh=kwh,
                    kvah=kvah,
                    volt_r=volt_r,
                )
            )

        # Sort chronologically
        normalized_readings.sort(key=lambda x: x.timestamp)

        # Compute summary statistics
        total_readings = len(normalized_readings)
        start_time = normalized_readings[0].timestamp if normalized_readings else None
        end_time = normalized_readings[-1].timestamp if normalized_readings else None
        
        min_kwh = min(total_kwh_values) if total_kwh_values else None
        max_kwh = max(total_kwh_values) if total_kwh_values else None
        kwh_delta = (max_kwh - min_kwh) if (max_kwh is not None and min_kwh is not None) else None

        avg_volt = (sum(volt_values) / len(volt_values)) if volt_values else None
        min_volt = min(volt_values) if volt_values else None
        max_volt = max(volt_values) if volt_values else None

        summary = ConsumptionSummary(
            total_readings=total_readings,
            start_time=start_time,
            end_time=end_time,
            total_kwh_delta=round(kwh_delta, 2) if kwh_delta is not None else None,
            min_kwh=min_kwh,
            max_kwh=max_kwh,
            avg_voltage_r=round(avg_volt, 2) if avg_volt is not None else None,
            min_voltage_r=min_volt,
            max_voltage_r=max_volt,
        )

        return ConsumptionResponse(
            meter_id=meter_id,
            summary=summary,
            readings=normalized_readings,
        )

    def fetch_meter_html_fallback(self, meter_id: str) -> Optional[MeterDetail]:
        """
        Fallback parser: retrieves /meters/{meter_id} HTML and parses with BeautifulSoup.
        Used to verify or augment data when direct JSON endpoints are bypassed.
        """
        url = f"/meters/{meter_id}"
        resp = self._request_with_reauth("GET", url)

        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        h1 = soup.find("h1")
        if not h1 or "Meter" not in h1.text:
            return None

        # Parse Nameplate parameters from <dl>
        nameplate_params: List[NameplateParameter] = []
        dts = soup.find_all("dt")
        dds = soup.find_all("dd")
        attr_map = {}
        for dt, dd in zip(dts, dds):
            label = dt.get_text(strip=True)
            val = dd.get_text(strip=True)
            nameplate_params.append(NameplateParameter(label=label, value=val))
            attr_map[label.lower()] = val

        # Parse Hierarchy Breadcrumbs from <nav>
        hierarchy_obj = None
        nav = soup.find("nav", class_=lambda c: c and "gap-1" in c)
        if nav:
            crumb_spans = [
                s.get_text(strip=True)
                for s in nav.find_all("span")
                if s.get_text(strip=True) and s.get_text(strip=True) != "›"
            ]
            # Standard order: Zone, Circle, Division, Subdivision, Substation, Feeder, DT
            def parse_crumb(raw: str) -> Optional[HierarchyNode]:
                if not raw:
                    return None
                if "(" in raw and raw.endswith(")"):
                    name, code_part = raw.rsplit("(", 1)
                    return HierarchyNode(name=name.strip(), code=code_part.rstrip(")"))
                return HierarchyNode(name=raw.strip(), code=raw.strip())

            nodes = [parse_crumb(c) for c in crumb_spans]
            hierarchy_obj = NetworkHierarchy(
                zone=nodes[0] if len(nodes) > 0 else None,
                circle=nodes[1] if len(nodes) > 1 else None,
                division=nodes[2] if len(nodes) > 2 else None,
                subdivision=nodes[3] if len(nodes) > 3 else None,
                substation=nodes[4] if len(nodes) > 4 else None,
                feeder=nodes[5] if len(nodes) > 5 else None,
                dt=nodes[6] if len(nodes) > 6 else None,
            )

        serial_number = attr_map.get("serial no", attr_map.get("serial", "UNKNOWN"))
        make = attr_map.get("make", "UNKNOWN")
        phase_type = attr_map.get("phase type", attr_map.get("phase", "single"))
        install_status = attr_map.get("installation status", attr_map.get("status", "Installed"))
        install_type = attr_map.get("installation type", "Whole Current")

        geo = self.get_meter_geo(meter_id)

        return MeterDetail(
            meter_id=meter_id,
            serial_number=serial_number,
            make=make,
            phase_type=phase_type,
            install_status=install_status,
            install_type=install_type,
            dt_code=hierarchy_obj.dt.code if (hierarchy_obj and hierarchy_obj.dt) else None,
            geo=geo,
            hierarchy=hierarchy_obj,
            nameplate=nameplate_params,
        )

    def check_health(self) -> Dict[str, Any]:
        """Verify connectivity to Urja portal and check session status."""
        try:
            resp = self.http_client.get("/login", timeout=5.0)
            portal_online = resp.status_code == 200
        except Exception:
            portal_online = False

        return {
            "portal_online": portal_online,
            "authenticated": self._is_authenticated,
            "last_auth_time": self._last_auth_time,
        }
