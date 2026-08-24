#!/usr/bin/env python3
"""check_data_integrity.py - 数据产物校验脚本

校验 static-site/data/ + data/ 下的关键 JSON 产物 + 主库关键指标行，拦截线上事故：
1. board_etf_map 空数组占比过高（"全部无 ETF"事故，etf_index_map.json 丢失致 broad 指数全空）
2. boot.json 嵌的 overview.date 与 overview.json.date 不一致（"成交额显示昨日值"事故）
3. intraday_snapshot amount_forecast 异常爆炸（"9.52 万亿/15 万亿"事故）
4. 关键文件不存在（etf_index_map.json 丢了 / boot.json 丢了 等）
5. a_fund_north_quarterly 最新季度行存在（CCASS 季度闸门/采集异常致指标缺失/滞后时静默）
6. export 导出面全量在位（P1-D2，单一事实源=export.py EXPORT_MANIFEST，防新数据类别
   「生成了没上线」静默缺失盲区，见 docs/bug-pattern-site-audit-20260823.md D 族）

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
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ── 阈值常量 ──────────────────────────────────────────────────────────────────
BOARD_ETF_EMPTY_FAIL_RATIO = 0.80   # 空数组占比 >=80% = FAIL（近全空，事故级）
BOARD_ETF_EMPTY_WARN_RATIO = 0.30   # >=30% = WARN（broad 指数全空，etf_index_map 缺失级）
AMOUNT_FORECAST_FAIL = 50000        # amount_forecast > 50000 亿 = FAIL（9.52 万亿/15 万亿事故）
STALE_DAYS_WARN = 3                 # date 滞后 >3 天 = WARN（日频数据可能停更）
STALE_DAYS_FAIL = 7                 # date 滞后 >7 天 = FAIL

# track_score 跨产物一致性（#29, 2026-08-22 全量两两对比替代旧 5 样本三版本抽样）
# overview.json 与 index/{id}-all.json 都是 board_etf_map.json 的快照（同源透传），
# 快照语义 = 全等（浮点安全容差 _TS_EQ_TOL）；不等 = 不同 build 产物混用：
#   map vs index 不等 = 增量门控漏依赖回归（#29 本体：733/1412 对滞后 1-2 天）
#   overview vs map 不等 = 必更白名单(MUST_RECOMPUTE)失效回归信号
_TS_EQ_TOL = 1e-6
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


# 首页 9 张情绪卡 score_id（与 overview today.scores 消费点一致，见 app/queries.py overview()）
EMOTION_SCORE_IDS = [
    "a_sentiment", "cross_market", "fear_greed",
    "sentiment_sz50", "sentiment_hs300", "sentiment_csi500",
    "sentiment_csi1000", "sentiment_cyb", "sentiment_kc50",
]


def check_sentiment_card_date(data_dir: Path) -> CheckResult:
    """校验首页情绪卡「当前值」date 与 sentiment 序列末尾 date 一致（§22 一致性扩展）。

    事故场景(2026-08-18)：overview today.scores 单一锚定 a_sentiment -> a_sentiment 缺当日
    (width 采集 ImportError)时 9 卡全停 T-1，而 sentiment-1y/6m 逐 score_id 取 max 已有当日
    -> 用户看到「弹窗读到 818、卡片读到 817」不一致。本校验对每张情绪卡比对：
    overview.today.scores.<id>.date == sentiment-1y.json.<id> 数组末尾 date。
    任一不一致 = FAIL 阻断上线（防「文件有最新、当前值停旧」再犯）。
    """
    name = "sentiment_card_date"
    ov, ov_err = _load_json(data_dir / "overview.json")
    if ov_err:
        return _fail(name, f"无法读 overview.json: {ov_err}")
    if not isinstance(ov, dict):
        return _fail(name, "overview.json 不是 dict")
    today = ov.get("today") if isinstance(ov.get("today"), dict) else {}
    ov_scores = today.get("scores") if isinstance(today.get("scores"), dict) else {}

    s1y, s1y_err = _load_json(data_dir / "sentiment-1y.json")
    if s1y_err:
        return _fail(name, f"无法读 sentiment-1y.json: {s1y_err}")
    if not isinstance(s1y, dict):
        return _fail(name, "sentiment-1y.json 不是 dict")

    mism = []
    for sid in EMOTION_SCORE_IDS:
        os_ = ov_scores.get(sid)
        if not (isinstance(os_, dict) and os_.get("date")):
            # 该卡未出现在 overview（数据层异常，非本校验比对范围），跳过避免误报
            continue
        ov_date = str(os_["date"])
        seq = s1y.get(sid)
        if not (isinstance(seq, list) and seq):
            mism.append(f"{sid}: overview 卡 date={ov_date} 但 sentiment-1y 无序列")
            continue
        last = seq[-1]
        last_date = last.get("date") if isinstance(last, dict) else None
        if last_date is None:
            continue
        if str(last_date) != ov_date:
            mism.append(f"{sid}: overview.today.scores.date={ov_date} != sentiment-1y 末尾={last_date}")

    if mism:
        return _fail(name, "情绪卡当前值 date 与 sentiment 序列末尾不一致(文件已有最新但当前值停旧): "
                           + "; ".join(mism))
    return _ok(name, f"{len(EMOTION_SCORE_IDS)} 张情绪卡 date 与 sentiment-1y 末尾一致")


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
    """校验 signal_kelly_backtest.json：象限×5周期×N模式组合完整(模式集动态读 config.sell_modes)。

    事故场景：脚本异常/ETF价格缺失 -> quadrants 为空或组合不完整 -> 前端 lab tab 全空。
    象限数随版本演进(7->16, 2026-08-09 加信号类型4+指数大类5)，动态计算非硬编码。
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

    # 16 象限: 同步 QUADRANT_META (scripts/signal_kelly_backtest.py L71)，新增象限时此处同步
    expected_quads = {
        "rating_high", "rating_mid", "rating_low",                       # 评级档 (3)
        "etf_strong", "etf_related", "etf_approx", "etf_has_track",      # ETF 跟踪档 (4)
        "sig_main", "sig_aux", "sig_special", "sig_backup",              # 信号类型 (4)
        "mkt_a", "mkt_hk", "mkt_global", "mkt_industry", "mkt_concept",  # 指数大类 (5)
    }
    missing = expected_quads - set(quadrants.keys())
    if missing:
        return _fail(name, f"缺少象限: {missing}")

    # 期望卖出模式集合: 动态读 config.sell_modes (A-F 固定规则 + G/H/I 信号驱动, 2026-08-10 加 G/H/I)。
    # 加新模式时后端 SELL_MODES 加即可, 此处自动适配, 不再硬编码 A-F。
    expected_modes = set((data.get("config") or {}).get("sell_modes", {}).keys())
    if not expected_modes:
        expected_modes = {"A", "B", "C", "D", "E", "F", "G", "H", "I"}

    # 验证 所有象限×5周期×N模式组合完整 + 非零象限有样本
    total_n = 0
    empty_quads = []
    n_quads = 0
    for qk, qv in quadrants.items():
        if not isinstance(qv, dict) or "periods" not in qv:
            return _fail(name, f"象限 {qk} 结构异常")
        n_quads += 1
        periods = qv["periods"]
        if not isinstance(periods, dict) or set(periods.keys()) != {"y1", "y3", "y5", "y10", "all"}:
            return _fail(name, f"象限 {qk} 周期不完整: {set(periods.keys()) if isinstance(periods, dict) else 'N/A'}")
        for pk, pv in periods.items():
            if not isinstance(pv, dict) or set(pv.keys()) != expected_modes:
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

    n_combos = n_quads * 5 * len(expected_modes)
    msg = f"{n_quads}象限×5周期×{len(expected_modes)}模式={n_combos}组合完整, all/A 总样本={total_n}"
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
    口径修正(2026-08-13)：排除"今日信号"设计 null —— 信号日 == score_date(overview.json 顶层
    date)的行无"至今"语义，queries.py L657 对今日信号恒置 None，属设计非事故。分母只算
    "应有值"行（非今日信号），防止把设计 null 误算进事故拦截。真事故拦截不放松：注入全 null
    时非今日信号行仍全 null -> 占比 0% -> 仍 FAIL。
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

    # 今日信号(信号日==score_date)无"至今"语义，设计 null 不计入分母（对齐 queries.py L657）
    score_date = data.get("date")
    total = 0
    nonnull = 0
    for s in signals:
        if not isinstance(s, dict):
            continue
        # 顶层 date 缺失时无法识别今日信号 -> 按旧口径全量统计（保守，不放松）
        if score_date is not None and s.get("date") == score_date:
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


