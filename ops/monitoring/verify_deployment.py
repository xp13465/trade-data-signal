#!/usr/bin/env python3
"""Read-only deployment verification. No network/credentials/processes by default.

Explicit --origin permits bounded GET probes only. No ingest, scheduled test,
incident mutation, collector execution, notification, migration or deploy calls.
The emitted report contains fixed diagnostic messages, never response bodies,
headers, token values, connection URLs, local paths or exception details.
"""
from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MAX_RESPONSE_BYTES = 1024 * 1024
ENDPOINTS = ('state', 'history?limit=1', 'events?limit=1', 'knowledge', 'incidents')
VALID_STATUSES = {'ok', 'warning', 'critical', 'unknown'}


def check(identifier, status, summary):
    return {'id': identifier, 'status': status, 'summary': summary}


def overall(checks):
    statuses = {c['status'] for c in checks}
    return next((s for s in ('critical', 'warning', 'unknown') if s in statuses), 'unknown' if not checks else 'ok')


def parse_time(value):
    if not isinstance(value, str):
        raise ValueError('timestamp')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timezone required')
    return result.astimezone(timezone.utc)


def origin_url(value, allow_local_http=False):
    parsed = urllib.parse.urlsplit(value)
    # A single origin, not a user-controlled path, query or credential-bearing URL.
    if (parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment
            or parsed.path not in ('', '/') or not parsed.hostname or '%' in parsed.netloc
            or any(ord(c) < 33 for c in value)):
        raise ValueError('origin must contain only scheme, host and optional port')
    _ = parsed.port
    local = parsed.hostname in ('localhost', '127.0.0.1', '::1')
    if parsed.scheme != 'https' and not (allow_local_http and local and parsed.scheme == 'http'):
        raise ValueError('HTTPS required; explicit loopback HTTP is local-test only')
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, '', '', ''))


def read_private_token(path):
    """Explicit private bootstrap token, regular owner-only file, bounded read."""
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise ValueError('private token file must be owned by current user and mode 0600 or stricter')
        raw = os.read(fd, 4097)
        if len(raw) > 4096:
            raise ValueError('token too long')
        token = raw.decode('utf-8').strip()
        if not token or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError('invalid token')
        return token
    finally:
        os.close(fd)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get_json(origin, endpoint, token=None, timeout=5):
    if endpoint not in ENDPOINTS:
        raise ValueError('only fixed read-only endpoints may be probed')
    headers = {'Accept': 'application/json', 'Cache-Control': 'no-cache'}
    if token:
        headers['X-Ops-Admin-Token'] = token
    request = urllib.request.Request(origin + '/api/ops/' + endpoint, headers=headers, method='GET')
    # Avoid inherited proxy credentials/routes; never forward auth on redirects.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        code = response.code
        safe_headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
        payload = response.read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ValueError('response exceeds verification budget')
    try:
        body = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        body = None
    return code, safe_headers, body


def response_checks(endpoint, response, authenticated=False):
    code, headers, body = response
    name = endpoint.split('?')[0]
    rows = []
    if code == 503:
        status, message = 'unknown', 'API not configured or unavailable; binding/migration proof missing'
    elif not authenticated:
        status, message = ('ok', 'Unauthenticated API access denied') if code in (401, 403) else ('critical', 'Unauthenticated API is accessible or returned unexpected status')
    elif code in (401, 403):
        status, message = 'unknown', 'Explicit admin authentication rejected; no private state verified'
    elif code != 200:
        status, message = 'unknown', 'Read probe did not return a usable API response'
    elif not isinstance(body, dict) or 'application/json' not in headers.get('content-type', '').lower():
        status, message = 'critical', 'API returned non-JSON or an unexpected response shape'
    else:
        status, message = 'ok', 'Read endpoint returned an authenticated JSON response'
    rows.append(check('http.' + name, status, message))
    # Security headers are required on errors as well as successful responses.
    cache = {part.strip().lower() for part in headers.get('cache-control', '').split(',')}
    rows.append(check('headers.' + name, 'ok' if 'no-store' in cache and not any(k.startswith('access-control-') for k in headers) else 'critical',
                      'No-store and no-CORS verified' if 'no-store' in cache and not any(k.startswith('access-control-') for k in headers) else 'API no-store/no-CORS contract failed'))
    if authenticated and code == 200 and isinstance(body, dict):
        field = {'history': 'runs', 'events': 'events', 'knowledge': 'records', 'incidents': 'incidents'}.get(name)
        if field:
            valid = isinstance(body.get(field), list)
            if name == 'knowledge':
                valid = valid and body.get('schema_version') == 1 and bool(re.fullmatch(r'[0-9a-f]{40}', str(body.get('baseline_code_ref', ''))))
            rows.append(check('shape.' + name, 'ok' if valid else 'critical', 'Endpoint envelope checked' if valid else 'Required endpoint envelope is missing'))
    return rows


