"""Public-only inputs and offline grading through byte-bound frozen validators."""
from __future__ import annotations
import argparse, hashlib, importlib, json, pathlib, re, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'evaluation/frozen/runtime'
sys.path.insert(0,str(RUNTIME))
CLASSIFICATION_ABS_TOL=1e-9  # same category tolerance as the existing local harness

def readjson(p):return json.loads(pathlib.Path(p).read_text(encoding='utf-8-sig'))
def sha(b):return hashlib.sha256(b).hexdigest()
runtime_manifest=RUNTIME/'FILE_SHA256.json'
if not runtime_manifest.exists():raise RuntimeError('frozen scientific runtime hash manifest missing')
for rel,expected in readjson(runtime_manifest).items():
    if sha((RUNTIME/rel).read_bytes())!=expected:raise RuntimeError('frozen scientific runtime modified: '+rel)
def manifest():
    with (ROOT/'case_sets/_index/cases.jsonl').open(encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]
def resolve_case(relative):
    p=(ROOT/relative).resolve()
    if not p.is_relative_to((ROOT/'case_sets').resolve()):raise ValueError('case path outside package')
    return p
def select_cases(task='all',topology='',scale='',limit_per_task=0):
    rows=[];counts={}
    for r in manifest():
        if task!='all' and r['task']!=task:continue
        if topology and not (r['topology_folder']==topology or r['topology_folder'].startswith(topology+'_')):continue
        if scale and r['scale']!=scale:continue
        if limit_per_task and counts.get(r['task'],0)>=limit_per_task:continue
        rows.append(r);counts[r['task']]=counts.get(r['task'],0)+1
    if not rows:raise ValueError('no matching cases')
    return rows

def public_messages(row):
    folder=resolve_case(row['case_dir']);identity=readjson(folder/'identity.json')
    messages=[]
    for role,name in [('system','system_prompt.txt'),('user','user_prompt.txt')]:
        rel='public/'+name;raw=(folder/rel).read_bytes()
        if sha(raw)!=identity['files'][rel]['sha256']:raise ValueError('public input hash mismatch')
        messages.append({'role':role,'content':raw.decode('utf-8')})
    h=sha(json.dumps(messages,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8'))
    if h!=row['messages_sha256']:raise ValueError('messages binding mismatch')
    return messages

def normalize_fence(text):
    stripped=text.strip()
    m=re.fullmatch(r'```(?:json)?\s*\r?\n(.*?)\r?\n```',stripped,re.I|re.S)
    return (m.group(1),True) if m else (stripped,False)

def classify(row,content,allow_single_fence=True):
    folder=resolve_case(row['case_dir']);task=row['task'];identity=readjson(folder/'identity.json')
    for name in ('root_case','private_truth'):
        rel='private/'+name+'.json'
        if sha((folder/rel).read_bytes())!=identity['files'][rel]['sha256']:
            return {'category':'REVIEW_DATA','reason':'PRIVATE_FILE_HASH_MISMATCH'}
    vp=RUNTIME/'src/tasks'/task.lower()/'validator.py'
    if sha(vp.read_bytes())!=identity['validator_source_sha256']:
        return {'category':'REVIEW_DATA','reason':'FROZEN_VALIDATOR_HASH_MISMATCH'}
    root=readjson(folder/'private/root_case.json');truth=readjson(folder/'private/private_truth.json')
    feasible=bool(truth['feasible' if task=='X2' else 'joint_feasible'])
    text,removed=normalize_fence(content) if allow_single_fence else (content,False)
    base={'truth_feasible':feasible,'single_outer_fence_removed':removed,'interface_status':row['interface_status'],'grading_version':'X2_X3_LOCAL_FOUR_WAY_V1'}
    try:
        obj=json.loads(text,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
    except (ValueError,TypeError):return {**base,'category':'MISSING','reason':'INVALID_JSON'}
    from src.case_core.task_support import validate_output_schema
    schema=validate_output_schema(task,obj)
    if schema:return {**base,'category':'MISSING','reason':'OUTPUT_SCHEMA_ERROR','errors':schema}
    validator=importlib.import_module('src.tasks.'+task.lower()+'.validator')
    v=getattr(validator,'validate_'+task.lower()+'_output')(root,truth,obj)
    errors=[str(e).lower() for e in v.get('errors',[])]
    if any('truth inconsisten' in e or 'truth is inconsistent' in e or 'below stored optimum' in e for e in errors):
        return {**base,'category':'REVIEW_ORACLE','validator':v}
    if obj['decision']=='REJECT' and feasible:
        return {**base,'category':'MISSING','reason':'INCORRECT_REJECT_NO_ALLOCATION','validator':v}
    if not v['valid']:return {**base,'category':'INFEASIBLE','validator':v}
    gaps=[x for k,x in v.get('metrics',{}).items() if k.endswith('_gap') and isinstance(x,(int,float))]
    category='SUBOPTIMAL' if any(x>CLASSIFICATION_ABS_TOL for x in gaps) else 'CORRECT'
    return {**base,'category':category,'correct_reject':obj['decision']=='REJECT','result_kind':'CERTIFIED_REJECT' if obj['decision']=='REJECT' else 'ALLOCATION','validator':v}

def safe_classify(row,content,allow_single_fence=True):
    try:return classify(row,content,allow_single_fence)
    except Exception as e:return {'category':'SCORING_ERROR','reason':type(e).__name__,'message':str(e)}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--case-dir',required=True);p.add_argument('--answer',required=True);p.add_argument('--strict',action='store_true');a=p.parse_args()
    folder=pathlib.Path(a.case_dir).resolve();row=next(r for r in manifest() if resolve_case(r['case_dir'])==folder)
    print(json.dumps(safe_classify(row,pathlib.Path(a.answer).read_text(encoding='utf-8-sig'),not a.strict),ensure_ascii=False,indent=2))