def _find_sentiment_db() -> Path | None:
    """定位主库 sentiment.db（daily_metric 写入端同库）。

    优先 trade-data/data/sentiment.db（launchd 写端 cwd=REPO=trade-data，最新主库），
    回退 trade/data/sentiment.db（镜像）。找不到返回 None。
    """
    for c in (
        Path("/Users/linhuichen/code/trade-data/data/sentiment.db"),
        Path("/Users/linhuichen/code/trade/data/sentiment.db"),
    ):
        if c.exists():
            return c
    return None


def _latest_published_quarter_end(today: datetime) -> datetime | None:
    """返回最近已发布的季度末（季度末 + 20 天 <= 今天），与 hkex_ccass_quarterly._quarter_end_dates 同口径。

    发布规则：CCASS 季度末后约 20 天才发布（实测 6/30 数据 7/15 发布）。
    """
    y, m = today.year, today.month
    for _ in range(8):
        if m <= 3:
            qe = datetime(y - 1, 12, 31)
        elif m <= 6:
            qe = datetime(y, 3, 31)
        elif m <= 9:
            qe = datetime(y, 6, 30)
        else:
            qe = datetime(y, 9, 30)
        if qe + timedelta(days=20) <= today:
            return qe
        if m <= 3:
            y, m = y - 1, 12
        elif m <= 6:
            y, m = y, 3
        elif m <= 9:
            y, m = y, 6
        else:
            y, m = y, 9
    return None


