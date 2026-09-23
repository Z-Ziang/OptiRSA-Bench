from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from src.case_core.allocation_validation import is_assignment_feasible


class FullRsaBudgetExceeded(RuntimeError):
    pass


def link_maps(directed_links: list[dict]) -> tuple[dict[int, dict], dict[int, list[tuple[int,int]]], dict[tuple[int,int], int]]:
    by_id={}
    out={}
    pair={}
    for row in directed_links:
        lid=int(row['link_id']); u=int(row['source_node_id']); v=int(row['destination_node_id'])
        if lid in by_id: raise ValueError(f'duplicate link_id {lid}')
        if (u,v) in pair and pair[(u,v)] != lid: raise ValueError('parallel directed links unsupported')
        by_id[lid]={'link_id':lid,'source_node_id':u,'destination_node_id':v}
        out.setdefault(u,[]).append((v,lid)); out.setdefault(v,[])
        pair[(u,v)]=lid
    for u in out: out[u].sort(key=lambda x:(x[0],x[1]))
    return by_id,out,pair


def spectrum_dict(root_or_rows: dict | list[dict]) -> dict[int,list[int]]:
    rows=root_or_rows['link_spectrum_states'] if isinstance(root_or_rows,dict) else root_or_rows
    return {int(x['link_id']):[int(v) for v in x['slot_availability']] for x in rows}


def feasible_slot_starts(path_link_ids: list[int], required_slots: int, spectrum_by_link: dict[int,list[int]]) -> list[int]:
    if not spectrum_by_link: return []
    slot_count=len(next(iter(spectrum_by_link.values())))
    return [s for s in range(slot_count-int(required_slots)+1) if is_assignment_feasible(path_link_ids,s,int(required_slots),spectrum_by_link)]


def path_from_nodes(nodes: list[int], directed_links: list[dict]) -> dict:
    _,_,pair=link_maps(directed_links)
    links=[]
    for u,v in zip(nodes,nodes[1:]):
        if (int(u),int(v)) not in pair: raise ValueError('node path contains missing directed edge')
        links.append(pair[(int(u),int(v))])
    return {'path_node_ids':[int(x) for x in nodes],'path_link_ids':links,'hop_count':len(links)}


def enumerate_all_simple_paths(source: int, destination: int, directed_links: list[dict], *, max_paths: int) -> list[dict]:
    if max_paths < 1: raise ValueError('max_paths must be positive')
    _,adj,_=link_maps(directed_links)
    source=int(source); destination=int(destination)
    paths=[]; node_path=[source]; link_path=[]; seen={source}
    def dfs(u:int):
        if u==destination:
            paths.append({'path_node_ids':list(node_path),'path_link_ids':list(link_path),'hop_count':len(link_path)})
            if len(paths)>max_paths:
                raise FullRsaBudgetExceeded(f'simple path count exceeds max_paths={max_paths}')
            return
        for v,lid in adj.get(u,[]):
            if v in seen: continue
            seen.add(v); node_path.append(v); link_path.append(lid)
            dfs(v)
            link_path.pop(); node_path.pop(); seen.remove(v)
    dfs(source)
    paths.sort(key=lambda p:(p['hop_count'],tuple(p['path_link_ids']),tuple(p['path_node_ids'])))
    return paths


def enumerate_actions_for_request(request: dict, directed_links: list[dict], spectrum_by_link: dict[int,list[int]], *, max_paths: int) -> tuple[list[dict], int]:
    paths=enumerate_all_simple_paths(int(request['source_node_id']),int(request['destination_node_id']),directed_links,max_paths=max_paths)
    actions=[]; width=int(request['required_slots'])
    for path in paths:
        for start in feasible_slot_starts(path['path_link_ids'],width,spectrum_by_link):
            actions.append({**path,'slot_start':start,'required_slots':width,'delta_tso_contribution':width*path['hop_count']})
    actions.sort(key=lambda a:(a['delta_tso_contribution'],tuple(a['path_link_ids']),a['slot_start']))
    return actions,len(paths)


