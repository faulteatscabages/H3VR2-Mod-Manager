#!/bin/bash
# macOS / Linux: double-click (macOS) or run ./install.command [--uninstall]
cd "$(dirname "$0")"
PY=python3
command -v $PY >/dev/null || { echo "Python 3 is required: https://www.python.org/downloads/"; read -p "Press Enter"; exit 1; }
if [ ! -d .venv ]; then
  echo "First run: setting up Python environment…"
  $PY -m venv .venv && .venv/bin/pip install -q -r requirements.txt || { echo "Setup failed"; read -p "Press Enter"; exit 1; }
fi
.venv/bin/python -I tools/install.py "$@"
read -p "Press Enter to close"
