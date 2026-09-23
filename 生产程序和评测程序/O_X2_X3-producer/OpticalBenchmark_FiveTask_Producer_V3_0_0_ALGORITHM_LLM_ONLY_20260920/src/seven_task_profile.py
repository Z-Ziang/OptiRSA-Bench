from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path

@dataclass(frozen=True)
class SevenTaskProfile:
    o_family_config: Path
    x2x3_config: Path
    s1x4_config: Path


def load_seven_task_profile(path: str|Path) -> SevenTaskProfile:
    p=Path(path).resolve(); obj=json.loads(p.read_text(encoding='utf-8'))
    if obj.get('schema_version')!='SEVEN_TASK_PROFILE_V2_1_0': raise ValueError('schema_version must be SEVEN_TASK_PROFILE_V2_1_0')
    allowed={'schema_version','o_family_config','x2x3_config','s1x4_config'}
    if set(obj)!=allowed: raise ValueError('seven-task profile fields must be exact')
    def r(key):
        v=obj.get(key)
        if not isinstance(v,str) or not v: raise ValueError(f'{key} must be non-empty string')
        q=(p.parent/v).resolve()
        if not q.is_file(): raise FileNotFoundError(q)
        return q
    return SevenTaskProfile(r('o_family_config'),r('x2x3_config'),r('s1x4_config'))
