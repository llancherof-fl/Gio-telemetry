import sys

with open('app/static/css/style.css', 'r') as f:
    css = f.read()

# Make sure rt-grid gets height: auto in mobile just like hist-layout
css = css.replace(
'''    .hist-layout,
    .hist-layout.panel-collapsed {
        height: auto;
        min-height: 0;
        max-height: none;
    }''',
'''    .rt-grid,
    .rt-grid.panel-collapsed,
    .hist-layout,
    .hist-layout.panel-collapsed {
        height: auto;
        min-height: 0;
        max-height: none;
    }''')

with open('app/static/css/style.css', 'w') as f:
    f.write(css)

print("Mobile height auto fixed")
