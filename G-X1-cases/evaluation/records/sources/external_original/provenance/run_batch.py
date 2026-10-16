"""Portable entry point using unchanged native backend and frozen validators."""
import argparse,json,os,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'backend'))
from core import Queue,TASKS,ProcessLock,atomic_json,read_json
from manage import recover,export
from prepare import verify_catalog
from worker import worker

def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['check','run','recover','export','status']);p.add_argument('--task',choices=TASKS);a=p.parse_args()
 if a.action=='check':
  for d in (ROOT/'datasets').iterdir():
   rows,result=verify_catalog(d);print(d.name,result)
  print('Offline verification passed; no provider requests made.');return
 if not a.task:p.error('--task required')
 runtime=ROOT/'output';t=a.task
 for folder in ('processes','logs','attempts','batches','history','exports'):(runtime/'tasks'/t/folder).mkdir(parents=True,exist_ok=True)
 q=Queue(runtime/'tasks'/t/'queue.sqlite',t)
 rows=[json.loads(x) for x in (ROOT/'cases.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
 selected=[]
 for r in rows:
  if r['task']==t:r['dataset_root']=str((ROOT/r['dataset_root']).resolve());selected.append(r)
 q.add_cases(selected);atomic_json(runtime/'config'/f'{t}.json',read_json(ROOT/'config'/f'{t}.json'))
 if a.action=='status':print(json.dumps(q.summary(),ensure_ascii=False,indent=2));return
 if a.action=='export':print(export(runtime,t));return
 with ProcessLock(runtime/'tasks'/t/'supervisor.lock'):
  recover(runtime,t)
  if a.action=='recover':print(q.summary());return
  if not os.environ.get('SILICONFLOW_API_KEY'):raise SystemExit('Set SILICONFLOW_API_KEY in your own environment; no key is included.')
  q.setting('control',{'stop':False,'reason':'External batch foreground run'})
  try:worker(runtime,t,0)
  finally:export(runtime,t)
if __name__=='__main__':main()
