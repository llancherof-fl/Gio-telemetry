/**
 * GIO Telemetry — Real-Time Module
 * Smart polling, auto-follow UX, route optimization and local state restore.
 */

var markerRT = null;
var routeLineRT = null;
var firstPositionRT = true;
var sessionPoints = [];
var sessionStartTime = new Date().toLocaleTimeString('es-CO');
var lastKnownId = null;
var latestPosition = null;

var RT_CACHE_KEY = 'gio_rt_state_v2';
var RT_CACHE_TTL_MS = 6 * 60 * 60 * 1000;
var RT_CACHE_MAX_POINTS = 260;
var RT_MAX_SESSION_POINTS = 700;
var RT_MIN_POINT_DISTANCE_METERS = 4;

var autoFollow = true;
var followUiLockUntil = 0;
var lastRealtimeDevice = '';

// ── OSRM debounce state for real-time ──
var rtOsrm = {
    inFlight: false,
    timer: null,
    cachedRoute: null,
    lastComputedCount: 0,
    DEBOUNCE: 5000
};

// ── Polling control ──
var pollInterval = 2200;
var pollTimer = null;
var backoffMultiplier = 1;
var MAX_BACKOFF = 16;

// ── Cache save throttling ──
var rtSaveTimer = null;

/**
 * Initialize real-time polling with visibility detection and map interaction hooks.
 */
function initRealtime() {
    if (mapRT) {
        mapRT.on('dragstart zoomstart', onRealtimeMapInteraction);
    }

    document.addEventListener('visibilitychange', function() {
        if (!document.hidden) {
            backoffMultiplier = 1;
            startPolling();
        } else {
            stopPolling();
        }
    });

    updateFollowUi();
    startPolling();
}

