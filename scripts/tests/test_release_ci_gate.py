"""Release decisions with fake REST responses: no network or deployment side effects."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('release_ci_gate', ROOT / 'scripts/check_release_ci_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
HEAD, BEFORE, NEW = 'a' * 40, 'b' * 40, 'c' * 40
REPO = {'full_name': gate.REPOSITORY, 'fork': False}
WORKFLOW = (ROOT / '.github/workflows/ops-monitoring-checks.yml').read_text()


def run(workflow=gate.QUALITY, **changes):
    result = dict(id=10 if workflow == gate.QUALITY else 20, workflow_id=1 if workflow == gate.QUALITY else 2,
                  head_sha=HEAD, head_branch='main', event='push', repository=REPO,
                  head_repository=REPO, path='.github/workflows/' + workflow,
                  run_attempt=1, status='completed', conclusion='success', updated_at='2026-11-09T00:00:00Z')
    result.update(changes)
    return deepcopy(result)


class API:
    def __init__(self, quality=None, ops=None, files=None):
        self.runs = {gate.QUALITY: [run()] if quality is None else quality,
                     gate.OPS: [] if ops is None else ops}
        self.details = {}
        self.head = HEAD
        self.calls = []
        self.diff = dict(status='ahead', base_commit={'sha': BEFORE},
                         merge_base_commit={'sha': BEFORE}, total_commits=3,
                         files=[{'filename': 'docs/guide.md', 'status': 'modified'}] if files is None else files)

    def get(self, path):
        self.calls.append(path)
        if path == '/git/ref/heads/main':
            return {'object': {'sha': self.head}}
        if path.startswith('/compare/'):
            return deepcopy(self.diff)
        if '/workflows/' in path:
            workflow = path.split('/')[3]
            query = parse_qs(urlsplit(path).query)
            assert query['head_sha'] == [HEAD]
            page = int(query['page'][0])
            runs = self.runs[workflow]
            return {'total_count': len(runs), 'workflow_runs': deepcopy(runs[(page-1)*100:page*100])}
        if path.startswith('/actions/runs/'):
            identity = int(path.split('/')[-1])
            if identity in self.details:
                return deepcopy(self.details[identity])
            return deepcopy(next(r for runs in self.runs.values() for r in runs if r['id'] == identity))
        raise AssertionError(path)


def expected(api, before=BEFORE, event='push', workflow=WORKFLOW):
    return gate.ops_expected(api, {'before': before}, event, HEAD, workflow)[0]


def check(api, ops=False, timeout=0, **kwargs):
    return gate.wait_for_ci(api, HEAD, ops, timeout, **kwargs)


def test_docs_only_push_does_not_wait_for_nonexistent_ops():
    api = API()
    assert expected(api) is False
    assert check(api) == 'quality=success ops=not-triggered'
    assert f'/compare/{BEFORE}...{HEAD}?per_page=100&page=1' in api.calls


@pytest.mark.parametrize('filename', ['worker/ops-ingest.js', 'ops/monitoring/deep/a.py',
                                    'static-site/app.js', 'package-lock.json',
                                    'scripts/check_release_ci_gate.py',
                                    '.github/workflows/deploy-pages.yml'])
def test_ops_paths_require_ops_and_missing_never_passes(filename):
    api = API(files=[{'filename': filename, 'status': 'modified'}])
    assert expected(api)
    with pytest.raises(gate.GateError, match='超时'):
        check(api, True)


def test_multi_commit_push_matches_earlier_change_not_last_parent():
    api = API(files=[{'filename': 'worker/ops-ingest.js', 'status': 'modified'},
                     {'filename': 'docs/final-commit.md', 'status': 'modified'}])
    assert expected(api)
    assert check(API(ops=[run(gate.OPS)]), True).endswith('ops=success')


def test_rename_away_from_ops_is_conservative():
    api = API(files=[{'filename': 'docs/old.py', 'previous_filename': 'scripts/ops_monitor.py', 'status': 'renamed'}])
    assert expected(api)


@pytest.mark.parametrize('before,event', [('0'*40, 'push'), ('', 'push'), (BEFORE, 'workflow_dispatch')])
def test_no_before_requires_explicit_ops_success(before, event):
    api = API()
    assert expected(api, before, event)
    assert not any('/compare/' in call for call in api.calls)
    with pytest.raises(gate.GateError):
        check(api, True)
    assert check(API(ops=[run(gate.OPS, event='workflow_dispatch')]), True).endswith('ops=success')


@pytest.mark.parametrize('change', [{'status': 'diverged'}, {'merge_base_commit': {'sha': NEW}},
                                     {'total_commits': 1000}, {'total_commits': None}])
def test_inexact_compare_cannot_skip_ops(change):
    api = API()
    api.diff.update(change)
    assert expected(api)


def test_compare_at_file_cap_cannot_skip_ops():
    api = API(files=[{'filename': f'docs/{i}.md', 'status': 'modified'} for i in range(300)])
    assert expected(api)
    api.diff['files'].pop()
    assert not expected(api)


@pytest.mark.parametrize('pattern', ['!ops/**', 'ops/[ab].py', 'ops/?.py', 'ops/a**b'])
def test_unsupported_pattern_requires_ops(pattern):
    workflow = f'on:\n  push:\n    branches: [main]\n    paths: ["{pattern}"]\n'
    assert expected(API(), workflow=workflow)


@pytest.mark.parametrize('workflow', ['broken: [', 'on: {}', 'on:\n  push:\n    paths-ignore: [docs/**]'])
def test_unknown_workflow_fails_closed(workflow):
    assert expected(API(), workflow=workflow)


@pytest.mark.parametrize('status', ['queued', 'pending', 'waiting', 'requested', 'in_progress'])
def test_waits_for_nonterminal_then_success_without_wall_clock_sleep(status):
    api = API(quality=[run(status=status, conclusion=None)])
    clock = [0]
    def advance(seconds):
        clock[0] += seconds
        api.runs[gate.QUALITY][0].update(status='completed', conclusion='success')
    assert check(api, timeout=30, now=lambda: clock[0], sleep=advance).startswith('quality=success')
    assert clock[0] == 15


@pytest.mark.parametrize('conclusion', ['failure', 'cancelled', 'timed_out', 'skipped', 'neutral', 'action_required', None])
@pytest.mark.parametrize('workflow', [gate.QUALITY, gate.OPS])
def test_red_or_non_success_blocks_even_when_paths_did_not_need_ops(conclusion, workflow):
    api = API(ops=[run(gate.OPS)])
    api.runs[workflow][0]['conclusion'] = conclusion
    with pytest.raises(gate.GateError, match='未成功'):
        check(api)


def test_timeout_and_missing_quality():
    for api in [API(quality=[]), API(quality=[run(status='queued', conclusion=None)])]:
        clock = [0]
        with pytest.raises(gate.GateError, match='超时'):
            check(api, timeout=1, now=lambda: clock[0], sleep=lambda n: clock.__setitem__(0, clock[0]+n))


def test_current_attempt_overrules_stale_green_list():
    api = API()
    api.details[10] = run(run_attempt=2, status='queued', conclusion=None)
    with pytest.raises(gate.GateError, match='超时'):
        check(api)
    api.details[10].update(status='completed', conclusion='failure')
    with pytest.raises(gate.GateError, match='未成功'):
        check(api)
    api.details[10]['conclusion'] = 'success'
    assert check(api).startswith('quality=success')


def test_newer_same_head_run_beats_older_green():
    api = API(quality=[run(), run(id=11, status='in_progress', conclusion=None)])
    with pytest.raises(gate.GateError, match='超时'):
        check(api)


@pytest.mark.parametrize('change', [{'head_sha': NEW}, {'head_branch': 'feature'}, {'event': 'pull_request'},
                                    {'head_repository': {'full_name': 'fork/repo', 'fork': True}},
                                    {'path': '.github/workflows/unrelated.yml'},
                                    {'repository': {'full_name': 'other/repo'}}])
def test_untrusted_or_different_run_never_substitutes_for_main_ci(change):
    with pytest.raises(gate.GateError, match='超时'):
        check(API(quality=[run(**change)]))


def test_attempt_regression_or_identity_change_rejected():
    for change in [{'run_attempt': 0}, {'head_sha': NEW}, {'workflow_id': 99}]:
        api = API()
        api.details[10] = run(**change)
        with pytest.raises(gate.GateError, match='不匹配'):
            check(api)


def test_main_advanced_during_wait_or_after_ci_success():
    api = API(quality=[run(status='queued', conclusion=None)])
    with pytest.raises(gate.GateError, match='main 已前进'):
        check(api, timeout=30, sleep=lambda _: setattr(api, 'head', NEW))
    api = API()
    original = api.get
    def get(path):
        result = original(path)
        if path.startswith('/actions/'):
            api.head = NEW
        return result
    api.get = get
    with pytest.raises(gate.GateError, match='main 已前进'):
        check(api)


def test_paginated_same_head_runs_do_not_hide_latest_red():
    api = API(quality=[run(id=i+1) for i in range(100)] + [run(id=101, conclusion='failure')])
    with pytest.raises(gate.GateError, match='未成功'):
        check(api)
    assert any('page=2' in call for call in api.calls)


def test_missing_api_data_or_unreadable_is_not_success():
    for result in [{}, {'total_count': 1, 'workflow_runs': []},
                   {'total_count': 1000, 'workflow_runs': []}]:
        api = API()
        original = api.get
        api.get = lambda p: result if '/workflows/' in p else original(p)
        with pytest.raises(gate.GateError):
            check(api)
    api = API()
    api.diff.pop('files')
    with pytest.raises(gate.GateError):
        expected(api)


def test_http_error_does_not_print_token_or_body(monkeypatch):
    from urllib.error import HTTPError
    def forbidden(*args, **kwargs):
        raise HTTPError('secret-url', 403, 'secret-body', {}, None)
    monkeypatch.setattr(gate, 'urlopen', forbidden)
    with pytest.raises(gate.GateError, match='HTTP 403') as error:
        gate.GitHub('secret-token').get('/git/ref/heads/main')
    assert 'secret' not in str(error.value)


@pytest.mark.parametrize('event_name,ref,repo,checkout', [('pull_request', 'refs/heads/main', gate.REPOSITORY, HEAD),
    ('push', 'refs/heads/feature', gate.REPOSITORY, HEAD), ('push', 'refs/heads/main', 'fork/repo', HEAD),
    ('push', 'refs/heads/main', gate.REPOSITORY, NEW)])
def test_deployment_context_rejected(event_name, ref, repo, checkout):
    with pytest.raises(gate.GateError):
        gate.validate_context({'repository': REPO, 'after': HEAD, 'ref': ref}, event_name, repo, ref, HEAD, checkout)


def test_manual_main_context_and_push_context():
    for event_name in ['push', 'workflow_dispatch']:
        gate.validate_context({'repository': REPO, 'after': HEAD, 'ref': 'refs/heads/main'},
                              event_name, gate.REPOSITORY, 'refs/heads/main', HEAD, HEAD)


@pytest.mark.parametrize('name', ['deploy-cf.yml', 'deploy-pages.yml'])
def test_old_red_ci_deploy_counterexample_and_new_dependency_structure(name):
    old = yaml.load(subprocess.check_output(['git', 'show', f'314e94e67aba19f9e7cf5aaa299553118b3a2f5b:.github/workflows/{name}'], text=True), Loader=yaml.BaseLoader)
    new = yaml.load((ROOT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader)
    # With unrelated CI red, all old deploy dependencies (none/build) still succeed.
    old_needs = old['jobs']['deploy'].get('needs', [])
    assert 'ci-gate' not in old_needs
    assert new['on'] == old['on']
    needs = new['jobs']['deploy']['needs']
    assert 'ci-gate' in needs
    assert new['jobs']['ci-gate']['permissions'] == {'actions': 'read', 'contents': 'read'}
    for job in new['jobs'].values():
        for step in job.get('steps', []):
            if step.get('uses', '').startswith('actions/checkout@'):
                assert step['with']['ref'] == '${{ github.sha }}'
                assert step['with']['persist-credentials'] == 'false'
    steps = new['jobs']['deploy']['steps']
    final = next(i for i, step in enumerate(steps) if step.get('run') == 'npx wrangler deploy' or step.get('uses', '').startswith('actions/deploy-pages@'))
    assert steps[final-1]['run'] == 'python3 scripts/check_release_ci_gate.py --timeout 0'
    with pytest.raises(gate.GateError, match='未成功'):
        check(API(quality=[run(conclusion='failure')]))


def test_partial_ops_record_must_not_look_like_path_filtered_skip():
    partial = run(gate.OPS)
    partial.pop('head_repository')
    with pytest.raises(gate.GateError, match='字段缺失'):
        check(API(ops=[partial]))


def test_live_api_unreadable_never_allows_release():
    api = API()
    def unreadable(path):
        raise gate.GateError('API 不可读')
    api.get = unreadable
    with pytest.raises(gate.GateError, match='不可读'):
        check(api)
    with pytest.raises(gate.GateError, match='不可读'):
        expected(api)


def test_cli_uses_fixed_checkout_and_emits_safe_summary(monkeypatch, tmp_path, capsys):
    event = tmp_path / 'event.json'
    event.write_text(json.dumps({'repository': REPO, 'ref': 'refs/heads/main', 'before': BEFORE, 'after': HEAD}))
    for key, value in {'GITHUB_EVENT_PATH': str(event), 'GITHUB_SHA': HEAD, 'GITHUB_EVENT_NAME': 'push',
                       'GITHUB_REPOSITORY': gate.REPOSITORY, 'GITHUB_REF': 'refs/heads/main',
                       'GITHUB_TOKEN': 'fixture-never-log-token'}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(gate.subprocess, 'check_output', lambda *args, **kwargs: HEAD + '\n')
    api = API()
    monkeypatch.setattr(gate, 'GitHub', lambda token: api)
    monkeypatch.setattr(sys, 'argv', ['gate', '--timeout', '0'])
    assert gate.main() == 0
    assert f'head={HEAD}' in capsys.readouterr().out
    api.runs[gate.QUALITY][0]['conclusion'] = 'failure'
    assert gate.main() == 1
    output = capsys.readouterr()
    assert 'BLOCKED' in output.err and '重跑' in output.err
    assert 'fixture-never-log-token' not in output.err + output.out


def test_older_run_id_rerun_after_newer_green_is_not_hidden():
    api = API(quality=[run(id=10, run_attempt=2, status='queued', conclusion=None,
                          updated_at='2026-11-09T00:01:00Z'), run(id=11)])
    with pytest.raises(gate.GateError, match='超时'):
        check(api)


def test_compare_missing_file_status_is_not_a_docs_only_proof():
    with pytest.raises(gate.GateError, match='记录缺失'):
        expected(API(files=[{'filename': 'docs/guide.md'}]))


def test_no_run_discovery_is_short_and_manual_does_not_wait():
    clock = [0]
    def advance(seconds):
        clock[0] += seconds
    with pytest.raises(gate.GateError, match='需补跑'):
        check(API(quality=[]), timeout=2100, now=lambda: clock[0], sleep=advance)
    assert clock[0] == 120
    with pytest.raises(gate.GateError, match='需补跑'):
        check(API(quality=[]), timeout=2100, discovery_timeout=0, now=lambda: 0,
              sleep=lambda _: pytest.fail('manual missing run must not sleep'))


def test_existing_queued_run_can_wait_longer_than_discovery_budget():
    clock = [0]
    api = API(quality=[run(status='queued', conclusion=None)])
    def advance(seconds):
        clock[0] += seconds
        if clock[0] >= 135:
            api.runs[gate.QUALITY][0].update(status='completed', conclusion='success')
    assert check(api, timeout=2100, now=lambda: clock[0], sleep=advance).startswith('quality=success')
    assert clock[0] == 135


# Exact incident interval from the parent, fixed full SHAs (read-only git, no API).
ALERT_BEFORE = "7e47f5a3e27e7cfc9661e3d0bd673e01906aa034"
ALERT_AFTER = "57dd0461cf9aeb73fb00f35822aefc5f93f9cc49"
ALERT_INPUTS = ['scripts/check_preupload_backup.py', 'scripts/upload_r2.py', 'scripts/r2_upload_async.sh', 'scripts/r2_lock_paths.py', 'scripts/r2_lock_probe.py', 'scripts/r2_pending_context.py', 'scripts/util_atomic.py', 'scripts/lib/upload_watchdog.sh', 'scripts/lib/repo_paths.sh', 'scripts/tests/test_preupload_accounting_*.py', 'scripts/tests/test_r2_purge_delivery_*.py', 'scripts/tests/test_237_check_preupload_backup_pytest.py', 'scripts/tests/test_f03*.py', 'scripts/tests/test_codex_r2_alert_delivery.py', 'scripts/tests/test_codex_r2_pending_handoff_*.py', 'scripts/tests/test_r2_lock*.py', 'scripts/tests/_notify_sandbox.py', 'scripts/tests/_zero_outbound.py', 'scripts/tests/conftest.py', 'scripts/tests/_ci_stubs.py']

def _alert_sample(pattern):
    return pattern.replace("*", "20261110")

def _assert_alert_coverage(text):
    data = yaml.load(text, Loader=yaml.BaseLoader)["on"]
    assert data["push"]["paths"] == data["pull_request"]["paths"]
    compiled = gate.ops_input_patterns(text)
    assert len(compiled) == len(data["push"]["paths"])
    for pattern in ALERT_INPUTS:
        assert pattern in data["push"]["paths"], pattern
        assert any(p.fullmatch(_alert_sample(pattern)) for p in compiled), pattern

def test_alert_inputs_push_pr_and_gate_one_to_one():
    _assert_alert_coverage(WORKFLOW)
    for filename in ["scripts/unrelated_collector.py", "app/unrelated.py", "docs/report.md"]:
        assert not expected(API(files=[{"filename": filename, "status": "modified"}]))

@pytest.mark.parametrize("removed", ALERT_INPUTS)
def test_removing_alert_subscription_is_detected(removed):
    data = yaml.load(WORKFLOW, Loader=yaml.BaseLoader)
    for event in ["push", "pull_request"]:
        data["on"][event]["paths"].remove(removed)
    with pytest.raises(AssertionError):
        _assert_alert_coverage(yaml.safe_dump(data, sort_keys=False))

def test_real_alert_push_previously_filtered_and_now_requires_ops():
    files = subprocess.run(["git", "diff", "--name-only", ALERT_BEFORE + ".." + ALERT_AFTER],
                           cwd=ROOT, capture_output=True, text=True, check=True, timeout=8).stdout.splitlines()
    old = subprocess.run(["git", "show", ALERT_AFTER + ":.github/workflows/ops-monitoring-checks.yml"],
                         cwd=ROOT, capture_output=True, text=True, check=True, timeout=8).stdout
    assert files and "scripts/upload_r2.py" in files and "scripts/check_preupload_backup.py" in files
    records = [{"filename": p, "status": "modified"} for p in files]
    assert expected(API(files=records), workflow=old) is False
    assert expected(API(files=records)) is True
    for p in files:
        if p.startswith("scripts/"):
            assert expected(API(files=[{"filename": p, "status": "modified"}])) is True, p
    with pytest.raises(gate.GateError, match="超时"):
        check(API(files=records), ops=True)

def test_push_pr_subscription_drift_requires_ops():
    data = yaml.load(WORKFLOW, Loader=yaml.BaseLoader)
    data["on"]["pull_request"]["paths"].remove("scripts/upload_r2.py")
    assert expected(API(), workflow=yaml.safe_dump(data, sort_keys=False)) is True


OVERFIT_VERIFIER_INPUTS = [
    "scripts/overfit_monitor.py",
    "scripts/tests/test_overfit_delivery_*.py",
    "scripts/tests/test_overfit_public_verifier_*.py",
    "scripts/tests/test_223_overfit_monitor_timeout.py",
]


def _assert_overfit_verifier_coverage(text):
    data = yaml.load(text, Loader=yaml.BaseLoader)["on"]
    assert data["push"]["paths"] == data["pull_request"]["paths"]
    patterns = gate.ops_input_patterns(text)
    for path in OVERFIT_VERIFIER_INPUTS:
        assert path in data["push"]["paths"]
        assert any(p.fullmatch(path.replace("*", "20261110")) for p in patterns)


def test_overfit_verifier_tests_require_exact_head_ops():
    _assert_overfit_verifier_coverage(WORKFLOW)
    for path in OVERFIT_VERIFIER_INPUTS:
        assert expected(API(files=[{"filename": path.replace("*", "20261110"), "status": "modified"}]))


@pytest.mark.parametrize("removed", OVERFIT_VERIFIER_INPUTS)
def test_removed_overfit_verifier_subscription_is_detected(removed):
    data = yaml.load(WORKFLOW, Loader=yaml.BaseLoader)
    for event in ("push", "pull_request"):
        data["on"][event]["paths"].remove(removed)
    with pytest.raises(AssertionError):
        _assert_overfit_verifier_coverage(yaml.safe_dump(data, sort_keys=False))


@pytest.mark.parametrize('filename', [
    'app/fx_contract.py', 'app/collector/public_fund_gap.py',
    'scripts/r2_safe_write.py', 'scripts/ops_business_evidence.py',
    'scripts/d1_metrics_evidence.py', 'scripts/lib/d1_execute.sh',
    'scripts/collect_fof_nav.py', 'scripts/main-merge.sh', 'scripts/deploy.sh',
    'static-site/lab.js', 'static-site/lab.css',
    'scripts/playwright-accept/mobile_source_harness.mjs',
    'scripts/tests/test_hc21_deploy_push_gate.py',
])
def test_backlog_isolated_module_change_requires_ops_success(filename):
    # A helper-only followup must not evade the release gate merely because its
    # previously listed caller has not changed in this push.
    api = API(files=[{'filename': filename, 'status': 'modified'}])
    assert expected(api)
    with pytest.raises(gate.GateError, match='超时'):
        check(api, True)
