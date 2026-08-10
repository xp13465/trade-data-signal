#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日AI预测(daily_brief)生成脚本 —— 第一阶段(单 prompt 主链路)。

用法(手动 CLI 始终可跑,不受 schedule_enabled 影响):
  python3 scripts/gen_daily_brief.py [--date YYYYMMDD] [--mock] [--rule-only] [--no-upload]

产出:
  - static-site/data/daily_brief.json           当日预测(meta 机检层 + text 展示层)
  - static-site/data/daily_brief_history.json   历史归档(90天滚动)+ 次日 hit 回填 + 命中率 stats
  - data/daily_brief_cost.log                   每次调用 token/费用(P2-1 成本监控)

主链路(P0-1 ~ P2-2 第一阶段落地):
  读数据 -> 构建 prompt(JSON 注入:前视防护 P1-7 / 数据锚定 P1-8 / 指令词黑名单 P0-3)
       -> deepseek 调用(超时/重试/429退避 P1-9)
       -> 解析输出 meta+text 两层(P0-1/P1-10)
       -> 合规脱敏 + 免责声明(P0-3)
       -> 写 JSON + 历史归档 + 次日 hit 回填(P0-1)
       -> R2 上传(数据走 R2,上传后前端可读)
  失败降级(P1-9): AI 失败/空响应 -> 规则版(version="rule") -> summary 最小版,
                 绝不让主流程失败阻塞。

北向口径修正(P0-2,已定稿):
  - 删除把 a_fund_north(成交总额,恒正)当日值当"外资方向"的用法
  - 主维度注入 futures_acc_trend(机构净多变化)+ 南向 hk_south(当日真方向)
    + a_fund_north_quarterly(季度反算,文案标注"季度口径,非日频,不得当当日方向断言")

配置: config/daily_brief.yaml
  - schedule_enabled: 调度开关,由 scripts/run_daily_brief.sh 定时入口拦截,本脚本 CLI 不受影响
  - compliance_enabled: 合规开关(指令词黑名单 + 脱敏 + 免责)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None
try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

# ── 路径解析 ────────────────────────────────────────────────────────────
# ROOT = scripts/ 的父目录(trade/,经 trade-data/scripts symlink resolve 后同此)
ROOT = Path(__file__).resolve().parent.parent
MAIN_REPO = Path("/Users/linhuichen/code/trade-data")  # launchd 主库/主数据(与 update_all.sh REPO 一致)


# ── 合规:指令词黑名单(P0-3)───────────────────────────────────────────────
# 证券合规红线=投资建议指令词。只允许"关注/警惕/观察/留意"类表述。
FORBIDDEN_WORDS = [
    "买入", "卖出", "加仓", "建仓", "清仓", "减仓", "重仓", "满仓",
    "抄底", "逃顶", "止损", "止盈", "仓位", "建议持有", "加杠杆", "梭哈", "重注",
]
# 脱敏替换映射(把指令词替换为"关注/观察"类安全表述,保语义完整)
SCRUB_MAP = {
    "买入": "关注", "建仓": "关注", "加仓": "关注", "重仓": "关注", "满仓": "关注",
    "抄底": "观察", "卖出": "警惕", "清仓": "警惕", "减仓": "警惕", "逃顶": "警惕",
    "止损": "留意风险", "止盈": "留意", "仓位": "风险敞口", "加杠杆": "谨慎",
    "梭哈": "谨慎", "重注": "谨慎", "建议持有": "持续观察",
}
# 命中即整句降级的强指令模式(正则,如"建议买入X""仓位X%"等)
STRONG_INSTRUCTION_RE = re.compile(
    r"建议\s*(买入|卖出|加仓|建仓|清仓|减仓|抄底|逃顶|止损|持有)"
    r"|仓位\s*[0-9０-９]+\s*%"
)


# ── 工具:repo/DB/数据目录定位 ───────────────────────────────────────────
def _candidate_repos() -> list[Path]:
    out: list[Path] = []
    for c in ([os.environ.get("REPO"), str(MAIN_REPO), str(ROOT)]):
        if not c:
            continue
        p = Path(c).resolve()
        if p not in out:
            out.append(p)
    return out


def pick_repo() -> Path:
    """挑数据最新的 repo(static-site/data/overview.json.date 最大者)。
    launchd/update_all 从 trade-data(主)跑,手动从 trade 跑;同日期时优先 trade-data,
    保证写入位置与 deploy.sh/upload_r2(REPO=trade-data)一致,避免双副本写偏。"""
    best, best_date = None, ""
    for r in _candidate_repos():
        ov = r / "static-site" / "data" / "overview.json"
        if not ov.exists():
            continue
        try:
            d = json.loads(ov.read_text(encoding="utf-8")).get("date", "")
        except Exception:
            d = ""
        if d > best_date:  # 严格大于:同日期保留先出现者(trade-data 在前)
            best_date, best = d, r
    if best is None:
        best = _candidate_repos()[0]
    return best


def pick_db(repo: Path) -> Path:
    """挑 daily_metric MAX(date) 最新的 sentiment.db(主库优先,镜像兜底;同日期优先 trade-data)。"""
    best, best_date = None, ""
    for r in _candidate_repos():
        db = r / "data" / "sentiment.db"
        if not db.exists():
            continue
        m = ""
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
            cur = conn.cursor()
            cur.execute("SELECT MAX(date) FROM daily_metric")
            m = (cur.fetchone() or [""])[0] or ""
            conn.close()
        except Exception:
            m = ""
        if m > best_date:
            best_date, best = m, db
    return best or repo / "data" / "sentiment.db"


