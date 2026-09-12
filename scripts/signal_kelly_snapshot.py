#!/usr/bin/env python3
"""signal_kelly_snapshot.py - 信号凯利回测每日快照 + 演进序列 + 断链/突变告警

目的:
    每日回测产物(signal_kelly_backtest.json)生成后, 提取 16 象限×5 周期×10 模式
    关键指标子集 + max_signal_date(全部成交 signal_date 最大值, 直接观测"信号停滞")
    + 最近 10 笔成交摘要 + 版本号, 固化到
    static-site/data/signal_kelly_snapshots/YYYYMMDD.json(全量快照, 按日一个文件),
    并维护 index.json(迷你演进序列: 每日 max_signal_date + 每模式 all 周期 total_return/n),
    供 lab「演进」曲线 + 首页角标读取; --check 模式下扫描 index.json 序列做两类告警。
    2026-09-04 P0 断链根治配套: 本快照让「回测 max_signal_date 停更」(类 9/1-9/4 零成交
    事故)变成自动可见(停滞档告警), 而不再等用户/超时发现。

方法口径:
    - key metric subset = {n, win_rate, pl_ratio, mean_return, total_return,
      annualized_return}; 每 (quadrant, period, mode) 一个指标对象。
    - max_signal_date = 全部成交 signal_date 最大值; recent 10 = 按 signal_date 降序
      取全局最新 10 笔(compact 数组 + fields, 对齐 trades 产物结构)。
    - 突变告警判定 = (std_jump and pp_jump) or (pp_jump and dir_confirmed)(#109 相对口径):
      std_jump = |今日 total_return − 窗口均值| > MUTATION_STD×std;
      pp_jump  = |单日 Δ| > max(窗口均值×MUTATION_PCT, ABS_FLOOR_DELTA(若窗口均值<ABS_FLOOR_MEAN));
      dir_confirmed = 前一日 Δ 与同向阈值(窗口均值×MUTATION_DIR_PCT)同向。
      ⚠️ 防前视 (§5.1⑥): 窗口/阈值只用 t 之前(含 t-1)的数据计算, 绝不用全期分位/未来数据反推。
    - 突变的绝对下限: 窗口均值 < ABS_FLOOR_MEAN(500元, 小模式如 E 百元量级)时,
      单日 |Δ| > ABS_FLOOR_DELTA(200元) 仍算 pp_jump(防小模式逃逸)。
    - 发布日(快照 version 变化)豁免突变告警; 停滞档不设趋势门(缺失即告警)。
    - 告警走 scripts/notify.py send()(邮件+飞书同 body, §23.10), dedup-key+24h 防抖。

输入依赖:
    - static-site/data/signal_kelly_backtest.json (回测统计, export.py 生成)
    - static-site/data/signal_kelly_trades.json   (交易记录, 同批生成)
输出:
    - static-site/data/signal_kelly_snapshots/YYYYMMDD.json (全量快照)
    - static-site/data/signal_kelly_snapshots/index.json     (迷你演进序列)
    - static-site/data/signal_kelly_snapshots/latest_posrating.json
      (#54 方案B 首页 AI仓位建议 K 档评级全史动态源, 复刻 lab _kellyApplyFeeRecompute
      K 档段, 供首页首屏注入; s06 状态缺失跳过=防残缺数据上线, 详见 write_posrating_file)
关键参数(常量, 不可从外部配置):
    - SNAPSHOT_VERSION 常量: "1.0", bump 当日=发布日豁免突变告警
    - ROLLING_WINDOW=60(快照日), MUTATION_STD=3.0, MUTATION_PCT=0.05,
      MUTATION_DIR_PCT=0.01, ABS_FLOOR_MEAN=500.0, ABS_FLOOR_DELTA=200.0,
      MIN_SAMPLES=5(窗口样本下限), LAG_ALERT_TD=2(posrating 停更档, 交易日),
      STAGNATION_LAG_ALERT_TD=3(停滞档, 容忍次日开盘成交 1 天延迟),
      DEDUP_WINDOW=86400(24h 防抖)
复现命令:
    # 生成今日快照 + 更新 index(export.py L1223 内部以 --data-dir DATA_DIR 调用, 写 trade-data 侧)
    python scripts/signal_kelly_snapshot.py --data-dir <DATA_DIR>
    # 只读模式告警检测(挂 backfill_metrics.sh 02:00/16:35/21:00 尾部,
    #   backfill 侧必须显式 --data-dir "$REPO/static-site/data" 与 export 写侧一致)
    python scripts/signal_kelly_snapshot.py --check --data-dir <DATA_DIR>
    # 从快照目录全量重建 index.json(2026-09-10 P0 修复配套: sig_main 显式取 + 防污染拦截)
    python scripts/signal_kelly_snapshot.py --rebuild --data-dir <DATA_DIR>
退出码语义(调用方依赖, 变更需同步 backfill_metrics.sh 快照段):
    0 = 快照成功 / --check 无告警
    1 = --check 检测到预期告警(停滞/突变; 正常路径, 非脚本错误, 不阻塞 backfill)
    2 = 脚本异常(非预期崩溃, 如产物缺失/读取失败; 区别于"有告警")
"""
import argparse
import json
import os
import statistics
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
DEFAULT_DATA_DIR = ROOT / "static-site" / "data"

