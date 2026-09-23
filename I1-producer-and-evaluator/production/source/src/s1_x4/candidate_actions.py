from __future__ import annotations
from collections import defaultdict
import networkx as nx
from src.case_core.allocation_validation import is_assignment_feasible


def compress_slot_starts(starts: list[int]) -> list[tuple[int, int]]:
    vals = sorted(set(int(x) for x in starts))
    if not vals:
        return []
    out=[]; a=b=vals[0]
    for x in vals[1:]:
        if x == b + 1:
            b=x
        else:
            out.append((a,b)); a=b=x
    out.append((a,b))
    return out


def expand_slot_ranges(ranges: list[tuple[int,int]]) -> list[int]:
    out=[]
    for a,b in ranges:
        a=int(a); b=int(b)
        if b<a: raise ValueError("invalid slot range")
        out.extend(range(a,b+1))
    return out


def deterministic_k_paths(directed_topology: dict, source_node_id: int, destination_node_id: int, k: int) -> list[dict]:
    if not isinstance(k,int) or isinstance(k,bool) or k < 1:
        raise ValueError("k must be a positive integer")
    records = directed_topology.get("directed_link_records", directed_topology.get("directed_links", []))
    links={(int(r['source_node_id']),int(r['destination_node_id'])):int(r['link_id']) for r in records}
    graph=nx.DiGraph(); graph.add_edges_from(links)
    try:
        raw=[]
        # shortest_simple_paths yields nondecreasing length; collect all paths through
        # the kth hop-count frontier before applying explicit deterministic ordering.
        gen=nx.shortest_simple_paths(graph,int(source_node_id),int(destination_node_id))
        kth_hops=None
        for nodes in gen:
            lids=[links[(u,v)] for u,v in zip(nodes,nodes[1:])]
            hops=len(lids)
            if kth_hops is not None and hops>kth_hops:
                break
            raw.append((hops,tuple(lids),tuple(int(x) for x in nodes)))
            if len(raw)>=k and kth_hops is None:
                kth_hops=hops
    except (nx.NetworkXNoPath,nx.NodeNotFound):
        raw=[]
    raw.sort(key=lambda x:(x[0],x[1],x[2]))
    out=[]
    for rank,(_,lids,nodes) in enumerate(raw[:k],1):
        out.append({'path_rank':rank,'path_node_ids':list(nodes),'path_link_ids':list(lids)})
    return out


def enumerate_feasible_actions(paths: list[dict], spectrum_by_link: dict[int,list[int]], required_slots: int) -> list[dict]:
    if not spectrum_by_link: return []
    slot_count=len(next(iter(spectrum_by_link.values())))
    out=[]
    for p in sorted(paths,key=lambda x:int(x['path_rank'])):
        for start in range(slot_count-int(required_slots)+1):
            if is_assignment_feasible(list(p['path_link_ids']),start,int(required_slots),spectrum_by_link):
                out.append({'path_rank':int(p['path_rank']),'slot_start':start,
                            'path_node_ids':list(p['path_node_ids']),'path_link_ids':list(p['path_link_ids'])})
    return out


def actions_by_path(paths: list[dict], actions: list[dict]) -> list[dict]:
    starts=defaultdict(list)
    for a in actions: starts[int(a['path_rank'])].append(int(a['slot_start']))
    out=[]
    for p in sorted(paths,key=lambda x:int(x['path_rank'])):
        rank=int(p['path_rank'])
        if rank not in starts: continue
        out.append({**p,'slot_start_ranges':compress_slot_starts(starts[rank])})
    return out
