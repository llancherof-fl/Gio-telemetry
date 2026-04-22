/**
 * GIO Telemetry — Historical Search Module
 * Date range search with validation, smart sampling,
 * request cancellation and robust map/list cleanup.
 */

var histMarkers = [];
var routeLineHist = null;
var historicRouteBounds = null;
var currentRange = { start: null, end: null };
var CACHE_KEY = 'gio_hist_cache_v2';
var CACHE_PTS = 30;
var FILTERS_KEY = 'gio_hist_filters_v1';
var HIST_MODE_TRIPS = 'trips';
var HIST_MODE_POINTS = 'points';

var histFetchController = null;
var histRouteController = null;
var histTripPointsController = null;
var histListObserver = null;
var histQueryToken = 0;
var histTrips = [];
var histTripPointsCache = {};
var histSelectedTripId = '';
var histSelectedTrip = null;
var histPreferredTripId = '';

// ── Location Query state ──
var locationQueryMode = false;
var gpsDotLayer = null;
var locationQueryMarker = null;
var locationQuerySpinner = null;
var locationQueryController = null;
var locationQueryData = null;   // raw GPS points of the current route (for dot overlay)

// ══════════════════════════════════════════
//  FILTERS
// ══════════════════════════════════════════

function loadDeviceOptions() {
    restoreHistoryFilters();

    var sampleSelect = document.getElementById('sample-select');
    var customInput = document.getElementById('sample-custom-minutes');
    var routeMethodSelect = document.getElementById('hist-route-method');
    var dataModeSelect = document.getElementById('hist-data-mode');
    if (sampleSelect) {
        sampleSelect.addEventListener('change', function () {
            syncSampleCustomUi();
            saveHistoryFilters();
            if (currentRange.start && currentRange.end) {
                runHistoricQuery();
            }
        });
    }
    if (customInput) {
        customInput.addEventListener('input', function () {
            sanitizeCustomSampleInput();
            saveHistoryFilters();
        });
        customInput.addEventListener('change', function () {
            sanitizeCustomSampleInput();
            saveHistoryFilters();
            if (currentRange.start && currentRange.end && getSampleMinutes() > 0) {
                runHistoricQuery();
            }
        });
    }
    if (routeMethodSelect) {
        routeMethodSelect.addEventListener('change', function () {
            saveHistoryFilters();
            if (currentRange.start && currentRange.end) {
                runHistoricQuery();
            }
        });
    }
    if (dataModeSelect) {
        dataModeSelect.addEventListener('change', function () {
            refreshHistoricalModeLabels();
            saveHistoryFilters();
            showToast(getHistoricalDataMode() === HIST_MODE_TRIPS ? 'Modo trayectos activado' : 'Modo puntos crudo activado');
            if (currentRange.start && currentRange.end) {
                runHistoricQuery();
            } else {
                clearHistoricLayers();
                document.getElementById('results-list').innerHTML =
                    '<div class="no-data"><div class="no-data-icon">' + SVG_SEARCH + '</div>Selecciona un rango y presiona Buscar</div>';
                document.getElementById('results-count').textContent = '—';
            }
        });
    }

    syncSampleCustomUi();
    refreshHistoricalModeLabels();
    updateHistoricFitButtonState(false);

    if (typeof updateLayoutOffsets === 'function') {
        updateLayoutOffsets();
    }
}

function restoreHistoryFilters() {
    try {
        var raw = localStorage.getItem(FILTERS_KEY);
        if (!raw) return;
        var saved = JSON.parse(raw);

        var sampleSelect = document.getElementById('sample-select');
        var customInput = document.getElementById('sample-custom-minutes');
        var routeMethodSelect = document.getElementById('hist-route-method');
        var dataModeSelect = document.getElementById('hist-data-mode');

        if (sampleSelect && saved.sampleMinutes) {
            if (saved.sampleMode === 'custom') {
                sampleSelect.value = 'custom';
            } else {
                sampleSelect.value = String(saved.sampleMinutes);
            }
        }
        if (customInput && saved.sampleCustomMinutes) {
            customInput.value = String(saved.sampleCustomMinutes);
        }
        if (routeMethodSelect && saved.routeMethod) {
            routeMethodSelect.value = saved.routeMethod === 'match' ? 'match' : 'route';
        }
        if (dataModeSelect && saved.dataMode) {
            dataModeSelect.value = saved.dataMode === HIST_MODE_POINTS ? HIST_MODE_POINTS : HIST_MODE_TRIPS;
        }

        syncSampleCustomUi();
        refreshHistoricalModeLabels();
    } catch (e) {
        // ignore corrupt storage
    }
}

function saveHistoryFilters() {
    try {
        var sampleSelect = document.getElementById('sample-select');
        var customInput = document.getElementById('sample-custom-minutes');
        var routeMethodSelect = document.getElementById('hist-route-method');
        var dataModeSelect = document.getElementById('hist-data-mode');

        localStorage.setItem(FILTERS_KEY, JSON.stringify({
            sampleMinutes: getSampleMinutes(),
            sampleMode: sampleSelect ? sampleSelect.value : '3',
            sampleCustomMinutes: customInput ? sanitizeCustomSampleInput() : 3,
            routeMethod: routeMethodSelect ? getHistoricRouteMethod() : 'route',
            dataMode: dataModeSelect ? getHistoricalDataMode() : HIST_MODE_TRIPS
        }));
    } catch (e) {
        // ignore storage failures
    }
}

function getHistoricRouteMethod() {
    var select = document.getElementById('hist-route-method');
    if (!select) return 'route';
    return select.value === 'match' ? 'match' : 'route';
}

function getHistoricalDataMode() {
    var select = document.getElementById('hist-data-mode');
    if (!select) return HIST_MODE_TRIPS;
    return select.value === HIST_MODE_POINTS ? HIST_MODE_POINTS : HIST_MODE_TRIPS;
}

function getHistoricalPanelTitle() {
    return getHistoricalDataMode() === HIST_MODE_TRIPS ? 'trayectos' : 'registros';
}

