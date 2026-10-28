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

数据就绪闸: 开盘价取不到(兜底链修复后, 主源+腾讯/新浪双源均取不到才算取不到) /
    数据日期陈旧(fund_etf_spot_em「数据日期」!= 执行日, F4, 已并入兜底优先) → 跨 9:30 锚点
    重试(墙钟锚点 09:28/09:31/09:35/09:40, 预算硬顶 900s, 2026-10-13 跨窗口治本) → 仍失败
    → severe 告警 + 买入行 status_text「伪跳空校验未完成(待人工)」(干跑阶段, 不真实下单)。
    陈旧快照绝不照算旧价(防 9:26 拉到昨日数据误剔真实跳空)。

幂等: 执行日买入行已有「伪跳空」标记 → 跳过, 不重复标记/通知。

存量死标记清理(2026-10-13): 历史遗留的「伪跳空校验未完成(待人工)」行(执行日已过)每日运行时
    按行内 order_price + etf_daily 执行日 open 重判(纯历史, 零实时接口) → 非伪跳空复位「待执行」/
    仍伪跳空标「伪跳空剔除」/ open 缺失保持不动。`--recheck-pending` 可立即清(date<=today)。

用法:
    python scripts/nextday_gap_check.py [--date YYYYMMDD] [--dry-run] [--no-r2] [--no-notify]
        [--test-open "code:price,code2:price2"] [--no-retry] [--retry-targets "HH:MM:SS,…"]
        [--recheck-pending]
    # --test-open 注入假开盘价(自测, 不拉 akshare); --dry-run 只计算打印不落盘不 R2 不通知
    # --recheck-pending 只清存量死标记后返回(不跑计划校验/标记)