def load_env() -> None:
    """加载 .env(deepseek/R2 凭证)。按 upload_r2.py 同款候选路径,setdefault 不覆盖。"""
    candidates = [
        ROOT / ".env",
        Path(os.environ.get("GIT_REPO", "")) / ".env" if os.environ.get("GIT_REPO") else None,
        Path(os.environ.get("REPO", "")) / ".env" if os.environ.get("REPO") else None,
        MAIN_REPO / ".env",
        Path("/Users/linhuichen/code/trade/.env"),
    ]
    for c in candidates:
        if not c or not c.exists():
            continue
        for line in c.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


# ── 配置 ─────────────────────────────────────────────────────────────────
def load_config() -> dict:
    if yaml is None:
        sys.exit("缺少 pyyaml,请 .venv 安装: pip install pyyaml")
    path = ROOT / "config" / "daily_brief.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg.setdefault("schedule_enabled", False)
    cfg.setdefault("compliance_enabled", True)
    cfg.setdefault("model", "deepseek-chat")
    cfg.setdefault("timeout_seconds", 60)
    cfg.setdefault("max_retries", 2)
    cfg.setdefault("temperature", 0.4)
    cfg.setdefault("max_watch_items", 5)
    cfg.setdefault("disclaimer", "AI 生成,研究用途,不构成投资建议。基于 {date} 收盘数据,历史命中率不代表未来。")
    cfg.setdefault("cost_log", "data/daily_brief_cost.log")
    cfg.setdefault("input_price_per_million", 2.0)
    cfg.setdefault("output_price_per_million", 8.0)
    cfg.setdefault("monthly_warn_yuan", 20.0)
    cfg.setdefault("review_enabled", True)
    return cfg


# ── 数据加载(P1-8 数据锚定:以 JSON 结构给模型)────────────────────────────
def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _db_metrics(conn: sqlite3.Connection, date: str, metric_ids: list[str]) -> dict:
    out = {}
    cur = conn.cursor()
    for mid in metric_ids:
        cur.execute(
            "SELECT value FROM daily_metric WHERE date=? AND metric_id=?", (date, mid)
        )
        row = cur.fetchone()
        out[mid] = round(row[0], 2) if row and row[0] is not None else None
    return out