function refreshHistoricalModeLabels() {
    var isTripsMode = getHistoricalDataMode() === HIST_MODE_TRIPS;
    var resultsTitle = document.querySelector('.results-title');
    var infoBtn = document.getElementById('hist-pane-info-btn');
    var helpText = document.getElementById('hist-help');
    var sampleSelect = document.getElementById('sample-select');
    var sampleCustomWrap = document.getElementById('sample-custom-wrap');
    var sampleCustomInput = document.getElementById('sample-custom-minutes');
    var samplingHint = document.getElementById('hist-sample-hint');

    if (resultsTitle) {
        resultsTitle.textContent = isTripsMode ? 'Trayectos' : 'Registros';
    }
    if (infoBtn) {
        infoBtn.textContent = isTripsMode ? 'Trayectos' : 'Registros';
    }
    if (helpText) {
        helpText.textContent = isTripsMode
            ? 'Selecciona rango para listar sesiones reales (inicio/fin), aplicar paso y ver su ruta individual.'
            : 'Usa un rango de tiempo y un nivel de detalle para consultar recorridos sin ruido visual.';
    }
    if (sampleSelect) {
        sampleSelect.disabled = false;
        sampleSelect.title = isTripsMode
            ? 'Ajusta resolución del trayecto seleccionado'
            : 'Reducir ruido de puntos';
    }
    if (sampleCustomInput) {
        sampleCustomInput.disabled = false;
    }
    if (sampleCustomWrap) {
        syncSampleCustomUi();
    }
    if (samplingHint) {
        samplingHint.hidden = false;
        samplingHint.textContent = isTripsMode
            ? 'Paso aplicado al trayecto seleccionado (menos puntos = respuesta más rápida).'
            : 'Paso aplicado al rango completo (menos ruido y menor carga).';
    }
    if (typeof updateHistoricalPanelButton === 'function') {
        updateHistoricalPanelButton();
    }
}

function getSampleMinutes() {
    var select = document.getElementById('sample-select');
    if (!select) return 3;

    if (select.value === 'custom') {
        return sanitizeCustomSampleInput();
    }

    var value = parseInt(select.value, 10);
    return isFinite(value) ? Math.min(60, Math.max(1, value)) : 3;
}

function sanitizeCustomSampleInput() {
    var input = document.getElementById('sample-custom-minutes');
    if (!input) return 3;

    var value = parseInt(input.value, 10);
    if (!isFinite(value)) value = 3;
    value = Math.min(60, Math.max(1, value));
    input.value = String(value);
    return value;
}

function syncSampleCustomUi() {
    var select = document.getElementById('sample-select');
    var wrap = document.getElementById('sample-custom-wrap');
    if (!select || !wrap) return;

    var isCustom = select.value === 'custom';
    wrap.hidden = !isCustom;
    wrap.setAttribute('aria-hidden', String(!isCustom));
    if (isCustom) {
        sanitizeCustomSampleInput();
    }
}

function getSampleLabel() {
    var select = document.getElementById('sample-select');
    if (!select) return '3 min';

    if (select.value === 'custom') {
        return sanitizeCustomSampleInput() + ' min (custom)';
    }

    var option = select.options[select.selectedIndex];
    return option ? option.textContent : String(getSampleMinutes()) + ' min';
}

// ══════════════════════════════════════════
//  QUICK RANGE
// ══════════════════════════════════════════

function applyQuickRange(val) {
    if (!val) {
        clearHistoric(true);
        return;
    }

    var now = new Date();
    var start;

    if (val === '30m') start = new Date(now.getTime() - 30 * 60 * 1000);
    else if (val === '1h') start = new Date(now.getTime() - 60 * 60 * 1000);
    else if (val === '3h') start = new Date(now.getTime() - 3 * 60 * 60 * 1000);
    else if (val === '6h') start = new Date(now.getTime() - 6 * 60 * 60 * 1000);
    else if (val === 'today') {
        start = new Date(now);
        start.setHours(0, 0, 0, 0);
    } else if (val === 'yesterday') {
        start = new Date(now);
        start.setDate(start.getDate() - 1);
        start.setHours(0, 0, 0, 0);

        var yesterdayEnd = new Date(start);
        yesterdayEnd.setHours(23, 59, 59, 999);
        currentRange.start = toLocalISO(start);
        currentRange.end = toLocalISO(yesterdayEnd);
        // === CORRECCIÓN PROFESOR A1: Búsqueda automática ===
        runHistoricQuery();
        return;
    } else if (val === 'week') {
        start = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    }

    currentRange.start = toLocalISO(start);
    currentRange.end = toLocalISO(new Date());
    // === CORRECCIÓN PROFESOR A1: Búsqueda automática ===
    runHistoricQuery();
}

// ══════════════════════════════════════════
//  HISTORIC QUERY
// ══════════════════════════════════════════

function setHistoricStatus(msg, color) {
    var status = document.getElementById('hist-status');
    if (!status) return;
    status.textContent = msg || '';
    status.style.color = color || 'var(--text-muted)';
}

function updateHistoricFitButtonState(enabled) {
    var btn = document.getElementById('btn-hist-fit');
    if (!btn) return;
    btn.disabled = !enabled;
}

function getHistoricFitPadding() {
    var right = 34;
    var panel = document.getElementById('results-panel');
    var histLayout = document.getElementById('hist-layout');
    var isDesktop = window.innerWidth > 960;
    var panelVisible = isDesktop
        && histLayout
        && !histLayout.classList.contains('panel-collapsed')
        && panel
        && window.getComputedStyle(panel).display !== 'none';

    if (panelVisible) {
        right = Math.round(panel.getBoundingClientRect().width + 26);
    }

    return {
        topLeft: [36, 34],
        bottomRight: [right, 42]
    };
}

function fitHistoricBounds(bounds, animate) {
    if (!mapHist || !bounds || !bounds.isValid()) return;
    var pad = getHistoricFitPadding();
    mapHist.fitBounds(bounds, {
        paddingTopLeft: pad.topLeft,
        paddingBottomRight: pad.bottomRight,
        maxZoom: 16,
        animate: animate !== false
    });
}

function fitHistoricRoute() {
    if (!historicRouteBounds) return;
    fitHistoricBounds(historicRouteBounds, true);
}

