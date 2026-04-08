/**
 * GIO Telemetry — Historical Search Module
 * Date range search with validation, device filters, smart sampling,
 * request cancellation and robust map/list cleanup.
 */

var histMarkers = [];
var routeLineHist = null;
var historicRouteBounds = null;
var currentRange = { start: null, end: null };
var CACHE_KEY = 'gio_hist_cache_v2';
var CACHE_PTS = 30;
var FILTERS_KEY = 'gio_hist_filters_v1';

var histFetchController = null;
var histRouteController = null;
var histListObserver = null;
var histQueryToken = 0;

// ══════════════════════════════════════════
//  FILTERS
// ══════════════════════════════════════════

function loadDeviceOptions() {
    var select = document.getElementById('device-select');
    if (!select) return;

    restoreHistoryFilters();
    var preferredDevice = select.value;

    fetch('/api/devices')
        .then(function(r) { return r.json(); })
        .then(function(payload) {
            var devices = (payload && payload.devices) || [];
            var currentValue = select.value || preferredDevice;

            select.innerHTML = '<option value="">Todos los vehículos</option>';
            devices.forEach(function(device) {
                if (!device) return;
                var option = document.createElement('option');
                option.value = device;
                option.textContent = device;
                select.appendChild(option);
            });

            if (currentValue && Array.from(select.options).some(function(o) { return o.value === currentValue; })) {
                select.value = currentValue;
            }
        })
        .catch(function() {
            // Fallback silently to "all devices"
        });

    select.addEventListener('change', saveHistoryFilters);

    var sampleSelect = document.getElementById('sample-select');
    var customInput = document.getElementById('sample-custom-minutes');
    if (sampleSelect) {
        sampleSelect.addEventListener('change', function() {
            syncSampleCustomUi();
            saveHistoryFilters();
        });
    }
    if (customInput) {
        customInput.addEventListener('input', function() {
            sanitizeCustomSampleInput();
            saveHistoryFilters();
        });
    }

    syncSampleCustomUi();
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
        var deviceSelect = document.getElementById('device-select');
        var customInput = document.getElementById('sample-custom-minutes');

        if (sampleSelect && saved.sampleMinutes) {
            if (saved.sampleMode === 'custom') {
                sampleSelect.value = 'custom';
            } else {
                sampleSelect.value = String(saved.sampleMinutes);
            }
        }
        if (deviceSelect && saved.device) {
            deviceSelect.value = saved.device;
        }
        if (customInput && saved.sampleCustomMinutes) {
            customInput.value = String(saved.sampleCustomMinutes);
        }

        syncSampleCustomUi();
    } catch (e) {
        // ignore corrupt storage
    }
}

function saveHistoryFilters() {
    try {
        var sampleSelect = document.getElementById('sample-select');
        var deviceSelect = document.getElementById('device-select');
        var customInput = document.getElementById('sample-custom-minutes');

        localStorage.setItem(FILTERS_KEY, JSON.stringify({
            sampleMinutes: getSampleMinutes(),
            sampleMode: sampleSelect ? sampleSelect.value : '3',
            sampleCustomMinutes: customInput ? sanitizeCustomSampleInput() : 3,
            device: deviceSelect ? deviceSelect.value : ''
        }));
    } catch (e) {
        // ignore storage failures
    }
}

function getSelectedDevice() {
    var select = document.getElementById('device-select');
    return select ? (select.value || '').trim() : '';
}

function countDistinctDevices(rows) {
    if (!rows || !rows.length) return 0;
    var seen = {};
    var count = 0;
    for (var i = 0; i < rows.length; i++) {
        var key = (rows[i].device || '').trim() || '__unknown__';
        if (seen[key]) continue;
        seen[key] = true;
        count += 1;
    }
    return count;
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
        return;
    } else if (val === 'week') {
        start = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    }

    currentRange.start = toLocalISO(start);
    currentRange.end = toLocalISO(new Date());
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
    setTimeout(function() {
        fitHistoricBounds(historicRouteBounds, !skipAnimation);
    }, 40);
}

function getHistoryUrl() {
    var sampleMinutes = getSampleMinutes();
    var device = getSelectedDevice();
    var params = [
        'start=' + encodeURIComponent(currentRange.start),
        'end=' + encodeURIComponent(currentRange.end),
        'sample_minutes=' + encodeURIComponent(String(sampleMinutes)),
        'limit=2500'
    ];

    if (device) {
        params.push('device=' + encodeURIComponent(device));
    }

    return '/api/history-range?' + params.join('&');
}

