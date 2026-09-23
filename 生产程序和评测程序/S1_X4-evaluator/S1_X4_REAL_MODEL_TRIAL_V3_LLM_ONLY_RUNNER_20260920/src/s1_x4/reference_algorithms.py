from __future__ import annotations
from copy import deepcopy
from concurrent.futures import ProcessPoolExecutor
from math import log
import os
import networkx as nx
from src.s1_x4.algorithm_api.environment import AlgorithmEpisodeEnvironment
from src.s1_x4.state_machine import network_utilization
from src.s1_x4.validators import validate_s1_response, validate_x4_response
from src.s1_x4.candidate_actions import deterministic_k_paths, enumerate_feasible_actions
from src.s1_x4.efm import network_efm
from src.state_simulation.core import free_blocks

S1_POLICIES=('KSP-FF','KSP-BF','FF-KSP','BF-KSP','KME-FF','KSP-EFM')
X4_POLICIES=S1_POLICIES+('SW-SP','SW-EFM')

def _common_bits(path, spectrum):
    n=len(next(iter(spectrum.values())))
    return [int(all(spectrum[int(lid)][s]==1 for lid in path['path_link_ids'])) for s in range(n)]

def _block_residual(action, paths, spectrum, required):
    p=next(p for p in paths if int(p['path_rank'])==int(action['path_rank']))
    st=int(action['slot_start'])
    for a,l in free_blocks(_common_bits(p,spectrum)):
        if a<=st and st+required<=a+l: return l-required
    raise RuntimeError('action not contained in common free block')

def _entropy(bits):
    blocks=[length for _,length in free_blocks(bits)]; total=sum(blocks)
    if total<=0 or len(blocks)<=1: return 0.0
    return -sum((b/total)*log(b/total) for b in blocks)

def _link_efm(bits):
    free=sum(bits)
    if free==0: return None
    best=run=0
    for bit in bits:
        if bit==1:
            run+=1; best=max(best,run)
        else: run=0
    return 1.0-best/free


def _base_efm(spectrum):
    values={int(row['link_id']):row['external_fragmentation'] for row in network_efm(spectrum)['link_efm']}
    defined=[value for value in values.values() if value is not None]
    return values,sum(defined),len(defined)


def _simulate_efm(spectrum, action, required, base=None):
    """Compute post-action EFM; optional base makes candidate scoring linear."""
    if base is None:
        s={k:list(v) for k,v in spectrum.items()}
        for lid in action['path_link_ids']:
            for pos in range(int(action['slot_start']),int(action['slot_start'])+required): s[int(lid)][pos]=0
        return network_efm(s)['network_efm']
    values,base_sum,base_count=base
    total=base_sum; count=base_count
    for lid in dict.fromkeys(int(x) for x in action['path_link_ids']):
        old=values[lid]
        bits=list(spectrum[lid])
        for pos in range(int(action['slot_start']),int(action['slot_start'])+required): bits[pos]=0
        new=_link_efm(bits)
        if old is not None: total-=old; count-=1
        if new is not None: total+=new; count+=1
    return total/count if count else None

def _choose_k_policy(policy, paths, actions, spectrum, required):
    if not actions: return None
    if policy=='KSP-FF': return min(actions,key=lambda a:(a['path_rank'],a['slot_start']))
    if policy=='KSP-BF':
        rank=min(a['path_rank'] for a in actions); pool=[a for a in actions if a['path_rank']==rank]
        return min(pool,key=lambda a:(_block_residual(a,paths,spectrum,required),a['slot_start']))
    if policy=='FF-KSP': return min(actions,key=lambda a:(a['slot_start'],a['path_rank']))
    if policy=='BF-KSP': return min(actions,key=lambda a:(_block_residual(a,paths,spectrum,required),a['slot_start'],a['path_rank']))
    if policy=='KME-FF':
        reps=[]
        for rank in sorted(set(a['path_rank'] for a in actions)):
            a=min((x for x in actions if x['path_rank']==rank),key=lambda x:x['slot_start']); p=next(p for p in paths if p['path_rank']==rank)
            before=sum(_entropy(spectrum[int(lid)]) for lid in p['path_link_ids']); s={k:list(v) for k,v in spectrum.items()}
            for lid in p['path_link_ids']:
                for pos in range(a['slot_start'],a['slot_start']+required): s[int(lid)][pos]=0
            after=sum(_entropy(s[int(lid)]) for lid in p['path_link_ids']); reps.append((after-before,rank,a))
        return min(reps,key=lambda x:(x[0],x[1]))[2]
    if policy=='KSP-EFM':
        base=_base_efm(spectrum)
        scored=[]
        for a in actions:
            v=_simulate_efm(spectrum,a,required,base); scored.append((v is None, float('inf') if v is None else v,a['path_rank'],a['slot_start'],a))
        return min(scored,key=lambda x:x[:4])[4]
    raise ValueError(policy)

