#!/usr/bin/env python3
"""SYNTHETIC offline controls for compare_benefits.py only; no production evidence."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parents[1]

def atomic(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False); f.write('\n'); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)

def fixture():
    b=['2026-10-19','2026-10-20','2026-10-21','2026-10-22','2026-10-23','2026-10-26','2026-10-27','2026-10-28','2026-10-29','2026-10-30']
    a=['2026-11-03','2026-11-04','2026-11-05','2026-11-06','2026-11-09','2026-11-10','2026-11-11','2026-11-12','2026-11-13','2026-11-16']
    dates=b+['2026-11-02']+a
    cal={'trading_days':dates,'source_ref':'synthetic://test-only-not-exchange-proof','verified_complete':True,'timezone':'Asia/Shanghai','sha256':hashlib.sha256(json.dumps(dates,separators=(',',':')).encode()).hexdigest()}
    rollout={'effective_at':'2026-11-02T12:00:00+08:00','evidence_ref':'synthetic://rollout','before_code_sha':'a'*40,'after_code_sha':'b'*40,'before_config_sha256':'c'*64,'after_config_sha256':'d'*64}
    result={}
    for label,ds,cfg,sha in [('before',b,'c'*64,'a'*40),('after',a,'d'*64,'b'*40)]:
        result[label]={'schema_version':'delivery-benefits-v1','measurement_kind':'synthetic','contract_id':'delivery-contracts-v1','metric_id':'chain_delivery_success','caliber_id':'synthetic-caliber-v1','population_id':'synthetic-chain-A','schedule_id':'synthetic-same-schedule','exclusion_policy_id':'synthetic-no-exclusions','normalizer_sha':'e'*40,'code_sha':sha,'config_sha256':cfg,'rollout':copy.deepcopy(rollout),'calendar':copy.deepcopy(cal),'as_of':'2026-11-17T00:00:00+08:00','confounders':[],'upstream_id':'synthetic-upstream','load_profile_id':'synthetic-load','runtime_id':'synthetic-runtime','manual_work':None,'days':[{'date':d,'deadline_at':d+'T23:59:00+08:00','closed':True,'code_sha':sha,'caliber_id':'synthetic-caliber-v1','inventory_complete':True,'inventory_ref':'synthetic://schedule/'+d,'outcome_ref':'synthetic://receipt/'+d,'scheduled':10,'excluded':[],'success':8 if label=='before' else 9,'failure':2 if label=='before' else 1,'unknown':0} for d in ds]}
    return result

def legacy_controls():
    spec=importlib.util.spec_from_file_location('offline_compare',HERE/'compare_benefits.py')
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    base=fixture(); results=[]
    atomic(HERE/'synthetic'/'complete-legal.json',base)
    def check(name,x,verify,allow=True):
        got=mod.compare(x['before'],x['after'],allow_synthetic=allow)
        verify(got)
        results.append({'name':name,'measurement_kind':'synthetic','pass':True,'status':got['status'],'not_ready_reasons':got['not_ready_reasons'],'before':got['before'].get('raw_totals'),'after':got['after'].get('raw_totals'),'descriptive_change':got['descriptive_change']})
    def ok(g):
        assert g['status']=='ready' and g['descriptive_change']['attribution']=='not_established' and g['real_benefit_claim'] is False
    def notready(g): assert g['status']=='not_ready' and g['descriptive_change'] is None
    check('complete_legal_control',copy.deepcopy(base),ok)
    check('synthetic_default_refused',copy.deepcopy(base),notready,False)
    x=copy.deepcopy(base)
    for p in x.values():
        for d in p['days']: d.update(success=0,failure=0,unknown=10)
    def allunknown(g):
        notready(g)
        assert g['before']['rates']['success_lower']==0 and g['before']['rates']['success_upper']==1
    check('all_unknown_bounds_0_to_1',x,allunknown)
    x=copy.deepcopy(base); x['after']['days'].pop(); check('only_nine_sessions',x,notready)
    x=copy.deepcopy(base); x['after']['days'][0]['code_sha']='f'*40; check('mixed_day_code',x,notready)
    x=copy.deepcopy(base); x['after']['days'][0]['caliber_id']='other'; check('mixed_day_caliber',x,notready)
    x=copy.deepcopy(base); x['after']['caliber_id']='other'; check('mixed_pair_caliber',x,notready)
    x=copy.deepcopy(base)
    x['before']['days'][0].update(scheduled=100,success=0,failure=100)
    for d in x['before']['days'][1:]: d.update(scheduled=1,success=1,failure=0)
    def weighted(g):
        ok(g); assert g['before']['raw_totals']['denominator']==109
        assert g['before']['rates']['success_lower']==9/109
        assert g['after']['raw_totals']['denominator']==100
        assert g['before']['rates']['success_lower']!=0.9
    check('unequal_denominators_batch_weighted_not_daily_mean',x,weighted)
    x=copy.deepcopy(base)
    for p in x.values(): p['rollout']['effective_at']=None
    check('missing_rollout_time',x,notready)
    x=copy.deepcopy(base); x['after']['code_sha']=None; check('missing_code_identity',x,notready)
    x=copy.deepcopy(base); x['after']['days'][0]['unknown']=1; check('unreconciled_denominator',x,notready)
    x=copy.deepcopy(base); x['after']['days'][-1]['closed']=False; check('unfinished_after_window',x,notready)
    x=copy.deepcopy(base)
    for p in x.values():
        for d in p['days']: d.update(success=4,failure=1,unknown=5)
    def unknownbounds(g):
        ok(g); assert g['descriptive_change']['direction']=='inconclusive'
        assert g['before']['rates']['success_lower']==0.4 and g['before']['rates']['success_upper']==0.9
        assert g['manual_work']['observed_minutes_difference'] is None
    check('partial_unknown_inconclusive_no_labor_inference',x,unknownbounds)
    x=copy.deepcopy(base); x['after']['confounders']=[{'factor':'upstream_change','evidence_ref':'synthetic://change'}]
    def confounding(g):
        ok(g); assert any(c.get('factor')=='code_sha' for c in g['confounders'])
        assert any(c.get('reported',{}).get('factor')=='upstream_change' for c in g['confounders'])
    check('complete_still_descriptive_with_confounders',x,confounding)
    x=copy.deepcopy(base); x['after']['days'][0]['date']=x['after']['days'][1]['date']; check('duplicate_trading_day',x,notready)
    x=copy.deepcopy(base); x['after']['calendar']['sha256']='0'*64; check('calendar_hash_mismatch',x,notready)
    x=copy.deepcopy(base)
    for label,p in x.items():
        p['manual_work']={'minutes':120 if label=='before' else 90,'complete':True,'eligible_batches':100,'scope_id':'synthetic-manual','evidence_ref':'synthetic://timelog'}
    def labor(g):
        ok(g); assert g['manual_work']['observed_minutes_difference']==30
        assert g['manual_work']['attribution']=='not_established'
        assert 'not net savings' in g['manual_work']['difference_semantics']
    check('manual_raw_total_difference_not_net_savings',x,labor)
    x=copy.deepcopy(base)
    for p in x.values():
        for i,d in enumerate(p['days']): d.update(scheduled=1 if i==0 else 0,success=1 if i==0 else 0,failure=0,unknown=0)
        p['manual_work']={'minutes':10,'complete':True,'eligible_batches':True,'scope_id':'synthetic-manual','evidence_ref':'synthetic://timelog'}
    def laborbool(g):
        ok(g); assert g['before']['raw_totals']['denominator']==1
        assert g['manual_work']['status']=='unavailable'
    check('manual_eligible_batches_bool_rejected',x,laborbool)
    for args,rc in [(['synthetic/complete-legal.json'],2),(['synthetic/complete-legal.json','--allow-synthetic'],0),(['input-template.json'],2)]:
        p=subprocess.run([sys.executable,'-B',str(HERE/'compare_benefits.py'),*args],cwd=HERE,text=True,capture_output=True)
        got=json.loads(p.stdout); assert p.returncode==rc and got['real_benefit_claim'] is False
        results.append({'name':'CLI '+' '.join(args),'measurement_kind':'synthetic' if args[0].startswith('synthetic/') else 'empty_template','pass':True,'exit_code':p.returncode,'status':got['status']})
    report={'tool_sha256':hashlib.sha256((HERE/'compare_benefits.py').read_bytes()).hexdigest(),'measurement_kind':'synthetic_controls_only','production_batches_executed':0,'production_data_read':False,'tests_passed':len(results),'tests_failed':0,'tests':results}
    atomic(HERE/'synthetic'/'validation-results.json',report)
    print(json.dumps({'tests_passed':len(results),'tests_failed':0,'production_batches':0,'output':str(HERE/'synthetic'/'validation-results.json')}))

import tempfile
import shutil
import unittest

class LegacyComparatorTests(unittest.TestCase):
    def test_21_synthetic_controls_in_temporary_directory(self):
        global HERE
        original = HERE
        with tempfile.TemporaryDirectory(prefix='synthetic-comparator-') as td:
            HERE = Path(td)
            try:
                shutil.copyfile(original / 'compare_benefits.py', HERE / 'compare_benefits.py')
                empty = fixture()
                for period in empty.values():
                    period['days'] = []
                atomic(HERE / 'input-template.json', empty)
                legacy_controls()
                report = json.loads((HERE / 'synthetic/validation-results.json').read_text())
                self.assertEqual(report['tests_passed'], 21)
            finally:
                HERE = original

if __name__ == '__main__':
    unittest.main()