function runHistoricQuery() {
    if (!currentRange.start || !currentRange.end) {
        showToast('Selecciona un rango de tiempo primero');
        return;
    }

    abortHistoricRequests();
    saveHistoryFilters();

    histQueryToken += 1;
    var token = histQueryToken;

    setHistoricStatus('Buscando registros...', 'var(--blue-strong)');

    document.getElementById('results-list').innerHTML =
        '<div class="no-data"><div class="skeleton" style="width:64%;height:12px;margin:8px auto"></div><div class="skeleton" style="width:42%;height:12px;margin:8px auto"></div></div>';
    document.getElementById('results-count').textContent = '...';

    histFetchController = new AbortController();

    fetch(getHistoryUrl(), { signal: histFetchController.signal })
        .then(function(r) {
            return r.json().then(function(body) {
                if (!r.ok) {
                    var msg = (body && body.error) ? body.error : 'Error al consultar histórico';
                    throw new Error(msg);
                }
                return body;
            });
        })
        .then(function(response) {
            if (token !== histQueryToken) return;

            var data = response.data || [];
            var meta = response.meta || {};
            var selectedDevice = getSelectedDevice();
            var distinctDevices = countDistinctDevices(data);

            if (meta.clamped) {
                showToast('Fecha fin ajustada al momento actual');
            }
            if (meta.dropped_outliers || meta.dropped_invalid) {
                var dropped = (meta.dropped_outliers || 0) + (meta.dropped_invalid || 0);
                showToast('Se omitieron ' + dropped + ' puntos atípicos o inválidos');
            }
            if (!selectedDevice && distinctDevices > 1) {
                showToast('Vista combinada: selecciona un vehículo para una ruta más precisa');
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

            var sampledInfo = ' · precisión ' + getSampleLabel();
            var cleanedInfo = meta.dropped_outliers
                ? ' · depurados ' + meta.dropped_outliers
                : '';
            setHistoricStatus((meta.count || data.length) + ' puntos' + sampledInfo + cleanedInfo, 'var(--green)');

            if (meta.has_more) {
                showToast('Se alcanzó el límite de consulta. Ajusta rango o filtro de vehículo.');
            }
        })
        .catch(function(err) {
            if (err && err.name === 'AbortError') return;

            clearHistoricLayers();
            document.getElementById('results-list').innerHTML =
                '<div class="no-data"><div class="no-data-icon">' + SVG_SEARCH + '</div>No se pudo cargar el histórico</div>';
            document.getElementById('results-count').textContent = '—';

            setHistoricStatus('Error en consulta', 'var(--red)');
            showToast(err && err.message ? err.message : 'Error al consultar la base de datos');
        });
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

    histListObserver = new IntersectionObserver(function(entries) {
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
    return batch.map(function(r, i) {
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
    histMarkers.forEach(function(m) { mapHist.removeLayer(m); });
    histMarkers = [];

    if (routeLineHist) {
        mapHist.removeLayer(routeLineHist);
        routeLineHist = null;
    }

    historicRouteBounds = null;
    updateHistoricFitButtonState(false);
}

function drawHistoricRoute(data, token) {
    clearHistoricLayers();
    if (!data.length) return;

    var first = data[0];
    var last = data[data.length - 1];

    histMarkers.push(
        L.marker([first.lat, first.lon], { icon: makeStartIcon() })
            .addTo(mapHist)
            .bindPopup('<b>Inicio</b><br>' + first.timestamp.substring(0, 16))
    );

    if (data.length > 1) {
        histMarkers.push(
            L.marker([last.lat, last.lon], { icon: makeEndIcon() })
                .addTo(mapHist)
                .bindPopup('<b>Fin</b><br>' + last.timestamp.substring(0, 16))
        );
    }

    var points = data.map(function(r) { return [parseFloat(r.lat), parseFloat(r.lon)]; });
    var basePoints = points.length > 550 ? samplePoints(points, 550) : points;
    var previewSegments = splitByLargeJumps(basePoints, 28);
    if (!previewSegments.length) {
        previewSegments = [basePoints];
    }
    var preview = previewSegments.map(function(segment) {
        return smoothPath(segment, { segments: 7, tension: 0.45 });
    }).filter(function(segment) {
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

    histRouteController = new AbortController();

    drawSmartRoute(mapHist, basePoints, {
        color: '#5f95ff',
        weight: 3.6,
        opacity: 0.88
    }, {
        signal: histRouteController.signal,
        maxJumpKm: 28,
        maxInputPoints: 260,
        minPointDistanceMeters: 3,
        chunked: true,
        chunkWaypoints: 25,
        chunkOverlap: 1,
        maxChunksPerSegment: 9
    }).then(function(line) {
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

    var maxRangeMs = 14 * 24 * 60 * 60 * 1000;
    if ((endDate.getTime() - startDate.getTime()) > maxRangeMs) {
        endInput.classList.add('input-error');
        if (errorEl) {
            errorEl.textContent = 'Selecciona un rango máximo de 14 días para mantener respuesta rápida';
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
            device: getSelectedDevice(),
            sampleMinutes: getSampleMinutes()
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

        var points = cache.points.map(function(r) {
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
