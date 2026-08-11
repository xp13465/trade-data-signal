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
import concurrent.futures
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

# ── 通知(2026-08-11 追加需求):邮件+飞书报告群 ──────────────────────────────
# import notify(多渠道统一出口)前把 scripts/ 放 sys.path,与 check_signals.py 同款。
sys.path.insert(0, str(ROOT / "scripts"))
import notify  # noqa: E402
import html as _html


def _html_esc(s) -> str:
    """HTML 转义(通知邮件用;页面展示由前端 _esc 处理,此处只发邮件)。"""
    return _html.escape(str(s), quote=True)


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
    # ── 多角色协作式(P0-4,2026-08-11 实施)────────────────────────────────
    #   false = 默认单 prompt 主链路;true = --multi 时走 6 角色编排(验证质量后再开)
    cfg.setdefault("multi_agent_enabled", False)
    cfg.setdefault("researcher_model", "deepseek-chat")  # 可选 deepseek-reasoner(R1 深度辩论,P1-11)
    cfg.setdefault("multi_agent_timeout_seconds", 90)
    cfg.setdefault("max_role_retries", 1)
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
        # 2026-08-11 口径分层（§2.5 卖信号区分修复）：
        #   buy_count/sell_count = 真实指数可交易信号（index_id 非 s.*，与首页
        #   signals_today 过滤口径一致）；buy_sentiment_count/sell_sentiment_count
        #   = 情绪分模拟信号（s.* 前缀，0-100 衍生指标，非可交易标的）。
        #   tradable_* / sentiment_* 为语义化别名，供 prompt 直接引用。
        "buy_count": summary.get("buy_count"),
        "sell_count": summary.get("sell_count"),
        "tradable_buy_count": summary.get("buy_count"),
        "tradable_sell_count": summary.get("sell_count"),
        "buy_sentiment_count": summary.get("buy_sentiment_count"),
        "sell_sentiment_count": summary.get("sell_sentiment_count"),
        "sentiment_buy_count": summary.get("buy_sentiment_count"),
        "sentiment_sell_count": summary.get("sell_sentiment_count"),
        "volume_amount": summary.get("volume_amount"),
        "volume_label": summary.get("volume_label"),
        "ma_bullish": summary.get("ma_bullish"),
        "ma_bearish": summary.get("ma_bearish"),
        "top_industries": [t.get("name") for t in (summary.get("top_industries") or [])[:3]],
        "bottom_industries": [t.get("name") for t in (summary.get("bottom_industries") or [])[:3]],
    }
    d["signals_note"] = (
        "口径说明: summary.buy_count/sell_count(或 tradable_buy_count/tradable_sell_count)"
        "为真实指数可交易信号(指数走势触发,可交易标的);"
        "summary.buy_sentiment_count/sell_sentiment_count(或 sentiment_buy_count/sentiment_sell_count)"
        "为情绪分模拟信号(s.* 前缀,0-100 衍生指标,非可交易标的,仅情绪参考)。"
        "引用时必须区分,情绪分信号须标注'情绪分信号',不得表述为'卖信号 N 个'。"
    )

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
    # 2026-08-11 审计缺口#1修复: export 实际产出结构为
    #   {dates:[...], series:{系列名:[{date,accuracy,follow_ratio,dominant_dir,...}]}, latest:{date,roles}}。
    #   旧代码期望扁平 {dates, 系列:[数值list]} 结构,isinstance(v,list) 对 series(dict) 全跳过 → 注入恒空。
    #   现适配实际结构: 取各系列近 5 日 follow_ratio(同向比例=机构净多方向强度)序列 + 当日 latest.roles。
    ft = _read_json(static_dir / "futures_acc_trend.json") or {}
    series_map = ft.get("series") or {}
    if isinstance(series_map, dict) and series_map:
        trend_tail = {}
        for name, rows in series_map.items():
            if not isinstance(rows, list) or not rows:
                continue
            recent = rows[-5:]
            trend_tail[name] = {
                "last": {
                    "date": recent[-1].get("date"),
                    "follow_ratio": recent[-1].get("follow_ratio"),
                    "dominant_dir": recent[-1].get("dominant_dir"),
                    "accuracy": recent[-1].get("accuracy"),
                },
                "trend": [
                    {"date": r.get("date"), "follow_ratio": r.get("follow_ratio"),
                     "dominant_dir": r.get("dominant_dir")} for r in recent
                ],
                "d5_chg": (round(recent[-1]["follow_ratio"] - recent[-5]["follow_ratio"], 2)
                           if len(recent) >= 5 and recent[-1].get("follow_ratio") is not None
                           and recent[-5].get("follow_ratio") is not None else None),
            }
        d["futures_acc_trend_tail"] = trend_tail
    latest = ft.get("latest") or {}
    if isinstance(latest, dict) and latest.get("roles"):
        d["futures_acc_trend_latest"] = latest  # {date, prev_date, roles:{系列:{follow_ratio,dominant_dir,accuracy,...}}}
    fc = _read_json(static_dir / "futures_acc_conclusion.json") or {}
    d["futures_acc_conclusion"] = fc.get("current_state") or {}

    # ── 机构风向(inst_ih_detail 席位净加仓 15 日 + 准确率,审计缺口#2 注入)──
    # 数据源: futures.json 是 /api/futures 路由的 export(export.py 消费 app/queries.py 产出),
    #   含 citic_ih_detail(中信期货)/inst_ih_detail(机构top20)/guotai_ih_detail(国泰君安) 三角色
    #   4品种(IH/IF/IC/IM)合计净加仓 total_chg vs 上证综指次日涨跌 next_return 的 15 日统计。
    futures = _read_json(static_dir / "futures.json") or {}
    inst_ih = {}
    for key, label in (("citic_ih_detail", "中信期货"), ("inst_ih_detail", "机构top20"),
                       ("guotai_ih_detail", "国泰君安")):
        det = futures.get(key) or {}
        if not det:
            continue
        inst_ih[label] = {
            "dominant_dir": det.get("dominant_dir"),
            "accuracy": det.get("accuracy"),
            "follow_ratio": det.get("follow_ratio"),
            "total_days": det.get("total"),
            "sample": f"{det.get('sample_start')}~{det.get('sample_end')}",
            "recent": [
                {"date": x.get("date"), "total_chg": x.get("total_chg"),
                 "dir": x.get("citic_dir"), "next_return": x.get("next_return"),
                 "correct": x.get("correct")}
                for x in (det.get("details") or [])[-5:]
            ],
        }
    d["inst_ih_trend"] = inst_ih  # 机构风向: 中信/机构top20/国泰君安 席位净加仓 15 日趋势 + 准确率
    d["inst_ih_note"] = (
        "口径说明: inst_ih_trend 为期货席位机构风向(中信期货/机构top20/国泰君安 三角色)4品种"
        "(IH/IF/IC/IM)合计净加仓 total_chg(手) vs 上证综指次日涨跌 next_return(%) 的15日统计:"
        "dominant_dir=主导方向(同向=净加仓方向与次日涨跌一致,逆向=相反), accuracy=15日准确率,"
        "follow_ratio=同向比例。recent 为最近5日逐日 total_chg/next_return/correct。"
        "机构净加仓方向是资金风向的重要参考。"
    )

    # ── ETF 汪汪队(etf_national_team,审计缺口#3 注入)──
    # 数据源: overview.json nt_signals_today(当日异动信号)+ etf_national_team-1m.json(12只跟踪ETF日份额)
    #   + etf_national_team_quarterly.json(季报机构持仓占比 inst_hold_pct)。
    nt = ov.get("nt_signals_today") or {}
    d["etf_national_team"] = {
        "date": nt.get("date"),
        "n_surge": nt.get("n_surge"),
        "n_outflow": nt.get("n_outflow"),
        "n_volume": nt.get("n_volume"),
        "is_resonance": nt.get("is_resonance"),
        "signals": [
            {"code": s.get("code"), "name": s.get("name"), "type": s.get("type"),
             "label": s.get("label"), "share_change_yi": s.get("share_change_yi"),
             "intensity": s.get("intensity"), "note": (s.get("note") or "")[:80]}
            for s in (nt.get("signals") or [])[:10]
        ],
        "recent_7d": nt.get("recent"),
    }
    nt_etfs = (_read_json(static_dir / "etf_national_team-1m.json") or {}).get("etfs") or []
    d["etf_national_team_share"] = []
    for e in nt_etfs[:12]:
        daily = e.get("daily") or []
        if not daily:
            continue
        d["etf_national_team_share"].append({
            "code": e.get("code"), "name": e.get("name"), "index": e.get("index"),
            "last_share_change_yi": daily[-1].get("share_change_yi"),
            "last5": [
                {"date": x.get("date"),
                 "share_change_pct": round(x["share_change_pct"], 2) if x.get("share_change_pct") is not None else None,
                 "share_change_yi": x.get("share_change_yi")}
                for x in daily[-5:]
            ],
        })
    q_etfs = (_read_json(static_dir / "etf_national_team_quarterly.json") or {}).get("etfs") or []
    d["etf_national_team_holders"] = []
    for e in q_etfs[:12]:
        hist = e.get("history") or []
        if not hist:
            continue
        last = hist[-1]
        d["etf_national_team_holders"].append({
            "code": e.get("code"), "name": e.get("name"), "index": e.get("index"),
            "report_date": last.get("report_date"),
            "inst_hold_pct": last.get("inst_hold_pct"),
            "retail_hold_pct": last.get("retail_hold_pct"),
        })
    d["etf_national_team_note"] = (
        "口径说明: etf_national_team 为ETF汪汪队(国家队/机构护盘资金)跟踪: signals=当日异动信号"
        "(type share_outflow 份额流出 / volume_surge 放量), share_change_yi=份额变化(亿份),"
        "intensity=异动强度, n_surge/n_outflow/n_volume=各类异动数量, is_resonance=多信号共振标志,"
        "recent_7d=近7日异动统计; etf_national_team_share=12只跟踪ETF近5日份额变化%(share_change_pct)"
        "与当日份额变化亿份(share_change_yi),正=资金流入增持; etf_national_team_holders=季报机构持仓占比"
        "(inst_hold_pct 机构占比,高=机构/国家队主导)。汪汪队增持/异动是护盘与资金面支撑信号。"
    )

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
            "confidence": 50,
            "confidence_reason": "规则版(非AI),无把握度评分,默认中等",
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
            "confidence": 50,
            "confidence_reason": "数据不足(最小版),默认中等",
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
        '  "confidence": 0-100整数(把握度), "confidence_reason": "1句把握度理由",\n'
        '  "watch_list": [{"index_id": "...", "name": "...", "win_rate": 0.75}],\n'
        '  "risk_items": ["..."],\n'
        '  "highlights": ["2-4条今日要点,每条≤40字,提炼方向+最重要关注与风险,供页面🎯高亮"],\n'
        '  "text": {"review": "...", "trend": "...", "watch": "...", "risk": "..."}\n'
        "}\n"
        "规则:\n"
        "1. direction 是下一个交易日的A股方向研判:up=偏强/看涨,down=偏弱/看跌,flat=震荡/看不清。拿不准就 flat,不硬猜方向。\n"
        "1b. confidence 给本次预测的整体把握度(0-100整数),基于论据充分性/分歧度/数据支持度:"
        "论据充分且信号一致=高把握 70-100;论据较足但有分歧=中等 55-70;论据不足或数据支持弱=低把握 30-55;"
        "方向看不清/数据缺失=0-30。把握度低时 direction 更倾向 flat,不硬猜。"
        "confidence_reason 用 1 句话说明把握度依据(如:量价均多但资金面分歧较大)。\n"
        "2. watch_list 明日关注标的 1-5 个,必须引用注入数据中真实存在的 index_id/name,可带参考胜率。\n"
        "3. risk_items 3-5 条风险点,引用注入数据(alert 预警维度/资金面/波动率/南向)。\n"
        "3b. highlights 2-4 条今日要点(每条≤40字):从方向/把握度/最重要关注/最重要风险中提炼最关键的 2-4 条,"
        "供页面\"🎯今日要点\"高亮展示;精炼概括,不与 watch_list/risk_items 逐条重复。\n"
        "4. 每条论断必须引用注入数据的具体数值或信号名(如:恐贪54/涨跌4067:1391/QVIX_300=19.6)。禁止编造不在注入数据里的指标或数值。\n"
        "4b.【信号口径红线】引用卖/买信号数量时,必须区分两类:真实指数可交易信号"
        "(summary.tradable_buy_count/tradable_sell_count,指数走势触发,可交易标的)与"
        "情绪分模拟信号(summary.sentiment_buy_count/sentiment_sell_count,s.* 前缀,"
        "0-100 衍生指标,非可交易标的,仅情绪参考)。情绪分信号必须标注'情绪分信号',"
        "不得表述为'卖信号 N 个'或'买信号 N 个';只有真实指数可交易信号才能称为"
        "'卖信号/买信号 N 个'。\n"
        "4c.【资金/护盘数据源】资金面可参考: inst_ih_trend(期货席位机构风向,中信/机构top20/"
        "国泰君安 15日净加仓 total_chg 方向+准确率 accuracy+主导方向 dominant_dir,见 inst_ih_note 口径)、"
        "futures_acc_trend_tail(机构净多变化 follow_ratio 同向比例趋势)+futures_acc_trend_latest(当日最新)、"
        "etf_national_team(ETF汪汪队异动信号+份额变化 share_change_yi+is_resonance 共振,见 "
        "etf_national_team_note 口径)+etf_national_team_share(12只跟踪ETF近5日份额变化)。"
        "这些是机构/护盘资金态度的重要证据,应在 trend/risk 中引用具体数值。\n"
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
def call_deepseek(messages: list[dict], cfg: dict, log_fn, model: str | None = None) -> dict | None:
    if requests is None:
        log_fn("requests 未安装,无法调 AI")
        return None
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        log_fn("未找到 DEEPSEEK_API_KEY(.env),跳过 AI")
        return None
    base = (os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1").rstrip("/")
    model = model or os.environ.get("DEEPSEEK_MODEL") or cfg.get("model", "deepseek-chat")
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
    # 把握度 confidence(0-100 整数,与 direction 并列):主编/单 prompt 输出。
    # 类型/范围校验:非数字缺省默认 50;越界 clamp 到 0-100;confidence_reason 截断防超长。
    try:
        confidence = int(round(float(parsed.get("confidence"))))
    except (TypeError, ValueError):
        confidence = 50
    confidence = max(0, min(100, confidence))
    confidence_reason = str(parsed.get("confidence_reason") or "").strip()[:120]
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
    # 今日要点(高亮重点,页面🎯区块): AI 输出 2-4 条,每条≤40字;缺失由 _ensure_highlights 兜底提炼
    highlights = []
    for h in (parsed.get("highlights") or [])[:4]:
        s = str(h).strip().replace("\n", " ")
        if s:
            highlights.append(s[:40])
    return {
        "meta": {
            "date": date,
            "version": "ai",
            "direction": direction,
            "confidence": confidence,
            "confidence_reason": confidence_reason,
            "watch_list": watch_list,
            "risk_items": risk_items,
            "highlights": highlights,
            "hit": {"direction": None, "actual_sh_pct": None, "actual_direction": None},
        },
        "text": text,
        "_usage": usage,
    }


# ═══ 多角色协作式编排(P0-4,2026-08-11 实施) ═══════════════════════════
# 6 角色: ①技术面 ②资金面 ③情绪面 ④风控(①②③④并行) -> ⑤研究员(多空辩论,串行)
#       -> ⑥主编(组装+meta+合规) -> 复用 parse_ai_output 结构(前端零改动)。
# 每角色只喂自己数据域(缩小数据域控幻觉,见 docs/ai-predict-multiagent-plan.md §3.1)。
# 降级链: 任一环节失败 -> 该角色论据缺失或整体降级单 prompt 主链路(保底不破 §3.4)。
# 合规: 主编 sys_text 复用指令词黑名单 + 最终 scrub_text 正则兜底(P0-3)。
# 模型: ①②③④⑥ deepseek-chat;⑤ 研究员 cfg.researcher_model(默认 deepseek-chat,
#       可切 deepseek-reasoner R1 深度辩论 = P1-11)。
# 成本: 各角色 usage 汇总一次写入 cost_log(version=ai-multi,~¥0.05/日)。
def split_domains(d: dict) -> dict:
    """按角色拆分数据域(每角色只喂自己的域,缩小数据域控幻觉)。"""
    s = d.get("summary") or {}
    funds = d.get("funds") or {}
    return {
        "tech": {
            "indices": d.get("indices"),
            "signals_today": d.get("signals_today"),
            "signal_stats_buy_top": d.get("signal_stats_buy_top"),
            "summary": {k: s.get(k) for k in (
                "sh_pct", "sh_close", "ma_bullish", "ma_bearish",
                "nh_count", "nl_count", "nhnl", "volume_amount", "volume_label",
                "tradable_buy_count", "tradable_sell_count", "buy_count", "sell_count")},
            "signals_note": d.get("signals_note"),
        },
        "fund": {
            "funds": funds,
            "futures_acc_trend_tail": d.get("futures_acc_trend_tail"),
            "futures_acc_trend_latest": d.get("futures_acc_trend_latest"),
            "futures_acc_conclusion": d.get("futures_acc_conclusion"),
            "inst_ih_trend": d.get("inst_ih_trend"),
            "inst_ih_note": d.get("inst_ih_note"),
            "north_quarterly": d.get("north_quarterly"),
            "funds_note": d.get("funds_note"),
        },
        "sentiment": {
            "scores": d.get("scores"),
            "recent_freeze": d.get("recent_freeze"),
            "industry_heatmap_top": d.get("industry_heatmap_top"),
            "alert_low": (d.get("alert") or {}).get("low"),
            "summary": {k: s.get(k) for k in (
                "sentiment_label", "sentiment_score", "fear_greed_value",
                "fear_greed_label", "is_freeze", "freeze_info",
                "sentiment_buy_count", "sentiment_sell_count",
                "buy_sentiment_count", "sell_sentiment_count")},
            "rotation_width": {k: funds.get(k) for k in (
                "a_rotation_5d", "a_rotation_10d", "a_rotation_20d",
                "a_rotation_concept_5d", "a_width_fengban_rate",
                "a_width_max_lianban", "a_width_zhaban_rate")},
            "etf_national_team": d.get("etf_national_team"),
            "etf_national_team_share": d.get("etf_national_team_share"),
            "etf_national_team_note": d.get("etf_national_team_note"),
        },
        "risk": {
            "alert": d.get("alert"),
            "risk_funds": {k: funds.get(k) for k in (
                "a_qvix_300", "a_qvix_1000", "a_volume_ratio", "a_volume_signal",
                "a_fund_main", "hk_south", "a_turnover_mean", "a_turnover_p90",
                "a_turnover_gt5_pct")},
            "industry_heatmap_top": d.get("industry_heatmap_top"),
        },
    }


def _role_sys_text(role: str, date: str) -> str:
    now_str = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        f"你是A股{role}分析师,基于注入的【{role}数据域】做分析。输出必须是【合法JSON对象】,"
        "不要输出任何 JSON 外的说明文字。JSON 结构固定为:\n"
        '{"summary":"1-2句结论","observations":["...","..."],'
        '"direction_hint":"up|down|flat","confidence":0.0-1.0,'
        '"signals":[{"type":"real|sentiment","name":"...","count":N,"note":"..."}]}\n'
        "规则:\n"
        "1. observations 2-4 条,每条引用注入数据的具体数值或信号名(如:恐贪54/QVIX=19.6/机构净多+1200)。\n"
        "2. direction_hint 给本角色倾向:up=偏强,down=偏弱,flat=震荡/看不清。拿不准就 flat,不硬猜。\n"
        "3. confidence 0-1 给本角色判断置信度。\n"
        "4. signals 仅当注入数据含信号/计数时列出,必须按 type 标注:"
        "real=真实指数可交易信号(指数走势触发,可交易标的),sentiment=情绪分模拟信号"
        "(s.* 前缀 0-100 衍生指标,非可交易标的,仅情绪参考)。\n"
        f"5. 当前北京时间 {now_str},数据截至 {date} 收盘。忽略 {date} 之后任何事件/消息/数据。\n"
        "6. 只分析注入数据,禁止编造指标或数值。"
    )


