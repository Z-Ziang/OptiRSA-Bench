from __future__ import annotations

import hashlib
import json
from itertools import combinations
from math import prod
from pathlib import Path
from typing import Iterable
import re

from src.case_core.config import OFamilyConfig, load_o_family_config
from src.case_core.exporter import export_dataset
from src.case_core.scenario_loader import PublicEnvironmentIndex, load_public_environment
from src.case_core.search import SearchBudgetExceeded
from src.tasks.o1.producer import build_o1_case
from src.tasks.o2_s.producer import build_o2s_case
from src.tasks.o2_c.producer import build_o2c_case

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _case_id(task: str, ordinal: int, namespace: str | None) -> str:
    if namespace is None:
        return f'{task}_{ordinal:06d}'
    safe = re.sub(r'[^A-Za-z0-9_.-]+', '_', str(namespace)).strip('_')
    if not safe:
        raise ValueError('case_id_namespace must contain an identifier character')
    return f'{task}_{safe}_{ordinal:06d}'


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        rel = path.relative_to(root).as_posix().encode('utf-8')
        digest.update(len(rel).to_bytes(4, 'big'))
        digest.update(rel)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, 'big'))
        digest.update(data)
    return digest.hexdigest()


def _action_count(env: PublicEnvironmentIndex, request_id: str, candidate_k: int | None = None) -> int:
    deriv = env.derivations[request_id]
    paths = sorted(deriv.get('candidate_paths', []), key=lambda x: int(x['rank']))
    if candidate_k is not None:
        paths = paths[:candidate_k]
    total = 0
    for path in paths:
        starts = path.get('feasible_slot_starts')
        if isinstance(starts, list):
            total += len(starts)
    if total:
        return total
    value = deriv.get('feasible_action_count')
    return int(value) if isinstance(value, int) else 10**12



def _path_action_count(env: PublicEnvironmentIndex, request_id: str, path_rank: int) -> int:
    paths=sorted(env.derivations[request_id].get('candidate_paths', []), key=lambda x:int(x['rank']))
    if path_rank < 1 or path_rank > len(paths):
        return 10**12
    starts=paths[path_rank-1].get('feasible_slot_starts')
    return len(starts) if isinstance(starts,list) else 10**12

def _subset_request_ids(env: PublicEnvironmentIndex, item: dict, count: int, selection: str, candidate_k: int | None = None) -> list[str] | None:
    ids = [str(x) for x in item.get('request_ids', [])]
    if len(ids) < count:
        return None
    if selection == 'LOW_ACTION':
        ids = sorted(ids, key=lambda rid: (_action_count(env, rid, candidate_k), rid))
    return ids[:count]


def _concurrent_candidates(env: PublicEnvironmentIndex, counts: Iterable[int], selection: str, candidate_k: int | None = None, fixed_path_rank: int | None = None) -> list[tuple[str, list[str], float, int]]:
    candidates: list[tuple[str, list[str], float, int]] = []
    for set_id, item in sorted(env.concurrent_sets.items()):
        ids = [str(x) for x in item.get('request_ids', [])]
        for count in counts:
            count=int(count)
            if len(ids) < count:
                continue
            groups = list(combinations(ids,count)) if selection == 'LOW_ACTION' else [tuple(ids[:count])]
            for group in groups:
                score = float(item.get('candidate_path_link_overlap_density') or 0.0)
                if fixed_path_rank is not None:
                    estimate=prod(_path_action_count(env,rid,fixed_path_rank) for rid in group)
                else:
                    estimate=prod(_action_count(env,rid,candidate_k) for rid in group)
                candidates.append((set_id,list(group),score,int(estimate)))
    if selection in {'HIGH_CONFLICT_O1', 'HIGH_CONFLICT_O2C'}:
        candidates.sort(key=lambda x: (-x[2], x[0], tuple(x[1])))
    elif selection == 'LOW_ACTION':
        candidates.sort(key=lambda x: (x[3], x[0], tuple(x[1])))
    else:
        candidates.sort(key=lambda x: (x[0], len(x[1]), tuple(x[1])))
    return candidates


def _o1_bundles(env: PublicEnvironmentIndex, cfg, *, allow_shortfall: bool, case_id_namespace: str | None = None) -> list[dict]:
    if not cfg.enabled or cfg.case_count == 0:
        return []
    specs=[]
    for rank in cfg.fixed_path_rank_values:
        for set_id, ids, score, estimate in _concurrent_candidates(env, cfg.request_count_values, cfg.selection, fixed_path_rank=rank):
            if all(len(env.derivations[rid].get('candidate_paths', [])) >= rank for rid in ids):
                specs.append((estimate,set_id,ids,rank,score))
    if cfg.selection == 'LOW_ACTION':
        specs.sort(key=lambda x:(x[0],x[3],x[1],tuple(x[2])))
    bundles=[]
    for _estimate, set_id, ids, rank, _score in specs:
        if len(bundles) >= cfg.case_count:
            break
        try:
            bundle=build_o1_case(env, ids, case_id=_case_id('O1', len(bundles)+1, case_id_namespace), fixed_path_rank=rank, max_complete_solutions=cfg.max_complete_solutions)
        except SearchBudgetExceeded:
            continue
        bundle['lineage']['source_concurrent_request_set_id']=set_id
        bundle['features']['source_action_product_estimate']=_estimate
        bundles.append(bundle)
    if len(bundles) < cfg.case_count and not allow_shortfall:
        raise ValueError(f'O1 requested {cfg.case_count} cases but source environment supports {len(bundles)} exact cases under this config')
    return bundles


