import sys

with open('app/static/css/style.css', 'r') as f:
    css = f.read()

# Add styles for collapsable cards
css_to_add = '''
/* Collapsable cards */
.card-body {
    transition: max-height 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.4s cubic-bezier(0.4, 0, 0.2, 1), padding 0.4s cubic-bezier(0.4, 0, 0.2, 1);
    max-height: 1000px;
    opacity: 1;
    overflow: hidden;
}

.card.collapsed .card-body {
    max-height: 0;
    opacity: 0;
}

.card.collapsed .chevron {
    transform: rotate(90deg) !important;
}

.card-header:hover {
    background: rgba(36, 56, 100, 0.6);
}
'''

if '/* Collapsable cards */' not in css:
    css += css_to_add

with open('app/static/css/style.css', 'w') as f:
    f.write(css)

print("CSS patches applied.")