function refreshHistoricLayout(skipAnimation) {
    if (!mapHist) return;
    mapHist.invalidateSize();
    if (!historicRouteBounds) return;
    setTimeout(function () {
        fitHistoricBounds(historicRouteBounds, !skipAnimation);
    }, 40);
}

function getHistoryUrl() {
    var sampleMinutes = getSampleMinutes();
    var params = [
        'start=' + encodeURIComponent(currentRange.start),
        'end=' + encodeURIComponent(currentRange.end),
        'sample_minutes=' + encodeURIComponent(String(sampleMinutes)),
        'limit=2500'
    ];

    return '/api/history-range?' + params.join('&');
}

function getTripsUrl() {
    var params = [
        'start=' + encodeURIComponent(currentRange.start),
        'end=' + encodeURIComponent(currentRange.end),
        'limit=400'
    ];

    return '/api/trips-range?' + params.join('&');
}

function runHistoricQuery() {
    if (!currentRange.start || !currentRange.end) {
        showToast('Selecciona un rango de tiempo primero');
        return;
    }

    abortHistoricRequests();
    saveHistoryFilters();
    refreshHistoricalModeLabels();
    updateMobileFilterSummary();

    histQueryToken += 1;
    var token = histQueryToken;
    var mode = getHistoricalDataMode();
    var requestedTripId = histSelectedTripId || histPreferredTripId || '';

    histTrips = [];
    histTripPointsCache = {};
    histSelectedTripId = '';
    histSelectedTrip = null;
    histPreferredTripId = requestedTripId;

    setHistoricStatus(
        mode === HIST_MODE_TRIPS ? 'Buscando trayectos...' : 'Buscando registros...',
        'var(--blue-strong)'
    );

    document.getElementById('results-list').innerHTML =
        '<div class="no-data"><div class="skeleton" style="width:64%;height:12px;margin:8px auto"></div><div class="skeleton" style="width:42%;height:12px;margin:8px auto"></div></div>';
    document.getElementById('results-count').textContent = '...';

    histFetchController = new AbortController();
    var url = mode === HIST_MODE_TRIPS ? getTripsUrl() : getHistoryUrl();

    fetch(url, { signal: histFetchController.signal })
        .then(function (r) {
            return r.json().then(function (body) {
                if (!r.ok) {
                    var msg = (body && body.error) ? body.error : 'Error al consultar histórico';
                    throw new Error(msg);
                }
                return body;
            });
        })
        .then(function (response) {
            if (token !== histQueryToken) return;
            if (mode === HIST_MODE_TRIPS) {
                runHistoricTripsQuery(response, token);
                return;
            }
            runHistoricPointsQuery(response, token);
        })
        .catch(function (err) {
            if (err && err.name === 'AbortError') return;

            clearHistoricLayers();
            document.getElementById('results-list').innerHTML =
                '<div class="no-data"><div class="no-data-icon">' + SVG_SEARCH + '</div>No se pudo cargar el histórico</div>';
            document.getElementById('results-count').textContent = '—';

            setHistoricStatus('Error en consulta', 'var(--red)');
            showToast(err && err.message ? err.message : 'Error al consultar la base de datos');
        });
}

function runHistoricPointsQuery(response, token) {
    var data = response.data || [];
    var meta = response.meta || {};

    if (meta.clamped) {
        showToast('Fecha fin ajustada al momento actual');
    }
    if (meta.dropped_outliers || meta.dropped_invalid) {
        var dropped = (meta.dropped_outliers || 0) + (meta.dropped_invalid || 0);
        showToast('Se omitieron ' + dropped + ' puntos atípicos o inválidos');
    }
    if (!data.length) {
        clearHistoricLayers();
        historicRouteBounds = null;
        updateHistoricFitButtonState(false);
        document.getElementById('results-list').innerHTML =
            '<div class="no-data"><div class="no-data-icon">' + SVG_INBOX + '</div>Sin registros en ese período</div>';
        document.getElementById('results-count').textContent = '0';
        setHistoricStatus('Sin registros', 'var(--text-muted)');
        return;
    }

    renderHistoricResults(data);
    drawHistoricRoute(data, token);
    saveToCache(data, meta);

    // Auto-collapse filter panel on mobile after successful search
    if (window.innerWidth <= 960 && typeof toggleMobileFilters === 'function') {
        var histView = document.getElementById('view-historical');
        if (histView && histView.classList.contains('filters-open')) {
            toggleMobileFilters();
        }
    }

    var sampledInfo = ' · precisión ' + getSampleLabel();
    var methodInfo = ' · método ' + (getHistoricRouteMethod() === 'match' ? 'Match' : 'Route');
    var cleanedInfo = meta.dropped_outliers
        ? ' · depurados ' + meta.dropped_outliers
        : '';
    setHistoricStatus((meta.count || data.length) + ' puntos' + sampledInfo + methodInfo + cleanedInfo, 'var(--green)');

    if (meta.has_more) {
        showToast('Se alcanzó el límite de consulta. Ajusta rango o sube el paso.');
    }
}

function runHistoricTripsQuery(response, token) {
    var trips = response.data || [];
    var meta = response.meta || {};
    histTrips = trips.slice();

    if (!trips.length) {
        clearHistoricLayers();
        historicRouteBounds = null;
        updateHistoricFitButtonState(false);
        document.getElementById('results-list').innerHTML =
            '<div class="no-data"><div class="no-data-icon">' + SVG_INBOX + '</div>Sin trayectos en ese período</div>';
        document.getElementById('results-count').textContent = '0';
        setHistoricStatus('Sin trayectos', 'var(--text-muted)');
        return;
    }

    renderTripResults(trips);

    // Auto-collapse filter panel on mobile after successful search
    if (window.innerWidth <= 960 && typeof toggleMobileFilters === 'function') {
        var histView = document.getElementById('view-historical');
        if (histView && histView.classList.contains('filters-open')) {
            toggleMobileFilters();
        }
    }

    var openTrips = trips.filter(function (item) {
        return String(item.status || '').toLowerCase() !== 'closed';
    }).length;
    document.getElementById('results-count').textContent = trips.length + ' tray.';
    setHistoricStatus(
        trips.length + ' trayectos · abiertos ' + openTrips + ' · precisión ' + getSampleLabel() + ' · selecciona uno para ver su ruta',
        'var(--green)'
    );

    if (meta.has_more) {
        showToast('Se alcanzó el límite de trayectos. Ajusta rango temporal.');
    }

    var preferred = null;
    if (histPreferredTripId) {
        preferred = trips.find(function (item) {
            return String(item.trip_id || '') === String(histPreferredTripId);
        }) || null;
    }
    if (!preferred) {
        preferred = getPreferredTrip(trips);
    }
    if (preferred && preferred.trip_id) {
        selectHistoricTrip(preferred.trip_id, token, false);
    }
}

