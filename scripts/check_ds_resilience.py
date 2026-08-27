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
