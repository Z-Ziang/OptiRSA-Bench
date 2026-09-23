from __future__ import annotations
import json
from pathlib import Path
import pytest
from jsonschema import Draft202012Validator
from src.i1.config import load_i1_config

ROOT = Path(__file__).resolve().parents[1]


def test_i1_config_schema_accepts_representative_config():
    schema = json.loads((ROOT / "configs" / "i1_config.schema.json").read_text(encoding="utf-8"))
    cfg = json.loads((ROOT / "configs" / "i1_representative.json").read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(cfg)) == []


def test_openai_compatible_rewrite_requires_connection_fields(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({
        "profile":"bad",
        "seed":1,
        "case_counts":{"I1-S":1,"I1-C":0,"I1-D":0},
        "objective_profiles":{
            "I1-S":["MIN-HOP-COUNT","MIN-FRAGMENTATION"],
            "I1-C":["MIN-TOTAL-SLOT-USAGE","MIN-FRAGMENTATION"],
            "I1-D":["MAX-ACCEPTED-REQUESTS","MIN-EXTERNAL-FRAGMENTATION"]
        },
        "rewrite":{"enabled":True,"mode":"openai_compatible","max_attempts":3},
        "allow_shortfall":False
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="base_url"):
        load_i1_config(p)
