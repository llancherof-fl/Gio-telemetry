import sys

with open('app/static/css/style.css', 'r') as f:
    content = f.read()

content = content.replace(
'''    #view-realtime.details-collapsed .rt-detail-cards {
        display: none;
    }''',
'''    .rt-grid.panel-collapsed .rt-detail-cards {
        display: none;
    }''')

with open('app/static/css/style.css', 'w') as f:
    f.write(content)

print("Mobile CSS Updated")
