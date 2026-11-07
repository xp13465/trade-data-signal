#!/usr/bin/env python3
"""Offline descriptive comparison. Reads normalized JSON only; writes JSON to stdout.
Usage: compare_benefits.py input.json [--allow-synthetic]
   or: compare_benefits.py --before before.json --after after.json
No repo imports, business calls, environment reads, networking or file writes.
Exit 0: ready descriptive comparison; 2: not_ready; 1: invalid input.
Scope v1: declared Asia/Shanghai delivery sessions; one fixed metric/population.
Not a US/Europe/multimarket calendar engine. Cross-market late inputs need a
separate expected-session/as-of contract; never substitute Chinese weekdays.
Input truth/actual exchange calendar must be attested upstream; hashes ensure local
consistency only. Bounds express unknown outcomes, not statistical confidence.
"""
import argparse
import hashlib
import json
import math
import os
import stat
import re
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SCHEMA = 'delivery-benefits-v1'
COMPARABLE = ('contract_id', 'metric_id', 'caliber_id', 'population_id',
              'schedule_id', 'exclusion_policy_id', 'normalizer_sha')
EXCLUSIONS = {'preapproved_maintenance', 'duplicate_or_shadow'}

def stamp(value):
    if not isinstance(value, str):
        raise ValueError('aware timestamp required')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.utcoffset() is None:
        raise ValueError('timestamp timezone required')
    return dt

def sha(value, length):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{%d}' % length, value) is not None

def integer(value):
    return type(value) is int and value >= 0

def nonempty(value):
    return isinstance(value, str) and bool(value.strip()) and value.lower() not in {'unknown','todo','null'}

def summarize(period, label, expected, errors):
    totals = dict(scheduled=0, excluded=0, denominator=0, success=0, failure=0, unknown=0)
    rows = period.get('days', [])
    if not isinstance(rows, list):
        errors.append(label + ':days_not_array')
        rows = []
    observed_dates = []
    rows_valid = True
    for n, row in enumerate(rows):
        p = f'{label}.days[{n}]'
        if not isinstance(row, dict):
            errors.append(p + ':not_object'); rows_valid = False; continue
        d = row.get('date')
        observed_dates.append(d)
        if row.get('inventory_complete') is not True:
            errors.append(p + ':inventory_incomplete')
        for k in ('inventory_ref', 'outcome_ref'):
            if not nonempty(row.get(k)):
                errors.append(p + ':' + k + '_missing')
        if row.get('code_sha') != period.get('code_sha') or not sha(row.get('code_sha'),40):
            errors.append(p + ':mixed_or_missing_code')
        if row.get('caliber_id') != period.get('caliber_id') or not nonempty(row.get('caliber_id')):
            errors.append(p + ':mixed_or_missing_caliber')
        try:
            deadline = stamp(row.get('deadline_at'))
            asof = stamp(period.get('as_of'))
            if deadline > asof or row.get('closed') is not True:
                errors.append(p + ':window_not_closed')
            if deadline.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat() < str(d):
                errors.append(p + ':deadline_precedes_session')
            rollout = stamp(period.get('rollout',{}).get('effective_at'))
            if label == 'before' and deadline >= rollout:
                errors.append(p + ':baseline_outcome_crosses_rollout')
            if label == 'after' and deadline <= rollout:
                errors.append(p + ':after_deadline_precedes_rollout')
        except (ValueError, TypeError, KeyError):
            errors.append(p + ':invalid_time')
        keys = ('scheduled','success','failure','unknown')
        if not all(integer(row.get(k)) for k in keys):
            errors.append(p + ':counts_require_nonnegative_integers'); rows_valid = False; continue
        exclusions = row.get('excluded',[])
        if not isinstance(exclusions,list):
            errors.append(p + ':invalid_exclusions'); rows_valid = False; continue
        ex = 0
        for e in exclusions:
            if not isinstance(e,dict) or not integer(e.get('count')):
                errors.append(p + ':invalid_exclusion_count'); rows_valid = False; continue
            ex += e['count']
            if e.get('reason') not in EXCLUSIONS or not nonempty(e.get('evidence_ref')):
                errors.append(p + ':unapproved_exclusion')
            try:
                if stamp(e.get('approved_at')) >= stamp(period.get('rollout',{}).get('effective_at')):
                    errors.append(p + ':exclusion_not_predeclared')
            except (ValueError, TypeError):
                errors.append(p + ':exclusion_approval_missing')
        den = row['scheduled'] - ex
        if den < 0 or row['success']+row['failure']+row['unknown'] != den:
            errors.append(p + ':denominator_not_reconciled'); rows_valid = False; continue
        totals['scheduled'] += row['scheduled']; totals['excluded'] += ex
        totals['denominator'] += den
        for k in ('success','failure','unknown'):
            totals[k] += row[k]
    if len(rows) != 10 or len(set(str(d) for d in observed_dates)) != 10:
        errors.append(label + ':requires_10_unique_actual_trading_days')
    if expected is None or observed_dates != expected:
        errors.append(label + ':not_exact_nearest_10_sessions')
    if not rows_valid:
        return {'raw_totals_partial':totals, 'rates':None, 'complete_counts':False}
    n=totals['denominator']; s=totals['success']; f=totals['failure']; u=totals['unknown']
    if not n:
        errors.append(label + ':zero_denominator')
    if n and s+f == 0:
        errors.append(label + ':all_outcomes_unknown')
    rates = None if not n else {
        'success_lower':s/n, 'success_upper':(s+u)/n,
        'failure_lower':f/n, 'failure_upper':(f+u)/n,
        'unknown_fraction':u/n, 'known_outcome_coverage':(s+f)/n,
        'success_among_known':None if not s+f else s/(s+f)}
    return {'raw_totals':totals, 'rates':rates, 'complete_counts':True,
            'session_dates':observed_dates,
            'bounds_kind':'logical_unknown_outcome_bounds_not_confidence_intervals',
            'aggregation':'sum_success/sum_eligible_batches; never mean_daily_rates'}

