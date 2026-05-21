import sys

with open('app/static/css/style.css', 'r') as f:
    css = f.read()

# Hide the chevron button on mobile for the realtime drawer (and historical) because mobile uses tabs.
css = css.replace(
'''    #view-realtime.mobile-pane-map #rt-detail-cards {
        display: none;
    }''',
'''    #view-realtime.mobile-pane-map #rt-detail-cards {
        display: none;
    }

    .results-actions {
        display: none;
    }''')

with open('app/static/css/style.css', 'w') as f:
    f.write(css)

print("Mobile drawer chevron hidden")