def _o2s_bundles(env: PublicEnvironmentIndex, cfg, *, allow_shortfall: bool, case_id_namespace: str | None = None) -> list[dict]:
    if not cfg.enabled or cfg.case_count == 0:
        return []
    specs=[]
    for k in cfg.candidate_k_values:
        ids=[rid for rid in env.requests if rid in env.derivations and len(env.derivations[rid].get('candidate_paths', [])) >= k]
        if cfg.selection == 'LOW_ACTION':
            ids.sort(key=lambda rid: (_action_count(env, rid, k), rid))
        else:
            ids.sort()
        specs.extend((rid, k) for rid in ids)
    bundles=[]
    for i, (rid, k) in enumerate(specs[:cfg.case_count], 1):
        bundles.append(build_o2s_case(env, rid, case_id=_case_id('O2S', i, case_id_namespace), candidate_k=k, max_complete_solutions=cfg.max_complete_solutions))
    if len(bundles) < cfg.case_count and not allow_shortfall:
        raise ValueError(f'O2-S requested {cfg.case_count} cases but source environment supports {len(bundles)} under this config')
    return bundles


def _o2c_bundles(env: PublicEnvironmentIndex, cfg, *, allow_shortfall: bool, case_id_namespace: str | None = None) -> list[dict]:
    if not cfg.enabled or cfg.case_count == 0:
        return []
    specs=[]
    for k in cfg.candidate_k_values:
        for set_id, ids, score, estimate in _concurrent_candidates(env, cfg.request_count_values, cfg.selection, k):
            if all(len(env.derivations[rid].get('candidate_paths', [])) >= k for rid in ids):
                specs.append((estimate,set_id,ids,k,score))
    if cfg.selection == 'LOW_ACTION':
        specs.sort(key=lambda x:(x[0],x[3],x[1],tuple(x[2])))
    bundles=[]
    for _estimate, set_id, ids, k, _score in specs:
        if len(bundles) >= cfg.case_count:
            break
        try:
            bundle=build_o2c_case(env, ids, case_id=_case_id('O2C', len(bundles)+1, case_id_namespace), candidate_k=k, max_complete_solutions=cfg.max_complete_solutions)
        except SearchBudgetExceeded:
            continue
        bundle['lineage']['source_concurrent_request_set_id']=set_id
        bundle['features']['source_action_product_estimate']=_estimate
        bundles.append(bundle)
    if len(bundles) < cfg.case_count and not allow_shortfall:
        raise ValueError(f'O2-C requested {cfg.case_count} cases but source environment supports {len(bundles)} exact cases under this config')
    return bundles


def derive_o_family_dataset(environment_root: str | Path, config_path: str | Path, output_root: str | Path, *, case_id_namespace: str | None = None) -> dict:
    environment_root=Path(environment_root).resolve()
    config=load_o_family_config(config_path)
    env=load_public_environment(environment_root)
    bundles={
        'O1': _o1_bundles(env, config.o1, allow_shortfall=config.execution.allow_shortfall, case_id_namespace=case_id_namespace or config.case_id_namespace),
        'O2-S': _o2s_bundles(env, config.o2s, allow_shortfall=config.execution.allow_shortfall, case_id_namespace=case_id_namespace or config.case_id_namespace),
        'O2-C': _o2c_bundles(env, config.o2c, allow_shortfall=config.execution.allow_shortfall, case_id_namespace=case_id_namespace or config.case_id_namespace),
    }
    metadata={
        'profile': config.profile,
        'seed': config.seed,
        'config_sha256': config.config_sha256,
        'source_environment_sha256': _tree_sha256(environment_root),
        'producer_contract_version': 'O_FAMILY_CASE_PRODUCER_V1_2_ALGORITHM_VIEW',
        'case_id_namespace': case_id_namespace or config.case_id_namespace,
    }
    return export_dataset(output_root, bundles, contracts_root=PROJECT_ROOT/'contracts', production_metadata=metadata)


def produce_environment_and_cases(environment_config: str | Path, case_config: str | Path, output_root: str | Path) -> dict:
    """Run the inherited batch producer and derive O-family Cases from every released unit.

    The returned output contains `public_environment_batch/` and one O-family dataset per
    released topology under `datasets/<topology_id>/`. The inherited runner remains the
    sole environment generator.
    """
    from src.production.batch import run_batch
    from src.production.config import load_production_config

    output_root=Path(output_root).resolve()
    batch_root=output_root/'public_environment_batch'
    cfg=load_production_config(Path(environment_config))
    result=run_batch(cfg, batch_root)
    if result.get('status') != 'PASS':
        raise RuntimeError(f"public-environment batch did not PASS: {result.get('status')}")
    datasets={}
    for unit in sorted((batch_root/'units').iterdir()):
        if not unit.is_dir():
            continue
        env_root=unit/'public_environment'
        dataset_root=output_root/'datasets'/unit.name
        datasets[unit.name]=derive_o_family_dataset(env_root, case_config, dataset_root, case_id_namespace=unit.name)
    return {
        'status':'PASS',
        'public_environment_batch_id': result.get('batch_id'),
        'topology_count': len(datasets),
        'datasets': datasets,
    }
