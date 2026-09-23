from __future__ import annotations

import subprocess
import sys


def test_runner_help_commands() -> None:
    for script in ("run_one_topology.py", "run_batch.py", "validate_batch.py"):
        proc = subprocess.run([sys.executable, script, "--help"], text=True, capture_output=True)
        assert proc.returncode == 0, proc.stderr
        assert "usage:" in proc.stdout.lower()
