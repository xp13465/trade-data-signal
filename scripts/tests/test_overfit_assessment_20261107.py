"""MR-01/MR-02: pure source functions only, no module imports or production I/O."""
import ast
from collections import defaultdict
import itertools
import json
import math
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
NAMES = {
    '_win', '_bucket_new', '_bucket_add', '_bucket_final', '_bucket_at',
    'bucket_backtest_trades', 'rolling_win_rates', 'calc_d1_deviation',
    'calc_d2_oos', 'calc_d3_param', 'calc_quadrant_health', 'calc_d4_quadrant',
    'valid_assessment_number', 'risk_level', 'compute_risk', 'daily_assessment',
    '_derive_daily_series', '_compute_bank', 'derive_daily_for_rolls',
    'assessed_prev_scores', 'evaluate_alerts', '_mk_alert',
}
CONSTANTS = {'AFG_MODES', 'OVERFIT_MODE', 'WINDOWS', 'SURFACE_DAYS',
             'W_D1', 'W_D2', 'W_D3', 'W_D4', 'ALERT_RULES'}


def source_functions():
    source = ROOT / 'scripts/overfit_monitor.py'
    nodes = []
    for node in ast.parse(source.read_text()).body:
        if isinstance(node, ast.FunctionDef) and node.name in NAMES:
            nodes.append(node)
        if isinstance(node, ast.Assign):
            ids = {n.id for target in node.targets for n in ast.walk(target) if isinstance(n, ast.Name)}
            if ids & CONSTANTS:
                ast.literal_eval(node.value)
                nodes.append(node)
    ns = {'math': math, 'defaultdict': defaultdict}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), ns)
    return ns


NS = source_functions()
DATE = '20261106'


def derive(bt, actual):
    return NS['_derive_daily_series']({15: bt}, {15: actual}, None, DATE, win=15)


def point(date=DATE, wr=50):
    # n=1 intentionally: no restored minimum-sample gate.
    return {'date': date, 'n': 1, 'win_rate': wr}


