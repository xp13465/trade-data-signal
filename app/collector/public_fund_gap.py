"""公募历史覆盖、NULL 有界复查与单目标原子提交。只使用调用方现有连接/预算。

覆盖区间只表示完整读取了源响应，不表示每天都有净值。NULL 队列来自真实库行，
不按日历制造缺口。首次历史按年向前推进，直到固定起点；空段同样必须查过。
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
import json
import math
import signal
import sqlite3
from pathlib import Path
import threading
import time

NAV_FIELDS = ('unit_nav', 'acc_nav', 'prev_unit_nav', 'nav_change_pct')
INDEX_FIELDS = ('close', 'pct_change')
GAP_LIMIT = 64  # 单目标每轮最多64个实际缺字段日期，永久空不会饿死队尾。
HISTORY_DAYS = 366


def remaining(deadline):
    left = deadline - time.monotonic()
    if left <= 0:
        raise TimeoutError('公募整轮预算耗尽')
    return left


@contextmanager
def request_budget(deadline, seconds):
    """urllib 的 socket timeout 不能限制慢滴流；主线程用绝对墙钟保护单次HTTP。"""
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('公募HTTP必须在采集主线程调用')
    old_handler = signal.getsignal(signal.SIGALRM)
    old_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    budget = min(seconds, remaining(deadline))
    if old_timer[0]:
        budget = min(budget, old_timer[0])
    class Expired(BaseException):
        pass
    def expire(*_):
        raise Expired()
    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, budget)
    try:
        yield budget
        remaining(deadline)
    except Expired:
        raise TimeoutError('公募HTTP绝对预算耗尽') from None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if old_timer[0]:
            signal.setitimer(signal.ITIMER_REAL,
                             max(.000001, old_timer[0] - (time.monotonic()-started)), old_timer[1])


def configure(conn, deadline):
    conn.execute(f'PRAGMA busy_timeout={max(1, int(min(5, remaining(deadline))*1000))}')
    conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)


def migrate(conn):
    # 兼容既有库；不重建业务表、不改原有FOF文件游标。调用方提交/回滚。
    conn.execute("""CREATE TABLE IF NOT EXISTS fund_collection_state (
        stream TEXT, code TEXT, history_before TEXT, gap_after TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(stream,code))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS fund_collection_gaps (
        stream TEXT, code TEXT, date TEXT, field TEXT, attempts INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(stream,code,date,field))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS fund_collection_conflicts (
        stream TEXT, code TEXT, date TEXT, field TEXT, before_value REAL, after_value REAL,
        source TEXT, observed_at TEXT, PRIMARY KEY(stream,code,date,field,before_value,after_value))""")
    # 复用业务表既有idx_daily_nav_code/idx_fund_index_daily_id，不在290秒轮次重建大表索引。


def tables(stream):
    if stream == 'nav':
        return 'fund_daily_nav', 'fund_code', NAV_FIELDS
    if stream == 'index':
        return 'fund_index_daily', 'index_id', INDEX_FIELDS
    raise ValueError('未知公募数据类型')


def shift(day, days):
    return (datetime.strptime(day, '%Y%m%d') + timedelta(days=days)).strftime('%Y%m%d')


def merge_ranges(ranges):
    merged = []
    for start, end in sorted(ranges):
        if start > end:
            continue
        if merged and start <= shift(merged[-1][1], 1):
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def plan(conn, stream, code, end, floor, lookback=7, work_limit=None):
    """只读规划；返回候选状态。失败不会推进历史/扫描位置或删除NULL任务。"""
    table, key, fields = tables(stream)
    index = 'idx_daily_nav_code' if stream == 'nav' else 'idx_fund_index_daily_id'
    # 强制复用旧索引；缺索引直接失败，不能退化为扫描全市场历史。
    table = f'{table} INDEXED BY {index}'
    has_state = conn.execute("SELECT 1 FROM sqlite_master WHERE name='fund_collection_state'").fetchone()
    state = conn.execute('SELECT history_before,gap_after FROM fund_collection_state WHERE stream=? AND code=?',
                         (stream, code)).fetchone() if has_state else None
    before, after = tuple(state) if state else (shift(end, 1), '')
    history_days = work_limit['history_days'] if work_limit else HISTORY_DAYS
    gap_limit = work_limit['gap_fields'] if work_limit else GAP_LIMIT
    history_start = floor if stream == "index" else max(floor, shift(before, -history_days))
    history_ranges = [(history_start, shift(before, -1))] if before > floor else []
    latest = conn.execute(f'SELECT MAX(date) FROM {table} WHERE {key}=? AND {fields[0]} IS NOT NULL',
                          (code,)).fetchone()[0]
    # 从最后有效日回看，停采超7日时仍覆盖整段；加一条真实上下文供prevNAV。
    recent_base = max(latest or '', (work_limit or {}).get('recent_through', '')) or end
    recent = shift(min(recent_base, end), -lookback)
    recent_end = min(end, shift(recent_base, history_days)) if work_limit else end
    predicate = ' OR '.join(f'{f} IS NULL' for f in fields)
    gaps = list(conn.execute(f'SELECT date,{",".join(fields)} FROM {table} WHERE {key}=? '
                            f'AND date>? AND date<=? AND ({predicate}) ORDER BY date LIMIT ?',
                            (code, after, end, GAP_LIMIT)))
    if not gaps and after:
        gaps = list(conn.execute(f'SELECT date,{",".join(fields)} FROM {table} WHERE {key}=? '
                                f'AND date<=? AND ({predicate}) ORDER BY date LIMIT ?', (code, end, GAP_LIMIT)))
    discovered = [(r[0], f) for r in gaps for f, v in zip(fields, r[1:]) if v is None]
    queued = list(conn.execute('SELECT date,field FROM fund_collection_gaps WHERE stream=? AND code=? '
                              'ORDER BY attempts,date,field LIMIT ?', (stream, code, gap_limit))) if has_state else []
    selected = list(dict.fromkeys([tuple(r) for r in queued] + discovered))[:gap_limit]
    next_history, next_gap = min(before, history_start), gaps[-1][0] if gaps else ''
    gap_ranges = [(d, d) for d, _ in selected]
    if work_limit:
        # A timed-out target gets complete, smaller units, not an ever-repeated
        # all-history+all-gaps transaction. These phases rotate independently of
        # the fund cursor. Only the successfully fetched phase advances coverage.
        phase = work_limit['phase']
        ranges = {'recent': [(recent, recent_end)], 'history': history_ranges,
                  'gap': gap_ranges}[phase]
        if phase != 'history':
            next_history = before
        if phase != 'gap':
            selected, discovered, next_gap = [], [], after
    else:
        ranges = history_ranges + [(recent, end)] + gap_ranges
    ranges = merge_ranges(ranges)
    with_context = []
    for start, stop in ranges:
        prev = conn.execute(f'SELECT MAX(date) FROM {table} WHERE {key}=? AND date<? '
                            f'AND {fields[0]} IS NOT NULL', (code, start)).fetchone()[0]
        context = prev or shift(start, -7)
        if work_limit:
            # A distant old database row must not silently expand a one-day
            # retry into years. Missing previous NAV remains NULL for later repair.
            context = max(context, shift(start, -7))
        with_context.append((start if stream == 'index' and start == floor else context, stop))
    return {'ranges': merge_ranges(with_context), 'history_before': next_history,
            'gap_after': next_gap, 'discovered': discovered, 'selected': selected,
            'recent_through': recent_end if work_limit and work_limit['phase'] == 'recent' else None}


class NonNullConflict(RuntimeError):
    def __init__(self, evidence):
        self.evidence = evidence
        super().__init__('同源非空冲突，整目标拒绝: ' + json.dumps(evidence, ensure_ascii=False))


def check_conflicts(conn, stream, code, rows, source):
    table, key, fields = tables(stream)
    evidence = []
    seen = {}
    for row in rows:
        d = row['date']
        if d in seen and row != seen[d]:
            raise ValueError('同日响应不一致')
        seen[d] = row
        old = conn.execute(f'SELECT {",".join(fields)} FROM {table} WHERE {key}=? AND date=?', (code, d)).fetchone()
        if old is None:
            continue
        for field, before in zip(fields, old):
            after = row.get(field)
            if before is not None and after is not None and not math.isclose(before, after, rel_tol=1e-10, abs_tol=1e-10):
                evidence.append({'date': d, 'field': field, 'before': before, 'after': after, 'source': source})
    if evidence:
        raise NonNullConflict(evidence)


def save_conflicts(conn, stream, code, error):
    # 业务事务已回滚；只另存不可变before/after审计，不写修复/覆盖进度。
    conn.executemany('INSERT OR IGNORE INTO fund_collection_conflicts VALUES(?,?,?,?,?,?,?,?)',
                     [(stream, code, e['date'], e['field'], e['before'], e['after'], e['source'],
                       datetime.now().isoformat()) for e in error.evidence])
    conn.commit()


def finish(conn, stream, code, candidate):
    if candidate is None:
        return
    table, key, fields = tables(stream)
    for d, field in candidate['discovered']:
        conn.execute('INSERT OR IGNORE INTO fund_collection_gaps(stream,code,date,field) VALUES(?,?,?,?)',
                     (stream, code, d, field))
    for d, field in candidate['selected']:
        assert field in fields
        value = conn.execute(f'SELECT {field} FROM {table} WHERE {key}=? AND date=?', (code, d)).fetchone()
        if value and value[0] is not None:
            conn.execute('DELETE FROM fund_collection_gaps WHERE stream=? AND code=? AND date=? AND field=?',
                         (stream, code, d, field))
        else:
            conn.execute('UPDATE fund_collection_gaps SET attempts=attempts+1 WHERE stream=? AND code=? AND date=? AND field=?',
                         (stream, code, d, field))
    conn.execute('INSERT INTO fund_collection_state VALUES(?,?,?,?) ON CONFLICT(stream,code) '
                 'DO UPDATE SET history_before=excluded.history_before,gap_after=excluded.gap_after',
                 (stream, code, candidate['history_before'], candidate['gap_after']))


def collect_index(fetch, get_conn, index_id, end, deadline, io_timeout, dry_run=False, snapshot_path=None):
    validate = lambda: None
    if dry_run and snapshot_path is not None:
        conn, validate = readonly_snapshot(snapshot_path, min(5, remaining(deadline)))
    else:
        conn = get_conn(timeout=min(5, remaining(deadline)))
    try:
        configure(conn, deadline)
        if not dry_run:
            migrate(conn)
            conn.commit()
        oldest = conn.execute('SELECT MIN(date) FROM fund_index_daily WHERE index_id=?', (index_id,)).fetchone()[0]
        floor = min(oldest or end, shift(end, -400))
        candidate = plan(conn, 'index', index_id, end, floor)
        rows = []
        for first, last in candidate['ranges']:
            rows.extend(fetch(first, last, index_id, deadline=deadline,
                              io_timeout=io_timeout, _return_rows=True))
        if not dry_run:
            conn.execute('BEGIN IMMEDIATE')
        check_conflicts(conn, 'index', index_id, rows, 'baostock')
        if not dry_run:
            conn.executemany('INSERT INTO fund_index_daily(date,index_id,close,pct_change) VALUES(?,?,?,?) '
                             'ON CONFLICT(date,index_id) DO UPDATE SET '
                             'close=COALESCE(fund_index_daily.close,excluded.close),'
                             'pct_change=COALESCE(fund_index_daily.pct_change,excluded.pct_change)',
                             [(r['date'], index_id, r['close'], r['pct_change']) for r in rows])
            finish(conn, 'index', index_id, candidate)
            remaining(deadline)
            conn.commit()
        return len(rows)
    except NonNullConflict as exc:
        conn.rollback()
        if not dry_run:
            save_conflicts(conn, 'index', index_id, exc)
        raise
    finally:
        conn.close()
        validate()


def readonly_snapshot(path, timeout=5):
    """dry-run仅接受无未合并WAL的静态快照；immutable避免创建wal/shm。

    不使用immutable悄悄忽略现存WAL；调用方退出前validate，变化即拒绝本次结果。
    """
    path = Path(path)
    def stamp():
        st = path.stat()
        wal = Path(str(path)+'-wal')
        if wal.exists() and wal.stat().st_size:
            raise ValueError('只读dry-run需要已checkpoint的静态副本；存在WAL，拒绝忽略其数据')
        return st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns
    initial = stamp()
    conn = sqlite3.connect(path.absolute().as_uri()+'?mode=ro&immutable=1', uri=True, timeout=timeout)
    def validate():
        if stamp() != initial:
            raise ValueError('dry-run期间快照变化，结果无效')
    return conn, validate
