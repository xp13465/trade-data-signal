#!/usr/bin/env python3
"""Read-only bounded cloud collector. --collect-only never accesses the network.

Only fixed systemctl properties, this collector's bounded journal projection and
fixed source paths are read. File existence is
not content correctness; publication/backup metadata never proves remote integrity.
Codex implements this collector; Claude reviews, merges and deploys. Python stdlib only.
"""
from __future__ import annotations

import argparse
import ast
import errno
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import hashlib
import http.client
import json
import math
import multiprocessing
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import ssl
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
import uuid

MAX_SNAPSHOT = 256 * 1024
MAX_JSON = 1024 * 1024
MAX_COMMAND = 128 * 1024
MAX_UNITS = 72
MAX_CHECKS = 250
SELF_UNIT = 'trade-ops-monitor.service'
SELF_JOURNAL = ('/usr/bin/journalctl', '--no-pager', '--quiet', '--boot=0',
                '--unit=' + SELF_UNIT, '--lines=64', '--output=json',
                '--output-fields=__REALTIME_TIMESTAMP,_BOOT_ID,_PID,UNIT,MESSAGE_ID,JOB_TYPE,JOB_RESULT,INVOCATION_ID,_SYSTEMD_UNIT,_SYSTEMD_INVOCATION_ID,SYSLOG_IDENTIFIER,MESSAGE')
ALLOWED_HOSTS = frozenset({'ss.fx8.store', 's.fx8.store', 'sss.sugas.site', 's.sugas.site'})
HEAD_PATHS = frozenset({'/', '/__build', '/__build.json', '/data/schedule_stats.json'})
UNIT_RE = re.compile(r'^trade-[A-Za-z0-9_-]{1,90}\.service$')
SAFE_PROPS = ('Id', 'LoadState', 'ActiveState', 'SubState', 'Type', 'Result',
              'ExecMainCode', 'ExecMainStatus', 'ExecMainStartTimestamp',
              'ExecMainExitTimestamp', 'UnitFileState', 'TimersCalendar',
              'TimersMonotonic', 'NextElapseUSecRealtime', 'NextElapseUSecMonotonic',
              'LastTriggerUSec', 'Persistent', 'SuccessExitStatus')
DELIVERY_ERRORS = frozenset({'ops_storage_unavailable', 'ops_storage_or_service_unavailable',
                            'ingest_not_configured', 'ops_token_configuration_invalid',
                            'ingest_required', 'snapshot_id_conflict'})
SERVER_ERROR_KINDS = frozenset({'unknown', 'storage_transient', 'storage_quota',
                               'storage_configuration', 'storage_constraint',
                               'storage_overloaded', 'storage_resource_limit', 'configuration'})
NONRETRY_KINDS = SERVER_ERROR_KINDS - {'unknown', 'storage_transient'}


class LimitError(Exception):
    pass


class ContractError(Exception):
    pass


class Budget:
    def __init__(self, seconds=20, clock=time.monotonic):
        self.clock = clock
        self.started = clock()
        self.deadline = self.started + seconds

    def remaining(self, maximum=None):
        left = self.deadline - self.clock()
        if left <= 0:
            raise LimitError('deadline')
        return min(left, maximum) if maximum is not None else left


@dataclass
class Settings:
    collector_id: str = 'cloud-main'
    code_root: str = '/home/ubuntu/code/trade-data-signal'
    data_root: str = '/home/ubuntu/code/trade-data'
    output_dir: str = '/run/trade-ops-monitor'
    ingest_url: str = 'https://ss.fx8.store/api/ops/ingest'
    secret_file: str = '/etc/trade-ops-monitor/ingest.token'
    total_timeout_seconds: int = 20
    command_timeout_seconds: int = 3
    schedule_max_age_seconds: int = 1800
    publication_head_url: str | None = None
    benefits_enabled: bool = False

    @classmethod
    def load(cls, path):
        obj = read_json(Path(path), 64 * 1024)
        if not isinstance(obj, dict) or set(obj) - set(cls.__dataclass_fields__):
            raise ContractError('config keys')
        cfg = cls(**obj)
        if type(cfg.benefits_enabled) is not bool:
            raise ContractError('benefits flag')
        if not isinstance(cfg.collector_id, str) or not re.fullmatch(r'[a-z0-9_-]{1,48}', cfg.collector_id):
            raise ContractError('collector id')
        for key in ('code_root', 'data_root', 'output_dir', 'secret_file'):
            value = getattr(cfg, key)
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise ContractError('absolute path required')
        for key, low, high in (('total_timeout_seconds', 10, 25), ('command_timeout_seconds', 1, 5),
                               ('schedule_max_age_seconds', 60, 86400)):
            if type(getattr(cfg, key)) is not int or not low <= getattr(cfg, key) <= high:
                raise ContractError('config budget')
        if not isinstance(cfg.ingest_url, str) or (cfg.publication_head_url is not None and not isinstance(cfg.publication_head_url, str)):
            raise ContractError('url type')
        return cfg


def strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError('duplicate JSON key')
        result[key] = value
    return result


def read_bytes(path, cap):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > cap:
            raise LimitError('not bounded regular file')
        raw = stream.read(cap + 1)
        after = os.fstat(stream.fileno())
    if len(raw) > cap or (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise LimitError('input changed or grew')
    return raw


def read_json(path, cap=MAX_JSON):
    def reject(_):
        raise ContractError('nonfinite JSON')
    return json.loads(read_bytes(path, cap), object_pairs_hook=strict_pairs, parse_constant=reject)


def source_path(root, relative):
    base = Path(root).resolve()
    path = base / relative
    if not path.resolve().is_relative_to(base):
        raise ContractError('source symlink escapes root')
    return path


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def check(cid, category, status, summary, evidence=None, observed_at=None):
    return {'id': cid, 'name': cid[:160], 'category': category, 'status': status,
            'observed_at': observed_at or utc_now(), 'summary': summary[:400], 'evidence': evidence or {}}


# The function shape is checked against actual source before evaluating its pure body.
# No import of gen_schedule_stats/unit_truth or execution of module statements.
REGISTRY_BUILDER = '''def _mk_registry():
    rows = []
    for t in TASKS:
        rows.append({"unit": TASK_UNITS[t["task"]], "task": t["task"], "name": t["name"],
                     "kind": "business", "include": True, "display": t["name"]})
    for m in EXTRA_MARKER_SCANS:
        rows.append({"unit": TASK_UNITS[m["task"]], "task": m["task"], "name": m["name"],
                     "kind": "business", "include": True, "display": m["name"]})
    for u in UNIT_ONLY:
        rows.append({**u, "kind": "business", "include": True, "display": u["name"]})
    for s in SELF_MONITOR_UNITS:
        rows.append({**s, "kind": "self_monitor", "include": False, "display": s["name"]})
    return rows
'''


def load_registry(code_root):
    path = source_path(code_root, 'scripts/gen_schedule_stats.py')
    tree = ast.parse(read_bytes(path, 512 * 1024))
    required = {'TASKS', 'TASK_UNITS', 'EXTRA_MARKER_SCANS', 'UNIT_ONLY', 'SELF_MONITOR_UNITS'}
    namespace = {}
    builder = None
    assignment_ok = False
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in required:
                    if target.id in namespace:
                        raise ContractError('registry reassignment')
                    namespace[target.id] = ast.literal_eval(node.value)
                if isinstance(target, ast.Name) and target.id == 'UNIT_REGISTRY':
                    assignment_ok = ast.dump(node.value) == ast.dump(ast.parse('_mk_registry()', mode='eval').body)
        if isinstance(node, ast.FunctionDef) and node.name == '_mk_registry':
            if builder is not None:
                raise ContractError('duplicate builder')
            builder = node
    if set(namespace) != required or builder is None or not assignment_ok:
        raise ContractError('registry contract missing')
    if builder.body and isinstance(builder.body[0], ast.Expr) and isinstance(builder.body[0].value, ast.Constant) and isinstance(builder.body[0].value.value, str):
        builder.body = builder.body[1:]
    trusted = ast.parse(REGISTRY_BUILDER).body[0]
    if ast.dump(builder) != ast.dump(trusted):
        raise ContractError('registry builder changed: review collector adapter')
    namespace['__builtins__'] = {}
    exec(compile(ast.Module(body=[builder], type_ignores=[]), '<verified registry builder>', 'exec'), namespace)
    rows = namespace['_mk_registry']()
    names = [r['unit'] for r in rows]
    if not names or len(rows) > MAX_UNITS or len(set(names)) != len(names) or any(not UNIT_RE.fullmatch(n) for n in names):
        raise ContractError('registry unit set')
    if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,90}', r['task']) or type(r['include']) is not bool for r in rows):
        raise ContractError('registry task set')
    return rows


