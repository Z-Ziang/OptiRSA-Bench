from __future__ import annotations
import hashlib,json,shutil,subprocess,sys
from pathlib import Path

TASK_FAMILIES=('O_FAMILY','X2X3','S1X4')
TASKS=('O1','O2-S','O2-C','X2','X3','S1','X4')

def _write(path,obj): path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def _sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def _child(cmd,report,cwd):
    r=subprocess.run([str(x) for x in cmd],cwd=str(cwd),text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    _write(report,{'command':[str(x) for x in cmd],'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr})
    if r.returncode: raise RuntimeError(f'child process failed with exit code {r.returncode}; report={report}')

def _copy(src,dst):
    if not src.is_dir(): return
    dst.mkdir(parents=True,exist_ok=True)
    for x in sorted(src.iterdir(),key=lambda p:p.name):
        y=dst/x.name
        if x.is_dir(): _copy(x,y)
        elif y.exists() and y.read_bytes()!=x.read_bytes(): raise ValueError(f'merge collision with different bytes: {y}')
        else: shutil.copy2(x,y)
def _rows(r):
    p=r/'case_index.jsonl'; return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]
def _summary(r): return json.loads((r/'production_summary.json').read_text(encoding='utf-8'))
def _hashes(root):
    for p in (root/'RUN_MANIFEST.json',root/'SHA256SUMS.txt'): p.unlink(missing_ok=True)
    files=[{'path':p.relative_to(root).as_posix(),'size_bytes':p.stat().st_size,'sha256':_sha(p)} for p in sorted(x for x in root.rglob('*') if x.is_file() and x.name not in {'RUN_MANIFEST.json','SHA256SUMS.txt'})]
    _write(root/'RUN_MANIFEST.json',{'schema_version':'SEVEN_TASK_RUN_MANIFEST_V2_1_0','file_count':len(files),'files':files})
    paths=sorted(x for x in root.rglob('*') if x.is_file() and x.name!='SHA256SUMS.txt')
    (root/'SHA256SUMS.txt').write_text(''.join(f'{_sha(p)}  {p.relative_to(root).as_posix()}\n' for p in paths),encoding='utf-8')

def merge_family_outputs(o_root,x_root,s_root,out,*,environment_root):
    roots={'O_FAMILY':Path(o_root).resolve(),'X2X3':Path(x_root).resolve(),'S1X4':Path(s_root).resolve()}; out=Path(out).resolve()
    if out.exists(): shutil.rmtree(out)
    out.mkdir(parents=True)
    for fr in roots.values():
        for rel in ('benchmark_case','evaluation_case','internal'): _copy(fr/rel,out/rel)
    rows=sum((_rows(fr) for fr in roots.values()),[]); rows.sort(key=lambda r:(r['task_type'],r['case_id']))
    (out/'case_index.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows),encoding='utf-8')
    sums={k:_summary(v) for k,v in roots.items()}; counts={t:0 for t in TASKS}
    for sm in sums.values():
        for t,c in sm.get('task_counts',{}).items():
            if t in counts: counts[t]=int(c)
    summary={'schema_version':'SEVEN_TASK_PRODUCTION_SUMMARY_V2_1_0','status':'PASS','environment_root':str(Path(environment_root).resolve()),'task_counts':counts,'total_case_count':sum(counts.values()),'benchmark_interface':'NATURAL_LANGUAGE_DUAL_ENDPOINT_DYNAMIC_V2_1_0','family_summaries':sums}
    _write(out/'production_summary.json',summary)
    for label,fr in roots.items():
        dst=out/'reports/family'
        dst.mkdir(parents=True,exist_ok=True)
        for n in ('production_summary.json','RUN_MANIFEST.json','SHA256SUMS.txt'):
            if (fr/n).is_file(): shutil.copy2(fr/n,dst/f'{label}_{n}')
    _hashes(out); return summary

def derive_seven_task_dataset(environment_root,o_config,x_config,s1x4_config,output_root):
    root=Path(__file__).resolve().parents[1]; out=Path(output_root).resolve(); work=out.with_name(out.name+'.family_work')
    if work.exists(): shutil.rmtree(work)
    work.mkdir(parents=True)
    try:
        reports=work/'process_reports'; o=work/'O_FAMILY'; x=work/'X2X3'; s=work/'S1X4'
        _child([sys.executable,root/'benchmark.py','derive-cases','--environment',Path(environment_root).resolve(),'--config',Path(o_config).resolve(),'--output',o],reports/'O_FAMILY.json',root)
        _child([sys.executable,root/'benchmark_x2x3.py','derive-cases','--environment',Path(environment_root).resolve(),'--config',Path(x_config).resolve(),'--output',x],reports/'X2X3.json',root)
        _child([sys.executable,root/'benchmark_s1x4.py','derive-cases','--environment',Path(environment_root).resolve(),'--config',Path(s1x4_config).resolve(),'--output',s],reports/'S1X4.json',root)
        summary=merge_family_outputs(o,x,s,out,environment_root=environment_root); _copy(reports,out/'reports/process'); _hashes(out); return summary
    except Exception:
        if out.exists(): shutil.rmtree(out)
        raise
    finally:
        if work.exists(): shutil.rmtree(work)

def verify_seven_task_dataset(dataset_root):
    from src.case_core.dataset_validator import verify_dataset
    from src.x2x3_dataset_validator import verify_x2x3_dataset
    from src.s1_x4.dataset_validator import verify_s1x4_dataset
    a=verify_dataset(dataset_root); b=verify_x2x3_dataset(dataset_root); c=verify_s1x4_dataset(dataset_root)
    return {'valid':bool(a.get('valid')) and bool(b.get('valid')) and bool(c.get('valid')),'o_family':a,'x2x3':b,'s1x4':c,'total_case_count':int(a.get('case_count',0))+int(b.get('case_count',0))+int(c.get('case_count',0))}


def produce_environment_and_seven_tasks(environment_config, o_config, x_config, s1x4_config, output_root):
    from src.production.batch import run_batch
    from src.production.config import load_production_config
    out=Path(output_root).resolve()
    if out.exists(): shutil.rmtree(out)
    out.mkdir(parents=True)
    batch_root=out/'public_environment_batch'
    batch=run_batch(load_production_config(Path(environment_config).resolve()),batch_root)
    if batch.get('status')!='PASS':
        raise RuntimeError(f"public-environment batch did not PASS: {batch.get('status')}")
    datasets={}
    for unit in sorted((batch_root/'units').iterdir()):
        if not unit.is_dir(): continue
        ds=out/'datasets'/unit.name
        datasets[unit.name]=derive_seven_task_dataset(unit/'public_environment',o_config,x_config,s1x4_config,ds)
        verified=verify_seven_task_dataset(ds)
        if not verified['valid']:
            raise RuntimeError(f"seven-task dataset verification failed for {unit.name}")
    result={'status':'PASS','public_environment_batch_id':batch.get('batch_id'),'topology_count':len(datasets),'datasets':datasets}
    _write(out/'SEVEN_TASK_PRODUCTION_RESULT.json',result)
    return result
