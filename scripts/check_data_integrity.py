#!/usr/bin/env python3
"""check_data_integrity.py - 数据产物校验脚本

校验 static-site/data/ + data/ 下的关键 JSON 产物，拦截 4 类线上事故：
1. board_etf_map 空数组占比过高（"全部无 ETF"事故，etf_index_map.json 丢失致 broad 指数全空）
2. boot.json 嵌的 overview.date 与 overview.json.date 不一致（"成交额显示昨日值"事故）
3. intraday_snapshot amount_forecast 异常爆炸（"9.52 万亿/15 万亿"事故）
4. 关键文件不存在（etf_index_map.json 丢了 / boot.json 丢了 等）

用法:
  python scripts/check_data_integrity.py                     # 全量校验
  python scripts/check_data_integrity.py --file PATH         # 单文件校验
  python scripts/check_data_integrity.py --strict            # warn 当 fail
  python scripts/check_data_integrity.py --deploy-mode       # deploy 接入(非 0 退出阻断)
  python scripts/check_data_integrity.py --data-dir DIR      # 指定 static-site/data/ 路径

退出码:
  0 = 全通过(含 warn)
  1 = 有 fail
  2 = 有 warn 且 --strict（手动排查用；--deploy-mode 不因 warn 阻断）

deploy.sh 接入(L105 后):
  "$PY" "$REPO/scripts/check_data_integrity.py" --deploy-mode --data-dir "$REPO/static-site/data"
  rc=$?; [ $rc -ne 0 ] && exit $rc
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ── 阈值常量 ──────────────────────────────────────────────────────────────────
BOARD_ETF_EMPTY_FAIL_RATIO = 0.80   # 空数组占比 >=80% = FAIL（近全空，事故级）
BOARD_ETF_EMPTY_WARN_RATIO = 0.30   # >=30% = WARN（broad 指数全空，etf_index_map 缺失级）
AMOUNT_FORECAST_FAIL = 50000        # amount_forecast > 50000 亿 = FAIL（9.52 万亿/15 万亿事故）
STALE_DAYS_WARN = 3                 # date 滞后 >3 天 = WARN（日频数据可能停更）
STALE_DAYS_FAIL = 7                 # date 滞后 >7 天 = FAIL

# track_score 三版本一致性容差（防 159335 类三版本不一致事故，§22 数据一致性铁律）
# board_etf_map vs overview signal vs index detail 三处同 ETF track_score 容差 ±1.0
# 超容差 = 不同 build 产物混用，>=2 指数不一致 = FAIL
TRACK_SCORE_TOLERANCE = 1.0
# etf_since_return 非 null 占比阈值（走势卡 ETF 至今盈亏注入失败拦截）
ETF_SINCE_RETURN_FAIL_RATIO = 0.90  # <90% = FAIL（后端注入失败）
ETF_SINCE_RETURN_WARN_RATIO = 0.95  # <95% = WARN

# 关键文件清单（存在性校验）
# static-site/data/ 下的部署产物 + data/ 下的构建依赖
KEY_FILES_STATIC = [
    "overview.json",
    "boot.json",
    "intraday_snapshot.json",
    "alert.json",
    "notifications.json",
    "schedule_stats.json",
    "fund_score.json",
    "ad_line.json",
    "a-stock-1y.json",
    "summary.json",
]
KEY_FILES_REPO_DATA = [
    "board_etf_map.json",
    "etf_index_map.json",
]

# broad 市场指数（board_etf_map 中应有 ETF 的关键指数）
BROAD_INDICES = ["sh", "sz", "sz50", "hs300", "csi500", "csi1000", "kc50", "cyb"]


# ── 工具函数 ──────────────────────────────────────────────────────────────────
def _load_json(path: Path) -> tuple[object, str | None]:
    """安全加载 JSON，返回 (data, error_msg)。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, f"文件不存在: {path}"
    except json.JSONDecodeError as e:
        return None, f"JSON 解析失败: {path}: {e}"
    except Exception as e:
        return None, f"读取失败: {path}: {type(e).__name__}: {e}"


def _today_str() -> str:
    """返回 YYYYMMDD 格式的今日日期（北京时间）。"""
    # datetime.now() 在本地 macOS 上是 CST，直接用
    return datetime.now().strftime("%Y%m%d")


def _days_ago(date_str: str) -> int | None:
    """解析 YYYYMMDD 日期字符串，返回距今天的天数（今日=0）。解析失败返回 None。"""
    try:
        d = datetime.strptime(date_str.strip(), "%Y%m%d")
        return (datetime.now() - d).days
    except (ValueError, AttributeError):
        return None


def _get_nested(d: dict, *keys, default=None):
    """安全嵌套取值。"""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
    return cur