def check_etf_hist(data_dir: Path) -> CheckResult:
    """校验 etf/ 全史日K产物目录（#10，export_etf_hist.py 生成）。

    事故场景：etf/ 目录丢失或文件为空 -> 前端 ETF 评分弹窗长周期 tab（3m~全部）
    fetchJSON 404 -> 走势区空白。默认 30 日不受影响（读 overview e.ohlc）。
    校验：目录存在 + 文件数>0 + 抽样 date/count/ohlc 结构非空。
    """
    import random

    name = "etf_hist"
    etf_dir = data_dir / "etf"
    if not etf_dir.is_dir():
        return _warn(name, f"etf/ 目录不存在: {etf_dir}（长周期 tab 将空白，"
                     f"跑 export_etf_hist.py 生成；默认30日不受影响）")

    files = sorted(etf_dir.glob("*.json"))
    if not files:
        return _warn(name, f"etf/ 目录无 JSON 文件: {etf_dir}")

    # 抽样最多 5 只验结构（date 非空 / count>0 / ohlc 数组非空）
    sample = random.sample(files, min(5, len(files)))
    bad = []
    for f in sample:
        d, err = _load_json(f)
        if err:
            bad.append(f"{f.name}: {err}")
            continue
        if not d.get("date") or not d.get("count") or not d.get("ohlc"):
            bad.append(f"{f.name}: date/count/ohlc 有空值")
        elif len(d["ohlc"]) != d["count"]:
            bad.append(f"{f.name}: count={d['count']} != len(ohlc)={len(d['ohlc'])}")
    if bad:
        return _fail(name, "; ".join(bad))
    return _ok(name, f"{len(files)} 只 ETF 全史日K，抽样 {len(sample)} 只结构正常")


