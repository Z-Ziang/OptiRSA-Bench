#!/usr/bin/env bash
set -euo pipefail
package_dir="$(cd "$(dirname "$0")/.." && pwd)"
python3.12 -m venv "$package_dir/.venv"
"$package_dir/.venv/bin/python" -m pip install -r "$package_dir/evaluation/requirements-lock.txt"
"$package_dir/.venv/bin/python" -m pip check
