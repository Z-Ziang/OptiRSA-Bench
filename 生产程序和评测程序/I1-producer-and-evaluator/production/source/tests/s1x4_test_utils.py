from __future__ import annotations
from pathlib import Path
import json


def minimal_dynamic_environment(root: Path, *, slot_count: int = 320, length: int = 4) -> Path:
    env = root / 'public_environment'
    for rel in [
        'topologies/physical','topologies/directed','states/spectrum','connections/initial',
        'requests/single','requests/derivation','requests/concurrent','requests/dynamic','scenarios','configs'
    ]:
        (env / rel).mkdir(parents=True, exist_ok=True)
    physical = {
        'topology_id':'top_demo',
        'node_records':[{'node_id':i} for i in range(4)],
        'physical_link_records':[
            {'physical_link_id':0,'node_u_id':0,'node_v_id':1},
            {'physical_link_id':1,'node_u_id':1,'node_v_id':3},
            {'physical_link_id':2,'node_u_id':0,'node_v_id':2},
            {'physical_link_id':3,'node_u_id':2,'node_v_id':3},
            {'physical_link_id':4,'node_u_id':1,'node_v_id':2},
        ],
    }
    directed_records=[]
    lid=0
    for p in physical['physical_link_records']:
        for u,v in ((p['node_u_id'],p['node_v_id']),(p['node_v_id'],p['node_u_id'])):
            directed_records.append({'link_id':lid,'source_node_id':u,'destination_node_id':v,'physical_link_id':p['physical_link_id']}); lid+=1
    directed={'topology_id':'top_demo','directed_link_records':directed_records}
    icset={
        'initial_existing_connection_set_id':'icset_demo','topology_id':'top_demo','reference_time':0.0,
        'existing_connections':[
            {'connection_id':'conn_seed','source_node_id':0,'destination_node_id':3,
             'path_link_ids':[0,2],'slot_start':0,'required_slots':2,'arrival_time':-1.0,'holding_time':2.0}
        ]
    }
    states=[]
    for r in directed_records:
        bits=[1]*slot_count
        if r['link_id'] in {0,2}:
            bits[0]=bits[1]=0
        states.append({'link_id':r['link_id'],'slot_availability':bits})
    state={'resource_state_id':'rs_demo','topology_id':'top_demo','reference_time':0.0,'slot_count':slot_count,
           'initial_existing_connection_set_id':'icset_demo','link_spectrum_states':states,'spectrum_state_metrics':{}}
    events=[]
    for i in range(length):
        events.append({'request_id':f'dynreq_demo_{i+1:06d}','source_node_id':0,'destination_node_id':3,
                       'required_slots':[2,3,5,9][i%4],'arrival_time':1.5+i*2.0,'holding_time':3.0+i*0.1})
    sequence={'request_sequence_id':'seq_demo','dynamic_request_events':events,'arrival_rate_lambda':0.5,'holding_time_rate_mu':1/15}
    scenario={'base_scenario_id':'bs_dynamic_demo','topology_id':'top_demo','resource_state_id':'rs_demo',
              'initial_existing_connection_set_id':'icset_demo','request_data_type':'DYNAMIC','request_data_id':'seq_demo'}
    def w(path,obj): path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    w(env/'topologies/physical/top_demo.json',physical); w(env/'topologies/directed/top_demo.json',directed)
    w(env/'states/spectrum/rs_demo.json',state); w(env/'connections/initial/icset_demo.json',icset)
    w(env/'requests/dynamic/seq_demo.json',sequence); w(env/'scenarios/bs_dynamic_demo.json',scenario)
    return env
