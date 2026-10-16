import collections,csv,hashlib,io,json,pathlib,zipfile
BASE=pathlib.Path('D:/codex/正式')
OUT=BASE/'X2X3_MERGE_AUDIT_20261017_R1'
ARCHIVES=[BASE/'包含部分评测结果的X2X3.zip',BASE/'X2X3后来补充.zip']
PREFIX=['01_original/','02_supplement/']
TOP='OptiRSA_X2X3_MERGED_20261017_R1/'
DEST=BASE/'OptiRSA_X2X3_合并含评测记录_20261017_R1.zip'
def sha(b):return hashlib.sha256(b).hexdigest()
def canonical(o):return json.dumps(o,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def dump(o):return json.dumps(o,ensure_ascii=False,indent=2).encode('utf-8')
def hashfile(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def signature(o):
 reqs=o.get('requests',[o.get('request')]);reqs=[{k:v for k,v in r.items() if k!='request_id'} for r in reqs]
 obj={'task':o['task_type'],'nodes':sorted(o['nodes']),'links':sorted(o['directed_links'],key=lambda x:x['link_id']), 'slot_count':o['slot_count'],'spectrum':sorted(o['link_spectrum_states'],key=lambda x:x['link_id']), 'probabilities':o['required_slots_probabilities'],'requests':sorted(reqs,key=canonical)}
 return sha(canonical(obj).encode())
def hops(o):
 adj=collections.defaultdict(list)
 for e in o['directed_links']:adj[e['source_node_id']].append(e['destination_node_id'])
 hs=[]
 for r in o.get('requests',[o.get('request')]):
  s,t=r['source_node_id'],r['destination_node_id'];q=collections.deque([(s,0)]);seen={s};found=None
  while q:
   u,d=q.popleft()
   if u==t:found=d;break
   for v in adj[u]:
    if v not in seen:seen.add(v);q.append((v,d+1))
  hs.append(found)
 return hs
def csvbytes(rows):
 s=io.StringIO(newline='');fields=list(dict.fromkeys(k for r in rows for k in r));w=csv.DictWriter(s,fields);w.writeheader()
 for r in rows:w.writerow({k:canonical(v) if isinstance(v,(list,dict)) else v for k,v in r.items()})
 return ('\ufeff'+s.getvalue()).encode('utf-8')
zs=[zipfile.ZipFile(p) for p in ARCHIVES]
files=[{i.filename:i for i in z.infolist() if not i.is_dir()} for z in zs]
for fs in files:
 assert len({n.casefold() for n in fs})==len(fs),'case-insensitive path collision'
 for n in fs:
  assert not n.startswith('/') and '\\' not in n and '..' not in pathlib.PurePosixPath(n).parts
oldbase='OptiRSA_X2X3_MID_5_60_HOP_GE2_R1/'
old=[json.loads(s) for s in zs[0].read(oldbase+'case_sets/_index/cases.jsonl').decode('utf-8-sig').splitlines() if s.strip()]
new=[json.loads(s) for s in zs[1].read('case_index.jsonl').decode('utf-8-sig').splitlines() if s.strip()]
completed=[json.loads(s) for s in zs[0].read('HANDOFF_X2X3_SENIOR_20261016/completed_results.jsonl').decode('utf-8-sig').splitlines() if s.strip()]
evalcounts=collections.Counter(r['case_uid'] for r in completed)
rows=[];issues=[]
for si,data in enumerate([old,new]):
 for r in data:
  if si==0:
   folder=oldbase+r['case_dir'];rootpath=folder+'/private/root_case.json';vp=folder+'/private/validation.json';sy=folder+'/public/system_prompt.txt';up=folder+'/public/user_prompt.txt'
   uid=r['case_uid'];decision=r['decision'];cert=r['certificate'];interface=r.get('interface_status','UNKNOWN')
  else:
   folder=r['package_dataset_path'];rootpath=f"{folder}/internal/cases/{r['task']}/{r['case_id']}/root_case.json";vp=f"{folder}/internal/private/{r['task']}/{r['case_id']}/validation.json";sy=f"{folder}/evaluation_case/{r['task']}/llm_system_prompt.txt";up=f"{folder}/evaluation_case/{r['task']}/llm/case_000001.json"
   uid=r['scientific_key'];decision=r['decision'];cert=r['certificate'];interface='SOURCE_INTERFACE_REVIEW_NOT_NEWLY_ACCEPTED'
  for p in [rootpath,vp,sy,up]:assert p in files[si],p
  o=json.loads(zs[si].read(rootpath));v=json.loads(zs[si].read(vp));assert v.get('valid') is True,(uid,v)
  assert o['task_type']==r['task'];sig=signature(o);hs=hops(o);bits=[b for st in o['link_spectrum_states'] for b in st['slot_availability']]
  rows.append({'source':'original' if si==0 else 'supplement','case_uid':uid,'case_id':r['case_id'],'task':r['task'],'node_count':len(o['nodes']),'topology_id':o['topology_id'],'semantic_signature':sig,'root_path':PREFIX[si]+rootpath,'case_dir':PREFIX[si]+folder,'system_prompt_path':PREFIX[si]+sy,'user_input_path':PREFIX[si]+up,'validator_path':PREFIX[si]+vp,'decision':decision,'certificate':cert,'validator_valid':True,'request_count':len(hs),'shortest_hops':hs,'initial_utilization':1-sum(bits)/len(bits),'interface_status':interface,'saved_evaluation_record_count':evalcounts[uid] if si==0 else 0})
  if any(h is None or h<2 for h in hs):issues.append({'case_uid':uid,'issue':'HOP_BELOW_2_OR_UNREACHABLE','hops':hs})
  if not 5<=len(o['nodes'])<=60:issues.append({'case_uid':uid,'issue':'OUTSIDE_NODE_5_60'})
groups=collections.defaultdict(list)
for r in rows:groups[r['semantic_signature']].append(r)
unique=[];duplicates=[]
for sig,rs in groups.items():
 first=rs[0];unique.append(first)
 if len(rs)>1:duplicates.append({'semantic_signature':sig,'count':len(rs),'case_ids':[r['case_id'] for r in rs],'sources':[r['source'] for r in rs],'decisions':sorted(set(r['decision'] for r in rs))})
 conflicts=[r for r in rs if r['decision']!=first['decision']]
 if conflicts:issues.append({'signature':sig,'issue':'TRUTH_DECISION_CONFLICT'})
pending=json.loads(zs[1].read('pending_tasks.json'))
summary={'source_cases':{'original':dict(collections.Counter(r['task'] for r in old)),'supplement':dict(collections.Counter(r['task'] for r in new))},'indexed_records':len(rows),'unique_semantic_objects':len(unique),'unique_by_task':dict(collections.Counter(r['task'] for r in unique)),'duplicate_groups':len(duplicates),'issues':issues,'preserved_evaluation_records':len(completed),'pending_in_supplement':len(pending),'additional_server_cases_not_downloaded':'UNKNOWN: user reports 10+; server unavailable; not included; distinct from packaged pending list','verification_scope':'Source payload hashes, ZIP CRC, indexed root and Validator status. No independent exact re-solve, model API call or fresh interface acceptance.','signature_method':'Same task + labeled nodes/links + full spectrum + slot_count + required_slots_probabilities + request objects excluding only request_id. Request order normalized. Node relabeling not treated as graph isomorphism; not a proof of objective/contract equivalence.'}
print('INDEX',canonical(summary),flush=True)
source_manifest=[];source_errors=[];expected=[]
for si in range(2):
 if si==0:
  expected.append({oldbase+r['path']:r['sha256'] for r in csv.DictReader(io.StringIO(zs[si].read(oldbase+'FILE_MANIFEST.csv').decode('utf-8-sig')))})
 else:expected.append({r['path']:r['sha256'] for r in json.loads(zs[si].read('FILE_MANIFEST.json'))})
source_meta=[{'source':p.name,'bytes':p.stat().st_size,'sha256':hashfile(p)} for p in ARCHIVES]
assert not DEST.exists(),DEST
with zipfile.ZipFile(DEST,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as zout:
 for si,z in enumerate(zs):
  for count,(name,info) in enumerate(files[si].items(),1):
   b=z.read(name);digest=sha(b)
   if name in expected[si] and expected[si][name]!=digest:source_errors.append({'source':si,'path':name,'issue':'SOURCE_MANIFEST_HASH_MISMATCH'})
   path=PREFIX[si]+name;zout.writestr(TOP+path,b);source_manifest.append({'path':path,'bytes':len(b),'sha256':digest,'source_archive':ARCHIVES[si].name,'source_member':name})
   if count%12000==0:print('COPIED',si,count,flush=True)
  for name in expected[si]:
   if name not in files[si]:source_errors.append({'source':si,'path':name,'issue':'MISSING_SOURCE_MANIFEST_MEMBER'})
 summary['source_manifest_errors']=source_errors
 summary['source_manifest_checked_entries']=sum(len(x) for x in expected)
 summary['preserved_source_files']=len(source_manifest)
 summary['source_archives']=source_meta
 readme=f'''# X2/X3 合并数据与已有评测记录（2026-10-17）

本包合并用户提供的两个本地 ZIP。原始文件逐字节保留，原包没有删除或修改。

## 数量
原包 X2 {summary['source_cases']['original'].get('X2',0)}，X3 {summary['source_cases']['original'].get('X3',0)}；补充包 X2 {summary['source_cases']['supplement'].get('X2',0)}，X3 {summary['source_cases']['supplement'].get('X3',0)}。
共 {len(rows)} 条来源记录；按公开科学对象审计签名得到 {len(unique)} 个唯一对象。重复组 {len(duplicates)}。不能只看名字去重，版本/接口仍应分别检查。
原交接 completed_results.jsonl 的 {len(completed)} 条评测记录全部保留；它们是答卷记录，不等于全部正确，不代表新增补充题已测。

## 目录与使用
- 01_original/：原包完整结构，包含 4608 题、评分程序、Inspect 入口、HANDOFF 评测结果和逐题交接状态。进入里面原数据根目录阅读原 README 及交接说明。
- 02_supplement/：补充包完整结构，包含 case_index、cases、runtime、科学证据、pending_tasks.json。进入此目录阅读其 README，使用该版本冻结评分程序。
- MERGED_INDEX/case_inventory.jsonl/csv：全部来源记录，每条提供相对于本合并根目录的 Case、公开输入、root 和 Validator 路径。
- MERGED_INDEX/unique_cases.jsonl：按科学对象签名选取首个来源，原始别名、评测记录均保留。它是导航清单，不是自动重复派发队列。
- MERGED_INDEX/duplicates.json、SUMMARY.json：重叠审计、限制及计数。
- MERGED_INDEX/source_files.csv：每个源文件的目标路径、原包路径、字节数和 SHA256。

公开英文题是评测对象，补充原结构中的中文模板只作为来源辅助文件保留，不另计 Case。private、internal/private、参考答案和未来答案不能提供给模型。
两批输入和评分接口不同，本包只做无损合并与索引，不改提示词、不改真值。不要把新增目录直接交给旧入口并假设兼容。继续评测需先按各版本适配路径，并按 Case×模型×提示词/参数版本排除已有结果及仍由其他会话负责的任务。原交接队列状态属于历史快照，不代表当前实时任务。

## 验证与科学边界
本次检查所有来源文件读取的 ZIP CRC，逐文件复制哈希，原清单 {summary['source_manifest_checked_entries']} 项；清单异常 {len(source_errors)} 项，详见 SUMMARY。每条索引对应的 root、公开题面、私有结果和 valid=true 记录已核实；没有重新求解全池最优值，也没有重新完成实际模型接口验收，原 REVIEW 标记继续有效。
当前合并不强制对补充题重新施加旧 R1 的两跳占比配额；参数与跳数请按统一索引分析。发现的范围或判定冲突列于 SUMMARY 的 issues。

## 服务器未取回部分
补充包内有 {len(pending)} 项未解决生产任务，仅保留记录，不计入有效 Case。用户另述服务器还有十多个 Case 未下载，由于服务器维护，其准确数量和身份 UNKNOWN。本包仅覆盖实际拿到的两个 ZIP，不能声明服务器最新成果全量交付。以后拿到后作为独立增量合并。

## 自包含与运行
原题、答案、证据、原评分代码和原有 Inspect 文件都保留，无需旧服务器公共环境读取本地载荷；运行仍需安装相应依赖和自行配置模型平台凭据。归档未新增 API 密钥，不调用模型。
SHA256SUMS_MERGED.txt 覆盖除它自身外的全部文件。归档旁的 .sha256 是整个 ZIP 校验值。merge_packages.py 可复现合并（输入文件名位于脚本顶部）。
'''
 extras={'README_合并说明_中文.md':readme.encode(),'MERGED_INDEX/case_inventory.jsonl':('\n'.join(canonical(r) for r in rows)+'\n').encode(),'MERGED_INDEX/case_inventory.csv':csvbytes(rows),'MERGED_INDEX/unique_cases.jsonl':('\n'.join(canonical(r) for r in unique)+'\n').encode(),'MERGED_INDEX/duplicates.json':dump(duplicates),'MERGED_INDEX/SUMMARY.json':dump(summary),'MERGED_INDEX/source_files.csv':csvbytes(source_manifest),'merge_packages.py':pathlib.Path(__file__).read_bytes()}
 for name,b in extras.items():zout.writestr(TOP+name,b)
 all_hashes=[(r['path'],r['sha256']) for r in source_manifest]+[(n,sha(b)) for n,b in extras.items()]
 zout.writestr(TOP+'SHA256SUMS_MERGED.txt',''.join(f'{h}  {n}\n' for n,h in all_hashes).encode())
print('ARCHIVE_WRITTEN',DEST,flush=True)
with zipfile.ZipFile(DEST) as z:
 assert len(z.namelist())==len(all_hashes)+1
 for i,(n,h) in enumerate(all_hashes,1):
  assert sha(z.read(TOP+n))==h,n
  if i%16000==0:print('VERIFIED',i,flush=True)
 assert z.testzip() is None
digest=hashfile(DEST)
DEST.with_suffix('.zip.sha256').write_text(digest+'  '+DEST.name+'\n',encoding='utf-8')
receipt={'zip_path':str(DEST),'bytes':DEST.stat().st_size,'sha256':digest,'verified_payload_files':len(all_hashes),'crc':'PASS','payload_hashes':'PASS','summary':summary}
(OUT/'MERGE_RECEIPT.json').write_bytes(dump(receipt));(OUT/'SUMMARY.json').write_bytes(dump(summary));(OUT/'README_合并说明_中文.md').write_text(readme,encoding='utf-8')
print('FINAL',canonical(receipt),flush=True)
