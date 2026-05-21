import sys

# 1. FIX index.html
with open('app/templates/index.html', 'r') as f:
    html = f.read()

# Make 1 min the default selected option
html = html.replace(
'''<option value="1">Detalle alto (1 min)</option>
                            <option value="3" selected>Paso recomendado (3 min)</option>''',
'''<option value="1" selected>Detalle alto (1 min)</option>
                            <option value="3">Paso recomendado (3 min)</option>''')

# Hide GPS chip from standard view
html = html.replace(
'''<span class="status-pill">
                <span class="status-dot" id="rt-status-dot"></span>
                <span id="rt-connection-label">Conectando señal GPS...</span>
            </span>''',
'''<span class="status-pill dev-only">
                <span class="status-dot" id="rt-status-dot"></span>
                <span id="rt-connection-label">Conectando señal GPS...</span>
            </span>''')

with open('app/templates/index.html', 'w') as f:
    f.write(html)


# 2. FIX style.css
with open('app/static/css/style.css', 'r') as f:
    css = f.read()

# Add height constraints to rt-grid so it is scrollable
css = css.replace(
'''.rt-grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 360px;
    gap: 12px;
    align-items: stretch;
    transition: grid-template-columns 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}''',
'''.rt-grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 360px;
    gap: 12px;
    align-items: stretch;
    transition: grid-template-columns 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    height: min(76vh, calc(100dvh - var(--layout-offset-desktop)));
    max-height: calc(100dvh - var(--layout-offset-desktop));
}''')

# Fix text overflow in .result-info
css = css.replace(
'''.result-info {
    flex: 1;
    min-width: 0;
}

.result-coords {''',
'''.result-info {
    flex: 1;
    min-width: 0;
    word-break: break-word;
}

.result-coords {''')

css = css.replace(
'''.result-item-trip {
    align-items: flex-start;
}''',
'''.result-item-trip {
    align-items: flex-start;
    flex-wrap: wrap;
}''')

# Hide redundant toggle buttons on mobile
css = css.replace(
'''@media (max-width: 960px) {''',
'''@media (max-width: 960px) {
    #btn-toggle-rt-details,
    #btn-toggle-hist-panel {
        display: none;
    }''')

with open('app/static/css/style.css', 'w') as f:
    f.write(css)

print("All fixes applied successfully")