function abortHistoricRequests() {
    if (histFetchController) {
        histFetchController.abort();
        histFetchController = null;
    }
    if (histRouteController) {
        histRouteController.abort();
        histRouteController = null;
    }
    if (histTripPointsController) {
        histTripPointsController.abort();
        histTripPointsController = null;
    }
}

function getPreferredTrip(trips) {
    if (!trips || !trips.length) return null;
    for (var i = 0; i < trips.length; i++) {
        if (String(trips[i].status || '').toLowerCase() === 'closed') {
            return trips[i];
        }
    }
    return trips[0];
}

function formatTripTimeLabel(value) {
    if (!value) return '—';
    var text = String(value);
    if (text.length >= 16 && text.indexOf(':') >= 0) {
        return text.substring(11, 16);
    }
    return text;
}

function isTripClosed(trip) {
    return String((trip && trip.status) || '').toLowerCase() === 'closed';
}

function getTripById(tripId) {
    if (!tripId || !histTrips.length) return null;
    for (var i = 0; i < histTrips.length; i++) {
        if (String(histTrips[i].trip_id || '') === String(tripId)) {
            return histTrips[i];
        }
    }
    return null;
}

function formatTripDuration(seconds) {
    var sec = parseInt(seconds, 10);
    if (!isFinite(sec) || sec <= 0) return '0m';
    var hours = Math.floor(sec / 3600);
    var minutes = Math.floor((sec % 3600) / 60);
    if (hours > 0 && minutes > 0) return hours + 'h ' + minutes + 'm';
    if (hours > 0) return hours + 'h';
    return Math.max(1, minutes) + 'm';
}

