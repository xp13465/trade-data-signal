// Private delivery measurements. Never call external services or own business paging.
const DAY = 86400000;
const FIELDS = ['record_kind','contract_id','chain_id','session_date','batch_id','deadline_at','expected','success','failure','unknown','code_sha','config_sha','calendar_sha','proof_sha','evaluated_at','inventory_complete','reason','strength','source_at','measurement_kind'];
const COMPARABLE = ['contract_id','metric_id','caliber_id','population_id','schedule_id','exclusion_policy_id','normalizer_sha'];
const q = (db, sql, ...a) => a.length ? db.prepare(sql).bind(...a) : db.prepare(sql);
const obj = x => x !== null && typeof x === 'object' && !Array.isArray(x);
const integer = x => Number.isSafeInteger(x) && x >= 0;
const nonempty = x => typeof x === 'string' && !!x.trim() && !['unknown','todo','null'].includes(x.toLowerCase());
const sha = (x, n) => typeof x === 'string' && new RegExp(`^[a-f0-9]{${n}}$`).test(x);
const date = x => typeof x === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(x) && Number.isFinite(Date.parse(x)) && new Date(x).toISOString().slice(0,10) === x;
const time = x => typeof x === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/.test(x) && Number.isFinite(Date.parse(x)) ? Date.parse(x) : NaN;
const localDate = x => Number.isFinite(time(x)) ? new Date(time(x) + 8*3600000).toISOString().slice(0,10) : null;
const canonical = x => Array.isArray(x) ? '['+x.map(canonical).join(',')+']' : obj(x) ? '{'+Object.keys(x).sort().map(k=>JSON.stringify(k)+':'+canonical(x[k])).join(',')+'}' : JSON.stringify(x);
function storedRecord(row) {
  const e=JSON.parse(row.record_json);
  const kind=['real','synthetic','unknown'].includes(row.measurement_kind)&&e.measurement_kind===row.measurement_kind?row.measurement_kind:'unknown';
  return {...e,measurement_kind:kind};
}
async function hash(x) { return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(x))),b=>b.toString(16).padStart(2,'0')).join(''); }
export async function benefitsConfigured(db, env) {
  if (env.OPS_BENEFITS_ENABLED !== 'true') return false;
  try { return !!await q(db,"SELECT name FROM sqlite_master WHERE type='table' AND name='ops_benefit_imports'").first(); } catch { return false; }
}
function record(e, check, now) {
  if (!obj(e) || Object.keys(e).some(k=>!FIELDS.includes(k)) || e.record_kind !== 'delivery_v1' ||
      !/^[a-z0-9_-]{1,48}$/.test(e.chain_id) || !date(e.session_date) || check.id !== `benefit:${e.chain_id}:${e.session_date}` ||
      !['verified','partial','unknown'].includes(e.strength) || !nonempty(e.batch_id) ||
      !Number.isFinite(time(e.evaluated_at)) || time(e.evaluated_at)>now+120000 || time(e.evaluated_at)>time(check.observed_at)+120000 ||
      (e.deadline_at!==null && (!Number.isFinite(time(e.deadline_at)) || localDate(e.deadline_at)<e.session_date)) ||
      (e.proof_sha!==null && !sha(e.proof_sha,64)) || ![true,false].includes(e.inventory_complete)) return null;
  const counts = ['expected','success','failure','unknown'].map(k=>e[k]);
  if (!counts.every(x=>x===null || integer(x))) return null;
  if (e.inventory_complete && (!counts.every(integer) || e.success+e.failure+e.unknown!==e.expected)) return null;
  if (e.strength==='verified' && (!nonempty(e.contract_id) || !Number.isFinite(time(e.deadline_at)) || !sha(e.proof_sha,64) || !Number.isFinite(time(e.source_at)) || time(e.source_at)>time(e.evaluated_at) || !e.inventory_complete || !sha(e.code_sha,40) || !sha(e.config_sha,64) || !sha(e.calendar_sha,64))) return null;
  if (e.strength!=='verified' && e.source_at!==null) return null;
  const kind=['real','synthetic','unknown'].includes(e.measurement_kind)?e.measurement_kind:'unknown';
  return Object.fromEntries(FIELDS.map(k=>[k,k==='measurement_kind'?kind:e[k] ?? null]));
}
export async function benefitStatements(db, env, snapshot, now) {
  if (!await benefitsConfigured(db,env)) return [];
  const statements=[];
  for (const c of snapshot.checks) {
    if (c.evidence?.record_kind!=='delivery_v1') continue;
    const e=record(c.evidence,c,now); if (!e) continue; // Malformed benefit evidence cannot break original ingest.
    // Kind is part of both immutable identity and content. A proof in a different
    // population can neither deduplicate nor replace a real delivery fact.
    const content=await hash(canonical({...e,evaluated_at:null}));
    const key=await hash(canonical([e.chain_id,e.session_date,e.batch_id,e.measurement_kind,e.proof_sha??content]));
    const json=JSON.stringify(e), clock=e.source_at?time(e.source_at):0;
    statements.push(q(db,`DELETE FROM ops_benefit_audit WHERE receipt_key IN (
      SELECT a.receipt_key FROM ops_benefit_audit a WHERE chain_id=? AND session_date=? AND batch_id=? AND measurement_kind=?
      AND receipt_key NOT IN(SELECT receipt_key FROM ops_benefit_current)
      ORDER BY received_ms DESC,receipt_key DESC LIMIT -1 OFFSET 62)`,e.chain_id,e.session_date,e.batch_id,e.measurement_kind));
    statements.push(q(db,`INSERT INTO ops_benefit_audit(receipt_key,content_hash,chain_id,session_date,batch_id,measurement_kind,evaluated_ms,received_ms,source,snapshot_id,record_json)
      SELECT ?,?,?,?,?,?,?,?,?,?,?
      WHERE EXISTS(SELECT 1 FROM ops_benefit_current WHERE chain_id=? AND session_date=? AND batch_id=? AND measurement_kind=?)
      OR (SELECT COUNT(*) FROM ops_benefit_current WHERE chain_id=? AND session_date=? AND measurement_kind=?)<100
      ON CONFLICT(receipt_key) DO NOTHING`,key,content,e.chain_id,e.session_date,e.batch_id,e.measurement_kind,clock,now,'collector',snapshot.snapshot_id,json,e.chain_id,e.session_date,e.batch_id,e.measurement_kind,e.chain_id,e.session_date,e.measurement_kind));
    statements.push(q(db,`INSERT INTO ops_benefit_current(chain_id,session_date,batch_id,measurement_kind,receipt_key,evaluated_ms,strength,code_sha,config_sha,calendar_sha,record_json) SELECT ?,?,?,?,?,?,?,?,?,?,?
      FROM ops_benefit_audit WHERE receipt_key=? AND content_hash=?
      ON CONFLICT(chain_id,session_date,batch_id,measurement_kind) DO UPDATE SET receipt_key=excluded.receipt_key,
      evaluated_ms=excluded.evaluated_ms,strength=excluded.strength,record_json=excluded.record_json,
      code_sha=excluded.code_sha,config_sha=excluded.config_sha,calendar_sha=excluded.calendar_sha
      WHERE (excluded.evaluated_ms>ops_benefit_current.evaluated_ms OR
        (ops_benefit_current.strength='unknown' AND excluded.strength='partial') OR
        (ops_benefit_current.strength='partial' AND excluded.strength='partial'
          AND COALESCE(json_extract(ops_benefit_current.record_json,'$.failure'),0)=0
          AND json_extract(excluded.record_json,'$.failure')>0))
      AND (ops_benefit_current.strength<>'verified' OR json_extract(excluded.record_json,'$.contract_id')=json_extract(ops_benefit_current.record_json,'$.contract_id'))
      AND (ops_benefit_current.strength<>'verified' OR json_extract(excluded.record_json,'$.deadline_at')=json_extract(ops_benefit_current.record_json,'$.deadline_at'))
      AND (ops_benefit_current.strength<>'verified' OR (excluded.strength='verified'
        AND excluded.code_sha=ops_benefit_current.code_sha AND excluded.config_sha=ops_benefit_current.config_sha
        AND excluded.calendar_sha=ops_benefit_current.calendar_sha))`,e.chain_id,e.session_date,e.batch_id,e.measurement_kind,key,clock,e.strength,e.code_sha,e.config_sha,e.calendar_sha,json,key,content));
    // Keep conflicts within their declared population. Unknown/synthetic failures
    // cannot corrupt a real study, and neither can their success conceal a real failure.
    statements.push(q(db,`UPDATE ops_benefit_current SET conflict_json=COALESCE(conflict_json,(
      SELECT a.record_json FROM ops_benefit_audit a WHERE a.chain_id=ops_benefit_current.chain_id
      AND a.session_date=ops_benefit_current.session_date AND a.batch_id=ops_benefit_current.batch_id
      AND a.measurement_kind=ops_benefit_current.measurement_kind
      AND a.receipt_key<>ops_benefit_current.receipt_key
      AND json_extract(a.record_json,'$.failure')>COALESCE(json_extract(ops_benefit_current.record_json,'$.failure'),0) AND (json_extract(a.record_json,'$.strength')='partial'
        OR (json_extract(a.record_json,'$.strength')='verified' AND a.evaluated_ms>=ops_benefit_current.evaluated_ms))
      ORDER BY a.received_ms DESC,a.receipt_key DESC LIMIT 1))
      WHERE chain_id=? AND session_date=? AND batch_id=? AND measurement_kind=? AND strength='verified'`,e.chain_id,e.session_date,e.batch_id,e.measurement_kind));
  }
  // Even a malformed/legacy benefit check must use retained real state when
  // configured; absence of a newly accepted record must not bypass the guard.
  if (!statements.length && snapshot.checks.some(c=>c.id.startsWith('benefit:'))) statements.push(q(db,'SELECT 1 FROM ops_benefit_current LIMIT 0'));
  return statements;
}
export async function benefitsRetain(db,env,now) {
  if (!await benefitsConfigured(db,env)) return;
  // Keep at least 60 full sessions per chain plus every registered study window indefinitely.
  // Study count is bounded to 50. Current/last evidence never ages out by wall time alone.
  await db.batch([
    q(db,`DELETE FROM ops_benefit_current WHERE session_date<? AND session_date NOT IN(
      SELECT DISTINCT b.session_date FROM ops_benefit_current b WHERE b.chain_id=ops_benefit_current.chain_id AND b.measurement_kind=ops_benefit_current.measurement_kind
      ORDER BY b.session_date DESC LIMIT 60)
      AND NOT EXISTS(SELECT 1 FROM ops_benefit_studies s,json_each(s.study_json,'$.before.calendar.trading_days') d
      WHERE json_extract(s.study_json,'$.chain_id')=ops_benefit_current.chain_id AND d.value=ops_benefit_current.session_date)`,new Date(now-400*DAY).toISOString().slice(0,10)),
    q(db,`DELETE FROM ops_benefit_audit WHERE received_ms<? AND receipt_key NOT IN(SELECT receipt_key FROM ops_benefit_current)
      AND NOT EXISTS(SELECT 1 FROM ops_benefit_current c WHERE c.chain_id=ops_benefit_audit.chain_id
      AND c.session_date=ops_benefit_audit.session_date AND c.batch_id=ops_benefit_audit.batch_id AND c.measurement_kind=ops_benefit_audit.measurement_kind)`,now-400*DAY),
  ]);
}

