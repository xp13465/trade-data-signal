#!/usr/bin/env python3
"""Task#10 数据源韧性修复批·机检断言(证伪式自测:T1/T2/L46④)

目的:数据源三线故障修复批(docs/ops/data-source-outage-diagnosis-20260827.md)的机检。
     证伪式自测:先打在病灶代码上跑出 FAIL(点名病灶),修复后同断言 PASS,
     两段输出均保留作证据(参照北向批先 33/38 -> 38/38 模式)。

方法口径:
  A组(T1 baostock 降并发+请求间限速):
    A1 runner.py 两处 BAOSTOCK_WORKERS env 默认值必须为 "1"(降并发防封禁面扩大)
    A2 baostock_parallel.py 函数签名/CLI 默认 n_workers 必须为 1
    A3 baostock_worker.py 主循环必须有请求间限速(BAOSTOCK_QUERY_INTERVAL)
    A4 baostock_worker.py 必须有连续失败指数退避(BAOSTOCK_FAIL_BACKOFF)
    A5 行为级:A3/A4 的退避计算函数 _fail_backoff_seconds 纯逻辑断言(30/60/120 cap)
  B组(T2 mootdx progress 宇宙缩水根治,DB 为事实源):
    B1 mootdx_daily.py 必须有 DB 对账函数(load_progress_reconciled / db_progress_snapshot)
    B2 mootdx_daily.save_progress 必须有缩水护栏(len(progress)<库中事实 code 数 -> 拒绝写盘)
    B3 runner.py mootdx step 必须用 reconciled load 切 todo(入口执行面:85 只宇宙不再放大)
    B4 行为级(reconcile):临时 DB 塞 300 codes 事实 -> 残缺 progress(85 只) ->
       load_progress_reconciled() 后 universe 恢复 == DB 事实全集,且 max(date) 对齐
    B5 行为级(护栏):残缺 dict 直接 save_progress -> 返回 False + 文件内容未被覆盖 +
       stderr 含 progress-guard;完整 dict save -> 返回 True 落盘
    B6 同病灶同修(baostock_daily.save_progress):同样存在覆盖性写入且当前无缩水护栏
  C组(L46④ notify severe 统一镜像 latest.md,追加式注册表,防旁路出口):
    C1 send(severe=True) 在三渠道 stub 下必须在 ALERTS_FILE(monkeypatch 到 tmp)追加条目,
       条目含 时间戳/[severe] 标记/来源/摘要(body 片段);dry_run=True 不落盘
    C2 追加式:两次 severe 两条都在(cap 内),旧 write_alert 详情区不被追加动作抹掉
    C3 write_alert 覆盖式重写后,已有 severe 流水仍保留(write_alert 不再抹流水)

输入依赖:仅本仓源码(app/collector/*.py scripts/notify.py)+ tempfile 临时目录;
         不读写生产 DB(data/stock_daily.db / sentiment.db 均不触碰);
         三渠道(email/tg/feishu)全部 monkeypatch stub,绝不真发。
输出:stdout PASS/FAIL 清单;exit 0=全部 PASS,1=任一 FAIL。
关键参数种子:A1 workers=1;A2 interval=0.5s;A3 backoff base=30 cap=120;
             B 护栏拒绝条件=len(progress)<db_code_count;C 流水 cap=50 条。
复现命令:/Users/linhuichen/code/trade/.venv/bin/python scripts/check_ds_resilience.py
数据截止:代码态校验,与数据日期无关;首跑于 2026-08-27(修复前 FAIL 版本留证)。
"""
from __future__ import annotations

import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import contextlib
from pathlib import Path

REPO = Path(__file__).absolute().parent.parent
WORKER = REPO / "app" / "collector" / "baostock_worker.py"
PARALLEL = REPO / "app" / "collector" / "baostock_parallel.py"
RUNNER = REPO / "app" / "collector" / "runner.py"
MOOTDX = REPO / "app" / "collector" / "mootdx_daily.py"
BAOS_DAILY = REPO / "app" / "collector" / "baostock_daily.py"
NOTIFY = REPO / "scripts" / "notify.py"