def _window_shortest(ctx, required):
    links=ctx['directed_links']; spectrum=ctx['spectrum_by_link']; req=ctx['request']; slot_count=ctx['slot_count']; out=[]
    source=int(req['source_node_id']); target=int(req['destination_node_id'])
    # The former implementation enumerated every shortest simple path for every
    # slot window.  Since every returned path has the same minimum hop count,
    # the exact ``min((link_id_tuple, node_tuple))`` tie-break can be obtained
    # by distance filtering followed by greedy link-id selection.  This keeps
    # the reference semantics while avoiding exponential path enumeration.
    linkmap={(int(r['source_node_id']),int(r['destination_node_id'])):int(r['link_id']) for r in links}
    window_count=slot_count-required+1
    eligible_pairs_by_start=[[] for _ in range(window_count)]
    # A bit at position ``s`` denotes a free slot.  Intersecting shifted
    # availability masks is exactly the old contiguous-window predicate, but
    # removes the repeated Python slice scan from every step/window.
    start_mask=(1 << window_count)-1
    for r in links:
        lid=int(r['link_id'])
        availability=sum((int(value) & 1) << index for index,value in enumerate(spectrum[lid]))
        valid_mask=availability
        for offset in range(1,required):
            valid_mask &= availability >> offset
        valid_mask &= start_mask
        pair=(int(r['source_node_id']),int(r['destination_node_id']))
        while valid_mask:
            lowest=valid_mask & -valid_mask
            eligible_pairs_by_start[lowest.bit_length()-1].append(pair)
            valid_mask ^= lowest

    for start, eligible_pairs_list in enumerate(eligible_pairs_by_start):
        eligible_pairs=set(eligible_pairs_list)
        adjacency={}
        reverse={}
        for u,v in eligible_pairs:
            adjacency.setdefault(u,[]).append(v)
            reverse.setdefault(v,[]).append(u)

        def distances(begin, graph):
            result={begin:0}; queue=[begin]
            for node in queue:
                for nxt in graph.get(node,()):
                    if nxt not in result:
                        result[nxt]=result[node]+1; queue.append(nxt)
            return result

        from_source=distances(source, adjacency)
        if target not in from_source:
            continue
        to_target=distances(target, reverse)
        dist=from_source[target]
        nodes=[source]; lids=[]; current=source
        for step in range(dist):
            choices=[
                nxt for nxt in adjacency.get(current,())
                if from_source.get(nxt)==step+1 and to_target.get(nxt)==dist-step-1
            ]
            if not choices:
                nodes=[]
                break
            nxt=min(choices,key=lambda node:(linkmap[(current,node)],node))
            lids.append(linkmap[(current,nxt)]); nodes.append(nxt); current=nxt
        if nodes and current==target:
            out.append({'path_rank':0,'path_link_ids':list(lids),'path_node_ids':list(nodes),'slot_start':start,'hop_count':len(lids)})
    return out

def _choose_x4(policy, ctx, reference_k):
    req=ctx['request']; required=int(req['required_slots'])
    if policy in S1_POLICIES:
        directed={'directed_link_records':ctx['directed_links']}; paths=deterministic_k_paths(directed,req['source_node_id'],req['destination_node_id'],reference_k)
        actions=enumerate_feasible_actions(paths,ctx['spectrum_by_link'],required); return _choose_k_policy(policy,paths,actions,ctx['spectrum_by_link'],required)
    windows=_window_shortest(ctx,required)
    if not windows: return None
    if policy=='SW-SP': return min(windows,key=lambda a:(a['hop_count'],a['slot_start'],tuple(a['path_link_ids'])))
    if policy=='SW-EFM':
        base=_base_efm(ctx['spectrum_by_link'])
        scored=[]
        for a in windows:
            v=_simulate_efm(ctx['spectrum_by_link'],a,required,base); scored.append((v is None,float('inf') if v is None else v,a['hop_count'],a['slot_start'],tuple(a['path_link_ids']),a))
        return min(scored,key=lambda x:x[:5])[5]
    raise ValueError(policy)

def _observation_context(static, observation):
    """Convert only the current compiled observation to legacy chooser shapes."""

    return {
        'request':dict(observation.request),
        'directed_links':static.topology.to_public_dict()['directed_links'],
        'spectrum_by_link':observation.spectrum.to_binary_by_link(),
        'slot_count':int(observation.spectrum.slot_count),
    }