# 阈值/参数常量区 —— 滚动窗基准, 非全期分位(§5.1⑥ 防前视)
SNAPSHOT_VERSION = "1.0"          # 发布日=version 变化当日, 豁免突变告警
ROLLING_WINDOW = 60               # 滚动窗快照日数(含昨天不含今天)
MUTATION_STD = 3.0                # 突变档: |today - 窗口均值| > k×std
MUTATION_PCT = 0.05               # 突变档: 单日 |Δ| > 窗口均值 × MUTATION_PCT(相对口径)
                                  #   #109 根治: 原 MUTATION_PP=20 按"20个百分点"设计, 但
                                  #   total_return 单位是元, 9000 元量级模式(G/I)单日正常波动
                                  #   一两百元(占窗口均值 2-4%)恒误报; 取 5% 兼容正常波动(20260911
                                  #   G Δ2.87%/H Δ4.34% 均不误报), 真突变(>5%)仍告警。
MUTATION_DIR_PCT = 0.01           # 突变档 dir_confirmed: 前一日同向 |Δ| > 窗口均值 × 0.01
ABS_FLOOR_MEAN = 500.0            # 窗口均值 < 此值视为小模式(如 E 百元量级), 启用 abs 下限
ABS_FLOOR_DELTA = 200.0           # 小模式 abs 下限: 单日 |Δ| > 200 元仍算突变(防小模式逃逸)
MIN_SAMPLES = 5                   # 窗口样本下限(不足跳过突变检测)
MIN_N = 20                        # 样本门: n<20 的模式不参与突变告警(小样本噪声大)
LAG_ALERT_TD = 2                  # posrating 停更档: 生成日落后最新快照日 ≥2 个交易日告警
STAGNATION_LAG_ALERT_TD = 3       # 停滞档: max_signal_date 落后 ≥3 个交易日告警
                                  #   次日开盘成交口径(KELLY_BUY_NEXTDAY=1)下, 信号日 T 的买价由
                                  #   T+1 开盘定价, 快照当天的 max_signal_date 天然少 1 个交易日;
                                  #   若再逢单日无买系信号, 健康 lag 即达 2。阈值放宽到 3, 只告警
                                  #   "连续 ≥2 个交易日无新信号"的真停滞, 排除周末+次日成交的正常
                                  #   延迟(2026-09-12 周六误报: 9-11 周五有 buy 但 9-14 周一才成交,
                                  #   max_signal_date 停 9-9, 自然日 lag=2 被误报)
DEDUP_WINDOW = 86400              # dedup 防抖窗口(24h)
MUTATION_RATIO = 0.30             # 防污染: 单日 total_return 相对上一快照日突变比 >30% 视为污染
                                  #   (sig_main all 全史累计收益每日正常波动 <1%, 30% 必为数据污染;
                                  #    2026-09-10 P0: 9/8 accum_nav 残留致 G/H/I 虚高 ~82%)
LOG_TAG = "[sigkelly_snapshot]"


def log(msg: str) -> None:
    print(f"{LOG_TAG} {msg}", flush=True)


def _resolve_ro_frame(path_str: str) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = DEFAULT_DATA_DIR / path
    return path


def load_backtest(data_dir: Path) -> dict:
    p = data_dir / "signal_kelly_backtest.json"
    if not p.exists():
        raise FileNotFoundError(f"回测产物不存在: {p}")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def load_trades(data_dir: Path) -> dict:
    p = data_dir / "signal_kelly_trades.json"
    if not p.exists():
        raise FileNotFoundError(f"交易记录不存在: {p}")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


