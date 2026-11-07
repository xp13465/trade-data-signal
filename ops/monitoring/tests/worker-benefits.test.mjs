import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync,readdirSync } from 'node:fs';
import { Miniflare,convertV4MiniflareOptions } from 'miniflare';
import handler,{opsScheduled} from '../../../worker/ops.js';

async function fixture(migrate=true){
 const mf=new Miniflare(convertV4MiniflareOptions({modules:true,compatibilityDate:'2026-11-07',script:'export default {fetch(){return new Response("test")}}',d1Databases:{OPS_DB:'benefits-isolated'}}));
 const db=await mf.getD1Database('OPS_DB');let unit='',trigger=false;
 const dir=new URL('../migrations/',import.meta.url);
 for(const file of readdirSync(dir).filter(f=>f.endsWith('.sql')&&(migrate||!f.startsWith('0004'))).sort())for(const raw of readFileSync(new URL(file,dir),'utf8').split('\n')){
  const line=raw.trim();if(!line||line.startsWith('--'))continue;if(line.startsWith('CREATE TRIGGER'))trigger=true;unit+=raw+'\n';if((!trigger&&line.endsWith(';'))||(trigger&&line==='END;')){await db.prepare(unit).run();unit='';trigger=false;}
 }
 const env={OPS_DB:db,OPS_ADMIN_TOKEN:'synthetic-admin',OPS_INGEST_TOKEN:'synthetic-ingest',OPS_ALERT_SCOPE:'all',OPS_ALERT_ENABLED:'false',OPS_BENEFITS_ENABLED:'true'};
 const call=async(path,body,role=body?'ingest':'admin',headers={})=>{
  const r=await handler(new Request('https://test.invalid/api/ops'+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json',...(role==='ingest'?{Authorization:'Bearer synthetic-ingest'}:{'X-Ops-Admin-Token':'synthetic-admin'}),...headers},body:body?JSON.stringify(body):undefined}),env,{});return {status:r.status,body:await r.json()};
 };
 const now=Date.now(),at=new Date(now).toISOString(),session=new Date(now-86400000).toISOString().slice(0,10);
 const base={record_kind:'delivery_v1',contract_id:'test-v1',chain_id:'market_signal_freeze_plan',session_date:session,batch_id:'market_signal_freeze_plan:'+session,measurement_kind:'real',deadline_at:session+'T15:00:00Z',expected:1,success:0,failure:1,unknown:0,code_sha:'a'.repeat(40),config_sha:'b'.repeat(64),calendar_sha:'c'.repeat(64),proof_sha:'d'.repeat(64),evaluated_at:at,inventory_complete:true,reason:'verified_failure',strength:'verified',source_at:new Date(now-20000).toISOString()};
 const snap=(e=base,status=e.failure?'critical':e.strength==='verified'?'ok':'unknown')=>({schema_version:1,snapshot_id:crypto.randomUUID(),collector_id:'benefit-test',collected_at:new Date().toISOString(),code_ref:'unknown',duration_ms:1,coverage:{counts:{checks:1},limitations:['Synthetic test only']},checks:[{id:'benefit:'+e.chain_id+':'+e.session_date,name:'Delivery test',category:'monitor',status,observed_at:new Date().toISOString(),summary:'Synthetic only',evidence:e}]});
 return{mf,db,env,call,base,snap};
}
test('D1: null inventory retained; source clock, idempotence and terminal evidence survive unknown/replay/cron',async()=>{
 const f=await fixture();try{
  const unknown={...f.base,contract_id:null,expected:null,success:null,failure:null,unknown:null,inventory_complete:false,strength:'unknown',source_at:null,deadline_at:null,proof_sha:'e'.repeat(64)};
  assert.equal((await f.call('/ingest',f.snap(unknown))).status,200);
  let view=(await f.call('/benefits')).body;assert.equal(view.records.length,1);assert.equal(view.records[0].expected,null);assert.equal(view.status,'not_ready');
  const partial={...unknown,expected:2,success:0,failure:1,unknown:1,inventory_complete:true,strength:'partial',proof_sha:'a'.repeat(64)};
  await f.call('/ingest',f.snap(partial));assert.equal((await f.call('/benefits')).body.records[0].failure,1);
  await f.call('/ingest',f.snap({...unknown,proof_sha:'b'.repeat(64)}));assert.equal((await f.call('/benefits')).body.records[0].strength,'partial');
  f.env.OPS_ALERT_ENABLED='true';f.env.OPS_ALERT_WEBHOOK='https://open.feishu.cn/open-apis/bot/v2/hook/synthetic-000000000000000';
  const s=f.snap();assert.equal((await f.call('/ingest',s)).status,200);assert.equal((await f.call('/ingest',s)).status,200);
  assert.equal((await f.call('/benefits')).body.records[0].failure,1);
  assert.equal((await f.call('/ingest',f.snap({...f.base,evaluated_at:new Date().toISOString()}))).status,200);
  assert.equal((await f.call('/benefits/audit')).body.records.length,4);
  await f.call('/ingest',f.snap({...unknown,proof_sha:'f'.repeat(64)}));
  await f.call('/ingest',f.snap({...f.base,success:1,failure:0,proof_sha:'1'.repeat(64),source_at:new Date(Date.parse(f.base.source_at)-1000).toISOString()}));
  await f.call('/ingest',f.snap({...f.base,success:1,failure:0,proof_sha:'2'.repeat(64),code_sha:'9'.repeat(40),source_at:new Date(Date.parse(f.base.source_at)+1000).toISOString()}));
  assert.equal((await f.call('/benefits')).body.records[0].failure,1);
  assert.equal((await f.call('/events')).body.events.filter(e=>e.check_id.startsWith('benefit:')&&e.kind==='recovery').length,0);
  assert.equal((await f.call('/state')).body.latest.checks[0].problem_open,true);
  const eventRows=(await f.call('/events')).body.events.filter(e=>e.check_id.startsWith('benefit:')&&['alert','recovery'].includes(e.kind));
  assert.ok(eventRows.length);assert.ok(eventRows.every(e=>e.delivery_status==='suppressed'&&e.last_error==='measurement_not_paging_owner'));
  await f.call('/ingest',f.snap({...f.base,success:1,failure:0,proof_sha:'3'.repeat(64),source_at:new Date(Date.parse(f.base.source_at)+2000).toISOString()}));
  assert.equal((await f.call('/benefits')).body.records[0].success,1);
  assert.equal((await f.call('/benefits')).body.records[0].evidence_conflict,true);
  assert.equal((await f.call('/state')).body.latest.checks[0].status,'critical');
  const backup=await f.call('/export');assert.equal(backup.status,200);assert.ok(backup.body.benefit_audit.length>=4);
  const nativeFetch=globalThis.fetch;let sends=0;globalThis.fetch=async()=>{sends++;throw new Error('Network forbidden in synthetic test');};
  try { await opsScheduled({},f.env,{}); } finally { globalThis.fetch=nativeFetch; }
  assert.equal(sends,0);assert.equal((await f.call('/benefits')).body.records[0].success,1);
  assert.equal((await f.call('/benefits',null,'ingest')).status,403);
  const study={expected_revision:0,study_id:'test',chain_id:'market_signal_freeze_plan',first_sample_proof_sha:'1'.repeat(64),before:{days:[],rollout:{effective_at:'2026-10-20T00:00:00Z'},calendar:{trading_days:[]}},after:{days:[],rollout:{effective_at:'2026-10-20T00:00:00Z'},calendar:{trading_days:[]}}};
  assert.equal((await f.call('/benefits/studies',study,'admin',{'X-Ops-Intent':'update'})).status,403);
  assert.equal((await f.call('/benefits/studies',study,'admin',{'X-Ops-Intent':'update',Origin:'https://else.invalid'})).status,403);
  const headers={'X-Ops-Intent':'update',Origin:'https://test.invalid'};
  const simultaneous=await Promise.all([f.call('/benefits/studies',study,'admin',headers),f.call('/benefits/studies',study,'admin',headers)]);
  assert.deepEqual(simultaneous.map(x=>x.status).sort(),[200,409]);
  assert.equal((await f.call('/benefits/studies',{...study,expected_revision:1},'admin',headers)).body.strength,'attested');
  assert.equal((await f.call('/benefits/studies',{...study,expected_revision:1,first_sample_proof_sha:'2'.repeat(64)},'admin',headers)).status,409);
 }finally{await f.mf.dispose();}
});
test('disabled or unmigrated and broken optional module storage preserve original ingest and cron',async()=>{
 for(const mode of ['disabled','unmigrated','broken']){
  const f=await fixture(mode!=='unmigrated');try{
   if(mode==='disabled')f.env.OPS_BENEFITS_ENABLED='false';
   if(mode==='broken')await f.db.prepare('DROP TABLE ops_benefit_current').run();
   assert.equal((await f.call('/ingest',f.snap())).status,200,mode);
   assert.equal((await f.call('/state')).status,200,mode);
   await opsScheduled({},f.env,{});
   if(mode!=='broken')assert.equal((await f.call('/benefits')).body.configured,false);
  }finally{await f.mf.dispose();}
 }
});

test('D1 complete 20-session comparison, immutable attested import, synthetic refusal and 400-day retention',async()=>{
 const f=await fixture();try{
  const dates=Array.from({length:21},(_,i)=>new Date(Date.UTC(2026,9,1+i)).toISOString().slice(0,10));
  const digest=async text=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text))),x=>x.toString(16).padStart(2,'0')).join('');
  const calendar={trading_days:dates,verified_complete:true,source_ref:'synthetic-test-calendar',timezone:'Asia/Shanghai',sha256:await digest(JSON.stringify(dates))};
  const rollout={effective_at:'2026-10-11T03:00:00Z',evidence_ref:'synthetic-test-rollout',before_code_sha:'a'.repeat(40),after_code_sha:'f'.repeat(40),before_config_sha256:'b'.repeat(64),after_config_sha256:'e'.repeat(64)};
  const study={expected_revision:0,study_id:'local-fixture-real-path',chain_id:f.base.chain_id,first_sample_proof_sha:await digest(dates[11])};
  for(const side of ['before','after'])study[side]={schema_version:'delivery-benefits-v1',measurement_kind:'real',contract_id:'test-v1',metric_id:'delivery',caliber_id:'v1',population_id:'onechain',schedule_id:'test',exclusion_policy_id:'none',normalizer_sha:'1'.repeat(40),code_sha:rollout[side+'_code_sha'],config_sha256:rollout[side+'_config_sha256'],rollout,calendar,as_of:'2026-11-07T00:00:00Z',confounders:[],days:[]};
  const headers={'X-Ops-Intent':'update',Origin:'https://test.invalid'};
  const register=await f.call('/benefits/studies',study,'admin',headers);assert.equal(register.status,200,JSON.stringify(register.body));
  const declaration={study_id:study.study_id,expected_revision:1,import_id:'attested-test',before:{...study.before,days:[]},after:{...study.after,days:[]}};
  assert.equal((await f.call('/benefits/import',declaration,'admin',headers)).body.strength,'attested');
  assert.equal((await f.call('/benefits')).body.status,'not_ready');
  assert.equal((await f.call('/benefits/import',declaration,'admin',headers)).body.duplicate,true);
  assert.equal((await f.call('/benefits/import',{...declaration,before:{...declaration.before,days:[{date:dates[0]}]}},'admin',headers)).status,409);
  for(const [i,d]of dates.entries()){
   if(i===10)continue;const side=i<10?'before':'after',n=(i%10)+1;
   const evidence={...f.base,session_date:d,batch_id:f.base.chain_id+':'+d,code_sha:study[side].code_sha,config_sha:study[side].config_sha256,calendar_sha:calendar.sha256,proof_sha:await digest(d),source_at:d+'T08:00:00Z',deadline_at:d+'T09:00:00Z',expected:n,success:n-1,failure:1,unknown:0};
   assert.equal((await f.call('/ingest',f.snap(evidence))).status,200);
  }
  let v=(await f.call('/benefits')).body;assert.equal(v.status,'ready');assert.equal(v.real_benefit_claim,false);assert.equal(v.studies[0].comparison.attribution,'not_established');
  assert.equal(v.studies[0].comparison.before.raw_totals.denominator,55);
  assert.equal(v.studies[0].comparison.before.rates.success_lower,45/55);
  assert.equal(v.studies[0].imports[0].strength,'attested');
  const synthetic={...study,study_id:'synthetic-must-not-green',before:{...study.before,measurement_kind:'synthetic'},after:{...study.after,measurement_kind:'synthetic'}};
  assert.equal((await f.call('/benefits/studies',synthetic,'admin',headers)).status,200);
  v=(await f.call('/benefits')).body;assert.equal(v.studies.find(s=>s.study_id===synthetic.study_id).comparison.status,'not_ready');
  const realNow=Date.now;Date.now=()=>realNow()+401*86400000;
  try{await opsScheduled({},f.env,{});}finally{Date.now=realNow;}
  assert.equal((await f.call('/benefits')).body.records.length,20);
  const exportValue=(await f.call('/export')).body;assert.equal(exportValue.benefit_audit.length,20);assert.equal(exportValue.benefit_imports.length,1);
 }finally{await f.mf.dispose();}
});