日志: data/logs/nextday_gap_check_launchd.log(标准开始/结束行, schedule_monitor 可读)。
"""
import argparse
import json
import os
import sqlite3
os.environ.setdefault("NOTIFY_SOURCE", os.path.basename(__file__))  # #245 批2 W1: 台账 source 溯源
import subprocess
import sys
import time
from datetime import datetime, date, timedelta
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
from notify_sent import notify_state  # noqa: E402  (#241 Pattern B/W2: 三态判据, 同 notify_sent 唯一实现)
from util_atomic import atomic_write_json  # noqa: E402  (原子写公共模块, 2026-09-22 非 kelly 链路统一)

try:  # R2 等锁超时诊断(2026-10-23 同类面): 只读 lsof + 子进程输出尾段。
    # A 方案后上传可能走全局锁或小锁 ⇒ 逐把探测(probe_locks + lock_paths_from_env)。
    # 辅助模块缺失/异常不得影响主流程(fail-safe): 退化为空串(与传统日志一致)。
    from r2_lock_probe import lock_paths_from_env, probe_locks, subprocess_output_tail  # noqa: E402
except Exception:  # noqa: BLE001
    def lock_paths_from_env(include_domains=False):  # noqa: D401
        return []

    def probe_locks(_paths):  # noqa: D401
        return ""

    def subprocess_output_tail(_exc, limit=2000):  # noqa: D401
        return ""

LOG_TAG = "[nextday_gap_check]"

# ── 跨 9:30 锚点重试(2026-10-13 跨窗口治本; 替代 #246 B4-2 的 60s×3 短退避) ──
# 根因: B4-2 的「60s×3 + ±25% jitter」(实际退避 135~225s, 末次尝试 ≈9:29:37)使**整个重试
# 窗口整体落在主源恢复点之前**(实测恢复点 9:31~9:40: 10-08 东财 9:31 恢复、10-09/10-12 9:40
# 链路健康)⇒ 必然全败 exit=2。改为按**墙钟锚点**重试: 首拉仍 9:26(保「源正常即秒过」早成功
# 路径), 重试锚点 09:28/09:31/09:35/09:40(跨过 9:30 开盘线 + 主源风控恢复点)。
# RETRY_BUDGET_S=900 = 各锚点等待累计硬顶(9:26 首拉起最坏 120+180+240+300=840s), 须 ≤ 外层
# systemd 墙(`TimeoutStartSec`, 2026-10-13 由 600 抬到 1800; 见 _sync_r2_and_notify 内 #223 注释)。
# 锚点确定性(无 jitter/随机) ⇒ 计划纯函数可逐位复现。
RETRY_TARGETS = ("09:28:00", "09:31:00", "09:35:00", "09:40:00")  # 墙钟重试锚点(HH:MM:SS)
RETRY_BUDGET_S = 900           # 各锚点等待累计硬顶(秒; 9:26 起最坏 840s, 留裕量给尾段)


def log(msg):
    print(f"{LOG_TAG} {msg}", flush=True)


def _retry_plan(now, targets=RETRY_TARGETS, budget=RETRY_BUDGET_S):
    """生成墙钟锚点重试计划(2026-10-13 跨 9:30 锚点重试治本)。

    给定墙钟 `now`(datetime, 首拉时刻), 逐锚点算「到该锚点还需睡多久」:
        wait = max(0, 锚点 - cursor)  —— cursor = 上一轮醒来时刻(首轮 = now); 锚点已过则 0
        (立即重试, 不出现负值)。
    故 wait 为**相邻锚点间差**(9:26 首拉 → 120+180+240+300 = 840s, 恰在 09:28/09:31/
    09:35/09:40 醒来), 循环可直接 `time.sleep(wait)` 顺序执行。累计等待达/超 `budget` 时把
    当轮截到剩余预算并停止再排(硬顶 ≤ budget)。
    返回 [(target_str, wait_sec)]:target_str 原样 "HH:MM:SS", wait_sec 保留 3 位。
    纯函数(完全由 now/targets/budget 决定, 无 jitter/随机 ⇒ 可测、逐位可复现)。
    """
    plan = []
    total = 0.0
    cursor = now
    for t in targets:
        hh, mm, ss = (int(x) for x in t.split(":"))
        target_dt = cursor.replace(hour=hh, minute=mm, second=ss, microsecond=0)
        w = (target_dt - cursor).total_seconds()
        if w < 0:
            w = 0.0
        if total + w > budget:
            w = max(budget - total, 0.0)
        plan.append((t, round(w, 3)))
        total += w
        cursor = cursor + timedelta(seconds=w)
        if total >= budget:
            break
    return plan


def _severe_alert(subject, body):
    """严重失败告警(notify.py --severe, 带 dedup 防轰炸; 同生成器 _severe_alert 先例)。"""
    log_path = REPO / "data" / "logs" / "nextday_gap_check_launchd.log"
    cmd = [PY, str(SCRIPT_DIR / "notify.py"), subject, body,
           "--severe", "--from-prefix", "[告警]",
           "--alert-issue", subject, "--alert-log", str(log_path),
           "--dedup-key", "nextday_gap_check_fail", "--dedup-window", "3600"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        # #241 Pattern B / W2(2026-10-10): 本函数 fire-and-forget(不 gate 行为), 仅把无判别力
        # 的 rc 换为可读三态(state), 便于排障时看出「真发出 / 被抑制 / 未发出」。
        _st = notify_state((r.stdout or "") + "\n" + (r.stderr or ""))
        log(f"severe 告警 state={_st} rc={r.returncode}")
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

    #254(2026-10-12): _fetch_intraday_open_prices 改返回 (out, zero_volume, meta) 且不再 raise;
    gap-check 是另一条已发布流程, **语义冻结不启用放宽** → 此处按 out 是否为空自行 re-raise,
    行为与放宽前逐字一致(仅「取了真价」才算成功, 零成交/取不到都视为未就绪)。
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
    out, _zero_volume, _meta = _fetch_intraday_open_prices(codes, expect_date=expect_date)
    # gap-check 冻结语义保持(§23.7): 本流程不启用 #254 放宽, out 为空仍 fail-closed(re-raise)
    if not out:
        raise RuntimeError("就绪闸: 未取得任何目标真实开盘价(fail-closed)")
    return out


def main():
    ap = argparse.ArgumentParser(description="次日买入计划伪跳空二次剔除(执行日 9:26)")
    ap.add_argument("--date", default=None, help="执行日 T+1(YYYYMMDD, 缺省=今天)")
    ap.add_argument("--dry-run", action="store_true", help="只计算打印, 不落盘/不 R2/不通知")
    ap.add_argument("--no-r2", action="store_true", help="落盘但不传 R2(自测用)")
    ap.add_argument("--no-notify", action="store_true", help="落盘但不通知(自测用)")
    ap.add_argument("--test-open", default=None, help='自测用假开盘价 "code:price,code2:price2"')
    ap.add_argument("--no-retry", action="store_true", help="禁用就绪重试(自测用)")
    ap.add_argument("--retry-targets", default=None,
                    help='墙钟重试锚点, 逗号分隔 "HH:MM:SS,HH:MM:SS"(默认 09:28:00,09:31:00,09:35:00,09:40:00)')
    ap.add_argument("--recheck-pending", action="store_true",
                    help="只清理存量「伪跳空校验未完成(待人工)」死标记(范围 date<=today)后返回, 不跑计划校验")
    args = ap.parse_args()

    today = args.date or _today()
    data_dir = REPO / "static-site" / "data"
    git_data_dir = GIT_REPO / "static-site" / "data"

    plan_doc, _ = _read_first([data_dir, git_data_dir], "nextday_plan.json")
    steps_doc, steps_path = _read_first([data_dir, git_data_dir], "auto_trade_steps.json")

    # etf_daily 库(同 nextday_plan_generator: REPO 优先, 回退 ROOT)
    db_path = REPO / "data" / "etf_national_team.db"
    if not db_path.exists():
        db_path = ROOT / "data" / "etf_national_team.db"

    # ---- 挂载点 B: --recheck-pending 独立清理模式(范围 date<=today, 不跑计划校验/标记) ----
    if args.recheck_pending:
        changed = _recheck_stale_pending(
            steps_doc, today, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), db_path,
            include_today=True)
        if args.dry_run:
            log("DRY-RUN: 不落盘不 R2 不通知(--recheck-pending)")
            return 0
        if changed:
            _persist_steps(steps_doc, data_dir, git_data_dir)
        else:
            log("--recheck-pending: 无死标记需清理(0 改动)")
        r2_rc, notify_rc = _sync_r2_and_notify([], changed, today,
                                               no_r2=args.no_r2, no_notify=args.no_notify)
        return 1 if (r2_rc or notify_rc) else 0

    # ---- 挂载点 A: 日常运行时自动清存量死标记(范围 date<today; 不动当天行) ----
    steps_changed = _recheck_stale_pending(
        steps_doc, today, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), db_path,
        include_today=False)
    if steps_changed and not args.dry_run:
        _persist_steps(steps_doc, data_dir, git_data_dir)

    def _sync_recheck():
        """早退/无剔除出口: recheck 有改动时补一次 R2 同步(§22 三步; dry-run 不落盘不推)。"""
        if steps_changed and not args.dry_run:
            r2_rc, notify_rc = _sync_r2_and_notify([], True, today,
                                                   no_r2=args.no_r2, no_notify=args.no_notify)
            if r2_rc or notify_rc:
                log(f"⚠ recheck 清理的线上同步未完全成功(r2_rc={r2_rc} notify_rc={notify_rc})")

    if plan_doc is None:
        log(f"nextday_plan.json 不存在, 无计划可校验, 跳过(退出 0)")
        _sync_recheck()
        return 0
    if not isinstance(plan_doc.get("plan"), list) or not plan_doc["plan"]:
        log(f"nextday_plan.json 空计划({plan_doc.get('empty')}), 无执行日买入, 跳过")
        _sync_recheck()
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
        _sync_recheck()
        return 0
    log(f"执行日 {today} 计划内 ETF={len(target)}: {sorted(target)}")

    # ---- 拉开盘价(就绪闸 + 跨 9:30 锚点重试) ----
    opens = None
    last_err = ""
    if args.test_open:
        opens = _fetch_opens(list(target.keys()), args.test_open)
        log(f"--test-open 注入开盘价: {opens}")
    else:
        retry_targets = (tuple(t.strip() for t in args.retry_targets.split(",") if t.strip())
                         if args.retry_targets else RETRY_TARGETS)
        plan = [] if args.no_retry else _retry_plan(datetime.now(), targets=retry_targets)
        total_attempts = 1 + len(plan)
        for attempt in range(1, total_attempts + 1):
            try:
                # F4: 传执行日 today 做数据日期新鲜度校验(陈旧快照抛 RuntimeError 走重试链)
                opens = _fetch_opens(list(target.keys()), None, today)
                if attempt > 1:
                    # Fix B(2026-09-23): 重试成功显式标记, 供 gen_schedule_stats 扫描侧
                    # 识别"窗口内异常后自愈"(否则 ConnectionError 命中即报, 卡 active 至今)。
                    # ⚠️ 纯标记, 不拼 last_err: last_err 含 "ConnectionError:" 会自命中
                    # ANOMALY_RE 且不含「拉开盘价失败」导致抑制不生效照样报(主控揪出, 09-23)。
                    # 失败原因上一行 "⚠ 第 N 次拉开盘价失败: {last_err}" 已有。
                    log(f"✓ 重试成功(第{attempt - 1}次失败后重试)")
                break
            except RuntimeError as e:
                last_err = str(e)
                log(f"⚠ 第 {attempt} 次拉开盘价失败: {last_err}")
                if args.no_retry or attempt == total_attempts:
                    opens = None
                    break
                target_str, wait = plan[attempt - 1]
                log(f"等到 {target_str} 重试(第 {attempt}/{len(plan)} 轮, 等 {wait:.0f}s, 预算≤{RETRY_BUDGET_S}s)")
                time.sleep(wait)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if opens is None:
        # 就绪闸 FAIL: severe 告警 + 全部买入行标记「伪跳空校验未完成(待人工)」
        _severe_alert(
            f"[告警] 次日买入计划伪跳空校验未完成 {today}",
            f"nextday_gap_check.py: 执行日 {today} 拉取开盘价跨 9:30 锚点重试(09:28/09:31/09:35/09:40)后仍失败, 无法完成伪跳空剔除, "
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
        _sync_recheck()
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
    # steps_changed 已在挂载点 A 处按 recheck 结果初始化(有改动=True), 此处不重置;
    # 下方 _mark_steps 用 `or steps_changed` 累加, 保证 recheck 改动不丢(§22 同步闭环)。
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


def _persist_steps(steps_doc, data_dir, git_data_dir):
    """把 steps_doc 原子写两树(static-site/data;§22 数据一致性)。"""
    for sp in [data_dir / "auto_trade_steps.json", git_data_dir / "auto_trade_steps.json"]:
        sp.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(sp, steps_doc, indent=1)
    log("auto_trade_steps 落盘(recheck 清死标记)")


def _open_one(cur, code, day):
    """取 etf_daily 该 code 在 day(YYYYMMDD)的真实开盘价;取不到返回 None。

    过滤口径与 nextday_plan_generator._next_open 同款(排除盘中占位行 etf_name<>etf_code +
    open 非空);本处按 exact date 命中执行日当天行(生成器用 date>after_date 取次日, 语义不同)。
    """
    cur.execute(
        "SELECT open FROM etf_daily WHERE etf_code=? AND date=? "
        "AND etf_name<>etf_code AND open IS NOT NULL LIMIT 1",
        (str(code), str(day)),
    )
    row = cur.fetchone()
    return None if row is None else float(row[0])


def _recheck_stale_pending(steps_doc, today, now, db_path, include_today=False):
    """重判存量「伪跳空校验未完成(待人工)」死标记(2026-10-13 治本; 纯历史读取, 零实时接口)。

    病灶(§4): 标记一旦落下, 既有链路(date==today 只标当天 + 幂等跳过 + 成功路径不覆盖 +
    生成器 gate_past 禁 replace)使历史行永不重访 ⇒ 误标行滞留(实测 9 行 20+ 天)。
    本函数按行内 order_price(生成时冻结的信号日收盘)+ etf_daily 执行日 open 重判(同式同阈值
    PSEUDO_GAP_EXCLUDE, 与 9:26 当日判定一致;防前视 §5.1⑥: 只用「信号日收盘 + 执行日开盘」
    两个当时已固定的量):
      - open 取不到(数据缺失)→ 保持不动(仍「待人工」, 不算错), log 一行
      - |gap| > PSEUDO_GAP_EXCLUDE → status="skipped" + status_text「伪跳空剔除(…)」
      - 否则 → status="pending" + status_text「待执行」
    幂等: 结果与现状逐字一致时不写(不刷 updated_at)⇒ 重跑零改动。
    范围: 默认 date<today(不动当天行, 当天归正常流程);include_today=True → date<=today。
    DB 只读(mode=ro);任何 DB 异常 → 返回 False(保持待人工, 防误清)。
    返回 bool 是否有改动(供调用方落盘 + R2 同步)。
    """
    if steps_doc is None or not isinstance(steps_doc.get("steps"), list):
        return False
    if not Path(db_path).exists():
        log(f"  ~ recheck: DB 不存在({db_path}), 保持待人工")
        return False
    con = None
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cur = con.cursor()
        changed = False
        n_hit = n_clear = n_stay = 0
        for s in steps_doc["steps"]:
            if not isinstance(s, dict):
                continue
            if str(s.get("action")) != "buy":
                continue
            if "伪跳空" not in str(s.get("status_text") or ""):
                continue
            d = str(s.get("date") or "")
            if not d:
                continue
            if include_today:
                if d > today:
                    continue
            elif d >= today:
                continue
            code = str(s.get("etf_code") or "")
            try:
                op = float(s.get("order_price"))
            except (TypeError, ValueError):
                log(f"  ~ recheck: {d}/{code} 无 order_price, 保持待人工")
                n_stay += 1
                continue
            if op <= 0:
                n_stay += 1
                continue
            o = _open_one(cur, code, d)
            if o is None or o <= 0:
                log(f"  ~ recheck: {d}/{code} etf_daily 无 open, 保持待人工")
                n_stay += 1
                continue
            n_hit += 1
            gap = o / op - 1.0
            if abs(gap) > PSEUDO_GAP_EXCLUDE:
                new_status, new_text = "skipped", f"伪跳空剔除(|开盘/信号日收盘-1|={abs(gap):.2%})"
            else:
                new_status, new_text = "pending", "待执行"
            if str(s.get("status")) == new_status and str(s.get("status_text")) == new_text:
                continue  # 幂等: 结果与现状逐字一致 → 不写(不刷 updated_at)
            s["status"] = new_status
            s["status_text"] = new_text
            s["updated_at"] = now
            changed = True
            n_clear += 1
            log(f"  ✓ recheck: {d}/{code} seq={s.get('seq')} → {new_status}「{new_text}」"
                f"(open={o} 信号日收盘={op} gap={gap:+.2%})")
        log(f"  recheck 汇总: 可判 {n_hit} 行 / 清理 {n_clear} 行 / 保持待人工 {n_stay} 行")
        return changed
    except Exception as e:
        log(f"  ⚠ recheck: DB 读取异常, 保持待人工(不清理): {e}")
        return False
    finally:
        if con is not None:
            con.close()


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
                # 2026-10-28 分域+梯度: 顶层 data/*.json 域; 锁等待 200s < 本层 subprocess timeout 300s。
                env["R2_UPLOAD_LOCK_DOMAIN"] = "data"
                env["R2_UPLOAD_LOCK_TIMEOUT"] = "200"
                # #223(2026-10-06 记录 / 2026-10-13 更新): timeout=300 vs 内层 R2 HTTP 超时
                # (云上 .env=600)本为梯度倒置; 但本链外层 systemd TimeoutStartSec 已由 600 抬到
                # 1800(2026-10-13 跨窗口治本, 见 trade-nextday-gap-check.service), 300 仍安全
                # (墙 1800 > 300 + 尾段裕量)。#223 的「梯度倒置」属另案, 勿在此顺手改 300。
                r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
                log(f"R2 退出码={r.returncode}\n{r.stdout}")
                if r.returncode != 0:
                    log(f"⚠ R2 上传失败: {r.stderr[-2000:]}")
                    r2_rc = 1
            except Exception as e:
                # 2026-10-23 同类面(与 nextday_plan_generator C 方案同病灶): capture_output=True 把
                # 子进程 stderr 的等锁心跳全吞掉, 日志里只剩「Command ... timed out」看不出在等锁。
                # 这里补 stderr 尾段 + 只读持锁候选; **不改 timeout(=300)、不改退出码(r2_rc=1)**。
                _tail = subprocess_output_tail(e)
                _holder = probe_locks(lock_paths_from_env(include_domains=True))
                log(f"⚠ R2 上传异常: {e}\n"
                    f"  子进程输出尾段(等锁心跳): {_tail or '(空)'}\n"
                    f"  锁占用探测(lsof 只读, 全局锁/小锁逐把): "
                    f"{_holder or '(探测不到, 可人工 lsof 排查)'}")
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
                # #241 Pattern B / W2(2026-10-10): rc 无判别力(notify.py main() 所有出口恒
                # return 0)。改三态判据: sent=真发出; suppressed=被 dedup 窗口抑制(已发过,
                # 成功且已知); failed/未知=保守置 notify_rc=1(交包装层告警/重试)。
                out = (r.stdout or "") + "\n" + (r.stderr or "")
                state = notify_state(out)
                log(f"notify 退出码={r.returncode} state={state}")
                if state not in ("sent", "suppressed"):
                    log(f"⚠ notify 未发出 state={state} rc={r.returncode}")
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
