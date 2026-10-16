"""Recompute dataset counts from this package alone; no Inspect or model calls."""
import argparse,csv,json,pathlib
from collections import Counter,defaultdict
from benchlib import manifest

def analyze(output):
    out=pathlib.Path(output);out.mkdir(parents=True,exist_ok=True);rows=manifest();groups=defaultdict(list)
    for r in rows:groups[(r['scale'],r['task'],r['load_band'],r['request_count'],r['decision'])].append(r)
    counts=[]
    for key,rs in sorted(groups.items()):
        counts.append(dict(zip(['scale','task','load_band','R','truth_decision'],key),cases=len(rs),graphs=len({r['graph_hash'] for r in rs}),snapshots=len({(r['graph_hash'],r['snapshot_hash']) for r in rs}),families=len({f for r in rs for f in r['family_ids']})))
    with (out/'coverage.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(counts[0]));w.writeheader();w.writerows(counts)
    summary={'unique_cases':len(rows),'task_counts':dict(Counter(r['task'] for r in rows)),'graphs':len({r['graph_hash'] for r in rows}),'source_topology_labels':len({r['topology_id'] for r in rows}),'graph_snapshot_pairs':len({(r['graph_hash'],r['snapshot_hash']) for r in rows}),'families':len({f for r in rows for f in r['family_ids']}),'request_slot_demands':{t:dict(Counter(w for r in rows if r['task']==t for w in json.loads(r['requested_slots']))) for t in ['X2','X3']},'actual_tokenizer_measurements':'NOT_MEASURED','LLM_difficulty':'NOT_INFERRED_FROM_GENERATION_PARAMETERS'}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');return summary
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();print(json.dumps(analyze(a.output),ensure_ascii=False,indent=2))