test('D1 conflicts never go green in either partial/verified order or equal-source conflicting verified failure',async()=>{
 for(const order of ['partial-first','success-first','equal-source']){
  const f=await fixture();try{
   const success={...f.base,expected:2,success:2,failure:0,unknown:0};
   const partial={...f.base,expected:2,success:0,failure:1,unknown:1,strength:'partial',source_at:null,proof_sha:'e'.repeat(64)};
   if(order==='partial-first'){await f.call('/ingest',f.snap(partial,'unknown'));await f.call('/ingest',f.snap(success));}
   else{await f.call('/ingest',f.snap(success));await f.call('/ingest',f.snap(order==='equal-source'?{...f.base,proof_sha:'f'.repeat(64)}:partial,'unknown'));}
   const r=(await f.call('/benefits')).body.records[0];assert.equal(r.evidence_conflict,true,order);assert.equal(r.conflict_evidence.failure,1);assert.equal(r.success,2,'original historical fact retained');
   assert.equal((await f.call('/state')).body.latest.checks[0].status,'critical',order);
   if(order==='partial-first'){
    for(let i=0;i<67;i++)await f.call('/ingest',f.snap({...partial,expected:null,success:null,failure:null,unknown:null,inventory_complete:false,strength:'unknown',proof_sha:i.toString(16).padStart(64,'0')}));
    assert.ok((await f.call('/benefits/audit?limit=200')).body.records.length<=64);
    assert.equal((await f.call('/benefits')).body.records[0].conflict_evidence.failure,1,'conflict survives bounded audit rotation');
   }
  }finally{await f.mf.dispose();}
 }
});

