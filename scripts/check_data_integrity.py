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
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ── 阈值常量 ──────────────────────────────────────────────────────────────────
BOARD_ETF_EMPTY_FAIL_RATIO = 0.80   # 空数组占比 >=80% = FAIL（近全空，事故级）
# codex-001 medium: deploy 模式标志(模块级, main() 按 --deploy-mode 赋值),
# 供个别校验项在 deploy 链收紧阈值(fund_nav 覆盖率 <98% FAIL)
_deploy_mode = False
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


def check_kelly_lab_slices(data_dir: Path) -> CheckResult:
    """校验凯利移动端切片(signal_kelly_trades_parts/)与整包同版（#97 批次C，F1 review-kelly-mobile-20260825）。

    事故场景：回测重跑只更新整包、切片由旧版脚本跑的没跟着导出 -> 「新整包+旧切片」同时上线
    -> 移动端弹窗快速预览数字 != 正式表数字（§22 数据一致性违反）。校验四件：
      ① lab_meta.generated_at == signal_kelly_trades.json.generated_at（混版 FAIL 阻断）
      ② meta.parts 记录的每片文件在位（防片丢失）
      ③ 目录 lab_ 片集合 == meta 记录集合（防孤儿/残留片被前端拉到旧数据）
      ④ codex-002 增强: 逐片深度校验——JSON 可解析+片 generated_at/fields 与整包一致
        + size==meta.bytes + 行数==meta.rows + 组内行数和==meta.total（防半截写入/单片混版）
    meta 不存在 = WARN 不阻断（切片未生成的老环境向后兼容；merge 后跑
    `python scripts/signal_kelly_backtest.py --export-lab-slices-only` 补生成）。
    整包 generated_at 用头 4KB 正则轻量提取（62MB 不全量加载；该键恒为首键，见产物头部）。
    """
    name = "kelly_lab_slices"
    trades_path = data_dir / "signal_kelly_trades.json"
    parts_dir = data_dir / "signal_kelly_trades_parts"
    meta_path = parts_dir / "lab_meta.json"
    if not trades_path.exists():
        return _warn(name, f"整包不存在: {trades_path.name}")
    if not meta_path.exists():
        return _warn(name, "lab_meta.json 不存在（切片未生成; merge 后跑 scripts/signal_kelly_backtest.py --export-lab-slices-only 同步）")

    # 整包 generated_at（首键，头 4KB 必含）
    with open(trades_path, "rb") as f:
        head = f.read(4096).decode("utf-8", errors="replace")
    m = re.search(r'"generated_at"\s*:\s*"([^"]+)"', head)
    if not m:
        return _warn(name, "整包头 4KB 未找到 generated_at（结构变更? 需人工核对）")
    full_ts = m.group(1)

    meta, err = _load_json(meta_path)
    if err:
        return _fail(name, f"lab_meta.json 解析失败: {err}")
    if not isinstance(meta, dict):
        return _fail(name, f"lab_meta.json 不是 dict: {type(meta).__name__}")
    meta_ts = meta.get("generated_at")
    if meta_ts != full_ts:
        return _fail(
            name,
            f"切片/整包混版: lab_meta.generated_at={meta_ts} != signal_kelly_trades.generated_at={full_ts}"
            f"（先跑 python scripts/signal_kelly_backtest.py --export-lab-slices-only 同步再 deploy, §22）",
        )

    # 片在位 + 双向集合比对（missing=meta 记了文件没了; orphan=目录有 meta 没记=残留旧片）
    expected = set()
    for g in (meta.get("groups") or {}).values():
        for p in ((g or {}).get("parts") or []):
            if p.get("name"):
                expected.add(p["name"])
    actual = {
        p.name for p in parts_dir.glob("lab_*.json")
        if p.name != "lab_meta.json" and re.match(r"^lab_.+__.+_p\d+\.json$", p.name)
    }
    missing = sorted(expected - actual)
    orphan = sorted(actual - expected)
    if missing:
        return _fail(name, f"meta 记录 {len(expected)} 片, 缺 {len(missing)} 片如 {missing[:3]}")
    if orphan:
        return _fail(name, f"目录存在 meta 未记录的残留片 {len(orphan)} 个如 {orphan[:3]}（重导后未清/混版）")

    # codex-002 high 增强: 逐片深度校验（防「文件在位但内容坏/旧」——半截写入/重导中断/混版单片的
    # 情况集合比对拦不住）。每片解析 JSON + 头部 generated_at/fields 与整包一致 + size==meta.bytes
    # + 数组行数==meta.rows。303 片全量 json.load 实测秒级, 可接受(仅 deploy 链跑)。
    bad = []
    checked_rows = 0
    for gkey, g in (meta.get("groups") or {}).items():
        declared_total = 0
        for p in ((g or {}).get("parts") or []):
            pn = p.get("name") or ""
            pp = parts_dir / pn
            try:
                if pp.stat().st_size != p.get("bytes"):
                    bad.append(f"{pn}:size({pp.stat().st_size}!={p.get('bytes')})")
                    continue
                shard = json.loads(pp.read_text(encoding="utf-8"))
                if shard.get("generated_at") != full_ts:
                    bad.append(f"{pn}:generated_at({shard.get('generated_at')}!={full_ts})")
                    continue
                if list(shard.get("fields") or []) != list(meta.get("fields") or []):
                    bad.append(f"{pn}:fields不一致")
                    continue
                qkv = (shard.get("quadrants") or {})
                n_rows = sum(len(v) for mk_map in qkv.values() for v in (mk_map.values() if isinstance(mk_map, dict) else []))
                if n_rows != p.get("rows"):
                    bad.append(f"{pn}:rows({n_rows}!={p.get('rows')})")
                    continue
                declared_total += n_rows
                checked_rows += n_rows
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                bad.append(f"{pn}:JSON解析失败({type(e).__name__})")
            except OSError as e:
                bad.append(f"{pn}:读取失败({type(e).__name__})")
        if isinstance(g, dict) and g.get("total") is not None and declared_total != g["total"]:
            bad.append(f"{gkey}:组总行数({declared_total}!=meta.total {g['total']})")
    if bad:
        return _fail(name, f"逐片深度校验 FAIL {len(bad)} 片如: {'; '.join(bad[:4])}（重导切片再 deploy）")

    n_groups = len(meta.get("groups") or {})
    return _ok(name, f"切片与整包同版({full_ts}), {n_groups}组/{len(expected)}片深度校验齐({checked_rows}行)")


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


