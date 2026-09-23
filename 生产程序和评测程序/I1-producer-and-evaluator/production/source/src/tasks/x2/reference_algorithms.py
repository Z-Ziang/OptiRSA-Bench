from __future__ import annotations

import networkx as nx

from src.case_core.full_rsa import allowed_links_for_window, deterministic_shortest_path, feasible_slot_starts, path_from_nodes
from src.case_core.search import _ExactWufrScorer
from src.case_core.wufr import build_reference_paths


def _graph(nodes,links):
    g=nx.DiGraph(); g.add_nodes_from(sorted(int(x) for x in nodes))
    for r in sorted(links,key=lambda x:int(x['link_id'])): g.add_edge(int(r['source_node_id']),int(r['destination_node_id']))
    return g

def _k_shortest(source,dest,nodes,links,k):
    g=_graph(nodes,links)
    try: gen=nx.shortest_simple_paths(g,int(source),int(dest))
    except nx.NetworkXNoPath: return []
    out=[]
    try:
        for _ in range(k): out.append(path_from_nodes(next(gen),links))
    except (StopIteration,nx.NetworkXNoPath): pass
    out.sort(key=lambda p:(p['hop_count'],tuple(p['path_link_ids']),tuple(p['path_node_ids'])))
    return out[:k]

def _score_candidates(candidates,root):
    if not candidates: return None
    sp={int(x['link_id']):list(x['slot_availability']) for x in root['link_spectrum_states']}
    q={int(k):float(v) for k,v in root['required_slots_probabilities'].items()}; refs=build_reference_paths(root['nodes'],root['directed_links']); scorer=_ExactWufrScorer(sp,q,refs)
    width=int(root['request']['required_slots']); best=None
    for c in candidates:
        w=scorer.score([{'path_link_ids':c['path_link_ids'],'slot_start':c['slot_start'],'required_slots':width}])
        key=(len(c['path_link_ids']),w,tuple(c['path_link_ids']),tuple(c['path_node_ids']),c['slot_start'])
        if best is None or key<best[0]: best=(key,c,w)
    return {'decision':'ACCEPT','path_node_ids':best[1]['path_node_ids'],'path_link_ids':best[1]['path_link_ids'],'slot_start':best[1]['slot_start'],'hop_count':len(best[1]['path_link_ids']),'post_wufr':float(best[2])}

def run_x2_reference_algorithms(root:dict)->dict:
    req=root['request']; sp={int(x['link_id']):list(x['slot_availability']) for x in root['link_spectrum_states']}; width=int(req['required_slots'])
    shortest=deterministic_shortest_path(req['source_node_id'],req['destination_node_id'],root['directed_links'])
    a1=None
    if shortest:
        starts=feasible_slot_starts(shortest['path_link_ids'],width,sp)
        if starts:
            a1=_score_candidates([{**shortest,'slot_start':starts[0]}],root)
    paths5=_k_shortest(req['source_node_id'],req['destination_node_id'],root['nodes'],root['directed_links'],5)
    c2=[]
    for p in paths5:
        for s in feasible_slot_starts(p['path_link_ids'],width,sp): c2.append({**p,'slot_start':s})
    a2=_score_candidates(c2,root)
    c3=list(c2); slot_count=int(root['slot_count'])
    for s in range(slot_count-width+1):
        allowed=allowed_links_for_window(root['directed_links'],sp,s,width)
        p=deterministic_shortest_path(req['source_node_id'],req['destination_node_id'],allowed)
        if p: c3.append({**p,'slot_start':s})
    a3=_score_candidates(c3,root)
    return {'algorithm_1_sp_ff':a1,'algorithm_2_ksp5_lex':a2,'algorithm_3_window_search_lex':a3}
