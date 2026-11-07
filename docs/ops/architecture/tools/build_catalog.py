from pathlib import Path
from collections import defaultdict,Counter
import json,hashlib,datetime,re,os
import argparse,sys,tempfile
base=Path(__file__).resolve().parents[1];inv=base/'inventory'
def inventory_paths():
 return tuple(p for p in sorted(inv.glob('*.json')) if p.name not in ['schema.json','catalog.json','reconciliation.json'])
source_inputs=inventory_paths()
source_bytes={p:p.read_bytes() for p in source_inputs}
source_data={p:json.loads(raw) for p,raw in source_bytes.items()}
input_digests={p:hashlib.sha256(raw).hexdigest() for p,raw in source_bytes.items()}
head=source_data[inv/'repository_tasks.json']['baseline_code_ref']
times=[datetime.datetime.fromisoformat(source_data[p]['observed_at'].replace('Z','+00:00')) for p in source_inputs]
now=max(times).astimezone(datetime.timezone(datetime.timedelta(hours=8))).isoformat()
def evidence(kind,location,note):return {'kind':kind,'location':location,'note':note}
cloud=source_data[inv/'runtime_cloud.json']; host=next(x for x in cloud['records'] if x['id']=='host:cloud')
by=defaultdict(list);srcfiles=[]
for p in source_inputs:
 j=source_data[p];srcfiles.append({'file':p.name,'records':len(j['records']),'baseline_code_ref':j['baseline_code_ref'],'sha256':input_digests[p]})
 for r in j['records']:by[r['id']].append((p.name,r,j.get('observed_at')))
rank={'runtime_observed':0,'code_confirmed':1,'documented_only':2,'inferred':3,'unknown':4,'planned':5}
allowed=['evidence_status','observed_at','runtime_observed_at','source_layer','field_observed_at','calendar_observation_partial','calendar_expressions','execution_location','scheduler','timezone','schedule','expected_frequency','entrypoint','runtime','route','paths','path_authority','business_health_reason','depends_on','workflow_status','workflow_group','remediation_state','root_cause_state','deployment_state','verification_state','observation_window','close_conditions','owner','last_verified_at','affected_objects','next_action','semantic_scope']
records=[]
for id,facets in sorted(by.items()):
 facets.sort(key=lambda f:(rank.get(f[1].get('evidence_status'),9),f[0]));first=facets[0][1];assert len({f[1]['kind'] for f in facets})==1
 observations=[];ev=[]
 for file,r,t in facets:
  o={'source_file':file,'record_id':id,'source_inventory_time':t,'source_inventory_code_ref':next(x['baseline_code_ref'] for x in srcfiles if x['file']==file)}
  for k in allowed:
   if k in r:o[k]=r[k]
  o['evidence']=r['evidence'][:6];o['evidence_total_count']=len(r['evidence'])
  if r.get('dependency_candidates'):
   o['dependency_candidate_labels']=[c.get('label','unknown') if isinstance(c,dict) else str(c) for c in r['dependency_candidates'][:12]];o['dependency_candidate_count']=len(r['dependency_candidates'])
  if r['kind']=='incident':
   for k,v in r.items():
    if k not in ['id','name','kind','evidence','health']:o.setdefault(k,v)
  observations.append(o);ev.append(evidence('inventory',f'inventory/{file}#{id}','完整记录与全部证据在该源清单；catalog保留按来源分隔的观察，详情证据最多展示6条。'))
 row={'id':id,'name':first['name'],'kind':first['kind'],'evidence_status':first['evidence_status'],'health':'unknown','evidence':ev,'observations':observations,'depends_on':sorted({d for _,r,_ in facets for d in r.get('depends_on',[])})}
 if first['kind']=='incident':
  for k in ['workflow_status','workflow_group','remediation_state','root_cause_state','deployment_state','verification_state','observation_window','close_conditions','owner','last_verified_at']:
   if k in first:row[k]=first[k]
 records.append(row)
catalog={'schema_version':1,'baseline_code_ref':head,'observed_at':now,'scope':'跨清单目录索引/离线预览数据；不是实时监控。record的evidence_status只描述最强一层来源，具体字段以observations各自证据为准。health统一unknown不自动聚合为健康。','coverage':{'source_files':srcfiles,'source_record_total':sum(f['records'] for f in srcfiles),'unique_ids':len(records),'evidence_truncation':'catalog每观察最多展示6条证据/12候选标签，完整数据在源清单。'},'records':records}

