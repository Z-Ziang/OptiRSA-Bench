"""Native Inspect Task: only system/user public texts are sent to the model."""
from inspect_ai import Task,task
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageSystem,ChatMessageUser,ModelOutput
from inspect_ai.scorer import Score,scorer
from inspect_ai.solver import generate,solver
from benchlib import public_messages,resolve_case,readjson,safe_classify

@scorer(metrics=[])
def frozen_score():
    async def score(state,target):
        row=state.metadata['case_record'];content=state.output.completion
        result=safe_classify(row,content,True);strict=safe_classify(row,content,False)
        return Score(value=1 if result['category']=='CORRECT' else 0,answer=result['category'],metadata={'result':result,'strict':strict})
    return score

@solver
def reference_replay():
    async def solve(state,generate):
        import json
        row=state.metadata['case_record'];out=readjson(resolve_case(row['case_dir'])/'private/evaluation_reference_output.json')
        state.output=ModelOutput.from_content(model='offline/reference_replay',content=json.dumps(out))
        return state
    return solve

@task
def gx1_cases(rows,offline_reference=False):
    samples=[]
    for row in rows:
        messages=public_messages(row)
        public_row={k:row[k] for k in ('case_uid','task','case_dir','topology_id','topology_folder','scale','messages_sha256','interface_status')}
        inp=[(ChatMessageSystem if m['role']=='system' else ChatMessageUser)(content=m['content']) for m in messages]
        samples.append(Sample(id=row['case_uid'],input=inp,target='',metadata={'case_record':public_row}))
    return Task(dataset=samples,solver=reference_replay() if offline_reference else generate(),scorer=frozen_score(),version='GX1_563_V31_INSPECT_V1')
