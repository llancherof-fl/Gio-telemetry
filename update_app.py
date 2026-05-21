import sys

with open('app/static/js/app.js', 'r') as f:
    content = f.read()

# Replace toggleRealtimeDetails
content = content.replace(
'''function toggleRealtimeDetails() {
    uiPrefs.realtimeDetailsOpen = !uiPrefs.realtimeDetailsOpen;
    applyUIPreferences();
    saveUIPreferences();

    if (mapRT) {
        setTimeout(function() { mapRT.invalidateSize(); }, 120);
    }
}''',
'''function toggleRealtimeDetails() {
    uiPrefs.realtimeDetailsOpen = !uiPrefs.realtimeDetailsOpen;
    applyUIPreferences();
    saveUIPreferences();

    if (mapRT) {
        setTimeout(function() {
            mapRT.invalidateSize();
        }, 320); // match transition duration
    }
}''')

# Update applyUIPreferences
content = content.replace(
'''    if (realtimeView) {
        realtimeView.classList.toggle('details-collapsed', !uiPrefs.realtimeDetailsOpen);
    }''',
'''    var rtGrid = document.getElementById('rt-grid');
    if (rtGrid) {
        rtGrid.classList.toggle('panel-collapsed', !uiPrefs.realtimeDetailsOpen);
    }''')

# Update toggleHistoricalPanel
content = content.replace(
'''    if (mapHist) {
        setTimeout(function() {
            mapHist.invalidateSize();
            if (typeof refreshHistoricLayout === 'function') {
                refreshHistoricLayout({ preserveView: true, refit: false, skipAnimation: true });
            }
        }, 260);
    }''',
'''    if (mapHist) {
        setTimeout(function() {
            mapHist.invalidateSize();
            if (typeof refreshHistoricLayout === 'function') {
                refreshHistoricLayout({ preserveView: true, refit: false, skipAnimation: true });
            }
        }, 320); // match transition duration
    }''')

with open('app/static/js/app.js', 'w') as f:
    f.write(content)

print("JS Updated")