def compare(before, after, allow_synthetic=False):
    errors=[]; expected={}; kinds=[]
    for label,p in (('before',before),('after',after)):
        if not isinstance(p,dict):
            raise ValueError(label + ' must be an object')
        if p.get('schema_version') != SCHEMA:
            errors.append(label + ':schema_version')
        kind=p.get('measurement_kind'); kinds.append(kind)
        if kind not in ('real','synthetic'):
            errors.append(label + ':measurement_kind_missing')
        if kind=='synthetic' and not allow_synthetic:
            errors.append(label + ':synthetic_refused_default')
        for k in COMPARABLE:
            if not nonempty(p.get(k)):
                errors.append(label + ':' + k + '_missing')
        if not sha(p.get('normalizer_sha'),40):
            errors.append(label + ':normalizer_identity_missing')
        if not sha(p.get('code_sha'),40) or not sha(p.get('config_sha256'),64):
            errors.append(label + ':code_or_config_identity_missing')
        rollout=p.get('rollout')
        if not isinstance(rollout,dict): rollout={}
        if not nonempty(rollout.get('evidence_ref')):
            errors.append(label + ':rollout_evidence_missing')
        if p.get('code_sha') != rollout.get(label+'_code_sha') or p.get('config_sha256') != rollout.get(label+'_config_sha256'):
            errors.append(label + ':unpaired_version')
        try:
            anchor=stamp(rollout.get('effective_at')).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
        except (ValueError,TypeError):
            anchor=None; errors.append(label + ':rollout_time_missing')
        cal=p.get('calendar')
        if not isinstance(cal,dict): cal={}
        dates=cal.get('trading_days',[])
        valid_dates=isinstance(dates,list) and all(isinstance(x,str) for x in dates)
        try:
            valid_dates=valid_dates and all(date.fromisoformat(x).isoformat()==x for x in dates)
        except (ValueError,TypeError): valid_dates=False
        if not valid_dates or dates != sorted(set(dates)):
            errors.append(label + ':invalid_calendar'); dates=[]
        digest=hashlib.sha256(json.dumps(dates,separators=(',',':')).encode()).hexdigest()
        if (cal.get('verified_complete') is not True or not nonempty(cal.get('source_ref'))
                or cal.get('timezone')!='Asia/Shanghai' or digest!=cal.get('sha256')):
            errors.append(label + ':actual_calendar_evidence_missing_or_hash_mismatch')
        b=[d for d in dates if anchor and d<anchor][-10:]
        a=[d for d in dates if anchor and d>anchor][:10]
        expected[label]=b if label=='before' else a
        if len(expected[label])!=10:
            errors.append(label + ':calendar_window_insufficient')
        if not isinstance(p.get('confounders'),list):
            errors.append(label + ':confounders_not_listed')
    for k in COMPARABLE+('rollout','calendar','measurement_kind'):
        if before.get(k)!=after.get(k): errors.append('pair:mixed_'+k)
    bs=summarize(before,'before',expected['before'],errors)
    af=summarize(after,'after',expected['after'],errors)
    errors=sorted(set(errors))
    ready=not errors
    confounders=[]
    for label,p in (('before',before),('after',after)):
        for item in p.get('confounders',[]) if isinstance(p.get('confounders'),list) else []:
            confounders.append({'period':label,'reported':item})
    for k in ('code_sha','config_sha256','upstream_id','load_profile_id','runtime_id'):
        x,y=before.get(k),after.get(k)
        if not nonempty(x) or not nonempty(y):
            confounders.append({'factor':k,'assessment':'unassessed'})
        elif x!=y:
            confounders.append({'factor':k,'assessment':'changed','before':x,'after':y})
    delta=None
    if ready:
        lo=af['rates']['success_lower']-bs['rates']['success_upper']
        hi=af['rates']['success_upper']-bs['rates']['success_lower']
        delta={'success_rate_change_percentage_points_bounds':[100*lo,100*hi],
               'direction':'increase' if lo>0 else 'decrease' if hi<0 else 'inconclusive',
               'attribution':'not_established', 'interpretation':'descriptive_only',
               'relative_improvement_percent':None}
    manual={'status':'unavailable','observed_minutes_difference':None,'reason':'missing_complete_measured_manual_work'}
    def measured(p, summary):
        m=p.get('manual_work')
        if not isinstance(m,dict) or not summary.get('complete_counts'): return None
        v=m.get('minutes')
        if (type(v) not in (int,float) or not math.isfinite(v) or v<0 or m.get('complete') is not True
                or not nonempty(m.get('evidence_ref')) or type(m.get('eligible_batches')) is not int
                or m.get('eligible_batches')!=summary['raw_totals']['denominator']
                or not nonempty(m.get('scope_id'))): return None
        return m
    bm,am=measured(before,bs),measured(after,af)
    if ready and bm and am and bm['scope_id']==am['scope_id']:
        manual={'status':'measured_descriptive_only','observed_minutes_difference':bm['minutes']-am['minutes'],
                'before_minutes':bm['minutes'],'after_minutes':am['minutes'],
                'before_minutes_per_batch':bm['minutes']/bs['raw_totals']['denominator'],
                'after_minutes_per_batch':am['minutes']/af['raw_totals']['denominator'],
                'difference_semantics':'raw_before_total_minus_after_total; not net savings; load and denominator may differ',
                'attribution':'not_established'}
    return {'schema_version':SCHEMA,'status':'ready' if ready else 'not_ready',
            'measurement_kind':'synthetic' if 'synthetic' in kinds else 'real' if kinds==['real','real'] else 'unknown',
            'real_benefit_claim':False,'attribution':'not_established','interpretation':'descriptive_only',
            'scope':'v1: declared Asia/Shanghai delivery sessions, one fixed metric/population; cross-market input expectations/as-of require separate contract',
            'not_ready_reasons':errors,'before':bs,'after':af,'descriptive_change':delta,
            'confounders':confounders,'manual_work':manual,
            'trust_boundary':'Normalized counts/calendar/evidence refs are supplied attestations, not independently fetched or verified business truth.',
            'window_policy':'10 nearest actual sessions strictly before/after rollout local date; whole rollout date excluded; after deadlines closed at as_of.'}

