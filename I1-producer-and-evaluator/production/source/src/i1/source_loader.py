from __future__ import annotations
import json
from pathlib import Path


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_i1_sources(environment_root: Path | str) -> dict:
    root = Path(environment_root).resolve()
    single_files = sorted((root / "requests" / "single").glob("*.jsonl"))
    if not single_files:
        raise FileNotFoundError("no single-request JSONL under requests/single")
    singles = []
    for p in single_files:
        singles.extend(_jsonl(p))
    by_id = {str(x["request_id"]): x for x in singles}

    concurrent = []
    for p in sorted((root / "requests" / "concurrent").glob("*.json")):
        obj = json.loads(p.read_text(encoding="utf-8"))
        ids = obj.get("request_ids", [])
        missing = [x for x in ids if x not in by_id]
        if missing:
            raise ValueError(f"unresolved concurrent request ids in {p.name}: {missing}")
        concurrent.append({"request_set_id": obj.get("request_set_id", p.stem), "requests": [by_id[x] for x in ids]})

    dynamic = []
    for p in sorted((root / "requests" / "dynamic").glob("*.json")):
        obj = json.loads(p.read_text(encoding="utf-8"))
        events = obj.get("dynamic_request_events", obj.get("request_events", []))
        prev = None
        for event in events:
            t = float(event["arrival_time"])
            if prev is not None and t <= prev:
                raise ValueError(f"dynamic arrival_time must be strictly increasing in {p.name}")
            prev = t
            dynamic.append({**event, "request_sequence_id": obj.get("request_sequence_id", p.stem)})
    if not dynamic:
        raise FileNotFoundError("no dynamic request events under requests/dynamic")
    return {"single": singles, "concurrent": concurrent, "dynamic": dynamic}