function summarize(period,label,expected,errors) {
  const totals={scheduled:0,excluded:0,denominator:0,success:0,failure:0,unknown:0};
  let rows=period.days??[]; if(!Array.isArray(rows)){errors.push(label+':days_not_array');rows=[];}
  const observed=[];let valid=true;
  rows.forEach((row,n)=>{
    const p=`${label}.days[${n}]`;if(!obj(row)){errors.push(p+':not_object');valid=false;return;}
    const d=row.date;observed.push(d);
    if(row.inventory_complete!==true)errors.push(p+':inventory_incomplete');
    for(const k of ['inventory_ref','outcome_ref'])if(!nonempty(row[k]))errors.push(p+':'+k+'_missing');
    if(row.code_sha!==period.code_sha||!sha(row.code_sha,40))errors.push(p+':mixed_or_missing_code');
    if(row.caliber_id!==period.caliber_id||!nonempty(row.caliber_id))errors.push(p+':mixed_or_missing_caliber');
    const deadline=time(row.deadline_at),asof=time(period.as_of),rollout=time(period.rollout?.effective_at);
    if(![deadline,asof,rollout].every(Number.isFinite))errors.push(p+':invalid_time');else{
      if(deadline>asof||row.closed!==true)errors.push(p+':window_not_closed');
      if(localDate(row.deadline_at)<String(d))errors.push(p+':deadline_precedes_session');
      if(label==='before'&&deadline>=rollout)errors.push(p+':baseline_outcome_crosses_rollout');
      if(label==='after'&&deadline<=rollout)errors.push(p+':after_deadline_precedes_rollout');
    }
    if(!['scheduled','success','failure','unknown'].every(k=>integer(row[k]))){errors.push(p+':counts_require_nonnegative_integers');valid=false;return;}
    const exclusions=row.excluded??[];if(!Array.isArray(exclusions)){errors.push(p+':invalid_exclusions');valid=false;return;}
    let ex=0;for(const e of exclusions){
      if(!obj(e)||!integer(e.count)){errors.push(p+':invalid_exclusion_count');valid=false;continue;}
      ex+=e.count;
      if(!['preapproved_maintenance','duplicate_or_shadow'].includes(e.reason)||!nonempty(e.evidence_ref))errors.push(p+':unapproved_exclusion');
      if(!Number.isFinite(time(e.approved_at))||!Number.isFinite(rollout))errors.push(p+':exclusion_approval_missing');
      else if(time(e.approved_at)>=rollout)errors.push(p+':exclusion_not_predeclared');
    }
    const den=row.scheduled-ex;if(den<0||row.success+row.failure+row.unknown!==den){errors.push(p+':denominator_not_reconciled');valid=false;return;}
    totals.scheduled+=row.scheduled;totals.excluded+=ex;totals.denominator+=den;
    for(const k of ['success','failure','unknown'])totals[k]+=row[k];
  });
  if(rows.length!==10||new Set(observed.map(String)).size!==10)errors.push(label+':requires_10_unique_actual_trading_days');
  if(canonical(observed)!==canonical(expected))errors.push(label+':not_exact_nearest_10_sessions');
  if(!valid)return{raw_totals_partial:totals,rates:null,complete_counts:false};
  const n=totals.denominator,s=totals.success,f=totals.failure,u=totals.unknown;
  if(!n)errors.push(label+':zero_denominator');if(n&&s+f===0)errors.push(label+':all_outcomes_unknown');
  return{raw_totals:totals,rates:!n?null:{success_lower:s/n,success_upper:(s+u)/n,failure_lower:f/n,failure_upper:(f+u)/n,unknown_fraction:u/n,known_outcome_coverage:(s+f)/n,success_among_known:!s&&!f?null:s/(s+f)},complete_counts:true,session_dates:observed,bounds_kind:'logical_unknown_outcome_bounds_not_confidence_intervals',aggregation:'sum_success/sum_eligible_batches; never mean_daily_rates'};
}
export async function compareBenefits(before,after,allowSynthetic=false) {
  if(!obj(before)||!obj(after))throw new Error('invalid_input');
  let errors=[];const expected={},kinds=[];
  for(const [label,p] of [['before',before],['after',after]]){
    if(p.schema_version!=='delivery-benefits-v1')errors.push(label+':schema_version');
    const kind=p.measurement_kind;kinds.push(kind);
    if(!['real','synthetic'].includes(kind))errors.push(label+':measurement_kind_missing');
    if(kind==='synthetic'&&!allowSynthetic)errors.push(label+':synthetic_refused_default');
    for(const k of COMPARABLE)if(!nonempty(p[k]))errors.push(label+':'+k+'_missing');
    if(!sha(p.normalizer_sha,40))errors.push(label+':normalizer_identity_missing');
    if(!sha(p.code_sha,40)||!sha(p.config_sha256,64))errors.push(label+':code_or_config_identity_missing');
    const rollout=obj(p.rollout)?p.rollout:{};
    if(!nonempty(rollout.evidence_ref))errors.push(label+':rollout_evidence_missing');
    if(p.code_sha!==rollout[label+'_code_sha']||p.config_sha256!==rollout[label+'_config_sha256'])errors.push(label+':unpaired_version');
    const anchor=localDate(rollout.effective_at);if(!anchor)errors.push(label+':rollout_time_missing');
    const cal=obj(p.calendar)?p.calendar:{};let dates=cal.trading_days??[];
    if(!Array.isArray(dates)||!dates.every(date)||canonical(dates)!==canonical([...new Set(dates)].sort())){errors.push(label+':invalid_calendar');dates=[];}
    if(cal.verified_complete!==true||!nonempty(cal.source_ref)||cal.timezone!=='Asia/Shanghai'||await hash(JSON.stringify(dates))!==cal.sha256)errors.push(label+':actual_calendar_evidence_missing_or_hash_mismatch');
    expected[label]=label==='before'?dates.filter(d=>anchor&&d<anchor).slice(-10):dates.filter(d=>anchor&&d>anchor).slice(0,10);
    if(expected[label].length!==10)errors.push(label+':calendar_window_insufficient');
    if(!Array.isArray(p.confounders))errors.push(label+':confounders_not_listed');
  }
  for(const k of [...COMPARABLE,'rollout','calendar','measurement_kind'])if(canonical(before[k]??null)!==canonical(after[k]??null))errors.push('pair:mixed_'+k);
  const bs=summarize(before,'before',expected.before,errors),af=summarize(after,'after',expected.after,errors);
  errors=[...new Set(errors)].sort();const ready=!errors.length;const confounders=[];
  for(const [label,p] of [['before',before],['after',after]])for(const item of Array.isArray(p.confounders)?p.confounders:[])confounders.push({period:label,reported:item});
  for(const k of ['code_sha','config_sha256','upstream_id','load_profile_id','runtime_id']){
    const x=before[k],y=after[k];if(!nonempty(x)||!nonempty(y))confounders.push({factor:k,assessment:'unassessed'});else if(x!==y)confounders.push({factor:k,assessment:'changed',before:x,after:y});
  }
  let delta=null;if(ready){const lo=af.rates.success_lower-bs.rates.success_upper,hi=af.rates.success_upper-bs.rates.success_lower;delta={success_rate_change_percentage_points_bounds:[100*lo,100*hi],direction:lo>0?'increase':hi<0?'decrease':'inconclusive',attribution:'not_established',interpretation:'descriptive_only',relative_improvement_percent:null};}
  let manual={status:'unavailable',observed_minutes_difference:null,reason:'missing_complete_measured_manual_work'};
  function measured(p,s){const m=p.manual_work;return obj(m)&&s.complete_counts&&typeof m.minutes==='number'&&Number.isFinite(m.minutes)&&m.minutes>=0&&m.complete===true&&nonempty(m.evidence_ref)&&integer(m.eligible_batches)&&m.eligible_batches===s.raw_totals.denominator&&nonempty(m.scope_id)?m:null;}
  const bm=measured(before,bs),am=measured(after,af);
  if(ready&&bm&&am&&bm.scope_id===am.scope_id)manual={status:'measured_descriptive_only',observed_minutes_difference:bm.minutes-am.minutes,before_minutes:bm.minutes,after_minutes:am.minutes,before_minutes_per_batch:bm.minutes/bs.raw_totals.denominator,after_minutes_per_batch:am.minutes/af.raw_totals.denominator,difference_semantics:'raw_before_total_minus_after_total; not net savings; load and denominator may differ',attribution:'not_established'};
  return{schema_version:'delivery-benefits-v1',status:ready?'ready':'not_ready',measurement_kind:kinds.includes('synthetic')?'synthetic':canonical(kinds)==='["real","real"]'?'real':'unknown',real_benefit_claim:false,attribution:'not_established',interpretation:'descriptive_only',scope:'v1: declared Asia/Shanghai delivery sessions, one fixed metric/population; cross-market input expectations/as-of require separate contract',not_ready_reasons:errors,before:bs,after:af,descriptive_change:delta,confounders,manual_work:manual,trust_boundary:'Normalized counts/calendar/evidence refs are supplied attestations, not independently fetched or verified business truth.',window_policy:'10 nearest actual sessions strictly before/after rollout local date; whole rollout date excluded; after deadlines closed at as_of.'};
}