def check_a_fund_north_quarterly() -> CheckResult:
    """校验主库 daily_metric 的 a_fund_north_quarterly 最新季度行存在。

    事故场景：季度闸门/采集异常（CCASS 爬取失败/写穿缓存被杀）致指标缺失或冻结时静默——
    前端北向季度指标卡显示旧值/空。期望最新行 date = 最近已发布季度末（季度末+20 天 < 今天），
    缺失或滞后 = FAIL（闸门每天 16:35/21:00 跳过、02:00 强制重算，正常应始终有当季行）。
    """
    name = "a_fund_north_quarterly"
    db = _find_sentiment_db()
    if db is None:
        return _warn(name, "sentiment.db 未找到，无法校验 a_fund_north_quarterly")
    try:
        conn = sqlite3.connect(str(db), timeout=5.0)
        row = conn.execute(
            "SELECT date, value FROM daily_metric "
            "WHERE metric_id='a_fund_north_quarterly' AND value IS NOT NULL "
            "ORDER BY date DESC LIMIT 1"
        ).fetchone()
        conn.close()
    except Exception as e:
        return _fail(name, f"读 sentiment.db 失败: {e}")

    expected = _latest_published_quarter_end(datetime.now())
    if expected is None:
        return _warn(name, "无法确定最近已发布季度末")
    expected_str = expected.strftime("%Y%m%d")

    if not row:
        return _fail(name, f"daily_metric 无 a_fund_north_quarterly 非空行"
                     f"（季度采集异常/闸门冻结，应至少存在最近已发布季度末 {expected_str}）")
    rdate, rval = row
    if rdate == expected_str:
        return _ok(name, f"最新季度行存在 date={rdate} value={rval:.2f} 亿")
    return _fail(name, f"最新季度行 date={rdate} != 期望 {expected_str}"
                 f"（季度闸门/采集异常致指标滞后，应 02:00 强制重算补回）")


def _load_track_map(repo_data_dir: Path) -> tuple[dict | None, str | None]:
    """读 board_etf_map.json -> {index_id: {code: entry}}（_meta/非 list 值跳过）。

    读不到/结构坏返回 (None, err)；调用方转 FAIL。"""
    bmap, err = _load_json(repo_data_dir / "board_etf_map.json")
    if err:
        return None, err
    if not isinstance(bmap, dict):
        return None, f"board_etf_map.json 不是 dict: {type(bmap).__name__}"
    out: dict[str, dict] = {}
    for idx, v in bmap.items():
        if idx.startswith("_") or not isinstance(v, list):
            continue
        out[idx] = {e.get("code"): e for e in v if isinstance(e, dict) and e.get("code")}
    return out, None


def _ts_float(v) -> float | None:
    """track_score 值 -> float；None/解析失败返回 None（灰灭/脏值，与对侧 None 同判）。"""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ts_equal(a: float | None, b: float | None) -> bool:
    """快照全等判定：双方同 None（一致灰灭）= 等；单侧 None = 不等；数值比 ±_TS_EQ_TOL。"""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= _TS_EQ_TOL


