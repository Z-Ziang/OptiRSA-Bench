"""Portable provider-neutral Inspect execution with job-boundary resume."""
from __future__ import annotations
import argparse,hashlib,importlib.metadata,json,os,pathlib,socket,time
from inspect_ai import eval
from inspect_ai.model import GenerateConfig,get_model
from inspect_ai.log import read_eval_log
from benchlib import ROOT,readjson,select_cases,public_messages,safe_classify
from inspect_tasks import gx1_cases
from summarize import summarize

def intact_output_after_error(sample):
    if not sample.error:return True
    if not sample.output or not sample.output.choices:return False
    return bool(sample.output.completion and sample.output.choices[0].stop_reason in ('stop','max_tokens','model_length','content_filter','tool_calls'))

def export_logs(log_dir,out,run_model):
    answers=out/'answers';answers.mkdir(exist_ok=True)
    for p in sorted(log_dir.rglob('*.eval')):
        try:log=read_eval_log(str(p))
        except Exception as e:
            print(json.dumps({'unreadable_inspect_log':p.name,'error_type':type(e).__name__}),flush=True)
            continue
        for s in log.samples or []:
            uid=str(s.id);path=answers/(uid+'.json')
            if path.exists():
                prior=readjson(path)
                if prior.get('status')=='RESPONSE_RECEIVED' and prior.get('result',{}).get('category')!='SCORING_ERROR':continue
            result={'case_uid':uid,'model':run_model,'status':'SERVICE_ERROR' if s.error else 'RESPONSE_RECEIVED','raw_completion':s.output.completion if s.output else '', 'finish_reason':getattr(s.output.choices[0],'stop_reason',None) if s.output and s.output.choices else None,'usage':{k:v.model_dump() for k,v in (s.model_usage or {}).items()},'started_at':s.started_at,'completed_at':s.completed_at,'total_seconds':s.total_time,'inspect_log':p.relative_to(out).as_posix()}
            if s.error and intact_output_after_error(s):
                # A scoring/export interruption with an intact answer is recovered offline.
                row=s.metadata['case_record'];result['status']='RESPONSE_RECEIVED'
                result.update(result=safe_classify(row,result['raw_completion']),strict=safe_classify(row,result['raw_completion'],False))
                result['inspect_error_with_retained_answer']=s.error.model_dump()
            elif s.error:result['service_error']=s.error.model_dump()
            elif s.scores:
                score=next(iter(s.scores.values()));result.update(score.metadata or {})
            else:result['result']={'category':'SCORING_ERROR','reason':'NO_INSPECT_SCORE'}
            temp=path.with_suffix('.tmp');temp.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8');temp.replace(path)
    summarize(out)

