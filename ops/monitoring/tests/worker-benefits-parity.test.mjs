import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {compareBenefits} from '../../../worker/ops_benefits.js';
function pair(){
 const dates=Array.from({length:21},(_,i)=>new Date(Date.UTC(2026,9,1+i)).toISOString().slice(0,10));
 const rollout={effective_at:'2026-10-11T03:00:00Z',evidence_ref:'synthetic-rollout',before_code_sha:'a'.repeat(40),after_code_sha:'b'.repeat(40),before_config_sha256:'c'.repeat(64),after_config_sha256:'d'.repeat(64)};
 const calendar={trading_days:dates,verified_complete:true,source_ref:'synthetic-calendar',timezone:'Asia/Shanghai',sha256:createHash('sha256').update(JSON.stringify(dates)).digest('hex')};
 const p={};for(const side of ['before','after']){const code_sha=rollout[side+'_code_sha'];p[side]={schema_version:'delivery-benefits-v1',measurement_kind:'synthetic',contract_id:'contract',metric_id:'delivery',caliber_id:'v1',population_id:'single-chain',schedule_id:'s1',exclusion_policy_id:'none',normalizer_sha:'1'.repeat(40),code_sha,config_sha256:rollout[side+'_config_sha256'],rollout,calendar,as_of:'2026-11-07T00:00:00Z',confounders:[],days:(side==='before'?dates.slice(0,10):dates.slice(11)).map((date,i)=>({date,inventory_complete:true,inventory_ref:'synthetic-inventory',outcome_ref:'synthetic-outcome',code_sha,caliber_id:'v1',deadline_at:date+'T08:00:00Z',closed:true,scheduled:i+1,success:i,failure:0,unknown:1,excluded:[]}))};}
 return p;
}
function python(p,allow){const script='import json,sys\nfrom ops.monitoring.compare_benefits import compare\np=json.load(sys.stdin)\nprint(json.dumps(compare(p["before"],p["after"],'+(allow?'True':'False')+')))';const r=spawnSync('python3',['-c',script],{cwd:new URL('../../../',import.meta.url),input:JSON.stringify(p),encoding:'utf8'});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout);}
const controls=[
 ['synthetic default refusal',()=>{},false],['explicit synthetic unequal denominators',()=>{},true],
 ['unknown inventory',p=>{Object.assign(p.after.days[0],{scheduled:null,success:null,failure:null,unknown:null,inventory_complete:false});},true],
 ['all unknown',p=>{for(const d of p.after.days){d.success=0;d.unknown=d.scheduled;}},true],
 ['mixed version',p=>{p.after.days[0].code_sha='9'.repeat(40);},true],
 ['calendar hash',p=>{p.after.calendar={...p.after.calendar,sha256:'e'.repeat(64)};},true],
 ['rollout date excluded',p=>{p.after.days[0].date='2026-10-11';},true],
 ['unclosed deadline',p=>{p.after.days[0].closed=false;},true],
 ['unapproved exclusion',p=>{p.after.days[0].excluded=[{count:1,reason:'random',evidence_ref:'fixture',approved_at:'2026-10-01T00:00:00Z'}];p.after.days[0].unknown=0;},true],
 ['confounders',p=>{p.before.confounders=['load changed'];p.after.runtime_id='runtime2';p.before.runtime_id='runtime1';},true],
 ['manual measured',p=>{for(const s of ['before','after'])p[s].manual_work={minutes:s==='before'?20:10,complete:true,evidence_ref:'fixture',eligible_batches:55,scope_id:'batchwork'};},true],
 ['bad rows',p=>{p.after.days=[null,3];},true],
];
for(const [name,mutate,allow]of controls)test('Python/JS complete result parity: '+name,async()=>{const p=pair();mutate(p);assert.deepEqual(await compareBenefits(p.before,p.after,allow),python(p,allow));});