function escapeHtml(text) {
    return String(text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function renderTripResults(trips) {
    if (histListObserver) {
        histListObserver.disconnect();
        histListObserver = null;
    }

    var listEl = document.getElementById('results-list');
    if (!listEl) return;

    var html = trips.map(function (trip, idx) {
        var status = isTripClosed(trip) ? 'closed' : 'open';
        var statusLabel = status === 'closed' ? 'Finalizado' : 'Abierto';
        var durationLabel = formatTripDuration(trip.duration_seconds);
        var pointCount = parseInt(trip.point_count, 10);
        if (!isFinite(pointCount)) pointCount = 0;
        var startLabel = formatTripTimeLabel(trip.start_ts);
        var endLabel = formatTripTimeLabel(trip.end_ts);
        var spanLabel = status === 'closed'
            ? ('Inicio ' + startLabel + ' · Fin ' + endLabel)
            : ('Inicio ' + startLabel + ' · Último ' + endLabel);
        var encodedTripId = encodeURIComponent(String(trip.trip_id || ''));
        var safeTripId = escapeHtml(trip.trip_id || '');
        var selectedClass = histSelectedTripId && histSelectedTripId === trip.trip_id ? ' active' : '';
        return '<div class="result-item result-item-trip' + selectedClass + '" data-trip-id="' + encodedTripId + '">' +
            '<div class="result-index">T' + (idx + 1) + '</div>' +
            '<div class="result-info">' +
            '<div class="result-coords">' + spanLabel + '</div>' +
            '<div class="result-device">' + escapeHtml(trip.device || '—') + ' · ' + pointCount + ' pts · ' + durationLabel + '</div>' +
            '<div class="result-subline">ID ' + safeTripId + '</div>' +
            '</div>' +
            '<div class="trip-status trip-status-' + status + '">' + statusLabel + '</div>' +
            '</div>';
    }).join('');

    listEl.innerHTML = html;
    Array.from(listEl.querySelectorAll('.result-item-trip')).forEach(function (node) {
        node.addEventListener('click', function () {
            var encoded = this.getAttribute('data-trip-id') || '';
            selectHistoricTripById(encoded);
        });
    });
}

function refreshTripSelectionUi() {
    var nodes = document.querySelectorAll('#results-list .result-item-trip');
    Array.from(nodes).forEach(function (node) {
        var encoded = node.getAttribute('data-trip-id') || '';
        var tripId = decodeURIComponent(encoded);
        node.classList.toggle('active', !!histSelectedTripId && tripId === histSelectedTripId);
    });
}

function selectHistoricTripById(encodedTripId) {
    var tripId = decodeURIComponent(String(encodedTripId || ''));
    if (!tripId) return;
    selectHistoricTrip(tripId, histQueryToken, true);
}

function getTripPointsCacheKey(tripId) {
    return String(tripId || '') + '|s' + String(getSampleMinutes());
}

function selectHistoricTrip(tripId, token, fromUserClick) {
    if (!tripId || token !== histQueryToken) return;

    histSelectedTripId = tripId;
    histSelectedTrip = getTripById(tripId);
    histPreferredTripId = tripId;
    refreshTripSelectionUi();

    var sampleMinutes = getSampleMinutes();
    var cacheKey = getTripPointsCacheKey(tripId);
    var cachedPoints = histTripPointsCache[cacheKey];
    if (cachedPoints && cachedPoints.length) {
        if (window.innerWidth <= 960 && typeof switchHistoricalMobilePane === 'function') {
            switchHistoricalMobilePane('map');
        }
        drawHistoricRoute(cachedPoints, token, { trip: histSelectedTrip });
        setHistoricStatus(
            cachedPoints.length + ' puntos del trayecto seleccionado · precisión ' + getSampleLabel() + ' · método ' + (getHistoricRouteMethod() === 'match' ? 'Match' : 'Route'),
            'var(--green)'
        );
        if (fromUserClick) {
            showToast('Trayecto cargado desde caché local de la sesión actual');
        }
        return;
    }

    if (histTripPointsController) {
        histTripPointsController.abort();
        histTripPointsController = null;
    }
    histTripPointsController = new AbortController();

    setHistoricStatus('Cargando trayecto seleccionado...', 'var(--blue-strong)');

    fetch('/api/trip-points?trip_id=' + encodeURIComponent(tripId) + '&limit=5000&sample_minutes=' + encodeURIComponent(String(sampleMinutes)), {
        signal: histTripPointsController.signal
    })
        .then(function (r) {
            return r.json().then(function (body) {
                if (!r.ok) {
                    var msg = (body && body.error) ? body.error : 'No se pudo cargar el trayecto';
                    throw new Error(msg);
                }
                return body;
            });
        })
        .then(function (payload) {
            if (token !== histQueryToken || tripId !== histSelectedTripId) return;
            var points = payload.data || [];
            var payloadMeta = payload.meta || {};
            histTripPointsCache[cacheKey] = points;

            if (!points.length) {
                clearHistoricLayers();
                setHistoricStatus('Trayecto sin puntos', 'var(--text-muted)');
                return;
            }

            if (payloadMeta.dropped_outliers || payloadMeta.dropped_invalid) {
                var dropped = (payloadMeta.dropped_outliers || 0) + (payloadMeta.dropped_invalid || 0);
                showToast('Se depuraron ' + dropped + ' puntos atípicos en este trayecto');
            }

            drawHistoricRoute(points, token, { trip: histSelectedTrip });
            saveToCache(points, {
                mode: HIST_MODE_TRIPS,
                trip_id: tripId,
                count: points.length
            });

            var trip = histSelectedTrip || getTripById(tripId);
            var summary = points.length + ' puntos del trayecto';
            if (trip) {
                summary = points.length + ' puntos · ' + formatTripDuration(trip.duration_seconds) + ' · ' + (trip.status === 'closed' ? 'finalizado' : 'abierto');
            }
            if (payloadMeta.dropped_outliers) {
                summary += ' · depurados ' + payloadMeta.dropped_outliers;
            }
            summary += ' · precisión ' + getSampleLabel();
            setHistoricStatus(summary + ' · método ' + (getHistoricRouteMethod() === 'match' ? 'Match' : 'Route'), 'var(--green)');
        })
        .catch(function (err) {
            if (err && err.name === 'AbortError') return;
            setHistoricStatus('Error cargando trayecto', 'var(--red)');
            showToast(err && err.message ? err.message : 'No se pudo cargar el trayecto seleccionado');
        })
        .finally(function () {
            histTripPointsController = null;
        });
}

// ══════════════════════════════════════════
//  RESULTS RENDERING (with lazy loading)
// ══════════════════════════════════════════

function renderHistoricResults(data) {
    document.getElementById('results-count').textContent = data.length + ' reg.';
    var reversed = data.slice().reverse();

    var BATCH = 60;
    var initialBatch = reversed.slice(0, BATCH);
    var listEl = document.getElementById('results-list');
    listEl.innerHTML = renderResultBatch(initialBatch, data.length, 0);

    if (histListObserver) {
        histListObserver.disconnect();
        histListObserver = null;
    }

    if (reversed.length <= BATCH) return;

    var sentinel = document.createElement('div');
    sentinel.id = 'lazy-sentinel';
    sentinel.style.height = '1px';
    listEl.appendChild(sentinel);

    var loaded = BATCH;

    histListObserver = new IntersectionObserver(function (entries) {
        if (!entries[0].isIntersecting || loaded >= reversed.length) return;

        var nextBatch = reversed.slice(loaded, loaded + BATCH);
        sentinel.insertAdjacentHTML('beforebegin', renderResultBatch(nextBatch, data.length, loaded));
        loaded += nextBatch.length;

        if (loaded >= reversed.length && histListObserver) {
            histListObserver.disconnect();
            histListObserver = null;
            sentinel.remove();
        }
    }, { root: listEl, threshold: 0.1 });

    histListObserver.observe(sentinel);
}

function renderResultBatch(batch, total, offset) {
    return batch.map(function (r, i) {
        var idx = total - (offset + i);
        return '<div class="result-item" onclick="flyToPoint(' + r.lat + ',' + r.lon + ')">' +
            '<div class="result-index">' + idx + '</div>' +
            '<div class="result-info">' +
            '<div class="result-coords">' + parseFloat(r.lat).toFixed(5) + ', ' + parseFloat(r.lon).toFixed(5) + '</div>' +
            '<div class="result-device">' + (r.device || '—') + '</div>' +
            '</div>' +
            '<div class="result-time">' + (r.timestamp ? r.timestamp.substring(11, 16) : '—') + '</div>' +
            '</div>';
    }).join('');
}

function flyToPoint(lat, lon) {
    if (!mapHist) return;
    mapHist.flyTo([lat, lon], Math.max(mapHist.getZoom(), 15), { duration: 0.55 });
}

// ══════════════════════════════════════════
//  HISTORIC ROUTE DRAWING
// ══════════════════════════════════════════

function clearHistoricLayers() {
    histMarkers.forEach(function (m) { mapHist.removeLayer(m); });
    histMarkers = [];

    if (routeLineHist) {
        mapHist.removeLayer(routeLineHist);
        routeLineHist = null;
    }

    clearGpsDots();
    clearLocationQueryMarker();
    locationQueryData = null;

    historicRouteBounds = null;
    updateHistoricFitButtonState(false);
    updateLocationQueryButton();
}

// ══════════════════════════════════════════
//  LOCATION QUERY — "¿Cuándo pasó?"
// ══════════════════════════════════════════

/**
 * Draw GPS raw-point dots on top of the OSRM route using the shared Canvas
 * renderer. Max 200 points (sampled uniformly) to keep canvas paint cost low.
 * Each dot is a small semi-transparent circle; no DOM node is created per dot.
 */
function drawGpsDots(data) {
    clearGpsDots();
    if (!mapHist || !data || !data.length) return;

    var pts = data.length > 200 ? samplePoints(data, 200) : data;

    // No custom renderer — use the map's default canvas (preferCanvas: true).
    // A separate L.canvas() instance can end up below the polyline canvas in the
    // DOM z-order and become invisible. Sharing the same canvas avoids that entirely.
    var layers = [];
    for (var i = 0; i < pts.length; i++) {
        var p = pts[i];
        var lat = parseFloat(p.lat);
        var lon = parseFloat(p.lon);
        if (!isFinite(lat) || !isFinite(lon)) continue;

        layers.push(L.circleMarker([lat, lon], {
            radius: 6,
            color: '#ffa94d',
            fillColor: '#ffa94d',
            fillOpacity: 0.9,
            weight: 1.5,
            interactive: false   // dots are decorative — clicks fall through to map
        }));
    }

    if (!layers.length) return;
    gpsDotLayer = L.layerGroup(layers).addTo(mapHist);
}

function clearGpsDots() {
    if (gpsDotLayer && mapHist) {
        mapHist.removeLayer(gpsDotLayer);
        gpsDotLayer = null;
    }
}

function clearLocationQueryMarker() {
    if (locationQuerySpinner && mapHist) {
        mapHist.removeLayer(locationQuerySpinner);
        locationQuerySpinner = null;
    }
    if (locationQueryMarker && mapHist) {
        mapHist.removeLayer(locationQueryMarker);
        locationQueryMarker = null;
    }
    if (locationQueryController) {
        locationQueryController.abort();
        locationQueryController = null;
    }
}

/**
 * Update the "¿Cuándo pasó?" button appearance to reflect current mode state.
 */
function updateLocationQueryButton() {
    var btn = document.getElementById('btn-query-location');
    if (!btn) return;
    var hasRoute = !!locationQueryData && locationQueryData.length > 0;
    btn.disabled = !hasRoute;
    btn.classList.toggle('btn-active-query', locationQueryMode && hasRoute);
}

/**
 * Update the compact mobile filter summary strip with the active range + step.
 * Called whenever filters change so the summary stays current without expanding.
 */
function updateMobileFilterSummary() {
    var el = document.getElementById('mobile-filter-summary');
    if (!el) return;

    if (!currentRange.start || !currentRange.end) {
        el.textContent = 'Configura un rango temporal';
        return;
    }

    var startDate = currentRange.start.substring(0, 10);
    var endDate = currentRange.end.substring(0, 10);
    var startTime = currentRange.start.substring(11, 16);
    var endTime = currentRange.end.substring(11, 16);

    var rangeLabel;
    if (startDate === endDate) {
        rangeLabel = startDate + ' ' + startTime + '–' + endTime;
    } else {
        rangeLabel = startDate.substring(5) + ' – ' + endDate.substring(5);
    }

    el.textContent = rangeLabel + ' · ' + getSampleLabel();
}

/**
 * Dismiss the instruction banner without deactivating query mode.
 * The X on the banner should only hide the hint text — dots and click
 * handler remain active so the user can keep querying after closing it.
 */
function closeLqBanner() {
    var banner = document.getElementById('location-query-banner');
    if (banner) banner.hidden = true;
}

/**
 * Toggle location query mode on/off.
 * When ON: map cursor becomes crosshair, GPS dots appear, click handler active.
 * When OFF: everything reverts, pending markers are cleared.
 */
function toggleLocationQueryMode() {
    if (!locationQueryData || !locationQueryData.length) return;

    locationQueryMode = !locationQueryMode;
    updateLocationQueryButton();

    var mapEl = document.getElementById('map-hist');
    var banner = document.getElementById('location-query-banner');

    if (locationQueryMode) {
        if (mapEl) mapEl.classList.add('query-mode');
        if (banner) banner.hidden = false;
        drawGpsDots(locationQueryData);
        mapHist.on('click', onHistMapClick);
    } else {
        if (mapEl) mapEl.classList.remove('query-mode');
        if (banner) banner.hidden = true;
        clearGpsDots();
        clearLocationQueryMarker();
        mapHist.off('click', onHistMapClick);
    }
}

/**
 * Handle map click in location query mode.
 * Shows a spinner dot, calls /api/nearest-point, then displays a popup with
 * the exact timestamp of the closest GPS record to the clicked coordinates.
 */
function onHistMapClick(e) {
    if (!locationQueryMode || !currentRange.start || !currentRange.end) return;

    clearLocationQueryMarker();

    var lat = e.latlng.lat;
    var lon = e.latlng.lng;

    // Immediate visual feedback at click location — use default map canvas
    locationQuerySpinner = L.circleMarker([lat, lon], {
        radius: 9,
        color: '#ffa94d',
        fillColor: '#ffa94d',
        fillOpacity: 0.35,
        weight: 2,
        interactive: false
    }).addTo(mapHist);

    var device = '';
    var deviceSelect = document.getElementById('device-select');
    if (deviceSelect) device = (deviceSelect.value || '').trim();

    var url = '/api/nearest-point'
        + '?lat=' + encodeURIComponent(lat)
        + '&lon=' + encodeURIComponent(lon)
        + '&start=' + encodeURIComponent(currentRange.start)
        + '&end=' + encodeURIComponent(currentRange.end)
        + '&radius_km=0.4';
    if (device) url += '&device=' + encodeURIComponent(device);

    locationQueryController = new AbortController();
    fetch(url, { signal: locationQueryController.signal })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (locationQuerySpinner && mapHist) {
                mapHist.removeLayer(locationQuerySpinner);
                locationQuerySpinner = null;
            }
            if (!data.found) {
                showToast('Sin registro GPS cerca de ese punto');
                return;
            }

            var ts = String(data.timestamp || '');
            var time = ts.length >= 16 ? ts.substring(11, 16) : ts;
            var date = ts.length >= 10 ? ts.substring(0, 10) : '';
            var dist = data.distance_m < 1000
                ? Math.round(data.distance_m) + ' m del clic'
                : (data.distance_m / 1000).toFixed(2) + ' km del clic';

            var lqIcon = L.divIcon({
                className: 'lq-result-icon',
                html: '<svg width="24" height="24" viewBox="0 0 24 24">'
                    + '<circle cx="12" cy="12" r="8" fill="#ffa94d" stroke="#fff" stroke-width="2.5"/>'
                    + '<circle cx="12" cy="12" r="3" fill="#fff"/>'
                    + '</svg>',
                iconSize: [24, 24],
                iconAnchor: [12, 12],
                popupAnchor: [0, -14]
            });
            locationQueryMarker = L.marker([data.lat, data.lon], { icon: lqIcon })
                .bindPopup(
                    '<div class="lq-popup">'
                    + '<div class="lq-popup-time">' + time + '</div>'
                    + '<div class="lq-popup-date">' + date + '</div>'
                    + '<div class="lq-popup-dist">' + dist + '</div>'
                    + '</div>',
                    { maxWidth: 180, className: 'lq-popup-wrap' }
                )
                .addTo(mapHist)
                .openPopup();
        })
        .catch(function (err) {
            if (locationQuerySpinner && mapHist) {
                mapHist.removeLayer(locationQuerySpinner);
                locationQuerySpinner = null;
            }
            if (err && err.name === 'AbortError') return;
            showToast('No se pudo consultar la posición');
        })
        .finally(function () {
            locationQueryController = null;
        });
}

