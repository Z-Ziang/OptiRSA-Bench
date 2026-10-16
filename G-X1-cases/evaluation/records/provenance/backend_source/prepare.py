"""Verify immutable archives, import identity-matched history and additive cases."""
from __future__ import annotations
import argparse
import collections
import contextlib
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile
import os
import uuid
from core import MODEL, TASKS, Queue, ProcessLock, atomic_json, read_json, digest, identity_key, compatible_history


def file_sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def science_signature(identity):
    selected={k:v['sha256'] for k,v in identity['files'].items()
              if k in ('private/root_case.json','private/truth.json','private/private_truth.json')}
    selected['validator']=identity['validator_source_sha256']
    return digest(selected)


def identity_task(identity):
    task=identity.get('task') or identity.get('source_manifest_record',{}).get('task_type')
    if task not in TASKS:raise ValueError('Missing task identity')
    return task


def extract_archive(path, destination):
    """Never overwrite an existing immutable dataset; verify bytes on reuse."""
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(path) as z:
        names=[n for n in z.namelist() if n.endswith('case_sets/_index/cases.jsonl')]
        if len(names)!=1:raise ValueError('Archive must contain exactly one case index')
        prefix=names[0][:-len('case_sets/_index/cases.jsonl')]
        for info in z.infolist():
            if info.is_dir():continue
            if not info.filename.startswith(prefix):raise ValueError('File outside dataset prefix')
            rel=PurePosixPath(info.filename[len(prefix):])
            if rel.is_absolute() or '..' in rel.parts or any(':' in p for p in rel.parts):raise ValueError('Unsafe archive path')
            target=destination.joinpath(*rel.parts)
            target.parent.mkdir(parents=True,exist_ok=True)
            content=z.read(info)
            if target.exists():
                if hashlib.sha256(target.read_bytes()).digest()!=hashlib.sha256(content).digest():raise ValueError('Immutable dataset file differs: '+str(target))
            else:target.write_bytes(content)
    return destination


def verify_catalog(dataset):
    dataset=Path(dataset).resolve()
    rows=[json.loads(s) for s in (dataset/'case_sets/_index/cases.jsonl').read_text(encoding='utf-8-sig').splitlines() if s.strip()]
    seen=set();verified=0;out=[]
    runtime=dataset/'evaluation/frozen/runtime'
    runtime_hash=file_sha(runtime/'FILE_SHA256.json');adapter_hash=file_sha(dataset/'evaluation/benchlib.py')
    validator_hashes={}
    for rel,h in read_json(runtime/'FILE_SHA256.json').items():
        if file_sha(runtime/rel)!=h:raise ValueError('Frozen scientific runtime changed: '+rel)
    for row in rows:
        uid=row['case_uid']
        if uid in seen:raise ValueError('Duplicate UID in dataset')
        seen.add(uid)
        if len(uid)!=64 or any(c not in '0123456789abcdef' for c in uid):raise ValueError('Unsafe UID')
        folder=(dataset/row['case_dir']).resolve()
        if not folder.is_relative_to(dataset/'case_sets'):raise ValueError('Case outside package')
        ident=read_json(folder/'identity.json')
        if ident['case_uid']!=uid or identity_task(ident)!=row['task']:raise ValueError('Case identity mismatch')
        for rel,meta in ident['files'].items():
            target=(folder/rel).resolve()
            if not target.is_relative_to(folder) or file_sha(target)!=meta['sha256']:raise ValueError('Case payload hash mismatch: '+str(target))
            verified+=1
        messages=[{'role':role,'content':(folder/'public'/name).read_bytes().decode('utf-8')}
                  for role,name in [('system','system_prompt.txt'),('user','user_prompt.txt')]]
        if digest(messages)!=row['messages_sha256']:raise ValueError('Prompt hash mismatch')
        validator=runtime/('gx1/validators.py' if row['task'] in TASKS[:4] else 'src/tasks/'+row['task'].lower()+'/validator.py')
        if validator not in validator_hashes:validator_hashes[validator]=file_sha(validator)
        if validator_hashes[validator]!=ident['validator_source_sha256']:raise ValueError('Case validator mismatch')
        out.append({**row,'science_sha256':science_signature(ident),'dataset_root':str(dataset),
                    'runtime_sha256':runtime_hash,'adapter_sha256':adapter_hash})
        if len(out)%1000==0:print(json.dumps({'verified_cases':len(out),'dataset':str(dataset)}),flush=True)
    return out,{'cases':len(out),'payload_hash_checks':verified,'runtime_manifest_sha256':file_sha(runtime/'FILE_SHA256.json')}