# ── 校验结果 ──────────────────────────────────────────────────────────────────
class CheckResult:
    """单个校验函数的返回结果。"""
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"

    def __init__(self, name: str, status: str, msg: str = "", detail: str = ""):
        self.name = name
        self.status = status
        self.msg = msg
        self.detail = detail

    def __repr__(self):
        return f"CheckResult({self.name!r}, {self.status!r}, {self.msg!r})"


def _ok(name: str, msg: str = "") -> CheckResult:
    return CheckResult(name, CheckResult.OK, msg)


def _warn(name: str, msg: str) -> CheckResult:
    return CheckResult(name, CheckResult.WARN, msg)


def _fail(name: str, msg: str) -> CheckResult:
    return CheckResult(name, CheckResult.FAIL, msg)


# ── 11 个校验函数 ─────────────────────────────────────────────────────────────

def check_board_etf_map(repo_data_dir: Path) -> CheckResult:
    """校验 board_etf_map.json：空数组占比（"全部无 ETF"事故拦截）。

    事故场景：etf_index_map.json 丢失 -> build_board_etf_map.py 无法自动采集 ->
    broad 指数(sh/sz/sz50/hs300...)全空 -> 空数组占比飙到 37%+。

    阈值：
    - >=80% 空 = FAIL（近全空，事故级）
    - >=30% 空 = WARN（broad 指数全空，etf_index_map 缺失级）
    """
    name = "board_etf_map"
    path = repo_data_dir / "board_etf_map.json"
    data, err = _load_json(path)
    if err:
        return _fail(name, err)

    if not isinstance(data, dict):
        return _fail(name, f"board_etf_map.json 不是 dict: {type(data).__name__}")

    # 排除 _meta 等非指数键
    index_keys = [k for k in data if not k.startswith("_")]
    if not index_keys:
        return _fail(name, "board_etf_map.json 无指数条目（仅 _meta）")

    empty_count = sum(1 for k in index_keys if not data[k])
    ratio = empty_count / len(index_keys)

    # broad 指数全空检查
    broad_empty = [k for k in BROAD_INDICES if k in data and not data[k]]
    broad_present = [k for k in BROAD_INDICES if k in data]

    if ratio >= BOARD_ETF_EMPTY_FAIL_RATIO:
        return _fail(name, f"空数组占比 {ratio:.1%} ({empty_count}/{len(index_keys)}) >= "
                      f"{BOARD_ETF_EMPTY_FAIL_RATIO:.0%}，近全空（事故级）")
    # broad 核心宽基指数全空 = FAIL（2026-08-06 升级：原仅 WARN 不阻断致 14 宽基全空事故上线）。
    # 事故根因：etf_index_map.json 缺失 -> build_board_etf_map.py 静默退化全空 -> broad 8 指数全空。
    # 现升级 FAIL 让 --deploy-mode 阻断 deploy，防静默覆盖线上 map。
    if broad_empty and len(broad_empty) == len(broad_present):
        return _fail(name, f"broad 核心宽基指数全空 {broad_empty}（{len(broad_empty)}/{len(broad_present)}"
                      f" present），etf_index_map.json 缺失或 build_board_etf_map.py 兜底失败")
    if ratio >= BOARD_ETF_EMPTY_WARN_RATIO:
        return _warn(name, f"空数组占比 {ratio:.1%} ({empty_count}/{len(index_keys)}) >= "
                     f"{BOARD_ETF_EMPTY_WARN_RATIO:.0%}")

    return _ok(name, f"空数组占比 {ratio:.1%} ({empty_count}/{len(index_keys)})")


def check_overview(data_dir: Path) -> CheckResult:
    """校验 overview.json：date 字段是今日（或最近交易日）。"""
    name = "overview"
    path = data_dir / "overview.json"
    data, err = _load_json(path)
    if err:
        return _fail(name, err)
    if not isinstance(data, dict):
        return _fail(name, f"overview.json 不是 dict: {type(data).__name__}")

    date_str = data.get("date")
    if not date_str:
        return _fail(name, "overview.json 无 date 字段")

    days = _days_ago(date_str)
    if days is None:
        return _fail(name, f"overview.json date 格式异常: {date_str}")
    if days > STALE_DAYS_FAIL:
        return _fail(name, f"overview.json date={date_str} 滞后 {days} 天 > {STALE_DAYS_FAIL} 天")
    if days > STALE_DAYS_WARN:
        return _warn(name, f"overview.json date={date_str} 滞后 {days} 天 > {STALE_DAYS_WARN} 天")

    return _ok(name, f"date={date_str} (滞后 {days} 天)")