function drawHistoricRoute(data, token, routeContext) {
    clearHistoricLayers();
    if (!data.length) return;

    // Store reference so GPS dot overlay and query mode can use it
    locationQueryData = data;
    updateLocationQueryButton();

    // On mobile, always surface the map pane when a route is about to draw
    if (window.innerWidth <= 960 && typeof switchHistoricalMobilePane === 'function') {
        switchHistoricalMobilePane('map');
    }

    var trip = routeContext && routeContext.trip ? routeContext.trip : null;
    var closedTrip = !trip || isTripClosed(trip);
    var first = data[0];
    var last = data[data.length - 1];

    histMarkers.push(
        L.marker([first.lat, first.lon], { icon: makeStartIcon() })
            .addTo(mapHist)
            .bindPopup('<b>Inicio sesión</b><br>' + first.timestamp.substring(0, 16))
    );

    if (data.length > 1) {
        var endLabel = closedTrip ? 'Fin sesión' : 'Último punto';
        var endIcon = closedTrip ? makeEndIcon() : makeOpenIcon();
        histMarkers.push(
            L.marker([last.lat, last.lon], { icon: endIcon })
                .addTo(mapHist)
                .bindPopup('<b>' + endLabel + '</b><br>' + last.timestamp.substring(0, 16))
        );
    }

    var points = data.map(function (r) { return [parseFloat(r.lat), parseFloat(r.lon)]; });
    var basePoints = points.length > 550 ? samplePoints(points, 550) : points;
    var previewSegments = splitByLargeJumps(basePoints, 28);
    if (!previewSegments.length) {
        previewSegments = [basePoints];
    }
    var preview = previewSegments.map(function (segment) {
        return smoothPath(segment, { segments: 7, tension: 0.45 });
    }).filter(function (segment) {
        return segment && segment.length > 1;
    });
    if (!preview.length && basePoints.length > 1) {
        preview = [basePoints.slice()];
    }
    var previewDraw = preview.length === 1 ? preview[0] : preview;

    routeLineHist = L.polyline(previewDraw, {
        color: '#5f95ff',
        weight: 3,
        opacity: 0.62,
        dashArray: '8 5'
    }).addTo(mapHist);

    historicRouteBounds = routeLineHist.getBounds();
    updateHistoricFitButtonState(true);
    fitHistoricBounds(historicRouteBounds, true);
    setHistoricStatus('Calculando ruta...', 'var(--blue-strong)');
    var partialFitted = false;

    histRouteController = new AbortController();

    drawSmartRoute(mapHist, basePoints, {
        color: '#5f95ff',
        weight: 3.6,
        opacity: 0.88
    }, {
        signal: histRouteController.signal,
        osrmMethod: getHistoricRouteMethod(),
        maxJumpKm: 28,
        maxInputPoints: 260,
        minPointDistanceMeters: 3,
        chunked: true,
        chunkWaypoints: 25,
        chunkOverlap: 1,
        maxChunksPerSegment: 9,
        onPartialRoute: function (partialRoute) {
            if (token !== histQueryToken || !routeLineHist || !partialRoute) return;
            routeLineHist.setStyle({ color: '#5f95ff', weight: 3.5, opacity: 0.86, dashArray: null });
            routeLineHist.setLatLngs(partialRoute);
            historicRouteBounds = routeLineHist.getBounds();
            updateHistoricFitButtonState(true);
            if (!partialFitted && historicRouteBounds && historicRouteBounds.isValid()) {
                fitHistoricBounds(historicRouteBounds, true);
                partialFitted = true;
            }
        }
    }).then(function (line) {
        if (token !== histQueryToken) {
            if (line) mapHist.removeLayer(line);
            return;
        }

        if (!line) {
            if (routeLineHist) routeLineHist.setStyle({ opacity: 0.8, dashArray: null });
            return;
        }

        if (routeLineHist) mapHist.removeLayer(routeLineHist);
        routeLineHist = line;
        historicRouteBounds = routeLineHist.getBounds();
        updateHistoricFitButtonState(true);
        fitHistoricBounds(historicRouteBounds, true);
    });
}

