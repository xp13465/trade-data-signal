#!/usr/bin/env python3
"""nextday_plan_generator.py - 次日买入计划生成器(PRD 阶段一 §3/§6, 干跑模式 AUTO_EXEC_ON=false)

目的:
    每天 21:00 盘后(launchd com.trade.nextday-plan)生成次日(T+1)买入计划:
      ①复用 kelly_posrating 同构逻辑(K=1 每日 top1)选出当日信号, 输出 data/nextday_plan.json
      ②把计划写进 static-site/data/auto_trade_steps.json(行为级状态机, seq1 挂单行为 pending,
        §6.2 全字段)
      ③同步两树 static-site/data/ + R2(upload_r2 upload-data-files, §22 三步同步)
      ④通知(邮件+飞书, 复用 notify.send 链路)
    干跑模式: 本阶段只生成计划+通知书, 不连 easytrader 不真实下单(AUTO_EXEC_ON=false, PRD §8/§9)。

方法口径(与 signal_kelly_backtest 回测同构, 防前视一致):
    - 交易候选 = signal_kelly_trades.json quadrants 三评级×A 模式并集(posRaw 同 kelly_posrating)
    - 过滤 = kelly_posrating.make_passes_fade(fIdx, trade_dims, loss_spec_map, feat_at, s06)
             (S06 per-date 动态基座 + 降亏键过滤, 复用现成模块)
    - base_pool = _collect_base_pool(三评级×全部 sell_modes, baseKey 去重)
    - K=1 保留 = _position_cap_kept_keys(base_pool, fIdx, K=1): 按 signal_date 分组,
      组内排序 track_score DESC→rating(high>mid>low)→signal(buy_backup>buy>buy_aux>buy_special)→buy_date ASC,
      保留前 1(即每日 top1)
    - 当日计划 = signal_date == T(今天/指定 --date)且被 K=1 保留的交易
    - buy_date = T 的下一个交易日(从 etf_daily 日期集取下一条已知日期, §11.4 长假处理)
    - prev_close = 该 etf 昨日收盘(etf_daily 中 <= T 最近一天 close, 即挂单价上限)
    - amount = 每日资金池 1 万等分(K=1 即 1 万)
    - 双校验: ① prev_close>0 非停牌(该 etf 前一日有成交) ② prev_close vs 信号日收盘 ±20% 内(伪跳空剔除同款,
      防除权/份额折算错位; 信号日收盘 = trades 该笔 real_buy_price 信号日近似或 etf_daily 该 etf T 日 close)

输入依赖:
    - <REPO>/static-site/data/signal_kelly_trades.json   (回测交易记录, 26 字段/笔, export 17:50 生成)
    - <REPO>/static-site/data/signal_kelly_backtest.json (config.sell_modes 定义 A-J 卖出模式)
    - <REPO>/static-site/data/kelly_mode_s06_state.json  (S06 动态基座快照, 20:35 每日重生)
    - <REPO>/static-site/data/kelly_loss_features.json   (降亏特征 + meta.rules 规格)
    - <REPO>/data/etf_national_team.db etf_daily         (取标的昨日收盘 -> 挂单价上限 + 交易日集合)
输出:
    - data/nextday_plan.json(本地权威: {date, plan:[{etf_code,etf_name,prev_close,amount,signal,track_score,signal_date,buy_date}]}; 空计划 {date, empty:true})
    - static-site/data/nextday_plan.json(用户页面可见, 同内容)
    - static-site/data/auto_trade_steps.json({schema_version:"v1", steps:[...]}, 追加模式幂等: 同 date 已存在则跳过)
关键参数(常量, 与 kelly_posrating/common.js 逐位对齐, 改参数必须同步 §22):
    - K=1, BUY_AMOUNT=10000, PSEUDO_GAP=0.20(伪跳空剔除阈值同 signal_kelly_backtest.PSEUDO_GAP_EXCLUDE)
复现命令:
    REPO=/Users/linhuichen/code/trade-data python3 scripts/nextday_plan_generator.py --date 20260908 --dry-run
    # --dry-run 只计算打印不落盘不发通知(自测); 无 --date 取今天; 无 --dry-run 会落盘两树+R2+通知
    REPO=/Users/linhuichen/code/trade-data python3 scripts/nextday_plan_generator.py   # launchd 同款(真跑)
"""
import argparse
import json
import os
import subprocess
import sys
import sqlite3
from datetime import datetime, date
from pathlib import Path

