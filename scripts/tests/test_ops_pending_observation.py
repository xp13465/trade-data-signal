"""Actual local queue -> collector projection. Never start a worker or send."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket

import pytest

import ops_monitor as m
import r2_pending_context as q


@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('network'))
    cfg = m.Settings(data_root=str(tmp_path), code_root=str(tmp_path),
                     r2_pending_flag=str(tmp_path / 'pending'))
    flag = Path(cfg.r2_pending_flag)
    root = (tmp_path / 'static-site').resolve()
    proof = tmp_path / 'producer.json'
    proof.write_text(json.dumps({'version': 1, 'run_id': 'run-1', 'static_dir': str(root),
        'outputs': {'data/test.json': {'size': 2, 'sha256': hashlib.sha256(b'{}').hexdigest()}}}))
    row = q.enqueue(flag, root, proof, 'run-1')
    return cfg, row, root, flag


def observe(cfg):
    c = m.Collector(cfg, now=datetime.now(timezone.utc))
    c.pending_publication()
    snapshot = c.snapshot()
    m.validate_snapshot(snapshot)
    return snapshot['checks'][0]


def contents(root):
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file()}


def test_pending_observation_has_no_queue_mutation_or_invented_deadline(queue):
    cfg, _, root, flag = queue
    before = contents(Path(cfg.data_root))
    got = observe(cfg)
    assert got['status'] == 'unknown'
    e = got['evidence']
    assert e['pending_count'] == e['unoffered_count'] == 1
    assert e['oldest_wait_seconds'] >= 0
    assert e['deadline_status'] == e['public_bytes_status'] == 'unknown'
    assert contents(Path(cfg.data_root)) == before
    assert str(root) not in json.dumps(got)


def test_missing_config_does_not_probe_default_production_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(q, 'inspect_contexts', lambda *a, **k: pytest.fail('unconfigured read'))
    row = observe(m.Settings(data_root=str(tmp_path), code_root=str(tmp_path)))
    assert row['status'] == 'unknown'
    assert row['evidence']['source_reason'] == 'pending_queue_not_configured'
    assert not list(tmp_path.iterdir())


def test_missing_or_corrupt_proof_is_visible(queue):
    cfg, record, _, _ = queue
    Path(record['proof_path']).write_bytes(b'{}')
    row = observe(cfg)
    assert row['status'] == 'warning'
    assert row['evidence']['proof_invalid_count'] == 1


def test_done_tombstone_does_not_prove_current_public_bytes(queue, tmp_path):
    cfg, record, root, flag = queue
    batch = tmp_path / 'batch.json'
    result = tmp_path / 'result.json'
    q.snapshot(flag, root, batch)
    content = json.loads(batch.read_text())
    result.write_text(json.dumps({'batch_id': content['batch_id'], 'outcomes': [{
        'id': record['id'], 'proof_sha256': record['proof_sha256'], 'state': 'done'}]}))
    assert q.finish(flag, root, batch, result, True)['consumed'] == [record['id']]
    row = observe(cfg)
    assert row['evidence']['done_count'] == 1
    assert row['evidence']['proof_invalid_count'] == 0
    assert row['evidence']['public_bytes_status'] == 'unknown'


def test_scan_cap_never_looks_like_empty_queue(queue, monkeypatch):
    cfg, _, _, _ = queue
    monkeypatch.setattr(q, 'INSPECT_MAX_ENTRIES', 0)
    row = observe(cfg)
    assert row['status'] == 'unknown'
    assert row['evidence']['truncated'] is True


def test_collector_passes_its_remaining_budget(queue, monkeypatch):
    cfg, _, _, _ = queue
    original = q.inspect_contexts
    seen = []
    def inspect(*args, **kwargs):
        seen.append(kwargs['budget_seconds'])
        return original(*args, **kwargs)
    monkeypatch.setattr(q, 'inspect_contexts', inspect)
    c = m.Collector(cfg)
    c.budget.deadline = c.budget.clock() + 0.3
    c.pending_publication()
    assert 0 < seen[0] <= 0.3


@pytest.mark.parametrize('flag', ['relative', 5, '/tmp/nul\x00'])
def test_pending_config_must_be_an_absolute_path(tmp_path, flag):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'r2_pending_flag': flag}))
    with pytest.raises(m.ContractError):
        m.Settings.load(path)
