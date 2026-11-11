"""Keep real model notices outside operations statistics without muting sends."""
import ast
from pathlib import Path

import pytest

import alert_noise_count as a


def producer():
    source = Path(__file__).resolve().parents[1] / 'overfit_monitor.py'
    nodes = [node for node in ast.parse(source.read_text()).body if
             isinstance(node, ast.FunctionDef) and node.name == '_mk_alert' or
             isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and
             t.id == 'ALERT_RULES' for t in node.targets)]
    ns = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), ns)
    return ns


def model_row(name='overfit_high'):
    ns = producer()
    alert = ns['_mk_alert'](name, 75, '2026-11-11', assessment={
        'missing_dims': [], 'assessment_status': 'complete', 'coverage': 1,
        'as_of': '2026-11-11', 'partial_score': 75})
    return {'ts': '2026-11-11 21:41:00', 'subject': alert['subject'],
            'tier': 'critical' if alert['level'] == 'SEVERE' else 'notice',
            'source': 'overfit_monitor.py', 'key': 'overfit_' + name,
            'group': 'alert', 'channels': dict.fromkeys(('email', 'feishu', 'telegram'), True)}


def test_real_rule_population_separates_model_from_ops_but_keeps_old_ruler():
    ns = producer()
    rows = [model_row(name) for name in ns['ALERT_RULES']]
    assert {'overfit_' + name for name in ns['ALERT_RULES']} == a.OVERFIT_MODEL_KEYS
    assert all(a.operations_kind(row)[0] == 'operations' for row in rows)
    account = a.outbound_account(rows, ['2026-11-11'])
    assert account['populations'] == {'business': len(rows)}
    assert all(c['declared_success_rows'] == 0 for c in account['channels'].values())
    assert account['pass'] is None  # no notification coverage/stability claim


@pytest.mark.parametrize('changed', [
    {'source': 'notify.py'}, {'key': 'overfit_publish_failed'},
    {'key': ['overfit_overfit_high']}, {'subject': '[告警] 过拟合发布失败'},
    {'tier': 'warning'}, {'noise_class': 'routine_notice'},
    {'ops_event_refs': [{'key': 'task', 'event_id': 'e', 'phase': 'active', 'source_run': 'r'}]},
    {'ops_event_refs': 'malformed-explicit-ops-reference'},
])
def test_ambiguous_or_explicit_operations_are_not_excluded(changed):
    row = dict(model_row(), **changed)
    account = a.outbound_account([row], ['2026-11-11'])
    assert account['populations'].get('business', 0) == 0
    assert account['channels']['email']['declared_success_rows'] == 1
