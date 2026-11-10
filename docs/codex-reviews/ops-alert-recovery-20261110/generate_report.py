"""Build a public, allowlisted summary from private evidence; never contacts production."""
import argparse
import hashlib
import json
from pathlib import Path

CODE_HEAD = 'b5a7483374d252c0622284f17560fd601eb55e3d'
BASE = 'f35437a699d199076b5654dcde58780be89ee6b4'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('verification.json'))
    args = parser.parse_args()
    root = args.evidence
    def read(name):
        return json.loads((root / name).read_text())
    parity = read('integration-final-implementation-parity.json')
    assert parity['head'] == CODE_HEAD and all(x['equal'] for x in parity['files'])
    jobs = read('integration-ci-final-jobs.json')['jobs']
    assert len(jobs) == 2 and all(j['head_sha'] == CODE_HEAD and j['conclusion'] == 'success' for j in jobs)
    annotations = read('ci-final-annotations.json')
    counts = next(json.loads(a['message']) for a in annotations if a['message'].startswith('{"tests":'))
    assert counts['failures'] == counts['errors'] == 0
    renderer_log = (root / 'schedule-renderer-tests.txt').read_text()
    assert 'pass 7' in renderer_log and 'fail 0' in renderer_log
    assert any(step.get('name') == 'Run node --test ops/monitoring/tests/schedule-recovery.test.mjs'
               and step.get('conclusion') == 'success' for job in jobs for step in job['steps'])
    fund = read('publicfund-recovery-r3-final.json')['receipt']
    probe = read('probe-overfit-recovered-skip-r3-result.json')
    assert fund['collector_exit'] == 0 and fund['indices_verified'] is True
    assert probe['raw_skip_count_after_success'] == 1 and not probe['false_severe']
    tests = {
        'fund_r2': 'fund-budget/parent-r2-tests.txt',
        'overfit_r4': 'parent-overfit-r4-tests.txt',
        'schema_compatibility': 'parent-log-gz-green.txt',
        'browser_HC03_HC04': 'healthcheck-ui-final.log',
        'monitor_r2': 'parent-monitor-r2-tests.txt',
    }
    result = {
        'schema_version': 1, 'base': BASE, 'tested_code_head': CODE_HEAD,
        'branch': 'codex/ops-alert-recovery-20261110',
        'source_deployed': False, 'merged_to_main': False,
        'ci': {'url': 'https://github.com/xp13465/trade-data-signal/actions/runs/42849179943',
               'jobs': [{'name': j['name'], 'conclusion': j['conclusion']} for j in jobs],
               'junit_counts': counts, 'raw_pytest_last_line_available': False},
        'local_test_last_lines': {k: (root / v).read_text().strip().splitlines()[-1] for k, v in tests.items()},
        'blob_parity': parity['files'],
        'review_status': {
            'HC01_04': 'prior two R2 PASS: 5 files unchanged; app outside schedule renderer identical; original 102 browser assertions rerun',
            'fund': 'R1 P2 repaired; parent reran independent probes; no independent R2 verdict',
            'overfit': '37 independent probes rerun by parent; formal reviewer interrupted by quota',
            'monitor': 'parent-reviewed/tested; formal independent review unavailable after quota',
            'final_acceptance': 'Claude fixed-head review, merge/deploy and natural-run verification required',
        },
        'production_fund_collection': {k: fund[k] for k in (
            'started_at', 'finished_at', 'collector_exit', 'before_indices', 'after_indices',
            'before_nav_rows', 'after_nav_rows', 'indices_verified', 'row_backup_counts',
            'full_backup_matches_recovery_slice', 'full_database_quick_check')},
        'production_fund_field_coverage': read('fund-nav-recovery-field-coverage.json'),
        'production_overfit': read('overfit-live-verification/verification.json'),
        'production_monitor_observation': read('runtime-ops-state-refresh-summary.json'),
        'own_transient_cleanup': {'journal_archived': True, 'original_business_units_unchanged': read('own-transient-unit-cleanup.json')['original_units_unchanged']},
        'schedule_renderer_test': {'test_count': 7, 'failed': 0, 'log_sha256': hashlib.sha256((root/'schedule-renderer-tests.txt').read_bytes()).hexdigest()},
        'skip_recovery_probe': probe,
        'evidence_hashes': {},
    }
    publication = root / 'publicfund-publication-final.json'
    public_check = root / 'publicfund-public-verification.json'
    if publication.exists():
        value = json.loads(publication.read_text())['receipt']
        result['production_fund_publication'] = {k: value.get(k) for k in (
            'started_at','finished_at','source_changed','git_write','stages',
            'position_estimate_date','uploads_completed','error')}
    if public_check.exists():
        result['production_fund_public_checks'] = json.loads(public_check.read_text())
    final_observation = root / 'runtime-ops-state-final-summary.json'
    if final_observation.exists():
        result['production_monitor_final_observation'] = json.loads(final_observation.read_text())
    for name in [*tests.values(), 'ci-final-annotations.json','integration-ci-final-jobs.json',
                 'integration-final-implementation-parity.json','publicfund-recovery-r3-final.json',
                 'probe-overfit-recovered-skip-r3-result.json','review-fund-r1.json',
                 'parent-independent-overfit-r1.py.log']:
        result['evidence_hashes'][name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(f'wrote {args.output}; code {CODE_HEAD}; CI {counts}')


if __name__ == '__main__':
    main()