class CommandRunner:
    """Fixed read-only commands, bounded pipes, hard wall deadline, no shell/env inheritance."""
    def __init__(self, budget, timeout=3):
        self.budget, self.timeout = budget, timeout

    def run(self, args):
        journal = (tuple(args[:-1]) == SELF_JOURNAL and
                   re.fullmatch(r'--since=@[0-9]{1,12}', args[-1] or '') is not None) if args else False
        systemctl = len(args) > 1 and args[0] == '/usr/bin/systemctl' and args[1] in ('show', 'list-unit-files')
        if not (systemctl or journal):
            raise ContractError('command not allowed')
        stop = time.monotonic() + self.budget.remaining(self.timeout)
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C',
                                                             'SYSTEMD_PAGER': '', 'SYSTEMD_COLORS': '0', 'TZ': 'UTC'})
        output = {'out': bytearray(), 'err': bytearray()}
        try:
            with selectors.DefaultSelector() as selector:
                for stream, label in ((proc.stdout, 'out'), (proc.stderr, 'err')):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, label)
                while selector.get_map():
                    left = min(stop - time.monotonic(), self.budget.remaining())
                    if left <= 0:
                        raise LimitError('command timeout')
                    for key, _ in selector.select(min(left, 0.1)):
                        data = os.read(key.fd, 8192)
                        if not data:
                            selector.unregister(key.fileobj)
                            continue
                        output[key.data].extend(data)
                        if sum(map(len, output.values())) > MAX_COMMAND:
                            raise LimitError('command output cap')
                code = proc.wait(timeout=max(0.01, min(stop - time.monotonic(), self.budget.remaining())))
            if code:
                raise ContractError('command failed')
            return output['out'].decode('utf-8', errors='strict')
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=1)
            proc.stdout.close()
            proc.stderr.close()


def parse_properties(text, expected):
    result = {}
    for block in text.strip().split('\n\n'):
        values = {}
        for line in block.splitlines():
            key, sep, value = line.partition('=')
            if not sep or key not in SAFE_PROPS:
                raise ContractError('unexpected systemctl property')
            values.setdefault(key, []).append(value)
        ids = values.get('Id', [])
        if len(ids) != 1 or ids[0] not in expected or ids[0] in result:
            raise ContractError('unexpected unit identity')
        if any(len(vals) != 1 for key, vals in values.items() if key not in ('TimersCalendar', 'TimersMonotonic')):
            raise ContractError('repeated scalar property')
        result[ids[0]] = values
    return result


def first(props, key):
    return props.get(key, [''])[0]


def systemd_time_utc(value):
    """Known cloud CST=Asia/Shanghai; unknown zones/naive inputs stay null."""
    if not value or value in ('n/a', '0'):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    except ValueError:
        pass
    match = re.fullmatch(r'(?:[A-Za-z]{3} )?(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:\.\d+)? (CST|UTC|GMT)', value)
    if not match:
        return None
    try:
        zone = timezone(timedelta(hours=8)) if match[2] == 'CST' else timezone.utc
        return datetime.strptime(match[1], '%Y-%m-%d %H:%M:%S').replace(tzinfo=zone).astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    except ValueError:
        return None


def schedule_time_utc(value):
    # The existing producer emits naive cloud-local timestamps to seconds.
    if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', value):
        value += ' CST'
    return systemd_time_utc(value) if isinstance(value, str) else None


def timestamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() if value else None


def previous_monitor_completion(raw, derived_end, current_start, now, max_age):
    """Bounded journal projection. Never infer completion from app output alone."""
    if len(raw.encode()) > MAX_COMMAND or len(raw.splitlines()) > 64:
        raise LimitError('completion records cap')
    records = [json.loads(line, object_pairs_hook=strict_pairs) for line in raw.splitlines() if line]
    terminals, deliveries = [], []
    for r in records:
        if not isinstance(r, dict):
            raise ContractError('completion record')
        manager = (r.get('_PID') == '1' and r.get('UNIT') == SELF_UNIT
                   and r.get('JOB_TYPE') == 'start' and ('JOB_RESULT' in r or r.get('MESSAGE_ID') in
                       ('39f53479d3a045ac8e11786248231fbf', 'be02cf6855d2428ba40df7e9d022f03d')))
        app = r.get('_SYSTEMD_UNIT') == SELF_UNIT and r.get('SYSLOG_IDENTIFIER') == 'trade-ops-monitor'
        if not manager and not app:
            continue
        usec, boot = r.get('__REALTIME_TIMESTAMP'), r.get('_BOOT_ID')
        if not isinstance(usec, str) or not usec.isdigit() or not isinstance(boot, str) or not re.fullmatch('[a-f0-9]{32}', boot):
            raise ContractError('completion timestamp or boot')
        ts = int(usec) / 1000000
        inv = r.get('INVOCATION_ID' if manager else '_SYSTEMD_INVOCATION_ID')
        if not isinstance(inv, str) or not re.fullmatch('[a-f0-9]{32}', inv):
            # A manager terminal without identity must block borrowing older success.
            if manager:
                raise ContractError('completion invocation')
            continue
        if manager:
            terminals.append((ts, boot, inv, r))
        elif app:
            try:
                msg = json.loads(r.get('MESSAGE', ''), object_pairs_hook=strict_pairs)
                if (isinstance(msg, dict) and msg.get('delivery_ok') is True
                        and msg.get('collect_only') is False and isinstance(msg.get('delivery'), dict)
                        and msg['delivery'].get('http_status') == 200):
                    uuid.UUID(msg['snapshot_id'])
                    deliveries.append((ts, boot, inv))
            except (ValueError, TypeError, KeyError, ContractError):
                pass
    if not terminals:
        return None
    ts, boot, inv, terminal = max(terminals, key=lambda r: r[0])
    if any(t == ts and (b, i, r) != (boot, inv, terminal) for t, b, i, r in terminals):
        return None  # Ambiguous terminal order must not manufacture recovery.
    if not derived_end < ts < current_start <= now or now - ts > max_age:
        return None
    done = (terminal.get('MESSAGE_ID') == '39f53479d3a045ac8e11786248231fbf'
            and terminal.get('JOB_RESULT') == 'done')
    failed = (terminal.get('MESSAGE_ID') == 'be02cf6855d2428ba40df7e9d022f03d'
              and terminal.get('JOB_RESULT') == 'failed')
    if done and not any(b == boot and i == inv and derived_end < t <= ts for t, b, i in deliveries):
        return None
    if not done and not failed:
        return None
    end = datetime.fromtimestamp(ts, timezone.utc).isoformat().replace('+00:00', 'Z')
    return done, end


