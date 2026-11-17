#!/usr/bin/env python3
"""check_fof_backfill.py - FOF/QDII 回补滞后 + 本轮覆盖率看门狗(2026-11-17)

【为什么需要它(病灶, 依据 /tmp/fof-budget-rca-20261117.md)】
  旧单轮 290s 预算被 recent 扫吃掉后回补被结构性截断, 但每轮仍 exit=1, 监控只看到
  「某 unit 失败」, 看不到真正的业务后果: 一部分基金的回补被推迟多个交易日。
  2026-11-17 相位拆分后回补到点软停是**正常**(rc=0, 不许当故障), 于是必须把
  「回补欠账到底积了多久」变成可判定的看门狗, 否则软完成会把真滞后洗成绿色。

【主判据(两条, 都只读采集器自己写的进度文件, 不重跑采集)】
  ① 本轮覆盖率: `last_runs.recent.attempted == last_runs.recent.selected`。
     少于 selected 且 stage_status 不是干净完成 ⇒ recent 相位没扫完全部选中基金 = 真故障
     (与 systemd rc=1 通道同源, 但这里给出「差几只」的业务口径; 宁可双报, 不静默)。
  ② 回补滞后: 对 `backfill_pending` 每只基金算「距上次尝试/入队已经过几个交易日」,
     锚 = max(backfill_pending_since, backfill_last_attempt); **恰好 7 个交易日不告警,
     8 个及以上告警**(用户拍板阈值 >7)。两个日期都没有 ⇒ 该只滞后无法判定, 只记可见,
     不单独告警(不拿猜的日期报警)。

【可见但不告警】`backfill_not_attempted`(本轮回补到点软停没跑到的只数)只进输出,
  不构成告警——它是软完成的正常代价, 由优先队列下一轮先补; 拿它报警 = 每晚假告警。

【不削弱的真故障通道(明确保留)】recent 相位 rc=1、整批失败 exit 2、回补锁被占 exit 3
  仍由 systemd failed-unit + gen_schedule_stats 退出码通道负责; 本看门狗**不接管、
  不抑制**这些通道, 只是补上「业务欠账时长」这一维度。

【输入】`--progress` 默认 `<repo>/data/public_fund.fof-nav-progress.json`(采集器轮转进度,
  version=1, 原子写)。文件缺失/格式坏 ⇒ exit 2(无法判定, 不假装健康)。
【输出】stdout 一行判定 + exit 0=OK / 1=告警 / 2=无法判定。
【告警】--notify 才走 ops_legacy_events defer_warning 入 schedule_monitor 聚合队列
  (同 check_s06_freshness.py 先例, 15min 周期不轰炸; 默认 dry 只打印, 单测安全)。
【单测】`--today YYYYMMDD` 显式冻结运行日 + `--progress` 传构造样本 ⇒ 判定纯函数、
  不依赖真实 today()(L51)。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
os.environ.setdefault("NOTIFY_SOURCE", os.path.basename(__file__))
import sys
from pathlib import Path

# absolute() 非 resolve(): 保持 trade-data/scripts 的 symlink 字面路径, 与调用方同树。
SCRIPT_DIR = Path(__file__).absolute().parent
sys.path.insert(0, str(SCRIPT_DIR))
from ops_legacy_events import observe, dispatch  # noqa: E402

DEFAULT_REPO_CANDIDATES = [
    Path(c) for c in (
        os.environ.get("REPO", ""),
        os.environ.get("GIT_REPO", ""),
        os.environ.get("MAIN_REPO", ""),
        "/Users/linhuichen/code/trade-data",
    ) if c
]
DEFAULT_REPO = next((p for p in DEFAULT_REPO_CANDIDATES if (p / "data" / "public_fund.db").exists()),
                    DEFAULT_REPO_CANDIDATES[0])
LAG_LIMIT_TRADING_DAYS = 7   # 用户拍板: >7 个交易日才告警(恰好 7 天不报)


def _parse_yyyymmdd(value: str) -> dt.date:
    return dt.datetime.strptime(value, "%Y%m%d").date()


def _load_trading_dates() -> set[str]:
    """与 app.calendar 同源(交易日历文件); 读不到时降级为「周一~周五」(与它一致)。"""
    try:
        sys.path.insert(0, str(SCRIPT_DIR.parent))
        from app.calendar import _load_trade_dates  # noqa: PLC0415  与采集器同一份日历
        return set(_load_trade_dates() or [])
    except Exception:  # noqa: BLE001  日历不可用 → 降到周末口径, 仍可判, 不假装健康
        return set()


def trading_days_between(since: str, today: str, calendar: set[str] | None = None) -> int:
    """`since` 之后(不含 since)到 `today`(含)之间的交易日个数。

    calendar 非空 = 用真实交易日历(YYYYMMDD 字符串集); 否则降级周末口径(周一~周五)。
    since > today ⇒ 0(未来日期不制造负滞后)。
    """
    start, end = _parse_yyyymmdd(since), _parse_yyyymmdd(today)
    if start >= end:
        return 0
    n = 0
    day = start + dt.timedelta(days=1)
    while day <= end:
        key = day.strftime("%Y%m%d")
        if calendar:
            if key in calendar:
                n += 1
        elif day.weekday() < 5:
            n += 1
        day += dt.timedelta(days=1)
    return n


def judge(progress: dict, today: str, calendar: set[str] | None = None) -> dict:
    """纯判定(不读盘/不发通知), 供单测直接喂构造样本。

    返回 {'action': bool, 'reasons': [...], 'message': str, 'lag_days': int,
          'lag_codes': [...], 'visible': str}。
    """
    last_runs = progress.get("last_runs")
    if not isinstance(last_runs, dict):
        raise ValueError("进度文件缺少 last_runs(相位摘要), 无法判覆盖率")
    recent = last_runs.get("recent")
    if not isinstance(recent, dict):
        raise ValueError("进度文件缺少 last_runs.recent, 无法判本轮覆盖率")

    reasons = []
    selected = int(recent.get("selected") or 0)
    attempted = int(recent.get("attempted") or 0)
    status = str(recent.get("stage_status") or "unknown")
    if attempted < selected:
        reasons.append(
            f"recent 相位覆盖率不足: attempted={attempted}/{selected}"
            f"(status={status}); 未扫完=新鲜度没保完, 属真故障(rc=1 通道应同时告警)")

    pending = progress.get("backfill_pending") or []
    if not isinstance(pending, list):
        raise ValueError("backfill_pending 不是列表, 无法判回补滞后")
    pending_since = progress.get("backfill_pending_since") or {}
    last_attempt = progress.get("backfill_last_attempt") or {}
    if not isinstance(pending_since, dict) or not isinstance(last_attempt, dict):
        raise ValueError("backfill_pending_since/backfill_last_attempt 格式异常")

    lag_codes, max_lag = [], 0
    undated = 0
    for code in pending:
        code = str(code)
        since = max(filter(None, (str(pending_since.get(code) or ""),
                                  str(last_attempt.get(code) or ""))), default="")
        if not since:
            undated += 1
            continue
        lag = trading_days_between(since, today, calendar)
        max_lag = max(max_lag, lag)
        if lag > LAG_LIMIT_TRADING_DAYS:
            lag_codes.append((code, lag))
    lag_codes.sort(key=lambda item: (-item[1], item[0]))
    if lag_codes:
        head = ", ".join(f"{c}@{d}日" for c, d in lag_codes[:8])
        more = "" if len(lag_codes) <= 8 else f" 等 {len(lag_codes)} 只"
        reasons.append(
            f"回补滞后 > {LAG_LIMIT_TRADING_DAYS} 个交易日: {len(lag_codes)} 只"
            f"(最大 {max_lag} 日; {head}{more}); 软完成欠账没被下一轮优先队列补上")

    backfill = last_runs.get("backfill") or {}
    visible = (f"recent={attempted}/{selected}({status}); 优先队列={len(pending)} 只"
               f"(最大滞后 {max_lag} 个交易日, 超过阈值 {len(lag_codes)} 只"
               + (f", {undated} 只无入队日期" if undated else "") + ")")
    if isinstance(backfill, dict) and backfill.get("backfill_not_attempted") is not None:
        visible += f"; 上轮 backfill_not_attempted={backfill.get('backfill_not_attempted')}(仅可见, 不告警)"
    message = visible + ("; " + "; ".join(reasons) if reasons else "")
    return {"action": bool(reasons), "reasons": reasons, "message": message,
            "lag_days": max_lag, "lag_codes": [c for c, _ in lag_codes], "visible": visible}


def main() -> int:
    ap = argparse.ArgumentParser(description="FOF/QDII 回补滞后 + 本轮覆盖率看门狗")
    ap.add_argument("--repo", default=str(DEFAULT_REPO), help="数据仓根(trade-data)")
    ap.add_argument("--progress", default=None,
                    help="显式指定轮转进度 JSON(dry 单测用; 默认 <repo>/data/public_fund.fof-nav-progress.json)")
    ap.add_argument("--today", default=None,
                    help="冻结运行日 YYYYMMDD(单测/隔天复跑用; 默认真实今天)")
    ap.add_argument("--notify", action="store_true",
                    help="告警真发 defer_warning 入聚合队列(默认 dry 只打印, 单测安全)")
    args = ap.parse_args()
    repo = Path(args.repo)
    progress_path = Path(args.progress) if args.progress else repo / "data" / "public_fund.fof-nav-progress.json"
    today = args.today or dt.date.today().strftime("%Y%m%d")
    _parse_yyyymmdd(today)  # 格式错直接抛 SystemExit(2)
    calendar = _load_trading_dates()

    key = "fof_backfill|" + progress_path.absolute().as_posix()

    def probe():
        payload = json.loads(progress_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("进度文件不是 JSON 对象")
        return judge(payload, today, calendar)

    refs = None
    try:
        facts, refs = observe(repo, key, probe) if args.notify else (probe(), None)
    except Exception as exc:  # noqa: BLE001  文件缺失/格式坏 = 无法判定, 不装健康
        print(f"FOF_BACKFILL_ERROR 进度无法判定: {type(exc).__name__}: {exc}", file=sys.stderr)
        if args.notify:
            try:
                dispatch(repo, SCRIPT_DIR / "notify.py", "[告警] FOF 回补看门狗无法判定",
                         f"读不到或读不懂轮转进度文件({progress_path})，不能证明回补健康：{exc}",
                         None, source="check_fof_backfill.py")
            except Exception as send_exc:  # noqa: BLE001
                print(f"[fof-backfill] 未确认告警: {send_exc}", file=sys.stderr)
        return 2
    if not facts["action"]:
        print("FOF_BACKFILL_OK " + facts["visible"])
        return 0
    print("FOF_BACKFILL_FAIL " + facts["message"])
    if args.notify:
        try:
            status = dispatch(repo, SCRIPT_DIR / "notify.py",
                              f"FOF 回补滞后/覆盖率异常({facts['lag_days']} 个交易日)",
                              facts["message"], refs, warning=True,
                              source="check_fof_backfill.py")
            if status not in ("deferred", "digested", "sent", "suppressed", "superseded"):
                print(f"[fof-backfill] 告警未完成({status})，下轮重试", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"[fof-backfill] 告警未完成，下轮重试: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
