"""Reproducible exploratory sampling and coverage-aware reporting. No API calls."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import random
import statistics
import math
import subprocess
import sys
from benchlib import ROOT, manifest, public_messages, readjson

FIELDS = ('task', 'scale', 'decision', 'load_band', 'request_count')


def stratum(row):
    return tuple(row[k] for k in FIELDS)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def write_csv(path, rows):
    if rows:
        with path.open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def plan(args):
    if args.per_task < 1:
        raise SystemExit('--per-task must be positive')
    out = Path(args.output)
    if out.exists():
        raise SystemExit('plan directory exists; use a new directory to preserve the frozen selection')
    population = manifest()
    excluded = set()
    for directory in args.exclude_results:
        path = Path(directory) / 'run_config.json'
        excluded.update(readjson(path)['case_uids'])
    pool = [r for r in population if r['case_uid'] not in excluded]
    rng = random.Random(args.seed)
    selected = []
    topology_use, snapshot_use, family_use = Counter(), Counter(), Counter()
    for task in ('X2', 'X3'):
        groups = defaultdict(list)
        for row in pool:
            if row['task'] == task:
                groups[stratum(row)].append(row)
        if sum(map(len, groups.values())) < args.per_task:
            raise SystemExit(f'not enough eligible cases for {task}')
        if args.per_task < len(groups):
            raise SystemExit(f'{task} requires at least {len(groups)} samples to cover all existing strata')
        for rows in groups.values():
            rows.sort(key=lambda r: r['case_uid'])
            rng.shuffle(rows)
        keys = sorted(groups)
        rng.shuffle(keys)
        count = 0
        while count < args.per_task:
            for key in keys:
                rows = groups[key]
                if not rows:
                    continue
                # Seeded order breaks ties. Prefer unused families, snapshots and topologies.
                row = min(rows, key=lambda r: (
                    sum(family_use[f] for f in r['family_ids']),
                    snapshot_use[(r['graph_hash'], r['snapshot_hash'])],
                    topology_use[r['graph_hash']],
                ))
                rows.remove(row)
                selected.append(row)
                topology_use[row['graph_hash']] += 1
                snapshot_use[(row['graph_hash'], row['snapshot_hash'])] += 1
                family_use.update(row['family_ids'])
                count += 1
                if count == args.per_task:
                    break
    # Verify every public input before writing a runnable plan.
    for row in selected:
        public_messages(row)
    available = Counter(stratum(r) for r in pool)
    full = Counter(stratum(r) for r in population)
    chosen = Counter(stratum(r) for r in selected)
    coverage = [dict(zip(FIELDS, key), population=full[key], eligible=available[key],
                     selected=chosen[key]) for key in sorted(full)]
    data = {
        'version': 1, 'purpose': 'exploratory', 'seed': args.seed,
        'per_task': args.per_task,
        'sampling': 'equal allocation across existing strata within each task, redistribute exhausted strata; prefer family/snapshot/topology diversity',
        'dataset_manifest_sha256': hashlib.sha256((ROOT/'case_sets/_index/cases.jsonl').read_bytes()).hexdigest(),
        'excluded_case_uids': sorted(excluded),
        'cases': [{k: r[k] for k in ('case_uid', 'messages_sha256', *FIELDS, 'topology_folder', 'graph_hash', 'snapshot_hash', 'family_ids', 'input_characters')} for r in selected],
        'coverage': coverage,
        'diversity': {'graphs': len(topology_use), 'snapshots': len(snapshot_use),
                      'families': len(family_use), 'repeated_families': sum(n > 1 for n in family_use.values())},
        'max_input_characters': max(r['input_characters'] for r in selected),
        'interpretation': 'Balanced diagnostic sample; raw rates are not population-weighted. Families and snapshots may be correlated. WUFR definition is not public in current prompts.',
    }
    out.mkdir(parents=True)
    write_json(out/'selection.json', data)
    write_csv(out/'coverage.csv', coverage)
    print(json.dumps({'selection': str(out/'selection.json'), 'selected': len(selected),
                      'tasks': dict(Counter(r['task'] for r in selected)),
                      'decisions': dict(Counter(r['decision'] for r in selected)),
                      'diversity': data['diversity'], 'API_requests': 0}, ensure_ascii=False, indent=2))


def metrics(rows, answers):
    records = [answers[r['case_uid']] for r in rows if r['case_uid'] in answers]
    categories = Counter(r.get('result', {}).get('category', r['status']) for r in records)
    scored = [r for r in records if r.get('result', {}).get('category') in ('CORRECT', 'SUBOPTIMAL', 'INFEASIBLE', 'MISSING')]
    feasible = [r for r in scored if r['result']['truth_feasible']]
    impossible = [r for r in scored if not r['result']['truth_feasible']]
    optimal = sum(r['result']['category'] == 'CORRECT' for r in feasible)
    valid = sum(r['result']['category'] in ('CORRECT', 'SUBOPTIMAL') for r in feasible)
    primary = sum(r['result'].get('validator', {}).get('valid', False) and
                  (lambda m: m.get('hop_gap', m.get('delta_tso_gap')) == 0)(r['result'].get('validator', {}).get('metrics', {})) for r in feasible)
    times = [r['total_seconds'] for r in records if isinstance(r.get('total_seconds'), (float, int))]
    tokens = Counter()
    for record in records:
        for usage in record.get('usage', {}).values():
            for key in ('input_tokens', 'output_tokens', 'reasoning_tokens', 'total_tokens'):
                tokens[key] += usage.get(key) or 0
    return dict(planned=len(rows), recorded=len(records), pending=len(rows)-len(records),
                responses_received=sum(r['status']=='RESPONSE_RECEIVED' for r in records),
                scored=len(scored), feasible_truth=len(feasible), OPTIMAL=optimal,
                SUBOPTIMAL=sum(r['result']['category']=='SUBOPTIMAL' for r in feasible),
                INFEASIBLE=sum(r['result']['category']=='INFEASIBLE' for r in feasible),
                MISSING=sum(r['result']['category']=='MISSING' for r in feasible),
                infeasible_truth=len(impossible), correct_reject=sum(r['result'].get('correct_reject',False) for r in impossible),
                incorrect_accept=sum(r['result']['category']=='INFEASIBLE' for r in impossible),
                service_error=sum(r['status']=='SERVICE_ERROR' for r in records),
                review=sum(n for k,n in categories.items() if k.startswith('REVIEW')),
                scoring_error=categories['SCORING_ERROR'],
                feasible_rate=valid/len(feasible) if feasible else None,
                primary_optimal_rate=primary/len(feasible) if feasible else None,
                full_optimal_rate=optimal/len(feasible) if feasible else None,
                mean_seconds=statistics.mean(times) if times else None,
                p95_seconds=sorted(times)[max(0, math.ceil(.95*len(times))-1)] if times else None,
                **{k: tokens[k] for k in ('input_tokens','output_tokens','reasoning_tokens','total_tokens')})


def report(args):
    selection = readjson(args.selection)
    rows = selection['cases']
    out = Path(args.results)
    if not out.is_dir():
        raise SystemExit('results directory does not exist')
    run_path = out/'run_config.json'
    if run_path.exists():
        run = readjson(run_path)
        if run['case_uids'] != [r['case_uid'] for r in rows] or run['input_hashes'] != [r['messages_sha256'] for r in rows] or run['dataset_manifest_sha256'] != selection['dataset_manifest_sha256']:
            raise SystemExit('selection does not match frozen run')
    answers = {p.stem: readjson(p) for p in (out/'answers').glob('*.json')}
    if set(answers) - {r['case_uid'] for r in rows}:
        raise SystemExit('results contain cases outside selection')
    table = []
    for dimensions in [('task',), FIELDS, ('task', 'topology_folder')]:
        groups = defaultdict(list)
        for row in rows:
            groups[tuple(row[k] for k in dimensions)].append(row)
        for key, group in sorted(groups.items()):
            table.append(dict(group_by='|'.join(dimensions),
                              **{k: key[dimensions.index(k)] if k in dimensions else '' for k in (*FIELDS,'topology_folder')},
                              **metrics(group, answers)))
    result = {'overall': metrics(rows, answers), 'groups': table,
              'interpretation': selection['interpretation']}
    write_json(out/'stratified_summary.json', result)
    write_csv(out/'stratified_summary.csv', table)
    print(json.dumps(result['overall'], ensure_ascii=False, indent=2))


def run(args):
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=False)
    cmd = [sys.executable, str(ROOT/'evaluation/run_eval.py'),
           '--case-list', args.selection, '--output', args.results]
    if args.config:
        cmd.extend(['--config', args.config])
    if args.resume:
        cmd.append('--resume')
    if args.offline_reference:
        cmd.append('--offline-reference')
    if args.dry_run:
        cmd.append('--dry-run')
    completed = subprocess.run(cmd, check=False)
    if not args.dry_run and (Path(args.results)/'run_config.json').exists():
        report(args)
    raise SystemExit(completed.returncode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan')
    p.add_argument('--output', required=True)
    p.add_argument('--per-task', type=int, default=100)
    p.add_argument('--seed', type=int, default=20261015)
    p.add_argument('--exclude-results', action='append', default=[], help='Prior run directory; repeatable')
    p.set_defaults(func=plan)
    p = sub.add_parser('report')
    p.add_argument('--selection', required=True)
    p.add_argument('--results', required=True)
    p.set_defaults(func=report)
    p = sub.add_parser('run', help='Run frozen cases and produce stratified reports; loads root .env')
    p.add_argument('--selection', required=True)
    p.add_argument('--results', required=True)
    p.add_argument('--config')
    p.add_argument('--resume', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--offline-reference', action='store_true')
    p.set_defaults(func=run)
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
