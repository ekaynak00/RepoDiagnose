#!/bin/bash
# RepoDiagnose — macOS / Linux launcher (on Windows use run.bat)
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python)
[ -z "$PY" ] && { echo "Python 3 not found. https://www.python.org/downloads/"; read -r; exit 1; }
if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c "import requests, numpy, matplotlib, openpyxl, sv_ttk" 2>/dev/null; then
  echo "First run: installing required packages..."
  { [ -x .venv/bin/python ] || "$PY" -m venv .venv; } && .venv/bin/python -m pip install -q -r requirements.txt || { echo "Setup failed."; read -r; exit 1; }
fi
.venv/bin/python -c "import tkinter" 2>/dev/null || { echo "tkinter is missing (Linux: sudo apt install python3-tk)"; read -r; exit 1; }
exec .venv/bin/python repodiagnose.py