def calendar_fingerprint(props):
    """SHA256 sorted whitespace-normalized expressions, preserving multiplicity.

    Hash canonical JSON {calendar:[...],monotonic:[...]} with sorted keys and
    compact separators, excluding next_elapse. This is not calendar-equivalence
    reasoning (e.g. different systemd aliases may have different hashes).
    """
    normalized = {'calendar': [], 'monotonic': []}
    for prop, dest in (('TimersCalendar', 'calendar'), ('TimersMonotonic', 'monotonic')):
        for raw in props.get(prop, []):
            if not raw:
                continue
            match = re.fullmatch(r'\{\s*(.*?)\s*;\s*next_elapse=.*?\s*\}', raw)
            if not match or (dest == 'calendar' and not match[1].startswith('OnCalendar=')):
                return None
            normalized[dest].append(' '.join(match[1].split()))
        normalized[dest].sort()
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def exit_matches_success_policy(props):
    code = first(props, 'ExecMainStatus')
    return code == '0' or (first(props, 'ExecMainCode') == '1' and code.isdigit()
                           and code in first(props, 'SuccessExitStatus').split())


def unit_check(name, props):
    timer = name.endswith('.timer')
    cid = ('cloud-timer:' if timer else 'cloud-service:') + name
    category = 'timer' if timer else 'service'
    if not props or first(props, 'LoadState') != 'loaded':
        return check(cid, category, 'unknown', 'Registered unit not observed as loaded')
    active, sub = first(props, 'ActiveState'), first(props, 'SubState')
    result, code, typ = first(props, 'Result'), first(props, 'ExecMainStatus'), first(props, 'Type')
    evidence = {'loaded': True, 'active': active in ('active', 'activating', 'reloading'),
                'failed': active == 'failed'}
    if not timer:
        evidence['last_start_utc'] = systemd_time_utc(first(props, 'ExecMainStartTimestamp'))
        evidence['last_exit_utc'] = systemd_time_utc(first(props, 'ExecMainExitTimestamp'))
        evidence['exit_code'] = int(code) if code.isdigit() else None
        evidence['unit_result'] = result
    if active == 'failed':
        evidence['exit_code'] = int(code) if code.isdigit() else None
        return check(cid, category, 'critical', 'Systemd reports failed; business impact not evaluated', evidence)
    if timer:
        n = sum(bool(v) for v in props.get('TimersCalendar', []) + props.get('TimersMonotonic', []))
        evidence.update(expression_count=n, calendar_sha256=calendar_fingerprint(props),
                        next_elapse_utc=systemd_time_utc(first(props, 'NextElapseUSecRealtime')),
                        last_trigger_utc=systemd_time_utc(first(props, 'LastTriggerUSec')))
        mono = first(props, 'NextElapseUSecMonotonic')
        evidence['next_observed'] = evidence['next_elapse_utc'] is not None or (mono.isdigit() and int(mono) > 0)
        if active != 'active':
            return check(cid, category, 'warning', 'Registered timer is not active', evidence)
        status = 'ok' if n and evidence['next_observed'] and evidence['calendar_sha256'] else 'unknown'
        return check(cid, category, status, 'Timer scheduling state only; job outcome is separate', evidence)
    if active in ('active', 'activating', 'reloading'):
        return check(cid, category, 'ok', 'Unit is executing; this is not completed business validation', evidence)
    has_run = evidence['last_start_utc'] is not None
    evidence['run_record_present'] = has_run
    if typ == 'oneshot' and active == 'inactive':
        if has_run and result == 'success' and exit_matches_success_policy(props):
            if code != '0':
                evidence['accepted_success_exit'] = True
            return check(cid, category, 'ok', 'Oneshot last systemd run succeeded; data correctness not checked', evidence)
        if has_run and ((code.isdigit() and int(code) != 0) or (result and result != 'success')):
            return check(cid, category, 'warning', 'Oneshot previous run was not successful', evidence)
        return check(cid, category, 'unknown', 'Inactive oneshot has no trusted completion record', evidence)
    return check(cid, category, 'unknown', 'Unit state has no implemented success criterion', evidence)


# Only these source paths may be statted. Group IDs follow the34-asset inventory;
# inventory records are a coverage catalogue, NEVER live health evidence.
ASSETS = {
    'data:sentiment-db': ('data/sentiment.db',),
    'data:etf-db': ('data/etf_national_team.db',),
    'data:stock-db': ('data/stock_daily.db',),
    'data:public-fund-db': ('data/public_fund.db',),
    'data:index-daily': (), 'data:score-daily': (), 'data:signal-daily': (),
    'data:history-overwrite-audit': (),
    'data:board-etf-map': ('data/board_etf_map.json',),
    'data:map-inputs': ('data/etf_index_map.json', 'data/etf_track_index.json', 'data/lof_track_index.json'),
    'data:etf-freeze': ('data/signal_kelly_etf_freeze.json',),
    'data:freeze-registries': (), 'data:frozen-missing-audit': (),
    'data:signal-stats-work': ('data/signal_stats.json',),
    'data:signal-stats': ('static-site/data/signal_stats.json',),
    'data:kelly-trades': ('static-site/data/signal_kelly_trades.json',),
    'data:kelly-trades-sdc': ('static-site/data/signal_kelly_trades_sdc.json',),
    'data:kelly-summary': ('static-site/data/signal_kelly_backtest.json',),
    'data:kelly-snapshots': ('static-site/data/signal_kelly_snapshots',),
    'data:schedule-stats': ('static-site/data/schedule_stats.json',),
    'data:runtime-logs': ('data/logs',),
    'data:notify-ledger': ('data/alerts/alert_ledger.jsonl',),
    'data:alert-state': ('data/alerts/latest.md', 'data/alerts/data_gap_alert_state.json'),
    'data:alert-buffers': ('data/alerts/warning_buffer.jsonl', 'data/notify_dedup.json'),
    'data:local-db-backups': ('data/backups',),
    'data:r2-db-backups': (), 'data:preupload-backups': (),
    'data:staticdata-backups': (),
    'data:upload-state': ('data/.r2_all_data_state.json',),
    'data:export-proof': (), 'data:published-data': (), 'data:restore-drill': (),
    'data:code-mirror': (),
    'data:export-manifest': ('static-site/data/export_manifest.json',),
}