def snapshot_checks(body, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(body, dict) or body.get('schema_version') != 1:
        return [check('snapshot', 'unknown', 'No valid state envelope available')]
    latest = body.get('latest')
    if latest is None:
        return [check('snapshot', 'unknown', 'No collector snapshot; an empty database is not healthy')]
    if not isinstance(latest, dict):
        return [check('snapshot', 'critical', 'Invalid latest snapshot shape')]
    try:
        server_time = parse_time(body.get('server_time'))
        collected = parse_time(latest.get('collected_at'))
    except ValueError:
        return [check('snapshot', 'unknown', 'Snapshot or server evidence time is missing or invalid')]
    if abs((now - server_time).total_seconds()) > 120:
        return [check('snapshot', 'unknown', 'Server clock differs from verifier; freshness cannot be proved')]
    age = (server_time - collected).total_seconds()
    if age < -120:
        return [check('snapshot', 'critical', 'Snapshot has an invalid future evidence time')]
    reported = body.get('collector_status')
    if age > 1800:
        return [check('snapshot', 'critical' if reported == 'fresh' else 'warning', 'Collector snapshot is stale; never infer recovery from HTTP success')]
    if reported != 'fresh':
        return [check('snapshot', 'unknown', 'Collector freshness is not confirmed by the server')]
    checks = latest.get('checks')
    if not isinstance(checks, list) or not checks or len(checks) > 250:
        return [check('snapshot', 'unknown', 'No valid nonempty collector check coverage')]
    if any(not isinstance(c, dict) or c.get('status') not in VALID_STATUSES for c in checks):
        return [check('snapshot', 'critical', 'Collector check statuses are invalid')]
    try:
        if any((server_time - parse_time(c.get('observed_at'))).total_seconds() > 1800 or
               (server_time - parse_time(c.get('observed_at'))).total_seconds() < -120 for c in checks):
            return [check('snapshot', 'unknown', 'Some check evidence is stale/future; fresh envelope alone is insufficient')]
    except ValueError:
        return [check('snapshot', 'unknown', 'Some check evidence times are missing')]
    missing = body.get('missing_checks', [])
    if not isinstance(missing, list) or any(not isinstance(c, dict) or c.get('status') != 'unknown' for c in missing):
        return [check('snapshot', 'critical', 'Missing-check coverage envelope is invalid')]
    counts = {s: sum(c['status'] == s for c in checks) for s in VALID_STATUSES}
    counts['unknown'] += len(missing)
    actual_counts = body.get('counts')
    if (not isinstance(actual_counts, dict) or any(type(v) is not int for v in actual_counts.values())
            or actual_counts != counts):
        return [check('snapshot', 'critical', 'Server counts disagree with current and missing check coverage')]
    rows = [check('snapshot', overall(checks), 'Fresh snapshot checked; business findings and unknown coverage preserved')]
    coverage = body.get('coverage') or {}
    if missing or not isinstance(coverage, dict) or coverage.get('prior_list_truncated'):
        rows.append(check('snapshot.coverage', 'unknown', 'Historical checks are missing or coverage is truncated; this is not recovery'))
    return rows


def parse_jsonc(text):
    """Parse JSONC without stripping comment-like substrings inside strings."""
    token = re.compile(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', re.S)
    text = token.sub(lambda match: match.group(1) or ('\n' * match.group(0).count('\n') or ' '), text)
    mask = re.sub(r'"(?:\\.|[^"\\])*"', lambda match: ' ' * len(match.group(0)), text)
    commas = [match.start() for match in re.finditer(r',(?=\s*[}\]])', mask)]
    for index in reversed(commas):
        text = text[:index] + text[index + 1:]
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result
    def reject_constant(value):
        raise ValueError('non-finite JSON number')
    return json.loads(text, object_pairs_hook=unique, parse_constant=reject_constant)


def worker_config_checks(config, local=False, config_path=None, source_root=None):
    if not isinstance(config, dict):
        return [check('config', 'unknown', 'No usable Worker configuration')]
    rows = []
    bindings = config.get('d1_databases')
    bindings = bindings if isinstance(bindings, list) else []
    ops = [b for b in bindings if isinstance(b, dict) and b.get('binding') == 'OPS_DB']
    if len(ops) != 1:
        rows.append(check('config.d1', 'critical', 'Exactly one dedicated OPS_DB binding is required'))
    else:
        database = ops[0]
        identifier = database.get('database_id')
        unique = bool(re.fullmatch(r'[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}', str(identifier)))
        others = [b for b in bindings if isinstance(b, dict) and b.get('binding') != 'OPS_DB']
        separate = all(identifier != b.get('database_id') and database.get('database_name') != b.get('database_name') for b in others)
        migration = bool(database.get('migrations_dir'))
        valid = unique and separate and migration
        rows.append(check('config.d1', 'ok' if valid else 'critical', 'Dedicated D1 and migration path declared' if valid else 'OPS_DB identity/migration isolation is invalid'))
    triggers = config.get('triggers') or {}
    crons = triggers.get('crons') if isinstance(triggers, dict) else None
    rows.append(check('config.cron', 'ok' if isinstance(crons, list) and '*/15 * * * *' in crons else 'critical',
                      'Independent fifteen-minute cron declared; runtime execution is not proved' if isinstance(crons, list) and '*/15 * * * *' in crons else 'Fifteen-minute watchdog cron declaration missing'))
    variables = config.get('vars') or {}
    forbidden = {'OPS_INGEST_TOKEN', 'OPS_ADMIN_TOKEN', 'OPS_ALERT_WEBHOOK', 'SESSION_SECRET', 'ADMIN_USERS', 'ADMIN_USERS_ADDITIONS'}
    safe = isinstance(variables, dict) and not (forbidden & set(variables))
    rows.append(check('config.secrets', 'ok' if safe else 'critical', 'Private bindings are not inline config variables' if safe else 'Private values must be provisioned as secrets, not inline configuration'))
    scope = variables.get('OPS_ALERT_SCOPE', 'watchdog') if isinstance(variables, dict) else None
    rows.append(check('config.alert-scope', 'ok' if scope == 'watchdog' else 'warning' if scope == 'all' else 'critical',
                      'Only collector loss/recovery may notify; business events belong to the existing chain' if scope == 'watchdog'
                      else 'All-check notifications require explicit Claude duplicate-alert review' if scope == 'all'
                      else 'OPS_ALERT_SCOPE is invalid; never assume broad alert permission'))
    enabled = variables.get('OPS_ALERT_ENABLED', 'false') if isinstance(variables, dict) else None
    rows.append(check('config.alert-enabled', 'ok' if enabled in ('false', False) else 'warning' if enabled in ('true', True) else 'critical',
                      'Real notification delivery disabled' if enabled in ('false', False)
                      else 'Real notifications enabled; scope and approval must be independently verified' if enabled in ('true', True)
                      else 'OPS_ALERT_ENABLED must be an explicit boolean value'))
    if local:
        all_bindings = [b for name in ('d1_databases', 'kv_namespaces', 'r2_buckets') for b in config.get(name, [])]
        simulated = bool(all_bindings) and all(isinstance(b, dict) and b.get('remote') is False for b in all_bindings) and enabled in ('false', False)
        rows.append(check('config.local', 'ok' if simulated else 'critical', 'All local storage bindings explicitly simulated' if simulated else 'Local configuration has remote or ambiguous bindings'))
    if config_path is not None:
        parent = Path(config_path).resolve().parent
        required = [('main', config.get('main'), False),
                    ('assets', config.get('assets', {}).get('directory') if isinstance(config.get('assets', {}), dict) else None, True),
                    ('migrations', ops[0].get('migrations_dir') if len(ops) == 1 else None, True)]
        expected = None if source_root is None else {
            'main': Path(source_root).resolve() / 'worker/headers.js',
            'assets': Path(source_root).resolve() / 'static-site',
            'migrations': Path(source_root).resolve() / 'ops/monitoring/migrations'}
        valid = True
        for label, raw, directory in required:
            if not isinstance(raw, str) or not raw:
                valid = False
                continue
            resolved = (parent / raw).resolve()
            valid = valid and (resolved.is_dir() if directory else resolved.is_file())
            if expected:
                valid = valid and resolved == expected[label]
        rows.append(check('config.paths', 'ok' if valid else 'critical',
                          'Candidate paths resolve to expected code/assets/migrations' if valid else 'Relocated candidate paths do not resolve to intended sources'))
    return rows


def canonical_unit(document, name):
    lines = document.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == f'`{name}`:':
            for begin in range(index + 1, len(lines)):
                if re.fullmatch(r'`trade-[A-Za-z0-9-]+\.(?:service|timer)`:', lines[begin].strip()):
                    return None
                if lines[begin].strip() == '```ini':
                    end = next(i for i in range(begin + 1, len(lines)) if lines[i].strip() == '```')
                    return '\n'.join(lines[begin + 1:end]) + '\n'
    return None


def package_checks(root):
    root = Path(root)
    rows = []
    canonical = root / 'docs/deploy/systemd-units-20260912.md'
    try:
        document = canonical.read_text() if canonical.exists() else ''
    except OSError:
        document = ''
    for name in ('trade-ops-monitor.service', 'trade-ops-monitor.timer'):
        path = root / 'ops/monitoring/install' / name
        if not path.is_file():
            rows.append(check('package.' + name, 'critical', 'Install unit missing'))
            continue
        try:
            contents = path.read_text()
        except OSError:
            rows.append(check('package.' + name, 'unknown', 'Install unit is unreadable; no policy proof'))
            continue
        config = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            config.read_string(contents)
        except configparser.Error:
            rows.append(check('package.' + name, 'critical', 'Install unit syntax invalid'))
            continue
        reference = canonical_unit(document, name)
        rows.append(check('canonical.' + name, 'unknown' if reference is None else 'ok' if reference == contents else 'critical',
                          'Canonical unit not registered yet' if reference is None else 'Canonical bytes match' if reference == contents else 'Canonical and install units have drifted'))
        if name.endswith('.service'):
            expected = {'Type': 'oneshot', 'ProtectSystem': 'strict', 'ProtectHome': 'read-only', 'NoNewPrivileges': 'yes', 'Restart': 'no', 'TimeoutStartSec': '240'}
            section = config['Service'] if config.has_section('Service') else {}
            valid = all(section.get(k) == v for k, v in expected.items()) and bool(section.get('LoadCredential')) and '--once' in section.get('ExecStart', '') and '/scripts/ops_monitor.py' in section.get('ExecStart', '')
        else:
            section = config['Timer'] if config.has_section('Timer') else {}
            valid = section.get('OnCalendar') == '*-*-* *:00/15:00' and section.get('Unit') == 'trade-ops-monitor.service'
        rows.append(check('package.' + name, 'ok' if valid else 'critical', 'Unit policy verified' if valid else 'Unit policy does not match deployment contract'))
    rows.append(check('runtime.collector', 'unknown', 'Package validation does not prove installed timer, successful collection or business health'))
    rows.append(check('runtime.watchdog', 'unknown', 'Independent Worker cron invocation must be verified separately by Claude'))
    return rows


def verify(root, origin=None, token=None, requester=get_json, now=None):
    rows = package_checks(root)
    if origin:
        try:
            response = requester(origin, 'state', None)
            rows += response_checks('state', response)
        except Exception:
            rows.append(check('http.unauthenticated', 'unknown', 'Read probe failed; details withheld'))
        if token:
            for endpoint in ENDPOINTS:
                try:
                    response = requester(origin, endpoint, token)
                    rows += response_checks(endpoint, response, True)
                    if endpoint == 'state' and response[0] == 200:
                        rows += snapshot_checks(response[2], now)
                except Exception:
                    rows.append(check('http.' + endpoint.split('?')[0], 'unknown', 'Read probe failed; details withheld'))
        else:
            rows.append(check('http.admin', 'unknown', 'No explicit bootstrap token supplied; use session UI for admin acceptance'))
    else:
        rows.append(check('http', 'unknown', 'Network probes disabled by default'))
    return {'schema_version': 1, 'verification_mode': 'GET-only' if origin else 'local-static-only',
            'status': overall(rows), 'checks': rows,
            'limitations': ['No ingest, scheduled test, incident update, notification or deployment was triggered',
                            'GET probes cannot prove independent cron execution, retention or provider delivery',
                            'A fresh collector snapshot and accepted notification do not prove business recovery']}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument('--worker-config', type=Path, help='Explicit candidate JSON/JSONC only; never an environment/secret file')
    ap.add_argument('--local-config', action='store_true', help='Require explicit remote:false for local bindings')
    ap.add_argument('--origin', help='Explicit HTTPS origin; enables GET probes only')
    ap.add_argument('--admin-token-file', type=Path, help='Explicit owner-only bootstrap token file; never a token argument')
    ap.add_argument('--allow-local-http', action='store_true', help='Permit literal loopback HTTP only for isolated local testing')
    args = ap.parse_args(argv)
    if args.admin_token_file and not args.origin:
        ap.error('--admin-token-file requires --origin')
    try:
        origin = origin_url(args.origin, args.allow_local_http) if args.origin else None
        token = read_private_token(args.admin_token_file) if args.admin_token_file else None
    except (ValueError, OSError):
        print(json.dumps({'status': 'unknown', 'error': 'Invalid origin or unreadable/insecure explicit admin token file'}))
        return 2
    report = verify(args.root, origin, token)
    if args.worker_config:
        try:
            if args.worker_config.suffix not in ('.json', '.jsonc'):
                raise ValueError('configuration suffix')
            config = parse_jsonc(args.worker_config.read_text())
            report['checks'] += worker_config_checks(config, args.local_config, args.worker_config, args.root)
        except (OSError, ValueError, TypeError):
            report['checks'].append(check('config', 'unknown', 'Candidate configuration is unreadable or invalid; details withheld'))
        report['status'] = overall(report['checks'])
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report['status'] in ('critical', 'warning') else 2 if report['status'] == 'unknown' else 0


if __name__ == '__main__':
    raise SystemExit(main())
