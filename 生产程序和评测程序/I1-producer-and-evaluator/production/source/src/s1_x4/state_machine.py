from __future__ import annotations
from copy import deepcopy
from src.s1_x4.candidate_actions import enumerate_feasible_actions
from src.s1_x4.efm import network_efm

def network_utilization(spectrum_by_link: dict[int, list[int]]) -> float | None:
    total=sum(len(bits) for bits in spectrum_by_link.values())
    if total == 0:
        return None
    occupied=sum(1-int(v) for bits in spectrum_by_link.values() for v in bits)
    return occupied/total



class DynamicEpisodeState:
    def __init__(self, episode: dict):
        self.episode=deepcopy(episode); self.index=0; self.current_time=None; self._prepared=None
        self.spectrum_by_link={int(x['link_id']):list(x['slot_availability']) for x in episode['initial_link_spectrum_states']}
        self.active=[dict(x, release_time=float(x['arrival_time'])+float(x['holding_time'])) for x in episode['initial_existing_connections']]
        self.trajectory=[]

    @property
    def finished(self): return self.index>=int(self.episode['episode_length'])

    def _release_due(self, now: float) -> int:
        keep=[]; released=[]
        for c in self.active:
            if float(c['release_time']) <= now: released.append(c)
            else: keep.append(c)
        for c in released:
            for lid in c['path_link_ids']:
                for s in range(int(c['slot_start']),int(c['slot_start'])+int(c['required_slots'])):
                    if self.spectrum_by_link[int(lid)][s] != 0:
                        raise RuntimeError('release ledger/state inconsistency')
                    self.spectrum_by_link[int(lid)][s]=1
        self.active=keep
        return len(released)

    def prepare_current_step(self) -> dict:
        if self.finished: raise RuntimeError('episode finished')
        if self._prepared is not None: return self._prepared
        req=dict(self.episode['request_events'][self.index]); now=float(req['arrival_time'])
        released=self._release_due(now); self.current_time=now
        ctx={
            'case_id':self.episode['case_id'],'task_type':self.episode['task_type'],'step_index_internal':self.index+1,
            'request':req,'current_time':now,'released_connection_count_before_decision':released,
            'nodes':list(self.episode['nodes']),'directed_links':deepcopy(self.episode['directed_links']),
            'slot_count':int(self.episode['slot_count']),'spectrum_by_link':deepcopy(self.spectrum_by_link),
            'active_connection_count_before_decision':len(self.active),
            'pre_decision_network_utilization':network_utilization(self.spectrum_by_link),
        }
        if self.episode['task_type']=='S1':
            paths=deepcopy(self.episode['task_config']['request_candidate_paths'][req['request_id']])
            ctx['candidate_paths']=paths
            ctx['candidate_actions']=enumerate_feasible_actions(paths,ctx['spectrum_by_link'],int(req['required_slots']))
        self._prepared=ctx
        return ctx

    def commit_step(self, validation_result: dict) -> dict:
        ctx=self.prepare_current_step(); valid=bool(validation_result.get('valid'))
        established=valid and validation_result.get('decision')=='ACCEPT'
        path_link_ids=list(validation_result.get('path_link_ids') or [])
        slot_start=validation_result.get('slot_start')
        req=ctx['request']
        if established:
            for lid in path_link_ids:
                for s in range(int(slot_start),int(slot_start)+int(req['required_slots'])):
                    if self.spectrum_by_link[int(lid)][s] != 1: raise RuntimeError('validated allocation no longer feasible')
                    self.spectrum_by_link[int(lid)][s]=0
            self.active.append({
                'connection_id':f"dut_{self.episode['case_id']}_{self.index+1:06d}",
                'source_node_id':int(req['source_node_id']),'destination_node_id':int(req['destination_node_id']),
                'path_link_ids':path_link_ids,'slot_start':int(slot_start),'required_slots':int(req['required_slots']),
                'arrival_time':float(req['arrival_time']),'holding_time':float(req['holding_time']),
                'release_time':float(req['arrival_time'])+float(req['holding_time'])})
        efm=network_efm(self.spectrum_by_link)
        record={
            'step_index':self.index+1,'request_id':req['request_id'],'current_time':ctx['current_time'],
            'decision':validation_result.get('decision'),'established':bool(established),'blocked':not bool(established),
            'validation_error':validation_result.get('error'),'released_connection_count_before_decision':ctx['released_connection_count_before_decision'],
            'active_connection_count_before_decision':ctx['active_connection_count_before_decision'],
            'active_connection_count_after_decision':len(self.active),
            'pre_decision_network_utilization':ctx['pre_decision_network_utilization'],
            'post_decision_network_utilization':network_utilization(self.spectrum_by_link),
            'post_decision_network_efm':efm['network_efm'],'efm_defined_link_count':efm['efm_defined_link_count'],
        }
        if self.episode['task_type']=='S1':
            record['candidate_action_count']=len(ctx.get('candidate_actions',[]))
        for key in ('path_rank','path_node_ids','path_link_ids','slot_start'):
            if key in validation_result: record[key]=validation_result[key]
        self.trajectory.append(record); self.index+=1; self._prepared=None
        return record