def check_track_score_map_vs_index(data_dir: Path, repo_data_dir: Path) -> CheckResult:
    """校验① board_etf_map vs index/{id}-all.json 全量 pair track_score 全等（#29）。

    index 详情 etfs 是 map 的快照（queries.etf_for 读同一文件透传），快照应全等。
    不等 = 增量门控漏依赖回归（#29 本体：map 单独刷新后 index 停旧快照，审计实测
    733/1412 对滞后 1-2 天，见 docs/r2-track-score-consistency-audit-20260822.md）。
    旧校验（5 样本 top1 抽样）对 55.6% 不一致率几乎无检出力，升级为全量两两对比。
    口径：code 集合双向相等 + 交集内 track_score 全等（双方同 None = 一致灰灭）。
    排除 match_method=="self"（ETF 本体兜底注入，board_etf_map 无 key 属设计内，
    queries._self_etf_for）。任何不一致 = FAIL 阻断 deploy（§22 数据一致性铁律）。
    """
    name = "track_score_map_vs_index"
    tmap, err = _load_track_map(repo_data_dir)
    if err:
        return _fail(name, f"无法读 board_etf_map: {err}")

    idx_dir = data_dir / "index"
    files = sorted(idx_dir.glob("*-all.json")) if idx_dir.exists() else []
    if not files:
        return _fail(name, f"index 详情产物缺失: {idx_dir} 无 *-all.json")

    total = 0        # 双方可比 pair 数（含同 None）
    bad: list[tuple] = []          # 分数不等
    missing: list[tuple] = []      # 单侧缺失（快照集合不等 = 滞后）
    worst = 0.0
    for f in files:
        d, derr = _load_json(f)
        if derr or not isinstance(d, dict):
            continue
        iid = f.name[: -len("-all.json")]
        mmap = tmap.get(iid)
        if mmap is None:
            continue  # map 未收录该指数（无快照关系，如 self 注入类），非比对对象
        seen: set[str] = set()
        for e in d.get("etfs") or []:
            if not (isinstance(e, dict) and e.get("code")):
                continue
            code = e["code"]
            seen.add(code)
            if e.get("match_method") == "self":
                continue
            ref = mmap.get(code)
            if ref is None:
                missing.append((iid, code, "index有/map无"))
                continue
            a = _ts_float(e.get("track_score"))
            b = _ts_float(ref.get("track_score"))
            total += 1
            if not _ts_equal(a, b):
                diff = abs((a or 0.0) - (b or 0.0))
                worst = max(worst, diff)
                bad.append((iid, code, f"map={b} index={a}"))
        for code in mmap:
            if code not in seen:
                missing.append((iid, code, "map有/index无"))

    problems = bad + missing
    if problems:
        head = "; ".join(f"{i}/{c}({w})" if w != "index有/map无" and w != "map有/index无"
                         else f"{i}/{c} {w}" for i, c, w in problems[:3])
        more = f" 等{len(problems)}对" if len(problems) > 3 else ""
        return _fail(name, f"board_etf_map vs index 详情 {len(problems)} 对不一致"
                     f"(分数不等{len(bad)}/单侧缺失{len(missing)}, 最大分差{worst:.2f}, "
                     f"可比{total}对) = 增量门控漏依赖回归(#29): {head}{more}")
    return _ok(name, f"board_etf_map vs index 详情全量一致({len(files)} 文件/{total} 对, "
               f"含同灰灭, 容差±{_TS_EQ_TOL})")


