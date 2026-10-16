"""Hash/schema integrity check and optionally bounded full frozen reference regrading."""
import argparse,csv,json,pathlib,time
from benchlib import ROOT,manifest,resolve_case,readjson,sha,public_messages,safe_classify

def main():
    p=argparse.ArgumentParser();p.add_argument('--reference-per-topology-task-decision',action='store_true');p.add_argument('--report',default='verification_report.json');a=p.parse_args()
    rows=manifest();assert len(rows)==8340 and len({r['case_uid'] for r in rows})==8340
    counts={};groups={};nfiles=0;start=time.time()
    for n,row in enumerate(rows,1):
        folder=resolve_case(row['case_dir']);identity=readjson(folder/'identity.json');public_messages(row)
        for rel,info in identity['files'].items():
            path=(folder/rel).resolve();assert path.is_relative_to(folder)
            assert sha(path.read_bytes())==info['sha256'];nfiles+=1
        counts[row['task']]=counts.get(row['task'],0)+1
        groups.setdefault((row['graph_hash'],row['task'],row['decision']),row)
        if n%1000==0:print(json.dumps({'checked_cases':n}),flush=True)
    assert counts=={'X2':5238,'X3':3102} or counts=={'X3':3102,'X2':5238}
    replay=[]
    if a.reference_per_topology_task_decision:
        for n,row in enumerate(groups.values(),1):
            raw=(resolve_case(row['case_dir'])/'private/reference_output.json').read_text(encoding='utf-8')
            result=safe_classify(row,raw)
            replay.append({'case_uid':row['case_uid'],'task':row['task'],'graph_hash':row['graph_hash'],'category':result['category'],'result':result})
            if result['category']!='CORRECT':raise ValueError(json.dumps(replay[-1]))
            if n%20==0:print(json.dumps({'reference_regraded':n,'planned':len(groups)}),flush=True)
    report={'case_count':len(rows),'task_counts':counts,'case_payload_hashes_checked':nfiles,'public_input_binding_checked':len(rows),'independently_regraded_reference_cases':len(replay),'global_optimality_reproved':False,'API_calls':0,'elapsed_seconds':round(time.time()-start,2),'reference_replays':replay}
    pathlib.Path(a.report).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k!='reference_replays'}))
if __name__=='__main__':main()