class Collector:
    def __init__(self, cfg, budget=None, runner=None, now=None):
        self.cfg = cfg
        self.budget = budget or Budget(cfg.total_timeout_seconds)
        self.runner = runner or CommandRunner(self.budget, cfg.command_timeout_seconds)
        self.now = now or datetime.now(timezone.utc)
        self.checks = []
        self.unit_observations = {}
        self.limitations = ['Operational checks are not business health guarantees',
                            'Asset metadata is not content integrity or business freshness',
                            'Remote publication and backup recoverability are not inferred',
                            'No business entrypoint or database content scan is executed']
        self.counts = {'registry_services': 0, 'services_observed': 0, 'timers_observed': 0,
                       'asset_groups': 0, 'schedule_rows': 0, 'source_errors': 0}

    def add(self, value):
        if len(self.checks) >= MAX_CHECKS - 2:
            self.counts['omitted_checks'] = self.counts.get('omitted_checks', 0) + 1
            return
        self.checks.append(value)

    def guarded(self, cid, category, action):
        try:
            self.budget.remaining()
            return action()
        except Exception as exc:
            self.counts['source_errors'] += 1
            self.add(check(cid, category, 'unknown', 'Collection unavailable; source not assumed healthy',
                           {'error_kind': type(exc).__name__[:64]}))
            return None

    def units(self, rows):
        names = [r['unit'] for r in rows]
        timers = [n.removesuffix('.service') + '.timer' for n in names]
        try:
            raw = self.runner.run(['/usr/bin/systemctl', 'list-unit-files', '--no-pager', '--no-legend', 'trade-*.service', 'trade-*.timer'])
            seen = set()
            for line in raw.splitlines():
                parts = line.split()
                if parts and re.fullmatch(r'trade-[A-Za-z0-9_-]{1,90}\.(service|timer)', parts[0]):
                    seen.add(parts[0])
            wanted = set(names + timers)
            self.add(check('monitor:unit-registration', 'monitor', 'ok' if seen == wanted else 'warning',
                           'Registered and installed unit sets compared',
                           {'registered_count': len(wanted), 'installed_count': len(seen),
                            'missing_count': len(wanted - seen), 'extra_count': len(seen - wanted)}))
        except Exception as exc:
            self.counts['source_errors'] += 1
            self.add(check('monitor:unit-registration', 'monitor', 'unknown', 'Installed unit enumeration unavailable',
                           {'error_kind': type(exc).__name__[:64]}))
        observed = {}
        try:
            text = self.runner.run(['/usr/bin/systemctl', 'show', '--no-pager', '--property=' + ','.join(SAFE_PROPS), *names, *timers])
            observed = parse_properties(text, set(names + timers))
        except Exception as exc:
            self.counts['source_errors'] += 1
            self.add(check('monitor:unit-read', 'monitor', 'unknown', 'Systemd property collection unavailable',
                           {'error_kind': type(exc).__name__[:64]}))
        self.unit_observations = observed
        for name in names + timers:
            props = observed.get(name)
            self.add(unit_check(name, props))
            if props:
                key = 'timers_observed' if name.endswith('.timer') else 'services_observed'
                self.counts[key] += 1

    def assets(self):
        # Extend coverage with new inventory IDs as unknown; never use inventory paths
        # to expand the fixed source whitelist or its historical health/status fields.
        ids = set(ASSETS)
        try:
            self.budget.remaining()
            obj = read_json(source_path(self.cfg.code_root, 'docs/ops/architecture/inventory/data_assets.json'))
            extra = {r['id'] for r in obj['records'] if re.fullmatch(r'data:[A-Za-z0-9_.:-]{1,100}', r['id'])}
            if len(extra) > 60:
                raise LimitError('asset catalogue cap')
            ids.update(extra)
        except Exception:
            self.counts['source_errors'] += 1
            self.add(check('monitor:asset-catalogue', 'monitor', 'unknown', 'Historical coverage catalogue unavailable; fixed asset groups still reported'))
        for cid in sorted(ids):
            count, sizes, denied = 0, 0, 0
            relatives = ASSETS.get(cid, ())
            try:
                self.budget.remaining()
                for relative in relatives:
                    try:
                        s = source_path(self.cfg.data_root, relative).stat()
                        if stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode):
                            count += 1
                            if stat.S_ISREG(s.st_mode):
                                sizes += s.st_size
                    except FileNotFoundError:
                        pass
                    except OSError:
                        denied += 1
                summary = ('Fixed asset metadata observed; content correctness and business freshness unknown'
                           if count else 'Asset content unverified; fixed source absent or outside lightweight scope')
                self.add(check(cid, 'data', 'unknown', summary,
                               {'fixed_sources': len(relatives), 'observed_sources': count, 'bytes': sizes,
                                'unreadable_sources': denied, 'content_verified': False}))
            except Exception as exc:
                self.counts['source_errors'] += 1
                self.add(check(cid, 'data', 'unknown', 'Asset observation budget unavailable', {'error_kind': type(exc).__name__[:64]}))
        self.counts['asset_groups'] = len(ids)

    def schedule(self, rows):
        try:
            self.budget.remaining()
            path = source_path(self.cfg.data_root, 'static-site/data/schedule_stats.json')
            obj = read_json(path)
            age = self.now.timestamp() - path.stat().st_mtime
            if not isinstance(obj, list) or len(obj) > MAX_UNITS:
                raise ContractError('schedule array')
            by_task = {}
            for item in obj:
                if not isinstance(item, dict) or not isinstance(item.get('task'), str) or item['task'] in by_task:
                    raise ContractError('schedule task identity')
                by_task[item['task']] = item
            trusted = -120 <= age <= self.cfg.schedule_max_age_seconds
            self.add(check('monitor:schedule-input', 'monitor', 'ok' if trusted else 'unknown',
                           'Derived schedule input age only; not market or asset freshness',
                           {'source_age_seconds': max(0, int(age)), 'within_observation_window': trusted, 'rows': len(obj)}))
        except Exception as exc:
            self.counts['source_errors'] += 1
            trusted, by_task = False, {}
            self.add(check('monitor:schedule-input', 'monitor', 'unknown', 'Derived schedule input unavailable', {'error_kind': type(exc).__name__[:64]}))
        for row in rows:
            if not row['include']:
                continue
            item = by_task.get(row['task'], {})
            cid = 'schedule:' + row['task']
            status, summary = 'unknown', 'No current trusted derived execution verdict'
            src = item.get('unit_exit_source') or item.get('exit_source')
            trusted_exit = src in ('systemd', 'ledger', 'log_explicit', 'log_deploy')
            code = item.get('last_exit')
            evidence = {'row_present': bool(item), 'source_current': trusted,
                        'trusted_exit_origin': trusted_exit, 'exit_conflict': item.get('exit_conflict') is True}
            evidence.update(derived_start_utc=schedule_time_utc(item.get('unit_start')),
                            derived_exit_utc=schedule_time_utc(item.get('unit_exit_ts')),
                            derived_exit_code=code if type(code) is int else None)
            if trusted and item:
                if item.get('exit_conflict') is True:
                    status, summary = 'warning', 'Derived exit evidence conflicts; not auto-resolved'
                elif item.get('unit_missed') is True or item.get('unit_timer_health') == 'missed':
                    status, summary = 'warning', 'Existing schedule producer reports a missed execution'
                elif item.get('log_anomaly') is True:
                    status, summary = 'warning', 'Existing schedule producer reports an anomaly; details withheld'
                elif item.get('round_state') == 'started_unfinished':
                    status, summary = self.unfinished_schedule(row, item, evidence)
                elif trusted_exit and type(code) is int:
                    evidence['exit_code'] = code
                    status = 'ok' if code == 0 else 'warning'
                    summary = 'Trusted derived execution verdict; no business data validation'
                    reconciled = self.completed_schedule(row, item, evidence)
                    if reconciled is not None:
                        status, summary = reconciled
            self.add(check(cid, 'monitor', status, summary, evidence))
            self.counts['schedule_rows'] += 1

    def completed_schedule(self, row, item, evidence):
        """Reconcile a completed derived round, never clear flags or rewrite history."""
        old_start = timestamp(evidence['derived_start_utc'])
        old_end = timestamp(evidence['derived_exit_utc'])
        if (item.get('unit') != row['unit'] or item.get('unit_exit_source') not in ('systemd', 'ledger')
                or old_start is None or old_end is None or not old_start <= old_end <= self.now.timestamp()):
            return None
        props = self.unit_observations.get(row['unit']) or {}
        if first(props, 'LoadState') != 'loaded' or first(props, 'Type') != 'oneshot':
            return None
        start = timestamp(systemd_time_utc(first(props, 'ExecMainStartTimestamp')))
        end_utc = systemd_time_utc(first(props, 'ExecMainExitTimestamp'))
        end = timestamp(end_utc)
        active = first(props, 'ActiveState')
        if active in ('active', 'activating', 'reloading'):
            evidence['execution_state'] = 'running'
            # The collector always observes its own current invocation running.
            # Require an earlier delivery ACK AND its matching manager completion.
            if row['unit'] == SELF_UNIT and start is not None:
                try:
                    since = int(self.now.timestamp() - self.cfg.schedule_max_age_seconds)
                    raw = self.runner.run([*SELF_JOURNAL, '--since=@' + str(since)])
                    completed = previous_monitor_completion(raw, old_end, start, self.now.timestamp(),
                                                            self.cfg.schedule_max_age_seconds)
                except Exception as exc:
                    evidence['completion_error_kind'] = type(exc).__name__[:64]
                    completed = None
                if completed:
                    success, end_utc = completed
                    evidence.update(completion_source='systemd_journal', completed_at_utc=end_utc,
                                    latest_completed_success=success, exit_code=0 if success else None,
                                    recovery_verified=success and item.get('last_exit') != 0)
                    return ('ok' if success else 'warning',
                            'Previous monitor delivery and completed invocation verified; current invocation still running')
                if item.get('last_exit') == 0:
                    return 'unknown', 'Monitor is running; no fresh completed delivery proof'
            # Running alone never clears an existing failure.
            return None
        if (active not in ('inactive', 'failed') or start is None or end is None
                or not old_end < start <= end <= self.now.timestamp()
                or self.now.timestamp() - end > self.cfg.schedule_max_age_seconds):
            return None
        code = first(props, 'ExecMainStatus')
        success = (active == 'inactive' and first(props, 'SubState') == 'dead'
                   and first(props, 'ExecMainCode') == '1' and first(props, 'Result') == 'success'
                   and exit_matches_success_policy(props))
        failure = (active == 'failed' or first(props, 'Result') not in ('', 'success')
                   or (code.isdigit() and int(code) != 0 and not success))
        if not success and not failure:
            return None
        evidence.update(completion_source='systemd_live', completed_at_utc=end_utc,
                        exit_code=int(code) if code.isdigit() else None,
                        execution_state='completed' if success else 'failed',
                        recovery_verified=success and item.get('last_exit') != 0)
        if success and code != '0':
            evidence['accepted_success_exit'] = True
        return ('ok' if success else 'warning',
                'Newer completed systemd round reconciles derived history; no business data validation')

    def unfinished_schedule(self, row, item, evidence):
        # Reuse the bounded live unit observation; a start recorded by the
        # schedule producer is not itself a failure or a completed success.
        props = self.unit_observations.get(row['unit']) or {}
        if first(props, 'LoadState') == 'loaded':
            if first(props, 'ActiveState') in ('active', 'activating', 'reloading'):
                evidence['execution_state'] = 'running'
                return 'unknown', 'Scheduled unit is running; completion not yet observed'
            start = systemd_time_utc(first(props, 'ExecMainStartTimestamp'))
            end = systemd_time_utc(first(props, 'ExecMainExitTimestamp'))
            raw_round = item.get('round_start_ts')
            if isinstance(raw_round, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', raw_round):
                raw_round += ' CST'
            round_start = systemd_time_utc(raw_round) if isinstance(raw_round, str) else None
            same_round = bool(start and round_start and start == round_start)
            evidence['same_round'] = same_round
            if (same_round and end and first(props, 'Type') == 'oneshot'
                    and first(props, 'ActiveState') == 'inactive'
                    and first(props, 'Result') == 'success' and exit_matches_success_policy(props)
                    and datetime.fromisoformat(end.replace('Z', '+00:00'))
                    >= datetime.fromisoformat(start.replace('Z', '+00:00'))
                    and datetime.fromisoformat(end.replace('Z', '+00:00')) <= self.now):
                evidence.update(execution_state='completed', exit_code=int(first(props, 'ExecMainStatus')),
                                trusted_exit_origin=True, completion_source='systemd_live')
                if evidence['exit_code'] != 0:
                    evidence['accepted_success_exit'] = True
                return 'ok', 'Scheduled round completed after derived snapshot; data correctness not checked'
            code = first(props, 'ExecMainStatus')
            if same_round and (first(props, 'ActiveState') == 'failed'
                               or first(props, 'Result') not in ('', 'success')
                               or (code.isdigit() and int(code) != 0)):
                evidence.update(execution_state='failed', trusted_exit_origin=True,
                                completion_source='systemd_live')
                if code.isdigit():
                    evidence['exit_code'] = int(code)
                return 'warning', 'Scheduled round failed according to current systemd evidence'
        evidence['execution_state'] = 'pending'
        return 'unknown', 'Unfinished scheduled round has no verified completion'

    def backups(self):
        try:
            self.budget.remaining()
            directory = source_path(self.cfg.data_root, 'data/backups')
            latest = {}
            with os.scandir(directory) as entries:
                for i, entry in enumerate(entries):
                    self.budget.remaining()
                    if i >= 1024:
                        raise LimitError('backup directory budget')
                    m = re.fullmatch(r'(sentiment|etf_national_team|stock_daily)_\d{8}_\d{4,6}\.db', entry.name)
                    if m and entry.is_file(follow_symlinks=False):
                        s = entry.stat(follow_symlinks=False)
                        if m[1] not in latest or s.st_mtime > latest[m[1]].st_mtime:
                            latest[m[1]] = s
            for family in ('sentiment', 'etf_national_team', 'stock_daily'):
                s = latest.get(family)
                self.add(check('backup:local-' + family, 'backup', 'unknown',
                               'Default local backup metadata only; remote copy and restore validity unknown',
                               {'present': s is not None, 'bytes': s.st_size if s else 0,
                                'age_seconds': max(0, int(self.now.timestamp() - s.st_mtime)) if s else None,
                                'restore_verified': False}))
        except Exception as exc:
            self.counts['source_errors'] += 1
            for family in ('sentiment', 'etf_national_team', 'stock_daily'):
                self.add(check('backup:local-' + family, 'backup', 'unknown', 'Default local backup observation unavailable',
                               {'error_kind': type(exc).__name__[:64]}))
        def ledger():
            obj = read_json(source_path(self.cfg.data_root, 'data/.r2_db_backup_state.json'), 256 * 1024)
            if not isinstance(obj, dict):
                raise ContractError('backup ledger')
            present = sum(isinstance(obj.get(k), dict) for k in ('sentiment.db', 'etf_national_team.db', 'stock_daily.db', 'public_fund.db'))
            self.add(check('backup:remote-ledger', 'backup', 'unknown', 'Backup ledger exists; remote objects and restoration not verified', {'known_database_entries': present, 'remote_verified': False}))
        self.guarded('backup:remote-ledger', 'backup', ledger)

    def resources(self):
        def disk():
            s = shutil.disk_usage(self.cfg.data_root)
            fraction = s.free / s.total
            self.add(check('resource:runtime-disk', 'resource', 'critical' if fraction < .05 else 'warning' if fraction < .15 else 'ok',
                           'Filesystem free capacity only; workload health is separate', {'free_bytes': s.free, 'total_bytes': s.total}))
        def memory():
            text = read_bytes(Path('/proc/meminfo'), 64 * 1024).decode()
            found = {m[1]: int(m[2]) * 1024 for m in re.finditer(r'(?m)^(MemTotal|MemAvailable):\s+(\d+) kB$', text)}
            total, available = found['MemTotal'], found['MemAvailable']
            if total <= 0 or not 0 <= available <= total:
                raise ContractError('memory values')
            self.add(check('resource:memory', 'resource', 'warning' if available / total < .1 else 'ok',
                           'Point memory availability; no trend inference', {'total_bytes': total, 'available_bytes': available}))
        def load():
            average = os.getloadavg()[0]
            cpus = os.cpu_count()
            if not cpus or not math.isfinite(average):
                raise ContractError('load values')
            self.add(check('resource:load', 'resource', 'warning' if average > cpus * 2 else 'ok',
                           'Point system load only', {'load_one_minute': average, 'cpu_count': cpus}))
        for cid, fn in (('resource:runtime-disk', disk), ('resource:memory', memory), ('resource:load', load)):
            self.guarded(cid, 'resource', fn)

    def collect(self):
        rows = self.guarded('monitor:registry', 'monitor', lambda: load_registry(self.cfg.code_root))
        if rows is not None:
            self.counts['registry_services'] = len(rows)
            self.add(check('monitor:registry', 'monitor', 'ok', 'Actual registry contract loaded without importing its generator', {'registered_services': len(rows)}))
            self.units(rows)
        self.assets()
        self.schedule(rows or [])
        self.backups()
        self.resources()
        self.add(check('publication:served-content', 'publication', 'unknown', 'External content and deployed event membership are not inferred from local metadata', {'content_verified': False}))
        return self.snapshot()

    def snapshot(self):
        if self.counts.get('omitted_checks'):
            self.checks.append(check('monitor:coverage-limit', 'monitor', 'unknown', 'Coverage exceeded bounded snapshot capacity', {'omitted_checks': self.counts['omitted_checks']}))
        return {'schema_version': 1, 'snapshot_id': str(uuid.uuid4()), 'collector_id': self.cfg.collector_id,
                'collected_at': utc_now(), 'code_ref': code_ref(self.cfg.code_root),
                'duration_ms': max(0, int((self.budget.clock() - self.budget.started) * 1000)),
                'checks': self.checks,
                'coverage': {'counts': dict(self.counts, checks=len(self.checks), **Counter(c['status'] for c in self.checks)),
                             'limitations': self.limitations}}


def code_ref(root):
    try:
        git = Path(root) / '.git'
        if git.is_file():
            text = read_bytes(git, 4096).decode().strip()
            if not text.startswith('gitdir: '):
                return 'unknown'
            git = (Path(root) / text[8:]).resolve()
        head = read_bytes(git / 'HEAD', 4096).decode().strip()
        if re.fullmatch('[a-f0-9]{40}', head):
            return head
        if not head.startswith('ref: refs/'):
            return 'unknown'
        ref = head[5:]
        if '..' in ref.split('/'):
            return 'unknown'
        bases = [git]
        if (git / 'commondir').is_file():
            bases.append((git / read_bytes(git / 'commondir', 4096).decode().strip()).resolve())
        for base in bases:
            try:
                value = read_bytes(base / ref, 4096).decode().strip()
                if re.fullmatch('[a-f0-9]{40}', value):
                    return value
            except OSError:
                pass
            try:
                for line in read_bytes(base / 'packed-refs', 256 * 1024).decode().splitlines():
                    if line.endswith(' ' + ref) and re.fullmatch('[a-f0-9]{40}', line[:40]):
                        return line[:40]
            except OSError:
                pass
    except Exception:
        pass
    return 'unknown'


def validate_snapshot(obj):
    """Mirror the ingest safety contract; reject before caching or sending."""
    expected = {'schema_version', 'snapshot_id', 'collector_id', 'collected_at', 'code_ref', 'duration_ms', 'checks', 'coverage'}
    if set(obj) != expected or obj['schema_version'] != 1:
        raise ContractError('snapshot fields')
    uuid.UUID(obj['snapshot_id'])
    if not re.fullmatch(r'[a-z0-9_-]{1,48}', obj['collector_id']):
        raise ContractError('collector id')
    if obj['code_ref'] != 'unknown' and not re.fullmatch('[a-f0-9]{40}', obj['code_ref']):
        raise ContractError('code ref')
    if type(obj['duration_ms']) is not int or not 0 <= obj['duration_ms'] <= 86400000:
        raise ContractError('duration')
    datetime.fromisoformat(obj['collected_at'].replace('Z', '+00:00'))
    coverage = obj['coverage']
    if set(coverage) != {'counts', 'limitations'} or not isinstance(coverage['counts'], dict) or len(coverage['counts']) > 30:
        raise ContractError('coverage')
    if any(type(v) is not int or v < 0 for v in coverage['counts'].values()):
        raise ContractError('coverage counts')
    if not isinstance(coverage['limitations'], list) or len(coverage['limitations']) > 20:
        raise ContractError('limitations')
    if any(not isinstance(v, str) or len(v) > 400 for v in coverage['limitations']):
        raise ContractError('limitation text')
    if not isinstance(obj['checks'], list) or len(obj['checks']) > MAX_CHECKS:
        raise ContractError('checks')
    ids = set()
    for c in obj['checks']:
        if set(c) != {'id', 'name', 'category', 'status', 'observed_at', 'summary', 'evidence'}:
            raise ContractError('check keys')
        if not re.fullmatch(r'[A-Za-z0-9:._-]{1,120}', c['id']) or c['id'] in ids:
            raise ContractError('check identity')
        ids.add(c['id'])
        if c['category'] not in ('service', 'timer', 'data', 'publication', 'backup', 'resource', 'monitor') or c['status'] not in ('ok', 'warning', 'critical', 'unknown'):
            raise ContractError('check enums')
        for key, cap in (('name', 160), ('summary', 400)):
            if not isinstance(c[key], str) or len(c[key]) > cap or re.search(r'https?://|/(?:home|Users|tmp|root|etc)/', c[key]):
                raise ContractError('unsafe text')
        datetime.fromisoformat(c['observed_at'].replace('Z', '+00:00'))
        if not isinstance(c['evidence'], dict) or len(c['evidence']) > 20:
            raise ContractError('evidence')
        for k, v in c['evidence'].items():
            if not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}', k) or re.search(r'token|secret|password|credential|authorization|cookie|argv|env|path|log|email|webhook|stack', k, re.I):
                raise ContractError('unsafe evidence key')
            if isinstance(v, str):
                if len(v) > 400 or '/' in v or '\\' in v or re.search(r'https?://|Bearer\s', v, re.I):
                    raise ContractError('unsafe evidence text')
            elif v is not None and type(v) not in (bool, int, float):
                raise ContractError('evidence scalar')
            elif isinstance(v, (int, float)) and not math.isfinite(v):
                raise ContractError('nonfinite')
    encoded = json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    if len(encoded) > MAX_SNAPSHOT:
        raise LimitError('snapshot size')
    return encoded