def check_boot(data_dir: Path) -> CheckResult:
    """校验 boot.json：overview.date 与 overview.json.date 一致（"成交额显示昨日值"事故拦截）。

    事故场景：boot.json 盘中不重新生成 -> 嵌的 overview 是昨夜旧版 ->
    前端 fetchBoot 缓存旧 overview -> 成交额卡显示昨日值。
    """
    name = "boot"
    path = data_dir / "boot.json"
    data, err = _load_json(path)
    if err:
        return _fail(name, err)
    if not isinstance(data, dict):
        return _fail(name, f"boot.json 不是 dict: {type(data).__name__}")

    # boot.json 的 overview.date
    boot_overview = data.get("overview")
    if not isinstance(boot_overview, dict):
        return _fail(name, "boot.json 无 overview 字段或不是 dict")
    boot_date = boot_overview.get("date")
    if not boot_date:
        return _fail(name, "boot.json overview 无 date 字段")

    # overview.json 的 date
    ov_path = data_dir / "overview.json"
    ov_data, ov_err = _load_json(ov_path)
    if ov_err:
        return _fail(name, f"无法读取 overview.json 做比对: {ov_err}")
    ov_date = ov_data.get("date") if isinstance(ov_data, dict) else None
    if not ov_date:
        return _fail(name, "overview.json 无 date 字段，无法比对")

    if boot_date != ov_date:
        return _fail(name, f"boot.overview.date={boot_date} != overview.json.date={ov_date}"
                     f"（boot.json 嵌旧版 overview，成交额卡会显示昨日值）")

    # generated_at 检查（WARN 级）
    generated_at = _get_nested(data, "_meta", "generated_at", default="")
    return _ok(name, f"boot.overview.date={boot_date} == overview.date={ov_date}"
               f"{f', generated_at={generated_at}' if generated_at else ''}")


def check_intraday_fresh(data_dir: Path) -> CheckResult:
    """校验 intraday_snapshot.json：amount_forecast 不爆炸（"9.52 万亿/15 万亿"事故拦截）。

    事故场景：预估算法 bug -> amount_forecast 算出 95200 亿(9.52 万亿)或 150000 亿(15 万亿)。
    正常 A 股全天成交额 0.5-3 万亿，盘中预估 >5 万亿必为 bug。
    """
    name = "intraday_fresh"
    path = data_dir / "intraday_snapshot.json"
    data, err = _load_json(path)
    if err:
        return _fail(name, err)
    if not isinstance(data, dict):
        return _fail(name, f"intraday_snapshot.json 不是 dict: {type(data).__name__}")

    amount_forecast = data.get("amount_forecast")
    if amount_forecast is None:
        # 盘后收盘轮可能无 amount_forecast，不算 fail
        is_closed = data.get("is_closed")
        if is_closed:
            return _ok(name, "盘后 is_closed=True，无 amount_forecast（正常）")
        return _warn(name, "盘中 is_closed=False 但无 amount_forecast 字段")

    try:
        af = float(amount_forecast)
    except (ValueError, TypeError):
        return _fail(name, f"amount_forecast 不是数字: {amount_forecast!r}")

    if af > AMOUNT_FORECAST_FAIL:
        return _fail(name, f"amount_forecast={af:.2f} 亿 > {AMOUNT_FORECAST_FAIL} 亿"
                     f"（异常爆炸，9.52 万亿/15 万亿事故）")

    collected_at = data.get("collected_at", "")
    return _ok(name, f"amount_forecast={af:.2f} 亿, collected_at={collected_at}")


def check_alert(data_dir: Path) -> CheckResult:
    """校验 alert.json：date 字段存在且不太旧。"""
    name = "alert"
    path = data_dir / "alert.json"
    data, err = _load_json(path)
    if err:
        return _fail(name, err)
    if not isinstance(data, dict):
        return _fail(name, f"alert.json 不是 dict: {type(data).__name__}")

    date_str = data.get("date")
    if not date_str:
        return _fail(name, "alert.json 无 date 字段")

    # alert 是盘后日频，允许滞后 1 天（盘前 alert 还是昨日盘后的）
    days = _days_ago(date_str)
    if days is None:
        return _warn(name, f"alert.json date 格式异常: {date_str}")
    if days > STALE_DAYS_FAIL:
        return _fail(name, f"alert.json date={date_str} 滞后 {days} 天 > {STALE_DAYS_FAIL} 天")
    if days > STALE_DAYS_WARN + 1:  # alert 允许多 1 天
        return _warn(name, f"alert.json date={date_str} 滞后 {days} 天")

    return _ok(name, f"date={date_str} (滞后 {days} 天)")


