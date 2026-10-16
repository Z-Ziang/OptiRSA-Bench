"""Materialize the approved MID/5-60 hop-stratified selection, no production/API."""
from pathlib import Path
import csv,json,hashlib,collections,zipfile,re,math,shutil
BASE=Path('D:/codex/正式数据集');OUT=Path(__file__).resolve().parent
AUDIT=BASE/'X2X3_COVERAGE_REVIEW_20261016_R1';SUP=BASE/'MID_R2_X2_X3_SCREEN_5_TO_60_20261015_R1'
PACKAGE=OUT/'OptiRSA_X2X3_MID_5_60_HOP_GE2_R1';SEED='OptiRSA_HOP2_BASELINE_MID_5TO60_20261016_R1'
def sha(b):return hashlib.sha256(b).hexdigest()
def js(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def rank(r,label=''):return sha((SEED+'|'+label+'|'+r['uid']).encode())
def writecsv(p,rows):
 rows=list(rows)
 if not rows:return
 cols=list(dict.fromkeys(k for r in rows for k in r))
 with p.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
  for r in rows:w.writerow({k:js(v) if isinstance(v,(dict,list)) else v for k,v in r.items()})
def jsonwrite(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
rr=[json.loads(x) for x in (AUDIT/'case_features.jsonl').read_text(encoding='utf-8').splitlines()]
assert len(rr)==8531 and len({r['scientific_signature'] for r in rr})==8531
eligible=[r for r in rr if 5<=r['node_count']<=60 and r['load_band']=='MID' and r['R']==(1 if r['task']=='X2' else 2)]
main=[r for r in eligible if r['hop3_pass']]
two=[r for r in eligible if all(h is not None and h>=2 for h in r['hops']) and 2 in r['hops']]
def stratum(r):return (r['topology_id'],r['decision'],js(r['widths']))
def memberkey(r,q):return (r['graph_signature'],r['snapshot_signature'],q['request_id'],q['source'],q['destination'],q['w'])
x2index=collections.defaultdict(list)
for r in main+two:
 if r['task']=='X2':x2index[memberkey(r,r['aligned_requests'][0])].append(r)
def counterparts(r):
 if r['task']!='X3':return []
 return sorted({x['uid'] for q in r['aligned_requests'] for x in x2index.get(memberkey(r,q),[])})
byuid={r['uid']:r for r in rr};kept={r['uid'] for r in main};pairpriorities=set();plan=[];quotas={}
for task in ['X3','X2']:
 for size in ['5-10','11-29','30-37','38-59','60']:
  candidates=[r for r in two if r['task']==task and r['size']==size];nmain=sum(r['task']==task and r['size']==size for r in main);n=min(len(candidates),nmain//9)
  groups=collections.defaultdict(list)
  for r in candidates:groups[stratum(r)].append(r)
  alloc={k:n*len(v)//len(candidates) for k,v in groups.items()} if candidates else {}
  remaining=n-sum(alloc.values())
  ordered=sorted(groups,key=lambda k:(-(n*len(groups[k])%len(candidates)),sha((SEED+js(k)).encode()))) if candidates else []
  for k in ordered[:remaining]:alloc[k]+=1
  chosen=[]
  for k,items in groups.items():
   if task=='X3':items.sort(key=lambda r:(-len(counterparts(r)),rank(r,'X3_PAIR_PREFERENCE')))
   else:items.sort(key=lambda r:(r['uid'] not in pairpriorities,rank(r,'X2_PAIR_PREFERENCE')))
   chosen.extend(items[:alloc[k]])
   quotas[(task,size,k)]=alloc[k]
   plan.append(dict(task=task,size=size,topology_id=k[0],decision=k[1],widths=k[2],two_hop_available=len(items),two_hop_selected=alloc[k]))
  assert len(chosen)==n
  for r in chosen:
   kept.add(r['uid'])
   if task=='X3':pairpriorities.update(counterparts(r))
selected=sorted([r for r in eligible if r['uid'] in kept],key=lambda r:(r['node_count'],r['topology_id'],r['task'],r['uid']))
assert len(selected)==4608 and collections.Counter(r['task'] for r in selected)=={'X2':3342,'X3':1266}
assert all(min(r['hops'])>=2 for r in selected)
assert sum(not r['hop3_pass'] for r in selected if r['task']=='X2')==332
assert sum(not r['hop3_pass'] for r in selected if r['task']=='X3')==126
assert not PACKAGE.exists(),'Refuse to overwrite previous materialized package'
PACKAGE.mkdir();(PACKAGE/'reports').mkdir();(PACKAGE/'case_sets').mkdir();(PACKAGE/'case_sets/_index').mkdir();(PACKAGE/'provenance').mkdir()
z=zipfile.ZipFile(BASE/'X2X3_20261014.zip');prefix='OptiRSA_Bench_L5_X2_X3/'
original={r['case_uid']:r for r in map(json.loads,z.read(prefix+'case_sets/_index/cases.jsonl').splitlines())}
suppdirs={r['uid']:SUP/r['local_case_dir'] for r in csv.DictReader((SUP/'191条实际载荷与来源验收.csv').open(encoding='utf-8-sig'))}
for n in z.namelist():
 rel=n[len(prefix):] if n.startswith(prefix) else ''
 if rel.startswith('evaluation/') and not n.endswith('/'):
  dest=PACKAGE/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(n))
for n in ['README_中文.md','README.md','THIRD_PARTY_NOTICES.md','BUILD_REPORT.json']:
 (PACKAGE/'provenance'/('SOURCE_'+n)).write_bytes(z.read(prefix+n))
validatorhash={t:sha((PACKAGE/f'evaluation/frozen/runtime/src/tasks/{t.lower()}/validator.py').read_bytes()) for t in ['X2','X3']}
newindex=[];payloadchecks=0
for i,r in enumerate(selected):
 if r['origin']=='FORMAL':
  m=dict(original[r['uid']]);sourcebase=prefix+m['case_dir']+'/';identity=json.loads(z.read(sourcebase+'identity.json'));dest=PACKAGE/m['case_dir'];dest.mkdir(parents=True)
  for rel in list(identity['files'])+['identity.json','metadata.json']:
   raw=z.read(sourcebase+rel)
   if rel in identity['files']:assert sha(raw)==identity['files'][rel]['sha256'];payloadchecks+=1
   target=dest/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
 else:
  src=suppdirs[r['uid']];topname=r['topology_id'].split('TOP_',1)[-1].split('_',1)[-1];folder=re.sub('[^A-Za-z0-9_-]','_',topname)+f"_n{r['node_count']}_HISTORY";relbase=f"case_sets/{folder}/{r['task']}/{r['uid'][:16]}";dest=PACKAGE/relbase;dest.mkdir(parents=True)
  for sub in ['public','private']:
   for f in (src/sub).iterdir():
    if f.is_file():target=dest/sub/f.name;target.parent.mkdir(exist_ok=True);shutil.copyfile(f,target)
  shutil.copyfile(src/'identity.json',dest/'source_identity.json')
  m=dict(case_uid=r['uid'],case_id=r['case_id'],task=r['task'],topology_id=r['topology_id'],topology_folder=folder,graph_hash=r['graph_signature'],snapshot_hash=r['snapshot_signature'],case_dir=relbase,family_ids=[],node_count=r['node_count'],scale='30-59',occupancy=r['actual_utilization'],load_band='MID',decision=r['decision'],request_count=r['R'],requested_slots=js(r['widths']),certificate=r['certificate'],oracle_status=r['certificate'],exposed=r['exposed'],interface_status='REVIEW_SOURCE_INTERFACE_BINDING',input_tokens='UNKNOWN_NOT_MEASURED')
  messages=[dict(role=role,content=(dest/'public'/name).read_bytes().decode('utf-8')) for role,name in [('system','system_prompt.txt'),('user','user_prompt.txt')]];m['messages_sha256']=sha(js(messages).encode());m['input_characters']=sum(len(x['content']) for x in messages)
  files={f.relative_to(dest).as_posix():dict(sha256=sha(f.read_bytes()),bytes=f.stat().st_size) for sub in ['public','private'] for f in (dest/sub).iterdir() if f.is_file()}
  identity=dict(case_uid=r['uid'],case_id=r['case_id'],task=r['task'],files=files,validator_source_sha256=validatorhash[r['task']],source_archive=r['source_archive'],source_member=r['source_member'],source_root_sha256=r['root_sha256'],source_identity='source_identity.json',verification_scope='Existing payload/source rebound; no new oracle solve; runtime reference regrade separately recorded')
  jsonwrite(dest/'identity.json',identity)
  jsonwrite(dest/'metadata.json',m)
 assert sha((dest/'private/root_case.json').read_bytes())==r['root_sha256']
 assert identity['validator_source_sha256']==validatorhash[r['task']]
 m.update(selection_version='MID_5TO60_HOP_GE2_BASELINE10PCT_R1',hop_stratum='GE3_MAIN' if r['hop3_pass'] else 'HOP2_BASELINE',shortest_hops=r['hops'],selection_scale=r['size'],origin=r['origin'],source_archive=r['source_archive'],source_member=r['source_member'],source_root_sha256=r['root_sha256'])
 newindex.append(m)
 if (i+1)%500==0:print('materialized',i+1,flush=True)
with (PACKAGE/'case_sets/_index/cases.jsonl').open('w',encoding='utf-8') as f:
 for r in newindex:f.write(js(r)+'\n')
writecsv(PACKAGE/'case_sets/_index/cases.csv',newindex)
writecsv(PACKAGE/'reports/selected_case_features.csv',selected);writecsv(PACKAGE/'reports/hop2_stratum_quotas.csv',plan)
decisions=[]
for r in rr:
 reason='SELECTED_GE3' if r['uid'] in kept and r['hop3_pass'] else 'SELECTED_HOP2' if r['uid'] in kept else 'OUTSIDE_N5_60' if not 5<=r['node_count']<=60 else 'OUTSIDE_MID' if r['load_band']!='MID' else 'OUTSIDE_REQUEST_COUNT' if r['R']!=(1 if r['task']=='X2' else 2) else 'CONTAINS_HOP1' if any(h is None or h<2 for h in r['hops']) else 'HOP2_NOT_SAMPLED'
 decisions.append(dict(uid=r['uid'],task=r['task'],node_count=r['node_count'],topology_id=r['topology_id'],hops=r['hops'],origin=r['origin'],selected=r['uid'] in kept,reason=reason))
writecsv(PACKAGE/'reports/all_source_selection_decisions.csv',decisions)
coverage=[]
for t in ['X2','X3']:
 for size in ['5-10','11-29','30-37','38-59','60']:
  a=[r for r in selected if r['task']==t and r['size']==size];coverage.append(dict(task=t,size=size,total=len(a),GE3=sum(r['hop3_pass'] for r in a),HOP2=sum(not r['hop3_pass'] for r in a),ACCEPT=sum(r['decision']=='ACCEPT' for r in a),REJECT=sum(r['decision']=='REJECT' for r in a),topology_ids=len({r['topology_id'] for r in a}),graphs=len({r['graph_signature'] for r in a}),graph_states=len({(r['graph_signature'],r['snapshot_signature']) for r in a}),supplement=sum(r['origin']!='FORMAL' for r in a)))
writecsv(PACKAGE/'reports/coverage_by_scale_task.csv',coverage)
topos=[]
for top,t in sorted({(r['topology_id'],r['task']) for r in selected}):
 a=[r for r in selected if r['topology_id']==top and r['task']==t];topos.append(dict(topology_id=top,task=t,node_count=a[0]['node_count'],total=len(a),HOP2=sum(not r['hop3_pass'] for r in a),GE3=sum(r['hop3_pass'] for r in a),graph_states=len({(r['graph_signature'],r['snapshot_signature']) for r in a}),ACCEPT=sum(r['decision']=='ACCEPT' for r in a),REJECT=sum(r['decision']=='REJECT' for r in a)))
writecsv(PACKAGE/'reports/coverage_by_topology.csv',topos)
links=[]
for r in selected:
 if r['task']=='X3':
  for q in r['aligned_requests']:
   for x in x2index.get(memberkey(r,q),[]):
    if x['uid'] in kept:links.append(dict(X3_uid=r['uid'],X2_uid=x['uid'],request_id=q['request_id'],graph_signature=r['graph_signature'],snapshot_signature=r['snapshot_signature'],evidence='Same graph/spectrum/request_id/OD/width; probability identity checked from materialized roots'))
writecsv(PACKAGE/'reports/x2_x3_request_links.csv',links)
newbyuid={m['case_uid']:m for m in newindex};rootcache={}
for link in links:
 for task in ['X2','X3']:
  uid=link[task+'_uid']
  if uid not in rootcache:rootcache[uid]=json.loads((PACKAGE/newbyuid[uid]['case_dir']/'private/root_case.json').read_bytes())
 assert rootcache[link['X2_uid']].get('required_slots_probabilities')==rootcache[link['X3_uid']].get('required_slots_probabilities')
linkedX3=len({r['X3_uid'] for r in links});families=collections.defaultdict(set)
for m in newindex:
 for fam in m.get('family_ids',[]):families[fam].add(m['task'])
counts=dict(collections.Counter(r['task'] for r in selected));suppcounts=dict(collections.Counter(r['task'] for r in selected if r['origin']!='FORMAL'))
summary=dict(case_count=len(selected),task_counts=counts,hop2_counts={t:sum(r['task']==t and not r['hop3_pass'] for r in selected) for t in ['X2','X3']},hop3_counts={t:sum(r['task']==t and r['hop3_pass'] for r in selected) for t in ['X2','X3']},supplement_counts=suppcounts,all_source_records=len(rr),selection_decisions=dict(collections.Counter(r['reason'] for r in decisions)),linked_X3_cases=linkedX3,X3_without_selected_member_X2=counts['X3']-linkedX3,request_link_edges=len(links),source_family_ids_both_tasks=sum(v=={'X2','X3'} for v in families.values()),coverage=coverage,original_formal_file_hash_checks=payloadchecks,seed=SEED,API_calls=0,new_scientific_cases=0)
jsonwrite(PACKAGE/'BUILD_REPORT.json',summary)
jsonwrite(PACKAGE/'SELECTION_PROTOCOL.json',dict(version='R1',seed=SEED,population='8340 original plus 191 audited historical additions',scope='English N5-60 MID; X2 R1, X3 R2',mandatory='Exclude any OD shortest_hops <2; retain all eligible >=3-hop candidates',hop2_target='Each task x selection size bin: floor(GE3_count/9), capped by availability',hop2_strata=['topology_id','truth_decision','widths'],allocation='Proportional largest remainder, deterministic hash tie breaks; no minimum cell allocation',within_stratum='Prefer available exact source member relationships, then deterministic hash rank; X3 sampled first, X2 prefers selected X3 counterparts within fixed strata quotas',difficulty='Hop categories describe span, not frozen difficulty labels',original_sources_modified=False,interface='Preserve source REVIEW; supplementary interface REVIEW_SOURCE_INTERFACE_BINDING. No formal interface approval inferred',source_artifact_sha256_manifest='../X2X3_COVERAGE_REVIEW_20261016_R1/来源SHA256.csv'))
shutil.copyfile(AUDIT/'来源SHA256.csv',PACKAGE/'provenance/source_archive_sha256.csv')
lines=['# X2/X3现有成果筛选集（2026-10-16）','','本包实际包含4608条现有英文Case：X2 3342条、X3 1266条。原始题面、真值及参考答案保留来源字节。范围为5–60节点、MID，X2单请求、X3双请求。原始归档未改动；未生产新题、未派生O1、未调用模型。','','## 选样规则','','任何请求的拓扑最短距离为1跳即排除。X2单请求>=3跳、X3每请求>=3跳构成主体。少量含2跳且不含1跳的Case作为基础对照，每任务每规模档最多约10%。这是按路径跨度组织的诊断候选集，不代表自然业务分布或已验证的简单/困难正态分布。','','两跳题按拓扑、ACCEPT/REJECT及宽度组合分层，比例分配，在配额内优先保留X2/X3请求关联，其次固定哈希排序；没有使用模型得分。相关选取概率并非统一随机抽样概率，后续不要当成原始题库的无偏代表样本。','','## 规模分布','','|任务|规模|总数|三跳主体|两跳对照|ACCEPT|REJECT|','|---|---|---:|---:|---:|---:|---:|']
for r in coverage:lines.append('|'+ '|'.join(str(r[k]) for k in ['task','size','total','GE3','HOP2','ACCEPT','REJECT'])+'|')
lines+=['',f"历史补充实际入选：{suppcounts}。请求成员关联覆盖{linkedX3}条X3，共{len(links)}条X3→X2成员关联边；其余X3保留任务本身资格，并在统计中明确缺少入选X2成员。原Family ID同时保留X2/X3的有{summary['source_family_ids_both_tasks']}组，不能据此称为完整五任务家族。",'','## 文件结构','','case_sets/拓扑文件夹/X2或X3/CaseUID：public为给模型的英文输入；private为真值、参考输出及验证证据。identity.json绑定哈希。case_sets/_index/cases.jsonl为统一运行清单。reports中有逐题特征、全部8531条来源的取舍记录、规模/拓扑覆盖、两跳配额及同源关联。','','evaluation包含从原包复制的Inspect入口及冻结科学评分器。未内置Python/Inspect依赖或平台凭据。Windows可先按照evaluation/setup.ps1安装依赖，平台与API Key由使用者提供。不会自动调用API。','','请使用本包新增的evaluation/verify_selected_dataset.py进行新版完整性核验；原evaluation/verify_dataset.py含8340条原包硬编码，仅作来源程序保留，不适用于本4608条选集。','','来源interface_status为REVIEW的记录继续保留；补充题标记REVIEW_SOURCE_INTERFACE_BINDING。数据文件齐全、来源Validator通过，不等于正式接口准入已完成。冻结英文输入没有添加WUFR公式，优化目标及评分器未更改。','','逐题Token未测量，字符数不等于Token。部分Case曾被使用或处于开发流程，exposed字段保留，本包不自动称为全新盲测集。原始最优真值沿用已有精确证据，未独立重新全局求解。','','## 后续工作','','优先填补38–59节点的任务成员缺项、60节点覆盖、多独立初态和经认证的联合协调场景。两跳题无需大批补产。取舍记录中的排除只作用于本新版，原始成果完整保留。']
(PACKAGE/'README_中文.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
z.close();jsonwrite(OUT/'BUILD_SUMMARY.json',summary);print(json.dumps(summary,ensure_ascii=False),flush=True)
