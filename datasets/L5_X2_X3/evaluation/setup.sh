#!/usr/bin/env bash
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
root="$(dirname "$here")"
python3.12 -m venv "$root/.venv"
"$root/.venv/bin/python" -m pip install --no-index --find-links "$here/vendor/common" --find-links "$here/vendor/linux_py312" -r "$here/requirements-lock.txt"
"$root/.venv/bin/python" -c "import inspect_ai,importlib.metadata as m;print('Inspect AI',m.version('inspect-ai'))"