def check_notifications(data_dir: Path) -> CheckResult:
    """校验 notifications.json：date 字段存在且是今日。"""
    name = "notifications"
    path = data_dir / "notifications.json"
    data, err = _load_json(path)
    if err:
        return _fail(name, err)
    if not isinstance(data, dict):
        return _fail(name, f"notifications.json 不是 dict: {type(data).__name__}")

    date_str = data.get("date")
    if not date_str:
        return _fail(name, "notifications.json 无 date 字段")

    days = _days_ago(date_str)
    if days is None:
        return _fail(name, f"notifications.json date 格式异常: {date_str}")
    if days > STALE_DAYS_FAIL:
        return _fail(name, f"notifications.json date={date_str} 滞后 {days} 天 > {STALE_DAYS_FAIL} 天")
    if days > 1:
        return _warn(name, f"notifications.json date={date_str} 滞后 {days} 天")

    return _ok(name, f"date={date_str} (滞后 {days} 天)")


def check_schedule_stats(data_dir: Path) -> CheckResult:
    """校验 schedule_stats.json：是 list 且非空，每项有 task/last_run 字段。"""
    name = "schedule_stats"
    path = data_dir / "schedule_stats.json"
    data, err = _load_json(path)
    if err:
        return _fail(name, err)
    if not isinstance(data, list):
        return _fail(name, f"schedule_stats.json 不是 list: {type(data).__name__}")
    if not data:
        return _fail(name, "schedule_stats.json 是空 list")

    required_keys = {"task", "last_run", "last_exit"}
    missing = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            missing.append(f"item[{i}] 不是 dict")
            continue
        if not required_keys.issubset(item.keys()):
            missing.append(f"item[{i}] 缺字段: {required_keys - set(item.keys())}")
    if missing:
        return _warn(name, f"部分条目字段缺失: {'; '.join(missing[:3])}")

    return _ok(name, f"{len(data)} 个任务条目")


def check_fund_score(data_dir: Path) -> CheckResult:
    """校验 fund_score.json：date 存在且 count > 0。"""
    name = "fund_score"
    path = data_dir / "fund_score.json"
    data, err = _load_json(path)
    if err:
        return _fail(name, err)
    if not isinstance(data, dict):
        return _fail(name, f"fund_score.json 不是 dict: {type(data).__name__}")

    date_str = data.get("date")
    if not date_str:
        return _fail(name, "fund_score.json 无 date 字段")

    days = _days_ago(date_str)
    if days is None:
        return _warn(name, f"fund_score.json date 格式异常: {date_str}")
    if days > STALE_DAYS_FAIL:
        return _fail(name, f"fund_score.json date={date_str} 滞后 {days} 天 > {STALE_DAYS_FAIL} 天")
    if days > STALE_DAYS_WARN:
        return _warn(name, f"fund_score.json date={date_str} 滞后 {days} 天（日频数据）")

    count = data.get("count", 0)
    if not count or count <= 0:
        return _warn(name, f"fund_score.json count={count}（无基金数据）")

    return _ok(name, f"date={date_str}, count={count} (滞后 {days} 天)")


def check_ad_line(data_dir: Path) -> CheckResult:
    """校验 ad_line.json：data list 非空，最后日期不太旧。"""
    name = "ad_line"
    path = data_dir / "ad_line.json"
    data, err = _load_json(path)
    if err:
        return _fail(name, err)
    if not isinstance(data, dict):
        return _fail(name, f"ad_line.json 不是 dict: {type(data).__name__}")

    data_list = data.get("data")
    if not isinstance(data_list, list) or not data_list:
        return _fail(name, "ad_line.json 无 data list 或为空")

    last = data_list[-1]
    if not isinstance(last, dict):
        return _warn(name, f"ad_line.json data[-1] 不是 dict: {type(last).__name__}")

    date_str = last.get("date", "")
    days = _days_ago(date_str)
    if days is None:
        return _warn(name, f"ad_line.json 最后日期格式异常: {date_str}")
    if days > STALE_DAYS_FAIL:
        return _fail(name, f"ad_line.json 最后日期={date_str} 滞后 {days} 天 > {STALE_DAYS_FAIL} 天")
    if days > STALE_DAYS_WARN:
        return _warn(name, f"ad_line.json 最后日期={date_str} 滞后 {days} 天（日频盘后数据）")

    return _ok(name, f"{len(data_list)} 条, 最后={date_str} (滞后 {days} 天)")


