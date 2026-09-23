from src.case_core.x_intent import render_x2_intent, render_x3_intent


def test_intent_renderers_carry_semantics_in_natural_language():
    x2=render_x2_intent({'request_id':'r1','source_node_id':3,'destination_node_id':50,'required_slots':9})
    assert '3' in x2 and '50' in x2 and '9' in x2
    requests=[
        {'request_id':'req_001','source_node_id':0,'destination_node_id':2,'required_slots':2},
        {'request_id':'req_002','source_node_id':2,'destination_node_id':1,'required_slots':5},
    ]
    x3=render_x3_intent(requests)
    assert 'req_001' in x3 and 'req_002' in x3 and '同时' in x3
