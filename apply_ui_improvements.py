import sys

# --- 1. Modify app.js ---
with open('app/static/js/app.js', 'r') as f:
    app_js = f.read()

app_js = app_js.replace(
'''var defaultPrefs = {
    isDev: false,
    realtimeDetailsOpen: true,
    historicalPanelOpen: true,
    sampleMinutes: 3,
    routeMethod: 'route',
    deviceFilter: ''
};''',
'''var defaultPrefs = {
    isDev: false,
    realtimeDetailsOpen: false,
    historicalPanelOpen: false,
    sampleMinutes: 3,
    routeMethod: 'route',
    deviceFilter: ''
};''')

# Add toggleCard function
if 'function toggleCard' not in app_js:
    app_js += '''\n\nfunction toggleCard(headerEl) {
    var card = headerEl.closest('.card');
    if(card) {
        card.classList.toggle('collapsed');
    }
}\n'''

with open('app/static/js/app.js', 'w') as f:
    f.write(app_js)


# --- 2. Modify realtime.js ---
with open('app/static/js/realtime.js', 'r') as f:
    rt_js = f.read()

# Timestamp formatting & dev-only wrapper
rt_js = rt_js.replace(
'''    if (livePanel) {
        livePanel.innerHTML =
            '<div class="live-grid">' +
                '<div class="live-field"><div class="lbl">Timestamp</div><div class="val" style="font-size:0.74rem">' + data.timestamp + '</div></div>' +
                '<div class="live-field"><div class="lbl">Dispositivo</div><div class="val" style="font-size:0.78rem">' + data.device + '</div></div>' +
            '</div>' +
            '<div class="live-grid">' +
                '<div class="live-field"><div class="lbl">Latitud</div><div class="val">' + lat.toFixed(6) + '</div></div>' +
                '<div class="live-field"><div class="lbl">Longitud</div><div class="val">' + lon.toFixed(6) + '</div></div>' +
            '</div>' +
            '<div class="live-grid">' +
                '<div class="live-field"><div class="lbl">Trip ID</div><div class="val" style="font-size:0.75rem">' + getTripShortId(rtTripMeta.tripId) + '</div></div>' +
                '<div class="live-field"><div class="lbl">Estado</div><div class="val">' + tripStatusLabel + '</div></div>' +
            '</div>';
    }''',
'''    if (livePanel) {
        var cleanTs = data.timestamp ? data.timestamp.split('.')[0] : '—';
        livePanel.innerHTML =
            '<div class="live-grid">' +
                '<div class="live-field"><div class="lbl">Timestamp</div><div class="val" style="font-size:0.8rem; font-weight:600;">' + cleanTs + '</div></div>' +
                '<div class="live-field"><div class="lbl">Dispositivo</div><div class="val" style="font-size:0.8rem; font-weight:600; color:var(--blue-light);">' + data.device + '</div></div>' +
            '</div>' +
            '<div class="dev-only">' +
                '<div class="live-grid" style="margin-top:8px;">' +
                    '<div class="live-field"><div class="lbl">Latitud</div><div class="val">' + lat.toFixed(6) + '</div></div>' +
                    '<div class="live-field"><div class="lbl">Longitud</div><div class="val">' + lon.toFixed(6) + '</div></div>' +
                '</div>' +
                '<div class="live-grid" style="margin-top:8px;">' +
                    '<div class="live-field"><div class="lbl">Trip ID</div><div class="val" style="font-size:0.75rem">' + getTripShortId(rtTripMeta.tripId) + '</div></div>' +
                    '<div class="live-field"><div class="lbl">Estado</div><div class="val">' + tripStatusLabel + '</div></div>' +
                '</div>' +
            '</div>';
    }''')

