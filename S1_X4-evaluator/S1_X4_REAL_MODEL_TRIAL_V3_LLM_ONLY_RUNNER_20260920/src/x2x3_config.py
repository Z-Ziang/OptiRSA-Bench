from __future__ import annotations

from dataclasses import dataclass
import hashlib, json
from pathlib import Path
from jsonschema import Draft202012Validator

class X2X3ConfigurationError(ValueError): pass

@dataclass(frozen=True)
class X2Config:
    enabled: bool; case_count:int; required_slots_values:tuple[int,...]; selection:str; max_simple_paths:int; max_optimal_actions:int
@dataclass(frozen=True)
class X3Config:
    enabled: bool; case_count:int; request_count_values:tuple[int,...]; selection_values:tuple[str,...]; max_simple_paths_per_request:int; max_search_nodes:int; max_complete_optimal_solutions:int
@dataclass(frozen=True)
class X2X3Config:
    schema_version:str; profile:str; seed:int; x2:X2Config; x3:X3Config; allow_shortfall:bool; source_path:Path; config_sha256:str

def load_x2x3_config(path:str|Path)->X2X3Config:
    path=Path(path).resolve(); text=path.read_text(encoding='utf-8'); raw=json.loads(text)
    schema=json.loads((Path(__file__).resolve().parents[1]/'configs/x2x3_config.schema.json').read_text(encoding='utf-8'))
    errs=sorted(Draft202012Validator(schema).iter_errors(raw),key=lambda e:list(e.path))
    if errs:
        e=errs[0]; loc='.'.join(map(str,e.path)) or '<root>'; raise X2X3ConfigurationError(f'config schema violation at {loc}: {e.message}')
    profile=str(raw['profile']); tx2=raw['tasks']['X2']; tx3=raw['tasks']['X3']
    if profile=='FORMAL' and tx2['selection']=='LOW_ORACLE_COMPLEXITY':
        raise X2X3ConfigurationError('LOW_ORACLE_COMPLEXITY is representative-only')
    x2=X2Config(bool(tx2['enabled']),int(tx2['case_count']),tuple(int(x) for x in tx2['required_slots_values']),str(tx2['selection']),int(tx2['max_simple_paths']),int(tx2['max_optimal_actions']))
    x3=X3Config(bool(tx3['enabled']),int(tx3['case_count']),tuple(int(x) for x in tx3['request_count_values']),tuple(str(x) for x in tx3['selection_values']),int(tx3['max_simple_paths_per_request']),int(tx3['max_search_nodes']),int(tx3['max_complete_optimal_solutions']))
    return X2X3Config('X2X3_PRODUCTION_CONFIG_V1_0',profile,int(raw['seed']),x2,x3,bool(raw['execution']['allow_shortfall']),path,hashlib.sha256(text.encode()).hexdigest())
