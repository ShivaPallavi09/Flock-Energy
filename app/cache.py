import time
import logging
from threading import Lock
from typing import Any, Dict, List, Optional
from app.client import UrjaPortalClient
from app.config import Settings, get_settings
from app.models import MeterDetail, Transformer
from app.query import normalize_exported_meter

logger = logging.getLogger("urja_cache")
logger.setLevel(logging.INFO)


class FleetCache:
    """
    In-memory cache manager for the Urja smart meter fleet and transformers.
    Maintains pre-indexed lookup maps, handles TTL staleness, and performs
    thread-safe atomic refreshes using the HMAC-authenticated bulk export endpoint.
    """

    def __init__(self, client: UrjaPortalClient, settings: Optional[Settings] = None):
        self.client = client
        self.settings = settings or get_settings()
        self.ttl_seconds = self.settings.cache_ttl_seconds

        self._lock = Lock()
        self._meters_by_id: Dict[str, MeterDetail] = {}
        self._transformers_by_code: Dict[str, Transformer] = {}
        self._last_refreshed: Optional[float] = None
        self._is_loading: bool = False

    @property
    def is_stale(self) -> bool:
        """Check if the cache has expired past its TTL or has never been populated."""
        if self._last_refreshed is None:
            return True
        return (time.time() - self._last_refreshed) > self.ttl_seconds

    @property
    def age_seconds(self) -> Optional[float]:
        """Return the age of the current cache in seconds."""
        if self._last_refreshed is None:
            return None
        return round(time.time() - self._last_refreshed, 1)

    def refresh(self, force: bool = False) -> bool:
        """
        Refresh the in-memory cache by downloading all meters via the signed export endpoint
        and all transformers. Thread-safe with atomic dictionary swap.
        """
        with self._lock:
            # Check if another thread refreshed while waiting for lock
            if not force and not self.is_stale:
                return False

            logger.info("Refreshing Urja fleet cache from upstream portal...")
            try:
                # 1. Fetch all meters using HMAC signed export endpoint
                raw_meters = self.client.export_all_meters()
                new_meters_map: Dict[str, MeterDetail] = {}
                for raw_m in raw_meters:
                    detail = normalize_exported_meter(raw_m)
                    new_meters_map[detail.meter_id] = detail

                # 2. Fetch all transformers
                new_transformers = self.client.get_all_transformers()
                new_dts_map = {dt.code: dt for dt in new_transformers}

                # Atomic swap
                self._meters_by_id = new_meters_map
                self._transformers_by_code = new_dts_map
                self._last_refreshed = time.time()

                logger.info(
                    f"Urja fleet cache refreshed: {len(self._meters_by_id)} meters, "
                    f"{len(self._transformers_by_code)} transformers indexed."
                )
                return True

            except Exception as e:
                logger.error(f"Failed to refresh fleet cache: {e}")
                # If we have existing data, keep it; if not, re-raise
                if not self._meters_by_id:
                    raise
                return False

    def get_all_meters(self) -> List[MeterDetail]:
        """Return all cached meters, triggering a refresh if stale."""
        if self.is_stale:
            try:
                self.refresh()
            except Exception as e:
                logger.warning(f"Background refresh failed, serving stale data: {e}")
        return list(self._meters_by_id.values())

    def get_meter(self, meter_id: str) -> Optional[MeterDetail]:
        """Retrieve a specific meter by ID from cache or fallback to live portal."""
        if self.is_stale:
            try:
                self.refresh()
            except Exception as e:
                logger.warning(f"Background refresh failed, serving stale data: {e}")

        # Check in cache
        if meter_id in self._meters_by_id:
            return self._meters_by_id[meter_id]

        # Fallback: meter might have been newly added or not in export
        logger.info(f"Meter {meter_id} not in cache, attempting live fallback fetch...")
        fallback_meter = self.client.fetch_meter_html_fallback(meter_id)
        if fallback_meter:
            with self._lock:
                self._meters_by_id[meter_id] = fallback_meter
            return fallback_meter

        return None

    def get_all_transformers(self) -> List[Transformer]:
        """Return all cached transformers."""
        if self.is_stale:
            try:
                self.refresh()
            except Exception as e:
                logger.warning(f"Background refresh failed, serving stale data: {e}")
        return list(self._transformers_by_code.values())

    def get_transformer(self, code: str) -> Optional[Transformer]:
        """Get transformer by its code."""
        if self.is_stale:
            try:
                self.refresh()
            except Exception as e:
                logger.warning(f"Background refresh failed, serving stale data: {e}")
        return self._transformers_by_code.get(code)

    def stats(self) -> Dict[str, Any]:
        """Return cache health and index diagnostics."""
        return {
            "cached_meters_count": len(self._meters_by_id),
            "cached_transformers_count": len(self._transformers_by_code),
            "is_stale": self.is_stale,
            "cache_age_seconds": self.age_seconds,
            "ttl_seconds": self.ttl_seconds,
        }