def endpoint(url, head=False, test_local=False):
    parsed = urlsplit(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ContractError('endpoint components')
    allowed_path = parsed.path in HEAD_PATHS if head else parsed.path == '/api/ops/ingest'
    if not allowed_path:
        raise ContractError('endpoint route')
    if test_local and parsed.scheme == 'http' and parsed.hostname == '127.0.0.1' and parsed.port and parsed.port >= 1024:
        return parsed
    if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_HOSTS or parsed.port not in (None, 443):
        raise ContractError('endpoint allowlist')
    return parsed


def read_secret(path):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        s = os.fstat(stream.fileno())
        if not stat.S_ISREG(s.st_mode) or stat.S_IMODE(s.st_mode) not in (0o400, 0o600) or s.st_uid not in (0, os.geteuid()) or s.st_size > 1024:
            raise ContractError('protected credential file required')
        token = stream.read(1025).decode('ascii').strip()
    if not re.fullmatch(r'[A-Za-z0-9_.~+/-]{16,512}={0,2}', token):
        raise ContractError('credential format')
    return token


def request_http(url, payload=None, secret_file=None, head=False, test_local=False, timeout=5):
    """No redirects, no response-body export, certificate verification mandatory."""
    target = endpoint(url, head=head, test_local=test_local)
    headers = {'Accept': 'application/json'}
    if not head:
        headers['Authorization'] = 'Bearer ' + read_secret(secret_file)
        headers['Content-Type'] = 'application/json'
    connection = (http.client.HTTPConnection(target.hostname, target.port, timeout=timeout)
                  if target.scheme == 'http' else
                  http.client.HTTPSConnection(target.hostname, target.port or 443, timeout=timeout, context=ssl.create_default_context()))
    try:
        connection.request('HEAD' if head else 'POST', target.path, body=payload, headers=headers)
        response = connection.getresponse()
        # Response may contain secrets/error bodies: don't return/print them.
        body = response.read(4097)
        if len(body) > 4096:
            raise LimitError('response size')
        ok = 200 <= response.status < 300
        result = {'ok': ok, 'http_status': int(response.status)}
        if ok and not head:
            try:
                ack = json.loads(body, object_pairs_hook=strict_pairs)
                sent_id = json.loads(payload)['snapshot_id']
                result['ok'] = isinstance(ack, dict) and ack.get('accepted') is True and ack.get('snapshot_id') == sent_id
            except (ValueError, UnicodeError, ContractError):
                result['ok'] = False
            if not result['ok']:
                result['error_kind'] = 'ProtocolError'
        elif not head:
            # Error bodies are untrusted. Only literal whitelist values survive;
            # edge HTML/unknown errors retain the HTTP status without reflection.
            try:
                error = json.loads(body, object_pairs_hook=strict_pairs)
            except (ValueError, UnicodeError, ContractError):
                error = None
            if isinstance(error, dict):
                for key, allowed in (('error', DELIVERY_ERRORS), ('error_kind', SERVER_ERROR_KINDS)):
                    if isinstance(error.get(key), str) and error[key] in allowed:
                        result[key] = error[key]
        return result
    finally:
        connection.close()


def network_error_kind(exc):
    # Never export arbitrary exception names/messages or retry TLS/config errors.
    if isinstance(exc, TimeoutError):
        return 'TimeoutError'
    if isinstance(exc, (ConnectionError, http.client.RemoteDisconnected)):
        return 'ConnectionError'
    if isinstance(exc, OSError) and exc.errno in (errno.EAGAIN, errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ECONNRESET, errno.ECONNREFUSED):
        return 'ConnectionError'
    if isinstance(exc, (http.client.HTTPException, ValueError, UnicodeError)):
        return 'ProtocolError'
    if isinstance(exc, LimitError):
        return 'LimitError'
    if isinstance(exc, ContractError):
        return 'ContractError'
    return 'NetworkError'


def _network_worker(pipe, url, payload, secret_file, head, test_local, deadline):
    # One attempt only: the parent enforces wall time across DNS/TLS/trickle reads.
    try:
        left = deadline - time.monotonic()
        if left <= 0:
            result = {'ok': False, 'error_kind': 'TimeoutError'}
        else:
            result = request_http(url, payload, secret_file, head, test_local, timeout=min(5, left))
    except Exception as exc:
        result = {'ok': False, 'error_kind': network_error_kind(exc)}
    try:
        pipe.send(result)
    finally:
        pipe.close()


def network_bounded(budget, url, payload=None, secret_file=None, head=False, test_local=False):
    # Preserve the original total deadline; use its remaining budget, not a
    # second fixed 8s ceiling. Every retry reuses identical payload bytes/ID.
    endpoint(url, head=head, test_local=test_local)
    started = time.monotonic()
    deadline = started + max(0, budget.remaining() - .15)
    context = multiprocessing.get_context('spawn')
    result = {'ok': False, 'error_kind': 'NetworkDeadline', 'attempts': 0}
    for attempt in range(1, 2 if head else 4):
        if deadline - time.monotonic() <= .15:
            result['deadline_exhausted'] = True
            break
        attempt_deadline = min(deadline, time.monotonic() + 5)
        receive, send = context.Pipe(duplex=False)
        proc = context.Process(target=_network_worker,
                               args=(send, url, payload, secret_file, head, test_local, attempt_deadline))
        try:
            proc.start()
            send.close()
            if receive.poll(max(0, attempt_deadline - time.monotonic())):
                try:
                    result = receive.recv()
                except EOFError:
                    result = {'ok': False, 'error_kind': 'NetworkError'}
            else:
                result = {'ok': False, 'error_kind': 'TimeoutError', 'attempt_deadline_exceeded': True}
        finally:
            if proc.pid is not None:
                proc.join(timeout=.01)
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=.1)
            receive.close()
            send.close()
        result['attempts'] = attempt
        kind = result.get('error_kind')
        retry = (kind in ('TimeoutError', 'ConnectionError') or result.get('http_status') in (502, 503, 504))
        if (head or result['ok'] or not retry or kind in NONRETRY_KINDS or
                result.get('error') in ('ingest_not_configured', 'ops_token_configuration_invalid') or attempt == 3):
            break
        delay = .15 * 2 ** (attempt - 1)
        if deadline - time.monotonic() <= delay + .15:
            result['deadline_exhausted'] = True
            break
        time.sleep(delay)
    result['elapsed_ms'] = int((time.monotonic() - started) * 1000)
    return result


