from pathlib import Path
import pytest
from tests.s1x4_test_utils import minimal_dynamic_environment


def test_efm_formula_and_null_edge():
    from src.s1_x4.efm import link_efm, network_efm
    assert link_efm([1,1,1,1]) == 0.0
    assert link_efm([1,1,0,1]) == pytest.approx(1-2/3)
    assert link_efm([0,0,0,0]) is None
    m=network_efm({0:[1,1,0,1],1:[0,0,0,0],2:[1,1,1,1]})
    assert m['efm_defined_link_count']==2
    assert m['network_efm']==pytest.approx((1-2/3)/2)


def test_interval_codec_roundtrip():
    from src.s1_x4.candidate_actions import compress_slot_starts, expand_slot_ranges
    starts=[1,2,3,8,9,10,11,25]
    ranges=compress_slot_starts(starts)
    assert ranges==[(1,3),(8,11),(25,25)]
    assert expand_slot_ranges(ranges)==starts


def test_deterministic_k_paths_and_exhaustive_actions():
    from src.s1_x4.candidate_actions import deterministic_k_paths, enumerate_feasible_actions
    directed={'directed_link_records':[
        {'link_id':0,'source_node_id':0,'destination_node_id':1}, {'link_id':1,'source_node_id':1,'destination_node_id':3},
        {'link_id':2,'source_node_id':0,'destination_node_id':2}, {'link_id':3,'source_node_id':2,'destination_node_id':3},
    ]}
    paths=deterministic_k_paths(directed,0,3,2)
    assert [p['path_link_ids'] for p in paths]==[[0,1],[2,3]]
    spectrum={i:[1,1,1,1] for i in range(4)}
    spectrum[0][1]=0
    actions=enumerate_feasible_actions(paths,spectrum,2)
    got=[(a['path_rank'],a['slot_start']) for a in actions]
    assert got==[(1,2),(2,0),(2,1),(2,2)]


def test_dynamic_loader_requires_strict_arrival_order(tmp_path: Path):
    from src.s1_x4.scenario_loader import load_dynamic_public_environment
    env=minimal_dynamic_environment(tmp_path,length=3)
    idx=load_dynamic_public_environment(env)
    assert len(idx.dynamic_sequences)==1
    p=env/'requests/dynamic/seq_demo.json'
    import json
    obj=json.loads(p.read_text(encoding='utf-8')); obj['dynamic_request_events'][1]['arrival_time']=obj['dynamic_request_events'][0]['arrival_time']
    p.write_text(json.dumps(obj),encoding='utf-8')
    with pytest.raises(ValueError,match='strictly increasing'):
        load_dynamic_public_environment(env)