KEY_METRICS = ("n", "win_rate", "pl_ratio", "mean_return", "total_return",
               "annualized_return")


def extract_quadrant_subset(quadrants: dict) -> dict:
    """16 象限 × 5 周期 × 10 模式 → key metric subset。"""
    out = {}
    for qname, qobj in quadrants.items():
        periods = qobj.get("periods", {}) if isinstance(qobj, dict) else {}
        qsub = {}
        for pname, pmodes in periods.items():
            if not isinstance(pmodes, dict):
                continue
            psub = {}
            for mode, mdata in pmodes.items():
                if not isinstance(mdata, dict):
                    continue
                psub[mode] = {k: mdata.get(k) for k in KEY_METRICS}
            qsub[pname] = psub
        out[qname] = qsub
    return out


def scan_trades(trades: dict) -> tuple[str, list]:
    """全象限成交里找 max_signal_date + 最近 10 笔(按 signal_date 降序)。
    trades.quadrants = {qname: {mode: [compact_trade_array, ...]}};
    compact_trade[0] = signal_date。返回 (max_signal_date, recent10)。
    """
    fields = trades.get("fields", [])
    qs = trades.get("quadrants", {})
    max_date = ""
    recent: list[list] = []
    for qname, modes in qs.items():
        for mode, trades_list in modes.items():
            if not isinstance(trades_list, list):
                continue
            for tr in trades_list:
                if not isinstance(tr, dict):  # compact 数组第一元素是 signal_date
                    sd = tr[0] if tr else ""
                else:
                    sd = tr.get("signal_date") or tr.get("date") or ""
                if not sd:
                    continue
                if sd > max_date:
                    max_date = sd
                recent.append(tr)
    # 最近 10 笔: 按 signal_date 降序, compact 优先
    def _sd(t) -> str:
        if isinstance(t, dict):
            return t.get("signal_date") or t.get("date") or ""
        return t[0] if t else ""

    recent.sort(key=_sd, reverse=True)
    return max_date, recent[:10]


def write_posrating_file(data_dir: Path, bt: dict, trades: dict) -> None:
    """#54 方案B: 生成首页 AI仓位建议 K 档评级全史动态源 latest_posrating.json。

    复刻 lab _kellyApplyFeeRecompute K 档段(A 模式 all 伪象限 + S06 per-date passesFade
    + 每日池等分 top-K + 峰值资金统计), 与 lab 同构对账过(§5.4⑦, scripts/check_posrating_parity.mjs)。
    首页方案B = 后端注入首页槽, 解决「进/出 lab 首页 K 档值跳变」(静态快照 86.60% → lab 动态 163%)。
    ⚠️ 完整版铁律(§23.15): s06 状态文件缺失 = 全放行残缺数据, 跳过不写,
    首页回退静态兜底; loss 特征缺失与 lab 同降级(fail-open), 照常计算。任何异常不阻断主链。
    """
    s06_path = data_dir / "kelly_mode_s06_state.json"
    if not s06_path.exists():
        log("kelly_mode_s06_state.json 缺失: 跳过 latest_posrating.json"
            "(首页回退静态兜底, 防全放行残缺数据上线)")
        return
    try:
        from kelly_posrating import compute_posrating
        s06_doc = json.loads(s06_path.read_text(encoding="utf-8"))
        feats_path = data_dir / "kelly_loss_features.json"
        loss_doc = json.loads(feats_path.read_text(encoding="utf-8")) if feats_path.exists() else None
        result = compute_posrating(trades, bt, s06_doc, loss_doc)
        p = snap_dir(data_dir) / "latest_posrating.json"
        p.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        v = result["values"][1]  # compute_posrating 内 key 为 int, 序列化后转字符串
        log(f"latest_posrating.json 已生成: K1 {v['ret']} dd={v['dd']} n={v['n']}")
    except Exception as e:  # noqa: BLE001
        log(f"latest_posrating.json 生成失败(跳过, 首页回退静态兜底): {e}")


