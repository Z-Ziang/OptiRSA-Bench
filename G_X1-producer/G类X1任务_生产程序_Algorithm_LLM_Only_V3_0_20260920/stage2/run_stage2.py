from __future__ import annotations

import argparse
import json
from pathlib import Path

from .teacher_demo import run_stage2_production


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run GX1 Teacher Demo Stage 2 using the supplied canonical-km physical topology package."
    )
    parser.add_argument("--canonical-root", required=True, help="Full canonical package root or physical-only directory")
    parser.add_argument("--output", required=True, help="New Stage 2 dataset output directory")
    parser.add_argument("--seed", type=int, default=20260913)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_stage2_production(Path(args.canonical_root), Path(args.output), seed=args.seed)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