def _find_public_fund_db() -> Path | None:
    """定位公募基金库 public_fund.db（fund_daily_nav 写入端同库）。

    优先 trade-data/data/public_fund.db（launchd 写端 cwd=REPO=trade-data，最新主库），
    回退 trade/data/public_fund.db（镜像）。找不到返回 None。
    """
    for p in (
        Path("/Users/linhuichen/code/trade-data/data/public_fund.db"),
        Path("/Users/linhuichen/code/trade/data/public_fund.db"),
    ):
        if p.exists():
            return p
    return None


def check_fund_nav(data_dir: Path) -> CheckResult:
    """校验 fund_nav/ 全史净值产物目录（#11，export_fund_nav.py 生成）。

    事故场景：fund_nav/ 目录丢失或文件为空 -> 前端基金评分弹窗「净值走势」
    fetchJSON 404 -> 走势区空白。校验四层（codex-001 medium 加深, 2026-08-26）：
      1) 目录存在 + 文件数>0 + 抽样 date/count/nav 结构非空
         （count==0 视为合法空数据基金放行：全 NULL 净值 code export 正常产出空 JSON，
          实测 136/26118 只；仅 count 显式为 0 放行，count 字段缺失仍判结构坏）;
      2) **全量轻量结构校验**: 逐文件 json.load + 顶层 dict + code/date 字段存在性
         （不读全量内容, 26120 文件实测 ~7s; 防随机抽样漏掉大面积定向损坏穿透）,
         抽样数可用 env FUND_NAV_SAMPLE_N 调节(默认 30);
      3) 覆盖率: 文件数 vs DB distinct fund_code
         （常规 <90% FAIL / <95% WARN; deploy 模式收紧到 <98% FAIL——deploy 是最后闸门）;
      4) 抽样最多 N 只 DB<->产物逐位一致（最新 3 个有效净值点 date/unit_nav/acc_nav 全等；
         空数据文件两侧均为空序列, 天然一致）。
    """
    import random

    name = "fund_nav"
    nav_dir = data_dir / "fund_nav"
    if not nav_dir.is_dir():
        return _warn(name, f"fund_nav/ 目录不存在: {nav_dir}（基金弹窗「净值走势」将空白，"
                     f"跑 export_fund_nav.py 生成；评分/凯利区块不受影响）")

    files = sorted(nav_dir.glob("*.json"))
    if not files:
        return _warn(name, f"fund_nav/ 目录无 JSON 文件: {nav_dir}")

    # codex-001 medium: 抽样数可配置(env FUND_NAV_SAMPLE_N, 默认 5->30), deploy 模式下
    # 大面积损坏靠全量轻量层兜住, 抽样只负责深度形状/DB 逐位比对
    try:
        sample_n = max(5, int(os.environ.get("FUND_NAV_SAMPLE_N", "30")))
    except ValueError:
        sample_n = 30

    # ── 第2层: 全量轻量结构校验(逐文件 json.load 头部, 不读全量 nav 内容)──
    light_bad = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            if not isinstance(d, dict):
                light_bad.append(f"{f.name}: 顶层非对象({type(d).__name__})")
            elif not d.get("code"):
                light_bad.append(f"{f.name}: 缺 code")
            # date 口径对齐抽样层空数据契约: 键必须存在, 值允许空串
            # （count==0 合法空数据基金 exporter 写 date="", 实测 136/26118 只）
            elif "date" not in d:
                light_bad.append(f"{f.name}: 缺 date")
            elif not isinstance(d.get("nav"), list):
                light_bad.append(f"{f.name}: nav 非数组")
        except json.JSONDecodeError as e:
            light_bad.append(f"{f.name}: JSON 解析失败 {e}")
        except OSError as e:
            light_bad.append(f"{f.name}: 读取失败 {e}")
        if len(light_bad) >= 8:
            break
    if light_bad:
        return _fail(name, f"全量轻量结构校验 {len(light_bad)}+ 个坏文件如: "
                     + "; ".join(light_bad[:4]))

    # 结构抽验(最多 N 只): date/count/nav 非空且 count==len(nav); count==0 合法空数据放行
    sample = random.sample(files, min(sample_n, len(files)))
    bad = []
    empty_cnt = 0
    for f in sample:
        try:
            d, err = _load_json(f)
            if err:
                bad.append(f"{f.name}: {err}")
                continue
            # 顶层必须是 dict（codex review high: 顶层数组/null 会让 d.get 抛 AttributeError 穿透）
            if not isinstance(d, dict):
                bad.append(f"{f.name}: 顶层非对象({type(d).__name__})")
                continue
            count = d.get("count")
            # 空数据契约: count 必须严格 int==0 且非 bool; nav 空数组; 含 code/name/source + date 字段
            # （保留内部 reviewer 已加的「count 缺失仍 FAIL」语义: count 缺失→非空分支→bad）
            if count == 0:
                if not isinstance(count, int) or isinstance(count, bool):
                    bad.append(f"{f.name}: count==0 但类型非 int({type(count).__name__})")
                elif not isinstance(d.get("nav"), list) or len(d["nav"]) != 0:
                    bad.append(f"{f.name}: 空数据但 nav 非空/非数组")
                else:
                    missing = [k for k in ("code", "name", "source")
                               if k not in d or d.get(k) in (None, "")]
                    if missing:
                        bad.append(f"{f.name}: 空数据缺关键字段 {missing}")
                    elif "date" not in d:
                        bad.append(f"{f.name}: 空数据缺 date 字段")
                    else:
                        empty_cnt += 1
                continue
            # 非空数据: 关键字段存在 + count 为 int + count==len(nav) + 逐项校验 nav 形状
            if count is None or not d.get("date") or not d.get("nav"):
                bad.append(f"{f.name}: date/count/nav 有空值")
                continue
            if not isinstance(count, int) or isinstance(count, bool):
                bad.append(f"{f.name}: count 类型非 int({type(count).__name__})")
                continue
            if len(d["nav"]) != count:
                bad.append(f"{f.name}: count={count} != len(nav)={len(d['nav'])}")
                continue
            for row in d["nav"]:
                if not isinstance(row, (list, tuple)) or len(row) != 3:
                    bad.append(f"{f.name}: nav 元素非 [date,unit_nav,acc_nav] 三元组")
                    break
                rdate, unit, acc = row
                if not isinstance(rdate, str) or not rdate:
                    bad.append(f"{f.name}: nav 元素 date 非法")
                    break
                if not isinstance(unit, (int, float)) or (acc is not None and not isinstance(acc, (int, float))):
                    bad.append(f"{f.name}: nav 元素 unit_nav/acc_nav 非数值")
                    break
        except Exception as e:
            bad.append(f"{f.name}: 抽样校验异常 {type(e).__name__}: {e}")
    if bad:
        return _fail(name, "; ".join(bad[:4]))

    # 覆盖率: 产物文件数 vs DB distinct fund_code
    db = _find_public_fund_db()
    db_codes = None
    conn = None
    if db:
        try:
            conn = sqlite3.connect(str(db), timeout=5.0)
            db_codes = {r[0] for r in conn.execute(
                "SELECT DISTINCT fund_code FROM fund_daily_nav "
                "WHERE fund_code IS NOT NULL AND fund_code != ''")}
        except sqlite3.Error as e:
            return _fail(name, f"读 public_fund.db 失败(db={db}): {e}")
        finally:
            if conn is not None:
                conn.close()
    if db_codes:
        # codex-001 low: exporter 会把非法字符替换成 _（_safe_code, 同 export_fund_nav.py）,
        # DB 脏 code 场景下 f.stem 与 DB code 直接交集口径错位 -> 建 filename->code 映射再算
        safe_re = re.compile(r"[^A-Za-z0-9_]")

        def _safe_code(code: str) -> str:
            return safe_re.sub("_", str(code or "").strip())

        fname_to_codes: dict[str, list[str]] = {}
        for c in db_codes:
            fname_to_codes.setdefault(_safe_code(c), []).append(c)
        collisions = [k for k, v in fname_to_codes.items() if len(v) > 1]
        local_names = {f.stem for f in files}
        covered = len(local_names & set(fname_to_codes))
        ratio = covered / len(db_codes)
        if collisions:
            print(f"  ⚠ {name}: safe_code 映射碰撞 {len(collisions)} 个"
                  f"如: {collisions[:3]}（DB 脏 code, 覆盖率口径含近似误差）")
        # codex-001 medium: deploy 模式收紧到 <98% FAIL（deploy 是上线最后闸门,
        # 大面积导出半途/定向删除在常规阈值下只 WARN 不阻断, deploy 链应更严）
        if _deploy_mode:
            if ratio < 0.98:
                return _fail(name, f"覆盖率 {ratio:.1%} ({covered}/{len(db_codes)}) < 98%"
                             f"（deploy 闸门收紧档），疑似导出半途/数据源变更")
        elif ratio < 0.90:
            return _fail(name, f"覆盖率 {ratio:.1%} ({covered}/{len(db_codes)}) < 90%，"
                         f"疑似导出半途/数据源变更")
        warn_line = (f"；覆盖率 {ratio:.1%}" if ratio < 0.95 else "")
        if ratio < 0.95:
            bad = [f"覆盖率 {ratio:.1%} ({covered}/{len(db_codes)}) < 95%"]
            return _warn(name, bad[0])

        # DB<->产物逐位一致抽验: 每只取 DB 最新 3 个有效净值点与产物尾部全等比对
        conn = sqlite3.connect(str(db), timeout=5.0)
        try:
            mismatch = []
            for f in sample:
                d, err = _load_json(f)
                if err or not isinstance(d, dict):
                    continue
                code = d.get("code", f.stem)
                rows = conn.execute(
                    "SELECT date, unit_nav, acc_nav FROM fund_daily_nav "
                    "WHERE fund_code=? AND unit_nav IS NOT NULL ORDER BY date DESC LIMIT 3",
                    (code,),
                ).fetchall()
                got = [(r[0], r[1], r[2]) for r in rows]
                exp = [(r[0], r[1], r[2]) for r in list(reversed(d.get("nav", [])))[:3]]
                if got != exp:
                    mismatch.append(
                        f"{code}: DB尾3={got[-1] if got else '[]'} vs "
                        f"产物尾3={exp[-1] if exp else '[]'}")
            if mismatch:
                return _fail(name, "DB↔产物不一致: " + "; ".join(mismatch[:3]))
        finally:
            conn.close()

    msg = f"{len(files)} 只基金全史净值，抽样 {len(sample)} 只结构+DB逐位一致"
    if empty_cnt:
        msg += f"（含合法空数据基金 {empty_cnt} 只）"
    if db_codes and len({f.stem for f in files} & set(fname_to_codes)) / len(db_codes) >= 0.95:
        msg += "，覆盖率 ≥95%"
    return _ok(name, msg)


