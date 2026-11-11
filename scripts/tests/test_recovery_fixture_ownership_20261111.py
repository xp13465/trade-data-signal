"""Guard all four clipped recovery-loop fixtures against fake ownership logic.

Executes their real extracted production blocks, dict inputs only. Does not call
collectors/notify/systemd; the real ownership helper is spied on, never replaced
with a constant predicate. Original four modules' behavior assertions stay intact.
"""
import importlib
from datetime import datetime

import pytest

MODULES = (
    'test_alert_recovery_r2_and_cleanup_20261031',
    'test_309_key_migration_20261025',
    'test_245_l2_budget_digest_20261010',
    'test_240_alert_denoise_batch2_20261009',
)


@pytest.mark.parametrize('module_name', MODULES)
@pytest.mark.parametrize('status', ['active', 'pending'])
def test_fixture_uses_real_owner_and_preserves_normal_recovery(module_name, status, monkeypatch):
    import ops_legacy_events
    from _zero_outbound import ZeroOutboundTrap
    module = importlib.import_module(module_name)
    real = ops_legacy_events.owns_event_key
    calls = []
    def observed(key):
        result = real(key)
        calls.append((key, result))
        return result
    monkeypatch.setattr(ops_legacy_events, 'owns_event_key', observed)
    keys = ('producer_s06|offline', 'producer_heartbeat|offline', 'normal_task|exit!=0|1')
    state = {key: {'status': status, 'keyword': 'offline',
                   'first_seen': '2026-11-11 10:00:00',
                   'requires_action': status == 'active'} for key in keys}
    with ZeroOutboundTrap() as trap:
        if hasattr(module, '_run_recovery'):
            module._run_recovery(state, seen=set())
        else:
            module._run_recovery_loop(state, seen=set(), now=datetime(2026, 11, 11, 11))
    assert trap.hits == []
    assert calls == [(keys[0], True), (keys[1], True), (keys[2], False)]
    assert state[keys[0]]['status'] == state[keys[1]]['status'] == status
    assert state[keys[2]]['status'] == 'recovered'
