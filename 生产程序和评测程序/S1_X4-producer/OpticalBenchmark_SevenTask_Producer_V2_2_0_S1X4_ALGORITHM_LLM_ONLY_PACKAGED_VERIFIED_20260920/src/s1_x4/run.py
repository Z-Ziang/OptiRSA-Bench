from __future__ import annotations
import hashlib,json
from pathlib import Path
from src.s1_x4.evaluator import DynamicEpisodeSession
from src.s1_x4.serialization import compute_dynamic_serialization_metrics


def _write(path,obj): path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def _sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def run_episode_with_dut(episode: dict, endpoint: str, dut_callable, output_dir: Path|str|None=None) -> dict:
    session=DynamicEpisodeSession(episode,endpoint=endpoint); prompts=[]
    while not session.finished:
        step=session.current_step(); prompts.append(step['prompt']); response=dut_callable(step); session.submit_response(response)
    summary=session.summary(); ser=compute_dynamic_serialization_metrics(prompts); result={'summary':summary,'trajectory':session.state.trajectory,'serialization_metrics':ser}
    if output_dir is not None:
        out=Path(output_dir).resolve(); out.mkdir(parents=True,exist_ok=True)
        (out/'trajectory.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False,sort_keys=True)+'\n' for x in result['trajectory']),encoding='utf-8')
        _write(out/'episode_metrics.json',summary); _write(out/'serialization_metrics.json',ser)
        _write(out/'validation_summary.json',{'case_id':episode['case_id'],'task_type':episode['task_type'],'step_count':summary['step_count'],'completed':True})
        files=sorted(x for x in out.rglob('*') if x.is_file() and x.name!='SHA256SUMS.txt'); (out/'SHA256SUMS.txt').write_text(''.join(f'{_sha(p)}  {p.relative_to(out).as_posix()}\n' for p in files),encoding='utf-8')
    return result