def load_data(static_dir: Path, db_path: Path, date: str) -> dict:
    """注入数据聚合(全部站点已有,JSON 结构化给模型)。"""
    d: dict = {"date": date}

    # ── static-site/data/ JSON ──
    summary = _read_json(static_dir / "summary.json") or {}
    d["summary"] = {
        "summary_short": summary.get("summary_short"),
        "summary": summary.get("summary"),
        "sentiment_label": summary.get("sentiment_label"),
        "sentiment_score": summary.get("sentiment_score"),
        "fear_greed_value": summary.get("fear_greed_value"),
        "fear_greed_label": summary.get("fear_greed_label"),
        "sh_pct": summary.get("sh_pct"),
        "sh_close": summary.get("sh_close"),
        "up_count": summary.get("up_count"),
        "down_count": summary.get("down_count"),
        "zt_count": summary.get("zt_count"),
        "dt_count": summary.get("dt_count"),
        "buy_count": summary.get("buy_count"),
        "sell_count": summary.get("sell_count"),
        "volume_amount": summary.get("volume_amount"),
        "volume_label": summary.get("volume_label"),
        "ma_bullish": summary.get("ma_bullish"),
        "ma_bearish": summary.get("ma_bearish"),
        "top_industries": [t.get("name") for t in (summary.get("top_industries") or [])[:3]],
        "bottom_industries": [t.get("name") for t in (summary.get("bottom_industries") or [])[:3]],
    }

    ov = _read_json(static_dir / "overview.json") or {}
    d["signals_today"] = [
        {
            "index_id": s.get("index_id"),
            "name": s.get("name"),
            "signal": s.get("signal"),
            "reason": (s.get("reason") or "")[:80],
        }
        for s in (ov.get("signals_today") or [])[:20]
    ]
    # index_id -> 可读名 映射(供 watch_list/规则版展示;优先 signals_today.name)
    d["name_map"] = {s.get("index_id"): s.get("name") for s in (ov.get("signals_today") or []) if s.get("index_id") and s.get("name")}
    d["signals_today_count"] = len(ov.get("signals_today") or [])
    d["recent_freeze"] = [f.get("date") for f in (ov.get("recent_freeze") or [])[-5:]]
    d["industry_heatmap_top"] = [
        {"name": h.get("name"), "pct_1d": round(h["pct_1d"], 2) if h.get("pct_1d") is not None else None}
        for h in (ov.get("industry_heatmap") or [])[:10]
    ]

    alert = _read_json(static_dir / "alert.json") or {}
    d["alert"] = {
        "high": {
            "score": alert.get("high", {}).get("score"),
            "level": alert.get("high", {}).get("level"),
            "hit_dims": [f"{x.get('k')}{x.get('name')}={round(x['score'],1)}"
                         for x in (alert.get("high", {}).get("dims") or []) if x.get("hit")],
        },
        "low": {
            "score": alert.get("low", {}).get("score"),
            "level": alert.get("low", {}).get("level"),
            "hit_dims": [f"{x.get('k')}{x.get('name')}={round(x['score'],1)}"
                         for x in (alert.get("low", {}).get("dims") or []) if x.get("hit")],
        },
    }

    # 信号历史胜率:buy 系 20d 胜率 top(明日关注排序依据,P1-4 简化版)
    stats = _read_json(static_dir / "signal_stats.json") or {}
    buy_rank = []
    for iid, st in stats.items():
        for sig in ("buy", "buy_aux", "buy_special", "buy_backup"):
            s20 = (st.get(sig) or {}).get("20d") or {}
            wr = s20.get("win_rate")
            n = s20.get("n") or 0
            if wr is not None and n >= 10:
                buy_rank.append({
                    "index_id": iid,
                    "name": d["name_map"].get(iid, iid),
                    "signal": sig, "win_rate": round(wr, 3), "n": n,
                })
    buy_rank.sort(key=lambda x: (x["win_rate"], x["n"]), reverse=True)
    d["signal_stats_buy_top"] = buy_rank[:10]

    # 期货机构净多(P0-2 主维度) + 结论
    ft = _read_json(static_dir / "futures_acc_trend.json") or {}
    dates = ft.get("dates") or []
    series = ft.get("series") or ft
    if dates:
        # 取最近 3 个交易日的净多趋势(结构: {dates:[...], ...series})
        trend_tail = {}
        for k, v in ft.items():
            if k in ("dates",) or not isinstance(v, list) or len(v) != len(dates):
                continue
            trend_tail[k] = {"date": dates[-1], "last": round(v[-1], 2) if v[-1] is not None else None,
                             "d5_chg": round(v[-1] - v[-5], 2) if len(v) >= 5 and v[-1] is not None and v[-5] is not None else None}
        d["futures_acc_trend_tail"] = trend_tail
    fc = _read_json(static_dir / "futures_acc_conclusion.json") or {}
    d["futures_acc_conclusion"] = fc.get("current_state") or {}

    # ── DB(daily_metric / score_daily / index_daily) ──
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
    try:
        # P0-2:资金面。a_fund_north 是成交总额(恒正,活跃度)不当方向;
        # 主维度 futures_acc_trend(已在上面)+ hk_south(当日真方向) + a_fund_north_quarterly(季度口径)。
        funds = _db_metrics(conn, date, [
            "a_fund_main", "a_fund_margin",
            "a_fund_north", "a_fund_north_quarterly", "hk_south",
            "a_qvix_300", "a_qvix_1000",
            "a_rotation_5d", "a_rotation_10d", "a_rotation_20d",
            "a_rotation_concept_5d", "a_rotation_concept_10d", "a_rotation_concept_20d",
            "a_width_fengban_rate", "a_width_max_lianban", "a_width_zhaban_rate",
            "a_turnover_mean", "a_turnover_p90", "a_turnover_gt5_pct",
            "a_volume_ratio", "a_volume_signal",
            "a_amount", "a_amount_ma5", "a_amount_ma20",
        ])
        # 北向季度反算:DB 里是 20260630 单行,查询最近一行带日期
        q = conn.cursor()
        q.execute("SELECT date, value FROM daily_metric WHERE metric_id='a_fund_north_quarterly' AND value IS NOT NULL ORDER BY date DESC LIMIT 1")
        qr = q.fetchone()
        north_quarterly = {"date": qr[0], "value": round(qr[1], 2)} if qr else None
        # 南向当日真方向(可正负)
        d["funds"] = funds
        d["north_quarterly"] = north_quarterly  # 标注:季度口径,非日频
        d["funds_note"] = (
            "口径说明: a_fund_north 为北向成交总额(恒正,市场活跃度)非外资方向,不得当方向断言;"
            "外资方向参考 a_fund_north_quarterly(季度反算,滞后,仅中期参考);"
            "南向 hk_south 为当日净买入(正=流入);机构资金态度以 futures_acc_trend 机构净多变化为主。"
        )

        # 情绪分(score_daily)
        q.execute("SELECT score_id, value FROM score_daily WHERE date=? AND score_id IN "
                  "('a_sentiment','fear_greed','sentiment_sz50','sentiment_hs300','sentiment_csi500',"
                  "'sentiment_csi1000','sentiment_cyb','sentiment_kc50')", (date,))
        d["scores"] = {r[0]: round(r[1], 1) for r in q.fetchall() if r[1] is not None}

        # 指数涨跌(index_daily)
        q.execute("SELECT index_id, pct_change, close FROM index_daily WHERE date=? AND index_id IN "
                  "('sh','sz','hs300','csi500','csi1000','cyb','kc50','sz50')", (date,))
        d["indices"] = {r[0]: {"pct_change": round(r[1], 2) if r[1] is not None else None,
                               "close": round(r[2], 2) if r[2] is not None else None} for r in q.fetchall()}
    finally:
        conn.close()
    return d