// ══════════════════════════════════════════
//  CLEAR
// ══════════════════════════════════════════

function clearHistoric(silent) {
    histQueryToken += 1;
    abortHistoricRequests();
    clearHistoricLayers();
    histTrips = [];
    histTripPointsCache = {};
    histSelectedTripId = '';
    histSelectedTrip = null;

    if (histListObserver) {
        histListObserver.disconnect();
        histListObserver = null;
    }

    document.getElementById('results-list').innerHTML =
        '<div class="no-data"><div class="no-data-icon">' + SVG_SEARCH + '</div>Selecciona un rango y presiona Buscar</div>';
    document.getElementById('results-count').textContent = '—';

    setHistoricStatus('', 'var(--text-muted)');

    var quick = document.getElementById('quick-select');
    if (quick) quick.value = '';

    currentRange = { start: null, end: null };

    if (mapHist) {
        mapHist.setView([10.9878, -74.7889], 13, { animate: true });
    }
    updateHistoricFitButtonState(false);
    refreshHistoricalModeLabels();

    if (!silent) {
        showToast('Mapa histórico limpio');
    }
}

// ══════════════════════════════════════════
//  MODAL — Date Range with Validation
// ══════════════════════════════════════════

function openModal() {
    var now = new Date();
    var oneHourAgo = new Date(now.getTime() - 60 * 60 * 1000);

    var startInput = document.getElementById('modal-start');
    var endInput = document.getElementById('modal-end');

    startInput.value = currentRange.start || toLocalISO(oneHourAgo);
    endInput.value = currentRange.end || toLocalISO(now);

    var nowISO = toLocalISO(now);
    startInput.max = nowISO;
    endInput.max = nowISO;

    validateModalDates();

    document.getElementById('modal-overlay').classList.add('open');
    document.body.style.overflow = 'hidden';
}

