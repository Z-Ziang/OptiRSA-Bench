from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FiveTaskProfile:
    o_family_config: Path
    x2x3_config: Path


def load_five_task_profile(path: str | Path) -> FiveTaskProfile:
    p=Path(path).resolve()
    data=json.loads(p.read_text(encoding='utf-8'))
    if data.get('schema_version')!='FIVE_TASK_PROFILE_V1_0':
        raise ValueError('schema_version must be FIVE_TASK_PROFILE_V1_0')
    allowed={'schema_version','o_family_config','x2x3_config'}
    extra=set(data)-allowed
    if extra: raise ValueError(f'unexpected profile fields: {sorted(extra)}')
    for key in ('o_family_config','x2x3_config'):
        if not isinstance(data.get(key),str) or not data[key].strip(): raise ValueError(f'{key} must be a non-empty string')
    o=(p.parent/data['o_family_config']).resolve()
    x=(p.parent/data['x2x3_config']).resolve()
    if not o.is_file(): raise FileNotFoundError(o)
    if not x.is_file(): raise FileNotFoundError(x)
    return FiveTaskProfile(o_family_config=o,x2x3_config=x)