def build_snapshot(data_dir: Path) -> dict:
    bt = load_backtest(data_dir)
    trades = load_trades(data_dir)
    quadrants = bt.get("quadrants", {})
    max_signal_date, recent10 = scan_trades(trades)
    write_posrating_file(data_dir, bt, trades)
    snapshot = {
        "date": datetime.now().strftime("%Y%m%d"),
        "generated_at": bt.get("generated_at"),
        "version": SNAPSHOT_VERSION,
        "max_signal_date": max_signal_date or "",
        "quadrants": extract_quadrant_subset(quadrants),
        "recent_trades": {
            "fields": [f for f in trades.get("fields", [])],
            "trades": recent10,
        },
    }
    return snapshot


def snap_dir(data_dir: Path) -> Path:
    d = data_dir / "signal_kelly_snapshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_index(data_dir: Path) -> dict:
    p = snap_dir(data_dir) / "index.json"
    if not p.exists():
        return {"version": "", "updated_at": "", "days": []}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_index(data_dir: Path, index: dict) -> None:
    p = snap_dir(data_dir) / "index.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)


def save_snapshot(data_dir: Path, snapshot: dict) -> None:
    d = snap_dir(data_dir)
    p = d / f"{snapshot['date']}.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False)


def _sig_main_all(snapshot: dict) -> dict:
    """取 sig_main 象限 all 周期 modes(演进弹窗数据源, 与 16 象限卡 sig_main 卡片一致)。

    2026-09-10 P0 修复: 原实现遍历全部 quadrants, 后写的象限覆盖前面的(mkt_concept 在键序
    最后), 导致 index.json 每行实际存的是 mkt_concept 而非 sig_main, 演进弹窗曲线与
    16 象限卡 sig_main 数值对不上。改为显式取 sig_main(单一事实源, §22 一致性)。
    """
    q = snapshot.get("quadrants", {}).get("sig_main", {})
    all_p = q.get("all", {}) if isinstance(q, dict) else {}
    if not isinstance(all_p, dict):
        return {}
    return {m: d for m, d in all_p.items() if isinstance(d, dict)}


def _polluted_ratio(prev_tr, tr) -> float:
    """单日 total_return 相对上一快照日变化比(|Δ|/|prev|)。"""
    if not isinstance(prev_tr, (int, float)) or not isinstance(tr, (int, float)):
        return 0.0
    if prev_tr == 0:
        return 0.0
    return abs(tr - prev_tr) / abs(prev_tr)


def append_to_index(index: dict, snapshot: dict) -> None:
    """把今日快照压成迷你演进行(每模式 all 周期 total_return/n), 去重覆盖同日。

    2026-09-10 P0 修复双件:
    ① 数据源=显式 sig_main 象限(见 _sig_main_all), 不再按 quadrants 键序遍历互相覆盖。
    ② 防污染: 写每 mode 前对比上一快照日同 mode 的 tr, 突变比 > MUTATION_RATIO
       (且非发布日 version 变化) → 该 mode 值置 null + polluted:true, 不写入虚高数字。
       背景: 9/8 accum_nav=1.5 占位残留污染 G/H/I total_return 虚高 ~82%(9/9 da1064998 已修),
       9/8 快照 sig_main 的 G/H/I 已被污染固化; 防污染逻辑保证「重跑脚本不复活污染点」
       (重建 index 时 9/8 G/H/I 自动拦截成 null, 演进曲线无尖峰; A-F/J 正常值保留)。
    """
    day_row = {"d": snapshot["date"], "m": snapshot["max_signal_date"],
               "v": snapshot["version"], "modes": {}}
    for mode, mdata in _sig_main_all(snapshot).items():
        tr = mdata.get("total_return")
        n = mdata.get("n")
        # 防污染: 对比上一快照日同 mode
        prev_row = index.get("days", [])[-1] if index.get("days") else None
        polluted = False
        if isinstance(tr, (int, float)) and prev_row is not None:
            prev_md = prev_row.get("modes", {}).get(mode)
            prev_tr = prev_md.get("tr") if isinstance(prev_md, dict) else None
            version_changed = prev_row.get("v") != snapshot["version"]
            if isinstance(prev_tr, (int, float)) and not version_changed and \
                    _polluted_ratio(prev_tr, tr) > MUTATION_RATIO:
                polluted = True
        if polluted:
            log(f"[防污染] {snapshot['date']} mode={mode} "
                f"total_return={tr:.2f} 相对昨日={prev_tr:.2f} "
                f"突变比>={MUTATION_RATIO:.0%}, 置 null 防虚高 "
                f"(2026-09-10 P0 类 accum_nav 污染防护)")
            day_row["modes"][mode] = {"tr": None, "n": n, "polluted": True}
            continue
        day_row["modes"][mode] = {"tr": tr, "n": n}
    days = index.get("days", [])
    # 去重: 同日覆盖
    for i, row in enumerate(days):
        if row.get("d") == snapshot["date"]:
            days[i] = day_row
            break
    else:
        days.append(day_row)
    days.sort(key=lambda r: r.get("d", ""))
    index["days"] = days
    index["version"] = SNAPSHOT_VERSION
    index["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")


