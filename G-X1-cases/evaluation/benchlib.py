"""GX1 public-only inputs and byte-bound frozen scientific validation."""
from __future__ import annotations
import argparse,hashlib,json,pathlib,re,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'evaluation/frozen/runtime'
sys.path.insert(0,str(RUNTIME))
def readjson(p):return json.loads(pathlib.Path(p).read_text(encoding='utf-8-sig'))
def sha(b):return hashlib.sha256(b).hexdigest()
for rel,h in readjson(RUNTIME/'FILE_SHA256.json').items():
 if sha((RUNTIME/rel).read_bytes())!=h:raise RuntimeError('Frozen scientific file modified: '+rel)
from gx1.validators import validate_dut_output
def manifest():
 with (ROOT/'case_sets/_index/cases.jsonl').open(encoding='utf-8') as f:return [json.loads(x) for x in f if x.strip()]
def resolve_case(relative):
 p=(ROOT/relative).resolve()
 if not p.is_relative_to((ROOT/'case_sets').resolve()):raise ValueError('Case outside package')
 return p
def select_cases(task='all',topology='',scale='',limit_per_task=0):
 rows=[];counts={}
 for r in manifest():
  if not r.get('evaluation_eligible',True):continue
  if task!='all' and r['task']!=task:continue
  if topology and not (r['topology_folder']==topology or topology==r['topology_id'] or r['topology_folder'].startswith(topology+'_')):continue
  if scale and r['scale']!=scale:continue
  if limit_per_task and counts.get(r['task'],0)>=limit_per_task:continue
  rows.append(r);counts[r['task']]=counts.get(r['task'],0)+1
 if not rows:raise ValueError('No matching cases')
 return rows
def public_messages(row):
 d=resolve_case(row['case_dir']);ident=readjson(d/'identity.json');ms=[]
 for role,name in [('system','system_prompt.txt'),('user','user_prompt.txt')]:
  rel='public/'+name;b=(d/rel).read_bytes()
  if sha(b)!=ident['files'][rel]['sha256']:raise ValueError('Public input hash mismatch')
  ms.append({'role':role,'content':b.decode('utf-8')})
 if sha(json.dumps(ms,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())!=row['messages_sha256']:raise ValueError('Message identity mismatch')
 return ms
def normalize_fence(text):
 m=re.fullmatch(r'```(?:json)?\s*\r?\n(.*?)\r?\n```',text.strip(),re.I|re.S)
 return (m.group(1),True) if m else (text.strip(),False)
def classify(row,content,allow_single_fence=True):
 if row.get('interface_status','').startswith('REVIEW'):return {'category':'REVIEW_INTERFACE','reason':row['interface_status']}
 d=resolve_case(row['case_dir']);ident=readjson(d/'identity.json')
 for rel in ['private/root_case.json','private/truth.json']:
  if sha((d/rel).read_bytes())!=ident['files'][rel]['sha256']:return {'category':'REVIEW_DATA','reason':'PRIVATE_FILE_HASH_MISMATCH'}
 if sha((RUNTIME/'gx1/validators.py').read_bytes())!=ident['validator_source_sha256']:return {'category':'REVIEW_DATA','reason':'VALIDATOR_HASH_MISMATCH'}
 root=readjson(d/'private/root_case.json');text,removed=normalize_fence(content) if allow_single_fence else (content,False)
 v=validate_dut_output(root,text);reason=v.get('reason','')
 category='CORRECT' if v['valid'] else 'MISSING' if reason in ('INVALID_JSON','OUTPUT_SCHEMA') else 'SUBOPTIMAL' if row['task']=='X1' and reason=='NOT_GLOBAL_OPTIMUM' else 'INFEASIBLE'
 # A submitted better legal path is a truth conflict, not a model failure.
 if row['task']=='X1' and reason=='NOT_GLOBAL_OPTIMUM' and v['submitted_cost']<v['optimal_cost']-1e-9:category='REVIEW_ORACLE'
 return {'category':category,'binary_correct':category=='CORRECT','task':row['task'],'truth_feasible':True,'correct_reject':False,'single_outer_fence_removed':removed,'interface_status':row['interface_status'],'grading_version':'GX1_LOCAL_FROZEN_FOUR_WAY_V1','validator':v}
def safe_classify(row,content,allow_single_fence=True):
 try:return classify(row,content,allow_single_fence)
 except Exception as e:return {'category':'SCORING_ERROR','reason':type(e).__name__,'message':str(e)}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--case-dir',required=True);p.add_argument('--answer',required=True);p.add_argument('--strict',action='store_true');a=p.parse_args()
 d=pathlib.Path(a.case_dir).resolve();r=next(r for r in manifest() if resolve_case(r['case_dir'])==d)
 print(json.dumps(safe_classify(r,pathlib.Path(a.answer).read_text(encoding='utf-8-sig'),not a.strict),ensure_ascii=False,indent=2))
