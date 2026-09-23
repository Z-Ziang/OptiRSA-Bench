#!/usr/bin/env python3
"""Run the formal public-environment production pipeline for one registered topology."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from src.production.config import ConfigurationError, load_production_config
from src.production.one_topology import ProductionUnitError, run_one_topology


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Produce one topology end-to-end: canonical topology -> LOAD_SEARCH_V1_0 resource states -> "
            "Request/RequestDerivation -> optional concurrent/dynamic data -> BaseScenario -> validation."
        )
    )
    parser.add_argument("--batch-config", required=True, type=Path, help="V1.0 production config JSON")
    parser.add_argument("--topology-id", help="Topology id registered in the config; optional when the config has one topology")
    parser.add_argument("--output-dir", required=True, type=Path, help="New/empty output directory for this topology")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_production_config(args.batch_config)
        if args.topology_id:
            matches = [item for item in config.topologies if item.topology_id == args.topology_id]
            if len(matches) != 1:
                raise ConfigurationError(f"topology_id not found in config: {args.topology_id}")
            spec = matches[0]
        else:
            if len(config.topologies) != 1:
                raise ConfigurationError("--topology-id is required when the config registers more than one topology")
            spec = config.topologies[0]
        print(f"[START] topology={spec.topology_id} source={spec.source_path}", flush=True)
        result = run_one_topology(config, spec, args.output_dir)
        print(json.dumps({
            "status": result["status"], "topology_id": result["topology_id"],
            "request_count": result["request_count"], "runtime_seconds": result["runtime_seconds"],
            "output_dir": str(args.output_dir.resolve()),
        }, ensure_ascii=False, indent=2))
        return 0
    except (ConfigurationError, ProductionUnitError, FileExistsError, ValueError, OSError) as exc:
        print(f"[BLOCKED] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