def read_json(path):
    def pairs(items):
        obj={}
        for k,v in items:
            if k in obj: raise ValueError('duplicate JSON key')
            obj[k]=v
        return obj
    def bad_constant(value): raise ValueError('nonfinite JSON number')
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as f:
        before = os.fstat(f.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > 2 * 1024 * 1024:
            raise ValueError('input limit')
        raw = f.read(2 * 1024 * 1024 + 1)
        after = os.fstat(f.fileno())
    if len(raw) > 2 * 1024 * 1024 or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('changed input')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',nargs='?'); p.add_argument('--before'); p.add_argument('--after')
    p.add_argument('--allow-synthetic',action='store_true',help='explicit demonstration only; never real benefit')
    a=p.parse_args(argv)
    try:
        if a.input and not a.before and not a.after:
            raw=read_json(a.input); before,after=raw['before'],raw['after']
        elif not a.input and a.before and a.after:
            before,after=read_json(a.before),read_json(a.after)
        else: raise ValueError('provide one envelope OR both --before and --after')
        result=compare(before,after,a.allow_synthetic)
    except (OSError,ValueError,KeyError,TypeError,AttributeError,OverflowError,RecursionError):
        # Do not echo input values or file contents; they could contain private data.
        result={'status':'not_ready','error':'invalid_input','real_benefit_claim':False,
                'descriptive_change':None,'attribution':'not_established'}
        print(json.dumps(result,ensure_ascii=False,allow_nan=False)); return 1
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    return 0 if result['status']=='ready' else 2

if __name__=='__main__':
    sys.exit(main())
