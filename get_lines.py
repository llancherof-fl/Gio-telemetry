import sys

with open('app/templates/index.html', 'r') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "rt-connection-label" in line or "rt-status-dot" in line or "Señal GPS" in line:
        print(f"{i+1}: {line.strip()}")