def main():
    p=argparse.ArgumentParser();p.add_argument('--config');p.add_argument('--task',choices=['G1','G2','G3','X1','all'],default='all');p.add_argument('--topology',default='');p.add_argument('--scale',default='');p.add_argument('--limit-per-task',type=int,default=0);p.add_argument('--output',required=True);p.add_argument('--resume',action='store_true');p.add_argument('--dry-run',action='store_true');p.add_argument('--offline-reference',action='store_true');p.add_argument('--purpose',choices=['exploratory','formal'],default='exploratory');a=p.parse_args()
    rows=select_cases(a.task,a.topology,a.scale,a.limit_per_task)
    # Full frozen source records are preserved; exact duplicate public questions are documented.
    if a.purpose=='formal' and any(r['interface_status'].startswith('REVIEW') for r in rows):raise SystemExit('Formal interface approval is pending. Use exploratory for current unchanged prompt protocol.')
    cfg=readjson(a.config) if a.config else {}
    if not a.offline_reference and not a.dry_run and not a.config:raise SystemExit('--config is required for real model requests')
    if a.dry_run:
        for r in rows:public_messages(r)
        print(json.dumps({'selected':len(rows),'tasks':{t:sum(r['task']==t for r in rows) for t in ['G1','G2','G3','X1']},'max_input_characters':max(r['input_characters'] for r in rows),'API_requests':0,'input_tokens':'NOT_MEASURED_BY_MODEL_TOKENIZER'}));return
    out=pathlib.Path(a.output).resolve();existing=out.exists()
    if existing and not a.resume:raise SystemExit('output exists; use a new directory or --resume')
    out.mkdir(parents=True,exist_ok=True);logs=out/'inspect_logs';logs.mkdir(exist_ok=True)
    frozen={'config':cfg,'case_uids':[r['case_uid'] for r in rows],'input_hashes':[r['messages_sha256'] for r in rows],'purpose':a.purpose,'offline_reference':a.offline_reference,'versions':{n:importlib.metadata.version(n) for n in ['inspect-ai','openai','jsonschema']},'dataset_manifest_sha256':hashlib.sha256((ROOT/'case_sets/_index/cases.jsonl').read_bytes()).hexdigest(),'evaluation_code_sha256':{name:hashlib.sha256((ROOT/'evaluation'/name).read_bytes()).hexdigest() for name in ['benchlib.py','inspect_tasks.py','run_eval.py','summarize.py']}}
    config_path=out/'run_config.json'
    if config_path.exists() and readjson(config_path)!=frozen:raise SystemExit('resume settings or dataset differ from the frozen run')
    config_path.write_text(json.dumps(frozen,ensure_ascii=False,indent=2),encoding='utf-8')
    lock=out/'.runner.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:raise SystemExit('runner lock exists; verify the recorded host/PID before any manual removal')
    os.write(fd,json.dumps({'pid':os.getpid(),'host':socket.gethostname()}).encode());os.close(fd)
    try:
        model='mockllm/model';model_label='offline/reference_replay'
        if not a.offline_reference:
            model_label=cfg.get('model','');env_name=cfg.get('api_key_env','BENCH_API_KEY');key=os.environ.get(env_name)
            if not key:raise SystemExit('API key environment variable is unset: '+env_name)
            if not model_label or 'YOUR_' in model_label:raise SystemExit('fill in the actual model API ID')
            if any(k.lower() in ('api_key','key','token','authorization') for k in cfg):raise SystemExit('do not put credentials in model config')
            generation=GenerateConfig(temperature=cfg.get('temperature',0),max_tokens=cfg.get('max_output_tokens',32768),max_connections=cfg.get('connections',4),max_retries=cfg.get('max_retries',2),timeout=cfg.get('timeout_seconds',300),extra_body=cfg.get('extra_body',{}))
            base_url=cfg.get('base_url')
            if cfg.get('provider','openai_compatible')=='openai_compatible':
                if not base_url or 'YOUR_' in base_url:raise SystemExit('fill in the platform base_url')
                model=get_model('openai-api/'+model_label,api_key=key,base_url=base_url,service_base_url=base_url,service='benchmark_platform',responses_api=False,config=generation)
            else:model=get_model(model_label,api_key=key,base_url=base_url,config=generation)
        export_logs(logs,out,model_label)
        done={p.stem for p in (out/'answers').glob('*.json') if readjson(p).get('status')=='RESPONSE_RECEIVED' and readjson(p).get('result',{}).get('category')!='SCORING_ERROR'}
        todo=[r for r in rows if r['case_uid'] not in done];chunk=int(cfg.get('chunk_size',50))
        if chunk<1:raise SystemExit('chunk_size must be positive')
        for pos in range(0,len(todo),chunk):
            batch=todo[pos:pos+chunk];print(json.dumps({'remaining_at_start':len(todo),'dispatch_chunk':len(batch),'offset':pos}),flush=True)
            eval(gx1_cases(batch,offline_reference=a.offline_reference),model=model,log_dir=str(logs),display='none',log_format='eval',log_model_api=False,fail_on_error=False,max_samples=int(cfg.get('connections',4)),epochs=1)
            export_logs(logs,out,model_label)
        print(json.dumps({'output':str(out),'summary':summarize(out)},ensure_ascii=False),flush=True)
    finally:lock.unlink(missing_ok=True)

if __name__=='__main__':main()