def trading_days_lag(end_date: str, start_date: str) -> int:
    """交易日 lag = len(trading_days_between(start, end)) - 1。无数据返回 -1。"""
    try:
        sys.path.insert(0, str(ROOT))
        from app.calendar import trading_days_between
        days = trading_days_between(start_date, end_date)
        return max(len(days) - 1, 0) if days else -1
    except Exception as e:  # noqa: BLE001
        log(f"交易日计算失败(按自然日退化): {e}")
        try:
            d0 = datetime.strptime(end_date, "%Y%m%d")
            d1 = datetime.strptime(start_date, "%Y%m%d")
            return max((d0 - d1).days - 1, 0)
        except Exception:  # noqa: BLE001
            return -1


def _send_notify(subject: str, body: str, severe: bool, dry_run: bool,
                 dedup_key: str | None = None) -> None:
    import notify
    if dedup_key and not dry_run and notify.check_dedup(dedup_key, DEDUP_WINDOW):
        log(f"[dedup] suppress {dedup_key}(24h 内已告警)")
        return
    res = notify.send(subject, body, severe=severe, dry_run=dry_run)
    if dedup_key and not dry_run:
        ok = res and any(res.values())
        if ok:
            notify.update_dedup(dedup_key)


def detect_posrating_stale(data_dir: Path, index: dict) -> list[dict]:
    """latest_posrating.json 停更检测(#54 方案B: 首页 K 档评级动态源)。

    生成日(latest_posrating.date)落后最新快照日(index.days[-1].d) ≥LAG_ALERT_TD 交易日 → 告警。
    挂载链: s06_snapshot.sh 20:35 尾部 + export 链 build_snapshot 17:50 双点生成;
    任一链停跑数日, date 即停留旧日, 用户侧静默回退静态兜底 86.60%, 必须当场暴露。
    """
    days = index.get("days", [])
    if not days:
        return []
    newest_day = days[-1].get("d", "")
    if not newest_day:
        return []
    p = snap_dir(data_dir) / "latest_posrating.json"
    if not p.exists():
        return [{"type": "posrating_stale",
                 "detail": "latest_posrating.json 缺失(首页 K 档评级回退静态兜底 86.60%)"}]
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [{"type": "posrating_stale", "detail": f"latest_posrating.json 解析失败({exc})"}]
    pr_date = str(doc.get("date") or "").strip()
    if not pr_date:
        return [{"type": "posrating_stale", "detail": "latest_posrating.json 无 date 字段(生成日)"}]
    if pr_date < newest_day:
        lag = trading_days_lag(newest_day, pr_date)
        if lag >= LAG_ALERT_TD:
            return [{"type": "posrating_stale",
                     "detail": f"latest_posrating.json 停更: 生成日={pr_date} "
                               f"落后最新快照日={newest_day} {lag} 个交易日(≥{LAG_ALERT_TD}告警)"}]
    return []


def detect_stagnation(index: dict, today_str: str) -> list[dict]:
    """停滞档: max_signal_date 落后今日 ≥STAGNATION_LAG_ALERT_TD 个交易日。

    阈值比 posrating 停更档(LAG_ALERT_TD=2)宽 1 天: 次日开盘成交口径下, 当天快照的
    max_signal_date 只含"T+1 开盘已发生"的信号, 天然少 1 个交易日; 单日无买系信号
    也会再推后 1 天。故健康 lag 最高到 2, 只有 ≥3(连续 ≥2 交易日无新信号)才算真停滞。
    """
    days = index.get("days", [])
    if not days:
        return []
    newest = days[-1]["m"]
    if not newest:
        return [{"type": "stagnation", "detail": "max_signal_date 为空(产物异常)"}]
    lag = trading_days_lag(today_str, newest)
    if lag >= STAGNATION_LAG_ALERT_TD:
        return [{"type": "stagnation", "detail": f"max_signal_date={newest} "
                f"落后今日{lag}个交易日(≥{STAGNATION_LAG_ALERT_TD}告警)"}]
    return []


