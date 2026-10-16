"""Idempotent local deployment configuration; never starts model requests."""
from pathlib import Path
import argparse
import os
import shutil
import contextlib
from core import TASKS,MODEL,atomic_json,read_json,Queue,ProcessLock


def deploy(root):
    from manage import active_processes
    root=Path(root).resolve()
    with contextlib.ExitStack() as locks:
        for task in TASKS:locks.enter_context(ProcessLock(root/'tasks'/task/'supervisor.lock'))
        if any(active_processes(root,task) for task in TASKS):raise RuntimeError('Stop all task processes before replacing deployment code')
        return _deploy_locked(root)


def _deploy_locked(root):
    root=Path(root).resolve();source=Path(__file__).resolve().parent
    code=root/'code';code.mkdir(parents=True,exist_ok=True)
    for path in source.glob('*.py'):
        target=code/path.name
        if path.resolve()!=target.resolve():shutil.copy2(path,target)
    for name in ('DESIGN.md','PLAN.md'):
        if (source/name).exists():shutil.copy2(source/name,root/name)
    secret=Path(os.environ['LOCALAPPDATA'])/'OptiRSA'/'siliconflow.dpapi'
    for task in TASKS:
        folder=root/'tasks'/task
        for name in ('logs','processes','attempts','history','exports'): (folder/name).mkdir(parents=True,exist_ok=True)
        cfg={'model':MODEL,'base_url':'https://api.siliconflow.cn/v1','workers':10,
             'temperature':0,'max_output_tokens':32768 if task=='G1' else 8192,
             'timeout_seconds':300,'max_transport_attempts':3,'retry_backoff_seconds':10,
             'extra_body':{},'reasoning_mode':'provider_native','credential_dpapi':str(secret)}
        path=root/'config'/f'{task}.json'
        if not path.exists():atomic_json(path,cfg)
        elif read_json(path)!=cfg:raise ValueError('Existing run configuration differs: '+task)
        Queue(folder/'queue.sqlite',task)
    wrapper='''param(
    [Parameter(Mandatory=$true)][ValidateSet("start","status","stop","recover","retry","export")][string]$Action,
    [ValidateSet("G1","G2","G3","X1","X2","X3")][string]$Task,
    [switch]$IncludeUncertain
)
$ErrorActionPreference = "Stop"
$arguments = @("--root", $PSScriptRoot, $Action)
if ($Task) { $arguments += @("--task", $Task) }
if ($IncludeUncertain) { $arguments += "--include-uncertain" }
& (Join-Path $PSScriptRoot ".venv\\Scripts\\python.exe") (Join-Path $PSScriptRoot "code\\manage.py") @arguments
if ($LASTEXITCODE -ne 0) { throw "Backend command failed (exit $LASTEXITCODE)" }
'''
    (root/'backend.ps1').write_text(wrapper,encoding='utf-8-sig')
    importer='''param([Parameter(Mandatory=$true)][string]$Archive)
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot ".venv\\Scripts\\python.exe") (Join-Path $PSScriptRoot "code\\prepare.py") --root $PSScriptRoot --archive $Archive
if ($LASTEXITCODE -ne 0) { throw "Import failed; inspect report before retrying" }
'''
    (root/'import-cases.ps1').write_text(importer,encoding='utf-8-sig')
    return {'root':str(root),'tasks':list(TASKS),'workers_per_task':10,'provider_API_calls':0}


if __name__=='__main__':
    import json
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args();print(json.dumps(deploy(a.root),indent=2))
