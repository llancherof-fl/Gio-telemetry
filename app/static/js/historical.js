/**
 * GIO Telemetry — Historical Search Module
 * Date range search with validation, OSRM routing with spline fallback,
 * lazy rendering, and modal management.
 */

var histMarkers = [];
var routeLineHist = null;
var currentRange = { start: null, end: null };
var CACHE_KEY = 'gio_hist_cache';
var CACHE_PTS = 20;

// ══════════════════════════════════════════
//  QUICK RANGE
// ══════════════════════════════════════════

function applyQuickRange(val) {
    if (!val) return;
    var now = new Date();
    var start;
    if (val === '30m') start = new Date(now - 30 * 60 * 1000);
    else if (val === '1h') start = new Date(now - 60 * 60 * 1000);
    else if (val === '3h') start = new Date(now - 3 * 60 * 60 * 1000);
    else if (val === '6h') start = new Date(now - 6 * 60 * 60 * 1000);
    else if (val === 'today') { start = new Date(now); start.setHours(0, 0, 0, 0); }
    else if (val === 'yesterday') {
        start = new Date(now); start.setDate(start.getDate() - 1); start.setHours(0, 0, 0, 0);
        now = new Date(start); now.setHours(23, 59, 59, 999);
    }
    else if (val === 'week') { start = new Date(now); start.setDate(start.getDate() - 7); }
    currentRange.start = toLocalISO(start);
    currentRange.end = toLocalISO(val === 'yesterday' ? now : new Date());
}


// ══════════════════════════════════════════
//  HISTORIC QUERY
// ══════════════════════════════════════════

function runHistoricQuery() {
    if (!currentRange.start || !currentRange.end) {
        showToast('Selecciona un rango de tiempo primero');
        return;
    }

    var status = document.getElementById('hist-status');
    status.textContent = 'Buscando...';
    status.style.color = 'var(--blue-bright)';

    document.getElementById('results-list').innerHTML =
        '<div class="no-data"><div class="skeleton" style="width:60%;height:12px;margin:8px auto"></div><div class="skeleton" style="width:40%;height:12px;margin:8px auto"></div></div>';
    document.getElementById('results-count').textContent = '...';

    var url = '/api/history-range?start=' + encodeURIComponent(currentRange.start) + '&end=' + encodeURIComponent(currentRange.end);

    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(response) {
            status.textContent = '';

            // Handle new enriched response format
            var data = response.data || response;
            var meta = response.meta || {};

            if (meta.clamped) {
                showToast('Fecha fin ajustada al momento actual');
            }

            if (!data || data.length === 0) {
                document.getElementById('results-list').innerHTML =
                    '<div class="no-data"><div class="no-data-icon">' + SVG_INBOX + '</div>Sin registros en ese período</div>';
                document.getElementById('results-count').textContent = '0';
                return;
            }

            renderHistoricResults(data);
            drawHistoricRoute(data);
            saveToCache(data);
        })
        .catch(function(err) {
            status.textContent = 'Error';
            status.style.color = '#ff6b6b';

            // Check if it's a validation error
            if (err && err.message) {
                showToast(err.message);
            } else {
                showToast('Error al consultar la base de datos');
            }
        });
}


// ══════════════════════════════════════════
//  RESULTS RENDERING (with lazy loading)
// ══════════════════════════════════════════

function renderHistoricResults(data) {
    document.getElementById('results-count').textContent = data.length + ' reg.';
    var reversed = data.slice().reverse();

    // Render first 50 immediately, rest lazily
    var BATCH = 50;
    var initialBatch = reversed.slice(0, BATCH);
    var remaining = reversed.slice(BATCH);

    var html = renderResultBatch(initialBatch, data.length, 0);
    var listEl = document.getElementById('results-list');
    listEl.innerHTML = html;

    // Lazy load remaining with IntersectionObserver
    if (remaining.length > 0) {
        var sentinel = document.createElement('div');
        sentinel.id = 'lazy-sentinel';
        sentinel.style.height = '1px';
        listEl.appendChild(sentinel);

        var loaded = BATCH;
        var observer = new IntersectionObserver(function(entries) {
            if (entries[0].isIntersecting && loaded < reversed.length) {
                var nextBatch = reversed.slice(loaded, loaded + BATCH);
                var batchHtml = renderResultBatch(nextBatch, data.length, loaded);

                sentinel.insertAdjacentHTML('beforebegin', batchHtml);
                loaded += nextBatch.length;

                if (loaded >= reversed.length) {
                    observer.disconnect();
                    sentinel.remove();
                }
            }
        }, { root: listEl, threshold: 0.1 });

        observer.observe(sentinel);
    }
}

function renderResultBatch(batch, total, offset) {
    return batch.map(function(r, i) {
        var idx = total - (offset + i);
        return '<div class="result-item" onclick="flyToPoint(' + r.lat + ',' + r.lon + ')">' +
            '<div class="result-index">' + idx + '</div>' +
            '<div class="result-info">' +
                '<div class="result-coords">' + parseFloat(r.lat).toFixed(5) + ', ' + parseFloat(r.lon).toFixed(5) + '</div>' +
                '<div class="result-device">' + r.device + '</div>' +
            '</div>' +
            '<div class="result-time">' + r.timestamp.substring(11, 16) + '</div>' +
        '</div>';
    }).join('');
}

function flyToPoint(lat, lon) {
    mapHist.flyTo([lat, lon], 16, { duration: 0.6 });
}


// ══════════════════════════════════════════
//  HISTORIC ROUTE DRAWING
// ══════════════════════════════════════════