function onRealtimeMapInteraction() {
    if (Date.now() < followUiLockUntil) return;
    if (!autoFollow) return;
    autoFollow = false;
    updateFollowUi();
    showToast('Seguimiento automático pausado');
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

function getRealtimeDeviceFilter() {
    var select = document.getElementById('device-select');
    if (!select) return '';
    return (select.value || '').trim();
}

function updateConnectionUi(label, online) {
    var labelEl = document.getElementById('rt-connection-label');
    var dotEl = document.getElementById('rt-status-dot');
    if (labelEl) labelEl.textContent = label;
    if (dotEl) {
        dotEl.style.background = online ? 'var(--green)' : 'var(--red)';
        dotEl.style.boxShadow = online
            ? '0 0 10px rgba(88, 209, 127, 0.8)'
            : '0 0 10px rgba(255, 123, 123, 0.7)';
    }
}

function updateFollowUi() {
    var toggleBtn = document.getElementById('btn-follow-toggle');
    var note = document.getElementById('rt-follow-note');

    if (toggleBtn) {
        toggleBtn.textContent = autoFollow ? 'Seguimiento: ON' : 'Seguimiento: OFF';
        toggleBtn.classList.toggle('btn-primary', autoFollow);
        toggleBtn.classList.toggle('btn-outline', !autoFollow);
    }

    if (note) {
        note.textContent = autoFollow
            ? 'Seguimiento automático activo'
            : 'Seguimiento pausado (usa Recentrar para retomar)';
    }
}

function toggleAutoFollow() {
    autoFollow = !autoFollow;
    updateFollowUi();

    if (autoFollow) {
        recenterVehicle();
    }
}

function recenterVehicle() {
    if (!latestPosition || !mapRT) return;

    followUiLockUntil = Date.now() + 1200;
    autoFollow = true;
    updateFollowUi();

    var targetZoom = Math.max(mapRT.getZoom(), 15);
    mapRT.flyTo([latestPosition.lat, latestPosition.lon], Math.min(targetZoom, 16), {
        animate: true,
        duration: 0.7
    });
}

function updateRecenterButtonsState(enabled) {
    var btn = document.getElementById('btn-recenter');
    var fab = document.getElementById('btn-recenter-fab');
    if (btn) btn.disabled = !enabled;
    if (fab) fab.disabled = !enabled;
}

/**
 * Fetch latest GPS position with change detection.
 */
function fetchLatest() {
    var device = getRealtimeDeviceFilter();
    if (device !== lastRealtimeDevice) {
        resetRealtimeSessionForDevice(device);
        lastRealtimeDevice = device;
    }

    var url = '/api/latest';
    if (device) {
        url += '?device=' + encodeURIComponent(device);
    }

    fetch(url)
        .then(function(r) {
            if (!r.ok) throw new Error('HTTP_' + r.status);
            return r.json();
        })
        .then(function(data) {
            if (data.error) {
                updateConnectionUi('Sin posiciones disponibles todavía', false);
                return;
            }

            backoffMultiplier = 1;
            updateConnectionUi('Señal GPS activa', true);

            var lat = parseFloat(data.lat);
            var lon = parseFloat(data.lon);
            var newId = data.id;
            if (!isFinite(lat) || !isFinite(lon)) return;

            latestPosition = { lat: lat, lon: lon };
            updateRecenterButtonsState(true);

            // Change detection: skip expensive redraw if nothing new
            if (newId === lastKnownId && markerRT) {
                if (autoFollow) {
                    mapRT.panTo([lat, lon], { animate: true, duration: 0.5 });
                }
                return;
            }
            lastKnownId = newId;

            // Update marker
            if (!markerRT) {
                markerRT = L.marker([lat, lon], { icon: makeCarIcon() }).addTo(mapRT);
            } else {
                markerRT.setLatLng([lat, lon]);
            }

            if (firstPositionRT) {
                mapRT.setView([lat, lon], 15);
                firstPositionRT = false;
            } else if (autoFollow) {
                mapRT.panTo([lat, lon], { animate: true, duration: 0.5 });
            }

            // Session route tracking with noise gate
            var currentPoint = [lat, lon];
            var lastPt = sessionPoints[sessionPoints.length - 1];
            var shouldPush = !lastPt || haversineDistance(lastPt, currentPoint) >= RT_MIN_POINT_DISTANCE_METERS;

            if (shouldPush) {
                sessionPoints.push(currentPoint);
                if (sessionPoints.length > RT_MAX_SESSION_POINTS) {
                    sessionPoints = sessionPoints.slice(sessionPoints.length - RT_MAX_SESSION_POINTS);
                }
                drawSessionRoute();
                queueRealtimeStateSave();
            }

            renderRealtimePanels(data, lat, lon);
        })
        .catch(function() {
            backoffMultiplier = Math.min(backoffMultiplier * 2, MAX_BACKOFF);
            updateConnectionUi('Conexión inestable, reintentando...', false);
        });
}

function resetRealtimeSessionForDevice(device) {
    if (routeLineRT) {
        mapRT.removeLayer(routeLineRT);
        routeLineRT = null;
    }
    if (markerRT) {
        mapRT.removeLayer(markerRT);
        markerRT = null;
    }

    sessionPoints = [];
    latestPosition = null;
    lastKnownId = null;
    firstPositionRT = true;

    rtOsrm.cachedRoute = null;
    rtOsrm.lastComputedCount = 0;

    updateRecenterButtonsState(false);

    var livePanel = document.getElementById('live-panel');
    if (livePanel) {
        livePanel.innerHTML =
            '<div class="no-data"><div class="no-data-icon">' + SVG_PIN_GREEN + '</div>Cargando posición del vehículo seleccionado...</div>';
    }

    var routeInfo = document.getElementById('route-info');
    if (routeInfo) {
        routeInfo.innerHTML =
            '<div class="no-data"><div class="no-data-icon">' + SVG_SEARCH + '</div>Ruta reiniciada para el nuevo filtro.</div>';
    }
}

function renderRealtimePanels(data, lat, lon) {
    var livePanel = document.getElementById('live-panel');
    var routeInfo = document.getElementById('route-info');

    if (livePanel) {
        livePanel.innerHTML =
            '<div class="live-grid">' +
                '<div class="live-field"><div class="lbl">Timestamp</div><div class="val" style="font-size:0.74rem">' + data.timestamp + '</div></div>' +
                '<div class="live-field"><div class="lbl">Dispositivo</div><div class="val" style="font-size:0.78rem">' + data.device + '</div></div>' +
            '</div>' +
            '<div class="live-grid">' +
                '<div class="live-field"><div class="lbl">Latitud</div><div class="val">' + lat.toFixed(6) + '</div></div>' +
                '<div class="live-field"><div class="lbl">Longitud</div><div class="val">' + lon.toFixed(6) + '</div></div>' +
            '</div>';
    }

    if (routeInfo) {
        routeInfo.innerHTML =
            '<div class="live-grid">' +
                '<div class="live-field"><div class="lbl">Puntos sesión</div><div class="val">' + sessionPoints.length + '</div></div>' +
                '<div class="live-field"><div class="lbl">Inicio sesión</div><div class="val" style="font-size:0.74rem">' + sessionStartTime + '</div></div>' +
            '</div>' +
            '<p style="font-size:0.71rem;color:var(--text-muted);margin-top:2px;padding:0 2px">Se guarda una caché corta para mejorar apertura y continuidad visual.</p>';
    }
}

function applyRouteToMap(latLngs, style) {
    if (!latLngs || latLngs.length < 2) return;

    if (!routeLineRT) {
        routeLineRT = L.polyline(latLngs, style).addTo(mapRT);
        return;
    }

    routeLineRT.setStyle(style);
    routeLineRT.setLatLngs(latLngs);
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
    if (sessionPoints.length < 2) return;

    if (rtOsrm.cachedRoute && rtOsrm.cachedRoute.length > 1) {
        var latest = sessionPoints[sessionPoints.length - 1];
        var combined = rtOsrm.cachedRoute.concat([latest]);
        applyRouteToMap(combined, { color: '#5bb9ff', weight: 3.4, opacity: 0.86 });
        return;
    }

    var base = sessionPoints.length > 240 ? samplePoints(sessionPoints, 240) : sessionPoints.slice();
    var smoothed = smoothPath(base, { segments: 6, tension: 0.42 });
    applyRouteToMap(smoothed, { color: '#5bb9ff', weight: 3, opacity: 0.74 });
}

/**
 * Execute OSRM route request for the session (debounced).
 */
function executeSessionOSRM() {
    if (rtOsrm.inFlight || sessionPoints.length < 2) return;

    // Skip expensive recalculation if only 1-2 points changed.
    if (rtOsrm.cachedRoute && (sessionPoints.length - rtOsrm.lastComputedCount) < 4) {
        return;
    }

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
                rtOsrm.lastComputedCount = sessionPoints.length;
                applyRouteToMap(rc, { color: '#5bb9ff', weight: 3.4, opacity: 0.88 });
            }
            // If OSRM failed, fallback spline already visible.
        })
        .catch(function() {
            rtOsrm.inFlight = false;
        });
}