def build_role_messages(role: str, domain: dict, date: str, cfg: dict) -> list[dict]:
    user = {
        "date": date,
        "data": domain,
        "任务": f"基于以上【{role}数据域】生成 {role} 分析 JSON。",
    }
    return [
        {"role": "system", "content": _role_sys_text(role, date)},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def _call_role(role: str, messages: list[dict], cfg: dict, log) -> dict | None:
    raw = call_deepseek(messages, cfg, log)
    if not raw:
        return None
    try:
        content = raw["choices"][0]["message"]["content"]
    except Exception:
        return None
    parsed = _extract_json(content)
    if not parsed:
        log(f"角色 {role} 输出解析失败")
        return None
    return {"role": role, "parsed": parsed, "usage": raw.get("usage") or {}}


def run_roles_parallel(domains: dict, date: str, cfg: dict, log) -> tuple[dict, list]:
    """①②③④ 角色并行调用(互不依赖)。返回 ({role: result}, usages)。"""
    results: dict = {}
    usages: list = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(_call_role, role, build_role_messages(role, dom, date, cfg), cfg, log): role
                for role, dom in domains.items()}
        for fut in concurrent.futures.as_completed(futs):
            role = futs[fut]
            try:
                r = fut.result()
            except Exception as e:
                log(f"角色 {role} 异常: {e}")
                r = None
            if r:
                results[role] = r
                usages.append(r.get("usage") or {})
    return results, usages