test('D1 one complete mixed-known result is valid evidence, never a conflict with itself',async()=>{
 const f=await fixture();try{
  const mixed={...f.base,expected:2,success:1,failure:1,unknown:0};
  assert.equal((await f.call('/ingest',f.snap(mixed))).status,200);
  let r=(await f.call('/benefits')).body.records[0];assert.equal(r.evidence_conflict,false);assert.equal(r.success,1);assert.equal(r.failure,1);
  await f.call('/ingest',f.snap({...mixed,strength:'partial',source_at:null,proof_sha:'f'.repeat(64)}));
  r=(await f.call('/benefits')).body.records[0];assert.equal(r.evidence_conflict,false,'partial known failure already represented in complete result');
 }finally{await f.mf.dispose();}
});

test('D1 honest synthetic wire never enters real measurements or an ok ops state',async()=>{
 const f=await fixture();try{
  const e={...f.base,measurement_kind:'synthetic',success:1,failure:0};
  assert.equal((await f.call('/ingest',f.snap(e,'ok'))).status,200);
  assert.equal((await f.call('/benefits')).body.records[0].measurement_kind,'synthetic');
  assert.equal((await f.call('/benefits/audit')).body.records[0].record.measurement_kind,'synthetic');
  assert.equal((await f.call('/state')).body.latest.checks[0].status,'unknown');
  assert.equal((await f.call('/events')).body.events.filter(e=>e.check_id.startsWith('benefit:')&&e.kind==='recovery').length,0);
 }finally{await f.mf.dispose();}
});