# ── 规则版兜底(P1-9 失败降级:version="rule")──────────────────────────────
def generate_rule_brief(date: str, data: dict, cfg: dict) -> dict:
    """规则版:不调 AI,从注入数据拼 4 段 + meta 断言。"""
    summary = data.get("summary") or {}
    scores = data.get("scores") or {}

    review = summary.get("summary_short") or "今日A股收盘数据缺失。"

    # trend:均线多空 + 量能
    mb, mbear = summary.get("ma_bullish") or 0, summary.get("ma_bearish") or 0
    if mb >= 6:
        trend = f"均线{mb}多{mbear}空,多头排列,趋势向好。"
    elif mbear >= 6:
        trend = f"均线{mb}多{mbear}空,空头排列,趋势偏弱。"
    else:
        trend = f"均线{mb}多{mbear}空,多空均势,震荡格局。"
    vol = summary.get("volume_label")
    if vol:
        trend += f"成交额{round(summary.get('volume_amount') or 0, 0):.0f}亿,{vol}。"

    # watch:高胜率买点信号 top + 行业热点
    watch_parts = []
    seen = set()
    for x in data.get("signal_stats_buy_top") or []:
        if x["index_id"] in seen:
            continue
        seen.add(x["index_id"])
        watch_parts.append(f"{x.get('name') or x['index_id']}({x['signal']},20日胜率{round(x['win_rate']*100):.0f}%)")
        if len(watch_parts) >= cfg.get("max_watch_items", 5):
            break
    for t in (summary.get("top_industries") or [])[:2]:
        watch_parts.append(f"板块:{t}")
    watch = "、".join(watch_parts[:cfg.get("max_watch_items", 5)]) or "无明显高胜率信号,留意大盘量能。"

    # risk:alert 命中维度 + 资金分歧(只引用数据,不指令)
    risks = []
    for k in ("high", "low"):
        for dim in (data.get("alert") or {}).get(k, {}).get("hit_dims") or []:
            risks.append(f"{k.upper()}预警{dim}")
    funds = data.get("funds") or {}
    if funds.get("a_fund_main") is not None and funds.get("a_fund_main") < -200:
        risks.append(f"主力资金净流出{abs(funds['a_fund_main']):.0f}亿")
    if funds.get("hk_south") is not None and funds.get("hk_south") < 0:
        risks.append(f"南向资金净流出{abs(funds['hk_south']):.0f}亿")
    if funds.get("a_qvix_300") is not None and funds.get("a_qvix_300") > 25:
        risks.append(f"QVIX_300={funds['a_qvix_300']}(波动率偏高)")
    risk = "、".join(risks[:3]) or "无显著风险点。"

    # direction(规则)
    bc, sc = summary.get("buy_count") or 0, summary.get("sell_count") or 0
    sh = summary.get("sh_pct")
    fg = summary.get("fear_greed_value")
    if sc > bc and (sh is None or sh < 0):
        direction = "down"
    elif bc > sc and (sh is None or sh > 0):
        direction = "up"
    elif fg is not None and fg < 15:
        direction = "up"  # 冰点反向观察
    elif fg is not None and fg > 85:
        direction = "down"  # 亢奋降温
    else:
        direction = "flat"

    watch_list = [
        {"index_id": x["index_id"], "name": x.get("name") or x["index_id"], "win_rate": x["win_rate"]}
        for x in (data.get("signal_stats_buy_top") or [])[:cfg.get("max_watch_items", 5)]
    ]
    risk_items = [r for r in risks[:3]]
    return {
        "meta": {
            "date": date,
            "version": "rule",
            "direction": direction,
            "watch_list": watch_list,
            "risk_items": risk_items,
            "hit": {"direction": None, "actual_sh_pct": None, "actual_direction": None},
        },
        "text": {"review": review, "trend": trend, "watch": watch, "risk": risk},
    }


# ── summary 最小版兜底(P1-9 最后一级,绝不让主流程失败)────────────────────
def generate_minimal_brief(date: str, data: dict) -> dict:
    summary = data.get("summary") or {}
    return {
        "meta": {
            "date": date,
            "version": "minimal",
            "direction": "flat",
            "watch_list": [],
            "risk_items": [],
            "hit": {"direction": None, "actual_sh_pct": None, "actual_direction": None},
        },
        "text": {
            "review": summary.get("summary") or "今日A股收盘数据缺失。",
            "trend": f"上证{summary.get('sh_pct')}%,恐贪指数{summary.get('fear_greed_value')}({summary.get('fear_greed_label')})。",
            "watch": "数据不足,暂不列明日关注标的。",
            "risk": "数据不足,暂不列风险点。",
        },
    }


