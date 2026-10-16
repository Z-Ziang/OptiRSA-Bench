"""Canonical six-task CLI, detached Windows supervision, local-only recovery."""
from __future__ import annotations
import argparse
import csv
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from core import TASKS, MODEL, Queue, ProcessLock, atomic_json, read_json, digest, identity_key
from worker import validate_config, grade_saved, now

DEFAULT_ROOT=Path('D:/codex/BENCHMARK/OptiRSA_SiliconFlow_Backend_20261016')
_detached_launchers=[]


def alive(entry):
    import psutil
    try:
        p=psutil.Process(entry['pid'])
        return p.is_running() and abs(p.create_time()-entry['create_time'])<.01
    except (psutil.Error,KeyError,TypeError):return False


def active_processes(root,task):
    _detached_launchers[:]=[p for p in _detached_launchers if p.poll() is None]
    found=[]
    for p in (Path(root)/'tasks'/task/'processes').glob('*.json'):
        try:
            entry=read_json(p)
            if alive(entry):found.append(entry)
        except (OSError,ValueError):continue
    return found


def cooldown_remaining(control,at=None):
    """Seconds until a provider rate-limit cooldown expires."""
    try:return max(0.0,float((control or {}).get('cooldown_until',0))-(time.time() if at is None else at))
    except (TypeError,ValueError):return 0.0


def recover(root,task):
    """Only called when no workers are alive; never dispatches a provider call."""
    root=Path(root);q=Queue(root/'tasks'/task/'queue.sqlite',task)
    for stored in q.rows(('RUNNING','SCORING_REVIEW','NEEDS_REVIEW')):
        uid=stored['uid'];row=json.loads(stored['record'])
        paths=sorted((root/'tasks'/task/'attempts'/uid).glob('*/answer.json'))
        if stored.get('answer_path') and Path(stored['answer_path']).exists():paths.insert(0,Path(stored['answer_path']))
        response_found=False
        for path in paths:
            try:
                q.recover_raw(uid,path)
            except Exception as exc:
                q.event(uid,'RECOVERY_ARTIFACT_REJECTED',{'path':str(path),'error_type':type(exc).__name__});continue
            response_found=True
            try:grade_saved(q,row,path)
            except Exception as exc:q.event(uid,'RECOVERY_GRADING_REVIEW',{'error_type':type(exc).__name__})
            break
        if response_found:continue
        recovered=False
        logs=set((root/'tasks'/task/'attempts'/uid).glob('*/inspect_logs/*.eval'))
        for binding in (root/'tasks'/task/'attempts'/uid).glob('*/binding.json'):
            try:
                location=read_json(binding).get('inspect_log_dir')
                if location:logs.update(Path(location).glob('*.eval'))
            except (OSError,ValueError):continue
        for logpath in sorted(logs):
            try:
                from inspect_ai.log import read_eval_log
                log=read_eval_log(str(logpath))
                sample=next((s for s in log.samples or [] if str(s.id)==uid),None)
                if not sample or not sample.output or not sample.output.choices:continue
                output=sample.output
                response={'case_uid':uid,'task':task,'model':MODEL,'status':'RESPONSE_RECEIVED',
                          'identity_key':identity_key(row),'raw_completion':output.completion or '',
                          'model_output':output.model_dump(mode='json'),'completed_at':sample.completed_at,
                          'recovered_from_inspect':str(logpath),'result':{'category':'SCORING_ERROR'}}
                path=root/'tasks'/task/'recovered'/uid/'answer.json';atomic_json(path,response);q.recover_raw(uid,path)
                grade_saved(q,row,path);recovered=True;break
            except Exception as exc:q.event(uid,'LOG_RECOVERY_REVIEW',{'error_type':type(exc).__name__})
        if not recovered and stored['status']=='RUNNING':
            with q.connect() as db:
                dispatched=any(json.loads(e[0]).get('attempt')==stored['attempts'] for e in db.execute("SELECT detail FROM events WHERE uid=? AND kind='API_DISPATCH'",(uid,)))
            if dispatched:q.fail(uid,'NEEDS_REVIEW','Process interrupted with no durable response; retry requires explicit --include-uncertain')
            else:
                q.fail(uid,'PENDING','Reserved but never dispatched; safe to resume')
                with q.connect() as db:db.execute('UPDATE cases SET retry_base=retry_base+1 WHERE uid=?',(uid,))
    return q.summary()