repo=source_data[inv/'repository_tasks.json'];cservices={r['runtime']['Id']:r for r in cloud['records'] if r['id'].startswith('cloud-service:')};ctimers={r['runtime']['Id']:r for r in cloud['records'] if r['id'].startswith('cloud-timer:')}
recon=[]
for r in repo['records']:
 if r.get('scheduler')!='systemd':continue
 u=r.get('unit');t=r.get('timer');s=cservices.get(u);rt=ctimers.get(t);decl=r.get('schedule',{}).get('OnCalendar',[]);raw=rt.get('runtime',{}).get('TimersCalendar','') if rt else '';actual=rt.get('calendar_expressions',[]) if rt else []
 if not actual:
  rawlist=raw if isinstance(raw,list) else [raw];actual=[z for value in rawlist for z in re.findall(r'OnCalendar=(.*?)\s*;\s*next_elapse=',value)]
 observed_paths=s.get('entrypoint',{}).get('script_paths',[]) if s else [];exp=r.get('entrypoint',[]);exp=exp if isinstance(exp,list) else []
 expbases=sorted({Path(x).name for x in exp if isinstance(x,str) and re.search(r'\.(sh|py|js)$',x)});obsbases=sorted({Path(x).name for x in observed_paths})
 def normcal(value):
  value=' '.join(value.split())
  if re.fullmatch(r'[A-Za-z.,]+ \d{1,2}:\d{2}:\d{2}',value):value=value.rsplit(' ',1)[0]+' *-*-* '+value.rsplit(' ',1)[1]
  return value
 calendar='same_literal' if decl and actual and sorted(decl)==sorted(actual) else 'same_after_explicit_wildcard_normalization' if decl and actual and sorted(map(normcal,decl))==sorted(map(normcal,actual)) else 'different_literal_needs_review' if decl and actual else 'not_compared'
 if rt and rt.get('calendar_observation_partial'):calendar='not_compared_partial_observation'
 entry='same_script_basename' if expbases and set(expbases).issubset(obsbases) else 'different_or_unresolved' if expbases and obsbases else 'not_compared'
 recon.append({'source_id':r['id'],'service_id':s['id'] if s else None,'timer_id':rt['id'] if rt else None,'unit':u,'timer':t,'presence':'matched_by_exact_unit_names' if s and rt else 'not_observed_in_scoped_snapshot','declared_OnCalendar':decl,'observed_OnCalendar':actual,'calendar_comparison':calendar,'declared_script_basenames':expbases,'observed_script_basenames':obsbases,'entrypoint_comparison':entry,'scope':'名称与字面表达式/脚本名对照；参数、全部timeout/锁/日历门控和业务结果未全量对齐。','observed_at':rt.get('observed_at') if rt else None})
matched={x['service_id'] for x in recon}|{x['timer_id'] for x in recon}; runtime_unmatched=[{'id':r['id'],'name':r['name'],'ownership':r.get('ownership','not_matched_in_source_tasks'),'note':'未匹配不等于异常或应删除。'} for r in cloud['records'] if r['kind'] in ['task','service'] and r['id'] not in matched]
rr={'reconciliation_version':1,'baseline_code_ref':head,'generated_at':now,'scope':'cloud systemd source declarations vs sampled runtime names, calendar literals and sanitized script basenames only; local/cron/CI coverage separately documented','comparisons':recon,'runtime_unmatched':runtime_unmatched,'summary':{'declared_systemd_tasks':len(recon),'matched_names':sum(x['presence']=='matched_by_exact_unit_names' for x in recon),'calendar_comparison':dict(Counter(x['calendar_comparison'] for x in recon)),'entrypoint_comparison':dict(Counter(x['entrypoint_comparison'] for x in recon)),'runtime_unmatched_count':len(runtime_unmatched)},'limitations':['同名不证明全部参数、锁、timeout、交易日或结果一致','schedule字面差异必须人工检查语义与时区后才认定漂移','非trade归属cron只保留外围记录，不计项目运行健康','本轮取证快照不代替持续监控']}

index={r['id']:r for r in catalog['records']}
for match in recon:
 ids=[x for x in [match['source_id'],match['service_id'],match['timer_id']] if x in index]
 for entity in ids:index[entity]['related_entity_ids']=sorted(set(index[entity].get('related_entity_ids',[])+[x for x in ids if x!=entity]))

# Template renders a generated projection of the same source records, no network/API.
template=(base/'templates/dashboard.html').read_text();embedded=json.dumps(catalog,ensure_ascii=False,separators=(',',':')).replace('<',chr(92)+'u003c').replace('>',chr(92)+'u003e').replace('&',chr(92)+'u0026')
html=template.replace('__CATALOG_JSON__',embedded)
outputs={inv/'catalog.json':json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',inv/'reconciliation.json':json.dumps(rr,ensure_ascii=False,indent=2)+'\n',base/'dashboard-preview.html':html}
parser=argparse.ArgumentParser(description='Offline docs-only catalogue builder; never calls business modules/network/DB.')
g=parser.add_mutually_exclusive_group();g.add_argument('--write',action='store_true',help='Atomically regenerate only catalogue/reconciliation/offline HTML');g.add_argument('--check',action='store_true',help='Check reproducibility without writes (default)');args=parser.parse_args()
if inventory_paths()!=source_inputs or any(hashlib.sha256(p.read_bytes()).hexdigest()!=digest for p,digest in input_digests.items()):
 raise RuntimeError('Source inventory changed during generation; retry from a stable snapshot.')
drift=[str(p.relative_to(base)) for p,text in outputs.items() if not p.exists() or p.read_text()!=text]
if args.write:
 for p,text in outputs.items():
  with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=p.parent,prefix='.kb-',suffix='.tmp',delete=False) as f:
   tmp=Path(f.name);f.write(text);f.flush();os.fsync(f.fileno())
  os.chmod(tmp,0o644);os.replace(tmp,p)
print(json.dumps({'mode':'write' if args.write else 'check','source_inventories':len(srcfiles),'source_records':catalog['coverage']['source_record_total'],'catalog_ids':len(records),'counts_by_kind':dict(Counter(r['kind'] for r in records)),'reconciliation':rr['summary'],'derived_files_different_before_run':drift},ensure_ascii=False))
if drift and not args.write:sys.exit(1)