test('D1 kind partitions identity, conflicts, pagination and prevents unknown/synthetic fresh recovery',async()=>{
 const f=await fixture();try{
  await f.call('/ingest',f.snap());
  const success={...f.base,success:1,failure:0,source_at:new Date(Date.parse(f.base.source_at)+1000).toISOString()};
  await f.call('/ingest',f.snap({...success,measurement_kind:'synthetic'},'ok'));
  const missing={...success};delete missing.measurement_kind;
  await f.call('/ingest',f.snap(missing,'ok'));
  const legacy={...missing,attempt_id:'legacy-private-attempt'};await f.call('/ingest',f.snap(legacy,'ok'));
  let v=(await f.call('/benefits')).body;
  assert.deepEqual(v.records.map(r=>r.measurement_kind).sort(),['real','synthetic','unknown']);
  assert.equal(v.records.find(r=>r.measurement_kind==='real').failure,1);
  assert.equal(v.records.find(r=>r.measurement_kind==='real').evidence_conflict,false);
  const state=(await f.call('/state')).body;assert.equal(state.latest.checks[0].status,'critical');assert.equal(state.latest.checks[0].problem_open,true);
  assert.equal(state.latest.checks[0].evidence.measurement_kind,'real');
  assert.equal((await f.call('/events')).body.events.filter(e=>e.check_id.startsWith('benefit:')&&e.kind==='recovery').length,0);
  const audit=(await f.call('/benefits/audit')).body.records;assert.equal(audit.length,3);assert.equal(new Set(audit.map(a=>a.receipt_key)).size,3);
  assert.ok(audit.every(a=>a.measurement_kind===a.record.measurement_kind&&Object.keys(a.record).length===20&&!('attempt_id'in a.record)));
  let cursor='',kinds=[];do{const p=(await f.call('/benefits/records?limit=1'+(cursor?'&after='+encodeURIComponent(cursor):''))).body;kinds.push(...p.records.map(r=>r.record.measurement_kind));cursor=p.next_after;}while(cursor);
  assert.deepEqual(kinds.sort(),['real','synthetic','unknown']);
  const backup=(await f.call('/export')).body;assert.equal(backup.benefit_current.length,3);assert.equal(backup.benefit_audit.length,3);
  // Unknown/synthetic failures with the same slot must not conflict with a real success either.
  const realSuccess={...success,proof_sha:'9'.repeat(64)};await f.call('/ingest',f.snap(realSuccess));
  await f.call('/ingest',f.snap({...f.base,measurement_kind:'synthetic',proof_sha:'8'.repeat(64),source_at:new Date(Date.parse(success.source_at)+1000).toISOString()}));
  v=(await f.call('/benefits')).body;assert.equal(v.records.find(r=>r.measurement_kind==='real').evidence_conflict,false);
 }finally{await f.mf.dispose();}
});

