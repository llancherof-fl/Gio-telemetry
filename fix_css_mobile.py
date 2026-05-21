import sys

with open('app/static/css/style.css', 'r') as f:
    css = f.read()

# Add rt-grid.panel-collapsed to the 1fr override in @media (max-width: 960px)
css = css.replace(
'''    .rt-grid,
    .hist-layout,
    .hist-layout.panel-collapsed {
        grid-template-columns: 1fr;
    }''',
'''    .rt-grid,
    .rt-grid.panel-collapsed,
    .hist-layout,
    .hist-layout.panel-collapsed {
        grid-template-columns: 1fr;
    }''')

with open('app/static/css/style.css', 'w') as f:
    f.write(css)

print("Mobile grid override fixed")
