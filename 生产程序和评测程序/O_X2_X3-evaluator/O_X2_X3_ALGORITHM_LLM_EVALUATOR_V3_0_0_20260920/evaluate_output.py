from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="使用正式五任务 Validator 评测一个 Algorithm 或 LLM 输出 JSON。"
    )
    parser.add_argument("--producer-root", required=True)
    parser.add_argument("--evidence-dataset", required=True)
    parser.add_argument("--task", required=True, choices=("O1", "O2-S", "O2-C", "X2", "X3"))
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--response", required=True)
    args = parser.parse_args()

    producer = Path(args.producer_root).resolve()
    command = [
        sys.executable,
        str(producer / "benchmark_ox.py"),
        "validate-output",
        "--dataset",
        str(Path(args.evidence_dataset).resolve()),
        "--task",
        args.task,
        "--case-id",
        args.case_id,
        "--response",
        str(Path(args.response).resolve()),
    ]
    completed = subprocess.run(
        command,
        cwd=producer,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.stdout:
        try:
            value = json.loads(completed.stdout)
            print(json.dumps(value, ensure_ascii=False, indent=2))
        except json.JSONDecodeError:
            print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