class AssessmentTests(unittest.TestCase):
    def test_all_missingness_masks_and_valid_zero(self):
        for mask in range(16):
            dims = [90 if mask & 1 << i else None for i in range(4)]
            score, detail = NS['compute_risk'](*dims, as_of=DATE)
            missing = [f'd{i+1}' for i, v in enumerate(dims) if v is None]
            self.assertEqual(detail['missing_dims'], missing)
            self.assertEqual(detail['coverage'], round(sum(w for w, v in zip([.4, .25, .2, .15], dims) if v is not None), 2))
            self.assertEqual(detail['as_of'], DATE)
            self.assertEqual(detail['assessment_status'], 'complete' if mask == 15 else 'unavailable' if mask == 0 else 'partial')
            self.assertEqual(score, 90 if mask == 15 else None)
            self.assertEqual(NS['risk_level'](score), 'red' if mask == 15 else 'gray')
        score, detail = NS['compute_risk'](0, 0, 0, 0, as_of=DATE)
        self.assertEqual((score, detail['assessment_status'], detail['coverage']), (0, 'complete', 1))

    def test_invalid_inputs_are_missing_and_json_safe(self):
        for invalid in [None, True, False, '90', '', [], {}, float('nan'), float('inf'), -float('inf')]:
            for i in range(4):
                dims = [0] * 4
                dims[i] = invalid
                score, detail = NS['compute_risk'](*dims, as_of=DATE)
                self.assertIsNone(score)
                self.assertEqual(detail['missing_dims'], [f'd{i+1}'])
                self.assertIsNone(detail['weighted'][f'd{i+1}'])
                json.dumps(detail, allow_nan=False)
            self.assertEqual(NS['risk_level'](invalid), 'gray')
            seq = derive([point()], [point(wr=invalid)])
            self.assertEqual(seq[0]['risk_score'], 40)
            self.assertTrue(seq[0]['missing_actual'])
            self.assertEqual(seq[0]['assessment_status'], 'unavailable')
            seq = derive([point(wr=invalid)], [point()])
            self.assertIsNone(seq[0]['risk_score'])
            self.assertTrue(seq[0]['missing_backtest'])

    def test_complete_four_dimensional_formula_frozen(self):
        for dims in itertools.product([0, 10, 30, 60, 90, 100], repeat=4):
            score, detail = NS['compute_risk'](*dims)
            parts = [w*v for w, v in zip([.4, .25, .2, .15], dims)]
            self.assertEqual(score, round(sum(parts)))
            self.assertEqual(detail['weighted'], {f'd{i+1}': round(v, 1) for i, v in enumerate(parts)})
        self.assertEqual([NS['risk_level'](x) for x in [0, 29, 30, 60, 61]], ['green', 'green', 'yellow', 'yellow', 'red'])

    def test_single_dimension_alerts_survive_unknown_composite(self):
        alerts = NS['evaluate_alerts'](0, [], None, 90, 90, 0, DATE)
        self.assertEqual([a['type'] for a in alerts], ['oos_fail', 'param_spike'])
        for a in alerts:
            self.assertIsNone(a['risk_score'])
            self.assertEqual(a['missing_dims'], ['d1'])
            self.assertEqual(a['coverage'], .6)
            self.assertEqual(a['as_of'], DATE)
            self.assertIn('不可评估', a['subject'])
            self.assertIn('权重覆盖 60%', a['body'])
            self.assertIn('缺维: d1', a['body'])
            self.assertNotIn('None', a['body'])
            self.assertNotIn('当前综合风险分: <b>0</b>', a['body'])
        self.assertEqual(NS['evaluate_alerts'](None, [1, 2, 3, 4, 5], None, None, None, None, DATE), [])

    def test_alert_thresholds_and_complete_behavior_frozen(self):
        for score in [0, 29, 30, 59, 60, 61, 90]:
            alerts = NS['evaluate_alerts'](score, [], score, score, score, score, DATE)
            self.assertEqual(any(a['type'] == 'overfit_high' for a in alerts), score >= 60)
        alerts = NS['evaluate_alerts'](0, [1, 2, 3, 4, 5], 0, 0, 0, 0, DATE)
        self.assertEqual([a['type'] for a in alerts], ['risk_climbing'])
        self.assertIn('当前综合风险分: <b>0</b> / 100', alerts[0]['body'])

    def test_native_bank_serialization_empty_and_param_spike(self):
        bank = NS['_compute_bank']({}, {}, {}, {}, DATE)
        current = bank['overfit']['current']
        self.assertEqual((current['risk_score'], current['level'], current['assessment_status'], current['as_of']), (None, 'gray', 'unavailable', DATE))
        trades = [{'mode': m, 'signal': 'buy', 'index_id': f'fixture_{i}', 'rating': 'mid',
                   'return_pct': ret, 'quad': 'sig_main'} for i in range(20) for m, ret in [('G', 1.), ('A', -1.)]]
        bank = NS['_compute_bank']({}, {}, {'20261105': trades}, {}, DATE)
        current = bank['overfit']['current']
        self.assertEqual(current['d3'], 90)
        self.assertIsNone(current['risk_score'])
        self.assertEqual(current['partial_score'], 18)
        self.assertEqual(current['coverage'], .35)
        alerts = NS['evaluate_alerts'](current['risk_score'], [], *(current[f'd{i}'] for i in range(1, 5)), DATE)
        self.assertEqual([a['type'] for a in alerts], ['param_spike'])
        for daily in bank['overfit']['daily_by_win'].values():
            self.assertEqual(daily[0]['risk_score'], 40)
            self.assertTrue(daily[0]['missing_actual'])
        json.dumps(bank, allow_nan=False)

    def test_daily_frozen_fields_and_missing_annotations(self):
        for actual in [0, 10, 24, 25, 30, 39, 40, 49, 50, 50.5, 51, 55, 60, 61, 65, 70, 100]:
            b = 50
            dev = actual-b
            if dev > 10: expected = max(10, 25-(dev-10)*.5)
            elif dev > 0: expected = 35-dev
            elif dev > -10: expected = 55-dev
            else: expected = min(95, 70-(dev+10)*1.5)
            p = derive([point(wr=b)], [point(wr=actual)])[0]
            self.assertEqual({k: p[k] for k in ['date', 'risk_score', 'level', 'win_rate']},
                             {'date': DATE, 'risk_score': round(expected), 'level': NS['risk_level'](expected), 'win_rate': 50.})
            self.assertEqual(p['assessment_status'], 'complete')
        self.assertEqual(derive([], [point()]), [])  # sell/no-backtest protection
        self.assertEqual(derive([], []), [])
        p = derive([point()], [])[0]
        self.assertEqual((p['risk_score'], p['level'], p['missing_actual'], p['missing_backtest'], p['as_of']), (40, 'yellow', True, False, DATE))
        seq = derive([point()], [point(), point('20261109')])
        self.assertIsNone(seq[-1]['risk_score'])
        self.assertEqual(seq[-1]['missing_reason'], ['missing_backtest'])
        p = derive([point(wr=None)], [point()])[0]
        self.assertIsNone(p['risk_score'])
        self.assertTrue(p['missing_backtest'])
        p = derive([point(wr=0)], [point(wr=0)])[0]
        self.assertEqual(p['assessment_status'], 'complete')

    def test_legacy_previous_scores_require_same_date_rolling_evidence(self):
        prev = {'overfit': {'daily': [{'date': DATE, 'risk_score': 40}, {'date': '20261109', 'risk_score': 40}]},
                'accuracy': {'rolling': {'backtest': {'60': [point(), point('20261109')]}, 'actual': {'60': [point()]}}}}
        self.assertEqual(NS['assessed_prev_scores'](prev), [40])  # valid 40 retained; missing 40 excluded
        prev['accuracy']['rolling']['actual'] = {'15': [point(), point('20261109')]}
        self.assertEqual(NS['assessed_prev_scores'](prev), [])
        prev['overfit']['daily'][0].update(NS['daily_assessment'](DATE, 50, 50))
        self.assertEqual(NS['assessed_prev_scores'](prev), [40])


if __name__ == '__main__':
    unittest.main()
