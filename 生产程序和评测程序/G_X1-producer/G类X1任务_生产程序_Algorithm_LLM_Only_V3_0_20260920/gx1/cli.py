from __future__ import annotations

import argparse
import json
from pathlib import Path

from .production import doctor, produce_batch, verify_output_tree
from .unified_schema import export_unified, verify_unified_export


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="OpticalBenchmark G1/G2/G3/X1 Algorithm+LLM standalone producer V3.0")
    p.add_argument("--config", help="生产配置 JSON")
    p.add_argument("--output", help="输出目录")
    p.add_argument("--doctor", action="store_true", help="运行环境与合同健康检查")
    p.add_argument("--verify-output", help="验证已经生产的输出目录")
    p.add_argument("--export-unified", metavar="SOURCE_DIR", help="将 legacy/internal source 导出为 PUBLIC UNIFIED schema")
    p.add_argument("--unified-output", metavar="OUTPUT_DIR", help="PUBLIC UNIFIED 导出目录")
    p.add_argument("--verify-unified", metavar="OUTPUT_DIR", help="验证 PUBLIC UNIFIED 导出目录")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.doctor:
        result = doctor(); print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if result["valid"] else 1
    if args.verify_output:
        result = verify_output_tree(args.verify_output); print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if result["valid"] else 1
    if args.verify_unified:
        result = verify_unified_export(args.verify_unified); print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if result["valid"] else 1
    if args.export_unified:
        if not args.unified_output:
            raise SystemExit("统一导出模式必须同时提供 --export-unified SOURCE_DIR 和 --unified-output OUTPUT_DIR")
        result = export_unified(args.export_unified, args.unified_output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["valid"] else 1
    if not args.config or not args.output:
        raise SystemExit("生产模式必须同时提供 --config 和 --output")
    manifest = produce_batch(args.config, args.output)
    verify = verify_output_tree(args.output)
    print(json.dumps({"manifest": manifest, "verification": verify}, ensure_ascii=False, indent=2))
    return 0 if verify["valid"] else 1