test('D1 twenty synthetic/missing-kind sessions cannot satisfy a real study; synthetic study remains default refused',async()=>{
 const f=await fixture();try{
  const dates=Array.from({length:21},(_,i)=>new Date(Date.UTC(2026,9,1+i)).toISOString().slice(0,10));
  const digest=async text=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text))),x=>x.toString(16).padStart(2,'0')).join('');
  const calendar={trading_days:dates,verified_complete:true,source_ref:'local-kind-test-calendar',timezone:'Asia/Shanghai',sha256:await digest(JSON.stringify(dates))};
  const rollout={effective_at:'2026-10-11T03:00:00Z',evidence_ref:'local-kind-test-rollout',before_code_sha:f.base.code_sha,after_code_sha:f.base.code_sha,before_config_sha256:f.base.config_sha,after_config_sha256:f.base.config_sha};
  const study={expected_revision:0,study_id:'kind-real',chain_id:f.base.chain_id,first_sample_proof_sha:await digest(dates[11])};
  for(const side of ['before','after'])study[side]={schema_version:'delivery-benefits-v1',measurement_kind:'real',contract_id:f.base.contract_id,metric_id:'delivery',caliber_id:'v1',population_id:'onechain',schedule_id:'test',exclusion_policy_id:'none',normalizer_sha:'1'.repeat(40),code_sha:f.base.code_sha,config_sha256:f.base.config_sha,rollout,calendar,as_of:'2026-11-07T00:00:00Z',confounders:[],days:[]};
  const headers={'X-Ops-Intent':'update',Origin:'https://test.invalid'};
  assert.equal((await f.call('/benefits/studies',study,'admin',headers)).status,200);
  const synthetic={...study,study_id:'kind-synthetic',before:{...study.before,measurement_kind:'synthetic'},after:{...study.after,measurement_kind:'synthetic'}};
  assert.equal((await f.call('/benefits/studies',synthetic,'admin',headers)).status,200);
  const unconfigured={...study,study_id:'kind-unconfigured',before:{...study.before},after:{...study.after}};delete unconfigured.before.measurement_kind;delete unconfigured.after.measurement_kind;
  assert.equal((await f.call('/benefits/studies',unconfigured,'admin',headers)).status,200);
  for(const d of dates.filter((_,i)=>i!==10))for(const kind of ['synthetic',undefined]){
   const e={...f.base,measurement_kind:kind,session_date:d,batch_id:f.base.chain_id+':'+d,calendar_sha:calendar.sha256,proof_sha:await digest(d),source_at:d+'T08:00:00Z',deadline_at:d+'T09:00:00Z',success:1,failure:0};
   if(kind===undefined)delete e.measurement_kind;
   assert.equal((await f.call('/ingest',f.snap(e,'ok'))).status,200);
  }
  const v=(await f.call('/benefits')).body;assert.equal(v.status,'not_ready');assert.equal(v.records.length,40);
  const real=v.studies.find(s=>s.study_id===study.study_id);assert.ok(real.before.days.concat(real.after.days).every(d=>d.success===null&&d.inventory_complete===false));
  const demo=v.studies.find(s=>s.study_id===synthetic.study_id);assert.ok(demo.before.days.concat(demo.after.days).every(d=>d.success===1&&d.inventory_complete===true));
  assert.equal(demo.comparison.status,'not_ready');assert.ok(demo.comparison.not_ready_reasons.includes('before:synthetic_refused_default'));
  const unknown=v.studies.find(s=>s.study_id===unconfigured.study_id);assert.ok(unknown.before.days.concat(unknown.after.days).every(d=>d.success===null));
  assert.ok(v.records.every(r=>r.measurement_kind!=='real'));
 }finally{await f.mf.dispose();}
});

