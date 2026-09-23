from __future__ import annotations
from dataclasses import dataclass
import hashlib, json
from pathlib import Path

@dataclass(frozen=True)
class S1X4Config:
    profile: str
    case_count: int
    allow_shortfall: bool
    k_values: tuple[int,...]
    run_reference_panel: bool
    config_sha256: str

def load_s1x4_config(path: Path|str) -> S1X4Config:
    p=Path(path); raw=p.read_bytes(); obj=json.loads(raw.decode('utf-8'))
    allowed={'profile','case_count','allow_shortfall','k_values','run_reference_panel'}
    extra=set(obj)-allowed
    if extra: raise ValueError(f'unknown S1/X4 config fields: {sorted(extra)}')
    profile=obj.get('profile'); count=obj.get('case_count'); ks=obj.get('k_values',[3,5])
    if not isinstance(profile,str) or not profile: raise ValueError('profile must be non-empty string')
    if not isinstance(count,int) or isinstance(count,bool) or count<0: raise ValueError('case_count must be non-negative integer')
    if not isinstance(obj.get('allow_shortfall',False),bool): raise ValueError('allow_shortfall must be boolean')
    if not isinstance(obj.get('run_reference_panel',True),bool): raise ValueError('run_reference_panel must be boolean')
    if not isinstance(ks,list) or not ks or any((not isinstance(k,int) or isinstance(k,bool) or k not in {3,5}) for k in ks):
        raise ValueError('k_values must be a non-empty list containing only 3 or 5')
    return S1X4Config(profile,count,bool(obj.get('allow_shortfall',False)),tuple(ks),bool(obj.get('run_reference_panel',True)),hashlib.sha256(raw).hexdigest())
