import sys

with open('app/static/css/style.css', 'r') as f:
    css = f.read()

# I will fix the broken syntax I just injected.
css = css.replace(
'''    .hist-layout, #rt-grid {
        grid-template-columns: 1fr;
    }
    #rt-grid.panel-collapsed, .hist-layout.panel-collapsed {
        grid-template-columns: 1fr;
    }
    /* override any desktop grid for drawer */
    .rt-grid {
        grid-template-columns: 1fr;
    }
        min-height: 460px;
        height: min(72vh, calc(100dvh - var(--layout-offset-tablet)));
        max-height: calc(100dvh - var(--layout-offset-tablet));
    }''',
'''    .hist-layout {
        grid-template-columns: minmax(0, 1fr) 320px;
        min-height: 460px;
        height: min(72vh, calc(100dvh - var(--layout-offset-tablet)));
        max-height: calc(100dvh - var(--layout-offset-tablet));
    }
    .rt-grid.panel-collapsed {
        grid-template-columns: minmax(0, 1fr) 52px;
    }''')

with open('app/static/css/style.css', 'w') as f:
    f.write(css)

print("Syntax fixed")
