from __future__ import annotations
import json
from statistics import fmean
from src.s1_x4.state_machine import DynamicEpisodeState
from src.s1_x4.validators import validate_s1_response, validate_x4_response
from src.s1_x4.renderer import render_s1_step, render_x4_step

class DynamicEpisodeSession:
    def __init__(self, episode: dict, *, endpoint: str='llm'):
        if endpoint != 'llm': raise ValueError('endpoint must be llm')
        self.episode=episode; self.endpoint=endpoint; self.state=DynamicEpisodeState(episode); self._generation=0; self._current=None; self._current_context=None
    @property
    def finished(self): return self.state.finished
    def _get_generation(self): return self._generation
    def current_step(self) -> dict:
        if self.finished: raise RuntimeError('episode finished')
        if self._current is not None: return self._current
        ctx=self.state.prepare_current_step(); task=self.episode['task_type']
        prompt=render_s1_step(self.episode,ctx,self.endpoint) if task=='S1' else render_x4_step(self.episode,ctx,self.endpoint)
        item={'case_id':f"{self.episode['case_id']}__step_{ctx['step_index_internal']:06d}",'prompt':prompt}
        self._current_context=ctx; self._current=item; return item
    def submit_response(self, response) -> dict:
        self.current_step(); ctx=self._current_context; task=self.episode['task_type']
        if isinstance(response,str):
            try: response=json.loads(response)
            except Exception as exc:
                validation={'valid':False,'decision':None,'error':f'invalid JSON: {exc}'}
            else:
                validation=validate_s1_response(response,ctx) if task=='S1' else validate_x4_response(response,ctx)
        else:
            validation=validate_s1_response(response,ctx) if task=='S1' else validate_x4_response(response,ctx)
        record=self.state.commit_step(validation); self._generation+=1; self._current=None; self._current_context=None
        return {'validation':validation,'trajectory_record':record,'finished':self.finished}
    def summary(self) -> dict:
        if not self.finished: raise RuntimeError('episode not finished')
        tr=self.state.trajectory; h=len(tr); blocked=sum(bool(x['blocked']) for x in tr); established=h-blocked
        vals=[x['post_decision_network_efm'] for x in tr if x['post_decision_network_efm'] is not None]
        return {
            'case_id':self.episode['case_id'],'task_type':self.episode['task_type'],'step_count':h,
            'established_count':established,'blocked_count':blocked,'submitted_reject_count':sum(x.get('decision')=='REJECT' for x in tr),
            'invalid_allocation_count':sum((x.get('decision')=='ACCEPT' and x.get('validation_error') is not None) for x in tr),
            'format_error_count':sum(x.get('decision') is None for x in tr),'rbr':blocked/h if h else None,
            'network_efm_defined_step_count':len(vals),'network_efm_series':[x['post_decision_network_efm'] for x in tr],
            'mean_network_efm':fmean(vals) if vals else None,'final_network_efm':tr[-1]['post_decision_network_efm'] if tr else None,
        }
