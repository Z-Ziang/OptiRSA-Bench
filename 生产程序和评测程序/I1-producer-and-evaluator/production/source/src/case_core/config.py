from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


class OFamilyConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class O1Config:
    enabled: bool
    case_count: int
    request_count_values: tuple[int, ...]
    fixed_path_rank_values: tuple[int, ...]
    selection: str
    max_complete_solutions: int


@dataclass(frozen=True)
class O2SConfig:
    enabled: bool
    case_count: int
    candidate_k_values: tuple[int, ...]
    selection: str
    max_complete_solutions: int


@dataclass(frozen=True)
class O2CConfig:
    enabled: bool
    case_count: int
    request_count_values: tuple[int, ...]
    candidate_k_values: tuple[int, ...]
    selection: str
    max_complete_solutions: int


@dataclass(frozen=True)
class OFamilyExecutionConfig:
    allow_shortfall: bool
    resume: bool


@dataclass(frozen=True)
class OFamilyConfig:
    schema_version: str
    profile: str
    seed: int
    o1: O1Config
    o2s: O2SConfig
    o2c: O2CConfig
    execution: OFamilyExecutionConfig
    case_id_namespace: str | None
    source_path: Path
    config_sha256: str


def _obj(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise OFamilyConfigurationError(f"{name} must be an object")
    return value


def _int(value: Any, name: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise OFamilyConfigurationError(f"{name} must be an integer >= {minimum}")
    return value


def _ints(value: Any, name: str, allowed: set[int]) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise OFamilyConfigurationError(f"{name} must be a non-empty array")
    vals=tuple(_int(x,name,minimum=1) for x in value)
    if len(set(vals)) != len(vals):
        raise OFamilyConfigurationError(f"{name} must not contain duplicates")
    bad=sorted(set(vals)-allowed)
    if bad:
        raise OFamilyConfigurationError(f"{name} contains values outside frozen set {sorted(allowed)}: {bad}")
    return vals


def _selection(raw: dict, task: str, allowed: set[str]) -> str:
    value=raw.get("selection")
    if value not in allowed:
        raise OFamilyConfigurationError(f"{task}.selection must be one of {sorted(allowed)}")
    return str(value)


def load_o_family_config(path: str | Path) -> OFamilyConfig:
    path=Path(path).resolve()
    try:
        text=path.read_text(encoding="utf-8")
        raw=json.loads(text)
    except FileNotFoundError as exc:
        raise OFamilyConfigurationError(f"config file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise OFamilyConfigurationError(f"config is not valid JSON: {exc}") from exc
    raw=_obj(raw,"config")
    schema_path=Path(__file__).resolve().parents[2]/"configs"/"o_family_config.schema.json"
    schema=json.loads(schema_path.read_text(encoding="utf-8"))
    errors=sorted(Draft202012Validator(schema).iter_errors(raw),key=lambda e:list(e.path))
    if errors:
        err=errors[0]
        path_text=".".join(str(x) for x in err.path) or "<root>"
        raise OFamilyConfigurationError(f"config schema violation at {path_text}: {err.message}")
    if raw.get("schema_version") != "O_FAMILY_PRODUCTION_CONFIG_V1_0":
        raise OFamilyConfigurationError("schema_version must be O_FAMILY_PRODUCTION_CONFIG_V1_0")
    profile=raw.get("profile")
    if profile not in {"FORMAL","REPRESENTATIVE"}:
        raise OFamilyConfigurationError("profile must be FORMAL or REPRESENTATIVE")
    seed=_int(raw.get("seed"),"seed")
    tasks=_obj(raw.get("tasks"),"tasks")
    if set(tasks) != {"O1","O2-S","O2-C"}:
        raise OFamilyConfigurationError("tasks must contain exactly O1, O2-S, O2-C")
    r1=_obj(tasks["O1"],"O1"); rs=_obj(tasks["O2-S"],"O2-S"); rc=_obj(tasks["O2-C"],"O2-C")
    o1=O1Config(
        bool(r1.get("enabled")), _int(r1.get("case_count"),"O1.case_count"),
        _ints(r1.get("request_count_values"),"O1.request_count_values",{2,4,6,8,10,12,14,16}),
        _ints(r1.get("fixed_path_rank_values"),"O1.fixed_path_rank_values",{1,2,3,4,5}),
        _selection(r1,"O1",{"PREFIX","HIGH_CONFLICT_O1","LOW_ACTION"} if profile=="REPRESENTATIVE" else {"PREFIX","HIGH_CONFLICT_O1"}),
        _int(r1.get("max_complete_solutions"),"O1.max_complete_solutions",minimum=1),
    )
    o2s=O2SConfig(
        bool(rs.get("enabled")), _int(rs.get("case_count"),"O2-S.case_count"),
        _ints(rs.get("candidate_k_values"),"O2-S.candidate_k_values",{2,3,5}),
        _selection(rs,"O2-S",{"PREFIX","LOW_ACTION"} if profile=="REPRESENTATIVE" else {"PREFIX"}),
        _int(rs.get("max_complete_solutions"),"O2-S.max_complete_solutions",minimum=1),
    )
    o2c=O2CConfig(
        bool(rc.get("enabled")), _int(rc.get("case_count"),"O2-C.case_count"),
        _ints(rc.get("request_count_values"),"O2-C.request_count_values",{2,4,6,8,9,10,11,12,14,16}),
        _ints(rc.get("candidate_k_values"),"O2-C.candidate_k_values",{2,3,5}),
        _selection(rc,"O2-C",{"PREFIX","HIGH_CONFLICT_O2C","LOW_ACTION"} if profile=="REPRESENTATIVE" else {"PREFIX","HIGH_CONFLICT_O2C"}),
        _int(rc.get("max_complete_solutions"),"O2-C.max_complete_solutions",minimum=1),
    )
    execution=_obj(raw.get("execution"),"execution")
    execution_cfg=OFamilyExecutionConfig(bool(execution.get("allow_shortfall",False)),bool(execution.get("resume",False)))
    namespace = raw.get("case_id_namespace")
    if namespace is not None and (not isinstance(namespace, str) or not namespace.strip()):
        raise OFamilyConfigurationError("case_id_namespace must be a non-empty string when provided")
    return OFamilyConfig("O_FAMILY_PRODUCTION_CONFIG_V1_0",str(profile),seed,o1,o2s,o2c,execution_cfg,namespace,path,hashlib.sha256(text.encode("utf-8")).hexdigest())
