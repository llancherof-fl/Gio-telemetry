import sys

# 1. Fix missing closing div in index.html
with open('app/templates/index.html', 'r') as f:
    html = f.read()

# I will add the missing </div> to close view-realtime right before view-historical
html = html.replace(
'''        </div>
    </div>
</div>

<div class="view" id="view-historical">''',
'''        </div>
    </div>
</div>
</div>

<div class="view" id="view-historical">''')

# 2. Fix the 3D car logic
# The user wants to see the 3D car. I will move the sensor 3d wrap outside the dev-only block or remove dev-only from the sensor panel.
# Wait, the user said "no veo ni el carrito". It's inside the MPU6050 panel.
# I will remove 'dev-only' from the sensor panel, but add 'dev-only' to the actual text values.
html = html.replace(
'''<div class="card dev-only" style="display:flex;flex-direction:column;">
                <div class="card-header">
                    <span class="badge badge-blue">SENSOR</span>
                    Telemetría MPU6050''',
'''<div class="card" style="display:flex;flex-direction:column;">
                <div class="card-header">
                    <span class="badge badge-blue">SENSOR</span>
                    Telemetría MPU6050''')
# Wait, the live-panel values inside it. It currently just says "Esperando datos de acelerómetro" and then javascript injects it.
# I will just leave the MPU6050 panel without dev-only so the car shows.

with open('app/templates/index.html', 'w') as f:
    f.write(html)

# 3. Fix CSS mobile rules
with open('app/static/css/style.css', 'r') as f:
    css = f.read()

# Fix the mobile pane visibility
css = css.replace('.rt-detail-cards', '#rt-detail-cards')
css = css.replace('.rt-grid.panel-collapsed #rt-detail-cards', '#rt-grid.panel-collapsed #rt-detail-cards')

# Fix grid layout for mobile. In mobile, it shouldn't use 52px drawer.
css = css.replace(
'''    .hist-layout {
        grid-template-columns: minmax(0, 1fr) 320px;''',
'''    .hist-layout, #rt-grid {
        grid-template-columns: 1fr;
    }
    #rt-grid.panel-collapsed, .hist-layout.panel-collapsed {
        grid-template-columns: 1fr;
    }
    /* override any desktop grid for drawer */
    .rt-grid {
        grid-template-columns: 1fr;
    }''')

with open('app/static/css/style.css', 'w') as f:
    f.write(css)

print("Fixed")
