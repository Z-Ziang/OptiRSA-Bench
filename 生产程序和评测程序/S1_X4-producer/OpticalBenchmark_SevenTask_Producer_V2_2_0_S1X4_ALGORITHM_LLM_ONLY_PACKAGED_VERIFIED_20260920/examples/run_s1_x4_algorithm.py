from __future__ import annotations

import argparse
import json
from pathlib import Path

from examples.s1_x4_algorithm_examples import FirstFeasibleS1, SimpleFullSpaceX4
from src.s1_x4.algorithm_api.runner import run_algorithm_benchmark

# The former run_algorithm_evaluation/--launcher interface is retained only
# as a compatibility spelling; the executable path below is run-config based.


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a public S1/X4 structured Algorithm example")
    parser.add_argument("--task", choices=("S1", "X4"), required=True)
    parser.add_argument("--run-config", "--launcher", dest="run_config", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    algorithm = FirstFeasibleS1() if args.task == "S1" else SimpleFullSpaceX4()
    result = run_algorithm_benchmark(
        args.run_config,
        algorithm,
        task_type=args.task,
        dataset_root=args.dataset_root,
        output_dir=args.output,
    )
    print(json.dumps({"status": "PASS", "summary": result["summary"], "timing": result["timing"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