async function storedCounts(f,snapshotId,accepted){
 const row=await f.db.prepare('SELECT counts_json,snapshot_json FROM ops_runs WHERE snapshot_id=?').bind(snapshotId).first();
 const saved=JSON.parse(row.snapshot_json),counts={ok:0,warning:0,critical:0,unknown:0};
 for(const check of saved.checks)counts[check.status]++;
 assert.deepEqual(JSON.parse(row.counts_json),counts,'counts_json must describe the final stored checks');
 assert.equal(Object.values(counts).reduce((a,b)=>a+b,0),saved.checks.length);
 const history=(await f.call('/history?limit=200')).body.runs.find(r=>r.snapshot_id===snapshotId);
 assert.deepEqual(history.counts,counts,'history is the same stored snapshot summary');
 if(accepted)assert.deepEqual(accepted.body.counts,counts,'accepted response uses persisted counts');
 const state=(await f.call('/state')).body;
 if(state.latest.snapshot_id===snapshotId&&state.missing_checks.length===0)assert.deepEqual(state.counts,counts,'fresh current state and history agree');
 return {saved,counts};
}

test('D1 final projected snapshot, history, state and accepted counts share retained evidence',async()=>{
 const f=await fixture();try{
  const failure=f.snap();const ordinary={id:'service:unrelated',name:'Unrelated original check',category:'service',status:'warning',observed_at:failure.collected_at,summary:'Original observation',evidence:{value:'original'}};failure.checks.push(ordinary);
  let accepted=await f.call('/ingest',failure);assert.equal(accepted.status,200);await storedCounts(f,failure.snapshot_id,accepted);
  for(const e of [{...f.base,success:1,failure:0,proof_sha:'1'.repeat(64),source_at:new Date(Date.parse(f.base.source_at)-1000).toISOString()}, {...f.base,strength:'unknown',source_at:null,expected:null,success:null,failure:null,unknown:null,inventory_complete:false,proof_sha:'2'.repeat(64)}]){
   const next=f.snap(e,e.strength==='unknown'?'unknown':'ok');next.checks.push({...ordinary,observed_at:next.collected_at});
   accepted=await f.call('/ingest',next);assert.equal(accepted.status,200);
   const result=await storedCounts(f,next.snapshot_id,accepted);assert.deepEqual(result.counts,{ok:0,warning:1,critical:1,unknown:0});assert.equal(result.saved.checks[1].evidence.value,'original');
   const duplicate=await f.call('/ingest',next);assert.equal(duplicate.status,200);await storedCounts(f,next.snapshot_id,duplicate);
   const conflict=structuredClone(next);conflict.checks[1].status='ok';assert.equal((await f.call('/ingest',conflict)).status,409);await storedCounts(f,next.snapshot_id);
  }
 }finally{await f.mf.dispose();}
});

