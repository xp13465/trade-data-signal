#!/usr/bin/env python3
"""nextday_gap_check.py - 次日买入计划伪跳空二次剔除(执行日 9:26 定时, PRD 阶段一 §3/§6)

背景:
    nextday_plan_generator.py 在 T 日 22:30 生成次日计划时, 对「次日 open 已入库」的历史回填段
    能做真伪跳空校验(A1); 但「当日计划」的 T+1 开盘价尚未产生, 生成时只能跳过留兜底。
    本脚本在 T+1 日 9:26(集合竞价 9:25 结束、开盘价已定)拉 akshare 当日真实开盘价, 对执行日
    (date==today / buy_date==today)的买入行做二次剔除, 补齐 A1 当日跳过的缺口。

口径(与回测 signal_kelly_backtest 同式, 防前视 §5.1⑥):
    gap = 当日开盘价 / 信号日收盘 - 1.0; |gap| > PSEUDO_GAP_EXCLUDE(0.20) → 剔除(份额折算等
    非真实可交易跳空)。信号日收盘 = nextday_plan.json 条目 prev_close(= 生成器 T 日 etf_daily
    close); 当日开盘价 = akshare fund_etf_spot_em「开盘价」列(与回测 _fetch_intraday_open_prices
    同源同函数, 不另写一份)。

剔除形态(设计报告 §2):
    - auto_trade_steps.json: 执行日(date==today)该 ETF 买入行(seq1/2/3, action=buy)
      status=skipped + status_text「伪跳空剔除(|开盘/信号日收盘-1|=xx%)」
    - nextday_plan.json: 条目加 gap_excluded:true

数据就绪闸: 开盘价取不到 / 数据日期陈旧(fund_etf_spot_em「数据日期」!= 执行日, F4) → 等
    --retry-wait 秒(默认 300, 9:26→9:31)重试一次 → 仍失败 → severe 告警 + 买入行 status_text
    「伪跳空校验未完成(待人工)」(干跑阶段, 不真实下单)。陈旧快照绝不照算旧价(防 9:26 拉到
    昨日数据误剔真实跳空)。

幂等: 执行日买入行已有「伪跳空」标记 → 跳过, 不重复标记/通知。

用法:
    python scripts/nextday_gap_check.py [--date YYYYMMDD] [--dry-run] [--no-r2] [--no-notify]
        [--test-open "code:price,code2:price2"] [--no-retry] [--retry-wait 秒]
    # --test-open 注入假开盘价(自测, 不拉 akshare); --dry-run 只计算打印不落盘不 R2 不通知
日志: data/logs/nextday_gap_check_launchd.log(标准开始/结束行, schedule_monitor 可读)。
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, date
from pathlib import Path

# 运行根: 显式 REPO 优先(trade-data 运行副本), 缺省回退脚本所在仓
ROOT = Path(__file__).resolve().parent.parent
REPO = Path(os.environ.get("REPO", str(ROOT)))
GIT_REPO = Path(os.environ.get("GIT_REPO", str(ROOT)))
PY = os.environ.get("PY", str(REPO / ".venv" / "bin" / "python"))
SCRIPT_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(REPO))  # 优先 REPO(实时数据侧)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from signal_kelly_backtest import PSEUDO_GAP_EXCLUDE, _fetch_intraday_open_prices  # noqa: E402
from util_atomic import atomic_write_json  # noqa: E402  (原子写公共模块, 2026-09-22 非 kelly 链路统一)

LOG_TAG = "[nextday_gap_check]"
DEFAULT_RETRY_WAIT = 300   # 9:26 → 9:31 重试间隔(秒)


def log(msg):
    print(f"{LOG_TAG} {msg}", flush=True)


def _severe_alert(subject, body):
    """严重失败告警(notify.py --severe, 带 dedup 防轰炸; 同生成器 _severe_alert 先例)。"""
    log_path = REPO / "data" / "logs" / "nextday_gap_check_launchd.log"
    cmd = [PY, str(SCRIPT_DIR / "notify.py"), subject, body,
           "--severe", "--from-prefix", "[告警]",
           "--alert-issue", subject, "--alert-log", str(log_path),
           "--dedup-key", "nextday_gap_check_gen_fail", "--dedup-window", "3600"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        log(f"severe 告警 rc={r.returncode}")
    except Exception as e:
        log(f"⚠ severe 告警调用异常(无法送达): {e}")


def _load_json(name: str, base: Path):
    p = base / name
    if not p.exists():
        return None
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _today():
    return date.today().strftime("%Y%m%d")


def _read_first(paths, name):
    """从候选路径列表读第一个存在的 JSON 文件, 返回 (doc, path); 都不存在返回 (None, None)。"""
    for p in paths:
        doc = _load_json(name, p)
        if doc is not None:
            return doc, p
    return None, None


def _fetch_opens(codes, test_open, expect_date=None):
    """拉执行日开盘价 {etf_code: open}。

    test_open 非空 → 用注入假开盘价(自测, 不拉 akshare, 不做日期校验);
    否则复用回测 _fetch_intraday_open_prices(同源同函数, 不另写一份 akshare 拉取),
    expect_date(=执行日 today)触发 F4 数据日期新鲜度校验(fail-closed)。
    全量失败抛 RuntimeError(由调用方重试 + severe 告警)。
    """
    if test_open:
        out = {}
        for item in test_open.split(","):
            item = item.strip()
            if not item or ":" not in item:
                continue
            code, price = item.split(":", 1)
            try:
                out[code.strip()] = float(price)
            except ValueError:
                continue
        return out
    return _fetch_intraday_open_prices(codes, expect_date=expect_date)


def main():
    ap = argparse.ArgumentParser(description="次日买入计划伪跳空二次剔除(执行日 9:26)")
    ap.add_argument("--date", default=None, help="执行日 T+1(YYYYMMDD, 缺省=今天)")
    ap.add_argument("--dry-run", action="store_true", help="只计算打印, 不落盘/不 R2/不通知")
    ap.add_argument("--no-r2", action="store_true", help="落盘但不传 R2(自测用)")
    ap.add_argument("--no-notify", action="store_true", help="落盘但不通知(自测用)")
    ap.add_argument("--test-open", default=None, help='自测用假开盘价 "code:price,code2:price2"')
    ap.add_argument("--no-retry", action="store_true", help="禁用就绪重试(自测用)")
    ap.add_argument("--retry-wait", type=int, default=DEFAULT_RETRY_WAIT, help="就绪重试等待秒数(默认 300)")
    args = ap.parse_args()

    today = args.date or _today()
    data_dir = REPO / "static-site" / "data"
    git_data_dir = GIT_REPO / "static-site" / "data"

    plan_doc, _ = _read_first([data_dir, git_data_dir], "nextday_plan.json")
    steps_doc, steps_path = _read_first([data_dir, git_data_dir], "auto_trade_steps.json")

    if plan_doc is None:
        log(f"nextday_plan.json 不存在, 无计划可校验, 跳过(退出 0)")
        return 0
    if not isinstance(plan_doc.get("plan"), list) or not plan_doc["plan"]:
        log(f"nextday_plan.json 空计划({plan_doc.get('empty')}), 无执行日买入, 跳过")
        return 0

    # 执行日(date==today / buy_date==today)买入计划条目, 键 = etf_code, 值 = 信号日收盘(prev_close)
    target = {}
    for p in plan_doc["plan"]:
        if not isinstance(p, dict):
            continue
        if str(p.get("buy_date") or "") != today:
            continue
        code = str(p.get("etf_code") or "")
        pc = p.get("prev_close")
        if code and pc is not None and float(pc) > 0:
            target[code] = float(pc)

    if not target:
        log(f"执行日 {today} 无买入计划条目(buy_date==today 无有效 prev_close), 跳过")
        return 0
    log(f"执行日 {today} 计划内 ETF={len(target)}: {sorted(target)}")

    # ---- 拉开盘价(就绪闸 + 重试) ----
    opens = None
    last_err = ""
    if args.test_open:
        opens = _fetch_opens(list(target.keys()), args.test_open)
        log(f"--test-open 注入开盘价: {opens}")
    else:
        for attempt in (1, 2):
            try:
                # F4: 传执行日 today 做数据日期新鲜度校验(陈旧快照抛 RuntimeError 走重试链)
                opens = _fetch_opens(list(target.keys()), None, today)
                if attempt == 2:
                    # Fix B(2026-09-23): 重试成功显式标记, 供 gen_schedule_stats 扫描侧
                    # 识别"窗口内异常后自愈"(否则 ConnectionError 命中即报, 卡 active 至今)。
                    # ⚠️ 纯标记, 不拼 last_err: last_err 含 "ConnectionError:" 会自命中
                    # ANOMALY_RE 且不含「拉开盘价失败」导致抑制不生效照样报(主控揪出, 09-23)。
                    # 失败原因上一行 "⚠ 第 N 次拉开盘价失败: {last_err}" 已有。
                    log("✓ 重试成功(第1次失败后重试)")
                break
            except RuntimeError as e:
                last_err = str(e)
                log(f"⚠ 第 {attempt} 次拉开盘价失败: {last_err}")
                if args.no_retry or attempt == 2:
                    opens = None
                    break
                log(f"等 {args.retry_wait}s 重试(9:26→9:31)")
                time.sleep(args.retry_wait)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if opens is None:
        # 就绪闸 FAIL: severe 告警 + 全部买入行标记「伪跳空校验未完成(待人工)」
        _severe_alert(
            f"[告警] 次日买入计划伪跳空校验未完成 {today}",
            f"nextday_gap_check.py: 执行日 {today} 拉取 akshare 开盘价两次失败, 无法完成伪跳空剔除, "
            f"买入行标记「伪跳空校验未完成(待人工)」待人工复核。<br>失败原因: {last_err}"
            f"<br>日志: {REPO}/data/logs/nextday_gap_check_launchd.log",
        )
        log(f"✗ 开盘价就绪闸 FAIL(重试后仍失败): {last_err}; 标记未完成(待人工)")
        if args.dry_run:
            log("DRY-RUN: 不落盘不 R2 不通知")
            return 2
        # 标记后 steps 已改 → 与单只缺失路径共用 R2 上传 + purge + 通知(§22 三步同步)
        _mark_unverified(steps_doc, today, target, now,
                         [data_dir / "auto_trade_steps.json", git_data_dir / "auto_trade_steps.json"])
        # 就绪 FAIL 无 excluded → 仅 R2 传 auto_trade_steps.json(§22 三步同步)
        r2_rc, notify_rc = _sync_r2_and_notify([], True, today,
                                               no_r2=args.no_r2, no_notify=args.no_notify)
        if r2_rc or notify_rc:
            log(f"⚠ 就绪闸 FAIL 的线上同步未完全成功(r2_rc={r2_rc} notify_rc={notify_rc}),线上状态可能仍滞留旧计划")
        log("落盘完成(auto_trade_steps.json 未完成标记)")
        return 2

    # ---- 逐 ETF 判定 gap ----
    excluded = []      # [(code, gap)]
    unverified = []    # [code](akshare 未返回该 code 开盘价)
    for code, sig_close in target.items():
        op = opens.get(code)
        if op is None or op <= 0:
            unverified.append(code)
            log(f"  ~ {code} 开盘价未取得(op={op}), 标记未完成(待人工)")
            continue
        gap = op / sig_close - 1.0
        if abs(gap) > PSEUDO_GAP_EXCLUDE:
            excluded.append((code, gap))
            log(f"  ✗ {code} 伪跳空剔除 open={op} sig_close={sig_close} gap={gap:.2%}")
        else:
            log(f"  ✓ {code} 正常 open={op} sig_close={sig_close} gap={gap:.2%}")

    if not excluded and not unverified:
        log(f"执行日 {today} 全部 {len(target)} 笔无伪跳空, 无标记")
        return 0

    if args.dry_run:
        log("DRY-RUN: 不落盘不 R2 不通知")
        for code, gap in excluded:
            print(f"  剔除 {code} gap={gap:+.2%} status_text=伪跳空剔除(|开盘/信号日收盘-1|={abs(gap):.2%})")
        for code in unverified:
            print(f"  未完成 {code} status_text=伪跳空校验未完成(待人工)")
        return 0

    # ---- 落盘标记 ----
    written = []
    steps_changed = False
    if excluded:
        steps_changed = _mark_steps(steps_doc, today, now, "skipped", excluded) or steps_changed
        _mark_plan(plan_doc, today, excluded)
    if unverified:
        steps_changed = _mark_steps(steps_doc, today, now, "pending", unverified,
                                    status_text="伪跳空校验未完成(待人工)") or steps_changed

    if steps_doc is not None and steps_changed:
        for sp in [data_dir / "auto_trade_steps.json", git_data_dir / "auto_trade_steps.json"]:
            sp.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(sp, steps_doc, indent=1)
            written.append(str(sp))
        log(f"auto_trade_steps 落盘(steps_changed): {len(steps_doc['steps'])} 行")
    if excluded:
        # 本地权威副本 = ROOT/data(与生成器 nextday_plan_generator.py write_targets 一致),
        # 不是 REPO/data: 云上 REPO=trade-data 运行副本、ROOT=脚本所在树, 两处若分叉则 gap_excluded
        # 永远进不了生成器 docstring 声明的「本地权威」ROOT/data/nextday_plan.json(§22 reviewer F2)。
        for d in [ROOT / "data", data_dir, git_data_dir]:
            d.mkdir(parents=True, exist_ok=True)
            atomic_write_json(d / "nextday_plan.json", plan_doc, indent=1)
            written.append(str(d / "nextday_plan.json"))
        log("nextday_plan.json 落盘(gap_excluded 标记)")

    # ---- R2 上传 + purge + 通知(§22 三步同步; 与 FAIL 路径共用 _sync_r2_and_notify) ----
    r2_rc, notify_rc = _sync_r2_and_notify(excluded, steps_changed, today,
                                           no_r2=args.no_r2, no_notify=args.no_notify)
    log("落盘完成: " + ", ".join(written))
    return 1 if (r2_rc or notify_rc) else 0


def _mark_steps(steps_doc, today, now, status, items, status_text=None):
    """标记 steps 买入行。items: [(code, gap)] 或 [code]。返回是否写入新行。

    status="skipped" + status_text 由 gap 生成; status="pending" + 固定 status_text 用于未完成(待人工)。
    幂等: 已有「伪跳空」标记的买入行跳过(不重复标记)。
    """
    if steps_doc is None or not isinstance(steps_doc.get("steps"), list):
        return False
    changed = False
    items_map = {}
    for it in items:
        if isinstance(it, tuple):
            code, gap = it
            items_map[str(code)] = status_text or f"伪跳空剔除(|开盘/信号日收盘-1|={abs(gap):.2%})"
        else:
            items_map[str(it)] = status_text or "伪跳空校验未完成(待人工)"
    for s in steps_doc["steps"]:
        if not isinstance(s, dict):
            continue
        if str(s.get("date")) != today:
            continue
        if str(s.get("action")) != "buy":
            continue
        code = str(s.get("etf_code") or "")
        if code not in items_map:
            continue
        if "伪跳空" in str(s.get("status_text") or ""):
            continue  # 幂等: 已有伪跳空标记
        s["status"] = status
        s["status_text"] = items_map[code]
        s["updated_at"] = now
        changed = True
        log(f"  标记 steps {code} seq={s.get('seq')} → {status}「{items_map[code]}」")
    return changed


def _mark_plan(plan_doc, today, excluded):
    """nextday_plan.json 条目加 gap_excluded:true(仅 buy_date==today 的被剔除条目)。"""
    codes = {str(c) for c, _ in excluded}
    for p in plan_doc.get("plan", []):
        if not isinstance(p, dict):
            continue
        if str(p.get("buy_date") or "") == today and str(p.get("etf_code") or "") in codes:
            p["gap_excluded"] = True


def _mark_unverified(steps_doc, today, target, now, write_paths):
    """就绪闸 FAIL: 全部买入行标记「伪跳空校验未完成(待人工)」并落盘。write_paths=文件路径列表。"""
    codes = list(target.keys())
    changed = _mark_steps(steps_doc, today, now, "pending", codes,
                          status_text="伪跳空校验未完成(待人工)")
    if changed:
        for sp in write_paths:
            sp.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(sp, steps_doc, indent=1)
        log("auto_trade_steps 落盘(未完成标记)")


def _sync_r2_and_notify(excluded, steps_changed, today, no_r2=False, no_notify=False):
    """R2 上传 + purge + 通知(邮件+飞书)。excluded=[(code, gap)], steps_changed 决定是否推 auto_trade_steps.json。

    FAIL 路径(opens is None)与单只缺失路径共用此段(§22 三步同步; 2026-09-23 修复: FAIL 此前提前
    return 漏走 R2, 线上滞留旧计划致多展示位不一致)。返回 (r2_rc, notify_rc)。
    """
    r2_rc = 0
    if not no_r2:
        r2_files = []
        if excluded:
            r2_files.append("nextday_plan.json")
        if steps_changed:
            r2_files.append("auto_trade_steps.json")
        if r2_files:
            cmd = [PY, str(SCRIPT_DIR / "upload_r2.py"), "upload-data-files"] + r2_files
            log("R2: " + " ".join(cmd))
            try:
                env = dict(os.environ)
                env.setdefault("REPO", str(REPO))
                r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
                log(f"R2 退出码={r.returncode}\n{r.stdout}")
                if r.returncode != 0:
                    log(f"⚠ R2 上传失败: {r.stderr[-2000:]}")
                    r2_rc = 1
            except Exception as e:
                log(f"⚠ R2 上传异常: {e}")
                r2_rc = 1

    notify_rc = 0
    if not no_notify:
        if excluded:
            lines = [f"{code} 伪跳空剔除(|开盘/信号日收盘-1|={abs(gap):.2%}, open/sig_close gap={gap:+.2%})"
                     for code, gap in excluded]
            subject = f"次日买入计划伪跳空剔除 {today}"
            body = "<br>".join(lines)
            cmd = [PY, str(SCRIPT_DIR / "notify.py"), subject, body,
                   "--dedup-key", f"nextday_gap_excluded_{today}", "--dedup-window", "86400",
                   "--feishu-group", "follow"]
            log("notify: " + subject)
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                log(f"notify 退出码={r.returncode}")
                if r.returncode != 0:
                    log(f"⚠ notify 失败 rc={r.returncode}")
                    notify_rc = 1
            except Exception as e:
                log(f"⚠ notify 异常: {e}")
                notify_rc = 1

    return r2_rc, notify_rc


if __name__ == "__main__":
    try:
        rc = main()
    except SystemExit:
        raise
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        log(f"✗ 未捕获异常({type(e).__name__}): {e}\n{tb}")
        _severe_alert(
            f"[告警] 次日买入计划伪跳空校验异常 {type(e).__name__}",
            f"nextday_gap_check.py 主流程未捕获异常, 伪跳空二次剔除中断(线上文件保持上一批)。"
            f"<br>异常: <pre>{tb[-2000:]}</pre>"
            f"<br>日志: {REPO}/data/logs/nextday_gap_check_launchd.log",
        )
        sys.exit(2)
    sys.exit(rc)