def check_track_score_overview_vs_map(data_dir: Path, repo_data_dir: Path) -> CheckResult:
    """校验② overview vs board_etf_map 今日 pair track_score 全等（#29 配套回归哨兵）。

    overview 已进必更白名单（export.py MUST_RECOMPUTE，每次全量重算读当前 map），
    今日 pair 应恒等；不等 = 必更白名单失效回归信号（overview 停旧 map 快照）。
    排除两类设计内注入（queries.py）：
      - match_method=="self"（ETF 本体兜底，map 无 key）
      - code 不在 map 的 _bk_top 条目（#60 方案A 冻结 ETF 被 map 换代后 prepend，带冻结时旧分，
        首页 1:1 对齐回测属设计内）；_bk_top 且 code 在 map 的条目数值=当前 map，正常比对。
    指数整体不在 map（tmap 无 key）时跳过该信号（无快照关系，防边界误报）。
    """
    name = "track_score_overview_vs_map"
    tmap, err = _load_track_map(repo_data_dir)
    if err:
        return _fail(name, f"无法读 board_etf_map: {err}")
    ov, ov_err = _load_json(data_dir / "overview.json")
    if ov_err or not isinstance(ov, dict):
        return _fail(name, f"无法读 overview.json: {ov_err or '非 dict'}")

    total = 0
    bad: list[tuple] = []
    worst = 0.0
    for s in ov.get("signals_today") or []:
        if not isinstance(s, dict):
            continue
        iid = s.get("index_id")
        mmap = tmap.get(iid)
        if not isinstance(mmap, dict):
            continue
        for e in s.get("etfs") or []:
            if not (isinstance(e, dict) and e.get("code")) or e.get("match_method") == "self":
                continue
            ref = mmap.get(e["code"])
            if ref is None:
                if e.get("_bk_top"):
                    continue  # 冻结 prepend（设计内）
                bad.append((iid, e["code"], "overview有/map无"))
                continue
            a = _ts_float(e.get("track_score"))
            b = _ts_float(ref.get("track_score"))
            total += 1
            if not _ts_equal(a, b):
                diff = abs((a or 0.0) - (b or 0.0))
                worst = max(worst, diff)
                bad.append((iid, e["code"], f"map={b} overview={a}"))

    if bad:
        head = "; ".join(f"{i}/{c}({w})" for i, c, w in bad[:3])
        more = f" 等{len(bad)}对" if len(bad) > 3 else ""
        return _fail(name, f"overview vs board_etf_map {len(bad)} 对今日 track_score 不一致"
                     f"(最大分差{worst:.2f}, 可比{total}对) = 必更白名单失效回归信号: {head}{more}")
    return _ok(name, f"overview vs board_etf_map 今日 pair 全量一致({total} 对, "
               f"容差±{_TS_EQ_TOL})")


# T1 AI降亏特征通道（2026-08-23）：kelly_loss_features.json 存在且规格完整（E16 防静默缺失）。
# 该文件是前端 AI 降亏新键 spec-driven 谓词的唯一规格源（meta.rules，键集=loss_rules.NEW_KEYS_PROD），
# 缺失/空 rules 时前端整体不拦（诚实降级）= 过滤静默失效，故 FAIL 阻断上线。
def _load_loss_rules():
    """从 scripts/loss_rules.py 动态加载规则单一事实源（断言动态化，#43）。

    键数断言不再写死数字（d0bd31856 曾因 X1/excludeTierNone 入规格手改 20→21 即病灶：
    每次动规则要人肉改断言），改从 loss_rules.NEW_KEYS_PROD 动态推导。Path.resolve()
    解析 symlink：本脚本从 trade 直跑或经 trade-data/scripts symlink 跑都落到同一真实
    scripts/ 目录，两树同源可跑。返回 (new_keys_prod, err)；加载失败返回 err，由上层
    FAIL 显性暴露（校验器自身不可用时绝不静默跳过，§23.11 精神）。
    """
    import importlib.util
    rules_py = Path(__file__).resolve().parent / "loss_rules.py"
    if not rules_py.exists():
        return None, f"未找到 loss_rules.py(单一事实源不可用): {rules_py}"
    try:
        spec = importlib.util.spec_from_file_location("_trade_loss_rules", rules_py)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:  # noqa: BLE001
        return None, f"加载 loss_rules.py 失败: {type(e).__name__}: {e}"
    return list(mod.NEW_KEYS_PROD), None