RESULTS: list[tuple[bool, str, str]] = []  # (ok, name, detail)


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((bool(ok), name, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  | {detail}" if detail else ""))


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ──────────────────────────── 静态断言(A/B 入口) ────────────────────────────
def static_checks() -> None:
    # A1: runner BAOSTOCK_WORKERS 默认值必须是 "1"(病灶现状=两处 `"3"` 放大并发封禁面)
    r = read(RUNNER)
    n_default3 = r.count('os.environ.get("BAOSTOCK_WORKERS", "3")')
    n_default1 = r.count('os.environ.get("BAOSTOCK_WORKERS", "1")')
    check("A1 runner BAOSTOCK_WORKERS 默认=1", n_default3 == 0 and n_default1 >= 2,
          f'default"3"出现{n_default3}次 default"1"出现{n_default1}次')

    # A2: parallel 签名与 CLI 默认 workers=1
    p = read(PARALLEL)
    sig_bad = "n_workers=3" in p
    cli_bad = 'n_workers = 3' in p
    check("A2 baostock_parallel 默认 n_workers=1", not sig_bad and not cli_bad and "n_workers=1" in p,
          f"签名默认3={sig_bad} CLI默认3={cli_bad}")

    # A3/A4: worker 限速 + 失败退避参数化(病灶现状=循环体零 sleep 连发)
    w = read(WORKER)
    check("A3 worker 请求间限速 BAOSTOCK_QUERY_INTERVAL",
          "BAOSTOCK_QUERY_INTERVAL" in w and "_QUERY_INTERVAL" in w)
    check("A4 worker 失败指数退避 BAOSTOCK_FAIL_BACKOFF",
          "BAOSTOCK_FAIL_BACKOFF" in w and "_FAIL_BACKOFF" in w)
    check("A4b 10001011 熔断行为保持现状(短路不假重试)",
          "circuit_open" in w and "10001011" in w)

    # B1-B3: mootdx reconcile/护栏/runner 入口
    m = read(MOOTDX)
    check("B1 mootdx DB 对账函数存在(db_progress_snapshot/load_progress_reconciled)",
          "def db_progress_snapshot" in m and "def load_progress_reconciled" in m)
    check("B2 mootdx save_progress 缩水护栏(progress-guard)",
          "progress-guard" in m and "db_code_count" in m)
    r2 = read(RUNNER)
    check("B3 runner mootdx step 用 reconciled load 切 todo",
          "mootdx_daily.load_progress_reconciled()" in r2)
    b = read(BAOS_DAILY)
    check("B6 baostock save_progress 同款缩水护栏(同病灶同修)",
          "progress-guard" in b)

    # D 组静态(T3 akshare 三级兜底转正 + stock_daily T2 配套 + T4 换手率备源参数化)
    m3 = read(MOOTDX)
    check("D1a mootdx akshare fallback 函数与预算常量",
          "def _run_akshare_fallback" in m3 and "AKSHARE_FALLBACK_BUDGET" in m3
          and '"1500"' in m3)
    check("D1b akshare fallback 契约三件(fetch_one/CooldownError捕获/北交所skip)",
          "_sd.fetch_one(code, start, today)" in m3
          and "except _sd.CooldownError" in m3
          and 'code.startswith(("8", "4", "92"))' in m3)
    check("D1c 12列->10列映射取[0..7,9,11](amplitude/pct_amt弃,turnover服务端值)",
          "(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[9], r[11])" in m3)
    n_wire_call = m3.count("_run_akshare_fallback(") - m3.count("def _run_akshare_fallback")
    check("D1d run_batch 两处接线(client失败分支+aborted分支)",
          n_wire_call >= 2 and m3.count("ak_rows, ak_ok") >= 2,
          f"调用点={n_wire_call} 接线段={m3.count('ak_rows, ak_ok')}处")
    sd = read(REPO / "app" / "collector" / "stock_daily.py")
    check("D2 stock_daily T2 三件套(snapshot/reconciled/护栏)",
          "def db_progress_snapshot" in sd and "def load_progress_reconciled" in sd
          and "progress-guard" in sd)
    r3 = read(RUNNER)
    check("D3 runner stock_daily step 用 reconciled load",
          "stock_daily.load_progress_reconciled()" in r3)
    c2 = read(REPO / "app" / "collector" / "cleanup_d3d2.py")
    check("D4a cleanup turnover 取数 source 参数化(baostock默认+mootdx表映射)",
          c2.count('source: str = "baostock"') >= 2
          and '{"baostock": "baostock_daily_raw", "mootdx": "mootdx_daily_raw"}' in c2)
    check("D4b CLI --source 校验只放行 baostock/mootdx",
          '--source' in c2 and 'src not in ("baostock", "mootdx")' in c2)


# ──────────────────────────── 行为断言(A5/B4/B5) ────────────────────────────
def behavior_checks() -> None:
    # A5: worker._fail_backoff_seconds 纯逻辑(consecutive_fails -> 秒数)
    try:
        wmod = load_module("ds_worker_under_test", WORKER)
        fn = getattr(wmod, "_fail_backoff_seconds", None)
        if fn is None:
            check("A5 退避秒数函数行为", False, "worker 无 _fail_backoff_seconds")
        else:
            cases = [(2, 30), (3, 60), (4, 120), (9, 120)]
            got = [(n, fn(n)) for n, _ in cases]
            ok = all(fn(n) == s for n, s in cases)
            check("A5 退避秒数 30/60/120cap", ok, f"got={got}")
    except Exception as e:  # noqa: BLE001
        check("A5 退避秒数函数行为", False, f"加载 worker 失败: {type(e).__name__}: {e}")

    # B4/B5: mootdx reconcile + 护栏(临时 DB/progress,不碰生产)
    with tempfile.TemporaryDirectory() as td:
        try:
            mmod = load_module("ds_mootdx_under_test", MOOTDX)
            tmp_db = Path(td) / "stock_daily.db"
            tmp_prog = Path(td) / "mootdx_progress.json"
            mmod.STOCK_DB_PATH = tmp_db
            mmod.PROGRESS_PATH = tmp_prog
            mmod.init_db()

            today = "20260822"  # 与下方入库数据的 MAX(date) 对齐(断言尺子=库事实)
            conn = sqlite3.connect(tmp_db)
            codes = [f"{i:06d}" for i in range(300)]  # 库中事实:300 codes
            rows = []
            for c in codes:
                for d in ("20260820", "20260821", "20260822"):
                    rows.append((c, d, 1.0, 1.0, 1.0, 1.0, 100, 100, 1.0, None))
            conn.executemany(
                "INSERT OR REPLACE INTO mootdx_daily_raw "
                "(code,date,open,high,low,close,volume,amount,pct_change,turnover) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            conn.commit()
            conn.close()

            # 磁盘现状 = 残缺 progress(85 只,last 停在旧行;模拟 7/21 SIGTERM 抹损后文件)
            broken = {c: "20260819" for c in [f"{i:06d}" for i in range(85)]}
            tmp_prog.write_text(json.dumps(broken), encoding="utf-8")

            prog, fixed = mmod.load_progress_reconciled()
            ok_b4 = len(prog) == 300 and all(prog[c] >= today for c in codes)
            check("B4 reconcile 从 DB 重建宇宙(85->300=max对齐)", ok_b4,
                  f"universe={len(prog)} fixed={fixed} min_max_date="
                  f"{min(prog.values())}")

            # B5 护栏:残缺 dict save 被拒
            err_buf = io.StringIO()
            with contextlib.redirect_stderr(err_buf):
                rc = mmod.save_progress(broken)  # len=85 < db_code_count=300
            on_disk = json.loads(tmp_prog.read_text(encoding="utf-8"))
            guard_ok = (rc is False and len(on_disk) == 300
                        and "progress-guard" in err_buf.getvalue())
            check("B5a 护栏拒绝缩水写入且磁盘未被破坏", guard_ok,
                  f"rc={rc} disk_len={len(on_disk)} stderr_has_guard="
                  f"{'progress-guard' in err_buf.getvalue()}")

            # B5b 完整 dict 正常放行
            full = {c: today for c in codes}
            rc2 = mmod.save_progress(full)
            check("B5b 完整宇宙正常写盘放行", rc2 is True, f"rc={rc2}")

            # 表不存在时护栏退化放行(全新环境可初始化)
            fresh = Path(td) / "fresh.db"
            mmod.STOCK_DB_PATH = fresh
            rc3 = mmod.save_progress({"000001": "20260824"})
            check("B5c 空表/新环境护栏退化放行", rc3 is True, f"rc={rc3}")
        except Exception as e:  # noqa: BLE001
            check("B4/B5 mootdx 行为断言", False, f"{type(e).__name__}: {e}")

    # C 组: notify severe 镜像(stub 三渠道,tmp 文件)
    with tempfile.TemporaryDirectory() as td:
        try:
            import contextlib as _ctx
            nmod = load_module("ds_notify_under_test", NOTIFY)
            tmp_dir = Path(td) / "alerts"
            nmod.ALERTS_DIR = tmp_dir
            nmod.ALERTS_FILE = tmp_dir / "latest.md"
            nmod._send_email = lambda *a, **k: True   # stub 全渠道
            nmod.send_telegram = lambda *a, **k: True
            nmod.send_feishu = lambda *a, **k: True

            res = nmod.send("[告警] baostock 封禁熔断(10001011)",
                            "<b>baostock 采集检测到账号/IP 级封禁</b><br>本轮 3 个 worker 熔断",
                            severe=True, source="runner_test")
            txt = nmod.ALERTS_FILE.read_text(encoding="utf-8") if nmod.ALERTS_FILE.exists() else ""
            c1 = ("[severe]" in txt and "来源" in txt and "runner_test" in txt
                  and "baostock 采集检测到账号/IP 级封禁" in txt.replace("<b>", "")
                  and any(ch.isdigit() for ch in txt.split("[severe]")[-1][:60]))
            check("C1 send(severe=True) 追加镜像条目(时间戳/级别/来源/摘要)", bool(c1),
                  f"len={len(txt)} 渠道结果={res}")
            # dry_run: 只读路径
            before = txt
            nmod.send("[告警] dry-run 测试", "x", severe=True, dry_run=True)
            after = nmod.ALERTS_FILE.read_text(encoding="utf-8")
            check("C1b dry_run 不落真实镜像", after == before, "dry_run 未改变 latest.md")

            # C2: 两条都保留 + write_alert 详情区不被抹
            nmod.write_alert("显式 issue 测试", "detail body")
            nmod.send("[告警] 第二条 severe", "second body marker", severe=True, source="s2")
            t2 = nmod.ALERTS_FILE.read_text(encoding="utf-8")
            check("C2 追加式两条共存+write_alert 区不被抹",
                  "第二条 severe" in t2 and "封禁熔断" in t2 and "显式 issue 测试" in t2)

            # C3: 再一次 write_alert 覆盖重写不得抹掉已积累流水
            nmod.write_alert("第二次显式 issue", "newer detail")
            t3 = nmod.ALERTS_FILE.read_text(encoding="utf-8")
            check("C3 write_alert 重写后流水保留",
                  "第二条 severe" in t3 and "封禁熔断" in t3 and "第二次显式 issue" in t3)
        except Exception as e:  # noqa: BLE001
            check("C组 notify severe 镜像", False, f"{type(e).__name__}: {e}")

    # D5-D7 行为级(Phase2:T3 akshare 映射入库 / stock_daily 护栏 / T4 备源取数)
    sys.path.insert(0, str(REPO))  # 包导入(相对导入需要 package 上下文)
    import importlib
    with tempfile.TemporaryDirectory() as td:
        try:
            amod = importlib.import_module("app.collector.mootdx_daily")
            tmp_db = Path(td) / "stock_daily.db"
            tmp_prog = Path(td) / "mootdx_progress.json"
            amod.STOCK_DB_PATH = tmp_db
            amod.PROGRESS_PATH = tmp_prog
            amod._DB_COUNT_CACHE.clear()  # 防 TTL 缓存跨测试串值
            amod.init_db()

            # monkeypatch akshare 层(_sd 同为 sys.modules 的 stock_daily 模块对象)
            sdmod = importlib.import_module("app.collector.stock_daily")
            sdmod.STOCK_DB_PATH = tmp_db
            sdmod.PROGRESS_PATH = Path(td) / "sd_progress.json"
            CALLS: list[str] = []

            def fake_fetch_one(code, start_date, end_date):
                CALLS.append(code)  # 12 列: code,date,o,h,l,c,volume,amount,
                # amplitude[8],pct_change[9],pct_amt[10],turnover[11]
                return ([(code, "20260822", 10.0, 11.0, 9.0, 10.5, 8800.0, 95700.0,
                          20.0, 4.56, 3.21, 9.10)], "")

            real_fetch = sdmod.fetch_one
            sdmod.fetch_one = fake_fetch_one
            try:
                # 北交所/新三板前缀 skip("8"/"4"/"92")+ SH/SZ 正常两只;
                # progress 齐 -> 整只去重(CALLS 不含该股);start>today 也去重请求
                prog_in = {"600000": "20260822"}
                total, ok, skip_bj = amod._run_akshare_fallback(
                    ["600000", "000001", "830799", "430047"],
                    progress=prog_in, incremental=True, today="20260822", verbose=False)
                d5a = (skip_bj == 2 and ok == 1 and total == 1 and CALLS == ["000001"]
                       and prog_in["000001"] == "20260822" and prog_in["600000"] == "20260822")
                check("D5a fallback 覆盖口径+去重+progress 固化", bool(d5a),
                      f"total={total} ok={ok} skip_bj={skip_bj} calls={CALLS}")

                # 列映射断言:库中行 == (code,date,o,h,l,c,volume,amount,r[9],r[11])
                conn = sqlite3.connect(tmp_db)
                got = conn.execute(
                    "SELECT code,date,open,high,low,close,volume,amount,"
                    "pct_change,turnover FROM mootdx_daily_raw").fetchall()
                conn.close()
                expect = ("000001", "20260822", 10.0, 11.0, 9.0, 10.5,
                          8800.0, 95700.0, 4.56, 9.10)
                d5b = len(got) == 1 and tuple(got[0]) == expect
                check("D5b 12列->10列映射精确值(amplitude/pct_amt弃)", bool(d5b),
                      f"got={got}")
            finally:
                sdmod.fetch_one = real_fetch

            # D6 stock_daily 缩水护栏(B 模式同款行为验证)
            sdb = Path(td) / "sdb.db"
            sdmod.STOCK_DB_PATH = sdb
            sdmod.init_db()
            conn = sqlite3.connect(sdb)
            conn.executemany(
                "INSERT INTO stock_daily_raw (code,date,open,high,low,close,"
                "volume,amount,pct_change,turnover) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(f"{i:06d}", "20260822", 1.0, 1.0, 1.0, 1.0, 100, 100, 1.0, None)
                 for i in range(120)])
            conn.commit()
            conn.close()
            err_buf = io.StringIO()
            with contextlib.redirect_stderr(err_buf):
                rc_bad = sdmod.save_progress({f"{i:06d}": "20260822" for i in range(50)})
            check("D6 stock_daily 护栏拒绝缩水(50<120)",
                  rc_bad is False and "progress-guard" in err_buf.getvalue(),
                  f"rc={rc_bad}")

            cmod = importlib.import_module("app.collector.cleanup_d3d2")
            # 非法 source 必须 raise(ValueError),不静默吞
            raised = False
            try:
                cmod.compute_turnover_dist(start_date="20260801",
                                           end_date="20260802", source="tencent")
            except ValueError:
                raised = True
            check("D7a cleanup 非法 source raise ValueError(腾讯源不存在,防误配)",
                  raised)

            # source=mootdx 从临时库聚合五指标正确性
            tdb = Path(td) / "t.db"
            cmod.STOCK_DB_PATH = tdb
            conn = sqlite3.connect(tdb)
            conn.execute(
                "CREATE TABLE mootdx_daily_raw (code TEXT, date TEXT, open REAL,"
                " high REAL, low REAL, close REAL, volume REAL, amount REAL,"
                " pct_change REAL, turnover REAL)")
            rows = []
            for day, turns in (("20260821", [1.0, 3.0]), ("20260822", [2.0, 6.0, 12.0])):
                for k, tv in enumerate(turns):
                    rows.append((f"{k:06d}", day, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, tv))
            # 一行 NULL turnover(mootdx 本体老数据):聚合必须剔除
            rows.append(("999999", "20260822", 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, None))
            conn.executemany(
                "INSERT INTO mootdx_daily_raw VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            conn.commit()
            conn.close()
            g = cmod.compute_turnover_dist(start_date="20260801",
                                           end_date="20260822", source="mootdx")
            g2 = g.set_index("date")
            d7b = (
                len(g) == 2
                and abs(g2.loc["20260822", "mean"] - (2 + 6 + 12) / 3) < 1e-9
                and abs(g2.loc["20260822", "gt5_pct"] - 2 / 3) < 1e-9  # >5 的有 6,12 两只
                and abs(g2.loc["20260821", "median"] - 2.0) < 1e-9
            )
            check("D7b compute(source=mootdx) 剔NULL聚合五指标正确", bool(d7b),
                  f"rows={len(g)} mean_0822={g2.loc['20260822', 'mean']:.4f} "
                  f"gt5={g2.loc['20260822', 'gt5_pct']:.4f}")

            # upsert 写入 daily_metric 带 source='mootdx' 标记(mock get_conn->临时 metric 库)
            mdb = Path(td) / "metric.db"
            mconn0 = sqlite3.connect(mdb)
            mconn0.execute(
                "CREATE TABLE daily_metric (date TEXT NOT NULL, metric_id TEXT NOT NULL,"
                " value REAL, source TEXT, updated_at TEXT,"
                " PRIMARY KEY (date, metric_id))")  # schema 与 app/db.py SCHEMA 对齐
            mconn0.close()
            orig_conn = cmod.get_conn
            cmod.get_conn = lambda: sqlite3.connect(mdb)
            try:
                res = cmod.upsert_turnover(g.copy(), source="mootdx")
                mconn = sqlite3.connect(mdb)
                srcs = {r[0] for r in mconn.execute(
                    "SELECT DISTINCT source FROM daily_metric WHERE "
                    "metric_id='a_turnover_mean'")}
                nrow = mconn.execute("SELECT COUNT(*) FROM daily_metric").fetchone()[0]
                mconn.close()
                d7c = res.get("written", 0) >= 0 and srcs == {"mootdx"} and nrow == 10
                check("D7c upsert_turnover source=mootdx 标记入 daily_metric", bool(d7c),
                      f"res={res} sources={srcs} rows={nrow}")
            finally:
                cmod.get_conn = orig_conn
        except Exception as e:  # noqa: BLE001
            check("D组 Phase2 行为断言", False, f"{type(e).__name__}: {e}")


def main() -> int:
    print(f"# check_ds_resilience @ {REPO} branch-check(证伪式自测)")
    static_checks()
    behavior_checks()
    n_pass = sum(1 for ok, _, _ in RESULTS if ok)
    print(f"\n=== {n_pass}/{len(RESULTS)} PASS ===")
    if n_pass < len(RESULTS):
        print("--- FAIL 明细 ---")
        for ok, name, detail in RESULTS:
            if not ok:
                print(f"FAIL  {name}  | {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