def detect_mutation(index: dict) -> list[dict]:
    """突变档: 今日 vs 滚动窗口(近 60 日, 含昨天不含今天)。"""
    days = index.get("days", [])
    if len(days) < 2:
        return []
    latest = days[-1]
    prevs = days[1 - ROLLING_WINDOW - 1:-1]  # 昨天及其前 59 日(不含今天)
    if not prevs:
        return []
    prev1 = prevs[-1]
    prev2 = prevs[-2] if len(prevs) >= 2 else None
    today_modes = latest.get("modes", {})
    alerts = []
    for mode, mdata in today_modes.items():
        today_tr = mdata.get("tr")
        today_n = mdata.get("n") or 0
        if today_tr is None or today_n < MIN_N:
            continue
        wins = [p["modes"][mode]["tr"] for p in prevs
                if isinstance(p.get("modes", {}).get(mode), dict)
                and isinstance(p["modes"][mode].get("tr"), (int, float))]
        if len(wins) < MIN_SAMPLES:
            continue
        mean = statistics.mean(wins)
        if len(wins) >= 2:
            std = statistics.stdev(wins)
        else:
            std = 0.0
        std_jump = std > 0 and abs(today_tr - mean) > MUTATION_STD * std
        day_delta = today_tr - prev1["modes"][mode]["tr"] if isinstance(
            prev1.get("modes", {}).get(mode), dict
        ) and isinstance(prev1["modes"][mode].get("tr"), (int, float)) else 0.0
        # 相对口径(#109 根治): 单日 |Δ| > 窗口均值 × MUTATION_PCT 才叫突变
        # (total_return 单位=元, 不同 mode 量级差异大, 绝对阈值会误伤/漏检)
        pct_threshold = mean * MUTATION_PCT
        if mean < ABS_FLOOR_MEAN:
            # 小模式(百元量级) abs 下限兜底, 防相对阈值过低导致逃逸
            pct_threshold = max(pct_threshold, ABS_FLOOR_DELTA)
        pp_jump = abs(day_delta) > pct_threshold
        dir_confirmed = False
        if prev2 is not None and isinstance(prev2.get("modes", {}).get(mode), dict) \
                and isinstance(prev2["modes"][mode].get("tr"), (int, float)):
            prev_delta = prev1["modes"][mode]["tr"] - prev2["modes"][mode]["tr"]
            dir_threshold = mean * MUTATION_DIR_PCT
            if (day_delta > 0 and prev_delta > dir_threshold) or \
               (day_delta < 0 and prev_delta < -dir_threshold):
                dir_confirmed = True
        # 相对口径组合(#109 根治): 去掉原"std_jump and 单日Δ>半阈值"第三条——该条在
        # 绝对口径下(MUTATION_PP*0.5=10元)对 9000 元量级模式恒触发, 改成相对半阈值后
        # 仍会让"std 大但相对波动正常"(G 今日 5.8σ=4.2% 属正常)误报, 故删除;
        # 只保留两条纯相对口径组合: std 偏离+相对日波幅 双确认 / 相对日波幅+连续两日同向
        if (std_jump and pp_jump) or (pp_jump and dir_confirmed):
            alerts.append({
                "type": "mutation", "mode": mode, "n": today_n,
                "today_tr": round(today_tr, 2), "mean": round(mean, 2),
                "std": round(std, 2) if std else 0,
                "day_delta": round(day_delta, 2),
                "detail": f"[{mode}] 今日 total_return={today_tr:.2f}, "
                          f"窗口均值={mean:.2f}, std={std:.2f}, 单日Δ={day_delta:+.2f}",
            })
    return alerts