def check_a_fund_north_quarterly() -> CheckResult:
    """校验主库 daily_metric 的 a_fund_north_quarterly 最新季度行存在。

    事故场景：季度闸门/采集异常（CCASS 爬取失败/写穿缓存被杀）致指标缺失或冻结时静默——
    前端北向季度指标卡显示旧值/空。期望最新行 date = 最近已发布季度末（季度末+20 天 < 今天），
    缺失或滞后 = FAIL（闸门每天 16:35/21:00 跳过、02:00 强制重算，正常应始终有当季行）。

    2026-08-24 codex 外审误报教训（rev-20260824-001）：外部 reviewer 沙箱环境审计时段撞上
    采集进程写库，connect 后查询报错走 except -> FAIL，而其手工 sqlite3 另一时刻能查到数据；
    因 FAIL msg 不带库路径与异常语境，reviewer 无法对齐环境，臆断为「查询列名与 schema 不匹配」
    （实证：metric_id 列名全历史正确，git log -S 'metric_name' 全历史 0 命中）。防再犯：
    本项所有 FAIL/WARN/OK msg 一律带 db 路径，锁竞争类异常显式标注语境——机检失败必须
    环境可对齐、根因可自解释，禁止让 reviewer 猜（§23.11 绝不静默精神）。
    """
    name = "a_fund_north_quarterly"
    db = _find_sentiment_db()
    if db is None:
        return _warn(name, "sentiment.db 未找到（trade-data 主库与 trade 镜像均不存在），"
                     "无法校验 a_fund_north_quarterly")
    try:
        conn = sqlite3.connect(str(db), timeout=5.0)
        row = conn.execute(
            "SELECT date, value FROM daily_metric "
            "WHERE metric_id='a_fund_north_quarterly' AND value IS NOT NULL "
            "ORDER BY date DESC LIMIT 1"
        ).fetchone()
        conn.close()
    except Exception as e:
        # 锁竞争专项提示：审计/机检若在采集时点（16:35/17:50/21:00 前后）撞写锁会到这，
        # 属环境时点问题非数据缺失，msg 必须说清，防被误读为 schema/权限问题。
        hint = "（库被占用，疑似采集进程持写锁，请避开采集时点重跑复验；非数据缺失/schema 问题）" \
            if "locked" in str(e).lower() else ""
        return _fail(name, f"读 sentiment.db 失败{hint}: db={db}: {e}")

    expected = _latest_published_quarter_end(datetime.now())
    if expected is None:
        return _warn(name, f"无法确定最近已发布季度末 (db={db})")
    expected_str = expected.strftime("%Y%m%d")

    if not row:
        return _fail(name, f"daily_metric 无 a_fund_north_quarterly 非空行"
                     f"（季度采集异常/闸门冻结，应至少存在最近已发布季度末 {expected_str}；db={db}）")
    rdate, rval = row
    if rdate == expected_str:
        return _ok(name, f"最新季度行存在 date={rdate} value={rval:.2f} 亿 (db={db})")
    return _fail(name, f"最新季度行 date={rdate} != 期望 {expected_str}"
                 f"（季度闸门/采集异常致指标滞后，应 02:00 强制重算补回；db={db}）")


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
    # #11 基金全史净值产物目录（export_fund_nav.py -> R2 fund_nav/ 前缀, 2026-08-25）
    results.append(check_fund_nav(data_dir))
    # #29 track_score 跨产物一致性（2026-08-22 起两路全量对比，替代旧 5 样本三版本抽样）
    results.append(check_track_score_map_vs_index(data_dir, repo_data_dir))
    results.append(check_track_score_overview_vs_map(data_dir, repo_data_dir))
    results.append(check_a_fund_north_quarterly())
    # T1 AI降亏特征通道（2026-08-23）：规格单源完整性（E16 防静默缺失）
    results.append(check_kelly_loss_features(data_dir))
    # P1-D2 export 导出面全量断言（2026-08-23，单一事实源=export.py EXPORT_MANIFEST，
    # E16 防「生成了没上线」31 产物盲区，见 docs/bug-pattern-site-audit-20260823.md D 族）
    results.append(check_export_manifest(data_dir))
    # #97 凯利移动端切片↔整包同版校验（F1 review-kelly-mobile-20260825，防「新整包+旧切片」混版上线 §22）
    results.append(check_kelly_lab_slices(data_dir))

    # S06 动态模式快照机检（2026-08-26 接入 deploy 同链，S06 切全站默认前置条件）：
    # 委托 scripts/check_s06_state.py 四断言（A1 独立复算/A2 decision_date 防前视/
    # A3 键集对齐/A4 阈值公示单源），任一 FAIL 阻断上线（§22 同链精神）
    results.append(check_s06_state_snapshot(data_dir))

    # 关键文件存在性
    results.extend(check_key_files(data_dir, repo_data_dir))

    return results


