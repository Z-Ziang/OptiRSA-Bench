#!/usr/bin/env python3
"""Run the same V1.0 one-topology production pipeline over a registered topology batch."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from src.production.batch import run_batch
from src.production.config import ConfigurationError, load_production_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Batch public-environment production. Each topology is isolated in staging and promoted to units/ only after PASS."
        )
    )
    parser.add_argument("--batch-config", required=True, type=Path, help="V1.0 production config JSON")
    parser.add_argument("--output-dir", required=True, type=Path, help="Batch output directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_production_config(args.batch_config)
        print(f"[START] batch={config.batch_id} topologies={len(config.topologies)}", flush=True)
        result = run_batch(config, args.output_dir)
        print(json.dumps({
            "status": result["status"], "batch_id": result["batch_id"],
            "passed": result["passed_topology_count"], "failed": result["failed_topology_count"],
            "runtime_seconds": result["runtime_seconds"], "output_dir": str(args.output_dir.resolve()),
        }, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS" else 1
    except (ConfigurationError, FileExistsError, ValueError, OSError) as exc:
        print(f"[BLOCKED] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
