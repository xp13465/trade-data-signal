#!/usr/bin/env python3
"""只读捕获两条QVIX全历史，或离线核对两个点时快照；不发送通知。"""
import argparse
import datetime as dt
import json
import math
import posixpath
import sqlite3
import sys
import time
from pathlib import Path

METRICS = frozenset(('a_qvix_300', 'a_qvix_1000'))
FIELDS = ('date', 'metric_id', 'value', 'source', 'updated_at')
MAX_ROWS = 100_000
MAX_BYTES = 16 * 1024 * 1024
QUERY_SECONDS = 3.0


def utc_time(value):
    if not isinstance(value, str):
        raise ValueError('captured_at_utc必须是UTC时间字符串')
    stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.utcoffset() != dt.timedelta(0):
        raise ValueError('captured_at_utc必须显式为UTC')
    return stamp


def validate(snapshot):
    if not isinstance(snapshot, dict) or set(snapshot) != {
        'schema_version', 'database_realpath', 'captured_at_utc', 'rows'
    }:
        raise ValueError('快照顶层字段不符合schema_version=1')
    if type(snapshot['schema_version']) is not int or snapshot['schema_version'] != 1:
        raise ValueError('schema_version必须为整数1')
    identity = snapshot['database_realpath']
    if (not isinstance(identity, str) or not identity.startswith('/')
            or identity.startswith('//') or '\x00' in identity
            or posixpath.normpath(identity) != identity):
        raise ValueError('database_realpath必须是规范绝对路径')
    utc_time(snapshot['captured_at_utc'])
    rows = snapshot['rows']
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError('rows须为数组且不超过100000行，禁止截断')
    seen, metrics = set(), set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(FIELDS):
            raise ValueError('每行必须完整包含date/metric_id/value/source/updated_at')
        date, metric = row['date'], row['metric_id']
        if not isinstance(date, str) or len(date) != 8 or not date.isascii() or not date.isdigit():
            raise ValueError('date必须是YYYYMMDD')
        dt.datetime.strptime(date, '%Y%m%d')
        if not isinstance(metric, str) or metric not in METRICS:
            raise ValueError('只接受两条指定QVIX指标')
        key = date, metric
        if key in seen:
            raise ValueError('重复日期指标键: '+str(key))
        seen.add(key)
        metrics.add(metric)
        value = row['value']
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
            raise ValueError('value必须是有限数值或null，不能是bool')
        for field in ('source', 'updated_at'):
            if row[field] is not None and not isinstance(row[field], str):
                raise ValueError(field+'必须是字符串或null')
    if metrics != METRICS:
        raise ValueError('快照必须包含两条指标；空/单指标导出不能作为完整上下文')
    return snapshot


def compact(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def capture(path):
    resolved = Path(path).resolve(strict=True)
    deadline = time.monotonic() + QUERY_SECONDS
    # mode=ro不会创建缺失数据库；不使用immutable，避免忽略现有WAL。
    conn = sqlite3.connect(resolved.as_uri()+'?mode=ro', uri=True, timeout=0.1)
    try:
        conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        conn.execute('PRAGMA query_only=ON')
        rows = conn.execute(
            'SELECT date,metric_id,value,source,updated_at FROM daily_metric '
            'WHERE metric_id IN (?,?) ORDER BY metric_id,date LIMIT ?',
            (*sorted(METRICS), MAX_ROWS+1),
        ).fetchall()
    finally:
        conn.close()
    snapshot = validate({'schema_version': 1, 'database_realpath': str(resolved),
                         'captured_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                         'rows': [dict(zip(FIELDS, row)) for row in rows]})
    if len(compact(snapshot).encode('utf-8')) > MAX_BYTES:
        raise ValueError('捕获超过16MiB，未输出截断快照')
    return snapshot


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('重复JSON字段: '+key)
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError('非法JSON数值: '+value)


def load_snapshot(path):
    with open(path, 'rb') as handle:
        raw = handle.read(MAX_BYTES+1)
    if len(raw) > MAX_BYTES:
        raise ValueError('快照超过16MiB，禁止截断解析')
    return validate(json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant))


def compare(baseline, current):
    validate(baseline)
    validate(current)
    if baseline['database_realpath'] != current['database_realpath']:
        raise ValueError('不同database_realpath，拒绝串库对比')
    if utc_time(current['captured_at_utc']) < utc_time(baseline['captured_at_utc']):
        raise ValueError('current时间早于baseline')
    before = {(r['date'], r['metric_id']): r for r in baseline['rows']}
    after = {(r['date'], r['metric_id']): r for r in current['rows']}
    changes = []
    for key in sorted(before.keys() | after.keys()):
        old, new = before.get(key), after.get(key)
        if old is None:
            kind, fields = 'added', []
        elif new is None:
            kind, fields = 'deleted', list(FIELDS[2:])
        else:
            fields = [f for f in FIELDS[2:] if old[f] != new[f]]
            if not fields:
                continue
            if new['source'] in ('rv_local', 'sse'):
                kind = 'protected_fields_changed'
            elif new['source'] == 'akshare' and old['source'] in ('akshare', 'rv_local', 'sse'):
                kind = 'primary_revision'
            else:
                kind = 'source_change_review'
        changes.append({'date': key[0], 'metric_id': key[1], 'kind': kind,
                        'fields': fields, 'before': old, 'after': new})
    needs_review = sum(c['kind'] in ('deleted', 'protected_fields_changed', 'source_change_review')
                       for c in changes)
    return {'schema_version': 1, 'database_realpath': baseline['database_realpath'],
            'baseline_at_utc': baseline['captured_at_utc'], 'current_at_utc': current['captured_at_utc'],
            'status': 'review' if needs_review else 'ok', 'review_count': needs_review,
            'before_rows': len(before), 'after_rows': len(after), 'changes': changes,
            'evidence_limit': '仅点时差异；不能证明写入因果或发现采样间已恢复的覆盖，也不证明长期根治。'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-db', metavar='PATH', help='显式只读SQLite；紧凑JSON到stdout')
    parser.add_argument('--baseline', metavar='FILE')
    parser.add_argument('--current', metavar='FILE')
    args = parser.parse_args(argv)
    if not ((args.capture_db and not args.baseline and not args.current)
            or (not args.capture_db and args.baseline and args.current)):
        parser.error('使用--capture-db PATH，或同时指定--baseline FILE --current FILE')
    try:
        result = capture(args.capture_db) if args.capture_db else compare(
            load_snapshot(args.baseline), load_snapshot(args.current))
        print(compact(result))
        return int(result.get('status') == 'review')
    except (ValueError, OSError, sqlite3.Error, OverflowError, RecursionError) as exc:
        print(compact({'schema_version': 1, 'status': 'error', 'error': str(exc)}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