def enumerate_feasible_actions_for_request(
    request: dict,
    directed_links: list[dict],
    spectrum_by_link: dict[int, list[int]],
    *,
    max_paths: int,
) -> tuple[list[dict], int]:
    """Enumerate only simple paths with at least one feasible spectrum window.

    This is a semantics-preserving exact-oracle optimization.  A path whose
    links do not share any free contiguous window can never produce an RSA
    action, so it may be pruned while the path is being traversed.  The
    returned actions are the same as ``enumerate_actions_for_request``; the
    returned path count is the count of feasible paths explored by this
    pruned traversal and is intended for diagnostics only.
    """
    if max_paths < 1:
        raise ValueError('max_paths must be positive')
    if not spectrum_by_link:
        return [], 0
    width = int(request['required_slots'])
    slot_count = len(next(iter(spectrum_by_link.values())))
    if width < 1 or width > slot_count:
        return [], 0
    window_count = slot_count - width + 1
    _, adjacency, _ = link_maps(directed_links)
    link_window_masks: dict[int, int] = {}
    for link_id, values in spectrum_by_link.items():
        if len(values) != slot_count:
            raise ValueError('spectrum rows have inconsistent slot counts')
        mask = 0
        for start in range(window_count):
            if all(int(value) == 1 for value in values[start:start + width]):
                mask |= 1 << start
        link_window_masks[int(link_id)] = mask

    # For each possible slot start, compute which nodes can still reach the
    # destination through links that are free in that window.  Intersecting
    # this mask during DFS avoids exploring dead branches when no feasible
    # end-to-end path exists, while retaining every feasible action.
    reverse: dict[int, list[tuple[int, int]]] = {}
    for node, edges in adjacency.items():
        reverse.setdefault(node, [])
        for next_node, link_id in edges:
            reverse.setdefault(next_node, []).append((node, int(link_id)))
    for node in reverse:
        reverse[node].sort()
    destination = int(request['destination_node_id'])
    reachable_windows: dict[int, int] = {node: 0 for node in adjacency}
    for start in range(window_count):
        stack = [destination]
        seen = {destination}
        while stack:
            node = stack.pop()
            reachable_windows[node] = reachable_windows.get(node, 0) | (1 << start)
            for predecessor, link_id in reverse.get(node, []):
                if not ((link_window_masks.get(link_id, 0) >> start) & 1):
                    continue
                if predecessor not in seen:
                    seen.add(predecessor)
                    stack.append(predecessor)

    source = int(request['source_node_id'])
    node_path = [source]
    link_path: list[int] = []
    seen = {source}
    actions: list[dict] = []
    feasible_path_count = 0

    def dfs(node: int, common_windows: int) -> None:
        nonlocal feasible_path_count
        if node == destination:
            feasible_path_count += 1
            if feasible_path_count > max_paths:
                raise FullRsaBudgetExceeded(
                    f'feasible simple path count exceeds max_paths={max_paths}'
                )
            for start in range(window_count):
                if (common_windows >> start) & 1:
                    actions.append({
                        'path_node_ids': list(node_path),
                        'path_link_ids': list(link_path),
                        'hop_count': len(link_path),
                        'slot_start': start,
                        'required_slots': width,
                        'delta_tso_contribution': width * len(link_path),
                    })
            return
        for next_node, link_id in adjacency.get(node, []):
            if next_node in seen:
                continue
            next_windows = common_windows & link_window_masks.get(int(link_id), 0)
            if not next_windows:
                continue
            seen.add(next_node)
            node_path.append(next_node)
            link_path.append(int(link_id))
            dfs(next_node, next_windows)
            link_path.pop()
            node_path.pop()
            seen.remove(next_node)

    dfs(source, ((1 << window_count) - 1) & reachable_windows.get(source, 0))
    actions.sort(key=lambda action: (
        action['delta_tso_contribution'],
        tuple(action['path_link_ids']),
        action['slot_start'],
    ))
    return actions, feasible_path_count


