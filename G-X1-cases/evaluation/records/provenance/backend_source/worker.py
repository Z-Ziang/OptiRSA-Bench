"""One native Inspect process per task with ten durable asynchronous slots."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid
from urllib.parse import urlparse
from core import MODEL, Queue, atomic_json, read_json, identity_key, digest


def now():return datetime.now(timezone.utc).isoformat()


def validate_config(cfg):
    if cfg.get('model')!=MODEL or not 1<=cfg.get('workers',0)<=10:raise ValueError('Only Qwen3-8B and 1..10 workers are allowed')
    url=cfg.get('base_url','')
    if cfg.get('test_mode'):
        parsed=urlparse(url)
        if parsed.scheme!='http' or parsed.hostname!='127.0.0.1':raise ValueError('Test mode is loopback-only')
    elif url!='https://api.siliconflow.cn/v1':raise ValueError('Production endpoint is frozen to SiliconFlow')


def failure_kind(error):
    text=json.dumps(error,default=str).lower()
    if re.search(r'\b(401|402|403)\b',text) or any(v in text for v in ('insufficient balance','insufficient_quota','insufficient quota','balance is insufficient','余额','authentication','unauthorized')):return 'PAUSE'
    if re.search(r'\b(408|409|429|500|502|503|504|529)\b',text) or any(v in text for v in ('timeout','timed out','connection','ratelimit','rate limit','overloaded','temporarily unavailable')):return 'TRANSIENT'
    return 'DEFER'


def error_details(exc):
    wrapper=type(exc).__name__;seen=set()
    while id(exc) not in seen:
        seen.add(id(exc));future=getattr(exc,'last_attempt',None)
        inner=future.exception() if future is not None else None
        if inner is None:break
        exc=inner
    out={'type':type(exc).__name__,'message':str(exc),'wrapper_type':wrapper}
    status=getattr(exc,'status_code',None)
    if status is not None:out['status_code']=status
    response=getattr(exc,'response',None)
    headers=getattr(response,'headers',None) or getattr(exc,'headers',None) or {}
    retry_after=headers.get('retry-after') or headers.get('Retry-After')
    retry_after_ms=headers.get('retry-after-ms') or headers.get('Retry-After-Ms')
    if retry_after_ms is not None:
        try:out['retry_after_seconds']=max(0.0,float(retry_after_ms)/1000.0)
        except (TypeError,ValueError):pass
    elif retry_after is not None:
        try:out['retry_after_seconds']=max(0.0,float(retry_after))
        except (TypeError,ValueError):
            try:out['retry_after_seconds']=max(0.0,parsedate_to_datetime(str(retry_after)).timestamp()-time.time())
            except (TypeError,ValueError,OverflowError):pass
    return out


_adapters={}
def adapter_for(row):
    root=Path(row['dataset_root']);key=row.get('runtime_sha256',str(root))
    if key not in _adapters:
        spec=importlib.util.spec_from_file_location('frozen_adapter_'+digest(str(root))[:12],root/'evaluation/benchlib.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);_adapters[key]=module
    module=_adapters[key];module.ROOT=root
    return module


def grade_saved(q,row,path):
    answer=read_json(path)
    if answer.get('identity_key')!=identity_key(row) or answer.get('case_uid')!=row['case_uid'] or answer.get('model')!=MODEL:raise ValueError('Response identity mismatch')
    adapter=adapter_for(row)
    result=adapter.safe_classify(row,answer['raw_completion']);strict=adapter.safe_classify(row,answer['raw_completion'],False)
    answer.update(result=result,strict=strict,graded_at=now())
    atomic_json(path,answer)
    q.complete(row['case_uid'],'SCORING_REVIEW' if result.get('category') in ('SCORING_ERROR','REVIEW_DATA') else 'COMPLETE',answer,path)
    return answer


def redact(value):
    text=json.dumps(value,ensure_ascii=False,default=str)
    secret=os.environ.get('SILICONFLOW_API_KEY','')
    if secret:text=text.replace(secret,'[REDACTED]')
    text=re.sub(r'sk-[A-Za-z0-9_-]{12,}','[REDACTED]',text)
    return json.loads(text)


def is_rate_limit_error(error):
    text=json.dumps(error,ensure_ascii=False,default=str).lower()
    return (str(error.get('status_code',''))=='429' or '50602' in text
            or 'tpm limit' in text or 'rate limit' in text or 'ratelimit' in text)


def reset_rate_limit_streak(q):
    state=q.setting('rate_limit_state') or {}
    if state.get('consecutive'):
        state.update(consecutive=0,last_success_at=time.time())
        q.setting('rate_limit_state',state)


def record_failure(q,row,folder,error,cfg):
    error=redact(error);atomic_json(folder/'service_error.json',error)
    if 'DISPATCH_STOPPED_BEFORE_REQUEST' in json.dumps(error):
        q.fail(row['case_uid'],'PENDING','Stopped before request')
        with q.connect() as db:db.execute('UPDATE cases SET retry_base=retry_base+1 WHERE uid=?',(row['case_uid'],))
        return
    kind=failure_kind(error)
    rate_limited=kind=='TRANSIENT' and is_rate_limit_error(error)
    rate_delay=None
    if rate_limited:
        current=time.time();state=q.setting('rate_limit_state') or {}
        streak=int(state.get('consecutive',0))+1
        exponential=min(3600,300*(2**min(streak-1,4)))
        rate_delay=max(exponential,float(error.get('retry_after_seconds',0) or 0))
        cooldown_until=current+rate_delay
        state.update(consecutive=streak,last_429_at=current,cooldown_until=cooldown_until,
                     cooldown_seconds=rate_delay)
        q.setting('rate_limit_state',state)
        q.setting('control',{'stop':True,'reason':'SiliconFlow TPM rate limit; cooldown before low-speed probe',
                             'time':now(),'cooldown_until':cooldown_until,
                             'cooldown_seconds':rate_delay,'consecutive_rate_limits':streak})
        q.event(row['case_uid'],'RATE_LIMIT_COOLDOWN',{'cooldown_seconds':rate_delay,
                 'cooldown_until':cooldown_until,'consecutive_rate_limits':streak})
    if kind=='PAUSE':
        q.setting('control',{'stop':True,'reason':'Provider authentication/balance/permission error','time':now()})
        q.fail(row['case_uid'],'PROVIDER_PAUSED',json.dumps(error))
    elif kind=='TRANSIENT' and row['_budget_attempt']<cfg.get('max_transport_attempts',3):
        delay=cfg.get('retry_backoff_seconds',10)*(2**(row['_budget_attempt']-1))
        if rate_delay is not None:delay=max(delay,rate_delay)
        q.fail(row['case_uid'],'RETRY',json.dumps(error),time.time()+delay)
    else:q.fail(row['case_uid'],'DEFERRED',json.dumps(error))
    q.event(row['case_uid'],'SERVICE_FAILURE',{'kind':kind,'attempt':row['_attempt']})


def execute_batch(q,root,rows,cfg,model):
    from inspect_ai import Task,eval
    from inspect_ai.dataset import Sample
    from inspect_ai.model import ChatMessageSystem,ChatMessageUser
    from inspect_ai.scorer import Score,scorer
    from inspect_ai.solver import solver
    task_name=rows[0]['task'];logdir=Path(root)/'tasks'/task_name/'batches'/uuid.uuid4().hex/'inspect_logs'
    cases={};samples=[]
    for row in rows:
        uid=row['case_uid'];attempt=row['_attempt']
        folder=Path(root)/'tasks'/row['task']/'attempts'/uid/f'{attempt:04d}'
        folder.mkdir(parents=True,exist_ok=False);started=now()
        cases[uid]=(row,folder,started)
        atomic_json(folder/'binding.json',{'case_uid':uid,'task':row['task'],'model':MODEL,'identity_key':identity_key(row),
                   'messages_sha256':row['messages_sha256'],'config_sha256':digest(cfg),'attempt':attempt,
                   'started_at':started,'inspect_log_dir':str(logdir)})
        messages=adapter_for(row).public_messages(row)
        samples.append(Sample(id=uid,input=[(ChatMessageSystem if m['role']=='system' else ChatMessageUser)(content=m['content']) for m in messages],target=''))

    @solver
    def durable_generate():
        async def solve(state,generate):
            uid=str(state.sample_id);row,folder,started=cases[uid];attempt=row['_attempt'];raw=folder/'answer.json'
            # Control is checked again immediately before entering the provider call.
            try:
                if (q.setting('control') or {}).get('stop'):raise RuntimeError('DISPATCH_STOPPED_BEFORE_REQUEST')
                q.event(uid,'API_DISPATCH',{'attempt':attempt,'model':MODEL,'endpoint':cfg['base_url']})
                state=await generate(state)
            except Exception as exc:
                record_failure(q,row,folder,error_details(exc),cfg)
                raise
            output=state.output
            answer={'case_uid':uid,'model':MODEL,'task':row['task'],'identity_key':identity_key(row),
                    'status':'RESPONSE_RECEIVED','raw_completion':output.completion or '',
                    'finish_reason':getattr(output.choices[0],'stop_reason',None) if output.choices else None,
                    'usage':output.usage.model_dump(mode='json') if output.usage else {},
                    'model_output':output.model_dump(mode='json'),'started_at':started,'completed_at':now(),
                    'messages_sha256':row['messages_sha256'],'protocol_sha256':digest(cfg),
                    'attempt':attempt,'inspect_log_dir':str(logdir)}
            atomic_json(raw,answer)  # Durable response boundary: always precedes grading/DB completion.
            q.recover_raw(uid,raw)
            q.event(uid,'RESPONSE_SAVED',{'path':str(raw)})
            reset_rate_limit_streak(q)
            return state
        return solve

    @scorer(metrics=[])
    def frozen_score():
        async def score(state,target):
            row,folder,_=cases[str(state.sample_id)];raw=folder/'answer.json'
            answer=grade_saved(q,row,raw);category=answer['result']['category']
            return Score(value=1 if category=='CORRECT' else 0,answer=category,
                         metadata={'result':answer['result'],'strict':answer['strict']})
        return score

    task=Task(dataset=samples,
              solver=durable_generate(),scorer=frozen_score(),version='OPTIRSA_DURABLE_V1')
    try:
        logs=eval(task,model=model,log_dir=str(logdir),display='none',log_format='eval',
                  log_model_api=False,fail_on_error=False,max_samples=cfg['workers'],epochs=1)
        samples_by_uid={str(s.id):s for log in logs for s in log.samples or []}
        for uid,(row,folder,_) in cases.items():
            raw=folder/'answer.json'
            if raw.exists():
                if q.get(uid)['status']=='SCORING_REVIEW':grade_saved(q,row,raw)
                continue
            if q.get(uid)['status']!='RUNNING':continue
            sample=samples_by_uid.get(uid)
            error=sample.error.model_dump(mode='json') if sample and sample.error else {'message':'Inspect returned no sample/response'}
            record_failure(q,row,folder,error,cfg)
    except Exception as exc:
        for uid,(row,folder,_) in cases.items():
            raw=folder/'answer.json'
            if raw.exists():
                q.recover_raw(uid,raw)
                try:grade_saved(q,row,raw)
                except Exception as grade_error:q.event(uid,'LOCAL_GRADING_FAILED',{'type':type(grade_error).__name__})
            elif q.get(uid)['status']=='RUNNING':
                q.fail(uid,'NEEDS_REVIEW',type(exc).__name__)
                q.event(uid,'BATCH_ENGINEERING_FAILURE',{'type':type(exc).__name__})


def worker(root,task,slot):
    import psutil
    from inspect_ai.model import GenerateConfig,get_model
    root=Path(root);cfg=read_json(root/'config'/f'{task}.json');validate_config(cfg)
    q=Queue(root/'tasks'/task/'queue.sqlite',task)
    me=psutil.Process();owner=f'{os.getpid()}:{me.create_time()}'
    atomic_json(root/'tasks'/task/'processes'/f'worker_{slot}.json',{'pid':os.getpid(),'create_time':me.create_time(),'task':task,'slot':slot,'role':'worker'})
    generation=GenerateConfig(temperature=cfg.get('temperature',0),max_tokens=cfg['max_output_tokens'],max_connections=cfg['workers'],adaptive_connections=False,
                              max_retries=0,timeout=cfg.get('timeout_seconds',300),attempt_timeout=cfg.get('timeout_seconds',300),extra_body=cfg.get('extra_body',{}))
    model=get_model('openai-api/'+MODEL,api_key=os.environ['SILICONFLOW_API_KEY'],base_url=cfg['base_url'],
                    service_base_url=cfg['base_url'],service='benchmark_platform',responses_api=False,
                    stream=False,max_retries=0,client_timeout=cfg.get('timeout_seconds',300),config=generation)
    while not (q.setting('control') or {}).get('stop'):
        rows=[]
        for _ in range(cfg.get('chunk_size',cfg['workers']*10)):
            row=q.claim(owner,cfg.get('max_transport_attempts',3))
            if row:rows.append(row)
        if not rows:
            if q.rows(('RETRY',)):
                time.sleep(.5);continue
            break
        try:execute_batch(q,root,rows,cfg,model)
        except Exception as exc:
            # Engineering failures are never treated as evidence that no response occurred.
            for row in rows:
                q.fail(row['case_uid'],'NEEDS_REVIEW',type(exc).__name__)
                q.event(row['case_uid'],'ENGINEERING_FAILURE',{'type':type(exc).__name__})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--task',required=True);p.add_argument('--slot',type=int,required=True);a=p.parse_args()
    worker(a.root,a.task,a.slot)
