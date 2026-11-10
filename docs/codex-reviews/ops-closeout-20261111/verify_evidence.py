"""Check archived evidence consistency, not present production health. No network/writes."""
import json
from pathlib import Path


def check(facts):
    failures = []
    def require(ok, name):
        if not ok:
            failures.append(name)
    source = facts['backup_source']
    restore = facts['backup_restore']
    names = {'sentiment', 'stock_daily', 'public_fund', 'etf_national_team'}
    require(source['complete'] is True, 'source complete')
    require({x['name'] for x in restore['results']} == names and len(restore['results']) == 4,
            'exactly four distinct restored databases')
    require(restore['run_id'] == source['run_id'], 'restore run binding')
    for row in restore['results']:
        name = row['name']
        expected = source['objects'].get(name)
        if not expected:
            failures.append('unknown database ' + name)
            continue
        require(row['run_id'] == source['run_id'], name + ' run binding')
        for field in ('key', 'raw', 'gzip', 'tables'):
            require(row[field] == expected[field], name + ' ' + field)
        require(row['integrity'] == ['ok'], name + ' integrity')
        require(row['before']['etag'] == row['after']['etag'], name + ' unchanged version')
        require(row['before']['run_match'] and row['after']['run_match'], name + ' object run')
        require(row['before']['entry_hash_match'] and row['after']['entry_hash_match'], name + ' entry identity')
    recovered = facts['fund_recovery']
    required = {('20261109', 'unit_nav', 1.1527), ('20261109', 'acc_nav', 1.1527),
                ('20261109', 'nav_change_pct', -0.11)}
    changes = recovered['changes']
    require(len(changes) == 3 and all(x['before'] is None for x in changes)
            and {(x['date'], x['field'], x['after']) for x in changes} == required,
            'only three approved empty cells')
    require(recovered['nonnull_unchanged'] and recovered['cursor_unchanged']
            and recovered['other_codes_unchanged'], 'existing values/cursor/other codes unchanged')
    public = facts['fund_public']
    require(public['sha256'] == recovered['bucket_sha256']
            and public['bytes'] == recovered['bucket_bytes'], 'published bucket matches recovered source')
    require(public['codes'] == recovered['bucket_codes'] == 107, 'all bucket codes retained')
    require(all(public['checks'].values()), 'public bucket checks')
    require(facts['fund_publication']['exit'] == recovered['collector_exit'] == 0, 'collector/uploader exit')
    require(len(facts['public_chains']['results']) == 11
            and all(x['source_match'] for x in facts['public_chains']['results']), 'historical 11 public checks')
    require(len(facts['etf_public']['results']) == 4
            and all(x['source_match'] for x in facts['etf_public']['results']), 'four public NAV checks')
    history = facts['history']['audit_compare']
    require(history['before_count'] == history['after_count'] == 136
            and history['added'] == history['removed'] == [], 'historical missing set unchanged')
    require(sum(facts['monitor']['counts'].values()) == 177, 'monitor count conservation')
    require(sum(facts['monitor']['unknown_categories'].values()) == facts['monitor']['counts']['unknown'],
            'unknown category conservation')
    require(facts['cnh']['actual_nov10_reproduces_stored_reason'], 'actual CNH reason replay')
    require(facts['source_deployed'] is False and facts['independent_review_pass'] is False,
            'no fabricated deployment or independent review')
    return {'evidence_consistent': not failures, 'failures': failures,
            'scope': 'archived receipt consistency only; not fresh production/review acceptance',
            'all_production_fixed': False}


if __name__ == '__main__':
    result = check(json.loads(Path(__file__).with_name('facts.json').read_text()))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['evidence_consistent'] else 1)
