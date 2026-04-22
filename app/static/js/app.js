/**
 * GIO Telemetry — Main Application Entry
 * View switching, UI preferences, and global event wiring.
 */

var UI_PREFS_KEY = 'gio_ui_prefs_v3';
var uiPrefs = {
    activeView: 'realtime',
    realtimeDetailsOpen: true,
    historicalPanelOpen: true,
    realtimeMobilePane: 'map',
    historicalMobilePane: 'map'
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
    var panelLabel = 'registros';
    if (typeof getHistoricalPanelTitle === 'function') {
        panelLabel = getHistoricalPanelTitle();
    }
    btn.textContent = uiPrefs.historicalPanelOpen
        ? ('Ocultar ' + panelLabel)
        : ('Mostrar ' + panelLabel);
}

function updateMobilePaneButtons() {
    var rtMapBtn = document.getElementById('rt-pane-map-btn');
    var rtInfoBtn = document.getElementById('rt-pane-info-btn');
    var histMapBtn = document.getElementById('hist-pane-map-btn');
    var histInfoBtn = document.getElementById('hist-pane-info-btn');

    if (rtMapBtn) rtMapBtn.classList.toggle('active', uiPrefs.realtimeMobilePane !== 'info');
    if (rtInfoBtn) rtInfoBtn.classList.toggle('active', uiPrefs.realtimeMobilePane === 'info');
    if (histMapBtn) histMapBtn.classList.toggle('active', uiPrefs.historicalMobilePane !== 'info');
    if (histInfoBtn) histInfoBtn.classList.toggle('active', uiPrefs.historicalMobilePane === 'info');
}

function applyMobilePanes() {
    var rtView = document.getElementById('view-realtime');
    var histView = document.getElementById('view-historical');

    if (rtView) {
        rtView.classList.toggle('mobile-pane-map', uiPrefs.realtimeMobilePane !== 'info');
        rtView.classList.toggle('mobile-pane-info', uiPrefs.realtimeMobilePane === 'info');
    }

    if (histView) {
        histView.classList.toggle('mobile-pane-map', uiPrefs.historicalMobilePane !== 'info');
        histView.classList.toggle('mobile-pane-info', uiPrefs.historicalMobilePane === 'info');
    }

    updateMobilePaneButtons();
}

function switchRealtimeMobilePane(pane) {
    uiPrefs.realtimeMobilePane = pane === 'info' ? 'info' : 'map';
    applyMobilePanes();
    saveUIPreferences();

    if (uiPrefs.realtimeMobilePane === 'map' && mapRT) {
        setTimeout(function() { mapRT.invalidateSize(); }, 140);
    }
}

function switchHistoricalMobilePane(pane) {
    uiPrefs.historicalMobilePane = pane === 'info' ? 'info' : 'map';
    applyMobilePanes();
    saveUIPreferences();

    if (uiPrefs.historicalMobilePane === 'map' && mapHist) {
        setTimeout(function() {
            mapHist.invalidateSize();
            if (typeof refreshHistoricLayout === 'function') {
                refreshHistoricLayout(true);
            }
        }, 160);
    }
}

