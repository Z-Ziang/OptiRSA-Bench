from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
from src.case_core.scenario_loader import load_public_environment, PublicEnvironmentIndex
from src.state_simulation.core import reconstruct_availability, ALLOWED_REQUIRED_SLOTS
from src.s1_x4.candidate_actions import deterministic_k_paths


def _index_json(directory: Path, key: str) -> dict[str,dict]:
    out={}
    if not directory.is_dir(): return out
    for p in sorted(directory.glob('*.json')):
        obj=json.loads(p.read_text(encoding='utf-8')); v=obj.get(key)
        if not isinstance(v,str) or not v: raise ValueError(f'{p}: missing {key}')
        if v in out: raise ValueError(f'duplicate {key}: {v}')
        out[v]=obj
    return out

@dataclass(frozen=True)
class DynamicPublicEnvironmentIndex:
    base: PublicEnvironmentIndex
    dynamic_sequences: dict[str,dict]
    initial_connection_sets: dict[str,dict]

    @property
    def scenarios(self): return self.base.scenarios
    @property
    def resource_states(self): return self.base.resource_states
    @property
    def directed_topologies(self): return self.base.directed_topologies
    @property
    def physical_topologies(self): return self.base.physical_topologies


def _validate_sequence(seq: dict) -> None:
    events=seq.get('dynamic_request_events')
    if not isinstance(events,list) or not events: raise ValueError('dynamic request sequence must be non-empty')
    ids=set(); last=None
    for e in events:
        rid=e.get('request_id')
        if not isinstance(rid,str) or not rid or rid in ids: raise ValueError('request_id must be unique and non-empty')
        ids.add(rid)
        t=e.get('arrival_time')
        if not isinstance(t,(int,float)) or isinstance(t,bool): raise ValueError('arrival_time must be numeric')
        if last is not None and not float(t)>last: raise ValueError('arrival_time must be strictly increasing')
        last=float(t)
        if float(e.get('holding_time',0))<=0: raise ValueError('holding_time must be positive')
        if int(e.get('required_slots',-1)) not in ALLOWED_REQUIRED_SLOTS: raise ValueError('required_slots')
        if int(e['source_node_id'])==int(e['destination_node_id']): raise ValueError('source and destination must differ')


def load_dynamic_public_environment(root: Path|str) -> DynamicPublicEnvironmentIndex:
    root=Path(root); base=load_public_environment(root)
    seqs=_index_json(root/'requests/dynamic','request_sequence_id')
    conns=_index_json(root/'connections/initial','initial_existing_connection_set_id')
    for seq in seqs.values(): _validate_sequence(seq)
    for sid,s in base.scenarios.items():
        if s.get('request_data_type')!='DYNAMIC': continue
        if s.get('request_data_id') not in seqs: raise ValueError(f'{sid}: missing dynamic sequence')
        rs=s.get('resource_state_id'); ic=s.get('initial_existing_connection_set_id')
        if rs not in base.resource_states: raise ValueError(f'{sid}: missing resource state')
        if ic not in conns: raise ValueError(f'{sid}: missing initial connection set')
        state=base.resource_states[rs]
        if state.get('initial_existing_connection_set_id') != ic: raise ValueError(f'{sid}: state/connection-set mismatch')
        if int(state.get('slot_count',-1)) != 320: raise ValueError('S1/X4 frozen contract requires slot_count=320')
        directed=base.directed_topologies[s['topology_id']]
        reconstructed=reconstruct_availability(conns[ic]['existing_connections'],directed,320)
        stored={int(x['link_id']):list(x['slot_availability']) for x in state['link_spectrum_states']}
        if reconstructed != stored: raise ValueError(f'{sid}: initial spectrum does not match initial connections')
    return DynamicPublicEnvironmentIndex(base,seqs,conns)


def build_episode_definition(index: DynamicPublicEnvironmentIndex, scenario_id: str, task_type: str, case_id: str, *, k: int|None, pairing_id: str) -> dict:
    if task_type not in {'S1','X4'}: raise ValueError('task_type must be S1 or X4')
    s=index.scenarios[scenario_id]
    if s.get('request_data_type')!='DYNAMIC': raise ValueError('scenario is not DYNAMIC')
    seq=index.dynamic_sequences[s['request_data_id']]; state=index.resource_states[s['resource_state_id']]
    directed=index.directed_topologies[s['topology_id']]; physical=index.physical_topologies[s['topology_id']]
    events=[dict(x) for x in seq['dynamic_request_events']]
    node_ids=sorted(int(x['node_id']) for x in physical['node_records'])
    ep={
        'schema_version':f'{task_type}_DYNAMIC_ROOT_CASE_V1_0','case_id':case_id,'task_type':task_type,'pairing_id':pairing_id,
        'topology_id':s['topology_id'],'resource_state_id':s['resource_state_id'],
        'initial_existing_connection_set_id':s['initial_existing_connection_set_id'],'request_sequence_id':s['request_data_id'],
        'nodes':node_ids,'directed_links':[dict(x) for x in directed['directed_link_records']], 'slot_count':320,
        'initial_link_spectrum_states':[dict(link_id=int(x['link_id']),slot_availability=list(x['slot_availability'])) for x in state['link_spectrum_states']],
        'initial_existing_connections':[dict(x) for x in index.initial_connection_sets[s['initial_existing_connection_set_id']]['existing_connections']],
        'episode_length':len(events),'request_events':events,
        'initial_reference_time':float(state['reference_time']),
        'holding_time_rate_mu':float(seq['holding_time_rate_mu']),
        'difficulty_context':dict(seq.get('generation_context') or {
            'arrival_rate_mode':'LEGACY_ABSOLUTE_UNLINKED',
            'dynamic_arrival_rate_lambda':float(seq['arrival_rate_lambda']),
            'state_arrival_rate_lambda':None,
            'requested_arrival_rate_multiplier':None,
            'lambda_ratio':None,
            'initial_load_band':None,
            'anchor_job_id':None,
        }),
        'source_base_scenario_id':scenario_id,
    }
    if task_type=='S1':
        if k is None: raise ValueError('S1 requires k')
        ep['task_config']={'k':int(k),'request_candidate_paths':{e['request_id']:deterministic_k_paths(directed,e['source_node_id'],e['destination_node_id'],int(k)) for e in events}}
    else:
        ep['task_config']={'reference_k':int(k) if k is not None else 3}
    return ep