def check_a_stock(data_dir: Path) -> CheckResult:
    """校验 a-stock-1y.json：有 metrics + indices 结构。"""
    name = "a_stock"
    path = data_dir / "a-stock-1y.json"
    data, err = _load_json(path)
    if err:
        return _fail(name, err)
    if not isinstance(data, dict):
        return _fail(name, f"a-stock-1y.json 不是 dict: {type(data).__name__}")

    metrics = data.get("metrics")
    indices = data.get("indices")
    if not isinstance(metrics, dict):
        return _fail(name, "a-stock-1y.json 无 metrics dict")
    if not isinstance(indices, dict):
        return _fail(name, "a-stock-1y.json 无 indices dict")

    # 检查 a_amount 的最后日期
    a_amount = metrics.get("a_amount")
    if isinstance(a_amount, dict) and isinstance(a_amount.get("data"), list) and a_amount["data"]:
        last_date = a_amount["data"][-1].get("date", "") if isinstance(a_amount["data"][-1], dict) else ""
        days = _days_ago(last_date)
        if days is not None and days > STALE_DAYS_FAIL:
            return _fail(name, f"a_amount 最后日期={last_date} 滞后 {days} 天 > {STALE_DAYS_FAIL} 天")
        if days is not None and days > STALE_DAYS_WARN:
            return _warn(name, f"a_amount 最后日期={last_date} 滞后 {days} 天")

    return _ok(name, f"metrics={len(metrics)} 项, indices={len(indices)} 项")


def check_etf_index_map(repo_data_dir: Path) -> CheckResult:
    """校验 etf_index_map.json：文件存在（build_board_etf_map.py 的数据源）。

    事故场景：etf_index_map.json 丢失 -> build_board_etf_map.py 无法自动采集 ->
    broad 指数 ETF 全空 -> 前端 ETF 联动 tag 不渲染。
    """
    name = "etf_index_map"
    path = repo_data_dir / "etf_index_map.json"
    if not path.exists():
        return _warn(name, f"etf_index_map.json 不存在: {path}（broad 指数 ETF 会全空，"
                     f"build_board_etf_map.py 退化为关键词匹配）")

    data, err = _load_json(path)
    if err:
        return _warn(name, err)
    if isinstance(data, list):
        return _ok(name, f"{len(data)} 只 ETF")
    if isinstance(data, dict):
        return _ok(name, f"{len(data)} 条 ETF 映射")
    return _warn(name, f"etf_index_map.json 结构异常: {type(data).__name__}")


def check_signal_kelly_backtest(data_dir: Path) -> CheckResult:
    """校验 signal_kelly_backtest.json：6象限×5周期×4模式=120组合完整。

    事故场景：脚本异常/ETF价格缺失 -> quadrants 为空或组合不完整 -> 前端 lab tab 全空。
    """
    name = "signal_kelly_backtest"
    path = data_dir / "signal_kelly_backtest.json"
    data, err = _load_json(path)
    if err:
        return _warn(name, err)  # 首次部署前文件不存在，WARN 不阻断
    if not isinstance(data, dict):
        return _fail(name, f"signal_kelly_backtest.json 不是 dict: {type(data).__name__}")

    quadrants = data.get("quadrants")
    if not isinstance(quadrants, dict):
        return _fail(name, "无 quadrants 字段或不是 dict")

    expected_quads = {"rating_high", "rating_mid", "rating_low",
                      "etf_strong", "etf_related", "etf_approx"}
    missing = expected_quads - set(quadrants.keys())
    if missing:
        return _fail(name, f"缺少象限: {missing}")

    # 验证 6×5×4=120 组合完整 + 非零象限有样本
    total_n = 0
    empty_quads = []
    for qk, qv in quadrants.items():
        if not isinstance(qv, dict) or "periods" not in qv:
            return _fail(name, f"象限 {qk} 结构异常")
        periods = qv["periods"]
        if not isinstance(periods, dict) or set(periods.keys()) != {"y1", "y3", "y5", "y10", "all"}:
            return _fail(name, f"象限 {qk} 周期不完整: {set(periods.keys()) if isinstance(periods, dict) else 'N/A'}")
        for pk, pv in periods.items():
            if not isinstance(pv, dict) or set(pv.keys()) != {"A", "B", "C", "D"}:
                return _fail(name, f"象限 {qk} 周期 {pk} 模式不完整")
            for mk, mv in pv.items():
                if isinstance(mv, dict) and "n" in mv:
                    total_n += mv["n"]
        # all 周期 A 模式样本数
        n_all_a = _get_nested(qv, "periods", "all", "A", "n", default=0)
        if n_all_a == 0:
            empty_quads.append(qk)

    if total_n == 0:
        return _fail(name, "所有象限所有组合样本数=0（脚本异常或数据缺失）")

    msg = f"120组合完整, all/A 总样本={total_n}"
    if empty_quads:
        msg += f", 零样本象限: {empty_quads}"
    return _ok(name, msg)


