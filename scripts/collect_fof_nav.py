#!/usr/bin/env python3
"""collect_fof_nav.py - #333 批1: FOF/QDII 净值独立采集器(方案 A, 止漏核心)。

根因(详见 docs/ops/333-fix-plan.md):
  app/collector/public_fund.py:fetch_daily_nav 用东财每日快照表(只最新 2 日列)+ 只写
  target_date 单日 + 次新列只喂 prev_unit_nav;FOF/QDII T+1/T+2 跨日发布,采集时当日列空
  → 写 NULL,次日 target_date 滚到 T+1,FOF 的 T 日净值落进次新列只成 prev_unit_nav,
  永不作为 T 日 unit_nav 落行。无回填(COALESCE 只保留非空)。

本采集器(止漏, 不改 fetch_daily_nav):
  - lsjz 完整分页；日常从最后有效日回看7日，历史每轮向前366日，真实NULL有界复查。
  - 只选 fund_basic.fund_type LIKE 'FOF%' OR 'QDII%'。
  - 只补缺行/NULL；非空修订保全before/after证据并整基金拒绝，不半写。
    注: 方向与 fetch_daily_nav **相反**——fetch_daily_nav 用 COALESCE(新值, 库值)=新值非空优先
    用新值(可覆盖库值); 本采集器用 COALESCE(库值, 新值)=库值非空永不被覆盖(更保守, 止漏不踩踏)。
  - 不用窗口内任一非空值推断整窗完整；轮转复查全部 FOF/QDII，允许迟发布日补入。
  - 分批: 每轮最多 BATCH_SIZE 只(500)，游标记最后尝试的基金，空/异常也推进，后批不饿死。
  - 单只失败不中断; 限速 0.3s/只防 WAF(实测 50 只 0.3s 间隔零 429/零封, 见 docs/ops/333-fix-plan.md);
    幂等(重跑只补 NULL)，游标只代表尝试位置，不证明整窗已补齐。
  - 原子写: 每只一个 transaction。

入口: python -m scripts.collect_fof_nav [--days N] [--limit N] [--batch N] [--dry-run] [--fund-code CODE]
  --days   拉 lsjz 的近 N 自然日(默认 7, 覆盖 T-1/T-2 + 周末)
  --limit  只跑前 N 只(调试/小样, 优先于 --batch，不推进轮转，最多500)
  --batch  每轮最多采 N 只(默认/上限500，持久游标轮转)
  --dry-run 只拉不写；须为已checkpoint的静态DB副本，拒绝未合并WAL
  --fund-code 单只定向复查，仅既有FOF/QDII；不读写全局轮转进度，可配--days 14。

时点(云上 timer): 21:10 交易日(21:00 backfill-evening 写 sentiment.db 不撞同库,
  21:20 futures 写期货不撞; public_fund.db 写入只 16:20/17:00 daily + 03:00 quarterly)。
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # cloud 无 certifi 时用系统 CA
    _SSL_CTX = ssl.create_default_context()

# 复用 public_fund 的 DB 连接/schema/锁(§6.5 第 2 层: 库里已有不重写)
from app.collector.public_fund import DB_PATH, get_conn, init_db, _acquire_lock, _safe_float
from scripts.util_atomic import atomic_write_json
from scripts.ops_fund_evidence import (capture as _fund_capture, observe as _fund_observe,
                                       setup_seconds as _fund_setup_seconds)

LSJZ_URL = "https://api.fund.eastmoney.com/f10/lsjz"
REFERER = "https://fundf10.eastmoney.com/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
REQ_TIMEOUT = 15  # 单只请求上限(秒)
RATE_LIMIT = 0.3  # 每只间隔(秒, 防 WAF; 实测 50 只 0.3s 间隔零 429/零封, 见 docs/ops/333-fix-plan.md)
BATCH_SIZE = 500  # 每轮硬上限；轮转位置跨日保留，不因窗口移动重头采。

# 整批失败信号(#366/F01): collect() 每轮置位, main() 据此 exit 2。
# 判定 = 本轮确有待采(pending 非空) + 非空(dry_run 不报) + ok==0 且零写入
# ⇒ exit 2 让 systemd 把 trade-fof-nav-collect.service 标 failed,
#   现有消费者 scripts/check_failed_units.py(扫 systemctl --failed)即可发现。
# 单只 FAIL 是常态(封闭期/份额类上游空),不算整批失败,不触发本信号。
LAST_BATCH_FAILED = False
SELECT_SQL = (
    "SELECT fund_code, fund_name, fund_type FROM fund_basic "
    "WHERE fund_type LIKE 'FOF%' OR fund_type LIKE 'QDII%' "
    "ORDER BY fund_code"
)
# 只补 NULL/缺行: COALESCE(库值, 新值) = 库值非空保留库值, 新值只填空位。
# 方向与 fetch_daily_nav **相反**: fetch_daily_nav 用 COALESCE(新值, 库值)=新值非空优先用新值
# (可覆盖库值); 本采集器用 COALESCE(库值, 新值)=库值非空永不被覆盖(更保守, 止漏不踩踏)。
UPSERT_SQL = (
    "INSERT INTO fund_daily_nav"
    "(date, fund_code, fund_name, unit_nav, acc_nav, prev_unit_nav, nav_change_pct) "
    "VALUES (?,?,?,?,?,?,?) "
    "ON CONFLICT(date, fund_code) DO UPDATE SET "
    "fund_name      = COALESCE(fund_daily_nav.fund_name,      excluded.fund_name), "
    "unit_nav       = COALESCE(fund_daily_nav.unit_nav,       excluded.unit_nav), "
    "acc_nav        = COALESCE(fund_daily_nav.acc_nav,        excluded.acc_nav), "
    "prev_unit_nav  = COALESCE(fund_daily_nav.prev_unit_nav,  excluded.prev_unit_nav), "
    "nav_change_pct = COALESCE(fund_daily_nav.nav_change_pct, excluded.nav_change_pct)"
)

# ---- 同源非空冲突告警(2026-11-12, 用户 11-11 拍板「维持旧值 + 加告警」)----
# 生产实证(11-11 21:10 轮): 60 只 20261019 prev_unit_nav eastmoney 修订值触发整只拒绝,
# fund_collection_conflicts 存了 60 条, 但 run_fof_nav_collect.sh 无 notify 调用、unit 无
# OnFailure ⇒ 全程零告警(/tmp/night-fail-triage.md §3)。拍板: 拒绝逻辑/DB 写入/rc 语义
# 一字不改, 只补「失败可见性」——本轮确实发生 NonNullConflict(拒绝>0)才发一次业务告警;
# 无冲突不发(不搞每晚「一切正常」); 只读内存已收集的冲突记录, 不额外扫库/不发采集请求。
CONFLICT_ALERT_DEDUP_KEY = "fof_nav_nonnull_conflict"
CONFLICT_ALERT_DEDUP_WINDOW = 72000  # 20h: 同一天多轮(含手动重跑)不刷屏, 次日晚间轮仍提醒


def _notify_nonnull_conflicts(conflicts, attempted=None, committed=None, not_attempted=None):
    """本轮同源非空冲突拒绝 → 一次业务告警(仅拒绝>0 才发, 无冲突直接返回)。

    四元组: tier=warning(批量档, 由 schedule_monitor 尾部 --flush-warnings 30min 聚合批发)
    / dedup window=72000s(20h) / 聚合域=collect / 首报策略=入聚合。
    只读内存里已收集的冲突记录(fund_collection_conflicts 同款字段), 唯一外发 =
    notify.py 子进程; 发送失败只记日志, 不改 rc/返回值/主流程结果。
    零外发铁律(§18 L48): 测试必须打桩本模块 subprocess.run 并断言调用参数。
    """
    if not conflicts:
        return
    codes = sorted({str(c['code']) for c in conflicts})
    dates = sorted({str(c['date']) for c in conflicts})
    fields = sorted({str(c['field']) for c in conflicts})
    sources = sorted({str(c.get('source') or 'unknown') for c in conflicts})
    rel = []
    for c in conflicts:
        before, after = c.get('before'), c.get('after')
        try:
            if before not in (None, 0):
                rel.append(abs(after - before) / abs(before))
        except Exception:  # noqa: BLE001  非数值/缺值只跳过, 不影响告警
            pass
    rel_txt = f"{min(rel):.4%}~{max(rel):.4%}" if rel else "不可计算(旧值为 0/缺失)"
    subject = (f"[告警] FOF 净值同源非空冲突 {len(conflicts)} 条/{len(codes)} 只"
               f"(DB 旧值保留未覆盖)")
    body = "<br>".join([
        "<b>FOF/QDII 净值采集同源非空冲突: 已按规则维持 DB 旧值(未覆盖)</b>",
        f"本轮冲突条数: {len(conflicts)} 条; 涉及基金: {len(codes)} 只",
        f"冲突日期: {', '.join(dates)}",
        f"冲突字段: {', '.join(fields)}",
        f"数据源: {', '.join(sources)}",
        f"相对差异范围(|修订值-旧值|/旧值): {rel_txt}",
        f"样本基金(最多 5 只): {', '.join(codes[:5])}",
        f"本轮计数: attempted={attempted} committed={committed} not_attempted={not_attempted}",
        "DB 旧值保留未覆盖;需人工拍板接受修订或维持旧值"
        "(修订证据已存 fund_collection_conflicts 审计表)。",
    ])
    cmd = [sys.executable, str(Path(__file__).resolve().parent / "notify.py"),
           subject, body, "--tier", "warning", "--from-prefix", "[告警]",
           "--dedup-key", CONFLICT_ALERT_DEDUP_KEY,
           "--dedup-window", str(CONFLICT_ALERT_DEDUP_WINDOW)]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except Exception as e:  # noqa: BLE001  发送失败不影响采集主流程/rc
        print(f"[fof_nav] 非空冲突告警发送失败(不影响采集主流程): {e}", flush=True)


def fetch_lsjz(fund_code: str, start_date: str, end_date: str, *,
               deadline: float | None = None) -> list[dict]:
    """完整分页后才返回；校验页号/总数/日期降序，跨页计算prevNAV。"""
    from app.collector.public_fund_gap import request_budget, remaining
    deadline = time.monotonic() + 290 if deadline is None else deadline
    rows = []
    total = None
    page = 1
    while True:
        remaining(deadline)
        url = (f"{LSJZ_URL}?fundCode={fund_code}&pageIndex={page}&pageSize=20"
               f"&startDate={start_date}&endDate={end_date}")
        req = urllib.request.Request(url, headers={"Referer": REFERER, "User-Agent": USER_AGENT})
        with request_budget(deadline, REQ_TIMEOUT) as budget:
            with urllib.request.urlopen(req, timeout=budget, context=_SSL_CTX) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        if not isinstance(data, dict) or data.get('ErrCode') not in (0, None):
            raise RuntimeError('lsjz错误响应')
        block = data.get('Data')
        if not isinstance(block, dict) or not isinstance(block.get('LSJZList'), list):
            raise ValueError('lsjz缺数据列表')
        part = block['LSJZList']
        count = data.get('TotalCount')
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError('lsjz总数非法')
        if data.get('PageIndex') != page or data.get('PageSize') != 20:
            raise ValueError('lsjz页号/页大小不符')
        if total is not None and total != count:
            raise ValueError('lsjz分页期间总数改变')
        total = count
        if len(part) != min(20, total-len(rows)):
            raise ValueError('lsjz缺页/条数不符')
        for r in part:
            d = str(r.get('FSRQ', ''))
            datetime.strptime(d, '%Y-%m-%d')
            if not start_date <= d <= end_date or (rows and rows[-1]['FSRQ'] <= d):
                raise ValueError('lsjz重复/乱序/越界日期')
            rows.append(r)
        if len(rows) == total:
            break
        page += 1
    out = []
    for i, r in enumerate(rows):
        unit = _safe_float(r.get('DWJZ'))
        if unit is None:
            continue  # 未公布值绝不制造占位。
        parsed = {'date': r['FSRQ'].replace('-', ''), 'fund_code': fund_code,
                  'unit_nav': unit, 'acc_nav': _safe_float(r.get('LJJZ')),
                  'nav_change_pct': _safe_float(r.get('JZZZL')),
                  'prev_unit_nav': _safe_float(rows[i+1].get('DWJZ')) if i+1 < len(rows) else None}
        if any(v is not None and not math.isfinite(v) for k, v in parsed.items()
               if k not in ('date', 'fund_code')):
            raise ValueError('lsjz含非有限数值')
        out.append(parsed)
    return out


@_fund_capture('fof-nav', lambda: DB_PATH.parent.parent)
def collect(days: int = 7, limit: int | None = None, dry_run: bool = False,
            batch: int = BATCH_SIZE, fund_code: str | None = None,
            budget_seconds: float = 290.0) -> int:
    """主流程。返回写入行数。

    整批失败信号(#366/F01): 若本轮确有待采(pending 非空)、非 dry_run、且 ok==0 且零写入,
    置位 mod.LAST_BATCH_FAILED, main() 据此 exit 2 → systemd 标 failed →
    check_failed_units.py 扫到。单只失败是常态不算整批失败。

    按代码轮转，每轮最多500只；不从库内零星非空值猜上游完整发布日期。
    进度文件邻接实际连接的DB，复用原子助手；损坏时明示重头复查，不跳过未知基金。
    已尝试目标即使超时回滚也记录轮转位置；它不是成功/完整覆盖游标。
    超时目标在原version=1进度中保留缩小后的工作范围，历史/缺口业务状态不假推进。
    dry_run只读已存在的库；limit调试小样不读写轮转位置。
    """
    from app.collector import public_fund_gap as gap
    if not math.isfinite(budget_seconds) or budget_seconds <= 0 or budget_seconds > 290:
        raise ValueError('整轮预算须在(0,290]秒内')
    deadline = time.monotonic() + budget_seconds - _fund_setup_seconds()
    global LAST_BATCH_FAILED
    LAST_BATCH_FAILED = False  # 每轮重置, 防同进程跨轮残留(合法空数据/锁占/无待采均保持 False)
    if days < 0 or batch < 1 or (limit is not None and limit < 1):
        raise ValueError("days须非负，batch/limit须为正整数")
    if fund_code is not None and (not isinstance(fund_code, str) or len(fund_code) != 6
                                  or not fund_code.isascii() or not fund_code.isdigit()):
        raise ValueError("fund_code须为6位ASCII数字")
    if not _acquire_lock(nonblock=True, lock_name="public_fund", **({"read_only": True} if dry_run else {})):
        _fund_observe('reason', reason='lock_not_attempted')
        print("[fof_nav] WARN public_fund.lock 被占, 跳过(防与 daily/quarterly 并发写同库)",
              flush=True)
        return 0
    target_rows = None
    validate_snapshot = lambda: None
    if dry_run or fund_code is not None:
        if dry_run:
            conn, validate_snapshot = gap.readonly_snapshot(DB_PATH, timeout=min(5, gap.remaining(deadline)))
        else:
            conn = sqlite3.connect(DB_PATH.absolute().as_uri() + "?mode=ro", uri=True, timeout=10)
        conn.execute("PRAGMA query_only=ON")
        if fund_code is not None:
            target_rows = list(conn.execute(
                "SELECT * FROM (" + SELECT_SQL + ") WHERE fund_code=?", (fund_code,)))
            if not target_rows:
                _fund_observe('reason', reason='target_outside_universe')
                print(f"[fof_nav] 非既有FOF/QDII目标 {fund_code}，跳过(未写库)", flush=True)
                conn.close()
                return 0
            if not dry_run:
                conn.close()
    if not dry_run:
        init_db()  # 在现有同库锁内初始化；dry_run不迁移/建库/设置WAL。
        conn = get_conn()
    nonnull_conflicts = []  # 本轮同源非空冲突(拒绝)记录, 收尾统一告警(见 _notify_nonnull_conflicts)
    try:
        gap.configure(conn, deadline)
        if not dry_run:
            gap.migrate(conn)
            conn.commit()
        end = date.today()
        start = end - timedelta(days=days)
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")
        all_funds = target_rows if target_rows is not None else list(conn.execute(SELECT_SQL))
        total_pool = len(all_funds)
        progress = None
        last_code = ""
        work_limits = {}
        if not dry_run and limit is None and fund_code is None and all_funds:
            db_file = conn.execute("PRAGMA database_list").fetchone()[2]
            if not db_file:
                conn.close()
                raise ValueError("轮转进度需要持久SQLite文件")
            progress = Path(db_file).with_suffix(".fof-nav-progress.json")
            try:
                saved = json.loads(progress.read_text())
                if not isinstance(saved, dict):
                    raise ValueError("进度不是对象")
                last_code = saved["last_code"]
                if saved.get("version") != 1 or not isinstance(last_code, str) or not last_code.isdigit():
                    raise ValueError("进度格式异常")
                pool = {row[0] for row in all_funds}
                limits = saved.get('work_limits', {})
                if not isinstance(limits, dict):
                    raise ValueError('工作预算记录不是对象')
                for code, value in limits.items():
                    if code not in pool:
                        continue
                    if (not isinstance(value, dict) or type(value.get('history_days')) is not int
                            or not 1 <= value['history_days'] <= gap.HISTORY_DAYS
                            or type(value.get('gap_fields')) is not int
                            or not 1 <= value['gap_fields'] <= gap.GAP_LIMIT
                            or value.get('phase') not in ('recent', 'history', 'gap')):
                        raise ValueError('工作预算记录格式异常')
                    if 'recent_through' in value:
                        through = value['recent_through']
                        if (not isinstance(through, str) or len(through) != 8
                                or not '19900101' <= through <= end.strftime('%Y%m%d')):
                            raise ValueError('已查窗口日期异常')
                        datetime.strptime(through, '%Y%m%d')
                    work_limits[code] = value
            except FileNotFoundError:
                pass
            except (ValueError, KeyError, TypeError):
                print("[fof_nav] WARN 轮转进度损坏，从头复查(不代表已补齐)", flush=True)
                last_code = ""
                work_limits = {}
        pending = [r for r in all_funds if r[0] > last_code] + [r for r in all_funds if r[0] <= last_code]
        pending = pending[:min(limit if limit is not None else batch, BATCH_SIZE)]
        run_batch = len(pending)
        _fund_observe('scope', pool_count=total_pool, selected_count=run_batch,
                      selected_codes=[r[0] for r in pending],
                      selection='targeted' if target_rows is not None else 'limited' if limit is not None else 'rotating',
                      pool_scope='target_only' if target_rows is not None else 'FOF_QDII',
                      recent_window=[start_str, end_str], expected_publication='T_plus_1_or_2_not_SLA')

        print(f"[fof_nav] FOF/QDII 总数={total_pool} 轮转起点={last_code or '起始'} "
              f"待采={len(pending)}/{total_pool} 本轮尝试(不代表整窗完整) "
              f"(拉近{days}日 {start_str}~{end_str} batch={run_batch} dry_run={dry_run})",
              flush=True)
        if not pending:
            print("[fof_nav] 无FOF/QDII目标，跳过", flush=True)
            conn.close()
            return 0

        had_pending = True  # 走到此处 = pending 非空(上方 not pending 已 early-return)
        total_written = 0
        ok = 0
        fail = 0  # 原义保留=空+异常之和(日志口径不变); 下方 empty/error_count 拆细供整批判据
        empty = 0  # 合法空响应(LSJZList=[]: 封闭期/份额类区间内无净值, 常态)→ 不算失败
        error_count = 0  # 真实异常(urlopen 抛错/JSON 解码失败/ErrCode!=0)→ 整批判据只看这个
        t0 = time.time()
        attempted = 0
        for idx, (fund_code, fund_name, fund_type) in enumerate(pending, 1):
            if time.monotonic() >= deadline:
                conn.close()
                raise TimeoutError('FOF整轮预算耗尽，保留已提交目标和原尝试游标')
            attempted += 1
            _fund_observe('attempt', fund_code=fund_code)
            candidate = None
            target_limit = work_limits.get(fund_code)
            budget_failed = False
            target_committed = False
            try:
                gap.configure(conn, deadline)
                # 定向/limit为明确窗口；正常轮转独立推进完整历史和长期NULL队列。
                if limit is None and target_rows is None:
                    candidate = gap.plan(conn, 'nav', fund_code, end.strftime('%Y%m%d'), '19900101', days,
                                         work_limit=target_limit)
                    ranges = candidate['ranges']
                else:
                    ranges = [(start.strftime('%Y%m%d'), end.strftime('%Y%m%d'))]
                _fund_observe('ranges', fund_code=fund_code, planned_ranges=ranges)
                merged = {}
                for first, last in ranges:
                    def iso(d):
                        return f'{d[:4]}-{d[4:6]}-{d[6:]}'
                    _fund_observe('range_attempt', fund_code=fund_code, first=first, last=last)
                    batch_rows = fetch_lsjz(fund_code, iso(first), iso(last), deadline=deadline)
                    _fund_observe('range_return', fund_code=fund_code, first=first, last=last,
                                  published_rows=len(batch_rows))
                    for row in batch_rows:
                        old = merged.get(row['date'])
                        if old and old != row:
                            raise ValueError('重叠范围返回不一致')
                        merged[row['date']] = row
                rows = list(merged.values())
                if ranges:
                    _fund_observe('source', rows=rows)
                gap.remaining(deadline)
                if not dry_run:
                    conn.execute('BEGIN IMMEDIATE')
                gap.check_conflicts(conn, 'nav', fund_code, rows, LSJZ_URL)
                if not rows:
                    # 合法空(HTTP200 + ErrCode=0 + LSJZList=[]): 该基金区间内本无净值, 非异常
                    empty += 1
                    fail += 1  # fail 仍含空(日志口径不变, 无外部程序化消费者)
                elif not dry_run:
                    params = [
                        (
                            r["date"], r["fund_code"], fund_name,
                            r["unit_nav"], r["acc_nav"], r["prev_unit_nav"],
                            r["nav_change_pct"],
                        )
                        for r in rows
                    ]
                    conn.executemany(UPSERT_SQL, params)
                if not dry_run:
                    gap.finish(conn, 'nav', fund_code, candidate)
                    gap.remaining(deadline)
                    conn.commit()  # NAV+历史覆盖+缺口队列在同一基金事务内提交
                    target_committed = True
                    _fund_observe('committed', rows=rows)
                if rows:
                    total_written += len(rows)
                    ok += 1
            except Exception as e:
                _fund_observe('error', reason=type(e).__name__)
                # P2-C(2026-11-05): 显式回滚, 保证失败那只零落库、不影响下一只。
                # 旧代码只计数不回滚: 失败那只的部分写入留在未提交事务里, 会被下一只
                # 的 commit 一起提交。失败基金本轮不留部分NAV，下次轮转仍会复查。
                try:
                    conn.rollback()
                except Exception:  # noqa: BLE001
                    pass
                if isinstance(e, gap.NonNullConflict) and not dry_run:
                    gap.save_conflicts(conn, 'nav', fund_code, e)
                    nonnull_conflicts.extend({'code': fund_code, **ev} for ev in e.evidence)
                if time.monotonic() >= deadline:
                    budget_failed = True
                    raise TimeoutError('FOF整轮预算耗尽，本基金已回滚') from e
                error_count += 1  # 真实异常计入整批判据
                fail += 1
                print(f"[fof_nav] FAIL {fund_code} {fund_type}: {e}", flush=True)
            finally:
                if progress is not None:
                    if budget_failed:
                        previous = target_limit or {'history_days': gap.HISTORY_DAYS,
                                                    'gap_fields': gap.GAP_LIMIT, 'phase': 'gap'}
                        work_limits[fund_code] = {**previous,
                            'history_days': max(1, previous['history_days'] // 2),
                            'gap_fields': max(1, previous['gap_fields'] // 2),
                            'phase': {'recent': 'history', 'history': 'gap', 'gap': 'recent'}[previous['phase']]}
                    elif target_limit:
                        work_limits[fund_code] = dict(target_limit, phase={
                            'recent': 'history', 'history': 'gap', 'gap': 'recent'}[target_limit['phase']])
                        if target_committed and candidate and candidate.get('recent_through'):
                            # 完整合法空也越过已查窗口；失败不推进。数据库先提交，
                            # 元数据崩溃最多重查，不会跳过尚未提交的源窗口。
                            work_limits[fund_code]['recent_through'] = candidate['recent_through']
                    value = {"version": 1, "last_code": fund_code}
                    if work_limits:
                        value['work_limits'] = work_limits
                    # Small, atomic attempt metadata is outside the rolled-back
                    # NAV transaction; a failed write remains a nonzero failure.
                    atomic_write_json(progress, value)
            if idx % 50 == 0:
                print(f"[fof_nav] 进度 {idx}/{len(pending)} ok={ok} fail={fail} "
                      f"empty={empty} error={error_count} written={total_written} "
                      f"{time.time()-t0:.0f}s", flush=True)
            if RATE_LIMIT:
                time.sleep(min(RATE_LIMIT, max(0, deadline-time.monotonic())))
        conn.close()
        remaining = total_pool - attempted
        print(f"[fof_nav] 完成 ok={ok} fail={fail} empty={empty} error={error_count} "
              f"written={total_written} {time.time()-t0:.0f}s 本轮未尝试={remaining}(下轮轮转；不代表缺值数)",
              flush=True)
        # 整批失败信号(#366/F01 + F01-R1): 确有待采 + 非 dry_run + 零成功零写入 **且
        # error_count>0**(含真实异常)才置位。全部合法空(empty>0, error=0)不算失败——
        # 封闭期/份额类区间内无净值是常态, 旧判定漏 error_count>0 守卫致合法空误判 exit 2 假告警。
        # ok>0 或 written>0 即判部分成功, 不触发。
        batch_fail = (had_pending and (not dry_run) and ok == 0
                      and total_written == 0 and error_count > 0)
        if batch_fail:
            print(f"[fof_nav] BATCH_FAIL 本轮待采={len(pending)} 整批失败: "
                  f"零成功零写入 且 error_count={error_count}>0(含真实异常, 非合法空) "
                  f"(常见原因=网络/WAF 或写库异常, 已写数据保留, 下轮自动续跑)",
                  flush=True)
        LAST_BATCH_FAILED = batch_fail  # global 声明在函数头(配合顶部复位)
        return total_written
    finally:
        conn.close()
        if nonnull_conflicts:
            # 冲突告警放 finally: 正常收尾与 TimeoutError 预算中断都覆盖(中断轮已检出的
            # 冲突也可见); 只读内存已收集记录, 不扫库。发送失败不改 rc/返回值/主流程。
            try:
                _notify_nonnull_conflicts(
                    nonnull_conflicts, attempted=attempted, committed=ok,
                    not_attempted=total_pool - attempted)
            except Exception as e:  # noqa: BLE001  兜底: 告警绝不掩盖采集主异常
                print(f"[fof_nav] 非空冲突告警异常(不影响采集主流程): {e}", flush=True)
        validate_snapshot()


def main() -> int:
    ap = argparse.ArgumentParser(description="#333 批1 FOF/QDII 净值采集器")
    ap.add_argument("--days", type=int, default=7, help="拉近 N 自然日(默认 7)")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 只(调试, 优先于 --batch)")
    ap.add_argument("--batch", type=int, default=BATCH_SIZE,
                    help=f"每轮最多采 N 只(默认/上限 {BATCH_SIZE}, 持久轮转续跑)")
    ap.add_argument("--dry-run", action="store_true", help="只拉不写")
    ap.add_argument("--fund-code", help="只复查指定6位基金代码(须为既有FOF/QDII，不动全局轮转进度)")
    ap.add_argument('--budget-seconds', type=float, default=290, help='整轮绝对预算，最多290秒')
    args = ap.parse_args()
    try:
        n = collect(days=args.days, limit=args.limit, dry_run=args.dry_run, batch=args.batch,
                    fund_code=args.fund_code, budget_seconds=args.budget_seconds)
    except ValueError as exc:
        ap.error(str(exc))
    print(f"[fof_nav] return written={n}", flush=True)
    # 整批失败(#366/F01 + F01-R1): exit 2 → systemd 标 trade-fof-nav-collect.service failed
    # → check_failed_units.py 扫 systemctl --failed 即发现。
    # 合法空数据(LSJZList=[])/单只失败/部分成功均 exit 0; 仅「零成功零写入且含真实异常」才 exit 2。
    if LAST_BATCH_FAILED:
        print("[fof_nav] exit 2: 整批失败信号已置位(供 check_failed_units 消费)", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