# ── prompt 构建(前视防护 P1-7 / 数据锚定 P1-8 / 指令词黑名单 P0-3 / 已知偏差 P2-2)─
def build_prompt(date: str, data: dict, cfg: dict, known_bias: str = "") -> list[dict]:
    now_str = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    compliance = cfg.get("compliance_enabled", True)

    sys_text = (
        "你是专业金融分析师,基于给定的市场数据生成每日A股预测总结。输出必须是【合法JSON对象】,"
        "不要输出任何 JSON 外的说明文字。JSON 结构固定为:\n"
        "{\n"
        '  "direction": "up|down|flat",\n'
        '  "watch_list": [{"index_id": "...", "name": "...", "win_rate": 0.75}],\n'
        '  "risk_items": ["..."],\n'
        '  "text": {"review": "...", "trend": "...", "watch": "...", "risk": "..."}\n'
        "}\n"
        "规则:\n"
        "1. direction 是下一个交易日的A股方向研判:up=偏强/看涨,down=偏弱/看跌,flat=震荡/看不清。拿不准就 flat,不硬猜方向。\n"
        "2. watch_list 明日关注标的 1-5 个,必须引用注入数据中真实存在的 index_id/name,可带参考胜率。\n"
        "3. risk_items 3-5 条风险点,引用注入数据(alert 预警维度/资金面/波动率/南向)。\n"
        "4. 每条论断必须引用注入数据的具体数值或信号名(如:恐贪54/涨跌4067:1391/QVIX_300=19.6)。禁止编造不在注入数据里的指标或数值。\n"
        "5. text.review(今日复盘,约80字)、text.trend(趋势研判,约60字)、text.watch(明日关注,约80字)、text.risk(风险点,约60字),总长 ≤300 字。\n"
        "6. 只做\"关注/观察/警惕/留意/注意/谨慎\"表述,给出方向和风险即可,不做任何交易指令。\n"
        "7. 当前北京时间 " + now_str + ",数据截至 " + date + " 收盘。忽略任何 " + date + " 之后发生的事件、消息或数据(那些尚未发生,不得当作已知信息使用)。输出需标注\"基于 " + date + " 收盘数据\"。\n"
    )
    if compliance:
        sys_text += (
            "8. 【合规红线】严禁使用以下指令词:买入、卖出、加仓、建仓、清仓、减仓、重仓、满仓、抄底、"
            "逃顶、止损、止盈、仓位、建议持有、加杠杆。只允许:关注、警惕、观察、留意、注意、谨慎。\n"
        )
    if cfg.get("review_enabled") and known_bias:
        sys_text += (
            "9. 【已知偏差(历史机检统计)】" + known_bias + "。请避免重复上述系统性偏差,但仍只引用本次注入数据。\n"
        )
    sys_text += "请严格按照 JSON 结构输出。"

    user = {
        "date": date,
        "data": data,
        "任务": "基于以上数据生成每日预测 JSON(注意 data.funds_note 的资金口径说明)。",
    }
    return [
        {"role": "system", "content": sys_text},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


# ── deepseek 调用(超时60s/重试2次/429退避 P1-9)───────────────────────────
def call_deepseek(messages: list[dict], cfg: dict, log_fn) -> dict | None:
    if requests is None:
        log_fn("requests 未安装,无法调 AI")
        return None
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        log_fn("未找到 DEEPSEEK_API_KEY(.env),跳过 AI")
        return None
    base = (os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1").rstrip("/")
    model = os.environ.get("DEEPSEEK_MODEL") or cfg.get("model", "deepseek-chat")
    url = base + "/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": messages,
        "temperature": float(cfg.get("temperature", 0.4)),
        "max_tokens": 1200,
        "response_format": {"type": "json_object"},
    }
    timeout = float(cfg.get("timeout_seconds", 60))
    retries = int(cfg.get("max_retries", 2))
    for attempt in range(retries + 1):
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                wait = 2 ** (attempt + 1)
                log_fn(f"deepseek 429 限流,退避 {wait}s(第{attempt + 1}次)")
                time.sleep(wait)
                continue
            log_fn(f"deepseek HTTP {r.status_code}: {r.text[:200]}")
            if r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            return None
        except (requests.Timeout, requests.ConnectionError) as e:
            log_fn(f"deepseek 请求异常({type(e).__name__}),第{attempt + 1}次")
            time.sleep(2 ** attempt)
    return None


# ── 解析+校验输出(P0-1/P1-8 数据锚定校验)─────────────────────────────────
def _extract_json(text: str) -> dict | None:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def parse_ai_output(raw: dict | None, data: dict, date: str) -> dict | None:
    if not raw:
        return None
    try:
        content = raw["choices"][0]["message"]["content"]
        usage = raw.get("usage") or {}
    except Exception:
        return None
    parsed = _extract_json(content)
    if not parsed:
        return None
    direction = parsed.get("direction")
    if direction not in ("up", "down", "flat"):
        direction = "flat"
    text = parsed.get("text") or {}
    text = {
        "review": str(text.get("review") or "").strip(),
        "trend": str(text.get("trend") or "").strip(),
        "watch": str(text.get("watch") or "").strip(),
        "risk": str(text.get("risk") or "").strip(),
    }
    # 数据锚定:watch_list 只保留注入数据中存在的 index_id(P1-8)
    # 强制校验注入集合(P1-2 reviewer 复核:injected_ids 曾只定义未使用,AI 编造 index_id 会直进展示)
    injected_ids = {
        x.get("index_id") for x in (data.get("signals_today") or [])
    } | {x.get("index_id") for x in (data.get("signal_stats_buy_top") or [])}
    watch_list = []
    for w in (parsed.get("watch_list") or [])[:5]:
        if not isinstance(w, dict):
            continue
        iid = str(w.get("index_id") or "").strip()
        if not iid or iid not in injected_ids:
            continue
        watch_list.append({
            "index_id": iid,
            "name": str(w.get("name") or iid)[:40],
            "win_rate": round(float(w.get("win_rate") or 0), 3) if w.get("win_rate") is not None else None,
        })
    risk_items = [str(r)[:80] for r in (parsed.get("risk_items") or [])[:5] if str(r).strip()]
    return {
        "meta": {
            "date": date,
            "version": "ai",
            "direction": direction,
            "watch_list": watch_list,
            "risk_items": risk_items,
            "hit": {"direction": None, "actual_sh_pct": None, "actual_direction": None},
        },
        "text": text,
        "_usage": usage,
    }


# ── 合规脱敏(P0-3 正则兜底)───────────────────────────────────────────────
def scrub_text(text: str, cfg: dict) -> str:
    if not cfg.get("compliance_enabled", True):
        return text
    out = text
    # 强指令模式整句降级
    def _strip_strong(m):
        return re.sub(r"建议\s*\S+", "留意", m.group(0))
    out = STRONG_INSTRUCTION_RE.sub(_strip_strong, out)
    # 普通指令词替换
    for w in FORBIDDEN_WORDS:
        out = out.replace(w, SCRUB_MAP.get(w, "关注"))
    # 残余指令词防御性剔除(如"满仓"未命中映射时)
    remain = [w for w in FORBIDDEN_WORDS if w in out]
    if remain:
        for w in remain:
            out = out.replace(w, "关注")
    return out


# ── 历史归档 + 次日 hit 回填(P0-1)───────────────────────────────────────
HISTORY_FILE = "daily_brief_history.json"
BRIEF_FILE = "daily_brief.json"
HISTORY_LIMIT = 90
HIT_THRESHOLD = 0.1  # 涨跌幅 >0.1% 才算 up/down,否则 flat


def _load_history(static_dir: Path) -> list[dict]:
    p = static_dir / HISTORY_FILE
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d.get("items") or []
    except Exception:
        return []


def _actual_direction(pct: float | None) -> str | None:
    if pct is None:
        return None
    if pct > HIT_THRESHOLD:
        return "up"
    if pct < -HIT_THRESHOLD:
        return "down"
    return "flat"


def backfill_hits(history: list[dict], db_path: Path, today: str) -> None:
    """对 history 中未回填(hit.direction=None)的条目,用其下一交易日实际 sh 涨跌幅回填。
    today=本次生成日期,只回填 date < today 的条目,避免回填"未来"。"""
    if not history:
        return
    # 只回填未判定条目(hit.direction is None);miss=False 也算已判定,避免每次重跑重扫(P2-1)
    pending = [it for it in history if (it.get("meta", {}).get("hit", {}).get("direction") is None)]
    if not pending:
        return
    # 一次性加载 index_daily sh 全表(date->pct_change)
    sh_map = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
        cur = conn.cursor()
        cur.execute("SELECT date, pct_change FROM index_daily WHERE index_id='sh' ORDER BY date")
        for r in cur.fetchall():
            if r[0] not in sh_map:
                sh_map[r[0]] = r[1]
        conn.close()
    except Exception:
        return
    dates = sorted(sh_map.keys())
    for it in history:
        meta = it.setdefault("meta", {})
        hit = meta.setdefault("hit", {})
        if hit.get("direction") is not None or not dates:
            continue
        bdate = it.get("date") or meta.get("date")
        if not bdate or bdate >= today:
            continue
        # 找 bdate 之后第一个有 sh 数据的交易日
        nxt = next((x for x in dates if x > bdate), None)
        if nxt is None:
            continue
        pct = sh_map.get(nxt)
        hit["actual_sh_pct"] = round(pct, 2) if pct is not None else None
        hit["actual_direction"] = _actual_direction(pct)
        if hit["actual_direction"]:
            pred = meta.get("direction")
            hit["direction"] = bool(pred and pred == hit["actual_direction"])
        it["_backfilled_via"] = nxt


def _history_stats(history: list[dict]) -> dict:
    """近30/90日方向命中率。"""
    def _calc(n):
        items = [it for it in history[:n] if it.get("meta", {}).get("hit", {}).get("direction") is not None]
        if not items:
            return {"n": 0, "hit": 0, "hit_rate": None}
        hits = sum(1 for it in items if it["meta"]["hit"]["direction"])
        return {"n": len(items), "hit": hits, "hit_rate": round(hits / len(items), 3)}
    return {"30d": _calc(30), "90d": _calc(90)}


def write_outputs(static_dir: Path, brief: dict, cfg: dict) -> dict:
    """写 daily_brief.json + 归档 history + 返回 stats。"""
    static_dir.mkdir(parents=True, exist_ok=True)
    date = brief["meta"]["date"]
    disclaimer = cfg.get("disclaimer", "").replace("{date}", date)
    brief["disclaimer"] = disclaimer
    brief["generated_at"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # text.note 末尾追加免责(展示层)
    brief["text"]["note"] = disclaimer

    # 归档
    history = _load_history(static_dir)
    # 删除同 date 旧条目(幂等重跑)
    history = [it for it in history if (it.get("date") or it.get("meta", {}).get("date")) != date]
    item = {
        "date": date,
        "meta": brief["meta"],
        "text": brief["text"],
        "disclaimer": disclaimer,
    }
    history.insert(0, item)
    history = history[:HISTORY_LIMIT]

    stats = _history_stats(history)
    hist_out = {"items": history, "total": len(history), "offset": 0, "limit": HISTORY_LIMIT, "stats": stats}

    (static_dir / BRIEF_FILE).write_text(
        json.dumps(brief, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (static_dir / HISTORY_FILE).write_text(
        json.dumps(hist_out, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return stats


# ── 成本监控(P2-1)────────────────────────────────────────────────────────
def _cost_log_path(repo: Path, cfg: dict) -> Path:
    p = Path(cfg.get("cost_log", "data/daily_brief_cost.log"))
    return p if p.is_absolute() else repo / p


def log_cost(repo: Path, cfg: dict, date: str, version: str, usage: dict | None, ok: bool) -> None:
    pt = (usage or {}).get("prompt_tokens") or 0
    ct = (usage or {}).get("completion_tokens") or 0
    cost = (pt / 1e6) * float(cfg.get("input_price_per_million", 2.0)) + \
           (ct / 1e6) * float(cfg.get("output_price_per_million", 8.0))
    line = f"{date}\t{_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\t{version}\t{pt}\t{ct}\t{cost:.4f}\t{'ok' if ok else 'fail'}\n"
    p = _cost_log_path(repo, cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(line)
    # 月度汇总 + 超阈值告警
    # 日志首列 date 格式 YYYYMMDD(20260810 无横线),month 用 %Y-%m 是 2026-08 有横线,
    # 直接 startswith(month) 恒 False 致月度累计恒0(P1-1 reviewer 复核 bug)。
    try:
        month = _dt.datetime.now().strftime("%Y-%m").replace("-", "")  # -> "202608"
        total = 0.0
        for ln in p.read_text(encoding="utf-8").splitlines():
            parts = ln.split("\t")
            if len(parts) >= 7 and parts[0].startswith(month):
                try:
                    total += float(parts[5])
                except Exception:
                    pass
        warn = float(cfg.get("monthly_warn_yuan", 20.0))
        if total > warn:
            try:
                subprocess.run(
                    [str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/notify.py"),
                     f"[告警] daily_brief 月度费用超阈值 ¥{total:.2f}",
                     f"本日调用 cost ¥{cost:.4f},月度累计 ¥{total:.2f} > ¥{warn}<br>日志: {p}",
                     "--from-prefix", "[告警]"], timeout=30, capture_output=True, check=False)
            except Exception:
                pass
    except Exception:
        pass


# ── R2 上传(数据走 R2,上传后前端可读)─────────────────────────────────────
def upload_to_r2(repo: Path, no_upload: bool) -> None:
    """上传 daily_brief*.json 到 R2 data/ 前缀 + purge edge cache。
    必须传 REPO=repo 给 upload_r2.py,否则其 STATIC_DIR 解析到 trade/ 而非本脚本写入的 trade-data/,
    会读空目录或旧文件导致 R2 内容错位(export-output-path-sync 同源陷阱)。"""
    if no_upload:
        return
    env = dict(os.environ)
    env.setdefault("REPO", str(repo))
    try:
        r = subprocess.run(
            [str(repo / ".venv/bin/python"), str(repo / "scripts/upload_r2.py"),
             "upload-data-files", BRIEF_FILE, HISTORY_FILE],
            cwd=str(repo), env=env, timeout=120, capture_output=True, check=False)
        out = (r.stdout or b"").decode("utf-8", errors="replace").strip()
        err = (r.stderr or b"").decode("utf-8", errors="replace").strip()
        if r.returncode == 0 and out:
            print(f"[R2] {out.splitlines()[-1]}")
        else:
            print(f"⚠ R2 上传 rc={r.returncode} {out[-300:] if out else ''} {err[-300:] if err else ''}")
    except Exception as e:
        print(f"⚠ R2 上传异常(不阻塞): {e}")


# ── staticdata 同步(数据仓库留档/复原,防 deploy 外生成器留旧版)──────────
def staticdata_sync(repo: Path, no_upload: bool) -> None:
    """同步 daily_brief*.json 到 staticdata 数据仓库(trade-data-signal-staticdata)。

    背景: staticdata 同步原依赖 deploy.sh 每次 deploy 后全量 rsync;但本脚本是 deploy
    外独立生成器(只写 static-site/data/ + R2 上传,不跑 deploy.sh) → staticdata 留旧版
    直到下次 deploy(同步时机缺口,见 docs/staticdata-daily-brief-sync.md §二)。
    这里调 scripts/staticdata_sync.sh(daily-brief 触发名),脚本内部持 /tmp/trade_deploy.lock
    阻塞防与 deploy.sh staticdata 段并发写同一 git 仓库,best-effort 失败不阻塞本流程。
    必须传 REPO=repo(同 upload_to_r2,防 static-site 路径解析到 trade/ 非本脚本写入目录)。"""
    if no_upload:
        return
    env = dict(os.environ)
    env.setdefault("REPO", str(repo))
    try:
        r = subprocess.run(
            ["bash", str(repo / "scripts/staticdata_sync.sh"), "daily-brief",
             BRIEF_FILE, HISTORY_FILE],
            cwd=str(repo), env=env, timeout=600, capture_output=True, check=False)
        out = (r.stdout or b"").decode("utf-8", errors="replace").strip()
        err = (r.stderr or b"").decode("utf-8", errors="replace").strip()
        if r.returncode == 0 and out:
            print(f"[staticdata] {out.splitlines()[-1]}")
        elif r.returncode != 0:
            print(f"⚠ staticdata 同步 rc={r.returncode} {out[-300:] if out else ''} {err[-300:] if err else ''}")
    except Exception as e:
        print(f"⚠ staticdata 同步异常(不阻塞): {e}")


# ── 已知偏差(P2-2 阶段1:从 history 统计偏差注入 prompt)──────────────────
def compute_known_bias(history: list[dict]) -> str:
    if not history:
        return ""
    scored = [it for it in history if it.get("meta", {}).get("hit", {}).get("direction") is not None]
    if not scored:
        return ""
    up_pred = [it for it in scored if it["meta"]["direction"] == "up"]
    down_pred = [it for it in scored if it["meta"]["direction"] == "down"]
    up_hit = sum(1 for it in up_pred if it["meta"]["hit"]["direction"])
    down_hit = sum(1 for it in down_pred if it["meta"]["hit"]["direction"])
    s = f"近{len(scored)}次可回测预测中,看涨{len(up_pred)}次命中{up_hit}次,看跌{len(down_pred)}次命中{down_hit}次。"
    if len(down_pred) >= 3 and down_hit / len(down_pred) < 0.5:
        s += "看跌判断命中率偏低,请对看跌倾向更谨慎(可多给震荡)。"
    if len(up_pred) >= 3 and up_hit / len(up_pred) < 0.5:
        s += "看涨判断命中率偏低,请对看涨倾向更谨慎(可多给震荡)。"
    return s


# ── 主流程 ───────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="每日AI预测(daily_brief)生成脚本")
    ap.add_argument("--date", default="", help="预测日期 YYYYMMDD(默认取 overview.date)")
    ap.add_argument("--mock", action="store_true", help="不真调 deepseek,用固定 mock 输出(测试)")
    ap.add_argument("--rule-only", action="store_true", help="强制走规则版(跳过 AI,测试降级)")
    ap.add_argument("--no-upload", action="store_true", help="跳过 R2 上传")
    args = ap.parse_args()

    load_env()
    cfg = load_config()
    repo = pick_repo()
    static_dir = repo / "static-site" / "data"
    db_path = pick_db(repo)

    date = args.date
    if not date:
        ov = _read_json(static_dir / "overview.json") or {}
        date = ov.get("date") or _dt.date.today().strftime("%Y%m%d")

    def log(msg: str) -> None:
        print(f"[gen_daily_brief] {msg}")

    log(f"repo={repo} date={date} db={db_path.name} compliance={cfg.get('compliance_enabled')}")

    # 数据注入
    data = load_data(static_dir, db_path, date)
    history = _load_history(static_dir)

    # 成本/失败链状态
    usage = None
    version = "ai"
    brief = None

    if not args.rule_only and not args.mock:
        # 主链路:AI 生成
        known_bias = compute_known_bias(history) if cfg.get("review_enabled") else ""
        messages = build_prompt(date, data, cfg, known_bias)
        raw = call_deepseek(messages, cfg, log)
        if raw:
            parsed = parse_ai_output(raw, data, date)
            if parsed:
                usage = parsed.pop("_usage", None)
                brief = parsed
                log(f"AI 生成成功 direction={brief['meta']['direction']} watch={len(brief['meta']['watch_list'])}")
            else:
                log("AI 输出解析失败,降级规则版")
                version = "rule"
        else:
            log("AI 调用失败/无返回,降级规则版")
            version = "rule"
    elif args.mock:
        # mock:模拟 AI 成功(测试主链路,不真调 API)
        brief = {
            "meta": {
                "date": date, "version": "ai", "direction": "up",
                "watch_list": [{"index_id": "hs300", "name": "沪深300", "win_rate": 0.65}],
                "risk_items": ["均线转弱预警", "主力净流出"],
                "hit": {"direction": None, "actual_sh_pct": None, "actual_direction": None},
            },
            "text": {
                "review": f"{date} A股情绪回暖,上证涨0.67%,多数上涨,成交2.5万亿。",
                "trend": "均线多空均势,震荡格局,量能平稳。",
                "watch": "关注沪深300(20日胜率65%)、高胜率买点信号。",
                "risk": "主力资金净流出、南向净流出。",
            },
        }
        usage = {"prompt_tokens": 1500, "completion_tokens": 300}
        version = "ai"
        log("MOCK 模式(不真调 deepseek)")
    elif args.rule_only:
        version = "rule"
        log("--rule-only: 强制走规则版")

    # 降级链:AI 失败 -> 规则版 -> summary 最小版(P1-9)
    if brief is None:
        try:
            brief = generate_rule_brief(date, data, cfg)
            brief["meta"]["version"] = "rule"
            version = "rule"
            log("降级: 规则版生成")
        except Exception as e:
            log(f"规则版失败({e}),降级 summary 最小版")
            brief = generate_minimal_brief(date, data)
            brief["meta"]["version"] = "minimal"
            version = "minimal"
    if version == "rule":
        brief["meta"]["version"] = "rule"

    # 合规脱敏 + 免责(在 meta 回填前完成 text 层)
    for k in ("review", "trend", "watch", "risk"):
        brief["text"][k] = scrub_text(brief["text"].get(k, ""), cfg)
    if version == "ai" and cfg.get("compliance_enabled"):
        _remains = [w for w in FORBIDDEN_WORDS if any(w in (brief["text"][k] or "") for k in ("review", "trend", "watch", "risk"))]
        if _remains:
            log(f"⚠ 合规校验仍有指令词残留: {_remains}(已在 scrub 阶段处理)")

    # 回填上一日 hit + 写输出
    backfill_hits(history, db_path, date)
    stats = write_outputs(static_dir, brief, cfg)
    log(f"写 {static_dir / BRIEF_FILE} + history({len(history)}条) hit_stats={stats}")

    # 成本日志
    log_cost(repo, cfg, date, version, usage, ok=(version == "ai"))

    # R2 上传
    upload_to_r2(repo, args.no_upload)
    # staticdata 同步(数据仓库留档,防 deploy 外生成器留旧版;best-effort)
    staticdata_sync(repo, args.no_upload)
    log(f"完成 version={version} date={date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