def atomic_private_json(directory, filename, obj):
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    ds = directory.lstat()
    if not stat.S_ISDIR(ds.st_mode) or ds.st_uid != os.geteuid() or stat.S_IMODE(ds.st_mode) & 0o077:
        raise ContractError('private output directory required')
    fd, tmp = tempfile.mkstemp(prefix='.' + filename + '-', dir=directory)
    try:
        with os.fdopen(fd, 'w') as out:
            os.fchmod(out.fileno(), 0o600)
            json.dump(obj, out, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, directory / filename)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def _benefits_worker(pipe, data_root, output_dir, now):
    # Dedicated child bounds even stalled filesystem reads/SQLite writes. It never
    # receives credentials, imports producers, or performs network operations.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from ops.monitoring import benefits
        result = benefits.sample(data_root, now=datetime.fromisoformat(now), seconds=0.8)
        benefits.persist(output_dir, result)
        checks = [benefits.wire(record) for record in result['records']]
        if not checks:
            checks = [check('monitor:benefits', 'monitor', 'unknown',
                            'Delivery policy or inventory unavailable; observations stored locally',
                            {'configured': False})]
        encoded = json.dumps(checks, allow_nan=False).encode()
        if len(encoded) > 24 * 1024:
            raise LimitError('benefit result size')
        pipe.send_bytes(encoded)
    except Exception:
        pipe.send_bytes(b'[]')
    finally:
        pipe.close()


