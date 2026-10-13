"""Summarize retained per-case results; excludes transport/review from model answer rates."""
import argparse,csv,json,pathlib
from collections import defaultdict,Counter
from benchlib import manifest

def summarize(out):
    out=pathlib.Path(out);inv={r['case_uid']:r for r in manifest()};groups=defaultdict(list);details=[]
    for p in sorted((out/'answers').glob('*.json')):
        r=json.loads(p.read_text(encoding='utf-8'));row=inv[r['case_uid']]
        category=r.get('result',{}).get('category',r['status']);details.append(r)
        groups[(r.get('model','UNKNOWN'),row['task'])].append((r,category))
    summary=[]
    for (model,task),rs in sorted(groups.items()):
        count=Counter(cat for r,cat in rs);eligible=[r for r,cat in rs if cat in ('CORRECT','SUBOPTIMAL','INFEASIBLE','MISSING')]
        feasible=[r for r in eligible if r['result']['truth_feasible']];impossible=[r for r in eligible if not r['result']['truth_feasible']]
        fc=Counter(r['result']['category'] for r in feasible)
        summary.append({'model':model,'task':task,'records':len(rs),'received_scored':len(eligible),'ground_truth_feasible':len(feasible),'OPTIMAL':fc['CORRECT'],'SUBOPTIMAL':fc['SUBOPTIMAL'],'INFEASIBLE':fc['INFEASIBLE'],'MISSING':fc['MISSING'],'ground_truth_infeasible':len(impossible),'correct_reject':sum(r['result'].get('correct_reject',False) for r in impossible),'service_error':count['SERVICE_ERROR'],'review_or_scoring_error':sum(n for cat,n in count.items() if cat.startswith('REVIEW') or cat=='SCORING_ERROR'),'feasible_optimal_rate':fc['CORRECT']/len(feasible) if feasible else None})
    if summary:
        with (out/'summary.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(summary[0]));w.writeheader();w.writerows(summary)
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    with (out/'results.jsonl').open('w',encoding='utf-8') as f:
        for r in details:f.write(json.dumps(r,ensure_ascii=False)+'\n')
    return summary
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();print(json.dumps(summarize(a.output),ensure_ascii=False,indent=2))
