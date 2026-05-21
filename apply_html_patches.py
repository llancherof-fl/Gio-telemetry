import sys

with open('app/templates/index.html', 'r') as f:
    html = f.read()

# 1. Redesign view-toolbar
html = html.replace(
'''<div class="view-toolbar">
        <div class="toolbar-group">
            <span class="status-pill dev-only">
                <span class="status-dot" id="rt-status-dot"></span>
                <span id="rt-connection-label">Conectando señal GPS...</span>
            </span>
            <span class="toolbar-note dev-only" id="rt-follow-note">Seguimiento automático activo</span>
        </div>
        <div class="toolbar-group">
            <select id="rt-route-method" class="dev-only" title="Método de ajuste de ruta">
                <option value="route">Route (rápido)</option>
                <option value="match">Match (más fiel)</option>
            </select>
            <button class="btn btn-outline" id="btn-follow-toggle" onclick="toggleAutoFollow()">Seguimiento: ON</button>
            <button class="btn btn-outline" id="btn-recenter" onclick="recenterVehicle()" disabled>Recentrar</button>
            <button class="btn btn-outline" id="btn-toggle-rt-details" onclick="toggleRealtimeDetails()">Ocultar detalles</button>
        </div>
    </div>''',
'''<div class="view-toolbar" style="flex-wrap: wrap; gap: 8px;">
        <div class="toolbar-group" style="flex: 1; min-width: 200px;">
            <span class="status-pill dev-only">
                <span class="status-dot" id="rt-status-dot"></span>
                <span id="rt-connection-label">Conectando señal GPS...</span>
            </span>
            <span class="toolbar-note dev-only" id="rt-follow-note">Seguimiento automático activo</span>
        </div>
        <div class="toolbar-group">
            <select id="rt-route-method" class="dev-only" title="Método de ajuste de ruta" style="padding: 4px; font-size: 0.75rem;">
                <option value="route">Route</option>
                <option value="match">Match</option>
            </select>
            <button class="btn btn-outline btn-sm" id="btn-follow-toggle" onclick="toggleAutoFollow()" style="font-size: 0.75rem; padding: 4px 8px;">Seguimiento: ON</button>
            <button class="btn btn-outline btn-sm" id="btn-recenter" onclick="recenterVehicle()" disabled style="font-size: 0.75rem; padding: 4px 8px;">Recentrar</button>
            <button class="btn btn-outline btn-sm" id="btn-toggle-rt-details" onclick="toggleRealtimeDetails()" style="font-size: 0.75rem; padding: 4px 8px;">Ocultar detalles</button>
        </div>
    </div>''')

# 2. Make live-panel collapsable (Card 1)
html = html.replace(
'''<div class="card" style="display:flex;flex-direction:column;">
                <div class="card-header">
                    <span class="badge badge-blue">LIVE</span>
                    Última posición
                </div>
                <div class="live-panel" id="live-panel">''',
'''<div class="card" style="display:flex;flex-direction:column;">
                <div class="card-header" onclick="toggleCard(this)" style="cursor:pointer; display:flex; justify-content:space-between; align-items:center;">
                    <div><span class="badge badge-blue">LIVE</span> Última posición</div>
                    <svg class="chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="transition: transform 0.3s;"><polyline points="6 9 12 15 18 9"></polyline></svg>
                </div>
                <div class="card-body">
                <div class="live-panel" id="live-panel">''')

# Close card body 1
html = html.replace(
'''</svg>
                        </div>
                        Cargando última posición...
                    </div>
                </div>
            </div>

            <div class="card" style="display:flex;flex-direction:column;">''',
'''</svg>
                        </div>
                        Cargando última posición...
                    </div>
                </div>
                </div>
            </div>

            <div class="card dev-only" style="display:flex;flex-direction:column;">''')

# 3. Make route-info collapsable and dev-only (Card 2)
html = html.replace(
'''<div class="card dev-only" style="display:flex;flex-direction:column;">
                <div class="card-header">
                    <span class="badge badge-orange">RUTA</span>
                    Recorrido de la sesión
                </div>
                <div class="live-panel" id="route-info">''',
'''<div class="card dev-only" style="display:flex;flex-direction:column;">
                <div class="card-header" onclick="toggleCard(this)" style="cursor:pointer; display:flex; justify-content:space-between; align-items:center;">
                    <div><span class="badge badge-orange">RUTA</span> Recorrido de la sesión</div>
                    <svg class="chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="transition: transform 0.3s;"><polyline points="6 9 12 15 18 9"></polyline></svg>
                </div>
                <div class="card-body">
                <div class="live-panel" id="route-info">''')

# Close card body 2
html = html.replace(
'''</svg>
                        </div>
                        La polilínea se construye durante esta sesión
                    </div>
                </div>
            </div>

            <div class="card" style="display:flex;flex-direction:column;">''',
'''</svg>
                        </div>
                        La polilínea se construye durante esta sesión
                    </div>
                </div>
                </div>
            </div>

            <div class="card" style="display:flex;flex-direction:column;">''')

# 4. Make sensor-panel collapsable (Card 3)
html = html.replace(
'''<div class="card" style="display:flex;flex-direction:column;">
                <div class="card-header">
                    <span class="badge badge-blue">SENSOR</span>
                    Telemetría MPU6050
                </div>
                <div class="live-panel" id="sensor-panel">''',
'''<div class="card" style="display:flex;flex-direction:column;">
                <div class="card-header" onclick="toggleCard(this)" style="cursor:pointer; display:flex; justify-content:space-between; align-items:center;">
                    <div><span class="badge badge-blue">SENSOR</span> Telemetría MPU6050</div>
                    <svg class="chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="transition: transform 0.3s;"><polyline points="6 9 12 15 18 9"></polyline></svg>
                </div>
                <div class="card-body">
                <div class="live-panel" id="sensor-panel">''')

# Close card body 3
html = html.replace(
'''</svg>
                        </div>
                        Esperando datos de acelerómetro
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>''',
'''</svg>
                        </div>
                        Esperando datos de acelerómetro
                    </div>
                </div>
                </div>
            </div>
        </div>
    </div>
</div>''')

with open('app/templates/index.html', 'w') as f:
    f.write(html)

print("HTML patches applied.")
