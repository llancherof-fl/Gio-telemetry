/**
 * GIO Telemetry — Main Application Entry
 * View switching, initialization, and global event wiring.
 */

/**
 * Switch between Real-Time and Historical views.
 */
function switchView(view) {
    document.querySelectorAll('.view').forEach(function(v) { v.classList.remove('active'); });
    document.querySelectorAll('.nav-tab').forEach(function(t) { t.classList.remove('active'); });
    document.getElementById('view-' + view).classList.add('active');
    document.getElementById('tab-' + (view === 'realtime' ? 'rt' : 'hist')).classList.add('active');

    setTimeout(function() {
        if (view === 'realtime' && mapRT) mapRT.invalidateSize();
        if (view === 'historical' && mapHist) mapHist.invalidateSize();
    }, 80);
}

/**
 * Initialize everything when the page loads.
 */
(function init() {
    initMaps();
    loadCachedRoute();
    initRealtime();

    // Wire up date validation listeners on modal inputs
    var startInput = document.getElementById('modal-start');
    var endInput = document.getElementById('modal-end');
    if (startInput) startInput.addEventListener('input', validateModalDates);
    if (endInput) endInput.addEventListener('input', validateModalDates);
})();