# 运行根: 显式 REPO 优先(trade-data 运行副本), 缺省回退脚本所在仓
ROOT = Path(__file__).resolve().parent.parent
REPO = Path(os.environ.get("REPO", str(ROOT)))
GIT_REPO = Path(os.environ.get("GIT_REPO", str(ROOT)))
PY = os.environ.get("PY", str(REPO / ".venv" / "bin" / "python"))
SCRIPT_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(SCRIPT_DIR))
import kelly_posrating as kp  # noqa: E402  (复用 make_passes_fade/_collect_base_pool/_position_cap_kept_keys)

K = 1                       # K 档(每日 top1)
BUY_AMOUNT = 10000          # 每日资金池 1 万等分
PSEUDO_GAP = 0.20           # 伪跳空剔除阈值(与 signal_kelly_backtest.PSEUDO_GAP_EXCLUDE 同款)
LOG_TAG = "[nextday_plan]"


def log(msg):
    print(f"{LOG_TAG} {msg}", flush=True)


def _severe_alert(subject, body):
    """严重失败告警(notify.py --severe, 带 dedup 防轰炸)。

    F2(2026-09-10): 生成器内 R2 上传失败/写盘失败等「会让线上停滞」的失败不再静默只 log,
    调 notify.py --severe 告警 + 最终退出码非 0(与 nextday_plan.sh 包装的 --severe 双保险,
    dedup key 不同不互吞; 包装只在 RC!=0 时兜底, 生成器内先行带明细 stderr)。
    """
    log_path = REPO / "data" / "logs" / "nextday_plan_launchd.log"
    cmd = [PY, str(SCRIPT_DIR / "notify.py"), subject, body,
           "--severe", "--from-prefix", "[告警]",
           "--alert-issue", subject, "--alert-log", str(log_path),
           "--dedup-key", "nextday_plan_gen_fail", "--dedup-window", "3600"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        log(f"severe 告警 rc={r.returncode}")
    except Exception as e:
        log(f"⚠ severe 告警调用异常(无法送达): {e}")


def _load_json(name: str, base: Path):
    p = base / name
    if not p.exists():
        raise FileNotFoundError(f"输入产物缺失: {p}")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _etf_daily_dates(db_path: Path) -> list[str]:
    """etf_daily 全部交易日(升序)。etf_daily 只含历史有行情日期(不含未来)。"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        cur.execute("SELECT DISTINCT date FROM etf_daily ORDER BY date")
        return [r[0] for r in cur.fetchall()]
    finally:
        con.close()


def _trade_calendar_dates(db_path: Path) -> list[str]:
    """权威交易日历(含未来, up to 当年): data/trade_dates.txt(akshare tool_trade_date_hist_sina 缓存)。

    用于确定 buy_date 下一交易日: T 是今天时 etf_daily 里没有 > T 的日期(今天之后的数据还没产生),
    必须用交易日历推算下一交易日(§11.4 长假/调休: 交易日历已含, 取 > T 的最小工作日即可)。
    """
    cands = []
    for base in (db_path.parent, ROOT / "data", REPO / "data"):
        p = base / "trade_dates.txt"
        if p.exists():
            try:
                cands = sorted({line.strip() for line in p.read_text().splitlines() if line.strip()})
                if cands:
                    return cands
            except Exception:
                continue
    return cands


def _prev_close(db_path: Path, etf_code: str, on_or_before: str):
    """etf_daily 该 etf <= on_or_before 最近一天 close(昨收=挂单价上限)。"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT date, close FROM etf_daily WHERE etf_code=? AND date<=? ORDER BY date DESC LIMIT 1",
            (etf_code, on_or_before),
        )
        row = cur.fetchone()
        if row is None:
            return None, None
        return row[0], (float(row[1]) if row[1] is not None else None)
    finally:
        con.close()