def _role_block(role: str, r: dict | None) -> str:
    if not r:
        return f"## {role}(角色失败,无论据)"
    p = r["parsed"]
    hint = {"up": "偏多", "down": "偏空", "flat": "震荡"}.get(p.get("direction_hint"), p.get("direction_hint"))
    return (f"## {role}(倾向 {hint},置信度 {p.get('confidence')})\n"
            f"结论: {p.get('summary')}\n"
            f"论据: {'; '.join(p.get('observations') or [])}")


def build_researcher_messages(role_results: dict, date: str, cfg: dict) -> list[dict]:
    now_str = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = [_role_block(role, role_results.get(role)) for role in ("tech", "fund", "sentiment", "risk")]
    user = {
        "date": date,
        "roles": "\n\n".join(parts),
        "任务": "你是A股研究员,做多空辩论后收敛。先分别列出【多头论据】与【空头论据】"
                "(各2-4条,引用各角色论据的具体数值),再给倾向判断与置信度。"
                "倾向必须同时给出支撑与风险,允许'震荡/看不清'。"
                "输出【合法JSON对象】:\n"
                '{"bull":["...","..."],"bear":["...","..."],"lean":"up|down|flat",'
                '"confidence":0.0-1.0,"summary":"1-2句多空融合结论"}',
    }
    sys_text = (
        f"你是A股研究员,对技术/资金/情绪/风控四角色论据做多空对抗辩论并收敛到倾向。当前北京时间 {now_str},"
        f"数据截至 {date} 收盘,忽略 {date} 之后事件。只引用注入论据,禁止编造。"
        "只做\"关注/观察/警惕/留意\"表述,不做任何交易指令。"
    )
    return [
        {"role": "system", "content": sys_text},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def build_editor_messages(role_results: dict, researcher: dict | None, date: str, cfg: dict,
                          data: dict | None = None) -> list[dict]:
    now_str = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    compliance = cfg.get("compliance_enabled", True)
    parts = [_role_block(role, role_results.get(role)) for role in ("tech", "fund", "sentiment", "risk")]
    researcher_block = "无(研究员未输出,基于角色论据自行权衡)"
    if researcher:
        researcher_block = (f"多头论据: {'; '.join(researcher.get('bull') or [])}\n"
                            f"空头论据: {'; '.join(researcher.get('bear') or [])}\n"
                            f"倾向: {researcher.get('lean')} 置信度 {researcher.get('confidence')}\n"
                            f"融合结论: {researcher.get('summary')}")
    sys_text = (
        "你是每日A股预测主编,汇总各角色论据与研究员倾向,组装最终每日预测。输出必须是【合法JSON对象】,"
        "不要输出任何 JSON 外的说明文字。JSON 结构固定为:\n"
        "{\n"
        '  "direction": "up|down|flat",\n'
        '  "confidence": 0-100整数(把握度), "confidence_reason": "1句把握度理由",\n'
        '  "watch_list": [{"index_id": "...", "name": "...", "win_rate": 0.75}],\n'
        '  "risk_items": ["..."],\n'
        '  "highlights": ["2-4条今日要点,每条≤40字,提炼方向+最重要关注与风险,供页面🎯高亮"],\n'
        '  "text": {"review": "...", "trend": "...", "watch": "...", "risk": "..."}\n'
        "}\n"
        "规则:\n"
        "1. direction 是下一交易日A股方向研判:up=偏强/看涨,down=偏弱/看跌,flat=震荡/看不清。拿不准就 flat。\n"
        "1b. confidence 给本次预测的整体把握度(0-100整数),基于多空辩论收敛结果——多空论据充分性/分歧度/数据支持度:"
        "论据充分且多空分歧小=高把握 70-100;论据较足但存在分歧=中等 55-70;论据不足或数据支持弱=低把握 30-55;"
        "方向看不清/数据缺失=0-30。把握度低时 direction 更倾向 flat,不硬猜。"
        "confidence_reason 用 1 句话说明把握度依据(如:多空论据均较充分但资金面分歧较大)。\n"
        "2. watch_list 明日关注标的 1-5 个,必须引用注入数据中真实存在的 index_id/name(数据锚定列表),可带参考胜率。\n"
        "3. risk_items 3-5 条风险点,引用各角色论据(alert 预警/资金面/波动率/南向/情绪极端)。\n"
        "3b. highlights 2-4 条今日要点(每条≤40字):从方向/把握度/最重要关注/最重要风险中提炼最关键的 2-4 条,"
        "供页面\"🎯今日要点\"高亮展示;精炼概括,不与 watch_list/risk_items 逐条重复。\n"
        "4. text.review(今日复盘,约120字)、text.trend(趋势研判,约100字)、text.watch(明日关注,约100字)、"
        "text.risk(风险点,约80字),总长 ≤400 字。每段要体现多角色融合:技术/资金/情绪/风控各至少一处。\n"
        "5. 每条论断引用具体数值或信号名,禁止编造。\n"
        "6. 【信号口径红线】引用卖/买信号数量时区分:真实指数可交易信号(非 s.*)与情绪分模拟信号(s.*,"
        "非可交易标的)。情绪分信号必须标注'情绪分信号',不得表述为'卖信号 N 个'。\n"
        "7. 只做\"关注/观察/警惕/留意/注意/谨慎\"表述,不做任何交易指令。\n"
        f"8. 当前北京时间 {now_str},数据截至 {date} 收盘,忽略 {date} 之后事件。输出标注\"基于 {date} 收盘数据\"。\n"
    )
    if compliance:
        sys_text += (
            "9. 【合规红线】严禁使用:买入、卖出、加仓、建仓、清仓、减仓、重仓、满仓、抄底、逃顶、止损、止盈、"
            "仓位、建议持有、加杠杆。只允许:关注、警惕、观察、留意、注意、谨慎。\n"
        )
    # 数据锚定(P1-8):与 parse_ai_output 同源,watch_list 只允许注入数据真实存在的 index_id
    injected_ids = {
        x.get("index_id") for x in (data.get("signals_today") or []) if data
    } | {x.get("index_id") for x in (data.get("signal_stats_buy_top") or []) if data}
    user = {
        "date": date,
        "roles": "\n\n".join(parts),
        "researcher": researcher_block,
        "signals_note": (data or {}).get("signals_note"),
        "数据锚定(仅这些 index_id 可用于 watch_list)": sorted(injected_ids),
        "任务": "基于以上角色论据+研究员倾向,组装最终每日预测 JSON(注意 signals_note 的信号口径说明)。",
    }
    return [
        {"role": "system", "content": sys_text},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]

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

# ── 结构化运行日志(2026-08-11 审计缺口#4)────────────────────────────────
#   双写: a) static-site/data/daily_brief_run_log.json(随 daily_brief.json 一起 R2 上传+staticdata 同步,前端可读)
#          b) data/logs/daily_brief_run.log(tab 分隔追加行,schedule_monitor grep 用)
#   cost.log 只记 token/费用,run_log 是全流程结构化日志,是扩展不是替换。
RUN_LOG_FILE = "daily_brief_run_log.json"
RUN_LOG_TEXT = "daily_brief_run.log"
RUN_LOG_LIMIT = 30


def _run_cost(usage: dict | None, cfg: dict) -> float:
    """与 log_cost 同口径的调用费用(¥)。"""
    pt = (usage or {}).get("prompt_tokens") or 0
    ct = (usage or {}).get("completion_tokens") or 0
    return (pt / 1e6) * float(cfg.get("input_price_per_million", 2.0)) + \
           (ct / 1e6) * float(cfg.get("output_price_per_million", 8.0))


def write_run_log(repo: Path, static_dir: Path, cfg: dict, entry: dict) -> None:
    """结构化运行日志双写(best-effort,失败不阻塞主流程)。

    entry 字段: date/ts/version/direction/confidence/watch_count/risk_count
      + timings{load_data,build_prompt,call_api,parse,write,r2,staticdata}
      + data_sources{各数据源数据量} + freshness{数据新鲜度} + ai{model,tokens,cost} + output{各段字数}。
    """
    entry.setdefault("ts", _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    # b) tab 分隔追加行
    try:
        p = repo / "data" / "logs" / RUN_LOG_TEXT
        p.parent.mkdir(parents=True, exist_ok=True)
        ai = entry.get("ai") or {}
        line = "\t".join([
            str(entry.get("date", "")), entry["ts"], str(entry.get("version", "")),
            str(entry.get("direction", "")), str(entry.get("confidence", "")),
            str(ai.get("prompt_tokens", "")), str(ai.get("completion_tokens", "")),
            str(round(ai.get("cost", 0.0), 4)),
            json.dumps(entry.get("timings") or {}, ensure_ascii=False),
            json.dumps(entry.get("data_sources") or {}, ensure_ascii=False),
            json.dumps(entry.get("freshness") or {}, ensure_ascii=False),
        ]) + "\n"
        with open(p, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    # a) run_log.json 最近 N 次数组(读旧->头插->截断->写回)
    try:
        items: list = []
        pj = static_dir / RUN_LOG_FILE
        if pj.exists():
            prev = _read_json(pj) or {}
            items = (prev.get("items") or []) if isinstance(prev, dict) else []
        items.insert(0, entry)
        items = items[:RUN_LOG_LIMIT]
        (static_dir / RUN_LOG_FILE).write_text(
            json.dumps({"items": items, "total": len(items), "limit": RUN_LOG_LIMIT},
                       ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


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
def upload_to_r2(repo: Path, no_upload: bool, files: list[str] | None = None) -> None:
    """上传 daily_brief*.json 到 R2 data/ 前缀 + purge edge cache。
    必须传 REPO=repo 给 upload_r2.py,否则其 STATIC_DIR 解析到 trade/ 而非本脚本写入的 trade-data/,
    会读空目录或旧文件导致 R2 内容错位(export-output-path-sync 同源陷阱)。
    files: 要上传的文件列表(默认主数据 3 件);run_log 在 write_run_log 后单独传(见 main)。"""
    if no_upload:
        return
    files = files if files is not None else [BRIEF_FILE, HISTORY_FILE, RUN_LOG_FILE]
    env = dict(os.environ)
    env.setdefault("REPO", str(repo))
    try:
        r = subprocess.run(
            [str(repo / ".venv/bin/python"), str(repo / "scripts/upload_r2.py"),
             "upload-data-files"] + files,
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
def staticdata_sync(repo: Path, no_upload: bool, files: list[str] | None = None) -> None:
    """同步 daily_brief*.json 到 staticdata 数据仓库(trade-data-signal-staticdata)。

    背景: staticdata 同步原依赖 deploy.sh 每次 deploy 后全量 rsync;但本脚本是 deploy
    外独立生成器(只写 static-site/data/ + R2 上传,不跑 deploy.sh) → staticdata 留旧版
    直到下次 deploy(同步时机缺口,见 docs/staticdata-daily-brief-sync.md §二)。
    这里调 scripts/staticdata_sync.sh(daily-brief 触发名),脚本内部持 /tmp/trade_deploy.lock
    阻塞防与 deploy.sh staticdata 段并发写同一 git 仓库,best-effort 失败不阻塞本流程。
    必须传 REPO=repo(同 upload_to_r2,防 static-site 路径解析到 trade/ 非本脚本写入目录)。
    files: 要同步的文件列表(默认主数据 3 件);run_log 在 write_run_log 后单独同步(见 main)。"""
    if no_upload:
        return
    files = files if files is not None else [BRIEF_FILE, HISTORY_FILE, RUN_LOG_FILE]
    env = dict(os.environ)
    env.setdefault("REPO", str(repo))
    try:
        r = subprocess.run(
            ["bash", str(repo / "scripts/staticdata_sync.sh"), "daily-brief"] + files,
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


def _merge_usage(usages: list[dict]) -> dict:
    """汇总多角色调用的 token 用量(成本监控)。"""
    pt = sum((u or {}).get("prompt_tokens") or 0 for u in usages)
    ct = sum((u or {}).get("completion_tokens") or 0 for u in usages)
    return {"prompt_tokens": pt, "completion_tokens": ct}


def run_multi_agent(date: str, data: dict, cfg: dict, log) -> tuple[dict | None, dict | None]:
    """6 角色协作式生成(①②③④并行 -> ⑤研究员串行 -> ⑥主编组装)。

    返回 (brief, total_usage);任一关键环节失败 -> 返回 (None, None) 由调用方降级单 prompt。
    主编输出经 parse_ai_output 复用结构/数据锚定(P1-8)校验,meta.version="ai-multi"。
    """
    domains = split_domains(data)
    role_results, usages = run_roles_parallel(domains, date, cfg, log)
    if len(role_results) < 2:
        log(f"多角色失败(仅 {len(role_results)}/4 角色成功),降级单 prompt")
        return None, None
    log(f"4 角色并行完成: {', '.join(sorted(role_results.keys()))}")

    # ⑤ 研究员(多空辩论,串行;失败跳过辩论段,主编直接基于角色论据)
    researcher = None
    researcher_model = cfg.get("researcher_model") or "deepseek-chat"
    r_raw = call_deepseek(build_researcher_messages(role_results, date, cfg), cfg, log,
                          model=researcher_model)
    if r_raw:
        try:
            r_content = r_raw["choices"][0]["message"]["content"]
        except Exception:
            r_content = ""
        rp = _extract_json(r_content)
        if rp:
            researcher = rp
            usages.append(r_raw.get("usage") or {})
            log(f"研究员多空辩论完成 lean={rp.get('lean')} conf={rp.get('confidence')}")
        else:
            log("研究员输出解析失败,跳过辩论段")
    else:
        log("研究员调用失败,跳过辩论段")

    # ⑥ 主编(串行)组装最终结构
    e_raw = call_deepseek(build_editor_messages(role_results, researcher, date, cfg, data), cfg, log)
    if not e_raw:
        log("主编调用失败,降级单 prompt")
        return None, None
    total_usage = _merge_usage(usages + [e_raw.get("usage") or {}])
    parsed = parse_ai_output(e_raw, data, date)
    if not parsed:
        log("主编输出解析失败,降级单 prompt")
        return None, None
    parsed["meta"]["version"] = "ai-multi"
    # 角色结论/辩论为可溯源工作笔记(meta 层,非主输出);同样过合规脱敏(P0-3 防未来展示泄漏)
    parsed["meta"]["roles"] = {r: scrub_text((v.get("parsed") or {}).get("summary") or "", cfg)
                               for r, v in role_results.items()}
    if researcher:
        researcher = dict(researcher)
        researcher["bull"] = [scrub_text(str(x), cfg) for x in researcher.get("bull") or []]
        researcher["bear"] = [scrub_text(str(x), cfg) for x in researcher.get("bear") or []]
        researcher["summary"] = scrub_text(str(researcher.get("summary") or ""), cfg)
    parsed["meta"]["debate"] = researcher  # P1 可选: 存多空论据供前端"展开看辩论"
    parsed["_usage"] = total_usage
    return parsed, total_usage


def _ensure_highlights(meta: dict) -> None:
    """确保 meta.highlights 非空(高亮区块非空壳):AI 未输出时从 meta 各字段提炼兜底。
    覆盖 rule/minimal 降级版 + AI 遗漏 highlights 的情况。
    """
    if meta.get("highlights"):
        return
    out: list[str] = []
    d = {"up": "偏强/看涨", "down": "偏弱/看跌", "flat": "震荡"}.get(meta.get("direction"))
    conf = meta.get("confidence")
    if conf is not None:
        try:
            conf = max(0, min(100, int(round(float(conf)))))
        except (TypeError, ValueError):
            conf = None
    if d:
        out.append(f"明日方向{d},把握度 {conf if conf is not None else '--'}/100")
    wl = meta.get("watch_list") or []
    if wl:
        name = (wl[0].get("name") or wl[0].get("index_id") or "").strip()
        if name:
            out.append(f"明日重点关注 {name}")
    ri = meta.get("risk_items") or []
    if ri:
        out.append(f"留意风险: {str(ri[0])[:30]}")
    meta["highlights"] = [x[:40] for x in out[:4]] or ["AI 预测生成,以正文为准"]


def notify_daily_brief(brief: dict, cfg: dict, log, dry_run: bool = False) -> dict | None:
    """生成成功后发 邮件+飞书报告群(2026-08-11 追加需求,完整版:先总结再细讲)。

    编排结构(邮件 HTML 与飞书 post 一致,§22 与页面同数据源):
      【总结段·开头】direction 方向 / confidence 信心 / highlights 今日要点 /
                    debate.lean 多空结论 + debate.summary 一句话结论
      【细讲段·后面】逐维度素材: watch_list 关注标的 / risk_items 风险项 /
                    trend 趋势 / confidence_reason 把握度理由 / review 复盘 +
                    多空辩论过程(meta.debate bull[]/bear[] 论据 + lean/confidence)
                    + 四角色结论 roles
    飞书 post 富文本(仅 report 报告群生效),A股红涨绿跌: 🔴偏强/🟢偏弱/⚪震荡(与平台信号灯一致)。
    防重复: 同日(date)只发一次,dedup key=daily_brief_notify_<date>,window=86400(notify_dedup.json)。
    失败不阻塞主流程(try/except 记日志)。dry_run=True 只校验参数不真发(自验用)。
    开关: config/daily_brief.yaml notify_enabled。
    """
    try:
        if not cfg.get("notify_enabled", True):
            log("通知开关 notify_enabled=false,跳过")
            return None
        meta = brief.get("meta") or {}
        text = brief.get("text") or {}
        date = meta.get("date") or ""
        if not date:
            log("通知: 无 date,跳过")
            return None
        direction = meta.get("direction")
        dir_label = {"up": "🔴 偏强", "down": "🟢 偏弱", "flat": "⚪ 震荡"}.get(direction, "➖ 震荡")
        conf = meta.get("confidence")
        conf_s = f"{conf}/100" if conf is not None else "--"
        conf_reason = str(meta.get("confidence_reason") or "").strip()
        highlights = meta.get("highlights") or []
        roles = meta.get("roles") or {}
        debate = meta.get("debate") or {}
        version = meta.get("version") or ""
        lean = {"up": "偏多", "down": "偏空", "flat": "震荡"}.get(debate.get("lean"), debate.get("lean") or "")
        dconf = debate.get("confidence")
        dconf_s = f"{round(float(dconf) * 100):.0f}%" if isinstance(dconf, (int, float)) else ""
        bull = [str(x) for x in (debate.get("bull") or [])]
        bear = [str(x) for x in (debate.get("bear") or [])]
        debate_sum = str(debate.get("summary") or "").strip()
        watch_names = "、".join(
            (w.get("name") or w.get("index_id") or "") for w in (meta.get("watch_list") or []) if w)
        risk_items = [str(r) for r in (meta.get("risk_items") or [])]
        subject = f"📊 AI预测 {date}:{dir_label}（把握度 {conf_s}）"

        # ═══ 总结段(开头): 方向/信心/要点/多空结论 ═══
        sum_lines = [f"明日方向: <b>{_html_esc(dir_label)}</b> · 把握度: <b>{conf_s}</b>"]
        if lean:
            sum_lines.append(f"多空结论: {_html_esc(lean)}{(' · 置信度 ' + dconf_s) if dconf_s else ''}")
        if debate_sum:
            sum_lines.append(f"一句话结论: {_html_esc(debate_sum)}")
        hl_html = "".join(f"<li>{_html_esc(x)}</li>" for x in highlights[:4])
        sum_html = (
            "<div style=\"background:#eef7ff;border-left:4px solid #2196f3;padding:8px 12px;margin:8px 0;\">"
            "<b>📌 总结</b>"
            + "".join(f"<p style=\"margin:4px 0;\">{x}</p>" for x in sum_lines)
            + (f"<ul style=\"margin:6px 0 0;padding-left:20px;\">{hl_html}</ul>" if hl_html else "")
            + "</div>"
        )

        # ═══ 细讲段(后面): 逐维度素材 + 多空辩论过程 ═══
        detail_parts: list[str] = []
        if conf_reason:
            detail_parts.append(f"<p style=\"margin:4px 0;\"><b>把握度理由:</b> {_html_esc(conf_reason)}</p>")
        if watch_names:
            detail_parts.append(f"<p style=\"margin:4px 0;\"><b>关注标的:</b> {_html_esc(watch_names)}</p>")
        if risk_items:
            detail_parts.append(f"<p style=\"margin:4px 0;\"><b>风险项:</b> {_html_esc('；'.join(risk_items))}</p>")
        if text.get("trend"):
            detail_parts.append(f"<p style=\"margin:4px 0;\"><b>趋势:</b> {_html_esc(text.get('trend'))}</p>")
        if text.get("review"):
            detail_parts.append(f"<p style=\"margin:4px 0;\"><b>复盘:</b> {_html_esc(text.get('review'))}</p>")
        if text.get("watch"):
            detail_parts.append(f"<p style=\"margin:4px 0;\"><b>关注(正文):</b> {_html_esc(text.get('watch'))}</p>")
        if text.get("risk"):
            detail_parts.append(f"<p style=\"margin:4px 0;\"><b>风险(正文):</b> {_html_esc(text.get('risk'))}</p>")
        # 多空辩论过程(bull/bear + lean/confidence)
        debate_parts: list[str] = []
        for x in bull:
            debate_parts.append(f"<p style=\"margin:4px 0;color:#c62828;\">🔴 多头: {_html_esc(x)}</p>")
        for x in bear:
            debate_parts.append(f"<p style=\"margin:4px 0;color:#2e7d32;\">🟢 空头: {_html_esc(x)}</p>")
        if debate_parts:
            head = (f"<h3 style=\"margin:12px 0 4px;\">⚖️ 多空辩论过程"
                    f"{(' · ' + _html_esc(lean)) if lean else ''}{(' · 置信度 ' + dconf_s) if dconf_s else ''}</h3>")
            detail_parts.append(head + "".join(debate_parts))
        # 四角色结论(素材上下文)
        if roles:
            role_items = "".join(
                f"<li><b>{_html_esc(k)}</b>: {_html_esc(str(v))}</li>" for k, v in roles.items())
            detail_parts.append(
                f"<h3 style=\"margin:12px 0 4px;\">🤔 四角色结论</h3>"
                f"<ul style=\"margin:6px 0;padding-left:20px;\">{role_items}</ul>")
        detail_html = "<h3 style=\"margin:12px 0 4px;\">📋 细讲</h3>" + "".join(detail_parts)

        body = (
            "<div style=\"font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;"
            "max-width:640px;margin:0 auto;color:#222;line-height:1.7;\">"
            f"<h2 style=\"margin-bottom:4px;\">🤖 每日AI预测（{date} 收盘）</h2>"
            f"{sum_html}{detail_html}"
            f"<p style=\"font-size:12px;color:#999;margin-top:12px;\">{_html_esc(brief.get('disclaimer') or '')}</p>"
            "</div>"
        )

        # ═══ 飞书 post(先总结再细讲,A股红涨绿跌) ═══
        lines: list[list[dict]] = [[notify.post_md(f"**{subject}**")]]
        lines.append([notify.post_md("📌 **总结**")])
        for h in highlights[:4]:
            lines.append([notify.post_text(f"🎯 {h}")])
        if lean:
            lines.append([notify.post_text(f"⚖️ 多空结论: {lean}{(' · 置信度 ' + dconf_s) if dconf_s else ''}")])
        if debate_sum:
            lines.append([notify.post_text(f"一句话: {debate_sum[:60]}")])
        lines.append([notify.post_md("📋 **细讲**")])
        if conf_reason:
            lines.append([notify.post_text(f"把握度理由: {conf_reason[:60]}")])
        if watch_names:
            lines.append([notify.post_text(f"关注标的: {watch_names[:60]}")])
        if risk_items:
            lines.append([notify.post_text(f"风险项: {'；'.join(risk_items)[:60]}")])
        if text.get("trend"):
            lines.append([notify.post_text(f"趋势: {str(text['trend'])[:60]}")])
        if bull or bear:
            lines.append([notify.post_md("⚖️ **多空辩论过程**")])
            for x in bull[:3]:
                lines.append([notify.post_text(f"🔴 多头: {x[:50]}")])
            for x in bear[:3]:
                lines.append([notify.post_text(f"🟢 空头: {x[:50]}")])
        if roles:
            lines.append([notify.post_md("🤔 **四角色结论**")])
            for k, v in roles.items():
                lines.append([notify.post_text(f"· {k}: {str(v)[:50]}")])
        if len(lines) > notify.FEISHU_POST_MAX_ROWS:
            n_omit = len(lines) - notify.FEISHU_POST_MAX_ROWS
            lines = lines[:notify.FEISHU_POST_MAX_ROWS] + [
                [notify.post_text(f"… 其余 {n_omit} 行省略，完整见邮件/页面")]]
        lines.append([notify.post_text("免责: AI 生成,研究用途,不构成投资建议")])
        feishu_post = notify.build_feishu_post(subject, lines)

        # 同日(date)只发一次(notify.py dedup,data/notify_dedup.json)
        dedup_key = f"daily_brief_notify_{date}"
        if not dry_run and notify.check_dedup(dedup_key, 86400):
            log(f"通知已发过(date={date}),同日去重跳过")
            return {"dedup": True}
        results = notify.send(subject, body, from_prefix="[AI预测]", feishu_group="report",
                              feishu_post=feishu_post, dry_run=dry_run)
        if not dry_run:
            notify.update_dedup(dedup_key)
        log(f"AI预测通知发送完成 version={version} 渠道={results}")
        return results
    except Exception as e:  # noqa: BLE001
        log(f"⚠ AI预测通知失败(不阻塞): {e}")
        return None


# ── 主流程 ───────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="每日AI预测(daily_brief)生成脚本")
    ap.add_argument("--date", default="", help="预测日期 YYYYMMDD(默认取 overview.date)")
    ap.add_argument("--mock", action="store_true", help="不真调 deepseek,用固定 mock 输出(测试)")
    ap.add_argument("--rule-only", action="store_true", help="强制走规则版(跳过 AI,测试降级)")
    ap.add_argument("--no-upload", action="store_true", help="跳过 R2 上传")
    ap.add_argument("--multi", action="store_true",
                    help="多角色协作式编排(6角色,并行;配置 daily_brief.yaml multi_agent_enabled 亦可开启)")
    ap.add_argument("--notify-dry-run", action="store_true",
                    help="通知只校验参数不真发(dry-run,自验用;仍跑完整生成)")
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

    # 运行日志:每步耗时 + 数据源数据量 + 数据新鲜度(run_log 审计缺口#4)
    timings: dict = {}
    t0 = time.time()
    # 数据注入
    data = load_data(static_dir, db_path, date)
    timings["load_data"] = round(time.time() - t0, 2)
    history = _load_history(static_dir)

    # 数据源数据量(供 run_log + 监控)
    data_sources = {
        "signals_today": len(data.get("signals_today") or []),
        "signal_stats_buy_top": len(data.get("signal_stats_buy_top") or []),
        "futures_acc_trend_series": len(data.get("futures_acc_trend_tail") or {}),
        "inst_ih_trend_roles": len(data.get("inst_ih_trend") or {}),
        "etf_national_team_share": len(data.get("etf_national_team_share") or []),
        "etf_nt_signals": len((data.get("etf_national_team") or {}).get("signals") or []),
        "summary_fields": len(data.get("summary") or {}),
    }
    # 数据新鲜度(各数据源日期是否=今日;None=数据缺失)
    _inst_ih_first = next(iter((data.get("inst_ih_trend") or {}).values()), None)
    freshness = {
        "futures_date": (data.get("futures_acc_trend_latest") or {}).get("date"),
        "etf_nt_date": (data.get("etf_national_team") or {}).get("date"),
        "inst_ih_last_date": ((_inst_ih_first or {}).get("recent") or [{}])[-1].get("date"),
    }

    # 成本/失败链状态
    usage = None
    version = "ai"
    brief = None

    if not args.rule_only and not args.mock:
        # 主链路:AI 生成。多角色编排优先(--multi 或配置开关),失败降级单 prompt 主链路(保底不破)。
        if args.multi or cfg.get("multi_agent_enabled", False):
            log("走多角色协作式编排(6角色)")
            tc = time.time()
            _multi_brief, _multi_usage = run_multi_agent(date, data, cfg, log)
            timings["call_api"] = round(time.time() - tc, 2)
            if _multi_brief:
                usage = _multi_brief.pop("_usage", None)
                brief = _multi_brief
                version = "ai-multi"
                timings.setdefault("build_prompt", 0)  # 多角色:prompt 构建在 run_multi_agent 内
                timings.setdefault("parse", 0)
                log(f"多角色AI生成成功 direction={brief['meta']['direction']} "
                    f"watch={len(brief['meta']['watch_list'])} roles={len(brief['meta'].get('roles') or {})}")
            else:
                timings.setdefault("build_prompt", 0)
                timings.setdefault("parse", 0)
                log("多角色编排失败,降级单 prompt 主链路")
        if brief is None:
            known_bias = compute_known_bias(history) if cfg.get("review_enabled") else ""
            tb = time.time()
            messages = build_prompt(date, data, cfg, known_bias)
            timings["build_prompt"] = round(time.time() - tb, 2)
            tc = time.time()
            raw = call_deepseek(messages, cfg, log)
            timings["call_api"] = round(time.time() - tc, 2)
            if raw:
                tp = time.time()
                parsed = parse_ai_output(raw, data, date)
                timings["parse"] = round(time.time() - tp, 2)
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
        timings.setdefault("build_prompt", 0)
        timings.setdefault("call_api", 0)
        timings.setdefault("parse", 0)
        # mock:模拟 AI 成功(测试主链路,不真调 API)
        brief = {
            "meta": {
                "date": date, "version": "ai", "direction": "up",
                "confidence": 75,
                "confidence_reason": "MOCK 测试数据",
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
        timings.setdefault("build_prompt", 0)
        timings.setdefault("call_api", 0)
        timings.setdefault("parse", 0)
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
    # 高亮重点兜底:AI/规则/最小版都保证 meta.highlights 非空(高亮区块非空壳)
    _ensure_highlights(brief["meta"])

    # 合规脱敏 + 免责(在 meta 回填前完成 text 层)
    for k in ("review", "trend", "watch", "risk"):
        brief["text"][k] = scrub_text(brief["text"].get(k, ""), cfg)
    # meta.risk_items 也用户可见(AI 弹窗逐字展示),同样过合规脱敏(P0-3)
    brief["meta"]["risk_items"] = [scrub_text(str(r), cfg) for r in brief["meta"].get("risk_items") or []]
    # meta.highlights 也用户可见(页面🎯今日要点,前端 _dbHighlightsHtml 逐字展示),
    # 同样过合规脱敏(AI 输出+_ensure_highlights 兜底提炼都在此统一 scrub)(P2-1)
    brief["meta"]["highlights"] = [scrub_text(str(x), cfg) for x in brief["meta"].get("highlights") or []]
    if version in ("ai", "ai-multi") and cfg.get("compliance_enabled"):
        _remains = [w for w in FORBIDDEN_WORDS if any(w in (brief["text"][k] or "") for k in ("review", "trend", "watch", "risk"))]
        if _remains:
            log(f"⚠ 合规校验仍有指令词残留: {_remains}(已在 scrub 阶段处理)")

    # 回填上一日 hit + 写输出
    backfill_hits(history, db_path, date)
    tw = time.time()
    stats = write_outputs(static_dir, brief, cfg)
    timings["write"] = round(time.time() - tw, 2)
    log(f"写 {static_dir / BRIEF_FILE} + history({len(history)}条) hit_stats={stats}")

    # 生成成功通知(2026-08-11 追加需求):邮件+飞书报告群,同日去重,失败不阻塞
    # --mock/--rule-only 是开发/自验 flag:跳过通知,防发"MOCK 测试数据"给真实用户
    # + 写 daily_brief_notify_<date> dedup key 阻断同日 20:40 真实生成的通知(P1-1)
    if not args.mock and not args.rule_only:
        notify_daily_brief(brief, cfg, log, dry_run=args.notify_dry_run)

    # 成本日志
    log_cost(repo, cfg, date, version, usage, ok=(version in ("ai", "ai-multi")))

    # R2 上传(主数据 2 件;run_log 在 write_run_log 后单独传,保证本 run 的 run_log 随本 run 上线)
    tu = time.time()
    upload_to_r2(repo, args.no_upload, files=[BRIEF_FILE, HISTORY_FILE])
    timings["r2"] = round(time.time() - tu, 2)
    # staticdata 同步(数据仓库留档,防 deploy 外生成器留旧版;best-effort)
    ts2 = time.time()
    staticdata_sync(repo, args.no_upload, files=[BRIEF_FILE, HISTORY_FILE])
    timings["staticdata"] = round(time.time() - ts2, 2)

    # 结构化运行日志双写(run_log 审计缺口#4: 每步耗时+数据量+新鲜度+AI参数+输出摘要)
    run_entry = {
        "date": date,
        "version": version,
        "direction": brief["meta"].get("direction"),
        "confidence": brief["meta"].get("confidence"),
        "watch_count": len(brief["meta"].get("watch_list") or []),
        "risk_count": len(brief["meta"].get("risk_items") or []),
        "timings": timings,
        "data_sources": data_sources,
        "freshness": freshness,
        "ai": {
            "model": cfg.get("model", "deepseek-chat"),
            "prompt_tokens": (usage or {}).get("prompt_tokens") or 0,
            "completion_tokens": (usage or {}).get("completion_tokens") or 0,
            "cost": round(_run_cost(usage, cfg), 4),
        },
        "output": {
            "review_len": len(brief["text"].get("review") or ""),
            "trend_len": len(brief["text"].get("trend") or ""),
            "watch_len": len(brief["text"].get("watch") or ""),
            "risk_len": len(brief["text"].get("risk") or ""),
        },
    }
    write_run_log(repo, static_dir, cfg, run_entry)
    log(f"运行日志已双写: {static_dir / RUN_LOG_FILE} + {repo / 'data' / 'logs' / RUN_LOG_TEXT}")

    # run_log 单独随本 run 上线(R2 + staticdata;upload_r2 对不存在文件自动跳过,幂等)
    upload_to_r2(repo, args.no_upload, files=[RUN_LOG_FILE])
    staticdata_sync(repo, args.no_upload, files=[RUN_LOG_FILE])

    log(f"完成 version={version} date={date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