def run_check(data_dir: Path, dry_run: bool) -> int:
    index = load_index(data_dir)
    days = index.get("days", [])
    if not days:
        log("index.json 无历史快照, 跳过告警检测")
        return 0
    today_str = datetime.now().strftime("%Y%m%d")
    alerts = []
    alerts += detect_stagnation(index, today_str)
    alerts += detect_posrating_stale(data_dir, index)
    # 发布日豁免: 今日 version != 昨日 version
    prev_ver = index.get("days", [])[-2].get("v") if len(index.get("days", [])) >= 2 else ""
    latest_ver = index.get("days", [])[-1].get("v") if index.get("days", []) else ""
    if prev_ver and latest_ver and prev_ver != latest_ver:
        log("发布日(version 变化), 豁免突变告警")
    else:
        alerts += detect_mutation(index)
    if not alerts:
        log(f"告警检测通过: 最新快照天={days[-1].get('d')} "
            f"max_signal_date={days[-1].get('m')}")
        return 0
    # 多条同 type=mutation 合并为 1 条发送(#109 根因2: G/H/I 各自独立 dedup key
    # 各打各的=一次 3 条轰炸; 合并后标题前缀 mode 列表, detail 逐 mode 列出)
    mutation_alerts = [a for a in alerts if a["type"] == "mutation"]
    other_alerts = [a for a in alerts if a["type"] != "mutation"]
    for a in other_alerts:
        subject = "[告警] 信号凯利回测停滞" if a["type"] in ("stagnation", "posrating_stale") else "[告警] 信号凯利回测指标突变"
        body_lines = [
            subject,
            f"判定档位: {a['type']}",
            a.get("detail", ""),
            f"数据截止日: {days[-1].get('d')} 快照 / max_signal_date={days[-1].get('m')}",
        ]
        if a["type"] == "posrating_stale":
            body_lines.append("影响面提示: latest_posrating.json 为首页 AI仓位建议 K 档评级动态源"
                              "(s06_snapshot.sh 20:35 + export/build_snapshot 17:50 双点生成); "
                              "停更时首页静默回退静态兜底 86.60% 历史数字, 用户无感知, 需及时补跑")
            body_lines.append("补跑: bash scripts/kelly_posrating.py --data-dir <static-site/data> --write")
        body_lines.append("发版豁免: 今日为发布日则本突变告警属预期(已跳过突变检测)。")
        body = "\n".join(body_lines)
        dedup_key = f"sigkelly_snapshot_{a['type']}_{a.get('mode', '')}_{days[-1]['d']}"
        if dry_run:
            log(f"[dry-run] 将发告警: {subject} | {a.get('detail', '')}")
        else:
            _send_notify(subject, body, severe=False,
                         dry_run=dry_run, dedup_key=dedup_key)
    if mutation_alerts:
        modes = "/".join(sorted(a.get("mode", "?") for a in mutation_alerts))
        subject = f"[告警] 信号凯利回测指标突变({modes})"
        body_lines = [subject, "判定档位: mutation"]
        for a in mutation_alerts:
            body_lines.append(a.get("detail", ""))
        body_lines.append(f"数据截止日: {days[-1].get('d')} 快照 / max_signal_date={days[-1].get('m')}")
        n_str = ", ".join(f"{a.get('mode')}={a.get('n')}" for a in mutation_alerts)
        body_lines.append(f"样本数 {n_str} (门 ≥{MIN_N})")
        body_lines.append("影响面提示: 回测 total_return 突变可能源于价格库数据缺口"
                          "(如 accum_nav 未补致信号跳单) 或真实市场风格切换, "
                          "建议查 check_data_integrity 信号滞后告警 + 最近 3 日成交明细。")
        body_lines.append("发版豁免: 今日为发布日则本突变告警属预期(已跳过突变检测)。")
        body = "\n".join(body_lines)
        # dedup key 不按 mode 拆分: 跨 mode 合并后只留 date 级 key, 防 24h 内重复轰炸
        dedup_key = f"sigkelly_snapshot_mutation_{days[-1]['d']}"
        if dry_run:
            log(f"[dry-run] 将发告警: {subject} | 合并 {len(mutation_alerts)} 条 mode [{modes}]")
        else:
            _send_notify(subject, body, severe=True,
                         dry_run=dry_run, dedup_key=dedup_key)
    return 1


