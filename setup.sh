#!/usr/bin/env bash
# LLMDyno setup for Linux: creates a virtual environment, installs LLMDyno and opens it in your browser.
# Usage:  ./setup.sh            (re-running it is safe; it only installs what is missing)
#         ./setup.sh --no-start (install without starting the server)
set -euo pipefail
cd "$(dirname "$0")"

case "$(uname -m)" in
  x86_64|amd64) ;;
  *) echo "LLMDyno supports x86-64 for now; this machine is $(uname -m)."; exit 1 ;;
esac

PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "LLMDyno needs Python 3.11 or newer (for example: sudo apt install python3.12 python3.12-venv)."
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
  echo "Docker was not found: install Docker Engine (https://docs.docker.com/engine/install/) and add yourself to the docker group."
fi

echo "$(.venv/bin/llmdyno --version) is installed."
if [ "${1:-}" = "--no-start" ]; then
  echo "Start it with:  .venv/bin/llmdyno serve --open"
else
  echo "Starting on http://127.0.0.1:8777 (Ctrl+C stops it) ..."
  exec .venv/bin/llmdyno serve --open
fi