def history_plan(root,archive,rows):
    by={r['case_uid']:r for r in rows};accepted=collections.defaultdict(list);rejected=[]
    with zipfile.ZipFile(archive) as z:
        old={}
        for prefix in ('datasets/GX1/','datasets/X2X3/'):
            for line in z.read(prefix+'case_sets/_index/cases.jsonl').decode('utf-8-sig').splitlines():
                if line.strip():
                    r=json.loads(line)
                    if r['case_uid'] in by:
                        ident=json.loads(z.read(prefix+r['case_dir']+'/identity.json'))
                        old[r['case_uid']]={**r,'science_sha256':science_signature(ident)}
        content=z.read('FINAL/all_recorded_attempts.jsonl')
        archive_copy=Path(root)/'history/all_recorded_attempts.jsonl'
        if archive_copy.exists() and archive_copy.read_bytes()!=content:raise ValueError('Historical snapshot changed')
        for line in content.decode('utf-8-sig').splitlines():
            if not line.strip():continue
            a=json.loads(line);uid=a.get('case_uid')
            if uid not in by or a.get('model')!=MODEL or a.get('status')!='RESPONSE_RECEIVED':continue
            prior=old.get(uid)
            if prior and compatible_history(by[uid],prior,a):accepted[uid].append(a)
            else:rejected.append({'case_uid':uid,'reason':'HISTORY_IDENTITY_OR_PAYLOAD_MISMATCH'})
    source_sha=file_sha(archive);saved=Path(root)/'history/source.json'
    if saved.exists() and read_json(saved)['sha256']!=source_sha:raise ValueError('Original historical archive identity changed')
    return {'content':content,'accepted':accepted,'rejected':rejected,'source_sha256':source_sha}


def import_history(root,archive,rows,plan):
    by={r['case_uid']:r for r in rows};accepted=plan['accepted'];rejected=plan['rejected']
    history=Path(root)/'history';history.mkdir(exist_ok=True);archive_copy=history/'all_recorded_attempts.jsonl'
    if not archive_copy.exists():
        temp=history/(uuid.uuid4().hex+'.tmp')
        with temp.open('wb') as f:f.write(plan['content']);f.flush();os.fsync(f.fileno())
        os.replace(temp,archive_copy)
    atomic_json(history/'source.json',{'archive':str(Path(archive).resolve()),'sha256':plan['source_sha256'],'index':'FINAL/all_recorded_attempts.jsonl'})
    queues={t:Queue(Path(root)/'tasks'/t/'queue.sqlite',t) for t in {r['task'] for r in rows}}
    for uid,answers in accepted.items():
        answers.sort(key=lambda a:a.get('completed_at') or '')
        selected={**answers[-1],'identity_key':identity_key(by[uid]),'historical':True,
                  'history_answer_count':len(answers),'historical_selection':'latest received response from FINAL; not normalized formal authority'}
        path=Path(root)/'tasks'/by[uid]['task']/'history'/f'{uid}.json'
        if not path.exists():atomic_json(path,selected)
        queues[by[uid]['task']].complete(uid,'HISTORICAL',selected,path)
    return {'matched_answers_by_task':dict(collections.Counter(by[u]['task'] for u in accepted)),
            'matched_case_uids':sorted(accepted),'rejected':rejected,'source_sha256':plan['source_sha256']}


