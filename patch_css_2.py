import sys

with open('app/static/css/style.css', 'r') as f:
    css = f.read()

# Make dev-only truly disappear
css = css.replace(
'''body:not(.dev-mode) .dev-only {
    opacity: 0;
    max-height: 0;
    overflow: hidden;
    padding: 0 !important;
    margin: 0 !important;
    border: none !important;
}''',
'''body:not(.dev-mode) .dev-only {
    display: none !important;
}''')

# Fix 3D canvas height so it doesn't crop
css_to_add = '''
#sensor-3d-wrap {
    min-height: 160px;
    display: flex;
    justify-content: center;
    align-items: center;
}
'''

if '#sensor-3d-wrap' not in css:
    css += css_to_add

with open('app/static/css/style.css', 'w') as f:
    f.write(css)

print("CSS dev-only and 3D wrap patched.")