function closeModal() {
    document.getElementById('modal-overlay').classList.remove('open');
    if (!document.getElementById('help-overlay') || !document.getElementById('help-overlay').classList.contains('open')) {
        document.body.style.overflow = '';
    }
}

function closeModalOutside(e) {
    if (e.target === document.getElementById('modal-overlay')) closeModal();
}

function setQuick(val) {
    applyQuickRange(val);

    var start = document.getElementById('modal-start');
    var end = document.getElementById('modal-end');

    start.value = currentRange.start || '';
    end.value = currentRange.end || '';

    validateModalDates();
}

function applyModal() {
    if (!validateModalDates()) return;

    currentRange.start = document.getElementById('modal-start').value;
    currentRange.end = document.getElementById('modal-end').value;

    closeModal();
    runHistoricQuery();
}

/**
 * Validate date inputs in the modal.
 * Returns true if valid, false if invalid.
 */
function validateModalDates() {
    var startInput = document.getElementById('modal-start');
    var endInput = document.getElementById('modal-end');
    var errorEl = document.getElementById('modal-error');
    var applyBtn = document.getElementById('btn-apply-modal');

    var startVal = startInput.value;
    var endVal = endInput.value;

    startInput.classList.remove('input-error');
    endInput.classList.remove('input-error');
    if (errorEl) errorEl.classList.remove('show');

    if (!startVal || !endVal) {
        if (applyBtn) applyBtn.disabled = true;
        return false;
    }

    var startDate = new Date(startVal);
    var endDate = new Date(endVal);
    var now = new Date();

    if (startDate >= endDate) {
        startInput.classList.add('input-error');
        endInput.classList.add('input-error');
        if (errorEl) {
            errorEl.textContent = 'La fecha de inicio debe ser anterior a la fecha fin';
            errorEl.classList.add('show');
        }
        if (applyBtn) applyBtn.disabled = true;
        return false;
    }

    if (endDate > new Date(now.getTime() + 60000)) {
        endInput.classList.add('input-error');
        if (errorEl) {
            errorEl.textContent = 'La fecha fin no puede ser futura';
            errorEl.classList.add('show');
        }
        if (applyBtn) applyBtn.disabled = true;
        return false;
    }

    var maxRangeMs = 31 * 24 * 60 * 60 * 1000;
    if ((endDate.getTime() - startDate.getTime()) > maxRangeMs) {
        endInput.classList.add('input-error');
        if (errorEl) {
            errorEl.textContent = 'Selecciona un rango máximo de 31 días para mantener respuesta rápida';
            errorEl.classList.add('show');
        }
        if (applyBtn) applyBtn.disabled = true;
        return false;
    }

    startInput.max = toLocalISO(now);
    endInput.min = startVal;
    endInput.max = toLocalISO(now);

    if (applyBtn) applyBtn.disabled = false;
    return true;
}

// ══════════════════════════════════════════
//  LOCAL CACHE
// ══════════════════════════════════════════

function saveToCache(data, meta) {
    try {
        localStorage.setItem(CACHE_KEY, JSON.stringify({
            savedAt: new Date().toISOString(),
            points: data.slice(-CACHE_PTS),
            meta: meta || {},
            range: currentRange,
            sampleMinutes: getSampleMinutes(),
            routeMethod: getHistoricRouteMethod(),
            dataMode: getHistoricalDataMode()
        }));
    } catch (e) {
        // ignore storage limits
    }
}

function loadCachedRoute() {
    try {
        var raw = localStorage.getItem(CACHE_KEY);
        if (!raw) return;

        var cache = JSON.parse(raw);
        if (!cache.points || cache.points.length < 2) return;

        var points = cache.points.map(function (r) {
            return [parseFloat(r.lat), parseFloat(r.lon)];
        });

        var smoothed = smoothPath(points, { segments: 6, tension: 0.46 });
        var cachedLine = L.polyline(smoothed, {
            color: '#5f95ff',
            weight: 2,
            opacity: 0.34,
            dashArray: '6 4'
        }).addTo(mapHist);
        routeLineHist = cachedLine;
        historicRouteBounds = cachedLine.getBounds();
        updateHistoricFitButtonState(true);

        fitHistoricBounds(historicRouteBounds, false);

        var savedAt = new Date(cache.savedAt).toLocaleString('es-CO');

        document.getElementById('results-list').innerHTML =
            '<div class="no-data" style="padding:16px;font-size:0.78rem">' +
            '<div class="no-data-icon">' + SVG_PACKAGE + '</div>' +
            'Última búsqueda desde caché<br>' +
            '<span style="color:var(--text-muted);font-size:0.72rem">' + savedAt + '</span><br><br>' +
            '<span style="color:var(--text-muted)">Realiza una nueva búsqueda para refrescar datos</span>' +
            '</div>';

        document.getElementById('results-count').textContent = cache.points.length + ' (caché)';
    } catch (e) {
        // ignore invalid cache
    }
}