def retry_cases(root,task,include_uncertain=False):
    root=Path(root)
    with ProcessLock(root/'tasks'/task/'supervisor.lock'):
        if active_processes(root,task):raise RuntimeError('Stop all task processes before retrying')
        recover(root,task)
        q=Queue(root/'tasks'/task/'queue.sqlite',task)
        states=['DEFERRED','PROVIDER_PAUSED']+(['NEEDS_REVIEW'] if include_uncertain else [])
        with q.connect() as db:
            marks=','.join('?' for _ in states)
            db.execute(f"UPDATE cases SET status='PENDING',retry_base=attempts,retry_after=0,error=NULL,updated=? WHERE status IN ({marks})",(time.time(),*states))
        q.event(None,'MANUAL_RETRY',{'states':states,'potential_uncertain_request_repeat':include_uncertain})
        return q.summary()


def export(root,task):
    root=Path(root);q=Queue(root/'tasks'/task/'queue.sqlite',task);out=root/'tasks'/task/'exports';out.mkdir(exist_ok=True)
    rows=q.rows();temp=out/'results.jsonl.tmp'
    with temp.open('w',encoding='utf-8') as f:
        for r in rows:
            if r['result']:
                answer=json.loads(r['result']);answer['_case_metadata']=json.loads(r['record']);answer['queue_status']=r['status']
                f.write(json.dumps(answer,ensure_ascii=False,default=str)+'\n')
        f.flush();os.fsync(f.fileno())
    os.replace(temp,out/'results.jsonl')
    temp=out/'progress.csv.tmp'
    with temp.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['case_uid','case_id','task','status','attempts','category','answer_path'])
        for r in rows:
            record=json.loads(r['record']);answer=json.loads(r['result']) if r['result'] else {}
            writer.writerow([r['uid'],record['case_id'],task,r['status'],r['attempts'],answer.get('result',{}).get('category',''),r['answer_path'] or ''])
    os.replace(temp,out/'progress.csv');atomic_json(out/'summary.json',q.summary())
    return str(out)


def protocol(cfg):
    code=Path(__file__).resolve().parent
    import hashlib
    return digest({'config':cfg,'code':{n:hashlib.sha256((code/n).read_bytes()).hexdigest() for n in ('core.py','worker.py','manage.py')},
                   'versions':{n:importlib.metadata.version(n) for n in ('inspect-ai','openai','jsonschema')}})


