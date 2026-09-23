from __future__ import annotations
from src.s1_x4.candidate_actions import actions_by_path


def _arr(v): return '['+','.join(str(int(x)) for x in v)+']'
def _fmt_num(x):
    if isinstance(x,int): return str(x)
    return format(float(x),'.12g')

def _free_ranges(bits):
    out=[]; a=None
    for i,b in enumerate(list(bits)+[0]):
        if b==1 and a is None: a=i
        elif b==0 and a is not None: out.append((a,i-1)); a=None
    return out

def _network(ctx, prefix='2. 当前网络有向链路及频谱资源状态：'):
    nodes=sorted(ctx['nodes']); lines=[f'{prefix}网络节点编号范围：{nodes[0]}～{nodes[-1]}，共{len(nodes)}个节点。']
    lm={int(x['link_id']):x for x in ctx['directed_links']}
    for lid in sorted(lm):
        r=lm[lid]; ranges=_free_ranges(ctx['spectrum_by_link'][lid]); s=','.join(f'[{a},{b}]' for a,b in ranges) if ranges else '无'
        lines.append(f"有向链路{lid}：{int(r['source_node_id'])}→{int(r['destination_node_id'])}；空闲槽位区间：{s}。")
    return '\n'.join(lines)

def _s1_req(req):
    return f"1. 当前业务请求：当前时刻为{_fmt_num(req['arrival_time'])}，请你为业务请求{req['request_id']}，建立一项从节点 {int(req['source_node_id'])} 到节点 {int(req['destination_node_id'])} 的业务连接，该请求需要连续使用 {int(req['required_slots'])} 个频谱槽位，业务连接持续时长为{_fmt_num(req['holding_time'])}。"

def _s1_actions(ctx,section):
    grouped=actions_by_path(ctx['candidate_paths'],ctx['candidate_actions'])
    lines=[section]
    if not grouped:
        lines.append('当前请求在规定的 K 条候选路径范围内不存在可行资源分配动作。')
    else:
        for p in grouped:
            rs=','.join(f'[{a},{b}]' for a,b in p['slot_start_ranges'])
            lines.append(f"候选路径{p['path_rank']}：path_rank={p['path_rank']}；路径节点数组：{_arr(p['path_node_ids'])}；有向链路数组：{_arr(p['path_link_ids'])}；可行频谱起始槽位：slot_start∈{rs}。")
        lines.append('以上列出的全部 (path_rank, slot_start) 组合均为当前网络状态下可行的资源分配动作。')
    return '\n'.join(lines)

def render_s1_step(episode,context,endpoint):
    if endpoint!='llm':
        raise ValueError('endpoint must be llm')
    tail='你的任务是根据当前网络资源状态，从上述可行动作中选择一个资源分配方案来完成业务请求的建立，并考虑本次资源分配对后续业务请求的长期影响，首要目标是在整个动态决策序列中尽量减少被阻塞的业务请求，即尽量提高成功建立数量。次要目标是在不违背首要目标的基础上，尽量降低网络外部频谱碎片程度（External Fragmentation Metric，EFM）。'
    return '\n\n'.join([_s1_req(context['request']),_network(context),_s1_actions(context,'3. 当前可行资源分配动作：'),tail])

def _x4_req(req):
    return f"1.当前业务请求：当前时刻为{_fmt_num(req['arrival_time'])}，请你为业务请求{req['request_id']}，建立一项从节点{int(req['source_node_id'])}到节点{int(req['destination_node_id'])}的业务连接，该请求需要连续使用{int(req['required_slots'])}个频谱槽位，业务连接持续时长为{_fmt_num(req['holding_time'])}。"

def render_x4_step(episode,context,endpoint):
    if endpoint!='llm':
        raise ValueError('endpoint must be llm')
    tail='你的任务是根据当前网络资源状态，自行搜索一条可行有向路径，并为该路径分配满足请求需求的连续频谱槽位来完成业务请求的建立，同时考虑本次资源分配对后续业务请求的长期影响。首要目标是在整个动态决策序列中尽量减少被阻塞的业务请求，即尽量提高成功建立数量。次要目标是在不违背首要目标的基础上，尽量降低网络外部频谱碎片程度（External Fragmentation Metric，EFM）。'
    return '\n'.join([_x4_req(context['request']),_network(context,prefix='2.当前网络有向链路及频谱资源状态：'),'',tail])
