#!/usr/bin/env bash
# LLMDyno setup for Linux and macOS (x86-64 or ARM64, including Apple Silicon): creates a virtual environment,
# installs LLMDyno and opens it in your browser.
# Usage:  ./setup.sh            (re-running it is safe; it only installs what is missing)
#         ./setup.sh --no-start (install without starting the server)
set -euo pipefail
cd "$(dirname "$0")"

OS="$(uname -s)"
case "$(uname -m)" in
  x86_64|amd64|arm64|aarch64) ;;
  *) echo "LLMDyno supports x86-64 and ARM64; this machine is $(uname -m)."; exit 1 ;;
esac
case "$OS" in
  Linux|Darwin) ;;
  *) echo "Use setup.ps1 on Windows; this script is for Linux and macOS."; exit 1 ;;
esac

PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  if [ "$OS" = "Darwin" ]; then
    echo "LLMDyno needs Python 3.11 or newer (for example: brew install python@3.12)."
  else
    echo "LLMDyno needs Python 3.11 or newer (for example: sudo apt install python3.12 python3.12-venv)."
  fi
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Creating .venv ..."
  "$PY" -m venv .venv
fi

if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
  # environments made by uv or some distributions ship without pip
  .venv/bin/python -m ensurepip --upgrade >/dev/null
fi
echo "Installing LLMDyno ..."
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e .

if ! command -v docker >/dev/null 2>&1; then
  if [ "$OS" = "Darwin" ]; then
    echo "Docker was not found: install Docker Desktop (brew install --cask docker, or https://docs.docker.com/desktop/setup/install/mac-install/)."
  else
    echo "Docker was not found: install Docker Engine (https://docs.docker.com/engine/install/) and add yourself to the docker group."
  fi
fi

echo "$(.venv/bin/llmdyno --version) is installed."
if [ "${1:-}" = "--no-start" ]; then
  echo "Start it with:  .venv/bin/llmdyno serve --open"
else
  echo "Starting on http://127.0.0.1:8777 (Ctrl+C stops it) ..."
  exec .venv/bin/llmdyno serve --open
fi
