"""Verify materialized selection; optional frozen reference regrade, never API."""
from pathlib import Path
import sys,json,hashlib,argparse,collections
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'evaluation'))
from benchlib import manifest,resolve_case,public_messages,safe_classify,readjson
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--reference-per-topology-task-decision',action='store_true');a=p.parse_args()
 rows=manifest();expected=readjson(ROOT/'BUILD_REPORT.json');assert len(rows)==expected['case_count'];assert len({r['case_uid'] for r in rows})==len(rows)
 assert dict(collections.Counter(r['task'] for r in rows))==expected['task_counts']
 files=0;checks=[];groups={}
 for i,r in enumerate(rows,1):
  relcase=Path(r['case_dir']);assert not relcase.is_absolute() and '..' not in relcase.parts and relcase.parts[0]=='case_sets'
  d=ROOT/relcase;identity=readjson(d/'identity.json')
  messages=[dict(role=role,content=(d/'public'/name).read_bytes().decode('utf-8')) for role,name in [('system','system_prompt.txt'),('user','user_prompt.txt')]]
  assert sha(json.dumps(messages,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())==r['messages_sha256']
  assert int(r['node_count']) in range(5,61) and r['load_band']=='MID'
  assert len(r['shortest_hops'])==(1 if r['task']=='X2' else 2) and min(r['shortest_hops'])>=2
  for rel,info in identity['files'].items():
   child=Path(rel);assert not child.is_absolute() and '..' not in child.parts
   f=d/child;assert sha(f.read_bytes())==info['sha256'];files+=1
  assert sha((d/'private/root_case.json').read_bytes())==r['source_root_sha256']
  assert sha((ROOT/f"evaluation/frozen/runtime/src/tasks/{r['task'].lower()}/validator.py").read_bytes())==identity['validator_source_sha256']
  groups.setdefault((r['graph_hash'],r['task'],r['decision'],r['origin']),r)
  if i%1000==0:print('checked',i,flush=True)
 if a.reference_per_topology_task_decision:
  for r in groups.values():
   result=safe_classify(r,(resolve_case(r['case_dir'])/'private/reference_output.json').read_text(encoding='utf-8'))
   checks.append(dict(uid=r['case_uid'],task=r['task'],origin=r['origin'],category=result['category'],details=result if result['category']!='CORRECT' else None))
 result=dict(case_count=len(rows),task_counts=expected['task_counts'],payload_hashes_checked=files,public_message_bindings_checked=len(rows),frozen_validator_bindings_checked=len(rows),source_root_bindings_checked=len(rows),reference_cases_checked=len(checks),reference_categories=dict(collections.Counter(r['category'] for r in checks)),reference_details=checks,API_calls=0,global_optimality_reproved=False)
 (ROOT/'reports/verification_selected.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in result.items() if k!='reference_details'},ensure_ascii=False))
 if any(r['category']!='CORRECT' for r in checks):sys.exit(2)
if __name__=='__main__':main()