def check_kelly_loss_features(data_dir: Path) -> CheckResult:
    """校验 kelly_loss_features.json：存在 + meta.rules 键集 ≡ loss_rules.NEW_KEYS_PROD + meta.thresholds 有值。"""
    name = "kelly_loss_features"
    path = data_dir / "kelly_loss_features.json"
    data, err = _load_json(path)
    if err:
        return _fail(name, err)
    if not isinstance(data, dict):
        return _fail(name, f"kelly_loss_features.json 不是 dict: {type(data).__name__}")

    meta = data.get("meta")
    if not isinstance(meta, dict):
        return _fail(name, "meta 缺失或非 dict")

    # 键集动态推导自 scripts/loss_rules.py NEW_KEYS_PROD（=RULE_SPECS 经 MINING_TO_PROD_KEY
    # 映射的全量生产键，含 excludeTierNone/X1；gen_kelly_loss_features.py 同源写出、lab.js
    # _KELLY_LOSS_NEW_KEYS 同源）。键集全等比只比长度更强：换键不改数也能抓；增删规则只改
    # loss_rules.py 一处，此处自动跟随，根治「动规则必人肉改断言」（d0bd31856 病灶）
    new_keys, err = _load_loss_rules()
    if err:
        return _fail(name, err)
    rules = meta.get("rules")
    keys = {r.get("key") for r in rules} if isinstance(rules, list) else set()
    missing = sorted(set(new_keys) - keys)
    extra = sorted(keys - set(new_keys))
    if missing or extra:
        _m = f"{missing[:4]}{'...' if len(missing) > 4 else ''}" if missing else "无"
        _x = f"{extra[:4]}{'...' if len(extra) > 4 else ''}" if extra else "无"
        return _fail(name, f"meta.rules 键集与 loss_rules.NEW_KEYS_PROD({len(new_keys)}键)不一致"
                     f"(缺{len(missing)}: {_m}; 多{len(extra)}: {_x}；前端过滤将静默失效)")

    thresholds = meta.get("thresholds")
    if not isinstance(thresholds, dict) or not thresholds:
        return _fail(name, "meta.thresholds 缺失或空（分位阈值快照缺失）")

    features = data.get("features")
    n_feat = len(features) if isinstance(features, dict) else 0
    return _ok(name, f"rules={len(keys)}键, thresholds={len(thresholds)}项, features={n_feat}序列")


# ── P1-D2: export 导出面 ⟺ 本地在位 全量断言(2026-08-23) ─────────────────────

def _load_export_manifest(data_dir: Path):
    """从 static-site/export.py 动态加载导出清单单一事实源（P1-D2）。

    importlib 按路径加载（export.py 非包成员；其顶层 sys.path.insert(ROOT) 后
    import app.* 与本脚本同根兼容，实测加载无副作用）。刻意不在本文件抄第二份
    文件名字面量——清单漂移由 export.py main() 末尾 manifest_alignment_check
    自守，本脚本只消费。返回 (files, warn_set, dir_globs, err)；加载失败返回 err，
    由上层 FAIL 显性暴露（校验器自身不可用时绝不静默跳过，§23.11 精神）。
    """
    import importlib.util
    export_py = data_dir.parent / "export.py"
    if not export_py.exists():
        return None, None, None, f"未找到 export.py(单一事实源不可用): {export_py}"
    try:
        spec = importlib.util.spec_from_file_location("_trade_export_manifest", export_py)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:  # noqa: BLE001
        return None, None, None, f"加载 export.py 失败: {type(e).__name__}: {e}"
    files = getattr(mod, "EXPORT_MANIFEST", None)
    if not isinstance(files, dict) or not files:
        return None, None, None, f"export.py 无有效 EXPORT_MANIFEST 清单: {export_py}"
    warn_set = set(getattr(mod, "EXPORT_MANIFEST_WARN", {}) or ())
    globs = list(getattr(mod, "EXPORT_MANIFEST_DIR_GLOBS", ()) or ())
    return files, warn_set, globs, None


