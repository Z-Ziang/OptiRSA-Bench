from __future__ import annotations
import hashlib,json,shutil
from pathlib import Path
from jsonschema import Draft202012Validator
from src.case_core.serialization_metrics import compute_serialization_metrics
from src.i1.version import I1_PRODUCER_VERSION

TASKS=("I1-S","I1-C","I1-D")

def _write_json(path: Path,obj,*,sort_keys=False):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=sort_keys)+"\n",encoding="utf-8")

def _sha(path: Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _serialization_metrics(prompt: str) -> dict:
    try:
        dual=compute_serialization_metrics(prompt)
        return {
            'prompt_char_count': dual['llm_prompt_char_count'],
            'prompt_utf8_bytes': dual['llm_prompt_utf8_bytes'],
            'prompt_token_count': dual['llm_prompt_token_count'],
            'canonical_tokenizer': dual['canonical_tokenizer'],
        }
    except RuntimeError as exc:
        return {
            'prompt_char_count': len(prompt),
            'prompt_utf8_bytes': len(prompt.encode('utf-8')),
            'prompt_token_count': None,
            'canonical_tokenizer': {
                'backend': 'tiktoken',
                'encoding': 'o200k_base',
                'package_version': None,
                'available': False,
                'error': str(exc),
            },
        }

def _validate(schema_path: Path,obj,label: str):
    schema=json.loads(schema_path.read_text(encoding='utf-8'))
    errs=sorted(Draft202012Validator(schema).iter_errors(obj),key=lambda e:list(e.path))
    if errs: raise ValueError(f"{label} schema violation: {errs[0].message}")

def export_i1_dataset(output_root: Path|str, records_by_task: dict, *, contracts_root: Path|str, production_metadata: dict) -> dict:
    root=Path(output_root).resolve(); contracts=Path(contracts_root).resolve()
    if root.exists(): shutil.rmtree(root)
    root.mkdir(parents=True)
    rows=[]; counts={}
    for task in TASKS:
        records=records_by_task.get(task,[]); counts[task]=len(records)
        if records:
            for base in (root/'benchmark_case'/task, root/'evaluation_case'/task):
                base.mkdir(parents=True,exist_ok=True)
                shutil.copy2(contracts/task/'llm_system_prompt.txt',base/'llm_system_prompt.txt')
            shutil.copytree(contracts/task,root/'internal/contracts'/task)
        for ordinal,rec in enumerate(records,1):
            cid=rec['case_id']; prompt=rec['final_prompt']; answer=rec['canonical_answer']
            benchmark={'case_id':cid,'llm_prompt':prompt,'answer':answer}
            evaluation={'case_id':cid,'prompt':prompt}
            _validate(contracts/task/'schemas/benchmark_case.schema.json',benchmark,f'{task}/{cid}/benchmark')
            _validate(contracts/task/'schemas/evaluation_case.schema.json',evaluation,f'{task}/{cid}/evaluation')
            _validate(contracts/task/'output_schema.json',answer,f'{task}/{cid}/answer')
            name=f'case_{ordinal:06d}.json'
            bp=root/'benchmark_case'/task/'cases'/name
            ep=root/'evaluation_case'/task/'cases'/name
            _write_json(bp,benchmark); _write_json(ep,evaluation)
            internal=root/'internal/cases'/task/cid
            _write_json(internal/'canonical_answer.json',answer,sort_keys=True)
            (internal/'base_prompt.txt').parent.mkdir(parents=True,exist_ok=True)
            (internal/'base_prompt.txt').write_text(rec['base_prompt']+'\n',encoding='utf-8')
            _write_json(internal/'rewrite.json',rec['rewrite'],sort_keys=True)
            _write_json(internal/'validation.json',rec['validation'],sort_keys=True)
            _write_json(internal/'lineage.json',rec['lineage'],sort_keys=True)
            features={'serialization_metrics':_serialization_metrics(prompt)}
            _write_json(internal/'features.json',features,sort_keys=True)
            rows.append({
                'case_id':cid,'task_type':task,'source_ref':rec['source_ref'],'features':features,
                'benchmark_case_path':bp.relative_to(root).as_posix(),
                'evaluation_case_path':ep.relative_to(root).as_posix(),
                'internal_case_dir':internal.relative_to(root).as_posix(),
            })
    rows.sort(key=lambda r:(r['task_type'],r['case_id']))
    (root/'case_index.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows),encoding='utf-8')
    summary={'schema_version':'I1_PRODUCTION_SUMMARY_V2_1_3','producer_version':I1_PRODUCER_VERSION,'case_count':len(rows),'task_counts':counts,'production_metadata':production_metadata,'benchmark_interface':'I1_LLM_ONLY_LLM_PROMPT_ANSWER_V2_1_3'}
    _write_json(root/'production_summary.json',summary,sort_keys=True)
    files=[]
    for p in sorted(x for x in root.rglob('*') if x.is_file() and x.name not in {'RUN_MANIFEST.json','SHA256SUMS.txt'}):
        files.append({'path':p.relative_to(root).as_posix(),'size_bytes':p.stat().st_size,'sha256':_sha(p)})
    _write_json(root/'RUN_MANIFEST.json',{'schema_version':'I1_RUN_MANIFEST_V2_1_3','producer_version':I1_PRODUCER_VERSION,'file_count':len(files),'files':files},sort_keys=True)
    lines=[f"{_sha(p)}  {p.relative_to(root).as_posix()}" for p in sorted(x for x in root.rglob('*') if x.is_file() and x.name!='SHA256SUMS.txt')]
    (root/'SHA256SUMS.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return summary