function queueRealtimeStateSave() {
    if (rtSaveTimer) return;
    rtSaveTimer = setTimeout(function() {
        rtSaveTimer = null;
        saveRealtimeState();
    }, 1200);
}

function saveRealtimeState() {
    try {
        var snapshotPoints = sessionPoints.length > RT_CACHE_MAX_POINTS
            ? samplePoints(sessionPoints, RT_CACHE_MAX_POINTS)
            : sessionPoints.slice();

        var center = mapRT ? mapRT.getCenter() : null;
        var zoom = mapRT ? mapRT.getZoom() : null;

        localStorage.setItem(RT_CACHE_KEY, JSON.stringify({
            savedAt: new Date().toISOString(),
            sessionStartTime: sessionStartTime,
            lastKnownId: lastKnownId,
            latestPosition: latestPosition,
            points: snapshotPoints,
            center: center ? { lat: center.lat, lon: center.lng } : null,
            zoom: zoom
        }));
    } catch (e) {
        // Ignore storage failures
    }
}

function loadRealtimeState() {
    try {
        var raw = localStorage.getItem(RT_CACHE_KEY);
        if (!raw) return;

        var cache = JSON.parse(raw);
        if (!cache.savedAt) return;

        var age = Date.now() - new Date(cache.savedAt).getTime();
        if (age > RT_CACHE_TTL_MS) return;

        sessionStartTime = cache.sessionStartTime || sessionStartTime;
        lastKnownId = cache.lastKnownId || lastKnownId;

        if (Array.isArray(cache.points) && cache.points.length > 1) {
            sessionPoints = cache.points.filter(function(p) {
                return Array.isArray(p) && isFinite(parseFloat(p[0])) && isFinite(parseFloat(p[1]));
            }).map(function(p) {
                return [parseFloat(p[0]), parseFloat(p[1])];
            });

            drawInterimRoute();
            renderRealtimePanels({ timestamp: 'Caché local', device: '—' }, sessionPoints[sessionPoints.length - 1][0], sessionPoints[sessionPoints.length - 1][1]);
        }

        if (cache.latestPosition && isFinite(cache.latestPosition.lat) && isFinite(cache.latestPosition.lon)) {
            latestPosition = {
                lat: parseFloat(cache.latestPosition.lat),
                lon: parseFloat(cache.latestPosition.lon)
            };
            markerRT = L.marker([latestPosition.lat, latestPosition.lon], { icon: makeCarIcon() }).addTo(mapRT);
            updateRecenterButtonsState(true);
        }

        if (cache.center && cache.zoom && mapRT) {
            mapRT.setView([cache.center.lat, cache.center.lon], cache.zoom);
            firstPositionRT = false;
        }
    } catch (e) {
        // Ignore invalid cache payload
    }
}