def check_s06_state_snapshot(data_dir: Path, timeout: int = 300) -> CheckResult:
    """S06 快照(kelly_mode_s06_state.json)四断言机检（2026-08-26 接入 deploy 校验链）。

    委托 scripts/check_s06_state.py 子进程执行（不 import，保持独立实现互证语义）：
      A1 第二实现复算逐位相等 / A2 decision_date==上一交易日(防前视) /
      A3 两基座+s06 dynamic 预设键集 / A4 阈值参数与生成器常量+公示文案单源。
    exit!=0 → fail（--deploy-mode 下阻断部署）；快照缺失 → fail（S06 切默认前置，
    缺失=前端 S06 档整体 fail-open 退化，属事故级不许静默上线）。
    """
    name = "s06_state"
    snap = data_dir / "kelly_mode_s06_state.json"
    if not snap.exists():
        return _fail(name, f"S06 快照不存在: {snap} (gen_kelly_mode_s06_state.py 未跑? 见 s06_snapshot.sh)")
    script = Path(__file__).resolve().parent / "check_s06_state.py"
    if not script.exists():
        return _fail(name, f"机检脚本缺失: {script}")
    repo_root = data_dir.parent.parent   # static-site/data -> 仓根(--repo/--data-repo 同根: trade-data 内 common.js/gen 脚本/index 输入齐备)
    cmd = [sys.executable, str(script), "--repo", str(repo_root), "--data-repo", str(repo_root)]
    if _deploy_mode:
        # codex008 F1(P0①): deploy 与 20:35 快照重生的每日固定时序窗口——17:50 链内
        # deploy 时因子(index-all.json)已更新到 T 而快照仍为昨晚生成(coverage_end=T-1,
        # 落后 1 个已入库交易日)。deploy 模式给显式容差 --allow-lag-days 1; 缺失/解析
        # 失败/超容差/结构不一致仍硬阻断。日常新鲜度由 schedule_monitor→check_s06_freshness
        # 兜底; 非 deploy 手动跑保持严格(default 0)。
        cmd += ["--allow-lag-days", "1"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return _fail(name, f"check_s06_state.py 超时(>{timeout}s)，疑似 index-all 异常巨大")
    tail = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
    summary = " | ".join(l.strip() for l in tail if "[FAIL]" in l or l.strip().startswith("✗"))[:400]
    if proc.returncode != 0:
        return _fail(name, f"check_s06_state.py rc={proc.returncode}: {summary or '详见该脚本输出'}")
    ok_line = next((l.strip() for l in tail if l.strip().startswith("✓")), "")
    return _ok(name, ok_line or "四断言 PASS")


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
    if args.deploy_mode:
        global _deploy_mode
        _deploy_mode = True

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
