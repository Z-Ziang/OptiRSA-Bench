from pathlib import Path
from src.case_core.scenario_loader import PublicEnvironmentIndex


def toy_env(*, slot_count=4, occupied0=None):
    occupied0=set(occupied0 or [])
    physical={'topology_id':'top_toy','node_records':[{'node_id':0},{'node_id':1}], 'physical_link_records':[{'physical_link_id':0,'node_u_id':0,'node_v_id':1}]}
    directed={'topology_id':'top_toy','directed_link_records':[
      {'link_id':0,'source_node_id':0,'destination_node_id':1,'physical_link_id':0},
      {'link_id':1,'source_node_id':1,'destination_node_id':0,'physical_link_id':0},
    ]}
    state={'resource_state_id':'rs_toy','topology_id':'top_toy','reference_time':0.0,'slot_count':slot_count,'initial_existing_connection_set_id':'ic_toy',
      'link_spectrum_states':[
        {'link_id':0,'slot_availability':[0 if i in occupied0 else 1 for i in range(slot_count)]},
        {'link_id':1,'slot_availability':[1]*slot_count},
      ],
      'spectrum_state_metrics':{'network_spectrum_utilization':len(occupied0)/(2*slot_count),'max_link_utilization':len(occupied0)/slot_count,'p90_link_utilization':len(occupied0)/slot_count,'link_utilization_variance':0.0,'link_spectrum_metrics':[
        {'link_id':0,'link_utilization':len(occupied0)/slot_count,'free_slot_count':slot_count-len(occupied0),'free_block_count':1,'largest_free_block_length':slot_count-len(occupied0)},
        {'link_id':1,'link_utilization':0.0,'free_slot_count':slot_count,'free_block_count':1,'largest_free_block_length':slot_count},
      ]}}
    requests={
      'r1':{'request_id':'r1','topology_id':'top_toy','source_node_id':0,'destination_node_id':1,'required_slots':2},
      'r2':{'request_id':'r2','topology_id':'top_toy','source_node_id':0,'destination_node_id':1,'required_slots':2},
    }
    derivations={rid:{'request_id':rid,'resource_state_id':'rs_toy','shortest_path_hops':1,'local_edge_connectivity':1,'candidate_path_k':1,'candidate_paths':[
      {'rank':1,'path_link_ids':[0],'common_free_block_count':1,'largest_common_free_block_length':slot_count,'feasible_slot_starts':list(range(max(0,slot_count-1)))}
    ],'feasible_candidate_path_count':1,'feasible_action_count':max(0,slot_count-1)} for rid in requests}
    concurrent={'set2':{'request_set_id':'set2','resource_state_id':'rs_toy','request_ids':['r1','r2'],'joint_feasibility_status':'FEASIBLE'}}
    configs={'gen_req':{'generation_config_id':'gen_req','production_stage':'REQUEST','topology_id':'top_toy','parameter_values':{'resource_state_id':'rs_toy'},'payload_slot_values':[1,2,4,8],'payload_slot_probabilities':[1.0,0.0,0.0,0.0],'guard_band_slots':1}}
    return PublicEnvironmentIndex(Path('.'),{'top_toy':physical},{'top_toy':directed},{'rs_toy':state},requests,derivations,concurrent,{},configs)