def rebuild_index(data_dir: Path, dry_run: bool = False) -> tuple[int, int]:
    """从快照目录全量重建 index.json(2026-09-10 P0 修复配套)。

    场景:  append_to_index 曾有覆盖 bug(写 mkt_concept 而非 sig_main) + 9/8 快照
    G/H/I 被 accum_nav 污染固化, 历史 index 行需按修复后口径(sig_main 显式取 +
    MUTATION_RATIO 防污染)一次性重建。逐日有序 append(index 里 prev_row 为实际前一天),
    防污染逻辑自动把 9/8 的 G/H/I 置 null(polluted:true), A-F/J 正常值保留。
    返回 (写入行数, 防污染拦截 mode 数)。
    """
    sd = snap_dir(data_dir)
    dates = sorted(p.stem for p in sd.glob("20*.json")
                   if p.stem not in ("latest_posrating", "index"))
    index = {"version": SNAPSHOT_VERSION, "updated_at": "", "days": []}
    blocked = 0
    for d in dates:
        p = sd / f"{d}.json"
        try:
            snap = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            log(f"[rebuild] {d}.json 读取失败(跳过): {exc}")
            continue
        if not isinstance(snap, dict) or not snap.get("quadrants"):
            log(f"[rebuild] {d}.json 无 quadrants(跳过, 疑似残缺产物)")
            continue
        # 用 append_to_index 逐日有序重建(防污染逻辑随附); 返回前计数拦截
        before = sum(1 for row in index.get("days", []) for md in row.get("modes", {}).values()
                     if md.get("polluted"))
        append_to_index(index, snap)
        after = sum(1 for row in index.get("days", []) for md in row.get("modes", {}).values()
                    if md.get("polluted"))
        blocked += after - before
    index["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    if not dry_run:
        save_index(data_dir, index)
    print(f"[sigkelly_snapshot] rebuild: {len(dates)} 快照日 → {len(index['days'])} index 行, "
          f"防污染拦截 {blocked} 个 mode", flush=True)
    return len(index["days"]), blocked


def _main() -> int:
    ap = argparse.ArgumentParser(description="信号凯利回测快照/演进/告警")
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR),
                    help="回测产物所在 data 目录(默认 static-site/data)")
    ap.add_argument("--check", action="store_true",
                    help="只读告警检测模式(读 index.json, 不生成快照)")
    ap.add_argument("--rebuild", action="store_true",
                    help="从快照目录全量重建 index.json(2026-09-10 P0 修复配套)")
    ap.add_argument("--dry-run", action="store_true", help="不写文件/不发通知")
    args = ap.parse_args()
    data_dir = _resolve_ro_frame(args.data_dir)
    if args.check:
        return run_check(data_dir, args.dry_run)
    if args.rebuild:
        rebuild_index(data_dir, args.dry_run)
        return 0
    index = load_index(data_dir)
    snapshot = build_snapshot(data_dir)
    if args.dry_run:
        log(f"[dry-run] 快照 date={snapshot['date']} "
            f"max_signal_date={snapshot['max_signal_date']} "
            f"quadrants={len(snapshot['quadrants'])}")
        return 0
    prev_max = index["days"][-1]["m"] if index["days"] else ""
    # 回测失败门(回退): max_signal_date 比昨日倒退 → SEVERE
    if prev_max and snapshot["max_signal_date"] and snapshot["max_signal_date"] < prev_max:
        subject = "[告警] 信号凯利回测 max_signal_date 倒退"
        body = (f"{subject}\n判定档位: 回测失败门(SEVERE)\n"
                f"昨日 {prev_max} → 今日 {snapshot['max_signal_date']}\n"
                f"回测产物可能损坏/数据源缺日, 建议查 export 日志与 accum_nav。")
        if not args.dry_run:
            _send_notify(subject, body, severe=True, dry_run=False,
                         dedup_key=f"sigkelly_snapshot_regress_{snapshot['date']}")
    save_snapshot(data_dir, snapshot)
    append_to_index(index, snapshot)
    save_index(data_dir, index)
    log(f"快照已生成: {snap_dir(data_dir) / (snapshot['date'] + '.json')}")
    log(f"index 共 {len(index['days'])} 个快照日, max_signal_date={snapshot['max_signal_date']}")
    return 0


def main() -> int:
    """入口。退出码语义(供调用方/backfill_metrics.sh 区分):
        0 = --check 无告警 / 快照生成成功
        1 = --check 检测到预期告警(停滞/突变, 正常路径, 非脚本错误)
        2 = 脚本异常(非预期崩溃, 如产物缺失/读取失败), 与"有告警"区分
    """
    try:
        return _main()
    except Exception as _e:  # noqa: BLE001
        log(f"脚本异常(非预期, 退出码 2): {_e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())