// All POST payloads are inline bounded safe JSON; never fetch evidence refs/files.
export async function benefitsRoute(request,db,env,auth,now,api) {
  const {fail,response,body,safeText,exactKeys,integer:checkInteger}=api;
  if(!await benefitsConfigured(db,env))return response({configured:false,status:'not_configured',not_ready_reasons:['feature_disabled_or_migration_missing'],real_benefit_claim:false});
  const url=new URL(request.url),path=url.pathname;
  function safeJSON(v,depth=0){
    if(depth>10)fail(400,'benefits_json_too_deep');
    if(typeof v==='string'){safeText(v,400);if(v!=='Asia/Shanghai'&&/[\\/]/.test(v))fail(400,'benefits_refs_must_be_safe_ids');}
    else if(Array.isArray(v)){if(v.length>400)fail(400,'benefits_array_too_large');for(const x of v)safeJSON(x,depth+1);}
    else if(obj(v)){if(Object.keys(v).length>50)fail(400,'benefits_object_too_large');for(const [k,x]of Object.entries(v)){safeText(k,64);safeJSON(x,depth+1);}}
    else if(v!==null&&typeof v!=='boolean'&&!(typeof v==='number'&&Number.isFinite(v)))fail(400,'invalid_benefits_json');
  }
  if(request.method==='POST'){
    if(request.headers.get('X-Ops-Intent')!=='update')fail(403,'update_intent_required');
    if(request.headers.get('Origin')!==url.origin)fail(403,'same_origin_required');
    const value=await body(request);safeJSON(value);
    if(path==='/api/ops/benefits/studies'){
      exactKeys(value,['expected_revision','study_id','chain_id','before','after','first_sample_proof_sha']);checkInteger(value.expected_revision);
      if(typeof value.study_id!=='string'||!/^[a-z0-9_-]{1,64}$/.test(value.study_id)||!/^[a-z0-9_-]{1,48}$/.test(value.chain_id)||!obj(value.before)||!obj(value.after)||
          !sha(value.first_sample_proof_sha,64)||!Array.isArray(value.before.days)||value.before.days.length||!Array.isArray(value.after.days)||value.after.days.length)fail(400,'invalid_study');
      // Registration fixes the complete policy/version/calendar identity. Editing requires a new ID.
      const study={study_id:value.study_id,chain_id:value.chain_id,before:value.before,after:value.after,first_sample_proof_sha:value.first_sample_proof_sha};
      if(!date(localDate(study.before.rollout?.effective_at))||study.before.calendar?.trading_days?.length>400||
        canonical(study.before.rollout)!==canonical(study.after.rollout)||canonical(study.before.calendar)!==canonical(study.after.calendar))fail(400,'invalid_study_window');
      const identity=await hash(canonical(study));
      const prior=await q(db,'SELECT * FROM ops_benefit_studies WHERE study_id=?',value.study_id).first();
      if(prior){if(prior.identity_hash!==identity||prior.revision!==value.expected_revision)fail(409,'immutable_study_or_revision_conflict');return response({study_id:value.study_id,revision:prior.revision,strength:'attested'});}
      if(value.expected_revision!==0)fail(409,'study_revision_conflict');
      const created=await q(db,`INSERT INTO ops_benefit_studies SELECT ?,1,?,?,? WHERE (SELECT COUNT(*) FROM ops_benefit_studies)<50 ON CONFLICT(study_id) DO NOTHING RETURNING revision`,value.study_id,identity,JSON.stringify(study),now).first();
      if(!created)fail(409,'study_conflict_or_capacity');
      return response({study_id:value.study_id,revision:1,strength:'attested'});
    }
    if(path==='/api/ops/benefits/import'){
      exactKeys(value,['expected_revision','study_id','import_id','before','after']);checkInteger(value.expected_revision);
      if(typeof value.import_id!=='string'||!/^[a-z0-9_-]{1,64}$/.test(value.import_id)||!obj(value.before)||!obj(value.after))fail(400,'invalid_import');
      const study=await q(db,'SELECT * FROM ops_benefit_studies WHERE study_id=?',value.study_id).first();
      if(!study||study.revision!==value.expected_revision)fail(409,'study_revision_conflict');
      const fixed=JSON.parse(study.study_json);
      for(const side of ['before','after']){
        if(!Array.isArray(value[side].days)||value[side].days.length>10)fail(400,'invalid_import_days');
        const p={...value[side],days:[]};if(canonical(p)!==canonical(fixed[side]))fail(409,'import_study_identity_conflict');
      }
      const content=await hash(canonical(value));
      const prior=await q(db,'SELECT content_hash FROM ops_benefit_imports WHERE import_id=?',value.import_id).first();
      if(prior){if(prior.content_hash!==content)fail(409,'immutable_import_conflict');return response({import_id:value.import_id,strength:'attested',duplicate:true});}
      const inserted=await q(db,`INSERT INTO ops_benefit_imports SELECT ?,?,?,?,? WHERE (SELECT COUNT(*) FROM ops_benefit_imports WHERE study_id=?)<20 ON CONFLICT(import_id) DO NOTHING RETURNING import_id`,value.import_id,value.study_id,content,now,JSON.stringify(value),value.study_id).first();
      if(!inserted)fail(409,'import_conflict_or_capacity');return response({import_id:value.import_id,strength:'attested'});
    }
    fail(404,'benefits_route_not_found');
  }
  if(request.method!=='GET')fail(405,'method_not_allowed');
  if(path==='/api/ops/benefits/records'||path==='/api/ops/benefits/audit'){
    const limit=api.boundedLimit(url),after=url.searchParams.get('after')||'';safeText(after,path.endsWith('/audit')?64:600,true);
    const audit=path.endsWith('/audit');
    const rows=(await q(db,audit?'SELECT * FROM ops_benefit_audit WHERE receipt_key>? ORDER BY receipt_key LIMIT ?':`SELECT *,chain_id||':'||session_date||':'||batch_id||':'||measurement_kind export_key FROM ops_benefit_current WHERE chain_id||':'||session_date||':'||batch_id||':'||measurement_kind>? ORDER BY export_key LIMIT ?`,after,limit).all()).results;
    return response({configured:true,records:rows.map(r=>({...r,record:storedRecord(r)})),next_after:rows.length===limit?(audit?rows.at(-1).receipt_key:rows.at(-1).export_key):null,consistency:'keyset_retained_state_not_transaction_snapshot'});
  }
  if(path!=='/api/ops/benefits')fail(404,'benefits_route_not_found');
  const studyAfter=url.searchParams.get('study_after')||'';safeText(studyAfter,64,true);
  const studyRows=(await q(db,'SELECT * FROM ops_benefit_studies WHERE study_id>? ORDER BY study_id LIMIT 6',studyAfter).all()).results;
  const studies=studyRows.slice(0,5);
  const raw=(await q(db,'SELECT * FROM ops_benefit_current ORDER BY session_date DESC,chain_id,batch_id,measurement_kind LIMIT 201').all()).results;
  const output=[];
  for(const row of studies){
    const study=JSON.parse(row.study_json),periods={};const reasons=[];let first=false;
    const anchor=localDate(study.before.rollout?.effective_at);
    for(const side of ['before','after']){
      const p={...study[side],manual_work:null,as_of:new Date(now).toISOString()};
      const dates=Array.isArray(p.calendar?.trading_days)?p.calendar.trading_days:[];
      const wanted=side==='before'?dates.filter(d=>d<anchor).slice(-10):dates.filter(d=>d>anchor).slice(0,10);
      // Query all batches for this exact bounded study window, never just the UI's recent rows.
      const records=(await q(db,`SELECT record_json,measurement_kind,conflict_json FROM ops_benefit_current WHERE chain_id=? AND measurement_kind=? AND session_date>=? AND session_date<=? ORDER BY session_date,batch_id`,study.chain_id,['real','synthetic'].includes(p.measurement_kind)?p.measurement_kind:'__unconfigured__',wanted[0]||'',wanted.at(-1)||'').all()).results.map(r=>({...storedRecord(r),evidence_conflict:!!r.conflict_json,conflict_evidence:r.conflict_json?JSON.parse(r.conflict_json):null}));
      p.days=wanted.map(d=>{
        const rs=records.filter(e=>e.session_date===d),good=rs.length>0&&rs.every(e=>['real','synthetic'].includes(p.measurement_kind)&&e.measurement_kind===p.measurement_kind&&!e.evidence_conflict&&e.strength==='verified'&&e.inventory_complete&&e.code_sha===p.code_sha&&e.config_sha===p.config_sha256&&e.calendar_sha===p.calendar.sha256&&e.contract_id===p.contract_id);
        if(!good)reasons.push(side+':'+d+(rs.some(e=>e.evidence_conflict)?':evidence_conflict':':production_evidence_missing_or_mixed'));
        const deadline=rs[0]?.deadline_at??null;
        if(rs.some(e=>e.deadline_at!==deadline))reasons.push(side+':'+d+':mixed_deadline');
        if(side==='after'&&good&&d===wanted[0]&&rs.some(e=>e.proof_sha===study.first_sample_proof_sha&&e.strength==='verified'&&time(e.evaluated_at)>=time(p.rollout?.effective_at)))first=true;
        return{date:d,scheduled:good?rs.reduce((a,e)=>a+e.expected,0):null,success:good?rs.reduce((a,e)=>a+e.success,0):null,failure:good?rs.reduce((a,e)=>a+e.failure,0):null,unknown:good?rs.reduce((a,e)=>a+e.unknown,0):null,
          inventory_complete:good,inventory_ref:good?rs[0].proof_sha:null,outcome_ref:good?rs[0].proof_sha:null,code_sha:good?p.code_sha:null,caliber_id:p.caliber_id,deadline_at:deadline,closed:!!deadline&&time(deadline)<=now,excluded:[]};
      });
      periods[side]=p;
    }
    if(!first)reasons.push('rollout_first_natural_sample_not_verified');
    const imports=(await q(db,'SELECT import_id,content_hash,received_ms,import_json FROM ops_benefit_imports WHERE study_id=? ORDER BY received_ms DESC,import_id LIMIT 20',row.study_id).all()).results.map(i=>({import_id:i.import_id,content_hash:i.content_hash,received_ms:i.received_ms,strength:'attested',declaration:JSON.parse(i.import_json)}));
    const comparison=await compareBenefits(periods.before,periods.after);
    comparison.not_ready_reasons=[...new Set([...comparison.not_ready_reasons,...reasons])].sort();
    if(comparison.not_ready_reasons.length){comparison.status='not_ready';comparison.descriptive_change=null;comparison.manual_work={status:'unavailable',observed_minutes_difference:null};}
    output.push({study_id:row.study_id,revision:row.revision,registration_strength:'attested',measurement_kind:study.before.measurement_kind===study.after.measurement_kind&&['real','synthetic'].includes(study.before.measurement_kind)?study.before.measurement_kind:'unknown',evidence_strength:first?(study.before.measurement_kind==='real'?'verified_consistency_only':'synthetic_consistency_only'):'attested',before:periods.before,after:periods.after,imports,comparison});
  }
  return response({configured:true,status:output.length&&output.every(s=>s.comparison.status==='ready')?'ready':'not_ready',real_benefit_claim:false,attribution:'not_established',not_ready_reasons:output.length?[]:['study_not_registered'],studies:output,next_study_after:studyRows.length>5?studies.at(-1).study_id:null,
    records:raw.slice(0,200).map(r=>({...storedRecord(r),evidence_conflict:!!r.conflict_json,conflict_evidence:r.conflict_json?JSON.parse(r.conflict_json):null})),records_truncated:raw.length>200,retention:{minimum_complete_sessions_per_chain:60,archive_days:400,audit_per_slot:64,studies_limit:50,imports_per_study:20},trust_boundary:'Registration and imports are attestations; verified means collector evidence consistency, not independent production activation or causal ROI.'});
}
export function benefitsExportTables(){return[['benefit_audit','ops_benefit_audit','receipt_key'],['benefit_current','ops_benefit_current',"chain_id||':'||session_date||':'||batch_id||':'||measurement_kind"],['benefit_studies','ops_benefit_studies','study_id'],['benefit_imports','ops_benefit_imports','import_id']];}

