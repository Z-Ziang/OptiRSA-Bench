from pathlib import Path
import os,sys,time,json,subprocess,sqlite3,hashlib,zipfile,traceback
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'backend'))
OUT=ROOT/'output'; EXEC=OUT/'execution'; TASKS=['G2','G1','G3','X2','X3','X1']; PY=sys.executable; MAX_PARALLEL_TASKS=1

def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(tmp,path)

def counts(task):
    db=OUT/'tasks'/task/'queue.sqlite'
    if not db.exists(): return {}
    try:
        with sqlite3.connect(db,timeout=30) as c: return dict(c.execute('select status,count(*) from cases group by status').fetchall())
    except sqlite3.Error: return {'QUEUE_READ_BUSY':1}

def maintenance(task,log):
    with log.open('ab') as f:
        for action in ('recover','export','status'):
            r=subprocess.run([PY,str(ROOT/'run_batch.py'),action,'--task',task],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,env=os.environ.copy())
            if r.returncode: raise RuntimeError(f'{task} {action} failed: {r.returncode}')

def package():
    from core import Queue,TASKS as CORE_TASKS
    summaries={t:Queue(OUT/'tasks'/t/'queue.sqlite',t).summary() for t in CORE_TASKS}
    unfinished={t:{s:n for s,n in v['counts'].items() if s!='COMPLETE'} for t,v in summaries.items()}
    report={'experiment_id':ROOT.name,'phase':'RUN_ENDED','all_600_complete':all(v['total']==100 and v['counts'].get('COMPLETE',0)==100 for v in summaries.values()),'tasks':summaries,'unfinished':unfinished,'thinking_enabled':False,'provider_parameter':{'enable_thinking':False},'concurrency_policy':'At most two task processes concurrently, one worker each after observed TPM rejections.','note':'All raw answers, errors, retries, queue databases, exports and Inspect logs are included. Only cases audited as explicit repeated 429 TPM rejections were requeued.'}
    save(EXEC/'FINAL_REPORT.json',report)
    manifest=EXEC/'RETURN_FILE_SHA256.json'
    files=sorted(p for p in OUT.rglob('*') if p.is_file() and p!=manifest)
    files.extend(ROOT/p for p in ['BATCH_MANIFEST.json','cases.jsonl','FILE_SHA256.json','EXPERIMENT_CHANGELOG.json','README_交接.md','requirements.txt'])
    files.extend(sorted((ROOT/'config').glob('*.json')))
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    save(manifest,hashes);files.append(manifest)
    dest=ROOT.parent/(ROOT.name+'_RETURN.zip');temp=dest.with_suffix('.zip.partial')
    with zipfile.ZipFile(temp,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
        for p in files:z.write(p,p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(temp) as z:
        if z.testzip() is not None: raise RuntimeError('ZIP integrity check failed')
        for rel,h in hashes.items():
            if hashlib.sha256(z.read(rel)).hexdigest()!=h: raise RuntimeError('ZIP hash mismatch: '+rel)
    os.replace(temp,dest)
    digest=hashlib.sha256(dest.read_bytes()).hexdigest()
    dest.with_suffix('.zip.sha256').write_text(digest+'  '+dest.name+'\n',encoding='utf-8')
    save(ROOT/'delivery_status.json',{'phase':'DELIVERY_READY','archive':str(dest),'sha256':digest,'all_600_complete':report['all_600_complete'],'unfinished':unfinished})

def main():
    if not os.environ.get('SILICONFLOW_API_KEY'): raise RuntimeError('SILICONFLOW_API_KEY is missing from launcher environment')
    cfgs={t:json.loads((ROOT/'config'/f'{t}.json').read_text(encoding='utf-8')) for t in TASKS}
    for t,cfg in cfgs.items():
        if cfg.get('extra_body',{}).get('enable_thinking') is not False or cfg.get('workers')!=1 or cfg.get('chunk_size')!=1: raise RuntimeError(f'{t} does not match explicit no-thinking/throttled config')
    env=os.environ.copy()
    for k in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY'): env.pop(k,None)
    env.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    status={'phase':'THROTTLED_RESUME','experiment_id':ROOT.name,'schedule':'One task at a time with one worker globally; max total worker concurrency 1. Start G2 first, then G1/G3, with delayed X retries later.','workers_per_task':{t:1 for t in TASKS},'max_parallel_tasks':MAX_PARALLEL_TASKS,'max_total_workers':MAX_PARALLEL_TASKS,'started_at':time.time(),'tasks':{}}
    save(EXEC/'parallel_run_status.json',status)
    pending=list(TASKS);active={};logs={}
    while pending or active:
        while pending and len(active)<MAX_PARALLEL_TASKS:
            t=pending.pop(0);log=EXEC/f'{t}_throttled.log';f=log.open('ab');logs[t]=f
            f.write(('\nTHROTTLED_START '+t+' '+time.strftime('%Y-%m-%d %H:%M:%S')+'\n').encode());f.flush()
            p=subprocess.Popen([PY,str(ROOT/'run_batch.py'),'run','--task',t],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            active[t]=p;status['tasks'][t]={'pid':p.pid,'state':'RUNNING'}
        for t,p in list(active.items()):
            code=p.poll()
            if code is not None:
                logs[t].write(('\nTHROTTLED_EXIT '+t+' code='+str(code)+'\n').encode());logs[t].close();del logs[t];del active[t]
                maintenance(t,EXEC/f'{t}_throttled.log')
                status['tasks'][t].update(state='EXITED',exit_code=code,counts=counts(t),finished_at=time.time())
        status['counts']={t:counts(t) for t in TASKS};status['active_tasks']=list(active);status['queued_tasks']=list(pending);status['updated_at']=time.time();save(EXEC/'parallel_run_status.json',status)
        if pending or active: time.sleep(5)
    status['phase']='ALL_TASKS_FINISHED';status['finished_at']=time.time();status['counts']={t:counts(t) for t in TASKS};save(EXEC/'parallel_run_status.json',status)
    package()

if __name__=='__main__':
    try: main()
    except Exception:
        save(ROOT/'delivery_status.json',{'phase':'ERROR','traceback':traceback.format_exc()});raise
