from __future__ import annotations
from dataclasses import dataclass
import json, os, urllib.request

REWRITE_SYSTEM_PROMPT = """你只负责对一条已经具有确定标准答案的光网络业务意图进行自然语言改写。
目标：让表达方式更加多样，但不得改变任何业务语义。
绝对不可修改：所有request_id、节点编号、required_slots、arrival_time、holding_time、请求数量、各请求字段之间的对应关系、优化目标及其优先级；I1-C中各业务请求出现顺序也不得改变。
不得增加网络拓扑、频谱状态、路径、候选动作、新业务要求、新约束或标准答案字段名/目标枚举编码。
若标准语义中的 objectives 只有1个目标，严禁使用“若相同再……”“其次……”“在此基础上再……”等暗示还存在另一层优化目标或 tie-break 的表达。若 objectives 有多个目标，必须完整保留每个目标及其原有优先级，不得省略任何一级目标。
数字和标识符必须原样保留。
只返回一个JSON对象：{\"rewritten_prompt\":\"...\"}。"""

@dataclass(frozen=True)
class RewriteResult:
    rewritten_prompt: str
    attempt: int
    raw_response: str | None = None

class IdentityRewriteClient:
    def rewrite(self, base_prompt: str, answer: dict) -> str:
        return base_prompt

    def rewrite_with_raw(
        self,
        base_prompt: str,
        answer: dict,
        *,
        difficulty: str = "EASY",
        rewrite_style: str | None = None,
        system_prompt: str | None = None,
    ):
        del difficulty, rewrite_style, system_prompt
        return self.rewrite(base_prompt, answer), None

    def parse_intent(self, prompt: str, answer_hint: dict | None = None) -> dict:
        if answer_hint is None:
            raise ValueError("IdentityRewriteClient requires answer_hint for deterministic validation")
        return answer_hint

    def parse_intent_with_raw(self, prompt: str, answer_hint: dict | None = None):
        return self.parse_intent(prompt, answer_hint), None

class OpenAICompatibleRewriteClient:
    def __init__(self, *, base_url: str, api_key_env: str, model: str, temperature: float=0.7, top_p: float=1.0, max_tokens: int=512, timeout_seconds: float=60.0, enable_thinking: bool | None = None):
        self.base_url=base_url.rstrip('/'); self.api_key_env=api_key_env; self.model=model; self.temperature=float(temperature); self.top_p=float(top_p); self.max_tokens=int(max_tokens); self.timeout_seconds=float(timeout_seconds); self.enable_thinking=enable_thinking
    def _chat(self, system: str, user: str, temperature: float, *, top_p: float | None = None, max_tokens: int | None = None) -> str:
        key=os.environ.get(self.api_key_env)
        if not key: raise RuntimeError(f"missing API key environment variable: {self.api_key_env}")
        payload={"model":self.model,"messages":[{"role":"system","content":system},{"role":"user","content":user}],"temperature":temperature,"top_p":self.top_p if top_p is None else float(top_p),"max_tokens":self.max_tokens if max_tokens is None else int(max_tokens)}
        if self.enable_thinking is not None:
            payload["enable_thinking"] = bool(self.enable_thinking)
        req=urllib.request.Request(self.base_url+"/chat/completions",data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},method="POST")
        with urllib.request.urlopen(req,timeout=self.timeout_seconds) as resp:
            obj=json.loads(resp.read().decode('utf-8'))
        return obj["choices"][0]["message"]["content"]
    @staticmethod
    def _extract_json(text: str) -> dict:
        s=text.strip()
        if s.startswith('```'):
            s=s.split('\n',1)[1] if '\n' in s else s
            if s.rstrip().endswith('```'): s=s.rstrip()[:-3].rstrip()
        return json.loads(s)
    def rewrite(self, base_prompt: str, answer: dict) -> str:
        text, _ = self.rewrite_with_raw(base_prompt, answer, difficulty="UNSPECIFIED")
        return text

    def rewrite_with_raw(
        self,
        base_prompt: str,
        answer: dict,
        *,
        difficulty: str = "UNSPECIFIED",
        rewrite_style: str | None = None,
        system_prompt: str | None = None,
    ):
        if rewrite_style is None:
            label = "难度等级：" + difficulty
        else:
            label = "表达风格：" + rewrite_style
        user=label+"\n基础文本：\n"+base_prompt+"\n\n不可变标准语义：\n"+json.dumps(answer,ensure_ascii=False,sort_keys=True)
        raw = self._chat(system_prompt or REWRITE_SYSTEM_PROMPT, user, self.temperature, top_p=self.top_p, max_tokens=self.max_tokens)
        obj=self._extract_json(raw)
        text=obj.get('rewritten_prompt')
        if not isinstance(text,str) or not text.strip(): raise ValueError('rewrite response missing rewritten_prompt')
        return text.strip(), raw
    def parse_intent(self, prompt: str, answer_hint: dict | None = None) -> dict:
        parsed, _ = self.parse_intent_with_raw(prompt, answer_hint)
        return parsed

    def parse_intent_with_raw(self, prompt: str, answer_hint: dict | None = None):
        if answer_hint is None:
            raise ValueError('answer_hint required to select I1 schema')
        kind=answer_hint.get('intent_type')
        if kind=='SINGLE':
            template={"intent_type":"SINGLE","source_node_id":0,"destination_node_id":0,"required_slots":0,"objectives":[]}
        elif kind=='CONCURRENT':
            template={"intent_type":"CONCURRENT","requests":[{"request_id":"","source_node_id":0,"destination_node_id":0,"required_slots":0}],"objectives":[]}
        elif kind=='DYNAMIC':
            template={"intent_type":"DYNAMIC","request":{"request_id":"","source_node_id":0,"destination_node_id":0,"required_slots":0,"arrival_time":0.0,"holding_time":0.0},"objectives":[]}
        else:
            raise ValueError(f'unknown intent_type: {kind}')
        system=(
            "你是严格的I1业务意图语义核验解析器。只根据用户提供的自然语言提取语义，只返回JSON，不解释。"
            "objectives必须使用以下枚举并保持文本中的优先级顺序："
            "MIN-HOP-COUNT（最小路径跳数）；MIN-FRAGMENTATION（最小本次分配后全网频谱碎片）；"
            "MIN-TOTAL-SLOT-USAGE（最小总槽位占用）；MAX-ACCEPTED-REQUESTS（动态序列最大成功建立请求数）；"
            "MIN-EXTERNAL-FRAGMENTATION（动态序列最小外部频谱碎片）。"
            "并发requests数组必须按自然语言中的请求出现顺序输出。"
        )
        user="输出结构示例（0和空字符串只是占位符，不是答案；数组长度按文本实际内容确定）：\n"+json.dumps(template,ensure_ascii=False)+"\n\n待解析自然语言：\n"+prompt
        raw = self._chat(system,user,0.0,top_p=1.0,max_tokens=self.max_tokens)
        return self._extract_json(raw), raw

def build_rewrite_client(cfg: dict):
    rw=cfg.get('rewrite',{})
    mode=rw.get('mode','identity')
    if mode=='identity': return IdentityRewriteClient()
    if mode=='openai_compatible':
        return OpenAICompatibleRewriteClient(base_url=rw['base_url'],api_key_env=rw['api_key_env'],model=rw['model'],temperature=rw.get('temperature',0.7),top_p=rw.get('top_p',1.0),max_tokens=rw.get('max_tokens',512),timeout_seconds=rw.get('timeout_seconds',60),enable_thinking=rw.get('enable_thinking'))
    raise ValueError(f"unknown rewrite mode: {mode}")