def _reference_response(policy, static, observation, reference_k):
    """Reference callback boundary: static topology + current observation only."""

    if observation.task_type == 'S1':
        paths=[p.to_public_dict() for p in observation.candidate_paths or ()]
        by_rank={int(path['path_rank']):path for path in paths}
        actions=[{
            'path_rank':int(row[0]),
            'slot_start':int(row[1]),
            'path_node_ids':list(by_rank[int(row[0])]['path_node_ids']),
            'path_link_ids':list(by_rank[int(row[0])]['path_link_ids']),
        } for row in observation.feasible_actions.tolist()]
        required=int(observation.request['required_slots'])
        selected=_choose_k_policy(policy,paths,actions,observation.spectrum.to_binary_by_link(),required)
        return {'decision':'REJECT','path_rank':None,'slot_start':None} if selected is None else {
            'decision':'ACCEPT','path_rank':selected['path_rank'],'slot_start':selected['slot_start']}
    context=_observation_context(static,observation)
    selected=_choose_x4(policy,context,reference_k)
    return {'decision':'REJECT','path_node_ids':[],'path_link_ids':[],'slot_start':None} if selected is None else {
        'decision':'ACCEPT','path_node_ids':selected['path_node_ids'],
        'path_link_ids':selected['path_link_ids'],'slot_start':selected['slot_start']}


def _run_policy(episode, policy):
    """Run a reference policy through the same official Algorithm environment."""

    initial_spectrum={int(x['link_id']):list(x['slot_availability']) for x in episode['initial_link_spectrum_states']}
    initial_efm=network_efm(initial_spectrum)['network_efm']
    initial_utilization=network_utilization(initial_spectrum)
    environment=AlgorithmEpisodeEnvironment(episode)
    observation=environment.reset()
    trajectory=[]
    reference_k=int(episode.get('task_config',{}).get('reference_k',3))
    while not environment.done:
        response=_reference_response(policy,environment.static_context,observation,reference_k)
        result=environment.step(response)
        trajectory.append(result.trajectory_record)
        observation=result.next_observation
    tr=trajectory; h=len(tr); blocked=sum(x['blocked'] for x in tr); vals=[x['post_decision_network_efm'] for x in tr if x['post_decision_network_efm'] is not None]
    efm_series=[x['post_decision_network_efm'] for x in tr]
    util_series=[x['post_decision_network_utilization'] for x in tr]
    return {'policy_name':policy,'episode_length':h,'established_count':h-blocked,'blocked_count':blocked,'rbr':blocked/h if h else None,
            'initial_network_efm':initial_efm,'final_network_efm':efm_series[-1] if efm_series else initial_efm,
            'network_efm_series':efm_series,'mean_network_efm':sum(vals)/len(vals) if vals else None,
            'initial_network_utilization':initial_utilization,'final_network_utilization':util_series[-1] if util_series else initial_utilization,
            'network_utilization_series':util_series,'trajectory':tr}

def _run_policy_worker(args):
    episode, policy = args
    return _run_policy(episode, policy)


def run_reference_panel(episode: dict, *, parallel: bool = False, max_workers: int | None = None) -> dict:
    policies=S1_POLICIES if episode['task_type']=='S1' else X4_POLICIES
    if parallel:
        workers=max_workers or min(len(policies), os.cpu_count() or 1)
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results=list(pool.map(_run_policy_worker, ((episode,p) for p in policies)))
    else:
        results=[_run_policy(episode,p) for p in policies]
    return {'type':'POLICY_PANEL','episode_length':int(episode['episode_length']),
            'primary_metric':'RBR','secondary_metric':'MEAN_NETWORK_EFM',
            'policy_results':results}


def run_reference_policy(episode: dict, policy_name: str) -> dict:
    """Run one named reference through the official compiled runtime."""

    policies=S1_POLICIES if episode['task_type']=='S1' else X4_POLICIES
    if policy_name not in policies:
        raise ValueError(f'unsupported {episode["task_type"]} reference policy: {policy_name}')
    return _run_policy(episode, policy_name)


def run_reference_panel_from_run_config(run_config_or_spec, *, dataset_root, output_dir=None) -> dict:
    """Evaluator-side run-config entry point for a complete reference panel."""

    from src.s1_x4.algorithm_api.run_config import resolve_run_config

    resolved=resolve_run_config(run_config_or_spec,dataset_root=dataset_root)
    panel=run_reference_panel(resolved.episode)
    if output_dir is not None:
        from pathlib import Path
        import json

        path=Path(output_dir); path.mkdir(parents=True,exist_ok=True)
        (path/'reference_output.json').write_text(json.dumps(panel,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return panel
