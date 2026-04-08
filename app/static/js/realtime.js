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
var RT_OSRM_WAYPOINTS = 25;
var RT_OSRM_TIMEOUT_MS = 8500;
var RT_OSRM_DEBOUNCE_MS = 1800;
var RT_OSRM_FORCE_REFRESH_MS = 18000;
var RT_OSRM_MIN_POINTS_DELTA = 3;
var RT_OSRM_DRIFT_REFRESH_METERS = 120;
var RT_OSRM_APPEND_MAX_METERS = 120;
var RT_OSRM_STALE_POINTS_THRESHOLD = 8;
var RT_OSRM_MIN_RECOMPUTE_MS = 3200;
var RT_OSRM_DENSE_POINTS_DELTA = 6;
var RT_ROUTE_SEGMENT_MAX_JUMP_KM = 50;
var RT_INTERIM_DIRECT_MAX_KM = 8;
var RT_FETCH_TIMEOUT_MS = 6000;
var RT_TELEPORT_MAX_SPEED_KMH = 260;
var RT_TELEPORT_HARD_JUMP_KM = 120;
var RT_TELEPORT_TOAST_COOLDOWN_MS = 15000;

var autoFollow = true;
var followUiLockUntil = 0;
var lastRealtimeDevice = '';
var activeRealtimeStreamDevice = '';

// ── OSRM debounce state for real-time ──
var rtOsrm = {
    inFlight: false,
    pending: false,
    timer: null,
    controller: null,
    cachedRoute: null,
    lastRequestCoords: '',
    lastComputedCount: 0,
    lastComputedAt: 0,
    lastRouteEnd: null,
    DEBOUNCE: RT_OSRM_DEBOUNCE_MS
};

// ── Polling control ──
var pollInterval = 2200;
var pollTimer = null;
var backoffMultiplier = 1;
var MAX_BACKOFF = 16;

// ── Cache save throttling ──
var rtSaveTimer = null;
var latestFetchInFlight = false;
var latestFetchController = null;
var lastPointTimestampMs = null;
var lastTeleportToastAt = 0;

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

function clearRtOsrmTimer() {
    if (rtOsrm.timer) {
        clearTimeout(rtOsrm.timer);
        rtOsrm.timer = null;
    }
}

function parseTelemetryTimestampMs(value) {
    if (!value) return null;
    if (typeof value === 'number') return value;

    var safe = String(value).trim();
    if (!safe) return null;

    // Backend timestamps often come as "YYYY-MM-DD HH:MM:SS.ssssss"
    // Convert to RFC-friendly format for Date parsing.
    var normalized = safe.replace(' ', 'T');
    var parsed = Date.parse(normalized);
    if (isFinite(parsed)) return parsed;
    return null;
}

function isPlausibleRealtimePoint(nextPoint, nextTsMs) {
    var prevPoint = sessionPoints[sessionPoints.length - 1];
    if (!prevPoint) {
        return { ok: true };
    }

    var distanceM = haversineDistance(prevPoint, nextPoint);
    if (distanceM >= RT_TELEPORT_HARD_JUMP_KM * 1000) {
        return { ok: false, reason: 'jump_hard' };
    }

    if (!lastPointTimestampMs || !nextTsMs || nextTsMs <= lastPointTimestampMs) {
        return { ok: true };
    }

    var deltaHours = (nextTsMs - lastPointTimestampMs) / 3600000;
    if (deltaHours <= 0) {
        return { ok: false, reason: 'time_invalid' };
    }

    var speedKmh = (distanceM / 1000) / deltaHours;
    if (speedKmh > RT_TELEPORT_MAX_SPEED_KMH) {
        return { ok: false, reason: 'speed_excess' };
    }

    return { ok: true };
}

function maybeShowTeleportToast() {
    var now = Date.now();
    if ((now - lastTeleportToastAt) < RT_TELEPORT_TOAST_COOLDOWN_MS) return;
    lastTeleportToastAt = now;
    showToast('Se omitió un punto atípico en tiempo real para evitar una ruta irreal');
}

function getRealtimeSafeSegments(points) {
    if (!points || points.length < 2) return [];
    return splitByLargeJumps(points, RT_ROUTE_SEGMENT_MAX_JUMP_KM).filter(function(segment) {
        return Array.isArray(segment) && segment.length > 1;
    });
}

function getActiveRealtimeSegment() {
    if (sessionPoints.length < 2) return null;
    var segments = getRealtimeSafeSegments(sessionPoints);
    if (!segments.length) {
        return sessionPoints.slice(Math.max(0, sessionPoints.length - 2));
    }
    return segments[segments.length - 1];
}

