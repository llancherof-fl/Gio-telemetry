/**
 * GIO Telemetry — Real-Time Module
 * Smart polling with change detection, visibility API, and exponential backoff.
 */

var markerRT = null;
var routeLineRT = null;
var firstPositionRT = true;
var sessionPoints = [];
var sessionStartTime = new Date().toLocaleTimeString('es-CO');
var lastKnownId = null;

// ── OSRM debounce state for real-time ──
var rtOsrm = {
    inFlight: false,
    timer: null,
    cachedRoute: null,
    DEBOUNCE: 5000
};

// ── Polling control ──
var pollInterval = 2000;
var pollTimer = null;
var statsTimer = null;
var backoffMultiplier = 1;
var MAX_BACKOFF = 16;
var isTabVisible = true;

/**
 * Initialize real-time polling with visibility detection.
 */
function initRealtime() {
    // Visibility API: pause polling when tab is hidden
    document.addEventListener('visibilitychange', function() {
        isTabVisible = !document.hidden;
        if (isTabVisible) {
            backoffMultiplier = 1;
            startPolling();
        } else {
            stopPolling();
        }
    });

    startPolling();
    fetchStats(); // Initial stats fetch
    setInterval(fetchStats, 30000); // Stats every 30s (not every 2s!)
}

/**
 * Start the smart polling loop.
 */
function startPolling() {
    stopPolling();
    pollOnce();
}

/**
 * Stop polling.
 */
function stopPolling() {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = null;
}

/**
 * Single poll iteration with smart scheduling.
 */
function pollOnce() {
    fetchLatest();
    var nextInterval = pollInterval * backoffMultiplier;
    pollTimer = setTimeout(pollOnce, Math.min(nextInterval, pollInterval * MAX_BACKOFF));
}

/**
 * Fetch latest GPS position with change detection.
 */
function fetchLatest() {
    fetch('/api/latest')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) return;

            backoffMultiplier = 1; // Reset backoff on success

            var lat = parseFloat(data.lat);
            var lon = parseFloat(data.lon);
            var newId = data.id;

            // ── Change detection: skip redraw if nothing changed ──
            if (newId === lastKnownId) return;
            lastKnownId = newId;

            // ── Update marker ──
            if (!markerRT) {
                markerRT = L.marker([lat, lon], { icon: makeCarIcon() }).addTo(mapRT);
            } else {
                markerRT.setLatLng([lat, lon]);
            }

            if (firstPositionRT) {
                mapRT.setView([lat, lon], 15);
                firstPositionRT = false;
            }

            // ── Track session route ──
            var lastPt = sessionPoints[sessionPoints.length - 1];
            if (!lastPt || lastPt[0] !== lat || lastPt[1] !== lon) {
                sessionPoints.push([lat, lon]);
                document.getElementById('stat-route-pts').textContent = sessionPoints.length;
                drawSessionRoute();
            }

            // ── Update info panels ──
            document.getElementById('live-panel').innerHTML =
                '<div class="live-grid">' +
                    '<div class="live-field"><div class="lbl">Timestamp</div><div class="val" style="font-size:0.75rem">' + data.timestamp + '</div></div>' +
                    '<div class="live-field"><div class="lbl">Dispositivo</div><div class="val" style="font-size:0.82rem">' + data.device + '</div></div>' +
                '</div>' +
                '<div class="live-grid" style="margin-top:4px">' +
                    '<div class="live-field"><div class="lbl">Latitud</div><div class="val">' + lat.toFixed(6) + '</div></div>' +
                    '<div class="live-field"><div class="lbl">Longitud</div><div class="val">' + lon.toFixed(6) + '</div></div>' +
                '</div>';

            document.getElementById('route-info').innerHTML =
                '<div class="live-grid">' +
                    '<div class="live-field"><div class="lbl">Puntos trazados</div><div class="val">' + sessionPoints.length + '</div></div>' +
                    '<div class="live-field"><div class="lbl">Inicio sesión</div><div class="val" style="font-size:0.75rem">' + sessionStartTime + '</div></div>' +
                '</div>' +
                '<p style="font-size:0.7rem;color:var(--text-muted);margin-top:8px;padding:0 4px">La ruta se reinicia al recargar la página.</p>';
        })
        .catch(function() {
            // Exponential backoff on errors
            backoffMultiplier = Math.min(backoffMultiplier * 2, MAX_BACKOFF);
        });
}

/**
 * Draw session route with debounced OSRM.
 */
function drawSessionRoute() {
    if (sessionPoints.length < 2) return;
    drawInterimRoute();
    if (rtOsrm.timer) clearTimeout(rtOsrm.timer);
    rtOsrm.timer = setTimeout(executeSessionOSRM, rtOsrm.DEBOUNCE);
}

/**
 * Draw interim route (cached OSRM + latest point, or spline fallback).
 */
function drawInterimRoute() {
    if (routeLineRT) mapRT.removeLayer(routeLineRT);

    if (rtOsrm.cachedRoute && rtOsrm.cachedRoute.length > 1) {
        var latest = sessionPoints[sessionPoints.length - 1];
        var combined = rtOsrm.cachedRoute.concat([latest]);
        routeLineRT = L.polyline(combined, { color: '#4dabf7', weight: 3.5, opacity: 0.85 }).addTo(mapRT);
    } else {
        // Use spline fallback instead of simple polyline
        var smoothed = smoothPath(sessionPoints, { segments: 8, tension: 0.4 });
        routeLineRT = L.polyline(smoothed, { color: '#4dabf7', weight: 3, opacity: 0.7 }).addTo(mapRT);
    }
}

/**
 * Execute OSRM route request for the session (debounced).
 */
function executeSessionOSRM() {
    if (rtOsrm.inFlight || sessionPoints.length < 2) return;

    var sampled = samplePoints(sessionPoints, 25);
    var coords = sampled.map(function(p) { return p[1] + ',' + p[0]; }).join(';');

    rtOsrm.inFlight = true;
    fetch('/api/osrm-proxy?coords=' + encodeURIComponent(coords))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            rtOsrm.inFlight = false;
            if (data.ok && data.geometry) {
                var rc = data.geometry.coordinates.map(function(c) { return [c[1], c[0]]; });
                rtOsrm.cachedRoute = rc;
                if (routeLineRT) mapRT.removeLayer(routeLineRT);
                routeLineRT = L.polyline(rc, { color: '#4dabf7', weight: 3.5, opacity: 0.85 }).addTo(mapRT);
            }
            // If OSRM failed, the interim spline route stays visible — no flicker
        })
        .catch(function() {
            rtOsrm.inFlight = false;
        });
}

/**
 * Fetch stats (cached server-side, called every 30s).
 */
function fetchStats() {
    fetch('/api/stats')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            document.getElementById('stat-total').textContent = (data.total_records || 0).toLocaleString();
            document.getElementById('stat-first').textContent = data.first_record ? data.first_record.substring(0, 16) : '—';
            document.getElementById('stat-last').textContent = data.last_record ? data.last_record.substring(0, 16) : '—';
        })
        .catch(function() {});
}