def check_trade_sim_indices(data_dir: Path) -> CheckResult:
    """校验 trade_sim_indices.json：存在 + 非滞后（trade_sim JSON 无调度致滞后拦截）。

    事故场景：simulate_trade --all 无自动调度 -> trade_sim JSON 停在旧日期 ->
    前端走势卡/策略实验室读旧回测数据。文件内容是 index_id 字符串列表无 date 字段，
    用文件 mtime 判断滞后。
    """
    name = "trade_sim_indices"
    path = data_dir / "trade_sim_indices.json"
    data, err = _load_json(path)
    if err:
        return _fail(name, err)
    if not isinstance(data, list):
        return _fail(name, f"trade_sim_indices.json 不是 list: {type(data).__name__}")
    if not data:
        return _fail(name, "trade_sim_indices.json 是空 list（无回测品种）")

    # mtime 滞后校验（list 内容是 index_id 字符串，无 date 字段，用文件 mtime）
    try:
        mtime_dt = datetime.fromtimestamp(path.stat().st_mtime)
        days = (datetime.now() - mtime_dt).days
    except OSError as e:
        return _warn(name, f"无法读取文件 mtime: {e}")
    if days > STALE_DAYS_FAIL:
        return _fail(name, f"trade_sim_indices.json mtime 滞后 {days} 天 > {STALE_DAYS_FAIL} 天"
                     f"（trade_sim JSON 无调度，回测数据过期）")
    if days > STALE_DAYS_WARN:
        return _warn(name, f"trade_sim_indices.json mtime 滞后 {days} 天 > {STALE_DAYS_WARN} 天")
    return _ok(name, f"{len(data)} 个品种, mtime 滞后 {days} 天")


def check_etf_since_return(data_dir: Path) -> CheckResult:
    """校验 overview.json signals_today etfs 的 etf_since_return 非 null 占比。

    事故场景：后端注入失败 -> 走势卡 ETF 至今盈亏全 null。
    """
    name = "etf_since_return"
    path = data_dir / "overview.json"
    data, err = _load_json(path)
    if err:
        return _fail(name, err)
    if not isinstance(data, dict):
        return _fail(name, f"overview.json 不是 dict: {type(data).__name__}")

    signals = data.get("signals_today")
    if not isinstance(signals, list):
        return _warn(name, "overview.json 无 signals_today list")

    total = 0
    nonnull = 0
    for s in signals:
        if not isinstance(s, dict):
            continue
        etfs = s.get("etfs")
        if not isinstance(etfs, list):
            continue
        for e in etfs:
            if isinstance(e, dict) and e.get("code"):
                total += 1
                if e.get("etf_since_return") is not None:
                    nonnull += 1

    if total == 0:
        return _warn(name, "signals_today 中无 ETF 条目（无法计算占比）")

    ratio = nonnull / total
    if ratio < ETF_SINCE_RETURN_FAIL_RATIO:
        return _fail(name, f"etf_since_return 非 null 占比 {ratio:.1%} ({nonnull}/{total}) < "
                     f"{ETF_SINCE_RETURN_FAIL_RATIO:.0%}（后端注入失败，走势卡 ETF 至今盈亏全 null）")
    if ratio < ETF_SINCE_RETURN_WARN_RATIO:
        return _warn(name, f"etf_since_return 非 null 占比 {ratio:.1%} ({nonnull}/{total}) < "
                     f"{ETF_SINCE_RETURN_WARN_RATIO:.0%}")
    return _ok(name, f"非 null 占比 {ratio:.1%} ({nonnull}/{total})")


