import sys

with open('app/static/css/style.css', 'r') as f:
    content = f.read()

# 1. Update rt-grid transition
content = content.replace(
'''.rt-grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 360px;
    gap: 12px;
    align-items: stretch;
}''',
'''.rt-grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 360px;
    gap: 12px;
    align-items: stretch;
    transition: grid-template-columns 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}''')

# 2. Update realtime details collapsed
content = content.replace(
'''#view-realtime.details-collapsed .rt-grid {
    grid-template-columns: minmax(0, 1fr);
}

#view-realtime.details-collapsed .rt-detail-cards {
    max-width: 0;
    opacity: 0;
    transform: translateX(14px);
    overflow: hidden;
    pointer-events: none;
}''',
'''.rt-grid.panel-collapsed {
    grid-template-columns: minmax(0, 1fr) 52px;
}

.rt-grid.panel-collapsed .results-title,
.rt-grid.panel-collapsed .results-actions > *:not(.icon-btn),
.rt-grid.panel-collapsed .results-list {
    opacity: 0;
    pointer-events: none;
}

.rt-grid.panel-collapsed .results-header {
    justify-content: center;
    min-height: 100%;
    border-bottom-color: transparent;
}

.rt-grid.panel-collapsed .icon-btn svg {
    transform: rotate(180deg);
}''')

# 3. Update hist-layout transition
content = content.replace(
'''    display: grid;
    grid-template-columns: minmax(0, 1fr) 360px;
    gap: 12px;
    transition: grid-template-columns 0.28s ease;''',
'''    display: grid;
    grid-template-columns: minmax(0, 1fr) 360px;
    gap: 12px;
    transition: grid-template-columns 0.3s cubic-bezier(0.4, 0, 0.2, 1);''')

with open('app/static/css/style.css', 'w') as f:
    f.write(content)

print("CSS Updated")