def benefits_bounded(cfg, budget):
    seconds = budget.remaining(2)
    stop = budget.clock() + seconds
    if seconds < 0.2:
        raise LimitError('benefits skipped for upload reserve')
    context = multiprocessing.get_context('spawn')
    receive, send = context.Pipe(duplex=False)
    proc = context.Process(target=_benefits_worker,
                           args=(send, cfg.data_root, cfg.output_dir, utc_now()))
    try:
        proc.start()
        send.close()
        if receive.poll(max(0, stop - budget.clock() - 0.15)):
            return json.loads(receive.recv_bytes(24 * 1024))
        return []
    finally:
        if proc.pid is not None:
            proc.join(timeout=0.01)
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=0.1)
        receive.close()
        send.close()


def append_benefits(snapshot, cfg, budget):
    try:
        checks = benefits_bounded(cfg, budget)
    except Exception:
        checks = []
    if not checks:
        checks = [check('monitor:benefits', 'monitor', 'unknown',
                        'Delivery evidence unavailable within collection budget')]
    for value in checks:
        # Keep original checks and optional publication check capacity. New
        # evidence can never displace operational coverage or prevent upload.
        if len(snapshot['checks']) >= MAX_CHECKS - 1:
            break
        candidate = dict(snapshot, checks=snapshot['checks'] + [value])
        try:
            validate_snapshot(candidate)
        except (ContractError, LimitError, ValueError, TypeError):
            continue
        snapshot['checks'].append(value)