function scheduleSessionOSRM(forceFast) {
    var activeSegment = getActiveRealtimeSegment();
    var activeCount = activeSegment ? activeSegment.length : sessionPoints.length;
    if (activeCount < 2) return;

    clearRtOsrmTimer();

    var delay = forceFast ? 380 : rtOsrm.DEBOUNCE;
    var latest = sessionPoints[sessionPoints.length - 1];
    if (rtOsrm.lastRouteEnd && latest) {
        var drift = haversineDistance(rtOsrm.lastRouteEnd, latest);
        if (drift > RT_OSRM_APPEND_MAX_METERS) {
            delay = 550;
        } else if ((activeCount - rtOsrm.lastComputedCount) >= 4) {
            delay = 900;
        }
    } else if (!rtOsrm.cachedRoute) {
        delay = 700;
    }

    rtOsrm.timer = setTimeout(function() {
        rtOsrm.timer = null;
        executeSessionOSRM();
    }, Math.max(250, delay));
}

function resetRealtimeRouteState(message) {
    if (routeLineRT) {
        mapRT.removeLayer(routeLineRT);
        routeLineRT = null;
    }

    sessionPoints = [];
    sessionStartTime = new Date().toLocaleTimeString('es-CO');

    clearRtOsrmTimer();
    if (rtOsrm.controller) {
        rtOsrm.controller.abort();
        rtOsrm.controller = null;
    }
    if (latestFetchController) {
        latestFetchController.abort();
        latestFetchController = null;
    }
    latestFetchInFlight = false;

    rtOsrm.cachedRoute = null;
    rtOsrm.inFlight = false;
    rtOsrm.pending = false;
    rtOsrm.lastComputedCount = 0;
    rtOsrm.lastComputedAt = 0;
    rtOsrm.lastRouteEnd = null;
    rtOsrm.lastRequestCoords = '';
    lastPointTimestampMs = null;

    var routeInfo = document.getElementById('route-info');
    if (routeInfo) {
        routeInfo.innerHTML =
            '<div class="no-data"><div class="no-data-icon">' + SVG_SEARCH + '</div>' +
            (message || 'Esperando puntos para construir ruta...') +
            '</div>';
    }
}

/**
 * Fetch latest GPS position with change detection.
 */
function fetchLatest() {
    var selectedDevice = getRealtimeDeviceFilter();
    if (selectedDevice !== lastRealtimeDevice) {
        resetRealtimeSessionForDevice(selectedDevice);
        lastRealtimeDevice = selectedDevice;
    }

    var effectiveDevice = selectedDevice || activeRealtimeStreamDevice;
    var url = '/api/latest';
    if (effectiveDevice) {
        url += '?device=' + encodeURIComponent(effectiveDevice);
    }

    if (latestFetchInFlight) return;

    var controller = new AbortController();
    latestFetchController = controller;
    latestFetchInFlight = true;
    var fetchTimeoutId = setTimeout(function() {
        controller.abort();
    }, RT_FETCH_TIMEOUT_MS);

    fetch(url, { signal: controller.signal })
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
            var streamDevice = (data.device || '').trim();
            if (!isFinite(lat) || !isFinite(lon)) return;

            if (!selectedDevice && streamDevice) {
                if (!activeRealtimeStreamDevice) {
                    activeRealtimeStreamDevice = streamDevice;
                } else if (activeRealtimeStreamDevice !== streamDevice) {
                    resetRealtimeRouteState('Se detectó cambio de vehículo en el stream. Ruta reiniciada para mantener consistencia.');
                    activeRealtimeStreamDevice = streamDevice;
                }
            } else if (selectedDevice) {
                activeRealtimeStreamDevice = selectedDevice;
            }

            latestPosition = { lat: lat, lon: lon };
            updateRecenterButtonsState(true);

            // Change detection: skip expensive redraw if nothing new
            if (newId === lastKnownId && markerRT) {
                if (autoFollow) {
                    mapRT.panTo([lat, lon], { animate: true, duration: 0.5 });
                }
                renderRealtimePanels(data, lat, lon);
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
            var currentTsMs = parseTelemetryTimestampMs(data.timestamp);
            var lastPt = sessionPoints[sessionPoints.length - 1];
            var jumpMeters = lastPt ? haversineDistance(lastPt, currentPoint) : 0;
            var shouldPush = !lastPt || jumpMeters >= RT_MIN_POINT_DISTANCE_METERS;

            if (shouldPush) {
                var plausibility = isPlausibleRealtimePoint(currentPoint, currentTsMs);
                if (!plausibility.ok) {
                    maybeShowTeleportToast();
                    renderRealtimePanels(data, lat, lon);
                    return;
                }

                if (lastPt && jumpMeters > RT_ROUTE_SEGMENT_MAX_JUMP_KM * 1000) {
                    rtOsrm.cachedRoute = null;
                    rtOsrm.lastRouteEnd = null;
                    rtOsrm.lastComputedCount = 0;
                    rtOsrm.lastRequestCoords = '';
                }

                sessionPoints.push(currentPoint);
                if (currentTsMs) {
                    lastPointTimestampMs = currentTsMs;
                }
                if (sessionPoints.length > RT_MAX_SESSION_POINTS) {
                    sessionPoints = sessionPoints.slice(sessionPoints.length - RT_MAX_SESSION_POINTS);
                    rtOsrm.lastComputedCount = Math.min(rtOsrm.lastComputedCount, sessionPoints.length);
                }
                drawSessionRoute();
                queueRealtimeStateSave();
            }

            renderRealtimePanels(data, lat, lon);
        })
        .catch(function() {
            backoffMultiplier = Math.min(backoffMultiplier * 2, MAX_BACKOFF);
            updateConnectionUi('Conexión inestable, reintentando...', false);
        })
        .finally(function() {
            clearTimeout(fetchTimeoutId);
            if (latestFetchController === controller) {
                latestFetchController = null;
            }
            latestFetchInFlight = false;
        });
}

