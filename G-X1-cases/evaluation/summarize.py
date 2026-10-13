"""Per-model/task answer results; service and oracle errors excluded from accuracy."""
import argparse,collections,csv,json,pathlib
from benchlib import manifest
def summarize(out):
 out=pathlib.Path(out);inv={r['case_uid']:r for r in manifest()};groups=collections.defaultdict(list);details=[]
 for p in sorted((out/'answers').glob('*.json')):
  r=json.loads(p.read_text(encoding='utf-8'));groups[(r['model'],inv[r['case_uid']]['task'])].append(r);details.append(r)
 rows=[];planned={}
 if (out/'run_config.json').exists():
  planned=collections.Counter(inv[k]['task'] for k in json.loads((out/'run_config.json').read_text())['case_uids'])
 for (model,task),rs in sorted(groups.items()):
  cs=collections.Counter(r.get('result',{}).get('category',r['status']) for r in rs);n=sum(cs[c] for c in ['CORRECT','SUBOPTIMAL','INFEASIBLE','MISSING'])
  rows.append({'model':model,'task':task,'planned':planned.get(task,0),'retained_records':len(rs),'received_scored':n,'binary_correct':cs['CORRECT'],'binary_incorrect':n-cs['CORRECT'],'accuracy':cs['CORRECT']/n if n else None,'X1_OPTIMAL':cs['CORRECT'] if task=='X1' else None,'X1_SUBOPTIMAL':cs['SUBOPTIMAL'] if task=='X1' else None,'X1_INFEASIBLE':cs['INFEASIBLE'] if task=='X1' else None,'X1_MISSING':cs['MISSING'] if task=='X1' else None,'output_truncated':sum(r.get('finish_reason') in ('max_tokens','model_length') for r in rs),'service_error':cs['SERVICE_ERROR'],'review_or_scoring_error':sum(v for k,v in cs.items() if k.startswith('REVIEW') or k=='SCORING_ERROR')})
 if rows:
  with (out/'summary.csv').open('w',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 (out/'summary.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
 (out/'results.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in details),encoding='utf-8')
 return rows
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();print(json.dumps(summarize(a.output),ensure_ascii=False,indent=2))