def check_track_score_consistency(data_dir: Path, repo_data_dir: Path) -> CheckResult:
    """校验 track_score 三版本一致性：board_etf_map vs overview signal vs index detail。

    事故场景：overview 用旧 board_etf_map 致 track_score 不一致（159335 三版本不一致事故，
    §22 数据一致性铁律）。三处同 ETF track_score 容差 ±TRACK_SCORE_TOLERANCE，超容差 = 不同
    build 产物混用。5 个样本指数中 >=2 不一致 = FAIL，>=1 = WARN。
    """
    name = "track_score_consistency"
    # 1. board_etf_map.json
    bmap, err = _load_json(repo_data_dir / "board_etf_map.json")
    if err:
        return _fail(name, f"无法读 board_etf_map: {err}")
    if not isinstance(bmap, dict):
        return _fail(name, f"board_etf_map.json 不是 dict: {type(bmap).__name__}")

    # 2. overview.json -> index_id -> {code: track_score}
    ov, ov_err = _load_json(data_dir / "overview.json")
    ov_scores: dict[str, dict[str, float]] = {}
    if not ov_err and isinstance(ov, dict):
        for s in ov.get("signals_today") or []:
            if not isinstance(s, dict):
                continue
            idx = s.get("index_id")
            etfs = s.get("etfs")
            if not idx or not isinstance(etfs, list):
                continue
            m = ov_scores.setdefault(idx, {})
            for e in etfs:
                if isinstance(e, dict) and e.get("code") and e.get("track_score") is not None:
                    try:
                        m[e["code"]] = float(e["track_score"])
                    except (TypeError, ValueError):
                        pass

    # 选 5 个有 ETF 的指数（broad 优先）
    sample_indices = []
    candidate_keys = BROAD_INDICES + [k for k in bmap
                                      if k not in BROAD_INDICES and not k.startswith("_")]
    for idx in candidate_keys:
        if len(sample_indices) >= 5:
            break
        etfs = bmap.get(idx)
        if not (isinstance(etfs, list) and etfs and isinstance(etfs[0], dict)
                and etfs[0].get("code")):
            continue
        ts = etfs[0].get("track_score")
        if ts is None:
            continue
        try:
            sample_indices.append((idx, etfs[0]["code"], float(ts)))
        except (TypeError, ValueError):
            pass

    if not sample_indices:
        return _warn(name, "board_etf_map 中无可用 top1 ETF track_score（无法比对）")

    inconsistent = []
    for idx, code, bmap_score in sample_indices:
        scores = [bmap_score]
        # overview signal
        if code in ov_scores.get(idx, {}):
            scores.append(ov_scores[idx][code])
        # index detail
        detail_path = data_dir / "index" / f"{idx}-all.json"
        detail, d_err = _load_json(detail_path)
        if not d_err and isinstance(detail, dict):
            for e in detail.get("etfs") or []:
                if isinstance(e, dict) and e.get("code") == code and e.get("track_score") is not None:
                    try:
                        scores.append(float(e["track_score"]))
                    except (TypeError, ValueError):
                        pass
                    break
        diff = max(scores) - min(scores)
        if diff > TRACK_SCORE_TOLERANCE:
            inconsistent.append((idx, code, scores, round(diff, 2)))

    if len(inconsistent) >= 2:
        detail = "; ".join(f"{i}/{c} scores={s} diff={d}" for i, c, s, d in inconsistent)
        return _fail(name, f"{len(inconsistent)} 个指数 track_score 三版本不一致"
                     f"(容差±{TRACK_SCORE_TOLERANCE}): {detail}")
    if len(inconsistent) == 1:
        idx, code, scores, diff = inconsistent[0]
        return _warn(name, f"{idx}/{code} track_score 不一致 scores={scores} diff={diff}"
                     f" (容差±{TRACK_SCORE_TOLERANCE})")
    return _ok(name, f"{len(sample_indices)} 个指数 top1 ETF track_score 三版本一致"
               f"(容差±{TRACK_SCORE_TOLERANCE})")


# ── 关键文件存在性校验 ────────────────────────────────────────────────────────

def check_key_files(data_dir: Path, repo_data_dir: Path) -> list[CheckResult]:
    """校验关键文件存在性（4 类事故拦截 #4）。"""
    results = []
    for fname in KEY_FILES_STATIC:
        path = data_dir / fname
        if not path.exists():
            results.append(_fail(f"file_exists:{fname}", f"关键文件不存在: {path}"))
        else:
            results.append(_ok(f"file_exists:{fname}", fname))
    for fname in KEY_FILES_REPO_DATA:
        path = repo_data_dir / fname
        if not path.exists():
            # etf_index_map.json 缺失是 WARN（构建依赖，非部署产物）
            if fname == "etf_index_map.json":
                results.append(_warn(f"file_exists:{fname}", f"构建依赖文件不存在: {path}"))
            else:
                results.append(_fail(f"file_exists:{fname}", f"关键文件不存在: {path}"))
        else:
            results.append(_ok(f"file_exists:{fname}", fname))
    return results


# ── 全量校验编排 ──────────────────────────────────────────────────────────────

def run_all_checks(data_dir: Path, repo_data_dir: Path) -> list[CheckResult]:
    """运行全部 14 个校验函数 + 关键文件存在性校验。"""
    results = []

    # 14 个校验函数
    results.append(check_board_etf_map(repo_data_dir))
    results.append(check_overview(data_dir))
    results.append(check_boot(data_dir))
    results.append(check_intraday_fresh(data_dir))
    results.append(check_alert(data_dir))
    results.append(check_notifications(data_dir))
    results.append(check_schedule_stats(data_dir))
    results.append(check_fund_score(data_dir))
    results.append(check_ad_line(data_dir))
    results.append(check_a_stock(data_dir))
    results.append(check_etf_index_map(repo_data_dir))
    results.append(check_signal_kelly_backtest(data_dir))
    results.append(check_trade_sim_indices(data_dir))
    results.append(check_etf_since_return(data_dir))
    results.append(check_track_score_consistency(data_dir, repo_data_dir))

    # 关键文件存在性
    results.extend(check_key_files(data_dir, repo_data_dir))

    return results


