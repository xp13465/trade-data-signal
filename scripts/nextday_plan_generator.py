#!/usr/bin/env python3
"""nextday_plan_generator.py - 次日买入计划生成器(PRD 阶段一 §3/§6, 干跑模式 AUTO_EXEC_ON=false)

目的:
    每天盘后(launchd com.trade.nextday-plan)生成次日(T+1)买入计划:
      ①复用首页 AI建议同一条选取链(K=1 每日 top1)选出当日信号, 输出 data/nextday_plan.json
      ②把计划写进 static-site/data/auto_trade_steps.json(行为级状态机, seq1 挂单行为 pending,
        §6.2 全字段)
      ③同步两树 static-site/data/ + R2(upload_r2 upload-data-files, §22 三步同步)
      ④通知(邮件+飞书, 复用 notify.send 链路)
    干跑模式: 本阶段只生成计划+通知书, 不连 easytrader 不真实下单(AUTO_EXEC_ON=false, PRD §8/§9)。

方法口径(2026-09-10 方案A根治, 设计缺口: 原实现从 signal_kelly_trades.json 选 signal_date==T,
但主回测 KELLY_BUY_NEXTDAY=1 口径下买价=次日开盘价, 今日信号永远不在 trades 里 → 定时跑必出
空计划误导。方案A(用户拍板): 生成器改走首页同一条路 = signal_daily 当日信号 + 冻结表 top1 ETF):
    - 信号源 = sentiment.db signal_daily 当日(T)全部信号, 排除 s.* 情绪分(与首页查询
      app/queries.py L1123-1128 一致), 再只取买信号 BUY_SIGNALS={buy,buy_aux,buy_special,
      buy_backup}(buy_special_filtered 归一为 buy_special, 与 queries._AI_MACRO_BUY_SIGNALS 一致)
    - top1 判定 = 冻结表 data/signal_kelly_etf_freeze.json(key=date|index_id|signal)命中
      → 冻结 code 为权威 top1(_bk_top); 未命中 → 前端 _topEtfByScore 同构(纯 max(track_score),
      平手回退 similarity)。track_score 命中冻结时取冻结表冻结分(2026-09-18 ③ 随信号日 T 固化,
      不随 board_etf_map 双树/重生值漂移, 3 版本漂移根因②), 未命中取 board_etf_map 注入值
      (与首页 overview 逐位一致)。
    - 降亏过滤 = 首页同款(queries._ai_macro_hit_filters, ctx 与 overview 完全同构) ∩ S06
      基座成员集(s06.filters_for_date(T) True 键; 快照缺行 fail-open 放行)。a9 基座补
      bullAuxBackupStop 前端分支(buy_aux/buy_backup × hs300 四档=牛市·主升)。
    - K=1 保留 = kelly 排序准则(track_score DESC → rating high>mid>low → signal
      buy_backup>buy>buy_aux>buy_special → buy_date ASC), 与首页 AI建议 top1 一致。
    - buy_date = T 的下一个交易日(权威交易日历 data/trade_dates.txt, §11.4 长假处理)
    - prev_close = 该 etf T 日收盘(etf_daily, 即挂单价上限; 与首页 etf_close 同源同口径)
    - amount = 每日资金池 1 万等分(K=1 即 1 万)
    - 双校验: ① prev_close>0 非停牌(信号日 T 有成交, 挂单价上限有效) ② 伪跳空剔除真口径
      (次日 open / 信号日收盘 - 1, |gap|>20% 剔除; 与回测 PSEUDO_GAP_EXCLUDE 同式; 信号日收盘 =
      etf_daily 该 etf T 日 close, 次日 open = etf_daily 该 etf T+1 日 open)
    - T+1 开盘价未入库(当日计划, 次日未开盘)时跳过该剔除, 留 9:26 nextday_gap_check 二次兜底

输入依赖:
    - <REPO>/data/sentiment.db signal_daily  (当日信号, 首页同源)
    - <REPO>/data/signal_kelly_etf_freeze.json(冻结表, key=date|index_id|signal → top1 ETF)
    - <REPO>/data/signal_stats.json           (评级 10d score, 首页同源)
    - <REPO>/config/indicators.yaml          (指数 market 归类, 首页同源)
    - <REPO>/static-site/data/kelly_mode_s06_state.json(S06 动态基座快照, 20:35 每日重生)
    - <REPO>/static-site/data/kelly_loss_features.json(降亏特征, ai_macro 内部读取)
    - <REPO>/data/board_etf_map.json         (每信号 ETF 候选映射, 首页同源)
    - <REPO>/data/etf_national_team.db etf_daily(取标的 T 日收盘 -> 挂单价上限 + 交易日集合)
    - <REPO>/data/trade_dates.txt            (权威交易日历, buy_date 下一交易日)
输出:
    - data/nextday_plan.json(本地权威: {date, plan:[{etf_code,etf_name,prev_close,amount,signal,track_score,signal_date,buy_date}]}; 空计划 {date, empty:true})
    - static-site/data/nextday_plan.json(用户页面可见, 同内容)
    - static-site/data/auto_trade_steps.json({schema_version:"v1", steps:[...]}, 幂等: 同 date 已存在且 etf_code 一致则跳过, 漂移则删旧行重写)
关键参数(常量, 与 kelly_posrating/前端逐位对齐, 改参数必须同步 §22):
    - K=1, BUY_AMOUNT=10000, PSEUDO_GAP=signal_kelly_backtest.PSEUDO_GAP_EXCLUDE(伪跳空剔除阈值同源)
复现命令:
    REPO=/Users/linhuichen/code/trade-data GIT_REPO=/Users/linhuichen/code/trade python3 scripts/nextday_plan_generator.py --date 20260910 --dry-run
    # --dry-run 只计算打印不落盘不发通知(自测); 无 --date 取今天; 无 --dry-run 会落盘两树+R2+通知
    REPO=/Users/linhuichen/code/trade-data GIT_REPO=/Users/linhuichen/code/trade python3 scripts/nextday_plan_generator.py   # launchd 同款(真跑)
    # 数据未就绪(缺当日收盘价)退出非 0(退出码 2, fail-closed 阻塞 + 告警, 不再 FORCE 用前日价)
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

sys.path.insert(0, str(REPO))  # 优先 REPO(实时数据侧; app 经 symlink 读 trade, __file__ 不 resolve → data 路径落 REPO)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

import kelly_posrating as kp  # noqa: E402  (复用 S06Resolver + _tds_fade_spec_hit(bullAuxBackupStop))
from app import queries as appq  # noqa: E402  (首页 AI建议同款: etf_for/_etf_freeze/_align_home_top1_to_backtest/_ai_macro_*)
from app.collector.fetchers import load_config  # noqa: E402  (indicators.yaml indicator.market 归类)
from signal_kelly_backtest import PSEUDO_GAP_EXCLUDE  # noqa: E402  (伪跳空阈值同源, 不各写一个数)

K = 1                       # K 档(每日 top1, 与首页 AI仓位建议默认 K=1 一致)
BUY_AMOUNT = 10000          # 每日资金池 1 万等分
BACKFILL_WINDOW_DAYS = 10   # 历史持仓回填窗口(最近 N 个交易日, #106; 窗口起点随每日前移, 已过期组滑出不删只不再补)
PSEUDO_GAP = PSEUDO_GAP_EXCLUDE  # 伪跳空剔除阈值(与 signal_kelly_backtest.PSEUDO_GAP_EXCLUDE 同源同常量, 不各写一个数)
LOG_TAG = "[nextday_plan]"
BUY_SIGNALS = {"buy", "buy_aux", "buy_special", "buy_backup"}  # 与 queries._AI_MACRO_BUY_SIGNALS 同源
_RATING_RANK = {"high": 0, "mid": 1, "low": 2, "": 3}
_SIG_RANK = {"buy_backup": 0, "buy": 1, "buy_aux": 2, "buy_special": 3, "": 9}


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


def _etf_latest_date(db_path: Path, etf_code: str) -> str | None:
    """etf_daily 该 etf 的最新交易日(无则 None)。用于计划内逐只就绪 gate(#38)。"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        cur.execute("SELECT MAX(date) FROM etf_daily WHERE etf_code=?", (etf_code,))
        row = cur.fetchone()
        return row[0] if row and row[0] else None
    finally:
        con.close()


def _plan_stale_codes(db_path: Path, plan: list[dict], T: str) -> list[str]:
    """计划内 ETF 最新日 < T 的 etf_code 列表(就绪 gate: 计划内每只 ETF 最新日须 == T)。

    #38 根治: 原 gate 用全局 max date(任一 ETF 到 T 就放行), 计划内停在旧日的 ETF(如 159880
    停在 09-14)被纳入 → prev_close 非 T 日收盘失真。改为逐只校验计划内 etf_code 最新日。
    """
    codes = sorted({str(p.get("etf_code") or "") for p in plan if p.get("etf_code")})
    return [c for c in codes if (_etf_latest_date(db_path, c) or "") < T]


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
    """etf_daily 该 etf <= on_or_before 最近一天 close(T 日收盘=挂单价上限)。"""
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


def _next_open(db_path: Path, etf_code: str, after_date: str):
    """etf_daily 该 etf > after_date 最近一天 open(T+1 开盘价, 伪跳空校验分子)。

    返回 open(float) 或 None。与回测 signal_kelly_backtest._batch_load_etf_prices 同款过滤
    (etf_name<>etf_code 排除盘中占位假数据行 + open 非空)。T+1 开盘价只在 T+1 日 20:07
    etf_national_team 采集后入库; 当日计划(次日未开盘)查不到 → 返回 None(留 9:26
    nextday_gap_check 二次剔除, 语义=「还没开盘」不是「无数据」)。
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT open FROM etf_daily WHERE etf_code=? AND date>? "
            "AND etf_name<>etf_code AND open IS NOT NULL ORDER BY date ASC LIMIT 1",
            (etf_code, after_date),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return float(row[0])
    finally:
        con.close()


def _next_trading_day(dates: list[str], t: str) -> str:
    """取 > t 的最小日期(下一交易日)。t 在集合内则取下一个; t 为最后一天则返回 None。"""
    for d in dates:
        if d > t:
            return d
    return None


def _nth_trading_day_after(dates: list[str], t: str, n: int) -> str:
    """取 > t 的第 n 个交易日(PRD §6.2 seq5 D+10 卖出日, 与回测 A 模式 hold_days=10 同口径:
    卖出日 = 信号日后第 10 个交易日。买入日 = 信号日次日(D+1=买入日), D+10 卖出 = 含买入日共持有 10 个交易日)。
    即 9/4 信号 → 9/7 买入 → 9/18 卖出(非 9/21, 后者是误按"买入日后第10"算的)。n=0 返回 _next_trading_day 同款。"""
    cnt = 0
    for d in dates:
        if d > t:
            cnt += 1
            if cnt >= n:
                return d
    return None


def _today():
    return date.today().strftime("%Y%m%d")


def _shares_planned(amount: float, price: float) -> int:
    """100 份整数倍向下取整(§6.6: 10000÷昨收 向下取整到 100 份整数倍)。"""
    if price <= 0:
        return 0
    return int(amount / price / 100) * 100


# 标准行为序号集(PRD §6.2 时间线): 1=09:15挂单 2=09:25竞价判定 3=14:55尾盘兜底 5=D+10卖出
STANDARD_SEQS = (1, 2, 3, 5)


def _build_steps_for_plan(p, now: str, sell_date: str) -> list[dict]:
    """某计划条目的完整行为链(PRD §6.2 时间线, 用户「兜底买入步骤什么时候显示」诉求的产物)。

    seq1 09:15 挂单(昨收限价单) / seq2 09:25 竞价判定(低开按开盘价成交, 高开等回落) /
    seq3 14:55 尾盘兜底(未成交撤单改市价) / seq5 D+10 卖出(A 模式持有 10 个交易日到期, 独立行)。
    全部 status=pending 待执行, 由前端按时钟推进展示(干跑阶段不写回执行状态)。
    """
    code = str(p.get("etf_code") or "")
    name = str(p.get("etf_name") or "")
    price = p.get("prev_close")
    amount = p.get("amount")
    shares = _shares_planned(amount, price) if (amount and price) else None
    buy_date = str(p.get("buy_date") or "")
    base = {
        "date": buy_date,
        "etf_code": code,
        "etf_name": name,
        "amount": amount,
        "shares_planned": shares,
        "status": "pending",
        "status_text": "待执行",
        "signal": p.get("signal") or "",
        "track_score": p.get("track_score"),
        "updated_at": now,
    }
    share_str = str(shares) if shares is not None else "全部"
    seq1 = dict(base, **{
        "seq": 1, "time_slot": "09:15", "action": "buy", "order_price": price,
        "expected_range": f"低开按开盘价成交; 高开等回落至 {price} 或尾盘兜底",
        "decision": f"9:25 集合竞价: O ≤ {price}? 是→按O成交; 否→高开等回落触及 {price}; 14:55 仍未触及→撤单市价兜底",
        "trigger_note": f"按昨收价 {price} 挂限价买单, 9:25 集合竞价撮合(干跑阶段只生成计划, 不真实下单)",
    })
    seq2 = dict(base, **{
        "seq": 2, "time_slot": "09:25", "action": "buy", "order_price": price,
        "expected_range": f"开盘 O ≤ 昨收 {price} → 按 O 成交; 高开 → 等回落触及 {price} 或尾盘兜底",
        "decision": f"decision A: 开盘 O ≤ 昨收 {price}? 是→按 O 成交(更低更优); 否→高开等回落触及 {price}, 14:55 未触及→撤单市价兜底",
        "trigger_note": "9:25 集合竞价撮合判定: 开盘价 ≤ 昨收即按开盘价成交; 高开则限价单挂盘面等回落触价自动成交",
    })
    seq3 = dict(base, **{
        "seq": 3, "time_slot": "14:55", "action": "buy", "order_price": price,
        "expected_range": f"14:55 仍未触及 {price} → 撤单改市价兜底买入(保证今日资金投出)",
        "decision": f"decision C: 已成交? 是→无事; 否→14:55 撤未成交单改市价买入(挂昨收+尾盘兜底为默认档, PRD §4.4)",
        "trigger_note": "尾盘兜底: 日内未回落触及挂单价, 撤未成交限价单, 改按当时市价买入保证今日投出资金",
    })
    seq5 = dict(base, **{
        "seq": 5, "time_slot": f"D+10 14:55", "action": "sell", "order_price": None,
        "sell_date": sell_date,  # 结构化键(YYYYMMDD): 前端 _atFindSellDue 按 today>=sell_date 判卖出到期, 防 D+1 提前叫卖
        "expected_range": f"第 10 个交易日({sell_date})收盘市价卖出 {share_str} 份",
        "decision": f"decision D: 到 A 模式到期日(D+10, {sell_date})? 是→市价卖出全部份额; Phase1 提醒手动 / Phase2 自动",
        "trigger_note": f"A 模式固定 10 个交易日到期: 卖出日 {sell_date}, 收盘市价卖出 {share_str} 份; Phase1 提醒手动 / Phase2 自动",
    })
    return [seq1, seq2, seq3, seq5]


def _backfill_missing_seqs(steps: list, trade_dates: list[str], now: str) -> bool:
    """迁移逻辑(需求①): 已存在 seq1 但缺 seq2/3/5 的 date|etf 组自动补完整链。

    只对 date|etf 组内有 seq1 的组补(说明该日真实生成了计划), 不丢已有 seq1 状态,
    已有 seq 不重复追加(幂等)。返回是否写入了新行。
    """
    if not isinstance(steps, list) or not steps:
        return False
    changed = False
    groups = {}
    order = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        d = str(s.get("date") or "")
        c = str(s.get("etf_code") or "")
        if not d or not c:
            continue
        k = (d, c)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(s)
    for k in order:
        rows = groups[k]
        have = {int(s.get("seq") or 0) for s in rows}
        if 1 not in have or all(x in have for x in STANDARD_SEQS):
            continue
        s1 = next((s for s in rows if str(s.get("seq")) == "1"), None)
        if not s1:
            continue
        # 卖出日 = 信号日后第 10 交易日; 老行无 signal_date, 用 buy_date 等价换算(第 9 个 > buy_date)
        sell_date = ""
        if trade_dates:
            sell_date = _nth_trading_day_after(trade_dates, str(s1.get("date") or ""), 9)
        p = {
            "buy_date": s1["date"],
            "etf_code": s1["etf_code"],
            "etf_name": s1.get("etf_name") or "",
            "prev_close": s1.get("order_price"),
            "amount": s1.get("amount") or BUY_AMOUNT,
            "signal": s1.get("signal") or "",
            "track_score": s1.get("track_score"),
        }
        for st in _build_steps_for_plan(p, now, sell_date):
            if int(st["seq"]) in have:
                continue
            # 迁移补行与回填段(#106)同标记: 前端显示「回填」角标, 说明干跑阶段恒 pending 不回写执行状态
            st["backfilled"] = True
            steps.append(st)
            have.add(int(st["seq"]))
            changed = True
            log(f"auto_trade_steps 迁移补齐 seq{st['seq']} {s1['etf_code']} {s1['etf_name']} date={s1['date']}")
    return changed


def _score_eq(a, b) -> bool:
    """track_score 浮点比较(round 到 4 位防浮点误差; None 两端相等)。"""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        return round(float(a), 4) == round(float(b), 4)
    except (TypeError, ValueError):
        return str(a) == str(b)


def _idempotency_check(steps, buy_date, new_codes, allow_past_replace=False, new_score_map=None):
    """幂等判定(2026-09-17 升级 buy_date+seq1 → buy_date+seq1+etf_code, 根治「过时快照不自愈」;
    2026-09-18 ⑤ 加已过执行日 replace 冻结 gate; 2026-09-18 缺陷a 加 repair 模式 ts 漂移判定)。

    执行日 buy_date 已有 seq1 挂单行时, 比较其 etf_code 集合与本次重算 top1(new_codes):
      - 一致 → 日常 "skip"(无漂移, 幂等跳过); 一致 且 repair 模式传 new_score_map 时, 额外逐行比较
        seq1 track_score 与本次重算(冻结分口径)——ts 漂移(etf_code 相同但 track_score 被旧排序写成
        非冻结分)也视为漂移 → replace。
      - 不一致 → 漂移; 若 buy_date 已过执行日(<=today)则默认 "skip"(⑤ 禁 replace, 防改写已过执行日行),
        否则原地删该 buy_date 全部旧行, 返回 "replace"(调用方重写)
    无 seq1 行 → "append"(正常追加; 回填段 #106 用它补历史未到期卖出行)。
    返回 (action, removed_count, skip_reason): removed_count 仅在 "replace" 时非 0;
    skip_reason ∈ {"match"(etf_code(及 repair 模式下 track_score)一致, 幂等跳过),
    "gate_past"(漂移但已过执行日, ⑤ 禁 replace), "repair_past"(修复模式替换已过执行日 code 漂移行),
    "repair_ts_past"(修复模式替换已过执行日 ts 漂移行), "drift_replace"(未来执行日 code 自愈替换),
    "drift_ts_replace"(未来执行日 ts 自愈替换)}。

    allow_past_replace=True(--repair-backfill 一次性修复模式): 漂移且已过执行日时仍 replace, 用于把
    commit 2f9502a92(K=1 排序改用信号日冻结分)之前写错的 backfilled 历史行(code 与 ts 两种漂移)重写
    正确。日常运行(False)行为不变: ⑤ gate 仍冻结已过执行日行, 防改写历史组(修复不会天天来回改),
    幂等只比 etf_code(new_score_map 不生效)。

    ⚠ ⑤ 已过执行日 replace 冻结 gate(2026-09-18, 3版本漂移根因③): 只包住 replace 分支——
      - 有 seq1 且漂移 且 buy_date <= today → "skip"(禁止 replace: 9-17 22:30 回填 20260916
        曾 replace 改写 9-17 执行日行; 执行日已过的历史组不再重写; 仅 --repair-backfill 显式豁免)
      - append/skip 分支不受 gate 影响: 无 seq1 的历史组仍 append 补卖出行(#106 正常功能, 不改写
        已存在行, 只补缺失提醒, 无执行风险), 一致组照常 skip。
      主链 buy_date=T+1>today 的漂移自愈不受影响; 迁移 _backfill_missing_seqs(L342-360)不走本函数,
      不受影响; gap_check 改执行状态不走生成器, 不受影响。
    """
    existing_seq1 = [s for s in steps if str(s.get("date")) == buy_date and str(s.get("seq")) == "1"]
    if not existing_seq1:
        return "append", 0, "append"
    existing_codes = {str(s.get("etf_code") or "") for s in existing_seq1}
    _today_str = _today()  # YYYYMMDD
    past = str(buy_date or "") <= _today_str
    if existing_codes == new_codes:
        if allow_past_replace and new_score_map:
            # repair 模式: 逐行核对 seq1 track_score 与本次重算(冻结分口径)一致, 防 ts 漂移漏修。
            for s in existing_seq1:
                _ec = str(s.get("etf_code") or "")
                if _ec in new_score_map and not _score_eq(s.get("track_score"), new_score_map[_ec]):
                    removed = sum(1 for _s in steps if str(_s.get("date")) == buy_date)
                    steps[:] = [x for x in steps if str(x.get("date")) != buy_date]
                    return "replace", removed, "repair_ts_past" if past else "drift_ts_replace"
        return "skip", 0, "match"
    if past and not allow_past_replace:
        # 漂移且已过执行日 → ⑤ gate 禁 replace(默认), 保持历史行不动(--repair-backfill 显式豁免)。
        return "skip", 0, "gate_past"
    # 漂移 → 删旧行重写: 未来执行日自愈(past=False), 或修复模式豁免已过执行日行(past and allow_past_replace)。
    removed = sum(1 for s in steps if str(s.get("date")) == buy_date)
    steps[:] = [s for s in steps if str(s.get("date")) != buy_date]
    return "replace", removed, "repair_past" if past else "drift_replace"


def _norm_signal(sig: str) -> str:
    """买信号归一: buy_special_filtered(邮件链路变体名) -> buy_special(与 queries/前端同口径)。"""
    return "buy_special" if str(sig or "") == "buy_special_filtered" else str(sig or "")


def _top_etf_by_score(etfs):
    """首页 AI建议 top1 判定(static-site/app.js _topEtfByScore 同构):
    _bk_top(冻结表权威)优先; 未命中 → 纯 max(track_score), 平手回退 similarity(与回测 _build_best_etf 同准则)。

    2026-09-18 ③ K=1 赢家随信号日 T 固化: 命中 _bk_top 且带 _bk_ts(冻结分)时返回冻结分副本
    (track_score 覆盖为 _bk_ts), 与前端同构——排序值用冻结时点分, 不随 board_etf_map 双树/重生值漂移。"""
    if not etfs:
        return None
    for _e in etfs:
        if isinstance(_e, dict) and _e.get("_bk_top") is True:
            _bk_ts = _e.get("_bk_ts")
            if isinstance(_bk_ts, (int, float)):
                _fz = dict(_e)
                _fz["track_score"] = _bk_ts
                return _fz
            return _e
    best = None
    for _e in etfs:
        if not isinstance(_e, dict):
            continue
        ts = _e.get("track_score")
        if ts is None:
            continue
        if best is None or ts > best.get("track_score", -1):
            best = _e
        elif ts == best.get("track_score"):
            if (_e.get("similarity") or -1) > (best.get("similarity") or -1):
                best = _e
    return best


def _signal_candidates(conn, cfg, T, freeze, sig_stats):
    """首页 overview 同款构建当日信号候选(signal_daily 注入 etfs + 冻结 _bk_top + ai_macro)。

    返回 sigs, 每条含: date/index_id/signal/reason/etfs/_bt_in_universe/ai_macro/_top1/_rating。
    """
    rows = conn.execute(
        "SELECT date, index_id, signal, reason FROM signal_daily "
        "WHERE date=? AND index_id NOT LIKE 's.%%' ORDER BY index_id",
        (T,),
    ).fetchall()
    sigs = [dict(r) for r in rows]
    if not sigs:
        return sigs
    _mkt_map = appq._ai_macro_build_market_map(cfg)
    _tier_state, _tier_dates, _ma60_bull_state = appq._ai_macro_build_market_state(conn)
    _cyb_state, _cyb_dates = appq._ai_macro_build_cyb_tier(conn)
    _ctx = {
        "rating_of": lambda _s: appq._ai_macro_rating_of(_s, sig_stats),
        "market_of": lambda _iid: _mkt_map.get(_iid or "", ""),
        "track_score_of": appq._ai_macro_track_score_of,
        "tier_of": lambda _d: appq._ai_macro_tier_at(_d, _tier_state, _tier_dates),
        "ma60_bull_of": lambda _d: appq._ai_macro_ma60_bull_at(_d, _ma60_bull_state, _tier_dates),
        "cyb_tier_of": lambda _d: appq._ai_macro_tier_at(_d, _cyb_state, _cyb_dates),
    }
    for _s in sigs:
        # ETF 候选注入(board_etf_map 或 self ETF), 与 overview L1186-1193 同款
        _self = appq._self_etf_for(_s["index_id"], cfg, conn)
        if _self:
            _s["etfs"] = _self["etfs"]
        else:
            _s["etfs"] = [dict(_e) for _e in (appq.etf_for(_s["index_id"]).get("etfs") or [])]
        # 冻结表命中 → 该信号 top1 = 回测标的(标 _bk_top 权威); 空数组指数不从冻结 prepend(同首页)
        appq._align_home_top1_to_backtest(_s, freeze)
        _s["_bt_in_universe"] = any(_e.get("track_score") is not None for _e in (_s.get("etfs") or []))
        # AI宏降亏命中标注(与 overview L1444-1452 同款)
        _f = appq._ai_macro_hit_filters(_s, _ctx)
        _s["ai_macro"] = {"hit": bool(_f), "filters": _f}
        _s["_top1"] = _top_etf_by_score(_s.get("etfs"))
        _s["_rating"] = appq._ai_macro_rating_of(_s, sig_stats)
        # hs300 四档(T 日大盘状态, bullAuxBackupStop a9 分支判定用)
        _s["_tier_at"] = appq._ai_macro_tier_at(T, _tier_state, _tier_dates)
    return sigs


def _ai_fade_hit(sig: dict, members) -> bool:
    """首页 _isAiFadeHit 同款降亏判定: ai_macro.filters ∩ S06 基座成员集; a9 基座补 bullAuxBackupStop。

    members: s06.filters_for_date(T) 的 True 键集合; None = S06 快照缺行 fail-open(放行)。
    """
    if members is None:
        return False
    if sig.get("ai_macro", {}).get("hit"):
        fs = sig.get("ai_macro", {}).get("filters") or []
        if any(_fk in members for _fk in fs):
            return True
    if "bullAuxBackupStop" in members:
        # 前端 _isBullStopHit(app.js L2904)同构: sig∈{buy_aux,buy_backup} × tier=牛市·主升
        # 用 kp._tds_fade_spec_hit(LEGACY_SPECS 同源)判定, 避免内联复制分叉
        if kp._tds_fade_spec_hit("bullAuxBackupStop",
                                 {"sig": str(sig.get("signal") or ""), "tier": str(sig.get("_tier_at") or "")}):
            return True
    return False


def _kelly_sort_key(cand: dict):
    """K=1 排序准则(kelly _position_cap_kept_keys / 首页 _posCapSortedFn 同款):
    track_score DESC → rating(high>mid>low) → signal(buy_backup>buy>buy_aux>buy_special) → buy_date ASC。

    2026-09-18 ③ K=1 赢家随信号日 T 固化: 排序分优先取冻结分(_bk_ts, 随信号日 T 固化),
    未命中冻结无 _bk_ts 则取 track_score(与前端 _topEtfByScore 同构, 防双树/重生值漂移)。"""
    _bk_ts = cand.get("_bk_ts")
    ts = _bk_ts if isinstance(_bk_ts, (int, float)) else cand.get("track_score")
    if ts is None:
        ts = -1.0
    return (-float(ts), _RATING_RANK.get(str(cand.get("_rating") or ""), 3),
            _SIG_RANK.get(str(cand.get("signal") or ""), 9), str(cand.get("buy_date") or ""))


def _build_plan_for_day(conn, cfg, db_path, trade_dates, T, freeze, sig_stats, s06, prefix=""):
    """给定信号日 T 构建当日买入计划(首页 AI建议同一条链; 任意 T 通用, 回填段逐日重演即复用本函数)。

    与主链当日计划同一代码路径(信号候选 → 买信号/宇宙/降亏过滤 → K=1 保留 → prev_close 双校验),
    避免回填另写一份造成「第二份实现」漂移(§5.4⑦)。
    返回 plan 列表(每条含 etf_code/etf_name/prev_close/amount/signal/track_score/signal_date/buy_date;
    空列表=当日无计划)。
    """
    _logp = (lambda m: log(f"{prefix} {m}")) if prefix else log
    sigs = _signal_candidates(conn, cfg, T, freeze, sig_stats)
    _logp(f"T={T} signal_daily 信号(排除 s.*)={len(sigs)}")

    # 买信号 + 入样宇宙 + 降亏过滤(首页 kept 同款): 先滤降亏再选 top-K
    _f6 = s06.filters_for_date(T)
    members = {k for k, v in (_f6 or {}).items() if v} if _f6 else None
    if members is None:
        _logp(f"⚠ s06 快照缺行(T={T} 无基座), 降亏过滤 fail-open 放行(与前端降级契约一致)")
    kept_signals = []
    fade_cut = []
    for _s in sigs:
        _sig = _norm_signal(_s["signal"])
        if _sig not in BUY_SIGNALS:
            continue
        if not _s.get("_bt_in_universe"):
            _logp(f"  - {_s['index_id']} {_sig} 未入样宇宙(无跟踪 ETF track_score)")
            continue
        top1 = _s.get("_top1")
        if not top1 or top1.get("track_score") is None:
            continue
        if _ai_fade_hit(_s, members):
            fade_cut.append(f"{_s['index_id']} {_s['signal']} ai_filters={_s['ai_macro']['filters']}")
            continue
        kept_signals.append({
            "signal_date": T,
            "index_id": _s["index_id"],
            "signal": _sig,
            "etf_code": str(top1.get("code") or ""),
            "etf_name": str(top1.get("name") or "") or str(top1.get("code") or ""),
            "track_score": top1.get("track_score"),
            "track_tier": top1.get("track_tier"),
            "_rating": _s.get("_rating"),
            # ③ 2026-09-18 冻结分双保险: 命中 _bk_top 时带冻结分, _kelly_sort_key 优先用它排序
            "_bk_ts": top1.get("_bk_ts"),
        })
    for _c in fade_cut:
        _logp(f"  ✗ 降亏过滤剔除: {_c}")
    _logp(f"当日买入信号通过降亏候选={len(kept_signals)}")

    # ---- K=1 保留(首页 AI建议 top1 同款排序) ----
    buy_date = _next_trading_day(trade_dates, T)
    if buy_date is None:
        _logp(f"⚠ 交易日历无 > {T} 的下一交易日(可能 T 已是日历最后一天), 走空计划")
        kept_signals = []
    for _c in kept_signals:
        _c["buy_date"] = buy_date
    kept_signals.sort(key=_kelly_sort_key)
    kept_signals = kept_signals[:K]
    _kept_desc = [f"{c['index_id']}|{c['signal']}|{c['etf_code']} ts={c['track_score']}" for c in kept_signals]
    _logp(f"K={K} 保留信号={_kept_desc}")

    # ---- prev_close + 双校验(原逻辑保留) ----
    plan = []
    for t in kept_signals:
        etf_code = t["etf_code"]
        etf_name = t["etf_name"]
        track_score = t["track_score"]
        # 信号日收盘 = etf_daily 该 etf T 日 close(挂单价上限 + 伪跳空校验参考点)
        _, prev_close = _prev_close(db_path, etf_code, T)
        sig_close = prev_close
        # 双校验 ①: prev_close>0 非停牌(信号日 T 有成交, 挂单价上限有效)
        if prev_close is None or prev_close <= 0:
            _logp(f"  ✗ {etf_code} {etf_name} prev_close={prev_close}(非停牌校验失败, 信号日无成交)")
            continue
        # 双校验 ②: 伪跳空剔除真口径(次日 open / 信号日收盘 - 1, |gap|>20% 剔除;
        #            与回测 signal_kelly_backtest.PSEUDO_GAP_EXCLUDE 同式, 防除权/份额折算错位)
        nxt_open = _next_open(db_path, etf_code, T)
        if nxt_open is not None and nxt_open > 0:
            gap = nxt_open / sig_close - 1.0
            if abs(gap) > PSEUDO_GAP:
                _logp(f"  ✗ {etf_code} {etf_name} 伪跳空剔除 nxt_open={nxt_open} sig_close={sig_close} gap={gap:.2%}")
                continue
        else:
            # T+1 开盘价未入库(当日计划, 次日未开盘) → 跳过, 留 9:26 nextday_gap_check 二次剔除
            _logp(f"  ~ {etf_code} {etf_name} 次日开盘价未入库(nxt_open={nxt_open}), 留 9:26 gap-check 兜底")
        plan.append({
            "etf_code": etf_code,
            "etf_name": etf_name,
            "prev_close": round(prev_close, 4),
            "amount": BUY_AMOUNT,
            "signal": t["signal"],
            "track_score": track_score,
            "signal_date": T,
            "buy_date": buy_date,
        })
    return plan


def _repair_backfill_window(trade_dates, T, steps_doc):
    """repair 模式(--repair-backfill)回填窗口: 常规最近 BACKFILL_WINDOW_DAYS 交易日 + 显式枚举现有
    backfilled 行的 buy_date 反推 signal_date(前一交易日)。

    原因(2026-09-18 缺陷b): 固定 [-BACKFILL_WINDOW_DAYS:] 只覆盖 20260904 起的窗口, 早于窗口的
    signal 20260902(道琼斯 ts 漂移)/20260903(光伏 code 漂移)漏修。显式枚举保证任何历史漂移行
    的 signal_date 都进窗口重演。日常模式窗口保持 [-BACKFILL_WINDOW_DAYS:] 不变。
    """
    days = [d for d in trade_dates if d < T]
    window = set(days[-BACKFILL_WINDOW_DAYS:])
    td_set = set(trade_dates)
    for st in steps_doc.get("steps", []):
        if not st.get("backfilled"):
            continue
        bd = str(st.get("date") or "")
        if bd not in td_set:
            continue
        idx = trade_dates.index(bd)
        if idx > 0:
            window.add(trade_dates[idx - 1])
    return sorted(window)


def _backfill_historical_groups(conn, cfg, db_path, trade_dates, T, freeze, sig_stats, s06,
                                steps_doc, now, repair_backfill=False):
    """历史持仓回填段(#106): 最近 BACKFILL_WINDOW_DAYS 交易日窗口内补未到期卖出行。

    对窗口内每个历史信号日 T'(< T 且落在窗口), 用 _build_plan_for_day 重演当日计划,
    把生成的完整行为链(seq1-5)追加到 steps_doc, 每条带 backfilled=true 标记。
    幂等: date(buy_date)+seq1+etf_code(+repair 模式下 track_score)判定(一致跳过, 漂移删旧行重写自愈
    替换), 重复跑不产生重复行。
    只补未到期组(sell_date >= T 且非空): 已到期(sell_date < T)的旧持仓不生成卖出提醒(防过期骚扰)。
    repair_backfill=True(--repair-backfill): 透传 _idempotency_check 豁免 ⑤ gate, 一次性重写已过执行日
    的漂移 backfilled 历史行(commit 2f9502a92 排序改冻结分前写错的行); 窗口扩展为
    _repair_backfill_window(常规窗口 + 枚举现有 backfilled 行 signal_date, 覆盖窗口外历史漂移行);
    并豁免「已到期组跳过」gate(缺陷c: 已到期组的 ts/code 漂移同样要改对, 日常模式保持跳过)。
    返回是否写入了新行。
    """
    if not trade_dates:
        return False
    window = _repair_backfill_window(trade_dates, T, steps_doc) if repair_backfill else \
        [d for d in trade_dates if d < T][-BACKFILL_WINDOW_DAYS:]
    _logp = lambda m: log(f"[回填] {m}")
    changed = False
    for Tb in window:
        plan_b = _build_plan_for_day(conn, cfg, db_path, trade_dates, Tb, freeze, sig_stats, s06,
                                     prefix=f"[回填{Tb}]")
        if not plan_b:
            continue
        bd = str(plan_b[0]["buy_date"] or "")
        # 先判到期(与旧口径一致: 已到期组不删只不再补, 防过期骚扰; 漂移自愈只作用于未到期组)。
        # repair 模式豁免(缺陷c 2026-09-18): --repair-backfill 目的就是改写历史漂移行, 已到期组
        # (卖出日 < T)同样有历史漂移, 必须继续走幂等 replace 改对 ts/code; 日常模式保持跳过不变。
        sell_date = _nth_trading_day_after(trade_dates, str(plan_b[0]["signal_date"]), 10) if trade_dates else ""
        if (not sell_date or sell_date < T) and not repair_backfill:
            _logp(f"跳过已到期组 buy_date={bd} sell_date={sell_date}(< T {T})")
            continue
        # 幂等(与主链当日追加同判定, 2026-09-17 升级 buy_date+seq1+etf_code): 已有该执行日 seq1
        # 且 etf_code 一致 → 跳过; 漂移 → 删旧行重写(自愈替换); --repair-backfill 豁免 ⑤ gate 改已过执行日
        # 行 + 升级比较 track_score(缺陷a 2026-09-18), 修 etf_code 相同但 ts 被旧排序写错的漂移。
        _new_codes = {str(p.get("etf_code") or "") for p in plan_b}
        _new_score_map = {str(p.get("etf_code") or ""): p.get("track_score") for p in plan_b}
        _action, _removed, _skip_reason = _idempotency_check(
            steps_doc["steps"], bd, _new_codes, allow_past_replace=repair_backfill,
            new_score_map=_new_score_map if repair_backfill else None)
        if _action == "skip":
            if _skip_reason == "gate_past":
                _logp(f"幂等跳过 buy_date={bd}(漂移但已过执行日, ⑤ gate 禁 replace, 不改写历史)")
            else:
                _logp(f"幂等跳过 buy_date={bd}(已在表且 etf_code/track_score 一致)")
            continue
        if _action == "replace":
            _tag = "修复替换(--repair-backfill)" if _skip_reason in ("repair_past", "repair_ts_past") else "自愈替换"
            _kind = "ts 漂移" if _skip_reason in ("repair_ts_past", "drift_ts_replace") else "etf_code 漂移"
            _logp(f"{_tag} buy_date={bd} 旧行 {_kind}, 删旧行 {_removed} 行重写")
        for p in plan_b:
            for st in _build_steps_for_plan(p, now, sell_date):
                st["backfilled"] = True
                steps_doc["steps"].append(st)
            changed = True
            _logp(f"回填补历史持仓卖出行 {p['etf_code']} {p['etf_name']} buy_date={bd} sell_date={sell_date} backfilled")
    return changed


def main():
    ap = argparse.ArgumentParser(description="次日买入计划生成器(PRD 阶段一 §3/§6, 干跑)")
    ap.add_argument("--date", default=None, help="信号日 T(YYYYMMDD, 缺省=今天)")
    ap.add_argument("--dry-run", action="store_true", help="只计算打印, 不落盘两树/不 R2/不通知")
    ap.add_argument("--no-r2", action="store_true", help="落盘但不传 R2(自测用)")
    ap.add_argument("--no-notify", action="store_true", help="落盘但不通知(自测用)")
    ap.add_argument("--no-backfill", action="store_true", help="关闭历史持仓回填段(自测/临时关)")
    ap.add_argument("--repair-backfill", action="store_true",
                    help="一次性修复模式: 豁免 _idempotency_check ⑤ gate, 允许 replace 已过执行日的漂移 "
                         "backfilled 历史行(commit 2f9502a92 改信号日冻结分前写错的行; 日常勿用)")
    args = ap.parse_args()

    T = args.date or _today()
    data_dir = REPO / "static-site" / "data"
    db_path = REPO / "data" / "etf_national_team.db"
    if not db_path.exists():
        db_path = ROOT / "data" / "etf_national_team.db"
    sent_db = REPO / "data" / "sentiment.db"
    if not sent_db.exists():
        sent_db = ROOT / "data" / "sentiment.db"
    log(f"REPO={REPO} T={T} dry_run={args.dry_run}")

    # 输入产物
    s06_doc = _load_json("kelly_mode_s06_state.json", data_dir)
    freeze = appq._etf_freeze()

    # etf_daily 基础就绪检查(全空无法取 prev_close 与交易日)
    etf_dates = _etf_daily_dates(db_path)
    if not etf_dates:
        log("✗ etf_daily 为空, 无法确定 prev_close 与交易日")
        return 2
    # s06 解析器(fail-open: 快照缺行 → None → 降亏放行, 同前端降级契约; 成员集计算在 _build_plan_for_day 内按 T 求)
    s06 = kp.S06Resolver(s06_doc)

    # 交易日集合(权威交易日历优先; 回填窗口与 buy_date 推算共用)
    cal_dates = _trade_calendar_dates(db_path)
    trade_dates = cal_dates or etf_dates
    if not trade_dates:
        log("✗ 交易日历与 etf_daily 均为空, 无法确定下一交易日")
        return 2

    # ---- 信号候选 → 当日计划(复用 _build_plan_for_day, 回填段同一代码路径) ----
    conn = sqlite3.connect(f"file:{sent_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cfg = load_config()
        sig_stats = appq.sigstats.load()
    except Exception as e:
        conn.close()
        log(f"✗ 信号统计/配置加载失败: {e}")
        return 2
    plan = _build_plan_for_day(conn, cfg, db_path, trade_dates, T, freeze, sig_stats, s06)

    # ---- 数据就绪 gate(§23.15 不上残缺版): 计划内每只 ETF 的 etf_daily 最新日必须 == T。
    #      #38 根治: 原 gate 用全局 max date(任一 ETF 到 T 就放行), 计划内停在旧日的 ETF(如 159880
    #      停在 09-14)被纳入 → prev_close 非 T 日收盘失真。改为逐只校验计划内 etf_code 最新日。
    #      时序倒挂根治(2026-09-17): fail-closed —— 缺当日收盘价(最新日 < T)时阻塞 + 告警,
    #      不再提供 NEXTDAY_PLAN_FORCE=1 强制继续用前日价(fail-open 已移除)。
    stale_codes = _plan_stale_codes(db_path, plan, T)
    if stale_codes:
        _severe_alert(
            f"[告警] 次日买入计划数据未就绪(缺当日收盘价) {T}",
            f"nextday_plan_generator.py: 计划内 ETF 最新交易日 < T {T}(etf_daily 当日收盘价未入库), "
            f"_prev_close 会退化为前日价(次日买入价时序倒挂), 已阻塞不产出计划。"
            f"<br>stale_codes: {stale_codes}<br>日志: {REPO}/data/logs/nextday_plan_launchd.log",
        )
        log(f"✗ 数据未就绪: 计划内 ETF 停在旧日(最新日 < T {T}, 缺当日收盘价): {stale_codes} "
            f"(etf_daily 当日收盘价未入库, 次日买入价会时序倒挂), 不产出误导性计划(fail-closed)")
        return 2

    buy_date = plan[0]["buy_date"] if plan else (_next_trading_day(trade_dates, T) if trade_dates else "")
    plan_doc = {"date": T, "plan": plan} if plan else {"date": T, "empty": True}
    log(f"计划条目={len(plan)} buy_date={buy_date}")
    for p in plan:
        log(f"  {p['etf_code']} {p['etf_name']} prev_close={p['prev_close']} amount={p['amount']} "
            f"signal={p['signal']} track_score={p['track_score']} buy_date={p['buy_date']}")

    # ---- auto_trade_steps.json 处理(加载 → 当日计划追加 → 历史回填 → 迁移; 全内存计算后统一落盘) ----
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
    # 幂等(2026-09-17 升级 buy_date+seq1 → buy_date+seq1+etf_code, 根治过时快照不自愈):
    # 执行日 buy_date 已有 seq1 且 etf_code 与本次重算 top1 一致 → 跳过; 漂移 → 删旧行重写。
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    steps_changed = False
    if plan:
        _new_codes = {str(p.get("etf_code") or "") for p in plan}
        _new_score_map = {str(p.get("etf_code") or ""): p.get("track_score") for p in plan}
        _action, _removed, _skip_reason = _idempotency_check(
            steps_doc["steps"], buy_date, _new_codes, allow_past_replace=args.repair_backfill,
            new_score_map=_new_score_map if args.repair_backfill else None)
        if _action == "skip":
            if _skip_reason == "gate_past":
                log(f"auto_trade_steps 漂移但已过执行日 date={buy_date}, ⑤ gate 禁 replace, 幂等跳过(不改写历史)")
            else:
                log(f"auto_trade_steps 已含执行日 date={buy_date} 且 etf_code/track_score 一致, 幂等跳过追加")
        else:
            if _action == "replace":
                _repair_tag = "修复替换(--repair-backfill)" if _skip_reason in ("repair_past", "repair_ts_past") else "自愈替换"
                _kind = "ts 漂移" if _skip_reason in ("repair_ts_past", "drift_ts_replace") else "etf_code 漂移"
                log(f"auto_trade_steps {_repair_tag}: 执行日 date={buy_date} 旧行 {_kind} 与本次重算 "
                    f"top1 {sorted(_new_codes)} 漂移, 删旧行 {_removed} 行重写")
            for p in plan:
                # 卖出日 = 信号日后第 10 交易日(A 模式 hold_days=10, 与回测 sell_date 口径一致)
                sell_date = _nth_trading_day_after(trade_dates, str(p["signal_date"]), 10) if trade_dates else ""
                for st in _build_steps_for_plan(p, now, sell_date):
                    steps_doc["steps"].append(st)
                steps_changed = True
                log(f"auto_trade_steps 追加完整行为链 {p['etf_code']} {p['etf_name']} "
                    f"buy_date={p['buy_date']} sell_date={sell_date} seq1/2/3/5")

    # 历史持仓回填段(#106): 窗口内每个历史交易日 T' 重演当日计划, 补未到期卖出行(幂等并入同一判定)
    if not args.no_backfill:
        if _backfill_historical_groups(conn, cfg, db_path, trade_dates, T, freeze, sig_stats, s06,
                                       steps_doc, now, repair_backfill=args.repair_backfill):
            steps_changed = True

    conn.close()  # 回填段为 conn 最后使用点, 后续落盘/R2/notify 均不依赖 SQLite 连接

    # 迁移: 已有 seq1 缺 seq2/3/5 的历史组自动补齐(需求① 不丢已有 seq1 状态)
    if _backfill_missing_seqs(steps_doc["steps"], trade_dates, now):
        steps_changed = True

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

    if steps_changed:
        for sp in steps_paths:
            with sp.open("w", encoding="utf-8") as f:
                json.dump(steps_doc, f, ensure_ascii=False, indent=1)
            written.append(str(sp))
        log(f"auto_trade_steps 落盘完成(steps_changed): {len(steps_doc['steps'])} 行")

    # ---- R2 上传(§22 三步同步; 盘后产物走 upload-data-files 段) ----
    # F2(2026-09-10): R2 失败不再静默 —— notify --severe + 最终退出码非 0。
    # 范围边界: 只对「会让线上停滞」的失败(R2 上传失败)告警; notify 通道自身波动
    # 不升级(计划已落盘本地, git/次日 deploy 兜底, 流程不要求在盘中强一致)。
    r2_rc = 0
    if not args.no_r2 and not args.dry_run:
        r2_files = ["nextday_plan.json"]
        # #106: 只要有 steps 变更(当日计划新增 / 历史回填补行 / 迁移补齐)就传, 不只看 plan(空计划日回填会漏传)
        if steps_changed:
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
               "--dedup-key", f"nextday_plan_{T}", "--dedup-window", "86400",
               "--feishu-group", "follow"]
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
    # F2(#98): 主流程未捕获 Exception 兜底 —— 既有 exit 分支(error 均 return 非 0)已覆盖
    # 已知失败面, 此处兜「意外异常」(如产物结构新 bug/DB 读错), 不再只打 traceback 静默:
    # ①log 错误 ②notify.py --severe 告警(带 stderr) ③exit 非 0 → schedule_monitor 感知
    try:
        rc = main()
    except SystemExit:
        raise
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        log(f"✗ 未捕获异常({type(e).__name__}): {e}\n{tb}")
        _severe_alert(
            f"[告警] 次日买入计划生成器异常 {type(e).__name__}",
            f"nextday_plan_generator.py 主流程未捕获异常, 次日买入计划生成中断(线上文件保持上一批)。"
            f"<br>异常: <pre>{tb[-2000:]}</pre>"
            f"<br>日志: {REPO}/data/logs/nextday_plan_launchd.log",
        )
        sys.exit(2)
    sys.exit(rc)