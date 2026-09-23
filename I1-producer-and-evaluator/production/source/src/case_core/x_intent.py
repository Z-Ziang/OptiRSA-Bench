from __future__ import annotations


def render_x2_intent(request: dict) -> str:
    return (
        f"请为节点 {int(request['source_node_id'])} 到节点 {int(request['destination_node_id'])} 建立一条业务连接，"
        f"该业务需要连续占用 {int(request['required_slots'])} 个频谱槽。请在当前网络资源状态下自主选择完整有向路径和频谱起始位置，"
        "优先使可行路径跳数最少；在达到最少跳数的方案中，再尽量降低分配后的全网 WUFR。"
    )


def render_x3_intent(requests: list[dict]) -> str:
    if not requests:
        raise ValueError("X3 requires at least one request")
    parts=[]
    for req in requests:
        parts.append(
            f"业务 {req['request_id']}：从节点 {int(req['source_node_id'])} 到节点 {int(req['destination_node_id'])}，"
            f"需要连续占用 {int(req['required_slots'])} 个频谱槽"
        )
    return (
        "当前需要同时建立以下业务连接：" + "；".join(parts) + "。"
        "请把这些业务作为同一批请求进行联合路由与频谱分配，整批只能全部接收或全部拒绝。"
        "若可行，先最小化整批新增频谱资源占用量 ΔTSO，再在最优 ΔTSO 的方案中降低分配后的全网 WUFR。"
    )