test('D1 broken optional storage fallback recounts verified ok and critical without changing ordinary checks',async()=>{
 for(const status of ['ok','critical']){
  const f=await fixture();try{
   await f.db.prepare('DROP TABLE ops_benefit_current').run();
   const e=status==='ok'?{...f.base,success:1,failure:0}:f.base;
   const s=f.snap(e,status);s.checks.push({id:'service:original',name:'Original service',category:'service',status:'ok',observed_at:s.collected_at,summary:'Original status preserved',evidence:{value:1}});
   const accepted=await f.call('/ingest',s);assert.equal(accepted.status,200);
   const {saved,counts}=await storedCounts(f,s.snapshot_id,accepted);assert.deepEqual(counts,{ok:1,warning:0,critical:0,unknown:1});assert.equal(saved.checks[1].status,'ok');
   assert.equal((await f.call('/ingest',s)).status,200);await storedCounts(f,s.snapshot_id);
   const changed=structuredClone(s);changed.checks[1].status='critical';assert.equal((await f.call('/ingest',changed)).status,409);await storedCounts(f,s.snapshot_id);
  }finally{await f.mf.dispose();}
 }
});

test('D1 documented batch limits: normal6 and bounded max250 markers preserve all evidence within individual SQL budgets',{timeout:60000},async()=>{
 for(const size of [6,250]){
  const f=await fixture();try{
   const stats={markers:size,maxSQLBytes:0,maxBoundParameters:0,batchCalls:0,directCalls:0,maxBatchStatements:0,maxBatchMs:0,maxBatchResultBytes:0};
   const native=new WeakMap();
   function wrap(statement){const result={bind(...args){stats.maxBoundParameters=Math.max(stats.maxBoundParameters,args.length);return wrap(statement.bind(...args));}};for(const method of ['first','all','run'])result[method]=(...args)=>{stats.directCalls++;return statement[method](...args);};native.set(result,statement);return result;}
   f.env.OPS_DB={prepare(sql){stats.maxSQLBytes=Math.max(stats.maxSQLBytes,Buffer.byteLength(sql));return wrap(f.db.prepare(sql));},async batch(statements){stats.batchCalls++;stats.maxBatchStatements=Math.max(stats.maxBatchStatements,statements.length);const start=performance.now(),result=await f.db.batch(statements.map(s=>native.get(s)));stats.maxBatchMs=Math.max(stats.maxBatchMs,performance.now()-start);stats.maxBatchResultBytes=Math.max(stats.maxBatchResultBytes,Buffer.byteLength(JSON.stringify(result)));return result;}};
   const s=f.snap();s.checks=[];
   for(let i=0;i<size;i++){const chain=size===6?['market_signal_freeze_plan','backtest_publish_consume','backup_isolated_restore'][i%3]:'bounded_'+i,session=size===6&&i>=3?new Date(Date.parse(f.base.session_date)-86400000).toISOString().slice(0,10):f.base.session_date;const evidence={...f.base,chain_id:chain,session_date:session,batch_id:chain+':'+session};s.checks.push({id:'benefit:'+chain+':'+session,name:'Bounded fixture',category:'monitor',status:'critical',observed_at:s.collected_at,summary:'Synthetic budget validation',evidence});}
   assert.ok(Buffer.byteLength(JSON.stringify(s))<=256*1024,'original body limit');
   const accepted=await f.call('/ingest',s);assert.equal(accepted.status,200);
   // Capture only the actual ingest invocation, not subsequent verification reads.
   const measured={...stats};assert.ok(measured.maxBoundParameters<=100);assert.ok(measured.maxSQLBytes<=100000);assert.ok(measured.maxBatchMs<30000);assert.ok(measured.maxBatchResultBytes<50*1024*1024);assert.ok(measured.batchCalls+measured.directCalls<=50);
   assert.equal((await f.db.prepare('SELECT COUNT(*) n FROM ops_benefit_current').first()).n,size,'no silent optional fallback or partial persistence');
   assert.equal((await f.db.prepare('SELECT COUNT(*) n FROM ops_benefit_audit').first()).n,size);
   await storedCounts(f,s.snapshot_id,accepted);
   console.log('D1_BATCH_BUDGET_FIXTURE '+JSON.stringify(measured));
  }finally{await f.mf.dispose();}
 }
});
