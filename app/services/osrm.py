"""
GIO Telemetry — OSRM Proxy with LRU In-Memory Cache
Routes requests through our backend to avoid CORS and adds caching.
"""
import hashlib
import time
import threading

import requests


class OSRMProxy:
    """Proxy OSRM requests with an in-memory LRU cache."""

    def __init__(self, base_url='https://router.project-osrm.org', cache_ttl=300, max_cache=200):
        self._base_url = base_url.rstrip('/')
        self._cache_ttl = cache_ttl  # seconds
        self._max_cache = max_cache
        self._cache = {}  # key -> { data, timestamp }
        self._lock = threading.Lock()

    @staticmethod
    def normalize_method(method):
        safe = (method or 'route').strip().lower()
        if safe not in ('route', 'match'):
            return 'route'
        return safe

    def get_route(self, coords_string, method='route'):
        """
        Get an OSRM route/match for the given coordinates string.
        coords_string: "lon1,lat1;lon2,lat2;..."
        method: "route" or "match"
        Returns: dict with OSRM response or None on failure.
        """
        safe_method = self.normalize_method(method)
        cache_key = self._make_key(coords_string, safe_method)

        # Check cache
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and (time.time() - cached['timestamp']) < self._cache_ttl:
                return cached['data']

        # Fetch from OSRM
        if safe_method == 'match':
            url = (
                f"{self._base_url}/match/v1/driving/{coords_string}"
                "?overview=full&geometries=geojson&gaps=ignore&tidy=true"
            )
        else:
            url = f"{self._base_url}/route/v1/driving/{coords_string}?overview=full&geometries=geojson"
        try:
            resp = requests.get(url, timeout=8)
            resp.raise_for_status()
            data = resp.json()

            if data.get('code') == 'Ok':
                # Cache the successful result
                with self._lock:
                    self._evict_if_needed()
                    self._cache[cache_key] = {
                        'data': data,
                        'timestamp': time.time(),
                    }
                return data
            return None
        except Exception as e:
            print(f"[OSRM] Error: {e}")
            return None

    def _make_key(self, coords_string, method):
        """Create a cache key from method+coordinates."""
        return hashlib.md5(f"{method}|{coords_string}".encode()).hexdigest()

    def _evict_if_needed(self):
        """Evict oldest entries if cache is full. Must be called with lock held."""
        if len(self._cache) >= self._max_cache:
            # Remove the oldest 25% of entries
            sorted_keys = sorted(
                self._cache.keys(),
                key=lambda k: self._cache[k]['timestamp'],
            )
            to_remove = len(sorted_keys) // 4 or 1
            for key in sorted_keys[:to_remove]:
                del self._cache[key]

    def clear_cache(self):
        """Clear the entire route cache."""
        with self._lock:
            self._cache.clear()

    @property
    def cache_size(self):
        return len(self._cache)