def _next_trading_day(dates: list[str], t: str) -> str:
    """取 > t 的最小日期(下一交易日)。t 在集合内则取下一个; t 为最后一天则返回 None。"""
    for d in dates:
        if d > t:
            return d
    return None


def _today():
    return date.today().strftime("%Y%m%d")


def _shares_planned(amount: float, price: float) -> int:
    """100 份整数倍向下取整(§6.6: 10000÷昨收 向下取整到 100 份整数倍)。"""
    if price <= 0:
        return 0
    return int(amount / price / 100) * 100


def _build_passes(trades_doc, backtest_doc, s06_doc, loss_feat_doc):
    """与 kelly_posrating.compute_posrating 同构构建 fIdx/passes/kept(复用现成模块)。"""
    fields = trades_doc.get("fields") or []
    fIdx = {f: i for i, f in enumerate(fields)}
    for need in ("signal_date", "index_id", "signal", "buy_date", "sell_date", "etf_code",
                 "buy_price", "sell_price", "current_price", "track_tier", "track_score",
                 "market_tier", "market_tier_all", "market_tier_cyb", "market_state", "rating"):
        if need not in fIdx:
            raise ValueError(f"trades.fields 缺必需字段: {need}")
    quads = trades_doc.get("quadrants") or {}
    sell_modes = ((backtest_doc.get("config") or {}).get("sell_modes")) or {}
    if not sell_modes:
        raise ValueError("backtest.config.sell_modes 缺失")
    trade_dims = kp._trade_dims(quads, fIdx)
    spec_map = {}
    feat_at = lambda name, date: None  # noqa: E731
    if loss_feat_doc:
        for r in (loss_feat_doc.get("meta") or {}).get("rules") or []:
            if isinstance(r, dict) and r.get("key"):
                spec_map[r["key"]] = r
        feats = loss_feat_doc.get("features") or {}

        def _feat_at(name, date):
            series = feats.get(name)
            if not series:
                return None
            return series.get(str(date))

        feat_at = _feat_at
    s06 = kp.S06Resolver(s06_doc)
    passes_fade = kp.make_passes_fade(fIdx, trade_dims, spec_map, feat_at, s06)
    base_pool = kp._collect_base_pool(quads, sell_modes, fIdx, passes_fade)
    kept = kp._position_cap_kept_keys(base_pool, fIdx, K)
    log(f"basePool={len(base_pool)} kept_K{K}={len(kept)}")
    return fIdx, passes_fade, base_pool, kept


def _trades_signal_close(trades_doc, fIdx, t, etf_code, signal_date):
    """信号日收盘近似: 优先该笔 trades 的 current_price(信号日收盘), 缺失回退 None。"""
    idx_cur = fIdx.get("current_price")
    if idx_cur is not None:
        v = t[idx_cur]
        if v is not None and float(v) > 0:
            return float(v)
    return None