def supervise(root,task):
    import psutil
    root=Path(root).resolve();folder=root/'tasks'/task;cfg=read_json(root/'config'/f'{task}.json');validate_config(cfg)
    with ProcessLock(folder/'supervisor.lock'):
        workers=[e for e in active_processes(root,task) if e.get('role') in ('worker','worker-launcher')]
        if workers:raise RuntimeError('Prior workers still alive; stop/drain before restart')
        q=Queue(folder/'queue.sqlite',task)
        if q.setting('import_in_progress'):raise RuntimeError('Dataset/history import incomplete; rerun import before starting')
        remaining=cooldown_remaining(q.setting('control'))
        if remaining:raise RuntimeError(f'Provider rate-limit cooldown remains active for {remaining:.0f} seconds')
        sig=protocol(cfg);previous=q.setting('protocol_sha256')
        if previous and previous!=sig:raise RuntimeError('Code or run condition changed; resume refused')
        q.setting('protocol_sha256',sig);recover(root,task)
        me=psutil.Process();entry={'pid':os.getpid(),'create_time':me.create_time(),'task':task,'role':'supervisor','started_at':now(),'launch_token':os.environ.get('OPTIRSA_LAUNCH_TOKEN')}
        atomic_json(folder/'processes/supervisor.json',entry)
        q.setting('control',{'stop':False,'reason':'Started explicitly','time':now()})
        atomic_json(folder/'run_manifest.json',{'model':MODEL,'config':cfg,'protocol_sha256':sig,'process':entry,
                     'datasets':sorted({json.loads(r['record'])['dataset_root'] for r in q.rows()}),
                     'historical_policy':'skip every identity-matched received response regardless of score','started_at':now()})
        handles=[];children=[]
        try:
            # Native Inspect runs cfg['workers'] asynchronous slots in one task process.
            for slot in range(1):
                stdout=(folder/'logs'/f'worker_{slot}.log');stdout.parent.mkdir(exist_ok=True)
                f=stdout.open('ab');handles.append(f)
                proc=subprocess.Popen([sys.executable,str(Path(__file__).with_name('worker.py')),'--root',str(root),'--task',task,'--slot',str(slot)],
                                      stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,
                                      creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                children.append(proc)
                atomic_json(folder/'processes'/f'launcher_worker_{slot}.json',{'pid':proc.pid,'create_time':psutil.Process(proc.pid).create_time(),'role':'worker-launcher','task':task})
            last_export=0
            while any(p.poll() is None for p in children):
                snapshot={**q.summary(),'process':entry,'worker_pids':[p.pid for p in children if p.poll() is None],'updated_at':now()}
                atomic_json(folder/'status.json',snapshot)
                if time.monotonic()-last_export>60:export(root,task);last_export=time.monotonic()
                time.sleep(.5 if cfg.get('test_mode') else 3)
            recover(root,task);export(root,task)
            summary=q.summary();counts=summary['counts']
            phase=('PAUSED' if summary['control'].get('stop') else 'COMPLETE' if not any(counts.get(s,0) for s in ('PENDING','RUNNING','RETRY','NEEDS_REVIEW','DEFERRED','PROVIDER_PAUSED','SCORING_REVIEW')) else 'ATTENTION_REQUIRED')
            atomic_json(folder/'status.json',{**summary,'phase':phase,'worker_exit_codes':[p.returncode for p in children],'updated_at':now()})
        finally:
            if any(p.poll() is None for p in children):q.setting('control',{'stop':True,'reason':'Supervisor exited; drain workers','time':now()})
            for f in handles:f.close()


def start(root,task):
    root=Path(root).resolve();folder=root/'tasks'/task;cfg=read_json(root/'config'/f'{task}.json');validate_config(cfg)
    with ProcessLock(folder/'launch.lock'):
        q=Queue(folder/'queue.sqlite',task)
        if q.setting('import_in_progress'):raise RuntimeError('Dataset/history import incomplete; run import recovery first')
        if active_processes(root,task):raise RuntimeError('Task already has live processes; duplicate start refused')
        control=q.setting('control') or {};remaining=cooldown_remaining(control)
        if remaining:return {'task':task,'started':False,'cooldown_seconds':remaining,'cooldown_until':control.get('cooldown_until')}
        with ProcessLock(folder/'supervisor.lock'):pass
        env=os.environ.copy();env.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
        token=uuid.uuid4().hex;env['OPTIRSA_LAUNCH_TOKEN']=token
        if cfg.get('test_mode'):env['SILICONFLOW_API_KEY']='loopback-only-test-key'
        else:
            from credentials import load
            env['SILICONFLOW_API_KEY']=load(cfg['credential_dpapi'])
        path=folder/'logs/supervisor.log';path.parent.mkdir(exist_ok=True)
        with path.open('ab') as f:
            proc=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--root',str(root),'run','--task',task],
                                  env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,
                                  creationflags=(subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP) if os.name=='nt' else 0,
                                  start_new_session=os.name!='nt',close_fds=True)
        _detached_launchers.append(proc)
        for _ in range(100):
            meta=folder/'processes/supervisor.json'
            if meta.exists():
                entry=read_json(meta)
                if entry.get('launch_token')==token and alive(entry):return {'task':task,'started':True,'supervisor_pid':entry['pid'],'workers':cfg['workers']}
            if proc.poll() is not None:raise RuntimeError('Supervisor startup failed; see '+str(path))
            time.sleep(.1)
        raise RuntimeError('Supervisor has not confirmed startup; inspect log before repeating start')


def status(root,task):
    root=Path(root);q=Queue(root/'tasks'/task/'queue.sqlite',task);procs=active_processes(root,task)
    counts=q.summary()['counts'];control=q.setting('control') or {}
    return {**q.summary(),'running':bool(procs),'processes':procs,
            'phase':'STOPPING' if procs and control.get('stop') else 'RUNNING' if procs else 'READY' if counts.get('PENDING',0) else 'COMPLETE' if not any(counts.get(s,0) for s in ('RETRY','NEEDS_REVIEW','DEFERRED','PROVIDER_PAUSED','SCORING_REVIEW','RUNNING')) else 'ATTENTION_REQUIRED'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default=str(DEFAULT_ROOT));subs=p.add_subparsers(dest='command',required=True)
    for command in ('start','run','status','stop','recover','retry','export'):
        sub=subs.add_parser(command);sub.add_argument('--task',choices=TASKS,required=command!='status')
        if command=='retry':sub.add_argument('--include-uncertain',action='store_true')
    a=p.parse_args();root=Path(a.root).resolve()
    if a.command=='start':result=start(root,a.task)
    elif a.command=='run':supervise(root,a.task);return
    elif a.command=='status':result=[status(root,t) for t in ([a.task] if a.task else TASKS)]
    elif a.command=='stop':
        q=Queue(root/'tasks'/a.task/'queue.sqlite',a.task);q.setting('control',{'stop':True,'reason':'Manual graceful stop','time':now()});result=status(root,a.task)
    elif a.command=='recover':
        with ProcessLock(root/'tasks'/a.task/'supervisor.lock'):
            if active_processes(root,a.task):raise RuntimeError('Cannot recover while workers are alive')
            result=recover(root,a.task)
    elif a.command=='retry':result=retry_cases(root,a.task,a.include_uncertain)
    else:result={'output':export(root,a.task)}
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