def run_once(cfg, collect_only=False, test_local_http=False):
    total_budget = Budget(cfg.total_timeout_seconds)
    collection_budget = Budget(cfg.total_timeout_seconds)
    collection_budget.started = total_budget.started
    collection_budget.deadline = total_budget.deadline if collect_only else total_budget.deadline - 8
    collector = Collector(cfg, budget=collection_budget)
    snapshot = collector.collect()
    if cfg.benefits_enabled:
        append_benefits(snapshot, cfg, collection_budget)
    if cfg.publication_head_url and not collect_only and total_budget.deadline - total_budget.clock() > 8.5:
        try:
            head_budget = Budget(2)
            head_budget.deadline = min(head_budget.deadline, total_budget.deadline - 8)
            result = network_bounded(head_budget, cfg.publication_head_url, head=True, test_local=test_local_http)
            snapshot['checks'].append(check('publication:transport', 'publication', 'ok' if result.get('ok') else 'unknown',
                                            'HTTPS HEAD transport observation only; content correctness unknown',
                                            {'reachable': result.get('ok', False), 'http_status': result.get('http_status')}))
        except Exception as exc:
            snapshot['checks'].append(check('publication:transport', 'publication', 'unknown', 'Publication transport observation unavailable', {'error_kind': type(exc).__name__[:64]}))
    elif cfg.publication_head_url:
        snapshot['checks'].append(check('publication:transport', 'publication', 'unknown', 'Optional transport probe skipped to preserve upload budget or collect-only mode'))
    snapshot['duration_ms'] = int((total_budget.clock() - total_budget.started) * 1000)
    snapshot['coverage']['counts']['checks'] = len(snapshot['checks'])
    snapshot['coverage']['counts'].update({key: 0 for key in ('ok', 'warning', 'critical', 'unknown')})
    snapshot['coverage']['counts'].update(Counter(c['status'] for c in snapshot['checks']))
    payload = validate_snapshot(snapshot)
    atomic_private_json(cfg.output_dir, 'snapshot.json', snapshot)
    delivery = {'ok': False, 'state': 'collect_only'}
    if not collect_only:
        try:
            delivery = network_bounded(total_budget, cfg.ingest_url, payload, cfg.secret_file, test_local=test_local_http)
        except Exception as exc:
            delivery = {'ok': False, 'error_kind': network_error_kind(exc)}
    report = {'snapshot_id': snapshot['snapshot_id'], 'collector_id': cfg.collector_id,
              'completed_at': utc_now(), 'coverage': snapshot['coverage'], 'delivery': delivery,
              'duration_ms': int((total_budget.clock() - total_budget.started) * 1000)}
    atomic_private_json(cfg.output_dir, 'report.json', report)
    return report, 0 if collect_only or delivery.get('ok') else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, help='Collector JSON configuration; never a token value')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--once', action='store_true', help='Collect one snapshot; bounded transient delivery retries, no deployment')
    mode.add_argument('--collect-only', action='store_true', help='Collect to private files; all outbound requests disabled')
    parser.add_argument('--token-file', help='Override protected token file, including systemd LoadCredential file')
    parser.add_argument('--test-local-http', action='store_true', help='Explicit test-only HTTP allowance for127.0.0.1 high port')
    args = parser.parse_args(argv)
    try:
        cfg = Settings.load(args.config)
        if args.token_file:
            if not Path(args.token_file).is_absolute():
                raise ContractError('absolute token file required')
            cfg.secret_file = args.token_file
        endpoint(cfg.ingest_url, test_local=args.test_local_http)
        if cfg.publication_head_url:
            endpoint(cfg.publication_head_url, head=True, test_local=args.test_local_http)
        report, code = run_once(cfg, collect_only=args.collect_only, test_local_http=args.test_local_http)
        print(json.dumps({'snapshot_id': report['snapshot_id'], 'checks': report['coverage']['counts']['checks'],
                          'delivery_ok': report['delivery'].get('ok', False), 'collect_only': args.collect_only,
                          'delivery': {key: report['delivery'][key] for key in ('http_status', 'error_kind', 'attempts', 'elapsed_ms',
                                                                          'deadline_exhausted', 'attempt_deadline_exceeded')
                                       if key in report['delivery']}}))
        return code
    except Exception as exc:
        # Error messages can contain URLs/paths/response text: expose exception class only.
        print('ops_monitor: operation failed (' + type(exc).__name__[:64] + ')', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