rt_js = rt_js.replace(
'''function updateRealtimeSensorPanelValues() {
    var sensorPanel = document.getElementById('sensor-panel');
    if (!sensorPanel || !latestSensor) return;
    
    var dataRows = sensorPanel.querySelector('.sensor-data-rows');
    if (!dataRows) return;
    
    var ax = parseFloat(latestSensor.ax) || 0;
    var ay = parseFloat(latestSensor.ay) || 0;
    var az = parseFloat(latestSensor.az) || 0;
    var gx = parseFloat(latestSensor.gx) || 0;
    var gy = parseFloat(latestSensor.gy) || 0;
    var gz = parseFloat(latestSensor.gz) || 0;

    var numEvents = 0;
    var parsed = parseSensorPayload(latestSensor);
    if (parsed) numEvents = parsed.events.length;

    var eventStr = numEvents > 0 
        ? '<span class="badge badge-orange">' + numEvents + ' eventos</span>'
        : '<span class="badge" style="background:var(--border)">Sin eventos</span>';

    dataRows.innerHTML = 
        '<div class="live-grid">' +
            '<div class="live-field"><div class="lbl">AX / AY / AZ</div><div class="val" style="font-size:0.75rem">' + ax.toFixed(2) + ' / ' + ay.toFixed(2) + ' / ' + az.toFixed(2) + '</div></div>' +
            '<div class="live-field"><div class="lbl">GX / GY / GZ</div><div class="val" style="font-size:0.75rem">' + gx.toFixed(2) + ' / ' + gy.toFixed(2) + ' / ' + gz.toFixed(2) + '</div></div>' +
        '</div>' +
        '<div class="live-grid" style="margin-top:10px;">' +
            '<div class="live-field"><div class="lbl">Eventos</div><div class="val" style="font-size:0.75rem">' + eventStr + '</div></div>' +
            '<div class="live-field"><div class="lbl">Source</div><div class="val" style="font-size:0.75rem">' + (latestSensor.source || '—') + '</div></div>' +
        '</div>';
}''',
'''function updateRealtimeSensorPanelValues() {
    var sensorPanel = document.getElementById('sensor-panel');
    if (!sensorPanel || !latestSensor) return;
    
    var dataRows = sensorPanel.querySelector('.sensor-data-rows');
    if (!dataRows) return;
    
    var ax = parseFloat(latestSensor.ax) || 0;
    var ay = parseFloat(latestSensor.ay) || 0;
    var az = parseFloat(latestSensor.az) || 0;
    var gx = parseFloat(latestSensor.gx) || 0;
    var gy = parseFloat(latestSensor.gy) || 0;
    var gz = parseFloat(latestSensor.gz) || 0;

    var numEvents = 0;
    var parsed = parseSensorPayload(latestSensor);
    if (parsed) numEvents = parsed.events.length;

    var eventStr = numEvents > 0 
        ? '<span class="badge badge-orange">' + numEvents + ' eventos</span>'
        : '<span class="badge" style="background:var(--border)">Sin eventos</span>';

    dataRows.innerHTML = 
        '<div class="dev-only">' +
        '<div class="live-grid">' +
            '<div class="live-field"><div class="lbl">AX / AY / AZ</div><div class="val" style="font-size:0.75rem">' + ax.toFixed(2) + ' / ' + ay.toFixed(2) + ' / ' + az.toFixed(2) + '</div></div>' +
            '<div class="live-field"><div class="lbl">GX / GY / GZ</div><div class="val" style="font-size:0.75rem">' + gx.toFixed(2) + ' / ' + gy.toFixed(2) + ' / ' + gz.toFixed(2) + '</div></div>' +
        '</div>' +
        '<div class="live-grid" style="margin-top:10px;">' +
            '<div class="live-field"><div class="lbl">Eventos</div><div class="val" style="font-size:0.75rem">' + eventStr + '</div></div>' +
            '<div class="live-field"><div class="lbl">Source</div><div class="val" style="font-size:0.75rem">' + (latestSensor.source || '—') + '</div></div>' +
        '</div>' +
        '</div>';
}''')

with open('app/static/js/realtime.js', 'w') as f:
    f.write(rt_js)

print("JS changes applied.")