def allowed_links_for_window(directed_links: list[dict], spectrum_by_link: dict[int,list[int]], start:int, width:int) -> list[dict]:
    out=[]
    for row in directed_links:
        lid=int(row['link_id']); vals=spectrum_by_link[lid]
        if start>=0 and start+width<=len(vals) and all(vals[i]==1 for i in range(start,start+width)):
            out.append(row)
    return out


def shortest_hop_distance(source:int,destination:int,directed_links:list[dict]) -> int | None:
    _,adj,_=link_maps(directed_links)
    q=deque([(int(source),0)]); seen={int(source)}
    while q:
        u,d=q.popleft()
        if u==int(destination): return d
        for v,_ in adj.get(u,[]):
            if v not in seen:
                seen.add(v); q.append((v,d+1))
    return None


def deterministic_shortest_path(source:int,destination:int,directed_links:list[dict]) -> dict | None:
    _,adj,_=link_maps(directed_links)
    source=int(source); destination=int(destination)
    dist={source:0}; q=deque([source])
    while q:
        u=q.popleft()
        for v,_ in adj.get(u,[]):
            if v not in dist:
                dist[v]=dist[u]+1; q.append(v)
    if destination not in dist: return None
    target=dist[destination]
    candidates=[]; np=[source]; lp=[]; seen={source}
    def dfs(u:int):
        if len(lp)>target: return
        if u==destination:
            if len(lp)==target: candidates.append((tuple(lp),tuple(np)))
            return
        for v,lid in adj.get(u,[]):
            if v in seen: continue
            if dist.get(v,10**9)>len(lp)+1: continue
            seen.add(v); np.append(v); lp.append(lid); dfs(v); lp.pop(); np.pop(); seen.remove(v)
    dfs(source)
    if not candidates: return None
    links,nodes=min(candidates)
    return {'path_node_ids':list(nodes),'path_link_ids':list(links),'hop_count':len(links)}


def enumerate_exact_hop_paths(source:int,destination:int,directed_links:list[dict],hop_count:int,*,max_paths:int) -> list[dict]:
    _,adj,_=link_maps(directed_links); source=int(source); destination=int(destination)
    rev={}
    for u,edges in adj.items():
        rev.setdefault(u,[])
        for v,_ in edges: rev.setdefault(v,[]).append(u)
    for v in rev: rev[v].sort()
    rdist={destination:0}; q=deque([destination])
    while q:
        v=q.popleft()
        for u in rev.get(v,[]):
            if u not in rdist: rdist[u]=rdist[v]+1; q.append(u)
    out=[]; np=[source]; lp=[]; seen={source}
    def dfs(u:int):
        remaining=hop_count-len(lp)
        if rdist.get(u,10**9)>remaining: return
        if len(lp)==hop_count:
            if u==destination:
                out.append({'path_node_ids':list(np),'path_link_ids':list(lp),'hop_count':hop_count})
                if len(out)>max_paths: raise FullRsaBudgetExceeded(f'optimal-hop path count exceeds max_paths={max_paths}')
            return
        for v,lid in adj.get(u,[]):
            if v in seen: continue
            if rdist.get(v,10**9)>remaining-1: continue
            seen.add(v); np.append(v); lp.append(lid); dfs(v); lp.pop(); np.pop(); seen.remove(v)
    dfs(source)
    out.sort(key=lambda p:(tuple(p['path_link_ids']),tuple(p['path_node_ids'])))
    return out


def action_masks(action:dict) -> dict[int,int]:
    width=int(action['required_slots']); start=int(action['slot_start']); mask=((1<<width)-1)<<start
    return {int(lid):mask for lid in action['path_link_ids']}


def masks_conflict(existing:dict[int,int], action:dict) -> bool:
    return any(existing.get(lid,0)&mask for lid,mask in action_masks(action).items())


def add_masks(existing:dict[int,int], action:dict) -> list[tuple[int,int]]:
    changed=[]
    for lid,mask in action_masks(action).items():
        old=existing.get(lid,0); changed.append((lid,old)); existing[lid]=old|mask
    return changed


def restore_masks(existing:dict[int,int], changed:list[tuple[int,int]]) -> None:
    for lid,old in changed:
        if old: existing[lid]=old
        else: existing.pop(lid,None)