function resetRealtimeSessionForDevice(device) {
    resetRealtimeRouteState('Ruta reiniciada para el nuevo filtro.');

    if (markerRT) {
        mapRT.removeLayer(markerRT);
        markerRT = null;
    }

    latestPosition = null;
    lastKnownId = null;
    firstPositionRT = true;
    activeRealtimeStreamDevice = device || '';

    updateRecenterButtonsState(false);

    var livePanel = document.getElementById('live-panel');
    if (livePanel) {
        livePanel.innerHTML =
            '<div class="no-data"><div class="no-data-icon">' + SVG_PIN_GREEN + '</div>Cargando posición del vehículo seleccionado...</div>';
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
    scheduleSessionOSRM(false);
}

/**
 * Draw interim route (cached OSRM + latest point, or spline fallback).
 */
function drawInterimRoute() {
    var activeSegment = getActiveRealtimeSegment();
    if (!activeSegment || activeSegment.length < 2) return;

    if (rtOsrm.cachedRoute && rtOsrm.cachedRoute.length > 1) {
        var latest = sessionPoints[sessionPoints.length - 1];
        var tail = rtOsrm.lastRouteEnd || rtOsrm.cachedRoute[rtOsrm.cachedRoute.length - 1];
        if (tail && haversineDistance(tail, latest) <= RT_OSRM_APPEND_MAX_METERS) {
            var combined = rtOsrm.cachedRoute.concat([latest]);
            applyRouteToMap(combined, { color: '#5bb9ff', weight: 3.4, opacity: 0.86 });
        } else {
            // Keep the last valid OSRM route visible while a new calculation is pending.
            // This avoids drawing a temporary global fallback chord over long-distance routes.
            applyRouteToMap(rtOsrm.cachedRoute, { color: '#5bb9ff', weight: 3.4, opacity: 0.86 });
        }
        return;
    }

    var base = activeSegment.length > 240 ? samplePoints(activeSegment, 240) : activeSegment.slice();
    if (base.length === 2 && distanceKm(base[0], base[1]) > RT_INTERIM_DIRECT_MAX_KM) {
        if (routeLineRT) {
            mapRT.removeLayer(routeLineRT);
            routeLineRT = null;
        }
        return;
    }

    var smoothed = smoothPath(base, { segments: 6, tension: 0.42 });
    applyRouteToMap(smoothed, { color: '#5bb9ff', weight: 3, opacity: 0.74 });
}

/**
 * Execute OSRM route request for the session (debounced).
 */
function executeSessionOSRM() {
    var activeSegment = getActiveRealtimeSegment();
    if (!activeSegment || activeSegment.length < 2) return;

    if (rtOsrm.inFlight) {
        rtOsrm.pending = true;
        return;
    }

    var now = Date.now();
    var activeCount = activeSegment.length;
    var pointsDelta = activeCount - rtOsrm.lastComputedCount;
    if (pointsDelta < 0) {
        rtOsrm.lastComputedCount = 0;
        pointsDelta = activeCount;
    }
    var latest = sessionPoints[sessionPoints.length - 1];
    var elapsed = now - rtOsrm.lastComputedAt;
    var driftMeters = rtOsrm.lastRouteEnd && latest
        ? haversineDistance(rtOsrm.lastRouteEnd, latest)
        : Infinity;

    var shouldRecompute = !rtOsrm.cachedRoute
        || pointsDelta >= RT_OSRM_MIN_POINTS_DELTA
        || elapsed >= RT_OSRM_FORCE_REFRESH_MS
        || driftMeters >= RT_OSRM_DRIFT_REFRESH_METERS;

    if (!shouldRecompute) return;

    var sampled = samplePoints(activeSegment, RT_OSRM_WAYPOINTS);
    var coords = sampled.map(function(p) { return p[1] + ',' + p[0]; }).join(';');
    var requestPointCount = activeCount;

    if (
        rtOsrm.cachedRoute
        && elapsed < RT_OSRM_MIN_RECOMPUTE_MS
        && pointsDelta < RT_OSRM_DENSE_POINTS_DELTA
        && driftMeters < (RT_OSRM_DRIFT_REFRESH_METERS * 2)
    ) {
        return;
    }

    if (rtOsrm.cachedRoute && coords === rtOsrm.lastRequestCoords && elapsed < RT_OSRM_FORCE_REFRESH_MS) {
        return;
    }

    rtOsrm.inFlight = true;
    rtOsrm.pending = false;
    rtOsrm.lastRequestCoords = coords;

    if (rtOsrm.controller) {
        rtOsrm.controller.abort();
    }
    var controller = new AbortController();
    rtOsrm.controller = controller;
    var timeoutId = setTimeout(function() {
        controller.abort();
    }, RT_OSRM_TIMEOUT_MS);

    fetch('/api/osrm-proxy?coords=' + encodeURIComponent(coords), { signal: controller.signal })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            rtOsrm.lastComputedAt = Date.now();
            var currentSegment = getActiveRealtimeSegment();
            var currentCount = currentSegment ? currentSegment.length : 0;
            if ((currentCount - requestPointCount) > RT_OSRM_STALE_POINTS_THRESHOLD && rtOsrm.cachedRoute) {
                rtOsrm.pending = true;
                return;
            }

            if (data.ok && data.geometry) {
                var rc = data.geometry.coordinates.map(function(c) { return [c[1], c[0]]; });
                if (rc.length > 1) {
                    rtOsrm.cachedRoute = rc;
                    rtOsrm.lastComputedCount = requestPointCount;
                    rtOsrm.lastRouteEnd = rc[rc.length - 1];
                    applyRouteToMap(rc, { color: '#5bb9ff', weight: 3.4, opacity: 0.88 });
                }
            }
            // If OSRM failed, fallback spline already visible.
        })
        .catch(function(err) {
            if (err && err.name === 'AbortError') {
                // Timeout or cancellation: keep fallback and try again soon if needed.
            }
            rtOsrm.lastComputedAt = Date.now();
        })
        .finally(function() {
            clearTimeout(timeoutId);
            if (rtOsrm.controller === controller) {
                rtOsrm.controller = null;
            }
            rtOsrm.inFlight = false;

            if (rtOsrm.pending) {
                rtOsrm.pending = false;
                scheduleSessionOSRM(true);
            }
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
            lastPointTimestampMs: lastPointTimestampMs,
            latestPosition: latestPosition,
            points: snapshotPoints,
            device: getRealtimeDeviceFilter() || activeRealtimeStreamDevice || '',
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
        var selectedDevice = getRealtimeDeviceFilter();
        if (selectedDevice && (cache.device || '') !== selectedDevice) return;

        var age = Date.now() - new Date(cache.savedAt).getTime();
        if (age > RT_CACHE_TTL_MS) return;

        sessionStartTime = cache.sessionStartTime || sessionStartTime;
        lastKnownId = cache.lastKnownId || lastKnownId;
        lastPointTimestampMs = cache.lastPointTimestampMs || lastPointTimestampMs;
        activeRealtimeStreamDevice = cache.device || activeRealtimeStreamDevice;

        if (Array.isArray(cache.points) && cache.points.length > 1) {
            sessionPoints = cache.points.filter(function(p) {
                return Array.isArray(p) && isFinite(parseFloat(p[0])) && isFinite(parseFloat(p[1]));
            }).map(function(p) {
                return [parseFloat(p[0]), parseFloat(p[1])];
            });

            drawInterimRoute();
            scheduleSessionOSRM(true);
            renderRealtimePanels(
                { timestamp: 'Caché local', device: activeRealtimeStreamDevice || '—' },
                sessionPoints[sessionPoints.length - 1][0],
                sessionPoints[sessionPoints.length - 1][1]
            );
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