def run_single_file_check(path: Path) -> CheckResult:
    """对单文件做基本校验（存在 + JSON 可解析）。"""
    name = f"single:{path.name}"
    data, err = _load_json(path)
    if err:
        return _fail(name, err)
    if isinstance(data, dict):
        n = len(data)
        return _ok(name, f"dict, {n} keys")
    if isinstance(data, list):
        return _ok(name, f"list, {len(data)} items")
    return _ok(name, f"{type(data).__name__}")


# ── 路径自动检测 ──────────────────────────────────────────────────────────────

def detect_dirs(data_dir_arg: str | None) -> tuple[Path, Path]:
    """检测 static-site/data/ 和 data/ 路径。

    优先级：
    1. --data-dir 参数
    2. REPO 环境变量（deploy.sh 设置）
    3. 脚本所在仓库的 static-site/data/
    4. 当前工作目录的 static-site/data/
    """
    if data_dir_arg:
        data_dir = Path(data_dir_arg).absolute()
        # repo_data_dir = data_dir 的上两级 / "data"
        repo_root = data_dir.parent.parent  # static-site/data -> repo root
        repo_data_dir = repo_root / "data"
        return data_dir, repo_data_dir

    # REPO 环境变量（deploy.sh 设置）
    repo_env = os.environ.get("REPO")
    if repo_env:
        repo_root = Path(repo_env).absolute()
        data_dir = repo_root / "static-site" / "data"
        repo_data_dir = repo_root / "data"
        if data_dir.exists():
            return data_dir, repo_data_dir

    # 脚本所在仓库（scripts/ 的上两级）
    script_root = Path(__file__).resolve().parent.parent
    data_dir = script_root / "static-site" / "data"
    repo_data_dir = script_root / "data"
    if data_dir.exists():
        return data_dir, repo_data_dir

    # trade-data 兜底（symlink 指向 trade，但 data/ 各自独立）
    trade_data = Path("/Users/linhuichen/code/trade-data")
    if (trade_data / "static-site" / "data").exists():
        return trade_data / "static-site" / "data", trade_data / "data"

    # 当前工作目录兜底
    cwd = Path.cwd()
    return cwd / "static-site" / "data", cwd / "data"


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="数据产物校验脚本 - 拦截 4 类线上事故",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
退出码:
  0 = 全通过(含 warn)
  1 = 有 fail
  2 = 有 warn 且 --strict / --deploy-mode
        """,
    )
    parser.add_argument("--file", metavar="PATH", help="单文件校验（存在 + JSON 可解析）")
    parser.add_argument("--strict", action="store_true", help="warn 当 fail（exit 1，手动排查用）")
    parser.add_argument("--deploy-mode", action="store_true",
                        help="deploy 接入模式（仅 fail 阻断 deploy，warn 不阻断）")
    parser.add_argument("--data-dir", metavar="DIR", help="指定 static-site/data/ 路径")
    args = parser.parse_args()

    # --strict: warn 当 fail (exit 2) 手动排查用
    # --deploy-mode: 只 fail 阻断 (exit 1), warn 不阻断 (exit 0) -- 避免预存在 warn 阻塞所有 deploy
    strict = args.strict

    # 单文件模式
    if args.file:
        path = Path(args.file).absolute()
        result = run_single_file_check(path)
        print_result(result)
        return determine_exit_code([result], strict)

    # 全量校验
    data_dir, repo_data_dir = detect_dirs(args.data_dir)
    print(f"=== 数据产物校验 ===")
    print(f"  data_dir:       {data_dir}")
    print(f"  repo_data_dir:  {repo_data_dir}")
    print()

    if not data_dir.exists():
        print(f"✗ data_dir 不存在: {data_dir}")
        return 1

    results = run_all_checks(data_dir, repo_data_dir)

    # 打印结果
    for r in results:
        print_result(r)

    # 汇总
    fails = [r for r in results if r.status == CheckResult.FAIL]
    warns = [r for r in results if r.status == CheckResult.WARN]
    oks = [r for r in results if r.status == CheckResult.OK]

    print()
    print(f"=== 汇总: {len(oks)} ok / {len(warns)} warn / {len(fails)} fail ===")

    return determine_exit_code(results, strict)


def print_result(r: CheckResult):
    """打印单个校验结果。"""
    if r.status == CheckResult.OK:
        print(f"  ✓ {r.name}: {r.msg}")
    elif r.status == CheckResult.WARN:
        print(f"  ⚠ {r.name}: {r.msg}")
    elif r.status == CheckResult.FAIL:
        print(f"  ✗ {r.name}: {r.msg}")


def determine_exit_code(results: list[CheckResult], strict: bool) -> int:
    """根据结果 + strict 模式决定退出码。"""
    fails = [r for r in results if r.status == CheckResult.FAIL]
    warns = [r for r in results if r.status == CheckResult.WARN]

    if fails:
        return 1
    if warns and strict:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
