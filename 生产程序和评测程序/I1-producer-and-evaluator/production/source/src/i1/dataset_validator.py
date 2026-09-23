from __future__ import annotations
import hashlib,json
from pathlib import Path
from jsonschema import Draft202012Validator

TASKS=("I1-S","I1-C","I1-D")

def _read(path: Path): return json.loads(path.read_text(encoding='utf-8'))
def _sha(path: Path): return hashlib.sha256(path.read_bytes()).hexdigest()

def _schema_ok(schema_path: Path,obj) -> str|None:
    schema=_read(schema_path); errs=sorted(Draft202012Validator(schema).iter_errors(obj),key=lambda e:list(e.path))
    return errs[0].message if errs else None

def verify_i1_dataset(dataset_root: Path|str) -> dict:
    root=Path(dataset_root).resolve(); errors=[]; count=0; seen=set()
    if not root.is_dir(): return {'valid':False,'case_count':0,'errors':[f'dataset not found: {root}']}
    idx=root/'case_index.jsonl'
    if not idx.is_file(): return {'valid':False,'case_count':0,'errors':['missing case_index.jsonl']}
    rows=[json.loads(x) for x in idx.read_text(encoding='utf-8').splitlines() if x.strip()]
    contracts=root/'internal/contracts'
    for task in TASKS:
        bench_contract=root/'benchmark_case'/task
        eval_contract=root/'evaluation_case'/task
        if any((root/'benchmark_case'/task/'cases').glob('*.json')):
            for base in (bench_contract,eval_contract):
                llm=base/'llm_system_prompt.txt'
                if not llm.is_file(): errors.append(f'{task}: missing llm_system_prompt.txt copy')
    for r in rows:
        task=r.get('task_type'); cid=r.get('case_id')
        if task not in TASKS: errors.append(f'unknown task: {task}'); continue
        count+=1
        if cid in seen: errors.append(f'duplicate case_id: {cid}')
        seen.add(cid)
        try:
            b=_read(root/r['benchmark_case_path']); ecase=_read(root/r['evaluation_case_path'])
            ans=_read(root/r['internal_case_dir']/'canonical_answer.json')
            val=_read(root/r['internal_case_dir']/'validation.json')
            if set(b)!={'case_id','llm_prompt','answer'}: raise ValueError('benchmark_case fields')
            if set(ecase)!={'case_id','prompt'}: raise ValueError('evaluation case fields')
            if ecase['prompt']!=b['llm_prompt']: raise ValueError('evaluation prompt mismatch')
            if b['answer']!=ans: raise ValueError('public answer differs from canonical_answer')
            if any('answer' in x or 'reference' in x or 'truth' in x for x in ecase): raise ValueError('evaluation answer leakage')
            if val.get('overall')!='PASS': raise ValueError('rewrite validation not PASS')
            er=_schema_ok(contracts/task/'schemas/benchmark_case.schema.json',b)
            if er: raise ValueError('benchmark schema: '+er)
            er=_schema_ok(contracts/task/'schemas/evaluation_case.schema.json',ecase)
            if er: raise ValueError('evaluation schema: '+er)
        except Exception as exc: errors.append(f'{task}/{cid}: {type(exc).__name__}: {exc}')
    hp=root/'SHA256SUMS.txt'
    if not hp.is_file(): errors.append('missing SHA256SUMS.txt')
    else:
        for line in hp.read_text(encoding='utf-8').splitlines():
            if not line: continue
            expected,rel=line.split('  ',1); p=root/rel
            if not p.is_file() or _sha(p)!=expected: errors.append(f'SHA256 mismatch: {rel}')
    return {'valid':not errors,'case_count':count,'errors':errors}