// Run after evidence selection in the SAME D1 batch. The original ops triggers must
// see the retained source-clock result too, or a resampled old success emits a false recovery.
export function benefitRunStatement(db,snapshot,hash,collected,now) {
  const json=JSON.stringify(snapshot);
  return q(db,`WITH projected(snapshot_json) AS (SELECT json_set(?,'$.checks',json((
    SELECT json_group_array(json(CASE WHEN json_extract(c.value,'$.id') LIKE 'benefit:%' THEN
      json_set(c.value,'$.status',CASE WHEN b.conflict_json IS NOT NULL THEN 'critical' WHEN b.receipt_key IS NULL THEN 'unknown'
        WHEN json_extract(b.record_json,'$.failure')>0 THEN 'critical'
        WHEN b.strength='verified' AND json_extract(b.record_json,'$.unknown')=0 THEN 'ok' ELSE 'unknown' END,
        '$.evidence',json(COALESCE(b.record_json,json_extract(c.value,'$.evidence'))),
        '$.summary',CASE WHEN b.conflict_json IS NOT NULL THEN 'Delivery evidence conflict; not comparable or recovered' ELSE 'Retained delivery evidence; measurement does not own business paging' END)
      ELSE c.value END))
    FROM json_each(?,'$.checks') c LEFT JOIN ops_benefit_current b
      ON json_extract(c.value,'$.evidence.record_kind')='delivery_v1'
      AND b.measurement_kind='real' AND json_extract(b.record_json,'$.measurement_kind')='real'
      AND b.chain_id=json_extract(c.value,'$.evidence.chain_id')
      AND b.session_date=json_extract(c.value,'$.evidence.session_date')
      AND b.batch_id=json_extract(c.value,'$.evidence.batch_id')
  )))) INSERT INTO ops_runs
  SELECT ?,?,?,?,?,?,(SELECT json_object(
    'ok',COALESCE(SUM(json_extract(value,'$.status')='ok'),0),
    'warning',COALESCE(SUM(json_extract(value,'$.status')='warning'),0),
    'critical',COALESCE(SUM(json_extract(value,'$.status')='critical'),0),
    'unknown',COALESCE(SUM(json_extract(value,'$.status')='unknown'),0))
    FROM json_each(projected.snapshot_json,'$.checks')),projected.snapshot_json
  FROM projected WHERE 1
  ON CONFLICT(snapshot_id) DO UPDATE SET content_hash=CASE WHEN ops_runs.content_hash=excluded.content_hash THEN ops_runs.content_hash ELSE NULL END`,
  json,json,snapshot.snapshot_id,hash,snapshot.collector_id,collected,now,snapshot.duration_ms);
}
