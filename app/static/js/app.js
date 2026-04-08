/**
 * GIO Telemetry — Main Application Entry
 * View switching, UI preferences, and global event wiring.
 */

var UI_PREFS_KEY = 'gio_ui_prefs_v3';
var uiPrefs = {
    activeView: 'realtime',
    realtimeDetailsOpen: true,
    historicalPanelOpen: true
};

function loadUIPreferences() {
    try {
        var raw = localStorage.getItem(UI_PREFS_KEY);
        if (!raw) return;
        var parsed = JSON.parse(raw);
        uiPrefs = Object.assign({}, uiPrefs, parsed || {});
    } catch (e) {
        // ignore corrupt storage
    }
}

function saveUIPreferences() {
    try {
        localStorage.setItem(UI_PREFS_KEY, JSON.stringify(uiPrefs));
    } catch (e) {
        // ignore storage limits
    }
}

function updateRealtimeDetailsButton() {
    var btn = document.getElementById('btn-toggle-rt-details');
    if (!btn) return;
    btn.textContent = uiPrefs.realtimeDetailsOpen ? 'Ocultar detalles' : 'Mostrar detalles';
}

function updateHistoricalPanelButton() {
    var btn = document.getElementById('btn-toggle-hist-panel');
    if (!btn) return;
    btn.textContent = uiPrefs.historicalPanelOpen ? 'Ocultar registros' : 'Mostrar registros';
}

function applyUIPreferences() {
    var realtimeView = document.getElementById('view-realtime');
    var histLayout = document.getElementById('hist-layout');

    if (realtimeView) {
        realtimeView.classList.toggle('details-collapsed', !uiPrefs.realtimeDetailsOpen);
    }

    if (histLayout) {
        histLayout.classList.toggle('panel-collapsed', !uiPrefs.historicalPanelOpen);
    }

    updateRealtimeDetailsButton();
    updateHistoricalPanelButton();
}

/**
 * Switch between Real-Time and Historical views.
 */
function switchView(view, skipPersist) {
    document.querySelectorAll('.view').forEach(function(v) { v.classList.remove('active'); });
    document.querySelectorAll('.nav-tab').forEach(function(t) {
        t.classList.remove('active');
        t.setAttribute('aria-selected', 'false');
    });

    document.getElementById('view-' + view).classList.add('active');
    var activeTab = document.getElementById('tab-' + (view === 'realtime' ? 'rt' : 'hist'));
    activeTab.classList.add('active');
    activeTab.setAttribute('aria-selected', 'true');

    if (!skipPersist) {
        uiPrefs.activeView = view;
        saveUIPreferences();
    }

    setTimeout(function() {
        if (view === 'realtime' && mapRT) mapRT.invalidateSize();
        if (view === 'historical' && mapHist) mapHist.invalidateSize();
    }, 90);
}

function toggleRealtimeDetails() {
    uiPrefs.realtimeDetailsOpen = !uiPrefs.realtimeDetailsOpen;
    applyUIPreferences();
    saveUIPreferences();

    if (mapRT) {
        setTimeout(function() { mapRT.invalidateSize(); }, 120);
    }
}

function toggleHistoricalPanel() {
    uiPrefs.historicalPanelOpen = !uiPrefs.historicalPanelOpen;
    applyUIPreferences();
    saveUIPreferences();

    if (mapHist) {
        setTimeout(function() { mapHist.invalidateSize(); }, 140);
    }
}

/**
 * Initialize everything when the page loads.
 */
(function init() {
    initMaps();
    loadUIPreferences();
    applyUIPreferences();

    // Restore soft state from local cache
    loadCachedRoute();
    if (typeof loadRealtimeState === 'function') {
        loadRealtimeState();
    }

    // Historical filters bootstrap
    if (typeof loadDeviceOptions === 'function') {
        loadDeviceOptions();
    }

    initRealtime();

    // Keep current modal values validated in real-time
    var startInput = document.getElementById('modal-start');
    var endInput = document.getElementById('modal-end');
    if (startInput) startInput.addEventListener('input', validateModalDates);
    if (endInput) endInput.addEventListener('input', validateModalDates);

    // Respect last active view from previous session
    switchView(uiPrefs.activeView || 'realtime', true);
})();