def check_export_manifest(data_dir: Path) -> CheckResult:
    """P1-D2：export 清单全量在位断言（E16 防「生成了没上线」静默缺失盲区）。

    事故场景（docs/bug-pattern-site-audit-20260823.md D 族）：export.py 导出面
    39 个 JSON 名中 31 个不在既有校验范围（public_fund_* 12 件/futures/metrics/
    signal_stats/signal_kelly_trades 等），新数据类别静默缺失无拦截。
    单一事实源 = static-site/export.py EXPORT_MANIFEST（动态 import，不抄字面量）：
    逐名检查存在 + 非空(size>0)；目录级动态名（index/*-all 等 cfg/31 行业变量名）
    按 EXPORT_MANIFEST_DIR_GLOBS 查「至少有文件」。缺失处置分级：WARN 集内 =
    WARN（signal_kelly 两件 subprocess 失败不阻塞 export 属设计内可缺），其余
    缺失/空文件 = FAIL（每日必有，缺失=生成链断裂）。
    """
    name = "export_manifest"
    files, warn_set, globs, err = _load_export_manifest(data_dir)
    if err:
        return _fail(name, err)

    missing: list[str] = []
    empty: list[str] = []
    warn_missing: list[str] = []
    for fname in sorted(files):
        p = data_dir / fname
        if not p.exists():
            if fname in warn_set:
                warn_missing.append(fname)
            else:
                missing.append(fname)
            continue
        try:
            if p.stat().st_size == 0:
                empty.append(fname)
        except OSError as e:
            empty.append(f"{fname}({e})")

    dir_missing: list[str] = []
    dir_hits = 0
    for pat in globs:
        hits = sorted(data_dir.glob(pat)) if data_dir.is_dir() else []
        if hits:
            dir_hits += 1
        else:
            dir_missing.append(pat)

    total_named = len(files)
    if missing or empty or dir_missing:
        parts = []
        if missing:
            parts.append(f"缺失{len(missing)}件: {missing[:6]}{'...' if len(missing) > 6 else ''}")
        if empty:
            parts.append(f"空文件{len(empty)}件: {empty[:6]}{'...' if len(empty) > 6 else ''}")
        if dir_missing:
            parts.append(f"目录族无文件: {dir_missing}")
        return _fail(name, f"export 清单全量断言失败({'; '.join(parts)}); "
                     f"清单源=export.py EXPORT_MANIFEST({total_named} 具名 + "
                     f"{len(globs)} 目录族)")
    msg = (f"清单全量在位: {total_named} 个具名产物非空 + {dir_hits}/{len(globs)} "
           f"目录族有文件(单一事实源=export.py EXPORT_MANIFEST)")
    if warn_missing:
        return _warn(name, msg + f"; 设计内可缺未生成: {warn_missing}")
    return _ok(name, msg)


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
    """运行全部校验函数 + 关键文件存在性校验（新增校验在 run_all_checks 末尾按
    时间序追加，历史"15 个"计数已不准确，以本函数 append 清单为准）。"""
    results = []

    # 15 个校验函数
    results.append(check_board_etf_map(repo_data_dir))
    results.append(check_overview(data_dir))
    results.append(check_sentiment_card_date(data_dir))
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
    # #10 ETF 全史日K产物目录（export_etf_hist.py -> R2 etf/ 前缀）
    results.append(check_etf_hist(data_dir))
    # #29 track_score 跨产物一致性（2026-08-22 起两路全量对比，替代旧 5 样本三版本抽样）
    results.append(check_track_score_map_vs_index(data_dir, repo_data_dir))
    results.append(check_track_score_overview_vs_map(data_dir, repo_data_dir))
    results.append(check_a_fund_north_quarterly())
    # T1 AI降亏特征通道（2026-08-23）：规格单源完整性（E16 防静默缺失）
    results.append(check_kelly_loss_features(data_dir))
    # P1-D2 export 导出面全量断言（2026-08-23，单一事实源=export.py EXPORT_MANIFEST，
    # E16 防「生成了没上线」31 产物盲区，见 docs/bug-pattern-site-audit-20260823.md D 族）
    results.append(check_export_manifest(data_dir))

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