function drawHistoricRoute(data) {
    // Clean previous
    histMarkers.forEach(function(m) { mapHist.removeLayer(m); });
    histMarkers = [];
    if (routeLineHist) { mapHist.removeLayer(routeLineHist); routeLineHist = null; }
    if (data.length === 0) return;

    // Start & end markers
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

    // Draw interim dashed line (visible while OSRM loads)
    var smoothed = smoothPath(points, { segments: 10, tension: 0.5 });
    routeLineHist = L.polyline(smoothed, {
        color: '#748ffc', weight: 3, opacity: 0.6, dashArray: '8 5'
    }).addTo(mapHist);
    mapHist.fitBounds(routeLineHist.getBounds(), { padding: [30, 30] });

    // Try OSRM for the real route
    var status = document.getElementById('hist-status');
    status.textContent = 'Calculando ruta...';
    status.style.color = 'var(--blue-bright)';

    drawSmartRoute(mapHist, points, {
        color: '#748ffc', weight: 3.5, opacity: 0.85
    }).then(function(line) {
        status.textContent = '';
        if (line) {
            // Remove the interim dashed line, replace with the smart one
            if (routeLineHist) mapHist.removeLayer(routeLineHist);
            routeLineHist = line;
            mapHist.fitBounds(routeLineHist.getBounds(), { padding: [30, 30] });
        } else {
            // Smart route returned null (shouldn't happen, but safety)
            if (routeLineHist) {
                routeLineHist.setStyle({ opacity: 0.8, dashArray: null });
            }
        }
    });
}


// ══════════════════════════════════════════
//  CLEAR
// ══════════════════════════════════════════

function clearHistoric() {
    histMarkers.forEach(function(m) { mapHist.removeLayer(m); });
    histMarkers = [];
    if (routeLineHist) { mapHist.removeLayer(routeLineHist); routeLineHist = null; }
    document.getElementById('results-list').innerHTML =
        '<div class="no-data"><div class="no-data-icon">' + SVG_SEARCH + '</div>Selecciona un rango y presiona Buscar</div>';
    document.getElementById('results-count').textContent = '—';
    document.getElementById('hist-status').textContent = '';
    document.getElementById('quick-select').value = '';
    currentRange = { start: null, end: null };
}


// ══════════════════════════════════════════
//  MODAL — Date Range with Validation
// ══════════════════════════════════════════

function openModal() {
    var now = new Date();
    var oneHourAgo = new Date(now - 60 * 60 * 1000);
    var startInput = document.getElementById('modal-start');
    var endInput = document.getElementById('modal-end');

    startInput.value = toLocalISO(oneHourAgo);
    endInput.value = toLocalISO(now);

    // Set max to now (prevent future dates)
    var nowISO = toLocalISO(now);
    endInput.max = nowISO;

    validateModalDates();

    document.getElementById('modal-overlay').classList.add('open');
    document.body.style.overflow = 'hidden';
}

function closeModal() {
    document.getElementById('modal-overlay').classList.remove('open');
    document.body.style.overflow = '';
}

function closeModalOutside(e) {
    if (e.target === document.getElementById('modal-overlay')) closeModal();
}

function setQuick(val) {
    applyQuickRange(val);
    document.getElementById('modal-start').value = currentRange.start;
    document.getElementById('modal-end').value = currentRange.end;
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

    // Reset state
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

    // Check: start must be before end
    if (startDate >= endDate) {
        startInput.classList.add('input-error');
        endInput.classList.add('input-error');
        if (errorEl) {
            errorEl.textContent = '⚠ La fecha de inicio debe ser anterior a la fecha fin';
            errorEl.classList.add('show');
        }
        if (applyBtn) applyBtn.disabled = true;
        return false;
    }

    // Check: end shouldn't be too far in the future
    if (endDate > new Date(now.getTime() + 60000)) {
        endInput.classList.add('input-error');
        if (errorEl) {
            errorEl.textContent = '⚠ La fecha fin no puede ser futura';
            errorEl.classList.add('show');
        }
        if (applyBtn) applyBtn.disabled = true;
        return false;
    }

    // Update min/max constraints
    endInput.min = startVal;

    if (applyBtn) applyBtn.disabled = false;
    return true;
}


// ══════════════════════════════════════════
//  LOCAL CACHE
// ══════════════════════════════════════════

function saveToCache(data) {
    try {
        localStorage.setItem(CACHE_KEY, JSON.stringify({
            savedAt: new Date().toISOString(),
            points: data.slice(-CACHE_PTS)
        }));
    } catch (e) {}
}

function loadCachedRoute() {
    try {
        var raw = localStorage.getItem(CACHE_KEY);
        if (!raw) return;
        var cache = JSON.parse(raw);
        if (!cache.points || cache.points.length < 2) return;
        var points = cache.points.map(function(r) { return [parseFloat(r.lat), parseFloat(r.lon)]; });

        // Use spline for cached route too
        var smoothed = smoothPath(points, { segments: 8, tension: 0.5 });
        var cachedLine = L.polyline(smoothed, { color: '#748ffc', weight: 2, opacity: 0.3, dashArray: '6 4' }).addTo(mapHist);
        mapHist.fitBounds(cachedLine.getBounds(), { padding: [40, 40] });

        var savedAt = new Date(cache.savedAt).toLocaleString('es-CO');
        document.getElementById('results-list').innerHTML =
            '<div class="no-data" style="padding:16px;font-size:0.78rem">' +
                '<div class="no-data-icon">' + SVG_PACKAGE + '</div>' +
                'Última búsqueda del caché<br>' +
                '<span style="color:var(--text-muted);font-size:0.72rem">' + savedAt + '</span><br><br>' +
                '<span style="color:var(--text-muted)">Haz una nueva búsqueda para actualizar</span>' +
            '</div>';
        document.getElementById('results-count').textContent = cache.points.length + ' (caché)';
    } catch (e) {}
}
