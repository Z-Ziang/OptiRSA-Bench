def assemble_scenarios(ids: dict[str, str]) -> list[dict]:
    topology = ids["topology_id"]
    paired = {"resource_state_id": ids["resource_state_id"],
              "initial_existing_connection_set_id": ids["initial_existing_connection_set_id"]}
    return [
        {"base_scenario_id":"bs_0001","topology_id":topology,"request_data_type":"NONE"},
        {"base_scenario_id":"bs_0002","topology_id":topology,**paired,
         "request_data_type":"SINGLE","request_data_id":ids["single_request_id"]},
        {"base_scenario_id":"bs_0003","topology_id":topology,**paired,
         "request_data_type":"CONCURRENT","request_data_id":ids["concurrent_request_set_id"]},
        {"base_scenario_id":"bs_0004","topology_id":topology,**paired,
         "request_data_type":"DYNAMIC","request_data_id":ids["dynamic_request_sequence_id"]},
    ]