def main():
    ap = argparse.ArgumentParser(description="次日买入计划生成器(PRD 阶段一 §3/§6, 干跑)")
    ap.add_argument("--date", default=None, help="信号日 T(YYYYMMDD, 缺省=今天)")
    ap.add_argument("--dry-run", action="store_true", help="只计算打印, 不落盘两树/不 R2/不通知")
    ap.add_argument("--no-r2", action="store_true", help="落盘但不传 R2(自测用)")
    ap.add_argument("--no-notify", action="store_true", help="落盘但不通知(自测用)")
    args = ap.parse_args()

    T = args.date or _today()
    data_dir = REPO / "static-site" / "data"
    db_path = REPO / "data" / "etf_national_team.db"
    if not db_path.exists():
        db_path = ROOT / "data" / "etf_national_team.db"
    log(f"REPO={REPO} T={T} dry_run={args.dry_run}")

    # 输入 5 产物
    trades_doc = _load_json("signal_kelly_trades.json", data_dir)
    backtest_doc = _load_json("signal_kelly_backtest.json", data_dir)
    s06_doc = _load_json("kelly_mode_s06_state.json", data_dir)
    loss_feat_doc = _load_json("kelly_loss_features.json", data_dir)

    fIdx, passes_fade, base_pool, kept = _build_passes(trades_doc, backtest_doc, s06_doc, loss_feat_doc)
    etf_dates = _etf_daily_dates(db_path)
    cal_dates = _trade_calendar_dates(db_path)
    # buy_date = 权威交易日历(含未来)中 > T 的最小日期; 日历不可用回退 etf_daily 历史日期集
    trade_dates = cal_dates or etf_dates
    if not trade_dates:
        raise RuntimeError("交易日历与 etf_daily 均为空, 无法确定下一交易日")

    idx = {
        "signal_date": fIdx["signal_date"], "index_id": fIdx["index_id"], "signal": fIdx["signal"],
        "buy_date": fIdx["buy_date"], "etf_code": fIdx["etf_code"], "etf_name": fIdx["etf_name"],
        "track_score": fIdx["track_score"],
    }

    # 当日(T)通过过滤且 K=1 保留的交易
    day_rows = []
    for t in base_pool:
        if str(t[idx["signal_date"]] or "") != T:
            continue
        if kp._base_key(t, fIdx) not in kept:
            continue
        day_rows.append(t)
    log(f"T={T} 当日通过过滤且 K=1 保留候选={len(day_rows)}")

    buy_date = _next_trading_day(trade_dates, T)
    if buy_date is None:
        log(f"⚠ 交易日历无 > {T} 的下一交易日(可能 T 已是日历最后一天), 走空计划")
        day_rows = []

    plan = []
    for t in day_rows:
        etf_code = str(t[idx["etf_code"]] or "")
        etf_name = str(t[idx["etf_name"]] or "")
        signal = str(t[idx["signal"]] or "")
        track_score = t[idx["track_score"]] if idx["track_score"] is not None else None
        sig_close = _trades_signal_close(trades_doc, fIdx, t, etf_code, T)
        # 双校验 ①: prev_close>0 非停牌(该 etf 前一日有成交)
        last_date, prev_close = _prev_close(db_path, etf_code, T)
        if prev_close is None or prev_close <= 0:
            log(f"  ✗ {etf_code} {etf_name} prev_close={prev_close}(非停牌校验失败, 前一日无成交)")
            continue
        # 双校验 ②: prev_close vs 信号日收盘 ±20%(伪跳空剔除同款)
        if sig_close is not None and sig_close > 0:
            gap = prev_close / sig_close - 1.0
            if abs(gap) > PSEUDO_GAP:
                log(f"  ✗ {etf_code} {etf_name} 伪跳空剔除 prev_close={prev_close} sig_close={sig_close} gap={gap:.2%}")
                continue
        plan.append({
            "etf_code": etf_code,
            "etf_name": etf_name,
            "prev_close": round(prev_close, 4),
            "amount": BUY_AMOUNT,
            "signal": signal,
            "track_score": track_score,
            "signal_date": T,
            "buy_date": buy_date,
        })

    plan_doc = {"date": T, "plan": plan} if plan else {"date": T, "empty": True}
    log(f"计划条目={len(plan)} buy_date={buy_date}")
    for p in plan:
        log(f"  {p['etf_code']} {p['etf_name']} prev_close={p['prev_close']} amount={p['amount']} "
            f"signal={p['signal']} track_score={p['track_score']} buy_date={p['buy_date']}")

    if args.dry_run:
        log("DRY-RUN: 不落盘不 R2 不通知")
        print(json.dumps(plan_doc, ensure_ascii=False, indent=2))
        return 0

    # ---- 落盘: 本地 data/nextday_plan.json + 两树 static-site/data/ ----
    write_targets = [ROOT / "data", data_dir, GIT_REPO / "static-site" / "data"]
    written = []
    for d in write_targets:
        d.mkdir(parents=True, exist_ok=True)
        with (d / "nextday_plan.json").open("w", encoding="utf-8") as f:
            json.dump(plan_doc, f, ensure_ascii=False, indent=1)
        written.append(str(d / "nextday_plan.json"))

    # ---- auto_trade_steps.json 追加(幂等: 同 date 已存在则跳过) ----
    steps_doc = {"schema_version": "v1", "steps": []}
    steps_paths = [data_dir / "auto_trade_steps.json", GIT_REPO / "static-site" / "data" / "auto_trade_steps.json"]
    for sp in steps_paths:
        if sp.exists():
            try:
                with sp.open("r", encoding="utf-8") as f:
                    existing = json.load(f)
                if isinstance(existing, dict) and isinstance(existing.get("steps"), list):
                    steps_doc["steps"] = existing["steps"]
                    break
            except Exception:
                pass
    # 幂等: steps 的 date = 执行日(buy_date, §6.2 交易日), 已存在该执行日的 seq1 挂单行则跳过
    if plan and any(str(s.get("date")) == buy_date and str(s.get("seq")) == "1"
                    for s in steps_doc["steps"]):
        log(f"auto_trade_steps 已含执行日 date={buy_date}, 幂等跳过追加")
    elif plan:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for p in plan:
            shares = _shares_planned(p["amount"], p["prev_close"])
            step = {
                "date": p["buy_date"],
                "seq": 1,
                "time_slot": "09:15",
                "action": "buy",
                "etf_code": p["etf_code"],
                "etf_name": p["etf_name"],
                "order_price": p["prev_close"],
                "expected_range": f"低开按开盘价成交; 高开等回落至 {p['prev_close']} 或尾盘兜底",
                "decision": f"9:25 集合竞价: O ≤ {p['prev_close']}? 是→按O成交; 否→高开等回落触及 {p['prev_close']}; 14:55 仍未触及→撤单市价兜底",
                "amount": p["amount"],
                "shares_planned": shares,
                "status": "pending",
                "status_text": "待执行",
                "signal": p["signal"],
                "track_score": p["track_score"],
                "trigger_note": f"按昨收价 {p['prev_close']} 挂限价买单, 9:25 集合竞价撮合(干跑阶段只生成计划, 不真实下单)",
                "updated_at": now,
            }
            steps_doc["steps"].append(step)
            log(f"auto_trade_steps 追加 seq1 {step['etf_code']} {step['etf_name']} buy_date={step['date']} shares={shares}")

        for sp in steps_paths:
            with sp.open("w", encoding="utf-8") as f:
                json.dump(steps_doc, f, ensure_ascii=False, indent=1)
            written.append(str(sp))

    # ---- R2 上传(§22 三步同步; 盘后产物走 upload-data-files 段) ----
    # F2(2026-09-10): R2 失败不再静默 —— notify --severe + 最终退出码非 0。
    # 范围边界: 只对「会让线上停滞」的失败(R2 上传失败)告警; notify 通道自身波动
    # 不升级(计划已落盘本地, git/次日 deploy 兜底, 流程不要求在盘中强一致)。
    r2_rc = 0
    if not args.no_r2 and not args.dry_run:
        r2_files = ["nextday_plan.json"]
        if plan:
            r2_files.append("auto_trade_steps.json")
        cmd = [PY, str(SCRIPT_DIR / "upload_r2.py"), "upload-data-files"] + r2_files
        log("R2: " + " ".join(cmd))
        try:
            env = dict(os.environ)
            env.setdefault("REPO", str(REPO))
            r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
            log(f"R2 退出码={r.returncode}\n{r.stdout}")
            if r.returncode != 0:
                _err = r.stderr[-2000:]
                log(f"⚠ R2 上传失败(将告警): {_err}")
                _severe_alert(
                    f"[告警] 次日买入计划 R2 上传失败 rc={r.returncode} {T}",
                    f"nextday_plan_generator.py: R2 upload-data-files 退出码 {r.returncode}, "
                    f"次日买入计划本地已落盘但 R2 未同步(线上 sss/s 备站可能滞后)。"
                    f"<br>R2 stderr: <pre>{_err}</pre>"
                    f"<br>日志: {REPO}/data/logs/nextday_plan_launchd.log",
                )
                r2_rc = 1
        except subprocess.TimeoutExpired:
            log("⚠ R2 上传超时(300s, 将告警)")
            _severe_alert(
                f"[告警] 次日买入计划 R2 上传超时 {T}",
                "nextday_plan_generator.py: R2 upload-data-files 300s 超时, "
                "次日买入计划本地已落盘但 R2 未同步确认(线上备站可能滞后)。<br>日志: "
                f"{REPO}/data/logs/nextday_plan_launchd.log",
            )
            r2_rc = 1
        except Exception as e:
            log(f"⚠ R2 上传异常: {e}")
            _severe_alert(
                f"[告警] 次日买入计划 R2 上传异常 {T}",
                f"nextday_plan_generator.py: R2 上传异常 {type(e).__name__}: {e}。<br>日志: "
                f"{REPO}/data/logs/nextday_plan_launchd.log",
            )
            r2_rc = 1

    # ---- 通知(邮件+飞书, 复用 notify.send 链路; 干跑阶段通知内容是「明日计划」) ----
    notify_rc = 0
    if not args.no_notify and not args.dry_run:
        if plan:
            lines = []
            for p in plan:
                lines.append(
                    f"明日计划: {p['etf_code']} {p['etf_name']} | 昨收 {p['prev_close']} | "
                    f"买入 {p['amount']//10000} 万元 | 信号: {p['signal']} | 跟踪分 {p['track_score']}"
                )
            subject = f"明日买入计划 {T}"
            body = "<br>".join(lines)
        else:
            subject = f"明日买入计划 {T}(空)"
            body = "明日无买入计划(无信号或 T 日非交易日)。"
        cmd = [PY, str(SCRIPT_DIR / "notify.py"), subject, body,
               "--dedup-key", f"nextday_plan_{T}", "--dedup-window", "86400"]
        log("notify: " + subject)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            log(f"notify 退出码={r.returncode}")
            if r.returncode != 0:
                # F2: 关键 notify(计划已生成)失败 = 用户收不到次日计划, 属会让线上停滞的一环
                # (计划产物本身已落盘, 但通知是 PRD 阶段一交付物的显式出口, 失败必须非 0 暴露,
                # 由 nextday_plan.sh 包装层兜底再发 severe; 此处只在包装已存在基础上叠加非 0,
                # 不重复发 severe —— 包装 --dedup-key nextday_plan_fail 已覆盖该失败面)
                log(f"⚠ notify 失败 rc={r.returncode}(计划已生成但通知未送达, 退出码非 0 交包装层告警)")
                notify_rc = 1
        except Exception as e:
            log(f"⚠ notify 异常: {e}")
            notify_rc = 1

    log("落盘完成: " + ", ".join(written))
    # F2: 任一「会让线上停滞」的失败(R2 上传失败/关键 notify 失败)都让退出码非 0,
    # 交 nextday_plan.sh 包装层走 notify --severe + schedule_monitor 漏跑/退出码监控兜底。
    return 1 if (r2_rc or notify_rc) else 0


if __name__ == "__main__":
    sys.exit(main())