function updateLayoutOffsets() {
    var nav = document.querySelector('.top-nav');
    var histView = document.getElementById('view-historical');
    if (!histView) return;

    var toolbar = histView.querySelector('.historical-toolbar');
    var help = document.getElementById('hist-help');

    var navH = nav ? nav.offsetHeight : 56;
    var toolbarH = toolbar ? toolbar.offsetHeight : 64;
    var helpH = help ? help.offsetHeight : 18;
    if (toolbarH < 20) toolbarH = 64;
    if (helpH < 8) helpH = 18;
    var desktopOffset = navH + toolbarH + helpH + 54;

    document.documentElement.style.setProperty('--layout-offset-desktop', desktopOffset + 'px');
    document.documentElement.style.setProperty('--layout-offset-tablet', (desktopOffset + 22) + 'px');
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

    applyMobilePanes();
    updateRealtimeDetailsButton();
    updateHistoricalPanelButton();
    updateLayoutOffsets();
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

    updateLayoutOffsets();

    setTimeout(function() {
        if (view === 'realtime' && mapRT) mapRT.invalidateSize();
        if (view === 'historical' && mapHist) {
            mapHist.invalidateSize();
            if (typeof refreshHistoricLayout === 'function') {
                refreshHistoricLayout(true);
            }
        }
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

function toggleMobileFilters() {
    var histView = document.getElementById('view-historical');
    if (!histView) return;
    var isOpen = histView.classList.toggle('filters-open');
    var btn = document.getElementById('btn-toggle-mobile-filters');
    if (btn) btn.classList.toggle('btn-active-query', isOpen);
    updateLayoutOffsets();
    if (!isOpen && mapHist) {
        setTimeout(function() { mapHist.invalidateSize(); }, 120);
    }
}

function toggleHistoricalPanel() {
    uiPrefs.historicalPanelOpen = !uiPrefs.historicalPanelOpen;
    applyUIPreferences();
    saveUIPreferences();

    if (mapHist) {
        setTimeout(function() {
            mapHist.invalidateSize();
            if (typeof refreshHistoricLayout === 'function') {
                refreshHistoricLayout(true);
            }
        }, 260);
    }
}

function openHelpModal(section) {
    var overlay = document.getElementById('help-overlay');
    if (!overlay) return;
    if (section) switchHelpSection(section);
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
}

function closeHelpModal() {
    var overlay = document.getElementById('help-overlay');
    if (!overlay) return;
    overlay.classList.remove('open');
    if (!document.getElementById('modal-overlay').classList.contains('open')) {
        document.body.style.overflow = '';
    }
}

function closeHelpOutside(e) {
    if (e.target === document.getElementById('help-overlay')) {
        closeHelpModal();
    }
}

function switchHelpSection(section) {
    var valid = ['general', 'historical', 'steps', 'mobile'];
    var safe = valid.indexOf(section) >= 0 ? section : 'general';

    valid.forEach(function(key) {
        var tab = document.getElementById('help-tab-' + key);
        var panel = document.getElementById('help-section-' + key);
        if (tab) tab.classList.toggle('active', key === safe);
        if (panel) panel.classList.toggle('active', key === safe);
    });
}

// ══════════════════════════════════════════
//  CORRECCIÓN PROFESOR A2: Toggle modo técnico
// ══════════════════════════════════════════

var DEV_MODE_KEY = 'gio_dev_mode_v1';

function initDevMode() {
    try {
        var saved = localStorage.getItem(DEV_MODE_KEY);
        if (saved === 'true') {
            document.body.classList.add('dev-mode');
            var btn = document.getElementById('dev-toggle');
            if (btn) btn.classList.add('active');
        }
    } catch (e) {
        // ignore storage issues
    }
}

function toggleDevMode() {
    var isNowDev = document.body.classList.toggle('dev-mode');
    var btn = document.getElementById('dev-toggle');
    if (btn) btn.classList.toggle('active', isNowDev);
    try {
        localStorage.setItem(DEV_MODE_KEY, String(isNowDev));
    } catch (e) {
        // ignore storage limits
    }
    showToast(isNowDev ? 'Modo técnico activado' : 'Modo técnico desactivado');
}

/**
 * Initialize everything when the page loads.
 */
(function init() {
    initMaps();
    loadUIPreferences();
    applyUIPreferences();
    initDevMode();  // === CORRECCIÓN PROFESOR A2 ===

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

    // Keep layout metrics synced with responsive toolbar/nav wraps
    window.addEventListener('resize', function() {
        updateLayoutOffsets();
        if (mapHist && (uiPrefs.activeView || 'realtime') === 'historical') {
            mapHist.invalidateSize();
        }
    });

    var histLayout = document.getElementById('hist-layout');
    if (histLayout) {
        histLayout.addEventListener('transitionend', function(evt) {
            if (!evt || evt.propertyName.indexOf('grid-template-columns') === -1) return;
            if (!mapHist) return;
            mapHist.invalidateSize();
            if (typeof refreshHistoricLayout === 'function') {
                refreshHistoricLayout(true);
            }
        });
    }
})();