def initialize(root, datasets, history=None):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True);rows=[];checks=[]
    saved=root/'history/source.json'
    if not history and saved.exists():history=read_json(saved)['archive']
    if history and not Path(history).is_file():raise FileNotFoundError('Historical archive unavailable; no cases imported')
    for data in datasets:
        rs,check=verify_catalog(data);rows+=rs;checks.append({'dataset':str(data),**check})
    if len({r['case_uid'] for r in rows})!=len(rows):raise ValueError('Overlapping supplied dataset indexes')
    affected=sorted({r['task'] for r in rows})
    staged_history=history_plan(root,history,rows) if history else None
    with contextlib.ExitStack() as stack:
        for task in affected:stack.enter_context(ProcessLock(root/'tasks'/task/'supervisor.lock'))
        # Validate every task before any queue mutation, including incremental additions.
        for task in affected:
            q=Queue(root/'tasks'/task/'queue.sqlite',task)
            signatures={(r['runtime_sha256'],r['adapter_sha256']) for r in rows if r['task']==task}
            if len(signatures)!=1:raise ValueError('Conflicting scientific adapters in one task')
            incoming=list(next(iter(signatures)));prior_adapter=q.setting('scientific_adapter')
            if prior_adapter and prior_adapter!=incoming:raise ValueError('Incremental dataset changes scientific adapter; use a separately reviewed run')
            from manage import active_processes
            if active_processes(root,task):
                raise RuntimeError('Orphan task worker still alive; stop before importing')
            existing={r['uid']:r for r in q.rows()}
            for r in rows:
                if r['task']==task:
                    prior=existing.get(r['case_uid'])
                    if prior and prior['identity_key']!=identity_key(r):raise ValueError('Case changed; import rejected: '+r['case_uid'])
        for task in affected:Queue(root/'tasks'/task/'queue.sqlite',task).setting('import_in_progress',{'datasets':[str(d) for d in datasets]})
        for task in affected:
            q=Queue(root/'tasks'/task/'queue.sqlite',task);q.add_cases([r for r in rows if r['task']==task])
            example=next(r for r in rows if r['task']==task)
            q.setting('scientific_adapter',[example['runtime_sha256'],example['adapter_sha256']])
        imported=import_history(root,history,rows,staged_history) if history else None
        summaries=[Queue(root/'tasks'/t/'queue.sqlite',t).summary() for t in affected]
        report={'datasets':checks,'history':imported,'queues':summaries,'provider_API_calls':0}
        atomic_json(root/'reports'/'last_import.json',report)
        import_id=uuid.uuid4().hex
        atomic_json(root/'reports/imports'/f'{import_id}.json',report)
        for task in affected:
            atomic_json(root/'tasks'/task/'imports'/f'{import_id}.json',report)
            Queue(root/'tasks'/task/'queue.sqlite',task).setting('import_in_progress',False)
    return report


def _live_worker(path):
    from manage import alive
    try:return alive(read_json(path))
    except (OSError,ValueError):return False


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--dataset',action='append',default=[])
    p.add_argument('--archive');p.add_argument('--history');a=p.parse_args();data=a.dataset
    if a.archive:
        tag=file_sha(a.archive)[:16]
        data.append(str(extract_archive(a.archive,Path(a.root)/'datasets'/('incremental_'+tag))))
    if not data:p.error('--dataset or --archive is required')
    history=a.history
    saved=Path(a.root)/'history/source.json'
    if not history and saved.exists():
        source=read_json(saved);history=source['archive']
    report=initialize(a.root,data,history)
    print(json.dumps({k:v for k,v in report.items() if k!='history'} | {'history_counts':(report.get('history') or {}).get('matched_answers_by_task',{})},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
