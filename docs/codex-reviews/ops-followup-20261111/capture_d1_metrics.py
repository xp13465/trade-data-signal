"""Read-only D1 daily counters. Refuse to present an unfinished UTC day as complete.

Uses the same GraphQL dataset verified for this project, not SQL execution.
No production writes, scheduler, retry loop or notifications. Saved files are private.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlparse

UTC = dt.timezone.utc
FIELDS = ('rowsRead', 'rowsWritten', 'readQueries', 'writeQueries')
QUERY = '''query($accountTag:string!,$start:Date,$end:Date,$databaseId:string){viewer{accounts(filter:{accountTag:$accountTag}){d1AnalyticsAdaptiveGroups(limit:100,filter:{date_geq:$start,date_leq:$end,databaseId:$databaseId},orderBy:[date_ASC]){sum{rowsRead rowsWritten readQueries writeQueries} dimensions{date databaseId}}}}}'''


def window(day, observed_at):
    if observed_at.tzinfo is None:
        raise ValueError('observed_at must have timezone')
    end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), tzinfo=UTC)
    return {'day_utc': day.isoformat(), 'observed_at': observed_at.isoformat(),
            'window_end_utc': end.isoformat(), 'window_closed': observed_at >= end,
            'platform_finality_verified': False}


def parse_metrics(payload, day, database_id):
    if not isinstance(payload, dict):
        raise ValueError('GraphQL object result required')
    if payload.get('errors'):
        raise ValueError('GraphQL returned errors; counters unavailable')
    accounts = payload['data']['viewer']['accounts']
    if not isinstance(accounts, list) or len(accounts) != 1:
        raise ValueError('one account result required')
    groups = accounts[0]['d1AnalyticsAdaptiveGroups']
    if not isinstance(groups, list) or len(groups) != 1:
        raise ValueError('one daily result required; missing does not mean zero')
    row = groups[0]
    if row['dimensions']['date'] != day.isoformat() or row['dimensions']['databaseId'] != database_id:
        raise ValueError('date/database identity mismatch')
    counters = row['sum']
    result = {}
    for field in FIELDS:
        value = counters[field]
        if type(value) is not int or value < 0:
            raise ValueError('nonnegative integer counter required: ' + field)
        result[field] = value
    return result


def query_metrics(repo, day):
    # Read only named credentials. Do not print values or put authorization in argv.
    env = {}
    for line in (repo / '.env').read_text().splitlines():
        key, sep, value = line.strip().partition('=')
        if sep and key in ('CLOUDFLARE_API_TOKEN', 'R2_S3_ENDPOINT'):
            env[key] = value.strip().strip('\"\'')
    token = env['CLOUDFLARE_API_TOKEN']
    if not token or any(c in token for c in '\r\n"\\'):
        raise ValueError('invalid credential formatting')
    host = urlparse(env['R2_S3_ENDPOINT']).hostname or ''
    account = host.split('.')[0]
    if not re.fullmatch('[a-f0-9]{32}', account):
        raise ValueError('account identity unavailable')
    config = (repo / 'wrangler.jsonc').read_text()
    match = re.search(r'"database_name"\s*:\s*"trade-fund-score"[\s\S]*?"database_id"\s*:\s*"([^"]+)"', config)
    if not match:
        raise ValueError('database binding unavailable')
    database_id = match.group(1)
    request = {'query': QUERY, 'variables': {'accountTag': account, 'start': day.isoformat(),
               'end': day.isoformat(), 'databaseId': database_id}}
    with tempfile.TemporaryDirectory(prefix='trade-d1-readonly-') as folder:
        path = Path(folder)
        request_file = path / 'query.json'
        request_file.write_text(json.dumps(request))
        body = path / 'response.json'
        args = ['curl', '--disable', '--silent', '--show-error', '--connect-timeout', '8', '--max-time', '35',
                '-K', '-', '--data-binary', '@' + str(request_file), '-o', str(body),
                '-w', '%{http_code}', 'https://api.cloudflare.com/client/v4/graphql']
        config_stdin = 'header = "Authorization: Bearer ' + token + '"\nheader = "Content-Type: application/json"\n'
        result = subprocess.run(args, input=config_stdin, text=True, capture_output=True, timeout=40)
        if result.returncode or result.stdout != '200':
            # Suppress raw transport errors/response, which can contain account information.
            raise ValueError('metrics transport failed (curl=' + str(result.returncode) +
                             ', http=' + result.stdout[:3] + ')')
        payload = json.loads(body.read_text())
    return parse_metrics(payload, day, database_id)


def capture(day, observed_at, fetch):
    result = window(day, observed_at)
    result['source'] = 'Cloudflare GraphQL d1AnalyticsAdaptiveGroups'
    result['database_name'] = 'trade-fund-score'
    result['production_mutated'] = False
    result['cost_savings_claimed'] = False
    if not result['window_closed']:
        result['state'] = 'awaiting_window_close'
        result['reason'] = 'Requested UTC day is still open; no query was made'
        return result, 2
    try:
        result['counters'] = fetch()
        result['state'] = 'observed_closed_window_not_finalized'
        result['reason'] = 'Closed UTC interval; platform ingestion finality and causal savings remain unverified'
        return result, 0
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        result['state'] = 'unavailable'
        result['error_type'] = type(exc).__name__
        result['reason'] = 'No complete identity-checked metrics result; do not substitute zero'
        return result, 1


def write_receipt(output, result):
    """Atomically publish a new receipt, refusing to overwrite any existing name."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent,
                                     prefix='.d1-receipt-', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.link(temporary, output)  # atomic create-only publication; same filesystem
    finally:
        temporary.unlink(missing_ok=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path, help='project checkout containing .env and wrangler.jsonc')
    parser.add_argument('--day', required=True, type=dt.date.fromisoformat, help='UTC date YYYY-MM-DD')
    parser.add_argument('--output', required=True, type=Path, help='new private receipt file; existing files are refused')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output exists; use a new filename to preserve prior observations')
    result, code = capture(args.day, dt.datetime.now(UTC), lambda: query_metrics(args.repo, args.day))
    write_receipt(args.output, result)
    print(json.dumps({'state': result['state'], 'window_closed': result['window_closed'],
                      'platform_finality_verified': False, 'output': str(args.output)}, ensure_ascii=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
