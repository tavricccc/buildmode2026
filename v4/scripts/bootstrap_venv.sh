#!/usr/bin/env bash
# Bootstrap a Python venv for the v4 backend and install the package in
# editable mode. Cross-platform enough to run under Git Bash on Windows.
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-python}"

if [ ! -d ".venv" ]; then
  echo "[bootstrap_venv] creating .venv"
  "$PYTHON_BIN" -m venv .venv
fi

if [ -f ".venv/Scripts/pip.exe" ]; then
  PIP=".venv/Scripts/pip.exe"
else
  PIP=".venv/bin/pip"
fi

"$PIP" install --upgrade pip
"$PIP" install -e ".[dev]"
echo "[bootstrap_venv] ready"
