#!/usr/bin/env python3
"""collect_fof_nav.py - #333 批1: FOF/QDII 净值独立采集器(方案 A, 止漏核心)。

根因(详见 docs/ops/333-fix-plan.md):
  app/collector/public_fund.py:fetch_daily_nav 用东财每日快照表(只最新 2 日列)+ 只写
  target_date 单日 + 次新列只喂 prev_unit_nav;FOF/QDII T+1/T+2 跨日发布,采集时当日列空
  → 写 NULL,次日 target_date 滚到 T+1,FOF 的 T 日净值落进次新列只成 prev_unit_nav,
  永不作为 T 日 unit_nav 落行。无回填(COALESCE 只保留非空)。

本采集器(止漏, 不改 fetch_daily_nav):
  - 走天天基金 lsjz 历史 API(api.fund.eastmoney.com/f10/lsjz, 带 Referer)补近 7 自然日净值。
  - 只选 fund_basic.fund_type LIKE 'FOF%' OR 'QDII%'。
  - 只补「缺行 or NULL」, 不覆盖已有非空(COALESCE(库值, 新值) = 库值非空保留库值)。
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
  --dry-run 只拉不写
  --fund-code 单只定向复查，仅既有FOF/QDII；不读写全局轮转进度，可配--days 14。

时点(云上 timer): 21:10 交易日(21:00 backfill-evening 写 sentiment.db 不撞同库,
  21:20 futures 写期货不撞; public_fund.db 写入只 16:20/17:00 daily + 03:00 quarterly)。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # cloud 无 certifi 时用系统 CA
    _SSL_CTX = ssl.create_default_context()

# 复用 public_fund 的 DB 连接/schema/锁(§6.5 第 2 层: 库里已有不重写)
from app.collector.public_fund import DB_PATH, get_conn, init_db, _acquire_lock, _safe_float
from scripts.util_atomic import atomic_write_json

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


def fetch_lsjz(fund_code: str, start_date: str, end_date: str) -> list[dict]:
    """拉 lsjz 历史 API, 返回 [{'date','unit_nav','acc_nav','pct','prev_unit'}, ...]。

    start/end = YYYY-MM-DD。返回按日期降序(API 原序), prev_unit 取下一条(更早一日)的 DWJZ。
    """
    url = (
        f"{LSJZ_URL}?fundCode={fund_code}&pageIndex=1&pageSize=20"
        f"&startDate={start_date}&endDate={end_date}"
    )
    req = urllib.request.Request(
        url, headers={"Referer": REFERER, "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=REQ_TIMEOUT, context=_SSL_CTX) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    if not data or data.get("ErrCode") not in (0, None):
        raise RuntimeError(f"lsjz ErrCode={data.get('ErrCode')} Msg={data.get('ErrMsg')}")
    rows = (data.get("Data") or {}).get("LSJZList") or []
    out: list[dict] = []
    for i, r in enumerate(rows):
        fsrq = str(r.get("FSRQ", "")).strip()  # 2026-10-30
        if not fsrq:
            continue
        d = fsrq.replace("-", "")  # 20261030
        unit = _safe_float(r.get("DWJZ"))
        if unit is None:
            continue  # 未发布值不能制造NULL占位；无有效净值仍是合法空响应。
        acc = _safe_float(r.get("LJJZ"))
        pct = _safe_float(r.get("JZZZL"))
        # prev_unit = 列表里下一条(更早一日)的单位净值(API 按日期降序)
        prev_unit = None
        if i + 1 < len(rows):
            prev_unit = _safe_float(rows[i + 1].get("DWJZ"))
        out.append(
            {
                "date": d,
                "fund_code": fund_code,
                "unit_nav": unit,
                "acc_nav": acc,
                "prev_unit_nav": prev_unit,
                "nav_change_pct": pct,
            }
        )
    return out


def collect(days: int = 7, limit: int | None = None, dry_run: bool = False,
            batch: int = BATCH_SIZE, fund_code: str | None = None) -> int:
    """主流程。返回写入行数。

    整批失败信号(#366/F01): 若本轮确有待采(pending 非空)、非 dry_run、且 ok==0 且零写入,
    置位 mod.LAST_BATCH_FAILED, main() 据此 exit 2 → systemd 标 failed →
    check_failed_units.py 扫到。单只失败是常态不算整批失败。

    按代码轮转，每轮最多500只；不从库内零星非空值猜上游完整发布日期。
    进度文件邻接实际连接的DB，复用原子助手；损坏时明示重头复查，不跳过未知基金。
    单基金落库后才记尝试位置；中断最多重试一只，COALESCE保证可安全重放。
    dry_run只读已存在的库；limit调试小样不读写轮转位置。
    """
    global LAST_BATCH_FAILED
    LAST_BATCH_FAILED = False  # 每轮重置, 防同进程跨轮残留(合法空数据/锁占/无待采均保持 False)
    if days < 0 or batch < 1 or (limit is not None and limit < 1):
        raise ValueError("days须非负，batch/limit须为正整数")
    if fund_code is not None and (not isinstance(fund_code, str) or len(fund_code) != 6
                                  or not fund_code.isascii() or not fund_code.isdigit()):
        raise ValueError("fund_code须为6位ASCII数字")
    if not _acquire_lock(nonblock=True, lock_name="public_fund"):
        print("[fof_nav] WARN public_fund.lock 被占, 跳过(防与 daily/quarterly 并发写同库)",
              flush=True)
        return 0
    target_rows = None
    if dry_run or fund_code is not None:
        conn = sqlite3.connect(DB_PATH.absolute().as_uri() + "?mode=ro", uri=True, timeout=10)
        conn.execute("PRAGMA query_only=ON")
        if fund_code is not None:
            target_rows = list(conn.execute(
                "SELECT * FROM (" + SELECT_SQL + ") WHERE fund_code=?", (fund_code,)))
            if not target_rows:
                print(f"[fof_nav] 非既有FOF/QDII目标 {fund_code}，跳过(未写库)", flush=True)
                conn.close()
                return 0
            if not dry_run:
                conn.close()
    if not dry_run:
        init_db()  # 在现有同库锁内初始化；dry_run不迁移/建库/设置WAL。
        conn = get_conn()
    end = date.today()
    start = end - timedelta(days=days)
    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")
    all_funds = target_rows if target_rows is not None else list(conn.execute(SELECT_SQL))
    total_pool = len(all_funds)
    progress = None
    last_code = ""
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
        except FileNotFoundError:
            pass
        except (ValueError, KeyError, TypeError):
            print("[fof_nav] WARN 轮转进度损坏，从头复查(不代表已补齐)", flush=True)
            last_code = ""
    pending = [r for r in all_funds if r[0] > last_code] + [r for r in all_funds if r[0] <= last_code]
    pending = pending[:min(limit if limit is not None else batch, BATCH_SIZE)]
    run_batch = len(pending)

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
    for idx, (fund_code, fund_name, fund_type) in enumerate(pending, 1):
        try:
            rows = fetch_lsjz(fund_code, start_str, end_str)
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
                conn.commit()  # 每只一个原子事务
            if rows:
                total_written += len(rows)
                ok += 1
        except Exception as e:
            # P2-C(2026-11-05): 显式回滚, 保证失败那只零落库、不影响下一只。
            # 旧代码只计数不回滚: 失败那只的部分写入留在未提交事务里, 会被下一只
            # 的 commit 一起提交。失败基金本轮不留部分NAV，下次轮转仍会复查。
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            error_count += 1  # 真实异常计入整批判据
            fail += 1
            print(f"[fof_nav] FAIL {fund_code} {fund_type}: {e}", flush=True)
        if progress is not None:
            try:
                atomic_write_json(progress, {"version": 1, "last_code": fund_code})
            except OSError:
                conn.close()
                raise  # 进度写失败必须非零退出，不能假称后批可续跑。
        if idx % 50 == 0:
            print(f"[fof_nav] 进度 {idx}/{len(pending)} ok={ok} fail={fail} "
                  f"empty={empty} error={error_count} written={total_written} "
                  f"{time.time()-t0:.0f}s", flush=True)
        time.sleep(RATE_LIMIT)
    conn.close()
    remaining = total_pool - len(pending)
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


def main() -> int:
    ap = argparse.ArgumentParser(description="#333 批1 FOF/QDII 净值采集器")
    ap.add_argument("--days", type=int, default=7, help="拉近 N 自然日(默认 7)")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 只(调试, 优先于 --batch)")
    ap.add_argument("--batch", type=int, default=BATCH_SIZE,
                    help=f"每轮最多采 N 只(默认/上限 {BATCH_SIZE}, 持久轮转续跑)")
    ap.add_argument("--dry-run", action="store_true", help="只拉不写")
    ap.add_argument("--fund-code", help="只复查指定6位基金代码(须为既有FOF/QDII，不动全局轮转进度)")
    args = ap.parse_args()
    try:
        n = collect(days=args.days, limit=args.limit, dry_run=args.dry_run, batch=args.batch,
                    fund_code=args.fund_code)
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
