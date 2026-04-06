"""
GIO Telemetry — Stats Cache Service
Refreshes aggregate stats every N seconds in a background thread
instead of querying on every request.
"""
import threading

from app.config import Config


class StatsCache:
    """Background thread that refreshes DB stats periodically."""

    def __init__(self):
        self._data = {
            'total_records': 0,
            'first_record': None,
            'last_record': None,
        }
        self._lock = threading.Lock()
        self._timer = None
        self._interval = Config.STATS_CACHE_INTERVAL
        self._running = False

    def start(self):
        """Start the background refresh loop."""
        self._running = True
        self._refresh()

    def stop(self):
        """Stop the background refresh loop."""
        self._running = False
        if self._timer:
            self._timer.cancel()

    def get(self):
        """Get the current cached stats (thread-safe)."""
        with self._lock:
            return dict(self._data)

    def _refresh(self):
        """Refresh stats from the database."""
        if not self._running:
            return
        try:
            from app.database import fetch_stats
            fresh = fetch_stats()
            with self._lock:
                self._data = fresh
        except Exception as e:
            print(f"[STATS] Error refreshing: {e}")
        finally:
            # Schedule next refresh
            if self._running:
                self._timer = threading.Timer(self._interval, self._refresh)
                self._timer.daemon = True
                self._timer.start()
