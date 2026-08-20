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
import shutil
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
# 统一部署源树/上传 helper(防再犯机制 E, 2026-08-18): pick_repo/pick_git_repo/force_env/guard
# 写部署源树(static-site/data) + R2 上传 + staticdata 同步统一走 scripts/pick_repo.py,
# env 用 force_env 强制覆盖 REPO/GIT_REPO(不用 setdefault),防子进程解析到与写入不一致的目录
# (2026-08-18 断点根因: fetch_news/项6 写错源树 → deploy rsync 反覆盖线上, §23.11 不静默)。
# scripts/ 已在上面 L64 sys.path.insert, 直接 import。
from pick_repo import (  # noqa: E402
    candidate_repos, pick_repo, pick_git_repo, force_env, guard_deploy_source_tree,
)


def pick_db(repo: Path) -> Path:
    """挑 daily_metric MAX(date) 最新的 sentiment.db(主库优先,镜像兜底;同日期优先 trade-data)。"""
    best, best_date = None, ""
    for r in candidate_repos():
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
    # ── 深度思考能力「连接配置」(2026-08-16,兼容旧配置无此块)────────────
    # 默认零变化:官方 deepseek-chat、thinking 不启用。老 yaml 缺此块也能跑(setdefault 兜底)。
    cfg.setdefault("provider", "official")
    cfg.setdefault("providers", {
        "official": {"base_url": "https://api.deepseek.com/v1", "supports_thinking": True},
        "ark": {"base_url": "https://ark.cn-beijing.volces.com/api/v3", "supports_thinking": True},
    })
    cfg.setdefault("thinking", {
        "enabled": False,
        "effort": "high",
        "model": "deepseek-v4-flash",
    })
    # ── 方向锚语义教学开关(AI预测升级第一步,2026-08-20,默认关=线上 prompt 零改动)──
    #   开关关→build_prompt/build_editor_messages 不注入方向锚,输出与改造前逐字一致(§23.7)；
    #   开关开→注入转折因子 T + 联动/压制因子 L 语义教学(见 _direction_anchor_semantics)。
    cfg.setdefault("direction_anchor_enabled", False)
    # ── 反思=因子归因回灌开关(AI预测自成长轮次3,2026-08-20,默认关=线上注入逐字不变)──
    #   开关关→build_reflection_inject 不追加「待规避因子」段,注入文本与改造前一致(§23.7)；
    #   开关开→聚合历史失败样本 factor_attribution 回灌下次预测(见 build_attribut_inject)。
    cfg.setdefault("reflection_factor_attribution_enabled", False)
    return cfg


# ── 方向锚语义教学:数据因子计算 + 教学文生成(2026-08-20,AI预测升级第一步)──
# 对应影响面知识图谱 C 节调用逻辑(转折因子 T 主权重 + 联动/压制因子 L 辅助权重)。
# 核心设计（主控数据自检确认）：T/L 必须一起加——只加 T 不加 L，8/14 改对但 8/18
# 反而改错（2026-08-18 全席位大幅转多却次日 -2.4 暴跌，需 L3 纳指大跌压制 T1）。
# 数据全从 sentiment.db 按 date 实时取（futures_position/daily_metric/index_daily），全只读，
# 与 `--date` 历史回放天然对齐（障碍① 的 inst_ih_trend 读当前 futures.json 不在此列）。
# 本函数自开只读连接，不依赖 load_data 已开连接，故不改变 data 注入域（开关关=线上 prompt 零改动）。
_ROLE_LABEL = {"中信期货": "中信", "top20": "机构top20", "国泰君安": "国泰君安"}
_VAR_ORDER = ("综合", "IC", "IM", "IF", "IH")


def _compute_direction_anchor(db_path: Path, date: str) -> dict:
    """按 date 从 DB 计算方向锚因子（转折 T + 联动/压制 L），返回 dict 供语义教学。

    口径对齐 docs/ai-predict-direction-market-winning-signals-20260820.md：
    - net_chg = long_chg - short_chg；转多日=连续≥2日 net<0 后当日转 net>0；
      转空日=连续≥2日 net>0 后当日转 net<0。
    - 均线多头 = 上证 sh 当日 close > 20日 close 均值（滚动，含当日）。
    - 利率下行通道 = us10y 当日 < 20日 us10y 均值（共同因子 L2）。
    - 美债10Y上行→黄金跌 = 当日 us10y 变化的负相关背景（L1）。
    - 纳指期货大跌 = us_futures_nq_chg 明显为负（L3 压制看多）。
    """
    out = {
        "date": date, "turns": [], "ma_bull": None, "us10y": None,
        "rate_down_channel": None, "gold": None, "nq_chg": None,
        "nq_open_low": None,
    }
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
    except Exception:
        return out
    try:
        cur = conn.cursor()
        # ── 转折 T:按 (role,variety) 的 net_chg 序列检测转向日 ──
        rows = cur.execute(
            "SELECT date,variety,role,long_chg,short_chg FROM futures_position ORDER BY date"
        ).fetchall()
        series: dict = {}  # (role,var) -> [(date,net_chg)]
        for d, var, role, lc, sc in rows:
            if lc is None or sc is None:
                continue
            series.setdefault((role, var), []).append((d, lc - sc))
        for (role, var), seq in series.items():
            netmap = dict(seq)
            if date not in netmap:
                continue
            all_dates = [d for d, _ in seq]
            i = all_dates.index(date)
            net_now = netmap[date]
            if net_now == 0:
                continue
            sig_now = 1 if net_now > 0 else -1
            # 向前数连续同符号日（run>=2 才构成"转向"基准，对齐 mine_turn_split_stability）
            prev_sig = None
            run = 0
            j = i - 1
            while j >= 0:
                n = netmap.get(all_dates[j])
                if n is None or n == 0:
                    j -= 1
                    continue
                s = 1 if n > 0 else -1
                if prev_sig is None or s == prev_sig:
                    prev_sig, run = s, run + 1
                    j -= 1
                else:
                    break
            turn_type = None
            if prev_sig is not None and run >= 2 and sig_now != prev_sig:
                turn_type = "to_long" if sig_now == 1 else "to_short"
            out["turns"].append({
                "role": role, "variety": var,
                "net_chg": int(net_now), "net_position": None,
                "turn_type": turn_type, "prev_sig": prev_sig, "run": run,
            })
        # ── 均线多头（sh close > ma20, 含当日滚动）──
        mrows = cur.execute(
            "SELECT date,close FROM index_daily WHERE index_id='sh' AND date<=? "
            "AND close IS NOT NULL ORDER BY date DESC LIMIT 20", (date,)
        ).fetchall()
        if len(mrows) >= 20:
            closes = [r[1] for r in mrows]
            ma20 = sum(closes) / 20.0
            out["ma_bull"] = bool(closes[0] > ma20)  # 当日 close > ma20
        # ── 联动/压制 L:利率/黄金/纳指 ──
        def _m(mid):
            r = cur.execute(
                "SELECT value FROM daily_metric WHERE date=? AND metric_id=?",
                (date, mid)).fetchone()
            return r[0] if r and r[0] is not None else None
        us10y_now = _m("us10y")
        out["us10y"] = us10y_now
        urows = cur.execute(
            "SELECT value FROM daily_metric WHERE metric_id='us10y' AND date<=? "
            "AND value IS NOT NULL ORDER BY date DESC LIMIT 20", (date,)
        ).fetchall()
        if us10y_now is not None and len(urows) >= 20:
            u_ma20 = sum(r[0] for r in urows) / 20.0
            out["rate_down_channel"] = bool(us10y_now < u_ma20)
        out["gold"] = _m("gold")
        nq = _m("us_futures_nq_chg")
        out["nq_chg"] = nq
        # 纳指大跌判断：当日纳指期货涨跌幅明显为负（<= -0.8% 视为压制看多阈值，对齐 8/18=-1.302 样本）
        out["nq_open_low"] = bool(nq is not None and nq <= -0.8)
    finally:
        conn.close()
    return out


def _direction_anchor_semantics(factors: dict, date: str) -> str:
    """把方向锚因子转成中文语义教学段（喂 build_prompt/build_editor_messages 系统提示）。
    转折因子 T=主权重、联动/压制因子 L=辅助权重。只返回教学规则+当日因子状态，
    不给指令词、不越合规红线（讲解用"转多/转空/看涨/看跌"方向语义，非交易指令）。
    """
    if not factors or not factors.get("turns"):
        return ""
    lines = [
        f"【方向锚(影响面知识图谱 C 节,仅供参考方向研判)】基准=全时段机构持仓逆向无效(49.2%)，"
        "只有机构『仓位转向日』才有方向信号。转折因子 T（主权重）:"
        "机构转多(连续≥2日减多后转加多)→次日顺势看涨(64-66%)；"
        "机构转空(连续≥2日减多后转加空)→次日『逆势看涨』(转空次日不跌、全时段净流出=偏空是错的,"
        "8/14/8/17 验证;top20IC转空+均线多头=84%,任一强转向OR=65%)。"
    ]
    turns = factors["turns"]
    to_long = [t for t in turns if t["turn_type"] == "to_long"]
    to_short = [t for t in turns if t["turn_type"] == "to_short"]
    if to_long:
        desc = "；".join(f"{_ROLE_LABEL.get(t['role'], t['role'])}{t['variety']}净加仓+{t['net_chg']}"
                         for t in to_long[:6])
        lines.append(f"  当日转多信号(T1 顺势看涨): {desc}。")
    if to_short:
        desc = "；".join(f"{_ROLE_LABEL.get(t['role'], t['role'])}{t['variety']}净减多-{-t['net_chg']}"
                         for t in to_short[:6])
        lines.append(f"  当日转空信号(T2/T3 逆势看涨,别当偏空): {desc}。")
    ma = factors.get("ma_bull")
    if ma is not None:
        lines.append(f"  均线多头={ma and '是' or '否'}" + ("(sh 收盘>20日线,转空+均线多头→84%强规则)"
                     if ma else "(sh 收盘≤20日线,方向强度下降)"))
    # 联动/压制 L（辅助权重,必须与 T 同判）
    lparts = []
    rd = factors.get("rate_down_channel")
    if rd is not None:
        lparts.append("利率下行通道(us10y<20日线)=A股+黄金同向偏强背景(54.5%/57.0%)" if rd
                      else "利率上行/盘整通道=宽松背景弱,A股+黄金难同强")
    us = factors.get("us10y")
    if us is not None:
        lparts.append(f"美债10Y={us}%（上行→黄金跌、避险资产承压；下行→风险偏好回升）")
    if factors.get("gold") is not None:
        lparts.append(f"金价={factors['gold']}")
    if lparts:
        lines.append("  联动因子 L（辅助权重,宏观环境约束）: " + "；".join(lparts) + "。")
    if factors.get("nq_open_low"):
        lines.append(
            "  ⚠️ 压制信号(L3 纳指期货大跌): 当日纳指期货 nq_chg="
            f"{factors['nq_chg']:.2f}% 明显大跌，压制转多/看多(2026-08-18 全席位大幅转多却次日-2.4暴跌"
            "即 nq 大跌压制 T 因子失效样本)。若非纳指大跌,转多信号可大胆顺势看涨。"
        )
    lines.append("  方向合成: 转折因子 T 为主权重(64-84%)、联动因子 L 为辅助(53-60%),"
                 "L3 纳指大跌可压过 T1 转多看涨。")
    return "\n".join(lines)


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


# ── 申万一级行业 code→name 映射(2026-08-16 AI 预测注入增强)────────────────
# 数据源: daily_metric `ind_flow_sw_<code>` 31 申万一级行业主力资金流向。
# 注入时压缩为 top5/bottom5(长度控制,见 ai-predict-inject-research.md §4.2)。
SW_INDUSTRY_NAME = {
    "sw_801010": "农林牧渔", "sw_801030": "化工", "sw_801040": "钢铁",
    "sw_801050": "有色金属", "sw_801080": "电子", "sw_801110": "家用电器",
    "sw_801120": "食品饮料", "sw_801130": "纺织服饰", "sw_801140": "轻工制造",
    "sw_801150": "医药生物", "sw_801160": "公用事业", "sw_801170": "交通运输",
    "sw_801180": "房地产", "sw_801200": "商贸零售", "sw_801210": "社会服务",
    "sw_801230": "综合", "sw_801710": "建筑材料", "sw_801720": "建筑装饰",
    "sw_801730": "电力设备", "sw_801740": "国防军工", "sw_801750": "计算机",
    "sw_801760": "传媒", "sw_801770": "通信", "sw_801780": "银行",
    "sw_801790": "非银金融", "sw_801880": "汽车", "sw_801890": "机械设备",
    "sw_801950": "煤炭", "sw_801960": "石油石化", "sw_801970": "环保",
    "sw_801980": "美容护理",
}


def _db_metric_latest(conn: sqlite3.Connection, date: str, metric_id: str):
    """读 daily_metric 指定日期单值(停更字段: 若最新行≠date 仍返回 None=不注入)。"""
    cur = conn.cursor()
    # 停更过滤(guard 策略 §4.3-1): 先取该 metric 最新日期,非当日=停更/降级不注入。
    cur.execute("SELECT MAX(date) FROM daily_metric WHERE metric_id=?", (metric_id,))
    latest = cur.fetchone()
    if not latest or latest[0] is None or latest[0] != date:
        return None
    cur.execute("SELECT value FROM daily_metric WHERE date=? AND metric_id=?", (date, metric_id))
    row = cur.fetchone()
    if not row or row[0] is None:
        return None
    return row[0]


def _load_last_generated_at(candidates: list) -> str:
    """读上一份 daily_brief.json 的 generated_at(增量续接游标)。回 ''(取不到)。

    候选路径按序尝试: static_dir/daily_brief.json、root_data_dir/daily_brief.json、代码仓 ROOT/data。
    daily_brief.generated_at 格式 "YYYY-MM-DD HH:MM:SS"(已验证,如 2026-08-15 21:02:37),
    表示上一次预测实际喂到新闻面的时刻。增量续接即以它为起点。
    """
    for p in candidates:
        try:
            if p and Path(p).exists():
                raw = _read_json(p)
                ga = (raw or {}).get("generated_at") or ""
                if isinstance(ga, str) and len(ga) >= 10 and ga[:4].isdigit():
                    return ga
        except Exception:
            continue
    return ""


def _load_news_inject(root_data_dir: Path, date: str, last_brief_candidates: list = None) -> dict:
    """读新闻面。

    模式 A(重跑历史日期,date != 今日,可复现): 读对应日期归档 news_digest/<date>.json
      当日完整新闻 —— 保持既有可复现语义(该日期预测应看到该日期当日完整新闻面)。

    模式 B(增量续接,date == 今日,2026-08-16 用户定,时间窗口根治): 生成当天预测时,
      新闻面不是「固定最近24h/只读当天」,而是「自上次预测喂到什么时候 → 现在」之间的所有增量:
        - 游标 = 上一份 daily_brief.json 的 generated_at(如 2026-08-15 21:02:37)。
        - 拼接: 游标所在日归档的「游标时刻之后」条目 + 中间每一天完整归档 + 今日完整归档。
        - 周六/周日/节假日档案同样按自然日归档(fetch_news 已 7×24 每小时累积),照常拼接。
        - 首次无上一份(游标取不到) → fallback 读「最近 N 天归档拼接」,honest 标注 available。
    返回 {"news": [...], "upcoming": [...], "available": bool},无值则各为空 list。
    """
    norm = lambda s: s.replace("-", "")
    today_ymd = _dt.date.today().strftime("%Y%m%d")

    def _pick(full: dict) -> dict:
        """从完整 digest 挑 news/upcoming(重要优先 + 量控,复用原逻辑)。"""
        news_raw = full.get("news") or []
        important = [n for n in news_raw if n.get("important")]
        others = [n for n in news_raw if not n.get("important")]
        pick = (important[:15] + others[:10])[:25]
        news = [{
            "time": n.get("time"),
            "title": (n.get("title") or "")[:120],
            "important": bool(n.get("important")),
        } for n in pick]
        upcoming = [{
            "time": u.get("time"),
            "title": (u.get("title") or "")[:120],
        } for u in (full.get("upcoming") or [])[:10]]
        return news, upcoming

    # 归档目录(从 root_data_dir 或 ROOT/data 找)
    archive_dir = root_data_dir / "news_digest"
    if not archive_dir.is_dir():
        alt_dir = ROOT / "data" / "news_digest"
        if alt_dir.is_dir():
            archive_dir = alt_dir

    def _read_archive(day_str: str):
        """读指定自然日新闻_digest 归档;返回 dict 或 None。
        优先年目录 news_digest/<YYYY>/<date>.json(2026-08-16 主控存储结构决定),
        fallback 旧扁平 news_digest/<date>.json(迁移期兼容)。"""
        y = day_str[:4]
        p = archive_dir / y / f"{day_str}.json"
        if p.exists():
            raw = _read_json(p)
            if isinstance(raw, dict) and (raw.get("date") or "").replace("-", "") == day_str.replace("-", ""):
                return raw
        legacy = archive_dir / f"{day_str}.json"
        if legacy.exists():
            raw = _read_json(legacy)
            if isinstance(raw, dict) and (raw.get("date") or "").replace("-", "") == day_str.replace("-", ""):
                return raw
        return None

    # 模式 A: 重跑历史日期(date != 今日)读该日期归档当日完整(可复现,保持既有语义)
    date_hyphen = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    if date != today_ymd:
        archive_raw = _read_archive(date_hyphen)
        if archive_raw:
            news, upcoming = _pick(archive_raw)
            return {"news": news, "upcoming": upcoming, "available": bool(news or upcoming)}
        # 无归档: fallback 当日 news_digest.json(旧行为)
        path = root_data_dir / "news_digest.json"
        if not path.exists():
            alt = ROOT / "data" / "news_digest.json"
            if alt.exists():
                path = alt
        raw = _read_json(path)
        if not isinstance(raw, dict):
            return {"news": [], "upcoming": [], "available": False}
        if (raw.get("date") or "") and norm(raw.get("date")) != norm(date):
            return {"news": [], "upcoming": [], "available": False}
        news, upcoming = _pick(raw)
        return {"news": news, "upcoming": upcoming, "available": bool(news or upcoming)}

    # ============ 模式 B: 增量续接(生成当天预测,date == 今日) ============
    cursor = _load_last_generated_at(last_brief_candidates or [])
    today_digest = _read_archive(today_ymd[:4] + "-" + today_ymd[4:6] + "-" + today_ymd[6:8])

    if not cursor:
        # 首跑无上一份: fallback 读「最近 7 天归档拼接」(honest: 给最近历史新闻,不冒充精确增量)
        merged = []
        days = []
        for i in range(7):
            dd = _dt.date.today() - _dt.timedelta(days=i)
            d_raw = _read_archive(dd.strftime("%Y-%m-%d"))
            if d_raw:
                days.append(dd.strftime("%Y-%m-%d"))
                merged.extend(d_raw.get("news") or [])
        combo = {"news": merged, "upcoming": (today_digest or {}).get("upcoming") or []}
        if merged:
            news, upcoming = _pick(combo)
            # honest 标注: 首跑无游标,新闻面为最近 N 天 fallback(标记,前端不消费;仅供审计)
            return {"news": news, "upcoming": upcoming, "available": True,
                    "_cursor": "", "_fallback_days": days}
        # 无归档也无当日 → 空
        return {"news": [], "upcoming": [], "available": False}

    # 有游标: 解析游标时刻,截游标所在日归档「游标时刻之后」 + 中间每天完整 + 今日完整
    try:
        cursor_dt = _dt.datetime.strptime(cursor, "%Y-%m-%d %H:%M:%S")
        cursor_ymd = cursor_dt.strftime("%Y%m%d")
        cursor_date_str = cursor_dt.strftime("%Y-%m-%d")
    except Exception:
        cursor_dt, cursor_ymd, cursor_date_str = None, "", cursor

    merged_news = []
    merged_upcoming = []
    covered = []

    # ① 游标所在日: 归档该日,取 time >= 游标时刻之后的条目
    if cursor_ymd and cursor_ymd != today_ymd:
        cursor_day_raw = _read_archive(cursor_date_str) if cursor_date_str else None
        if cursor_day_raw:
            covered.append(cursor_date_str)
            cursor_time = cursor_dt.strftime("%H:%M") if cursor_dt else ""
            for n in (cursor_day_raw.get("news") or []):
                # 游标时刻之后的条目(time >= cursor 的 HH:MM;同小时视为可能已喂过,保守排除)
                nt = (n.get("time") or "")
                if nt and cursor_time and nt >= cursor_time:
                    merged_news.append(n)

    # ② 中间天(游标次日 → 今日前一天)完整归档
    if cursor_ymd:
        cur = _dt.datetime.strptime(today_ymd, "%Y%m%d").date()
        start = _dt.datetime.strptime(cursor_ymd, "%Y%m%d").date() + _dt.timedelta(days=1)
        d = start
        while d < cur:
            dd_raw = _read_archive(d.strftime("%Y-%m-%d"))
            if dd_raw:
                covered.append(d.strftime("%Y-%m-%d"))
                merged_news.extend(dd_raw.get("news") or [])
            d += _dt.timedelta(days=1)

    # ③ 今日完整归档(今天截止现在,每小时采集累积)
    if today_digest:
        today_str = today_ymd[:4] + "-" + today_ymd[4:6] + "-" + today_ymd[6:8]
        covered.append(today_str)
        merged_news.extend(today_digest.get("news") or [])
        merged_upcoming.extend(today_digest.get("upcoming") or [])

    # 跨日拼接去重(title 归一化),重要优先 + 时间新优先截断
    seen = set()
    unique_news = []
    # 重要优先在前(跨日合并后,保持 order 稳定: 先按重要,后按 time)
    ordered = sorted(merged_news, key=lambda n: (not bool(n.get("important")), str(n.get("time"))))
    for n in ordered:
        nt = (n.get("title") or "").strip()
        key = re.sub(r"[\s·—\-:：,，。.、()（）\'\"“”]+", "", nt.upper()) if nt else ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique_news.append(n)
    combo = {"news": unique_news[:25], "upcoming": merged_upcoming[:10]}
    news, upcoming = _pick(combo)

    ok = bool(news or upcoming)
    return {"news": news, "upcoming": upcoming, "available": ok,
            "_cursor": cursor, "_covered": covered}


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
    # industry_heatmap_top: 附 sw_ index_id(申万行业,如 sw_801010),供 sector_ranges 板块名
    #   -> index_id 锚定(板块区间次日验证要用 index_daily.sw_xxx 的 pct_change)。
    d["industry_heatmap_top"] = [
        {"id": h.get("id"), "name": h.get("name"),
         "pct_1d": round(h["pct_1d"], 2) if h.get("pct_1d") is not None else None}
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
    # 新鲜度守卫（2026-08-14 修"最新信号卡7/31"bug）：etf_signal 只在信号触发时写行，无触发会停在旧日；
    # data_date(etf_daily 每日健康) 才是真实数据日期，signal_stale 时明确标注"近N交易日无信号触发"，
    # 避免 AI 把旧信号日(如7/31)当最新数据呈现。仅提示性，不伪造"今日有信号"。
    _nt_data_date = nt.get("data_date") or nt.get("date") or ""
    _nt_sig_date = nt.get("date") or ""
    if nt.get("signal_stale"):
        _nt_stale_note = (
            f"[新鲜度提示] 汪汪队信号数据日期 data_date={_nt_data_date}(每日健康更新), "
            f"最近信号日 signal_date={_nt_sig_date}(etf_signal 仅在信号触发时写行,"
            f"近{nt.get('signal_stale_td')}个交易日无信号触发=stale)。"
            "本段 signals/recent 为最后一次触发日的旧数据,描述资金动向时须以 data_date 为基准、"
            "明确说明'近期无新信号触发',不得把旧信号当今日实时数据。"
        )
    else:
        _nt_stale_note = (
            f"[新鲜度] 汪汪队信号数据日期 data_date={_nt_data_date},最近信号日 signal_date={_nt_sig_date},"
            "信号新鲜。"
        )
    d["etf_national_team_note"] = (
        "口径说明: etf_national_team 为ETF汪汪队(国家队/机构护盘资金)跟踪: signals=当日异动信号"
        "(type share_outflow 份额流出 / volume_surge 放量), share_change_yi=份额变化(亿份),"
        "intensity=异动强度, n_surge/n_outflow/n_volume=各类异动数量, is_resonance=多信号共振标志,"
        "recent_7d=近7日异动统计; etf_national_team_share=12只跟踪ETF近5日份额变化%(share_change_pct)"
        "与当日份额变化亿份(share_change_yi),正=资金流入增持; etf_national_team_holders=季报机构持仓占比"
        "(inst_hold_pct 机构占比,高=机构/国家队主导)。汪汪队增持/异动是护盘与资金面支撑信号。"
        + _nt_stale_note
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

        # 中间层 7 个全押(2026-08-15 三层命中: 大盘+中间层+板块)数据注入:
        #   前6个 type=index(涨跌幅%,来自 index_daily): sz 深证成指 / cyb 创业板指 /
        #   kc50 科创50 / bj50 北证50 / hsi 恒生指数 / hstech 恒生科技。
        #   cn10y type=yield(10年国债收益率%,来自 daily_metric,当前 ~1.6964),做次日收益率变化基点预测锚。
        #   这些白名单 item 是 AI 预测 index_ranges 的 name 依据(见 MIDDLE_INDEX_MAP)。
        middle_ids = ["sz", "cyb", "kc50", "bj50", "hsi", "hstech"]
        q.execute("SELECT index_id, pct_change FROM index_daily WHERE date=? AND index_id IN (%s)"
                  % ",".join("?" * len(middle_ids)),
                  (date, *middle_ids))
        d["middle_indices"] = {r[0]: (round(r[1], 2) if r[1] is not None else None)
                               for r in q.fetchall()}
        # cn10y 当日 10年国债收益率(收益率基数,非涨跌幅)
        q.execute("SELECT value FROM daily_metric WHERE date=? AND metric_id='cn10y'", (date,))
        mrow = q.fetchone()
        d["cn10y"] = round(mrow[0], 4) if mrow and mrow[0] is not None else None

        # ── AI 预测注入面增强(2026-08-16,调研 ai-predict-inject-research.md §4)──
        # 原则: 全部站内已有数据(接入成本≈0);guard 四策略——停更过滤(_db_metric_latest
        # 校验最新行=当日,seal/zhaban/new_high_low/ind_turn 停更自动跳过)、None 跳过、
        # 大面积0拦截(新高新低本次不注入)、usdcnh 量纲÷100 标注。不改任何既有字段(§23.7 只增不改)。
        def _m(mid):  # 便捷读当日 metric(None=无值/停更,不注入)
            return _db_metric_latest(q.connection, date, mid)

        # cross_market 跨市场/全球面: 美股期货4 + 欧亚期货9(合并为 chg 序列,长度控制)
        us_futures = {
            "es": _m("us_futures_es_chg"), "nq": _m("us_futures_nq_chg"),
            "ym": _m("us_futures_ym_chg"), "rty": _m("us_futures_rty_chg"),
        }
        euasia = {
            "dax": _m("us_futures_dax_chg"), "cac40": _m("us_futures_cac40_chg"),
            "ftse100": _m("us_futures_ftse100_chg"), "sx5e": _m("us_futures_sx5e_chg"),
            "sensex": _m("us_futures_sensex_chg"), "asx200": _m("us_futures_asx200_chg"),
            "kospi": _m("us_futures_kospi_chg"), "nikkei225": _m("us_futures_nikkei225_chg"),
            "hsi": _m("us_futures_hsi_chg"),
        }
        if any(v is not None for v in us_futures.values()):
            d["cross_market"] = {
                "us_futures": us_futures, "euroasia_futures": euasia,
                "note": "us_futures=美股期货涨跌幅%(es标普/nq纳指/ym道指/rty罗素),euroasia="
                        "欧亚期货涨跌幅%(dax德股/kospi韩股/nikkei225日经/hsi恒指)。美股隔夜方向"
                        "对A股开盘领先(跌时传染更强),作方向参考。",
            }

        # forex_commodity 汇金商品: 含汇率利差/美债/贵金属原油,量纲标注
        _usdcnh_raw = _m("usdcnh")
        forex_com = {
            "usdcnh": (round(_usdcnh_raw / 100, 4) if _usdcnh_raw is not None else None),
            "cn_us_spread": _m("cn_us_spread"), "us10y": _m("us10y"),
            "gold": _m("gold"), "wti_oil": _m("wti_oil"),
            "brent": _m("brent"), "comex_silver": _m("comex_silver"),
        }
        if any(v is not None for v in forex_com.values()):
            d["forex_commodity"] = {
                **{k: v for k, v in forex_com.items() if v is not None},
                "note": ("usdcnh=离岸人民币汇率(原始值含×100 量纲,已 ÷100 归一化,如 6.79);"
                         "cn_us_spread=中美10年国债利差%(中cn10y-美us10y);us10y=美10年收益率%;"
                         "gold/wti_oil/brent/comex_silver=贵金属原油价格。跨市场风险参考。"),
            }

        # lhb 龙虎榜机构净买(资金面增量)
        _lhb_net = _m("lhb_inst_net")
        _lhb_cnt = _m("lhb_count")
        if _lhb_net is not None or _lhb_cnt is not None:
            d["lhb"] = {
                "count": _lhb_cnt, "inst_net_yi": round(_lhb_net, 2) if _lhb_net is not None else None,
                "note": "inst_net_yi=龙虎榜机构净买额(亿元,正=机构净买入),机构席位活跃度资金风向参考。",
            }

        # unlock_ipo 供给/事件面(解禁+IPO)
        _unc, _una, _ipc, _ipa = _m("unlock_count"), _m("unlock_amount"), _m("ipo_count"), _m("ipo_amount")
        if any(v is not None for v in (_unc, _una, _ipc, _ipa)):
            d["unlock_ipo"] = {
                "unlock_count": _unc,
                "unlock_amount_yi": round(_una, 2) if _una is not None else None,
                "ipo_count": _ipc,
                "ipo_amount_yi": round(_ipa, 2) if _ipa is not None else None,
                "note": "unlock_amount_yi=解禁金额(亿元),ipo_amount_yi=IPO募资金额(亿元)。供给压力参考。",
            }

        # daban 打板溢价(情绪/打板增强;seal_rate/zhaban_count 停更不注入)
        _db = _m("a_width_daban_premium")
        if _db is not None:
            d["daban"] = {
                "premium": round(_db, 4) if _db is not None else None,
                "note": "premium=打板溢价(封板资金次日兑现意愿,低=打板资金兑现意愿弱)。",
            }

        # ind_flow 行业主力资金流(31申万一级,压缩 top5/bottom5 长度控制)
        q.execute("SELECT metric_id, value FROM daily_metric WHERE date=? AND metric_id LIKE 'ind_flow_sw_%' "
                  "AND value IS NOT NULL", (date,))
        _flow_rows = q.fetchall()
        if _flow_rows:
            # ind_flow_sw_801770 -> sw 码 ind_flow_sw_801770 去前缀 -> SW_INDUSTRY_NAME
            _flow = sorted(
                [(SW_INDUSTRY_NAME.get(mid[len("ind_flow_"):], mid), round(val, 1))
                 for mid, val in _flow_rows],
                key=lambda x: x[1], reverse=True)
            d["ind_flow"] = {
                "top5_inflow": _flow[:5],
                "bottom5_outflow": _flow[-5:],
                "note": "ind_flow=申万31一级行业主力净流入(亿元):top5=净流入前5,bottom5=净流出前5,"
                        "行业资金轮动方向参考。",
            }
    finally:
        conn.close()
    # ── 注入面增强:JSON 产物键(估值/宽度/均线/新闻)───────────────
    # positions 估值位置(8宽基 1y/3y百分位+label+股息率→ERP 中期位置参考)
    pos = (_read_json(static_dir / "position.json") or {}).get("positions") or []
    pos_list = []
    for x in pos:
        p1, p3 = x.get("percentile_1y"), x.get("percentile_3y")
        if p1 is None and p3 is None:
            continue
        pos_list.append({
            "index_id": x.get("index_id"), "name": x.get("name"),
            "pct_1y": round(p1, 1) if p1 is not None else None,
            "pct_3y": round(p3, 1) if p3 is not None else None,
            "label": x.get("label"),
        })
    if pos_list:
        d["positions"] = {
            "positions": pos_list,
            "note": "positions=8宽基估值位置(1y/3y 历史百分位+语义label):低位<30=便宜,高位>70=偏贵,"
                    "作中期位置参考非次日方向主依据。",
        }

    # ad_line 腾落线/宽度(ad_line.json data[-1] 当日,不注历史数组)
    adl = (_read_json(static_dir / "ad_line.json") or {}).get("data") or []
    if adl:
        last = adl[-1]
        if last.get("ad_line") is not None:
            d["ad_line"] = {
                "ad_line": round(last["ad_line"], 1),
                "ma5": round(last["ad_line_ma5"], 1) if last.get("ad_line_ma5") is not None else None,
                "ratio": round(last["ratio"], 3) if last.get("ratio") is not None else None,
                "note": "ad_line=腾落线(涨跌家数累计差,负=宽度偏弱);ratio=涨跌比。宽度/参与度参考。",
            }

    # ma_cross 均线金叉(ma_alignment.json data[-1] 当日 bullish/bearish/cross)
    maa = (_read_json(static_dir / "ma_alignment.json") or {}).get("data") or []
    if maa:
        last = maa[-1]
        if last.get("bullish") is not None:
            d["ma_cross"] = {
                "bullish": int(last["bullish"] or 0), "bearish": int(last["bearish"] or 0),
                "cross": int(last["cross"] or 0),
                "note": "ma_cross=8宽基均线状态: bullish=多头排列数, bearish=空头排列数, cross=当日金叉/死叉数。",
            }

    # 新闻面(增量续接,2026-08-16: 生成当天预测读「上次 generated_at → 现在」增量;
    #   重跑历史日期读该日期归档可复现)。缺失/无可用静默跳过。
    # 上一份 daily_brief.json 作为增量游标来源(static_dir 优先,root_data_dir/ROOT/data 兜底)。
    last_brief_cands = [
        static_dir / "daily_brief.json",
        db_path.parent / "daily_brief.json",
        Path(str(ROOT / "data" / "daily_brief.json")),
    ]
    news = _load_news_inject(db_path.parent, date, last_brief_cands)
    if news["available"]:
        d["news"] = news
    else:
        d["news_inject_skipped"] = True  # 仅标记跳过,不报错(guard)
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

    # 规则版区间:固定窄区间(标注"规则版区间"),方向由 direction 推导,宽度<0.5。
    # up→(0.05,0.50], down→[-0.50,-0.05), flat→(-0.10,0.10)(2026-08-15用户补充:
    # 方向最优先正负,flat震荡是少见情况,区间宽度硬≤0.2=±0.1);配合 _derive_direction 一致。
    if direction == "up":
        rng = {"lo": 0.05, "hi": 0.50}
    elif direction == "down":
        rng = {"lo": -0.50, "hi": -0.05}
    else:
        rng = {"lo": -0.10, "hi": 0.10}
    sector_ranges_rule = []  # 规则版不预测板块区间(无 AI 逻辑)
    index_ranges_rule = []   # 规则版不预测中间层 7 个全押(无 AI 逻辑)
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
            "range": rng,                       # 规则版固定窄区间
            "index_ranges": index_ranges_rule,  # 规则版中间层=空(无 AI 推理)
            "sector_ranges": sector_ranges_rule,
            "range_status": "rule_fixed",
            "range_note": "规则版区间(非AI推导,固定窄带)",
            "confidence": 50,
            "confidence_reason": "规则版(非AI),无把握度评分,默认中等",
            "watch_list": watch_list,
            "risk_items": risk_items,
            "hit": {"direction": None, "actual_sh_pct": None, "actual_direction": None,
                    "range_hit": None, "sector_hits": None, "middle_hits": None},
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
            "range": {"lo": -0.10, "hi": 0.10},  # 数据不足最小版,默认兜底;flat须≤0.2宽(2026-08-15收紧)
            "index_ranges": [],                 # 最小版中间层=空(无 AI 推理)
            "sector_ranges": [],
            "range_status": "minimal_default",
            "range_note": "最小版(数据不足),方向与区间均为默认兜底,可信度低",
            "confidence": 50,
            "confidence_reason": "数据不足(最小版),默认中等",
            "watch_list": [],
            "risk_items": [],
            "hit": {"direction": None, "actual_sh_pct": None, "actual_direction": None,
                    "range_hit": None, "sector_hits": None, "middle_hits": None},
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
        '  "range": {"lo": 0.5, "hi": 1.5}, // 大盘(上证指数)次日涨跌幅区间(%),必填,hi-lo≤0.5\n'
        '  "index_ranges": [{"name": "深证成指", "lo": 0.5, "hi": 1.0}, {"name": "10年国债", "lo": 1, "hi": -1}], // 中间层7个全押区间,必填全部7个\n'
        '  "sector_ranges": [{"name": "中证1000", "lo": 1.0, "hi": 1.5}], // 1-3个领涨/领跌板块区间\n'
        '  "confidence": 0-100整数(把握度), "confidence_reason": "1句把握度理由",\n'
        '  "watch_list": [{"index_id": "...", "name": "...", "win_rate": 0.75}],\n'
        '  "risk_items": ["..."],\n'
        '  "highlights": ["2-4条今日要点,每条≤40字,提炼方向+最重要关注与风险,供页面🎯高亮"],\n'
        '  "text": {"review": "...", "trend": "...", "watch": "...", "risk": "..."}\n'
        "}\n"
        "规则:\n"
        "1.【方向+区间双必填·铁律】必须同时给出明确 direction 和具体幅度区间 range,二者缺一不可。"
        "range 代表上证指数次日涨跌幅(%):lo 下界、hi 上界,必填且禁止省略;"
        "方向由区间自动推导(lo>0→up, hi<0→down,含0→flat),不得出现\"拿不准就flat/不硬猜方向\"的逃避行为,"
        "区间可以窄但必须给、不准含糊。区间宽度约束:hi-lo ≤ 0.5(1.5-2可以,1.5-3不行),越窄越显真本事;"
        "lo/hi 绝对值 ≤5。direction 必须与区间一致。\n"
        "1a方向·优先正负【铁律】方向最优先给 up 或 down(正/负),正常平盘0很少见,不得偷懒给flat;"
        "只有真正判断将横盘窄幅震荡时才给 flat,且 flat 区间宽度必须≤0.2(如±0.1),禁止宽于0.2(平盘没有奔放幅度);"
        "正/负方向区间宽度可到0.5(仍≤0.5硬上限)。区间越窄越显真本事。\n"
        "1a\"【全正/全负区间·铁律】判断偏涨(up)必须给**全正区间**(lo>0,如 +0.3~+0.8),"
        "判断偏跌(down)必须给**全负区间**(hi<0,如 -0.8~-0.3)。严禁给\"跨0含0端点\"的区间"
        "(如 -0.5~+0.5 / -0.5~0 / 0~+0.5)——这种区间会被判成 flat;若你确实想给 flat,"
        "宽度只能≤±0.1(含0端点跨度≤0.2),别偷懒给跨0宽区间。含0端点=flat,必须显式 flat 而非跨0宽区间。\n"
        "1a'【中间层 7 个全押·铁律】index_ranges 必须输出**全部 7 个中间层指数**的次日预测区间"
        "(深证成指/创业板指/科创50/北证50/恒生指数/恒生科技/10年国债,不能少给、不能只选1-3个、"
        "不能为提升命中率放宽区间——难度优先于命中率)。每个 name 必须 ∈ 注入数据 middle_indices/cn10y "
        "且必须给出 lo/hi。前6个(type=index)是**涨跌幅%**区间,宽度≤0.5、|lo/hi|≤5"
        "(如深证成指 +0.5~+1.0%)。第7个 **10年国债(type=yield)是收益率变化基点区间,不是涨跌幅%**:"
        "预测次日 cn10y 收益率相对当日的变化(基点,1基点=0.01%),lo/hi 用整数基点、宽度≤3、|lo/hi|≤3"
        "(如 +1~-1 表示预期次日收益率在 当日−1bp 到 当日+1bp 之间)。漏掉任何1个或给出白名单外的 name "
        "都视为中间层不完整。\n"
        "1a.【板块区间·必填】sector_ranges 给 1-3 个领涨/领跌板块的次日涨跌幅区间,每个板块名 name "
        "必须 ∈ 注入数据 industry_heatmap_top 里真实存在的板块名(只能选自它),lo/hi 约束同上(宽度≤0.5、|·|≤5)。\n"
        "1b. confidence 给本次预测的整体把握度(0-100整数),基于论据充分性/分歧度/数据支持度:"
        "论据充分且信号一致=高把握 70-100;论据较足但有分歧=中等 55-70;论据不足或数据支持弱=低把握 30-55;"
        "论据不足就老实给低 confidence,但绝不能因此省略区间或改称 flat——区间必须给。"
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
        "4d.【宏观/跨市场/估值/新闻面】可引用注入数据中的估值位置(positions 1y/3y百分位+label)、"
        "跨市场(cross_market 美股期货es/nq/ym/rty+欧亚期货,美股隔夜方向对A股开盘领先尤其跌时更强)、"
        "汇率利差(gold/oil/usdcnh/cn_us_spread,注意 usdcnh 已归一化为如 6.79)、腾落线/宽度(ad_line/ma_cross)、"
        "龙虎榜(lhb 机构净买)、行业资金流(ind_flow top5/bottom5)、解禁IPO(unlock_ipo 供给压力)、"
        "打板溢价(daban)。这些作**方向与风险参考**;positions 为中期位置参考不作次日方向主依据。"
        "若存在 news 字段则可用于当日政策/外围事件提示(事件驱动),upcoming 可提示「明日关键事件」"
        "(如国新办发布会/宏观数据公布前波动不确定)。只引用注入数据,不得编造 news 里没有的新闻。\n"
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
    # ── 方向锚语义教学(AI预测升级第一步,2026-08-20):开关 off=跳过,线上 prompt 逐字不变 ──
    if cfg.get("direction_anchor_enabled"):
        _anchor_text = _direction_anchor_semantics(_compute_direction_anchor(
            pick_db(pick_repo()), date), date)
        if _anchor_text:
            sys_text += "9a.【方向锚(方向研判辅助)】" + _anchor_text + "\n"
    sys_text += "请严格按照 JSON 结构输出。"

    user = {
        "date": date,
        "data": data,
        "板块白名单(仅这些 name 可用于 sector_ranges,且必须选领涨/领跌的板块)": [
            h.get("name") for h in (data.get("industry_heatmap_top") or []) if h.get("name")
        ],
        "中间层白名单(仅这些 name 可用于 index_ranges,且必须全部7个都给出区间)": (
            "深证成指(sz)/创业板指(cyb)/科创50(kc50)/北证50(bj50)/恒生指数(hsi)/恒生科技(hstech) "
            "为涨跌幅%;10年国债(cn10y) 为收益率变化基点"
        ),
        "中间层当日数据": {
            "middle_indices": data.get("middle_indices"),
            "cn10y": data.get("cn10y"),
        },
        "任务": "基于以上数据生成每日预测 JSON(注意 data.funds_note 的资金口径说明)。",
    }
    return [
        {"role": "system", "content": sys_text},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


# ── deepseek 调用(超时60s/重试2次/429退避 P1-9;双 provider + 思考档位 2026-08-16)───
def call_deepseek(messages: list[dict], cfg: dict, log_fn, model: str | None = None) -> dict | None:
    if requests is None:
        log_fn("requests 未安装,无法调 AI")
        return None
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        log_fn("未找到 DEEPSEEK_API_KEY(.env),跳过 AI")
        return None
    # ── provider 解析(官方/火山方舟双端)。env DEEPSEEK_BASE_URL 最高优先,否则按 provider 配置。──
    provider = cfg.get("provider") or "official"
    providers_cfg = cfg.get("providers") or {}
    pcfg = providers_cfg.get(provider) or {}
    base = (os.environ.get("DEEPSEEK_BASE_URL")
            or pcfg.get("base_url")
            or "https://api.deepseek.com/v1").rstrip("/")
    # ── 思考档位解析:thinking.enabled=true 时切 v4 推理模型 + 注入思考参数;默认 false 零变化。──
    thinking_cfg = cfg.get("thinking") or {}
    thinking_on = bool(thinking_cfg.get("enabled")) and bool(pcfg.get("supports_thinking"))
    eff = str(thinking_cfg.get("effort") or "high").lower()
    if eff == "disabled":
        thinking_on = False            # effort=disabled 等效不启用
    # 模型优先级:思考开启->thinking.model(v4 推理模型);否则沿用传入/env/cfg.model(现状 deepseek-chat)
    use_model = None
    if thinking_on:
        use_model = thinking_cfg.get("model") or cfg.get("model", "deepseek-chat")
    else:
        use_model = model or os.environ.get("DEEPSEEK_MODEL") or cfg.get("model", "deepseek-chat")
    url = base + "/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": use_model,
        "messages": messages,
        "temperature": float(cfg.get("temperature", 0.4)),
        "max_tokens": 1200,
        "response_format": {"type": "json_object"},
    }
    if thinking_on:
        # deepseek-v4 推理模型思考生效方式:thinking 对象 + reasoning_effort 档位。
        # high/max 映射见官方思考模式文档;disabled 走上方 eff 分支关闭。thinking 模式不支持 temperature(无效,去掉)。
        payload["thinking"] = {"type": "enabled"}
        if eff in ("high", "max"):
            payload["reasoning_effort"] = eff
        payload.pop("temperature", None)
        log_fn(f"deepseek 思考模式开思考: model={use_model} effort={eff} provider={provider} base={base}")
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


def _raw_range_fields(raw: dict | None) -> str:
    """观测纠盲(2026-08-15): 从 AI 原始返回提取 content 的 range/index_ranges/sector_ranges 字段
    原样打印(JSON 字符串),供降级时区分"AI 没给区间" vs "AI 给了非法区间形态"。"""
    if not raw:
        return "None"
    try:
        content = raw["choices"][0]["message"]["content"]
    except Exception:
        return "raw-unreadable"
    p = _extract_json(content)
    if not p:
        return f"JSON未解析出内部区间; content前200字= {str(content)[:200]}"
    fields = {k: p.get(k) for k in ("range", "index_ranges", "sector_ranges")}
    return json.dumps(fields, ensure_ascii=False)[:1500]


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
    # ── 区间双必填(2026-08-15 规格): range + sector_ranges。
    # 缺 range / 区间非法 → 整条标注"区间缺失/非法"降级(不静默 flat 化),方向同标降级。
    range_ok = _parse_range(parsed.get("range"))
    sectors = _parse_sector_ranges(parsed.get("sector_ranges"), data)
    # 板块区间允许为空(仅大盘区间)视为区间不完整:大盘必须有,板块缺失记为空。
    # 大盘区间缺失/非法 => 方向也无从推导,整条降级(range_status)。direction 由区间推导,禁用"拿不准就flat"。
    if range_ok is None:
        range_status = "range_missing_invalid"
        direction = "N/A"          # 大盘区间缺失 => 方向无法由区间推导,显式降级;不静默 flat
    else:
        range_status = "ok"
        # direction 一律由区间推导为准(lo>0→up, hi<0→down, 跨0→flat);
        # 若 AI 给的 direction 与区间矛盾,以区间为准覆盖(force)。
        direction = _derive_direction(range_ok["lo"], range_ok["hi"])
    # 中间层 7 全押校验(在大盘区间合法前提下): 解析 index_ranges;缺任意一个白名单项 = 中间层不完整降级。
    # 不静默 flat / 不硬判 —— 降级后回填 middle_hit 保持 None(N/A),由整体 direction 判定体现"不完整不算中"。
    middle_out = []
    if range_ok:
        mid = _parse_index_ranges(parsed.get("index_ranges"), data)
        if mid:
            have = set(m["name"] for m in mid)
            expected = set(MIDDLE_INDEX_MAP.keys())
            if expected.issubset(have):
                middle_out = mid
            else:
                middle_out = []
    # 大盘区间缺失/非法时中间层无从谈起 → 中间层置空(range_status 已降级)
    if not range_ok:
        middle_out = []
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
    # sector_ranges 规范化为 [{name, lo, hi, index_id}];前端展示用 name/lo/hi,index_id 供次日验证。
    sector_out = ([dict(s) for s in sectors] if sectors else []) if range_ok else []
    return {
        "meta": {
            "date": date,
            "version": "ai",
            "direction": direction,
            "range": range_ok,                     # {"lo","hi"} 或 None(缺失/非法)
            "index_ranges": middle_out,            # [{name,lo,hi,type}] 中间层7全押 或 []
            "sector_ranges": sector_out,           # [{name,lo,hi,index_id}] 或 []
            "range_status": range_status,          # "ok" | "range_missing_invalid"
            "range_note": ("" if range_ok else "AI未给出合法幅度区间,方向不可信,已降级"),
            "confidence": confidence,
            "confidence_reason": confidence_reason,
            "watch_list": watch_list,
            "risk_items": risk_items,
            "highlights": highlights,
            "hit": {"direction": None, "actual_sh_pct": None, "actual_direction": None,
                    "range_hit": None, "sector_hits": None, "middle_hits": None},
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
                "volume_amount", "volume_label",
                "tradable_buy_count", "tradable_sell_count", "buy_count", "sell_count")},
            "signals_note": d.get("signals_note"),
            # 2026-08-16 注入增强: 宽度/技术面 + 美股领先
            "ad_line": d.get("ad_line"),
            "ma_cross": d.get("ma_cross"),
            "cross_market": d.get("cross_market"),
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
            # 2026-08-16 注入增强: 资金面增量(龙虎榜/行业资金流/供给)
            "lhb": d.get("lhb"),
            "ind_flow": d.get("ind_flow"),
            "unlock_ipo": d.get("unlock_ipo"),
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
            # 2026-08-16 注入增强: 打板情绪 + 估值位置(中期参考)
            "daban": d.get("daban"),
            "positions": d.get("positions"),
        },
        "risk": {
            "alert": d.get("alert"),
            "risk_funds": {k: funds.get(k) for k in (
                "a_qvix_300", "a_qvix_1000", "a_volume_ratio", "a_volume_signal",
                "a_fund_main", "hk_south", "a_turnover_mean", "a_turnover_p90",
                "a_turnover_gt5_pct")},
            "industry_heatmap_top": d.get("industry_heatmap_top"),
            # 2026-08-16 注入增强: 跨市场/汇率利差风险 + 新闻事件风险
            "cross_market": d.get("cross_market"),
            "forex_commodity": d.get("forex_commodity"),
            "news": d.get("news"),
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
        "2. direction_hint 给本角色倾向:up=偏强,down=偏弱,flat=震荡/看不清。"
        "必须基于数据给出明确倾向,禁止以'看不清/震荡'作逃避改口;flat 只在数据真呈现窄幅震荡时给出,"
        "且后续主编会要求给出具体幅度区间,倾向要与区间一致。\n"
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
                "倾向必须明确给 lean(up/down/flat),不得以'看不清'逃避;flat 仅在数据真呈窄幅震荡时给。"
                "主编会基于你的 lean 收敛出**具体涨跌幅度区间**(区间必须给),所以 lean 也要有数值方向感。"
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
                          data: dict | None = None, reflections: dict | None = None,
                          history: list | None = None) -> list[dict]:
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
        '  "range": {"lo": 0.5, "hi": 1.5}, // 大盘(上证指数)次日涨跌幅区间(%),必填,hi-lo≤0.5\n'
        '  "index_ranges": [{"name": "深证成指", "lo": 0.5, "hi": 1.0}, {"name": "10年国债", "lo": 1, "hi": -1}], // 中间层7个全押区间,必填全部7个\n'
        '  "sector_ranges": [{"name": "中证1000", "lo": 1.0, "hi": 1.5}], // 1-3个领涨/领跌板块区间\n'
        '  "confidence": 0-100整数(把握度), "confidence_reason": "1句把握度理由",\n'
        '  "watch_list": [{"index_id": "...", "name": "...", "win_rate": 0.75}],\n'
        '  "risk_items": ["..."],\n'
        '  "highlights": ["2-4条今日要点,每条≤40字,提炼方向+最重要关注与风险,供页面🎯高亮"],\n'
        '  "text": {"review": "...", "trend": "...", "watch": "...", "risk": "..."}\n'
        "}\n"
        "规则:\n"
        "1.【方向+区间双必填·铁律】必须同时给出明确 direction 和具体幅度区间 range,二者缺一不可。"
        "range 代表上证指数次日涨跌幅(%):lo 下界、hi 上界,必填且禁止省略;"
        "方向由区间自动推导(lo>0→up, hi<0→down,含0→flat),不得出现\"拿不准就flat/不硬猜方向\"的逃避行为,"
        "区间可以窄但必须给、不准含糊。区间宽度约束:hi-lo ≤ 0.5(1.5-2可以,1.5-3不行),越窄越显真本事;"
        "lo/hi 绝对值 ≤5。direction 必须与区间一致。\n"
        "1a方向·优先正负【铁律】方向最优先给 up 或 down(正/负),正常平盘0很少见,不得偷懒给flat;"
        "只有真正判断将横盘窄幅震荡时才给 flat,且 flat 区间宽度必须≤0.2(如±0.1),禁止宽于0.2(平盘没有奔放幅度);"
        "正/负方向区间宽度可到0.5(仍≤0.5硬上限)。区间越窄越显真本事。\n"
        "1a\"【全正/全负区间·铁律】判断偏涨(up)必须给**全正区间**(lo>0,如 +0.3~+0.8),"
        "判断偏跌(down)必须给**全负区间**(hi<0,如 -0.8~-0.3)。严禁给\"跨0含0端点\"的区间"
        "(如 -0.5~+0.5 / -0.5~0 / 0~+0.5)——这种区间会被判成 flat;若你确实想给 flat,"
        "宽度只能≤±0.1(含0端点跨度≤0.2),别偷懒给跨0宽区间。含0端点=flat,必须显式 flat 而非跨0宽区间。\n"
        "1a'【中间层 7 个全押·铁律】index_ranges 必须输出**全部 7 个中间层指数**的次日预测区间"
        "(深证成指/创业板指/科创50/北证50/恒生指数/恒生科技/10年国债,不能少给、不能只选1-3个、"
        "不能为提升命中率放宽区间——难度优先于命中率)。每个 name 必须 ∈ 注入数据 middle_indices/cn10y "
        "且必须给出 lo/hi。前6个(type=index)是**涨跌幅%**区间,宽度≤0.5、|lo/hi|≤5"
        "(如深证成指 +0.5~+1.0%)。第7个 **10年国债(type=yield)是收益率变化基点区间,不是涨跌幅%**:"
        "预测次日 cn10y 收益率相对当日的变化(基点,1基点=0.01%),lo/hi 用整数基点、宽度≤3、|lo/hi|≤3"
        "(如 +1~-1 表示预期次日收益率在 当日−1bp 到 当日+1bp 之间)。漏掉任何1个或给出白名单外的 name "
        "都视为中间层不完整。\n"
        "1a.【板块区间·必填】sector_ranges 给 1-3 个领涨/领跌板块的次日涨跌幅区间,每个板块名 name "
        "必须 ∈ 注入数据 industry_heatmap_top 里真实存在的板块名(只能选自它),lo/hi 约束同上(宽度≤0.5、|·|≤5)。\n"
        "1b. confidence 给本次预测的整体把握度(0-100整数),基于多空辩论收敛结果——多空论据充分性/分歧度/数据支持度:"
        "论据充分且多空分歧小=高把握 70-100;论据较足但存在分歧=中等 55-70;论据不足或数据支持弱=低把握 30-55;"
        "论据不足就老实给低 confidence,但绝不能因此省略区间或改称 flat——区间必须给。"
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
    # 历史反思注入(AI 预测自成长 Step 1,2026-08-17):主编规则段后注入截至昨日的失败模式(时间隔离)
    # 三档联动(2026-08-18):按严格口径命中率分档决定注入强度/文案
    refl_inject = build_reflection_inject(reflections or {}, date, cfg, history)
    if refl_inject:
        sys_text += (
            "9. " + refl_inject + "\n"
        )
        next_rule = 10
    else:
        next_rule = 9
    if compliance:
        sys_text += (
            f"{next_rule}. 【合规红线】严禁使用:买入、卖出、加仓、建仓、清仓、减仓、重仓、满仓、抄底、逃顶、止损、止盈、"
            "仓位、建议持有、加杠杆。只允许:关注、警惕、观察、留意、注意、谨慎。\n"
        )
    # ── 方向锚语义教学(AI预测升级第一步,2026-08-20):开关 off=跳过,线上 prompt 逐字不变 ──
    if cfg.get("direction_anchor_enabled"):
        _anchor_text = _direction_anchor_semantics(_compute_direction_anchor(
            pick_db(pick_repo()), date), date)
        if _anchor_text:
            sys_text += f"{next_rule+1}.【方向锚(方向研判辅助)】" + _anchor_text + "\n"
    # 数据锚定(P1-8):与 parse_ai_output 同源,watch_list 只允许注入数据真实存在的 index_id
    injected_ids = {
        x.get("index_id") for x in (data.get("signals_today") or []) if data
    } | {x.get("index_id") for x in (data.get("signal_stats_buy_top") or []) if data}
    # 板块名白名单(data.industry_heatmap_top 真实存在的板块名,供 sector_ranges.name 校验)
    sector_names = [h.get("name") for h in (data.get("industry_heatmap_top") or []) if data
                    and h.get("name")]
    user = {
        "date": date,
        "roles": "\n\n".join(parts),
        "researcher": researcher_block,
        "signals_note": (data or {}).get("signals_note"),
        "数据锚定(仅这些 index_id 可用于 watch_list)": sorted(injected_ids),
        "板块白名单(仅这些 name 可用于 sector_ranges,且必须选你判断领涨/领跌的板块)": sector_names,
        "中间层白名单(仅这些 name 可用于 index_ranges,且必须全部7个都给出区间)": (
            "深证成指(sz)/创业板指(cyb)/科创50(kc50)/北证50(bj50)/恒生指数(hsi)/恒生科技(hstech) "
            "为涨跌幅%;10年国债(cn10y) 为收益率变化基点"
        ),
        "中间层当日数据": {
            "middle_indices": (data or {}).get("middle_indices"),
            "cn10y": (data or {}).get("cn10y"),
        },
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
# ── AI 预测自成长闭环(Step 1,2026-08-17 实施,方案 docs/ai-predict-self-growth.md)──
#   失败样本反思:回填失败 -> 规则级归因 -> confidence 分桶校准 -> 注入下次预测。
#   数据落「根 data/」(本地,不进 git,§8 不 add 根 data/);注入内容按 date 归档可复现。
REFLECTIONS_FILE = "daily_brief_reflections.json"          # 失败样本反思(根 data/)
REFLECTIONS_INJECTED_FILE = "brief_reflections_injected.json"  # 按 date 归档注入文本
REFLECTION_INJECT_ENV = "BRIEF_REFLECTION_INJECT"          # env=0 关闭注入(默认开)
REFLECTION_ERROR_BPS = 0.5   # 方向对但实际偏离区间中点超该阈值(%)判 range_imprecise
# confidence 分桶校准:按桶(0-59/60-69/70-100)累积命中率(样本少如实输出,不做虚假统计意义)
CONFIDENCE_BUCKETS = [(0, 59), (60, 69), (70, 100)]
HIT_THRESHOLD = 0.5  # 涨跌幅 >0.5% 才算 up/down,否则 flat(2026-08-14 口径变更 0.1->0.5:
#                     模型被提示词引导倾向 flat,±0.1% 容忍带下 flat 天花板仅 ~8%(近30日6.7%),
#                     致 0% 命中率是口径算出来的而非预测能力为 0;±0.5% 带下 flat 天花板 ~37%,
#                     8/11-8/13 中 8/11(+0.32%)/8/12(-0.50%) 判命中,命中率 0/3->2/3)

# ── 区间预测硬约束(2026-08-15 用户定,规格 docs/daily-brief-range-prediction-spec.md)──
# 命中=实际涨跌幅落进区间(大盘+板块双区间全中),不再是"±0.5% 容忍带下 flat 圆回来"。
# 区间宽度上限是硬闸(防 AI 写宽区间套命中):hi - lo ≤ 0.5%,越窄越好。
# 方向优先级 + flat 收紧(2026-08-15 用户补充):方向最优先正负(flat是少见情况);
# 若跨0(推导为 flat),区间宽度硬≤0.2(=±0.1),正/负方向仍可到0.5。
RANGE_MAX_WIDTH = 0.5    # 区间宽度硬上限(hi-lo ≤ 0.5),up/down 用
RANGE_FLAT_MAX_WIDTH = 0.2  # flat(区间跨0含0)宽度硬上限(hi-lo ≤ 0.2,2026-08-15收紧)
RANGE_ABS_LIMIT = 5.0    # lo/hi 绝对值硬上限(-5 ~ +5,防离谱区间)
RANGE_SECTOR_MAX = 3     # sector_ranges 最多 3 个

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


# ── 区间预测辅助(2026-08-15 区间双命中口径)─────────────────────────────────
def _derive_direction(lo: float, hi: float) -> str:
    """由区间推导方向:lo>0→up, hi<0→down, 否则 flat(区间跨0含0→flat)。"""
    if lo > 0:
        return "up"
    if hi < 0:
        return "down"
    return "flat"


def _parse_range(raw) -> dict | None:
    """解析并硬校验大盘 range == {"lo": float, "hi": float}。
    校验: lo≤hi、hi-lo≤RANGE_MAX_WIDTH、flat(跨0含0)时 hi-lo≤RANGE_FLAT_MAX_WIDTH(0.2)、
    |lo/hi|≤RANGE_ABS_LIMIT。合法返回规范化 {"lo","hi"};缺失/非 dict/类型错/非法宽度/越界
    返回 None(=区间缺失/非法)。flat 逃不出宽区间:跨0给>0.2宽区间 → 判非法。"""
    if not isinstance(raw, dict):
        return None
    try:
        lo = float(raw.get("lo"))
        hi = float(raw.get("hi"))
    except (TypeError, ValueError):
        return None
    if lo > hi:
        return None
    if hi - lo > RANGE_MAX_WIDTH:
        return None
    # 方向优先级: flat(区间跨0含0=会推导为flat)必须≤0.2宽,否则判非法降级,逃不出宽区间
    if lo <= 0 <= hi and (hi - lo) > RANGE_FLAT_MAX_WIDTH:
        return None
    if abs(lo) > RANGE_ABS_LIMIT or abs(hi) > RANGE_ABS_LIMIT:
        return None
    return {"lo": round(lo, 2), "hi": round(hi, 2)}


def _build_sector_id_map(data: dict) -> dict:
    """板块名(申万行业可读名)->sw_ index_id 映射,供 sector_ranges name 校验 + 次日验证。
    白名单来源 = load_data 注入的 industry_heatmap_top(30日均线带 id)。
    返回 {name: index_id}。"""
    m: dict = {}
    for h in (data.get("industry_heatmap_top") or []):
        nm = h.get("name")
        iid = h.get("id")
        if nm and iid:
            m.setdefault(nm, iid)
    return m


def _parse_sector_ranges(raw, data: dict) -> list[dict] | None:
    """解析并硬校验 sector_ranges:
       - 1-3 个,每个 {"name","lo","hi"}
       - name 必须 ∈ 注入 industry_heatmap_top 真实存在的板块名
       - 每个区间走 _parse_range 硬校验
    全合法返回 [{name, lo, hi, index_id}];非法/超出白名单 → 该 sector 丢弃;
    若输出空 sector_ranges(或全部非法)但 AI 本应输出 → 返回 None 表示板块区间缺失/非法。"""
    if not isinstance(raw, list) or not raw:
        return None
    id_map = _build_sector_id_map(data)
    out: list[dict] = []
    for s in raw[:RANGE_SECTOR_MAX]:
        if not isinstance(s, dict):
            continue
        nm = str(s.get("name") or "").strip()
        r = _parse_range(s)
        if not r or nm not in id_map:
            continue
        out.append({"name": nm, "lo": r["lo"], "hi": r["hi"], "index_id": id_map[nm]})
    if not out:
        return None
    return out


# ── 中间层 7 个全押(2026-08-15 三层命中: 大盘+中间层+板块)────────────────────
# name → type(预测口径)。前6个 type=index(涨跌幅%,来自 index_daily),第7个 cn10y
# type=yield(10年国债收益率%,来自 daily_metric,预测"次日收益率变化基点")。
# 白名单: AI 只允许预测这些 name,其余一律丢弃(不静默 flat 化)。
# 中间层 name(中文可读名) -> type(预测口径)。前6 type=index(涨跌幅%,来自 index_daily),
# 第7个 cn10y type=yield(10年国债收益率%,来自 daily_metric,预测"次日收益率变化基点")。
# whitelist 判定: name 必须 ∈ 本 dict(只有这7个 name 被允许),是 AI 预测 index_ranges 的 name 依据。
MIDDLE_INDEX_MAP = {
    "深证成指": "index", "创业板指": "index", "科创50": "index", "北证50": "index",
    "恒生指数": "index", "恒生科技": "index", "10年国债": "yield",
}
# 中间层 name(中文可读名) -> index_id(次日验证用 index_daily key;cn10y 走 daily_metric 无 index_id)。
MIDDLE_NAME_TO_ID = {
    "深证成指": "sz", "创业板指": "cyb", "科创50": "kc50",
    "北证50": "bj50", "恒生指数": "hsi", "恒生科技": "hstech",
}
# 中间层 id(type=index 宽基) -> 中文名(供回填/展示对齐)。
MIDDLE_ID_TO_NAME = {v: k for k, v in MIDDLE_NAME_TO_ID.items()}
# 中间层 7 个 name(顺序稳定,供完整性校验): 前6宽基 + 10年国债。
MIDDLE_NAMES = list(MIDDLE_INDEX_MAP.keys())
# type=index 区间约束(与大盘相同): 宽度≤0.5、|lo/hi|≤5。
MIDDLE_IDX_MAX_WIDTH = 0.5
MIDDLE_IDX_ABS_LIMIT = 5.0
# type=yield(收益率变化基点): 宽度≤3bp、|lo/hi|≤3(如 +1~-1)。
MIDDLE_YIELD_MAX_WIDTH = 3.0
MIDDLE_YIELD_ABS_LIMIT = 3.0


def _normalize_range(lo: float, hi: float) -> tuple[float, float]:
    """若 lo>hi 交换(± 带表示如 +1~-1 即 [-1,+1],归一化为 lo≤hi)。"""
    return (hi, lo) if lo > hi else (lo, hi)


def _validate_middle_width(typ: str, lo: float, hi: float) -> bool:
    """按 type 校验中间层区间宽度 + 越界。type=index 用涨跌幅%约束;
    type=yield 用收益率变化基点(宽度≤3、|·|≤3)约束。lo>hi 时先归一化再验宽度。"""
    lo, hi = _normalize_range(lo, hi)
    if abs(lo) > RANGE_ABS_LIMIT or abs(hi) > RANGE_ABS_LIMIT:
        return False
    if typ == "index":
        if hi - lo > MIDDLE_IDX_MAX_WIDTH:
            return False
    elif typ == "yield":
        if hi - lo > MIDDLE_YIELD_MAX_WIDTH:
            return False
        if abs(lo) > MIDDLE_YIELD_ABS_LIMIT or abs(hi) > MIDDLE_YIELD_ABS_LIMIT:
            return False
    else:
        return False
    return True


def _parse_index_ranges(raw, data: dict) -> list[dict] | None:
    """解析并硬校验中间层 index_ranges(7 个全押):
       - 每个 {"name","lo","hi"},name 必须 ∈ MIDDLE_INDEX_MAP(NULL 不参与,由数据决定在不在场)
       - type=index 用涨跌幅%(宽度≤0.5、|·|≤5);type=yield(cn10y)用收益率变化基点(宽度≤3、|·|≤3)
       - 缺 range 的中间层项 → 该项缺失(整条降级由上游处理,不伪造 not sure)
    全合法返回 [{name,lo,hi,type}];非法项丢弃;完全非法/空 → None。"""
    if not isinstance(raw, list) or not raw:
        return None
    out: list[dict] = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        nm = str(s.get("name") or "").strip()
        if nm not in MIDDLE_INDEX_MAP:
            continue  # 不在白名单 → 丢弃
        typ = MIDDLE_INDEX_MAP[nm]
        try:
            lo = float(s.get("lo"))
            hi = float(s.get("hi"))
        except (TypeError, ValueError):
            continue
        if not _validate_middle_width(typ, lo, hi):
            continue
        nlo, nhi = _normalize_range(lo, hi)  # 归一化 lo≤hi(± 带如 +1~-1 → -1~+1)
        out.append({
            "name": nm, "lo": round(nlo, 2), "hi": round(nhi, 2), "type": typ,
            "index_id": MIDDLE_NAME_TO_ID.get(nm),  # 前6宽基 index_id;cn10y=None(走基点)
        })
    if not out:
        return None
    return out


def _load_cn10y_map(db_path: Path) -> dict | None:
    """一次性加载 daily_metric cn10y 全表(date->value 收益率%);失败返回 None。"""
    cn_map: dict = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
        cur = conn.cursor()
        cur.execute("SELECT date, value FROM daily_metric WHERE metric_id='cn10y' ORDER BY date")
        for r in cur.fetchall():
            if r[0] not in cn_map:
                cn_map[r[0]] = r[1]
        conn.close()
    except Exception:
        return None
    return cn_map


def _load_sh_pct_map(db_path: Path) -> dict | None:
    """一次性加载 index_daily sh 全表(date->pct_change);失败返回 None。"""
    sh_map: dict = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
        cur = conn.cursor()
        cur.execute("SELECT date, pct_change FROM index_daily WHERE index_id='sh' ORDER BY date")
        for r in cur.fetchall():
            if r[0] not in sh_map:
                sh_map[r[0]] = r[1]
        conn.close()
    except Exception:
        return None
    return sh_map


def _load_index_pct_maps(db_path: Path, index_ids: list[str]) -> dict:
    """加载多个指数(index_id)的 date->pct_change map,供板块次日验证。
    返回 {index_id: {date: pct}}(每个只保留最新一天 pct,key 唯一)。"""
    out: dict = {}
    if not index_ids:
        return out
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
        cur = conn.cursor()
        for iid in index_ids:
            cur.execute("SELECT date, pct_change FROM index_daily WHERE index_id=? ORDER BY date", (iid,))
            rows = cur.fetchall()
            if rows:
                m: dict = {}
                for r in rows:
                    m.setdefault(r[0], r[1])
                out[iid] = m
        conn.close()
    except Exception:
        return out
    return out


def backfill_hits(history: list[dict], db_path: Path, today: str) -> None:
    """对 history 中未回填(hit.direction=None)的条目,用其下一交易日实际指数涨跌幅回填命中。

    口径(2026-08-15 三层命中):命中=大盘区间命中 AND 中间层命中(7全中) AND 板块命中,即:
      - range_hit: 次日上证 pct ∈ [range.lo, range.hi](无 range 或无法验证 → None=N/A)
      - middle_hits: 中间层7个逐指数验证:
           前6宽基(sz/cyb/kc50/bj50/hsi/hstech)=次日 index_daily pct ∈ [lo,hi](涨跌幅%);
           10年国债(cn10y type=yield)=次日 cn10y − 当日 cn10y 变化(基点,×100)∈ [lo,hi];
           (基点是**次日收益率 − 当日收益率**,生成日周五预测下周一则取下一交易日的 cn10y)
           -> 7 个全中才 middle_hit=true;任一 N/A(数据缺失/无法验证)→ middle_hit=None(不硬判不伪造)。
      - sector_hits: 每个预测板块次日申万指数 pct ∈ [lo,hi](全中才板块层命中;无法验证该板块 → None)
      - direction(向后兼容字段)= 三层新条目代表"整体命中"=大盘 AND 中间层 AND 板块三层全中;
        过渡条目(有 range+板块但 index_ranges 空)→ 走老方向判定 = range_hit AND board_hit(不含中间层,
        不让缺中间层整条置 None 丢一天);老条目(无 range)沿用旧"方向相等"判定(区间命中 N/A,不伪造)。
    today=本次生成日期,只回填 date < today 的条目,避免回填"未来"。"""
    if not history:
        return
    # 只回填未判定条目(hit.direction is None);miss=False 也算已判定,避免每次重跑重扫(P2-1)
    pending = [it for it in history if (it.get("meta", {}).get("hit", {}).get("direction") is None)]
    if not pending:
        return
    sh_map = _load_sh_pct_map(db_path)
    if sh_map is None:
        return
    dates = sorted(sh_map.keys())
    # 预收集所有条目用到的板块 index_id,一次性查库(避免逐条连库)
    needed_idx = set()
    for it in pending:
        meta = it.get("meta") or {}
        for s in (meta.get("sector_ranges") or []):
            if s.get("index_id"):
                needed_idx.add(s["index_id"])
    idx_maps = _load_index_pct_maps(db_path, sorted(needed_idx))
    # 中间层: 前6宽基 index 的次日 pct map + cn10y 收益率 map(用于基点变化)
    middle_idx_ids = ["sz", "cyb", "kc50", "bj50", "hsi", "hstech"]
    middle_idx_maps = _load_index_pct_maps(db_path, middle_idx_ids)
    cn10y_map = _load_cn10y_map(db_path)
    for it in pending:
        meta = it.setdefault("meta", {})
        hit = meta.setdefault("hit", {})
        if hit.get("direction") is not None or not dates:
            continue
        bdate = it.get("date") or meta.get("date")
        if not bdate or bdate >= today:
            continue
        # 找 bdate 之后第一个有 sh 数据的交易日(全局交易日对齐)
        nxt = next((x for x in dates if x > bdate), None)
        if nxt is None:
            continue
        pct = sh_map.get(nxt)
        hit["actual_sh_pct"] = round(pct, 2) if pct is not None else None
        hit["actual_direction"] = _actual_direction(pct)
        rng = meta.get("range")
        pred = meta.get("direction")
        # 判断是否"三层新条目"(含中间层 index_ranges)。8/14 过渡条目特例:
        #  有 range + 板块,但 index_ranges 为空(None/[])→ 中间层缺失,走"老方向判定"
        #  (不含中间层,即 direction=range_hit AND board_hit),不让整条置 None 丢一天(P2 修复)。
        idx_ranges = meta.get("index_ranges") or []
        has_middle = bool(rng and idx_ranges)
        # ── 中间层命中(7 全中才 middle_hit=true;任一 N/A → None)──
        middle_hits = []
        middle_hit = None  # 默认 N/A(无中间层预测 → 不硬判)
        if has_middle:
            all_mid = True
            all_na = True
            for mi in idx_ranges:
                nm = mi.get("name")
                typ = mi.get("type")
                lo, hi = mi.get("lo"), mi.get("hi")
                if nm == "cn10y" or typ == "yield":
                    # 收益率变化基点 = 次日 cn10y − 当日 cn10y(×100 得基点)
                    cur_yield = cn10y_map.get(bdate) if cn10y_map else None
                    nxt_yield = cn10y_map.get(nxt) if cn10y_map else None
                    if cur_yield is None or nxt_yield is None:
                        middle_hits.append({"name": nm, "lo": lo, "hi": hi, "actual_bp": None, "hit": None})
                        all_mid = False
                    else:
                        bp = round((nxt_yield - cur_yield) * 100, 1)
                        ok = bool(lo <= bp <= hi)
                        middle_hits.append({"name": nm, "lo": lo, "hi": hi, "actual_bp": bp, "hit": ok})
                        all_na = False
                        if not ok:
                            all_mid = False
                else:
                    # type=index 宽基: 次日涨跌幅% ∈ [lo,hi]
                    iid = mi.get("index_id") or MIDDLE_NAME_TO_ID.get(nm)
                    im = middle_idx_maps.get(iid) or {}
                    mpct = None
                    for d in dates:
                        if d > bdate and d in im:
                            mpct = im[d]
                            break
                    if mpct is None:
                        middle_hits.append({"name": nm, "lo": lo, "hi": hi, "actual_pct": None, "hit": None})
                        all_mid = False
                    else:
                        mpct = round(mpct, 2)
                        ok = bool(lo <= mpct <= hi)
                        middle_hits.append({"name": nm, "lo": lo, "hi": hi, "actual_pct": mpct, "hit": ok})
                        all_na = False
                        if not ok:
                            all_mid = False
            hit["middle_hits"] = middle_hits
            if middle_hits and not all_na:
                middle_hit = all_mid  # 7 全中才 true
            else:
                middle_hit = None
        else:
            hit["middle_hits"] = None
        # ── 大盘区间命中 ──
        if rng and pct is not None:
            # 大盘区间命中
            hit["range_hit"] = bool(rng["lo"] <= pct <= rng["hi"])
            # 板块命中:每个预测板块次日 pct ∈ [lo,hi];全中才板块层命中;无法验证 → None
            sector_hits = []
            all_hit = True
            all_na = True
            for s in (meta.get("sector_ranges") or []):
                im = idx_maps.get(s.get("index_id")) or {}
                spct = None
                for d in dates:
                    if d > bdate and d in im:
                        spct = im[d]
                        break
                if spct is None:
                    sector_hits.append({"name": s["name"], "actual_pct": None, "hit": None})
                    all_hit = False
                else:
                    spct = round(spct, 2)
                    sh_ok = bool(s["lo"] <= spct <= s["hi"])
                    sector_hits.append({"name": s["name"], "actual_pct": spct, "hit": sh_ok})
                    all_na = False
                    if not sh_ok:
                        all_hit = False
            hit["sector_hits"] = sector_hits
            if sector_hits and not all_na:
                board_hit = all_hit
            else:
                board_hit = None  # 无板块或板块全无法验证 → 板块层 N/A
            # 整体命中 = 大盘 AND 中间层 AND 板块三层全中;任一层 N/A 则整体不硬判(标 None)
            # 8/14 过渡条目(有 range+板块但 index_ranges 空):中间层不适用 → 走老方向判定
            #   direction = range_hit AND board_hit(双层),不让缺中间层整条置 None 丢一天(P2 修复)。
            if not has_middle:
                if board_hit is None or hit["range_hit"] is None:
                    hit["direction"] = None
                else:
                    hit["direction"] = bool(hit["range_hit"] and board_hit)
            elif board_hit is None or hit["range_hit"] is None or middle_hit is None:
                hit["direction"] = None
            else:
                hit["direction"] = bool(hit["range_hit"] and middle_hit and board_hit)
        else:
            # 老条目(无 range)/pct 缺失:区间命中 N/A;方向沿用旧"方向相等"口径(不伪造区间命中)
            hit["range_hit"] = None
            hit["sector_hits"] = None
            if hit["actual_direction"]:
                hit["direction"] = bool(pred and pred == hit["actual_direction"])
        it["_backfilled_via"] = nxt


def reclassify_all_hits(history: list[dict]) -> None:
    """按当前口径重判所有已回填条目的命中(口径变更时重刷历史)。

    backfill_hits 只回填 hit.direction is None 的未判定条目;当 HIT_THRESHOLD / 区间口径
    变更时,已判定条目的语义随之失效,需逐条重判。本函数基于每条已存的 actual_sh_pct 与
    meta.range / meta.sector_ranges 重算,不重新查库(幂等)。

    区间口径(2026-08-15):
      - 有 range 条目:range_hit=大盘落区间;sector_hits=每板块落区间(全中=板块命中);
        direction=大盘 AND 板块双命中。
      - 老条目(无 range):区间命中一律 N/A(不算中不算不中),只保留旧"方向相等"判定,不伪造区间命中。
    """
    for it in history:
        meta = it.get("meta") or {}
        hit = meta.get("hit") or {}
        pct = hit.get("actual_sh_pct")
        if pct is None:
            continue
        ad = _actual_direction(pct)
        hit["actual_direction"] = ad
        pred = meta.get("direction")
        rng = meta.get("range")
        if rng and pct is not None:
            hit["range_hit"] = bool(rng["lo"] <= pct <= rng["hi"])
        else:
            hit["range_hit"] = None  # 老条目无 range/缺失 → N/A
        # sector_hits 无法从磁盘重算(需板块次日 pct,未落盘),保持已回填值或置 None(N/A)
        if "sector_hits" not in hit:
            hit["sector_hits"] = None
        # middle_hits 数据已随 hit 落盘(含 actual_bp/actual_pct),从已存值计算 middle_hit(不重查库,幂等)
        middle_hit = None
        mid = hit.get("middle_hits")
        if isinstance(mid, list) and mid:
            if any(s.get("hit") is None for s in mid):
                middle_hit = None  # 任一 N/A → 中间层不硬判
            else:
                middle_hit = all(s.get("hit") is True for s in mid)
        if "middle_hits" not in hit:
            hit["middle_hits"] = None
        if hit["range_hit"] is None:
            # 老条目(无 range):区间命中 N/A,保留旧方向相等判定(不伪造)
            if ad:
                hit["direction"] = bool(pred and pred == ad)
            else:
                hit["direction"] = None
        else:
            # 新区间条目:direction = 大盘 AND 中间层 AND 板块三层全中(整体命中)
            sector_hits = hit.get("sector_hits") or []
            board_hit = None
            if sector_hits:
                any_sna = any(s.get("hit") is None for s in sector_hits)
                board_hit = all(s.get("hit") is True for s in sector_hits)
                if any_sna:
                    board_hit = None  # 板块层有无法验证项 → 板块层不硬判
            elif not sector_hits:
                board_hit = None
            # 8/14 过渡条目(有 range 但无 middle_hits 落盘)= 中间层不适用,
            #   走老方向判定 = range_hit AND board_hit(不含中间层),不让缺中间层整条置 None(P2 修复)。
            if not (isinstance(mid, list) and mid):
                # 过渡条目/中间层缺失:双层判定
                if board_hit is None or hit["range_hit"] is None:
                    hit["direction"] = None
                else:
                    hit["direction"] = bool(hit["range_hit"] and board_hit)
            elif board_hit is None or middle_hit is None:
                hit["direction"] = None
            else:
                hit["direction"] = bool(hit["range_hit"] and middle_hit and board_hit)


def _history_stats(history: list[dict]) -> dict:
    """近30/90日命中率(严格口径 2026-08-18 用户拍板)。

    仅方向命中(老条目无区间/幅度层可校准)= 未中:计入分母但不计中。
    真命中 = 含区间(新格式)且整体方向命中(三层全命中)。字段结构兼容(30d/90d 各含 n/hit/hit_rate)。"""
    def _calc(n):
        items = [it for it in history[:n] if it.get("meta", {}).get("hit", {}).get("direction") is not None]
        if not items:
            return {"n": 0, "hit": 0, "hit_rate": None}
        hits = 0
        for it in items:
            m = it.get("meta", {}) or {}
            h = m.get("hit") or {}
            rng = m.get("range")
            has_range = bool(rng and rng.get("lo") is not None)
            # 严格口径:仅当含区间且整体方向命中(三层全命中)才算中;老条目仅方向命中=未中
            if h.get("direction") and has_range:
                hits += 1
        return {"n": len(items), "hit": hits, "hit_rate": round(hits / len(items), 3)}
    return {"30d": _calc(30), "90d": _calc(90)}


def write_outputs(static_dir: Path, brief: dict, cfg: dict, history: list | None = None) -> dict:
    """写 daily_brief.json + 归档 history + 返回 stats。

    history: 可选,已回填的 history(由主流程 backfill_hits 就地回填后传入)。
    传入时不从磁盘重载,避免 write_outputs 内部 _load_history 重载丢弃 backfill_hits
    的回填改动(2026-08-12 修复: 回填改动此前从未落盘,commit 8b7589c7b 引入)。"""
    static_dir.mkdir(parents=True, exist_ok=True)
    date = brief["meta"]["date"]
    disclaimer = cfg.get("disclaimer", "").replace("{date}", date)
    brief["disclaimer"] = disclaimer
    brief["generated_at"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # text.note 末尾追加免责(展示层)
    brief["text"]["note"] = disclaimer

    # 归档(传入已回填 history 时不重载,保留 backfill_hits 就地回填的改动)
    if history is None:
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


# ── AI 预测语音播报(edge-tts,2026-08-16,方案 docs/ai-predict-tts-plan.md §三)────────
#   用微软 Edge "大声朗读"免费在线 TTS(edge-tts 包,非 Azure 商用)把 AI 预测合成 mp3,
#   写 static-site/data/daily_brief_tts_<date>.mp3,前端 <audio> 播放。合成失败不阻塞主流程,
#   不写 meta.tts_available(前端据此隐藏播放按钮,降级不破)。
TTS_FILE_PREFIX = "daily_brief_tts_"
TTS_VOICE = "zh-CN-XiaoxiaoNeural"  # 晓晓,女,标准中文神经音色
TTS_RATE = "-5%"                    # 略慢一点,更易听清


def _tts_filename(date: str) -> str:
    return f"{TTS_FILE_PREFIX}{date}.mp3"


def _synth_tts(brief: dict, static_dir: Path, date: str, log) -> str | None:
    """组朗读文本 -> edge-tts 合成 mp3 -> 返回 mp3 相对 static-site/data/ 文件名;失败返回 None。

    只有 AI/AI-multi 完整版(meta.highlights 非空)才合成,rule/minimal 兜底版跳过(内容单薄不值得播)。
    朗读文本(按序拼接,§22 与前端 _dbBriefDetailHtml 同源同口径): 方向+把握度 -> 大盘区间(meta.range) -> 🧭结论(debate.summary) -> 🎯今日要点(highlights) -> 复盘(review) -> 趋势(trend) -> 关注(watch) -> 风险(risk)。
    方向措辞与前端 _dbDirLabel 一致(偏强/偏弱/震荡),结论回退口径与前端 _dbConclusionHtml 一致(debate.summary -> confidence_reason -> highlights[0])。
    失败(微软服务不可达/限流/调整协议)catch 记日志,不抛,不阻塞 daily_brief 主流程(风险见方案 §四)。
    """
    try:
        meta = brief.get("meta") or {}
        hl = meta.get("highlights") or []
        if not (isinstance(hl, list) and hl):
            log("tts 跳过: 非 AI 完整版(highlights 为空),不合成")
            return None
        text = brief.get("text") or {}
        parts = []
        # 方向措辞与前端 _dbDirLabel 一致(up=偏强/down=偏弱/其余=震荡,含 N/A),防"页面偏强/语音上涨"对不上(§22)
        dir_label = {"up": "偏强", "down": "偏弱"}.get(meta.get("direction"), "震荡")
        conf = meta.get("confidence")
        if isinstance(conf, (int, float)) and not isinstance(conf, bool):
            parts.append(f"今日上证指数方向{dir_label}，把握度{int(round(conf))}。")
        # 大盘区间: 与前端「大盘区间」行同源(meta.range lo~hi); 老条目无 range 则跳过(不伪造,与前端一致)
        rng = meta.get("range") or {}
        lo, hi = rng.get("lo"), rng.get("hi")
        if isinstance(lo, (int, float)) and not isinstance(lo, bool) and isinstance(hi, (int, float)) and not isinstance(hi, bool):
            _fmt_pct = lambda v: (f"+{v:.2f}" if v > 0 else f"{v:.2f}")
            parts.append(f"预计次日上证{_fmt_pct(lo)}至{_fmt_pct(hi)}。")
        # 🧭结论: 与前端 _dbConclusionHtml 同源同回退口径; 缺则整句跳过
        db = meta.get("debate") or {}
        concl = db.get("summary") or meta.get("confidence_reason") or (hl[0] if hl else "")
        if concl:
            parts.append(f"结论：{concl}")
        if hl:
            parts.append("今日要点：" + "。".join(str(x) for x in hl) + "。")
        for key, label in (("review", "复盘"), ("trend", "趋势研判"), ("watch", "明日关注"), ("risk", "风险提示")):
            seg = (text.get(key) or "").strip()
            if seg:
                parts.append(f"{label}：{seg}")
        content = "\n".join(parts)
        if not content.strip():
            log("tts 跳过: 无可用朗读文本")
            return None
        mp3 = static_dir / _tts_filename(date)
        # edge-tts 程序化调用(save_sync 同步版,不用 asyncio.run 兼容旧 py)
        import edge_tts
        communicate = edge_tts.Communicate(content, TTS_VOICE, rate=TTS_RATE)
        communicate.save_sync(str(mp3))
        if not mp3.exists() or mp3.stat().st_size == 0:
            log(f"⚠ tts 生成失败: 文件空 {mp3.name}")
            return None
        log(f"tts 合成成功: {mp3.name} {mp3.stat().st_size} 字节")
        # 写作时间/价格可选;meta.tts_available 由调用方(需在 write_outputs 前设置才能归档进 history)
        return _tts_filename(date)
    except Exception as e:
        log(f"⚠ tts 合成失败(不阻塞主流程): {e}")
        return None


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
    # 统一 helper force_env(防再犯机制 E, 2026-08-18): 强制覆盖 REPO/GIT_REPO(不用 setdefault),
    # REPO=pick_repo() 选中的部署源树, GIT_REPO=trade git 仓, 上传链与写入位置同树,
    # 防 launchd 注入 REPO 与 pick_repo 决策不一致导致 STATIC_DIR 错位读旧版。
    env = force_env(dict(os.environ), repo)
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
    # 统一 helper force_env(防再犯机制 E): 同 upload_to_r2, 防 staticdata_sync.sh 解析 repo
    # 与 pick_repo 写入位置不一致(强制覆盖 REPO/GIT_REPO, 不用 setdefault)。
    env = force_env(dict(os.environ), repo)
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


# ── AI 预测自成长闭环 Step 1:失败样本落盘 + 规则级归因 + 分桶校准 + 注入(2026-08-17)──
#   设计要点:
#    - 数据落「根 data/」(repo/data/,本地不进 git);幂等(同 date 已落不重复落)。
#    - 时间隔离(walk-forward):只记录/注入 backfilled_via <= 预测日-1 的样本,防未来函数。
#    - 无证据标「无法归因」,不臆造(§5.1)。老格式(无区间)只能 direction 级分类。
def _load_reflections(ref_path: Path) -> dict:
    """读 reflections.json,返回 {"samples": [...], "stats": {...}};文件不存在返回空结构。"""
    empty = {"samples": [], "stats": {}}
    if not ref_path.exists():
        return empty
    try:
        d = json.loads(ref_path.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            return empty
        d.setdefault("samples", [])
        d.setdefault("stats", {})
        return d
    except Exception:
        return empty


def _write_reflections(ref_path: Path, data: dict) -> None:
    try:
        ref_path.parent.mkdir(parents=True, exist_ok=True)
        ref_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        print(f"[gen_daily_brief] ⚠ reflections 写盘失败(不阻塞): {e}")


def _confidence_bucket(conf) -> str:
    """confidence -> 分桶标签(0-59/60-69/70-100)。"""
    try:
        c = int(round(float(conf)))
    except (TypeError, ValueError):
        return None
    for lo, hi in CONFIDENCE_BUCKETS:
        if lo <= c <= hi:
            return f"{lo}-{hi}"
    return None


def _reflect_news_digest_ref(backfilled_via: str, db_path: Path) -> tuple[str, str]:
    """判定次日新闻归档证据:backfilled_via(实际交易日)若有 news_digest 归档 -> evidence_source=news。
    返回 (evidence_source, news_digest_ref)。只引用"归档存在",不臆造新闻内容(§5.1)。"""
    if not backfilled_via or len(backfilled_via) != 8:
        return "rule_based", None
    day_hyphen = f"{backfilled_via[:4]}-{backfilled_via[4:6]}-{backfilled_via[6:8]}"
    y = backfilled_via[:4]
    # 优先年目录 news_digest/<YYYY>/<date>.json,fallback 扁平位;db_path 可能为 None(测试/纯函数调用)
    db_news = (db_path.parent if db_path is not None else ROOT / "data")
    cands = [
        db_news / "news_digest" / y / f"{day_hyphen}.json",
        db_news / "news_digest" / f"{day_hyphen}.json",
        ROOT / "data" / "news_digest" / y / f"{day_hyphen}.json",
        ROOT / "data" / "news_digest" / f"{day_hyphen}.json",
    ]
    for c in cands:
        if c.exists():
            return "news", day_hyphen
    return "rule_based", None


# ── 反思=因子归因回灌(TA Reflector 内核,2026-08-20):把错归因到具体误导因子 ──
#   现状旧版只做规则级归因(direction_fail/partial/range_imprecise)+一句 summary,
#   没归因到「具体哪个因子误导了方向」,也没把「该因子近期表现」回灌下次预测。
#   本函数对失败日复用 _compute_direction_anchor(与方向锚同源同 DB 只读)现算当日因子状态,
#   判断「预测方向 vs 当日因子语义方向」是否被某因子误导,产出 factor_attribution 归因列表。
#   归因随样本落盘(reflections 记录),注入时聚合 top 误导因子 → 回灌下次 prompt 约束(见 build_attribut_inject)。
def _attribut_factor(db_path: Path, date: str, pred: str, failure_type: str,
                     actual_dir: str) -> list[dict]:
    """对失败日做因子归因。返回 [{factor, dir, detail}] 或 [](无归因/db 不可用)。"""
    if not db_path or failure_type == "direction_only":
        return []
    try:
        f = _compute_direction_anchor(db_path, date)
    except Exception:
        return []
    attrs: list[dict] = []
    turns = f.get("turns") or []
    to_long = [t for t in turns if t.get("turn_type") == "to_long"]
    to_short = [t for t in turns if t.get("turn_type") == "to_short"]
    ma_bull = f.get("ma_bull")
    nq_low = bool(f.get("nq_open_low"))
    nq_chg = f.get("nq_chg")
    # 方向误判(direction_fail/老格式 direction_only)：归因到与预测反向冲突的当日因子语义
    if failure_type in ("direction_fail", "direction_only", "range_imprecise") and pred and actual_dir:
        if pred == "up" and nq_low:
            attrs.append({
                "factor": "L3纳指大跌压制看多", "dir": "外部压制",
                "detail": f"当日纳指期货 nq_chg={nq_chg if nq_chg is not None else '--'}% 明显大跌，压制看多/转多信号"
                          f"(方向锚 L3: 2026-08-18 全席位大幅转多却次日 -2.4 暴跌同因)。预测看涨被外部压制证伪。",
            })
        if pred == "down" and to_short:
            attrs.append({
                "factor": "转空信号被当偏空", "dir": "逆势",
                "detail": "当日存在机构仓位转空信号(T)，方向锚语义=转空次日『逆势看涨』(全时段净流出≠偏空，8/14/8/17 验证；"
                          "top20IC转空+均线多头=84%)。预测偏空与 T2/T3 逆势看涨语义冲突，被当日量价强空覆盖，"
                          "提示勿把转空直接当偏空。",
            })
        if pred == "down" and to_long and ma_bull:
            attrs.append({
                "factor": "T1顺势看涨/均线多头强规则", "dir": "顺势",
                "detail": "当日存在机构转多信号(T1，顺势看涨 64-66% 白名单)且 sh 收盘>20日线(均线多头,84% 强化)。"
                          "预测偏空与 T1+均线多头看涨语义冲突。",
            })
        if pred == "up" and to_long and not nq_low and actual_dir == "down":
            attrs.append({
                "factor": "T1顺势看涨当日失效", "dir": "顺势失效",
                "detail": "当日存在机构转多信号(T1)且无 L3 纳指外部压制，方向锚语义应顺势看涨，但次日实际下跌，"
                          "T1 因子当日未兑现。(诚实标注:证明链路为当日因子状态，是否为长期失效需连续多日观测)",
            })
    elif failure_type == "partial":
        attrs.append({
            "factor": "板块/中间层失真", "dir": "区间层",
            "detail": "方向对但板块/中间层判定有误(partial)，归因到板块层而非方向因子。",
        })
    return attrs


def _classify_failure(it: dict, db_path: Path) -> dict | None:
    """对一个已回填历史条目做规则级失败归因;非失败(命中/N/A)返回 None。
    返回记录结构(字段见 REFLECTIONS_FILE 语义),供落盘。"""
    meta = it.get("meta") or {}
    hit = meta.get("hit") or {}
    pred = meta.get("direction")
    actual = hit.get("actual_sh_pct")
    actual_dir = hit.get("actual_direction")
    if actual is None or actual_dir is None:
        return None
    direction_hit = bool(hit.get("direction"))
    # 严格口径(2026-08-18 用户拍板):仅方向命中(无幅度/区间层校准)= 未中,也要反思。
    #   老条目(改造前无 range/中间层)的 direction 只按旧"方向相等"判定,无区间可校准幅度,
    #   视为不完整命中 → 进反思;新格式(有区间)的 direction=true = 三层全命中 = 真命中,不反思。
    rng_raw = meta.get("range")
    has_range = bool(rng_raw and rng_raw.get("lo") is not None)
    if direction_hit and has_range:
        return None
    # 若 direction 未判定(None)= N/A,不落盘(不硬判失败)
    if hit.get("direction") is None:
        return None
    date = it.get("date") or meta.get("date")
    rng = meta.get("range")
    pred_dirs = {"up": "看涨", "down": "看跌", "flat": "震荡"}
    act_dirs = {"up": "上涨", "down": "下跌", "flat": "震荡"}
    # ── failure_type / error_bps ──
    # 方向失败 = 预测方向与次日实际方向不一致(如预测跌实际涨)
    wrong_dir = bool(pred and actual_dir and pred != actual_dir)
    # 区间失准 = 方向对但幅度偏(实际落区间外且偏离区间中点超阈值)
    range_miss = False
    error_bps = None
    mid = None
    if rng and rng.get("lo") is not None:
        mid = (rng["lo"] + rng["hi"]) / 2.0
        error_bps = round(actual - mid, 2)  # 预测误差(实际 - 区间中点,%)
        if not (rng["lo"] <= actual <= rng["hi"]):
            range_miss = True
    # partial = 方向+大盘区间对但中间层/板块层有错(三层未全中)
    middle_hit = hit.get("middle_hits")
    sector_hits = hit.get("sector_hits")
    partial = False
    if not wrong_dir and (rng and rng.get("lo") is not None) and hit.get("range_hit"):
        # 大盘区间命中,但中间层/板块层有失败项 -> partial
        if isinstance(middle_hit, list) and any(x.get("hit") is False for x in middle_hit):
            partial = True
        elif isinstance(sector_hits, list) and any(x.get("hit") is False for x in sector_hits):
            partial = True
    if wrong_dir:
        failure_type = "direction_fail"
    elif partial:
        failure_type = "partial"
    elif range_miss and error_bps is not None and abs(error_bps) > REFLECTION_ERROR_BPS:
        failure_type = "range_imprecise"
    elif direction_hit and not has_range:
        # 严格口径(2026-08-18):老条目仅方向命中(无区间/幅度层可校准)= 未中,单独标注 type
        failure_type = "direction_only"
    else:
        # 老格式(无区间)/无区间样本:只能方向级分类(方向对即非失败已在上面拦截,方向错已走 direction_fail)
        failure_type = "range_imprecise"
    # ── evidence_source / news_digest_ref ──
    bvia = it.get("_backfilled_via")
    evidence_source, news_ref = _reflect_news_digest_ref(bvia, db_path)
    # ── expected_gap_summary(规则级,只引用预测内已有依据 + 实际,不臆造)──
    pred_label = pred_dirs.get(pred, str(pred))
    act_label = act_dirs.get(actual_dir, str(actual_dir))
    basis = []
    ri = meta.get("risk_items") or []
    for x in ri[:3]:
        s = str(x)[:60]
        if s:
            basis.append(s)
    if not basis and meta.get("confidence_reason"):
        basis.append(str(meta["confidence_reason"])[:80])
    gap = f"预测{pred_label}"
    if rng and rng.get("lo") is not None:
        gap += f"({rng['lo']}~{rng['hi']}%)"
    gap += f",次日实际{act_label}({actual:+}%)"
    if wrong_dir:
        gap += "→方向误判"
    elif error_bps is not None:
        gap += f"→幅度偏差约{error_bps:+.2f}%"
    elif direction_hit and not has_range:
        gap += "→仅方向命中(无区间/幅度层可校准,严格口径计未中)"
    if basis:
        gap += ";预测依据:" + ";".join(basis)
    if evidence_source == "news" and news_ref:
        gap += f"(次日 {news_ref} 新闻归档可对照催化,未臆造内容)"
    else:
        gap += "(无次日新闻证据,规则级归因)"
    return {
        "date": date,
        "predict_date": date,
        "backfilled_via": bvia,
        "direction_pred": pred,
        "range_pred": rng,
        "direction_actual": actual_dir,
        "actual_pct": actual,
        "direction_hit": direction_hit,
        "range_hit": hit.get("range_hit"),
        "middle_hits": hit.get("middle_hits"),
        "sector_hits": hit.get("sector_hits"),
        "failure_type": failure_type,
        "error_bps": error_bps,
        "expected_gap_summary": gap,
        "evidence_source": evidence_source,
        "news_digest_ref": news_ref,
        "confidence": meta.get("confidence"),
        # 反思=因子归因(TA Reflector 内核,2026-08-20):把错归因到具体误导因子。
        #   只落盘,注入见 build_attribut_inject(受 cfg.reflection_factor_attribution_enabled 栅)。
        "factor_attribution": _attribut_factor(db_path, date, pred, failure_type, actual_dir),
    }


def _recompute_reflection_stats(samples: list[dict]) -> dict:
    """按 confidence 分桶累积命中率(样本少如实输出,不做虚假统计意义标注)。"""
    buckets = {}
    for lo, hi in CONFIDENCE_BUCKETS:
        key = f"{lo}-{hi}"
        in_bucket = [s for s in samples if (s.get("confidence") is not None
                                            and lo <= int(s["confidence"]) <= hi)]
        n = len(in_bucket)
        if n == 0:
            buckets[key] = {"n": 0, "hit": 0, "hit_rate": None}
            continue
        hits = sum(1 for s in in_bucket if s.get("direction_hit"))
        buckets[key] = {"n": n, "hit": hits, "hit_rate": round(hits / n, 3)}
    return {
        "buckets": buckets,
        "note": "样本稀疏阶段统计仅累积参考,不构成显著统计意义(§5.1 诚实标注)",
        "total_samples": len(samples),
    }


def record_reflections(history: list[dict], ref_path: Path, db_path: Path, today: str) -> dict:
    """回填后扫描失败样本落盘(幂等,同 date 已落不重复落;只落 backfilled_via <= today-1)。

    在 backfill_hits 之后调用:对每个「已回填且失败」的条目做规则级归因并追加 reflections.json。
    时间隔离:只处理 _backfilled_via <= 预测日-1 的样本(今天预测不吃当日及之后的反思)。
    返回更新后的 reflections dict(供注入侧复用,避免二次读盘)。
    """
    ref = _load_reflections(ref_path)
    samples = ref.get("samples") or []
    existing_dates = {s.get("date") for s in samples}
    new_count = 0
    added_dates = []
    for it in history:
        meta = it.get("meta") or {}
        hit = meta.get("hit") or {}
        if hit.get("direction") is None:
            continue  # 未回填/未判定,跳过
        bvia = it.get("_backfilled_via")
        if not bvia:
            continue
        # 时间隔离:只记录已回填且回填日 < 今天 的样本(预测日 T 不吃当日及之后反思)
        if bvia >= today:
            continue
        d = it.get("date") or meta.get("date")
        if not d or d in existing_dates:
            continue  # 幂等
        rec = _classify_failure(it, db_path)
        if rec is None:
            continue
        samples.append(rec)
        existing_dates.add(d)
        new_count += 1
        added_dates.append(f"{d}:{rec.get('failure_type')}")
    if new_count:
        ref["samples"] = samples
        ref["stats"] = _recompute_reflection_stats(samples)
        ref["updated_at"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _write_reflections(ref_path, ref)
        # 明细列出本次新增样本(日期:类型),便于在 8/18 等生成日志确认历史补录(如 8/14 direction_fail 自动落盘)
        print(f"[gen_daily_brief] reflections: 新增 {new_count} 条失败反思 {','.join(added_dates)} (累计 {len(samples)})")
    return ref


def _strict_hit_rate(history, window: int = 30):
    """严格口径命中率(2026-08-18 用户拍板:仅方向命中=未中)。

    与 _history_stats 同口径:仅含区间(新格式)且整体方向命中(三层全命中)才算中;
    老条目(无区间)仅方向命中=未中(计入分母不计中)。返回 (n, hit, rate|None)。"""
    items = [it for it in (history or [])[:window]
             if (it.get("meta", {}) or {}).get("hit", {}).get("direction") is not None]
    if not items:
        return 0, 0, None
    hits = sum(1 for it in items
               if (it["meta"]["hit"]["direction"]
                   and bool((it["meta"].get("range") or {}).get("lo") is not None)))
    return len(items), hits, hits / len(items)


def _reflection_tier(hit_rate):
    """按严格口径命中率分档(2026-08-18 用户拍板三档联动)。返回档位字符串。

    <50% 及格线以下=reinforce(加强反思注入);50-75 及格=normal(正常反思);
    75-90 良好=light(降级注入/仅最近一次);>=90 优秀=success(参考借鉴,不注入失败样本)。"""
    if hit_rate is None:
        return "normal"
    if hit_rate < 0.50:
        return "reinforce"
    if hit_rate < 0.75:
        return "normal"
    if hit_rate < 0.90:
        return "light"
    return "success"


def build_attribut_inject(reflections: dict, date: str, cfg: dict, history: list | None = None) -> str:
    """反思=因子归因回灌(TA Reflector 内核,2026-08-20):把「该误导因子近期待规避倾向」回灌下次预测。

    与 build_reflection_inject 同源同时间隔离(walk-forward):只取 backfilled_via < date 的样本，
    聚合这些失败样本的 factor_attribution(落盘于 _classify_failure),统计 top 误导因子、
    连续出错倾向,生成「待规避因子约束」段叠加进 build_reflection_inject 的注入文本(作为第9条后追加约束)。

    与方向锚语义互补不互斥:归因列的是「某因子当天误导了方向」,注入的是「该因子近期待规避」,
    方向锚(语义教学)照常独立注入;两者同源同 DB,开 attr 注入时方向锚建议同时开(否则纯规避无正向替代)。
    开关 cfg.reflection_factor_attribution_enabled(false 默认=线上注入文本逐字不变,可 A/B)。
    返回注入约束段;未开/无可聚合/优秀档返回 ''。"""
    if not cfg.get("reflection_factor_attribution_enabled", False):
        return ""
    if not cfg.get("review_enabled", True):
        return ""
    samples = reflections.get("samples") or []
    past = [s for s in samples if s.get("backfilled_via") and s.get("backfilled_via") < date
            and s.get("factor_attribution")]
    if not past:
        return ""
    # 优秀档(>=90% 命中)不注入失败归因(与 build_reflection_inject 优秀档同口径,避免干扰已成功模式)
    _, _, hit_rate = _strict_hit_rate(history, window=30)
    if _reflection_tier(hit_rate) == "success":
        return ""
    # top 误导因子聚合:统计每个 factor 出现次数 + 最新一次详情
    agg: dict[str, dict] = {}
    for s in past:
        for a in (s.get("factor_attribution") or []):
            fac = a.get("factor") or ""
            if not fac:
                continue
            e = agg.setdefault(fac, {"count": 0, "detail": "", "date": ""})
            e["count"] += 1
            if s.get("date", "") > e.get("date", ""):
                e["date"], e["detail"] = s["date"], a.get("detail") or ""
    # 按次数降序取 top3
    top = sorted(agg.items(), key=lambda kv: kv[1]["count"], reverse=True)[:3]
    if not top:
        return ""
    lines = []
    for fac, e in top:
        suffix = "（连续多次，建议重点规避）" if e["count"] >= 2 else ""
        lines.append(f"  · {fac}：近 {e['count']} 次失败误判{suffix}。{e['detail']}")
    header = (f"【待规避因子(反思归因回灌)】以下因子在近 {len(past)} 次失败预测中反复误导方向，"
              "若本日出现该因子同态信号，请降低其权重或以反向结论交叉验证，勿直接依它下单向结论；"
              f"但仍只引用本次注入数据，不臆造：\n")
    return scrub_text(header + "\n".join(lines), cfg)


def build_reflection_inject(reflections: dict, date: str, cfg: dict, history: list | None = None) -> str:
    """从 reflections.json 提取「预测日 date 之前已回填」的失败模式,生成注入文本(已 scrub)。

    只注入 backfilled_via < date 的样本(严格时间隔离 walk-forward,防未来函数)。
    规则级文本:近 N 次失败的方向/区间/误差模式,请模型参考历史失误校准本次判断。
    三档联动(2026-08-18):按严格口径近30日命中率分档决定注入强度与文案——及格线以下加强注入(全部失败样本)、
    及格档正常(近3次)、良好降级(仅最近一次)、优秀参考借鉴(不注入失败样本,改正向提示保持成功模式)。
    返回注入文本;无可注入或注入关闭返回 ''。"""
    if os.environ.get(REFLECTION_INJECT_ENV) == "0":
        return ""
    if not cfg.get("review_enabled", True):
        return ""
    samples = reflections.get("samples") or []
    # 时间隔离:只取回填日在预测日之前的样本(backfilled_via < date 才可注入)
    past = [s for s in samples if s.get("backfilled_via") and s.get("backfilled_via") < date]
    if not past:
        return ""
    # 三档联动:按严格口径命中率分档
    _, _, hit_rate = _strict_hit_rate(history, window=30)
    tier = _reflection_tier(hit_rate)
    if tier == "success":
        # 优秀档(>=90%):参考借鉴,不注入失败样本,改正向提示保持成功模式
        rate_txt = f"{hit_rate * 100:.0f}%" if hit_rate is not None else "--"
        text = (f"【历史反思校准(优秀档)】近期严格口径命中率{rate_txt}(≥90%),保持当前分析框架与决策依据;"
                "请参考近期成功预测的推理模式(多空辩论收敛、区间校准),避免因过度调整破坏已有效的判断方法。"
                "但仍只引用本次注入数据,不臆造。")
        return scrub_text(text, cfg)
    # 注入强度按档位:及格线以下=全部失败样本(加强反思);良好=仅最近一次(降级);及格/正常=近3次
    if tier == "reinforce":
        top_n = len(past)
        prefix = "加强反思"
    elif tier == "light":
        top_n = 1
        prefix = "轻量参考"
    else:
        top_n = 3
        prefix = "正常校准"
    past_sorted = sorted(past, key=lambda s: (s.get("backfilled_via") or ""), reverse=True)[:top_n]
    lines = []
    dir_fail = 0
    for s in past_sorted:
        d = s.get("date")
        ft = s.get("failure_type")
        summary = (s.get("expected_gap_summary") or "")[:200]
        lines.append(f"{d}:{ft}({summary})")
        if ft == "direction_fail":
            dir_fail += 1
    header = f"【历史反思校准({prefix})】截至本预测日之前已回填的 {len(past)} 次失败预测反思:"
    body = " ;".join(lines)
    if tier == "reinforce":
        hint = ("近期严格口径命中率低于及格线,请加强反思:对方向与幅度结论更谨慎权衡,"
                "优先复核历史反复失误模式(方向误判/仅方向命中/区间失准),必要时压低把握度以免高估。"
                "但仍只引用本次注入数据,不臆造。")
    elif tier == "light":
        hint = ("近期命中率良好,可减少对历史失败的过度警惕,仅参考最近一次失败模式即可。"
                "但仍只引用本次注入数据,不臆造。")
    elif dir_fail >= 2:
        hint = ("近几次多次出现方向误判,请对方向结论更谨慎权衡、避免因单一资金面/情绪面论据直接下反向结论。"
                "但仍只引用本次注入数据,不臆造。")
    else:
        hint = "请参考上述历史失败模式校准本次判断(尤其方向与幅度),但仍只引用本次注入数据,不臆造。"
    text = header + body + hint
    # 反思=因子归因回灌(2026-08-20,TA Reflector 内核):聚合 top 误导因子待规避约束,叠加进注入文本。
    #   受 cfg.reflection_factor_attribution_enabled 栅(false 默认=线上注入文本逐字不变)。
    attr_inject = build_attribut_inject(reflections, date, cfg, history)
    if attr_inject:
        text += "\n" + attr_inject
    # 合规 scrub:注入文本过现有脱敏(不注入内部敏感/密钥,只注入失败模式描述)
    return scrub_text(text, cfg)


def build_reflection_meta(reflections: dict, date: str, cfg: dict, history: list | None = None):
    """生成用户可读的「历史反思校准」结构化要点(与 build_reflection_inject 同源同时间隔离)。

    只取 backfilled_via < date 的样本(严格时间隔离 walk-forward,防未来函数),与注入口径完全一致,
    保证前端展示的反思要点 = 本次预测实际注入的样本,不是另算一套(§22 一致)。
    返回 dict {n, injected_n, dir_fail, tier, hit_rate, samples:[{date,type,summary}], generated_at} 或 None(无注入样本/关闭)。"""
    if os.environ.get(REFLECTION_INJECT_ENV) == "0":
        return None
    if not cfg.get("review_enabled", True):
        return None
    samples = reflections.get("samples") or []
    past = [s for s in samples if s.get("backfilled_via") and s.get("backfilled_via") < date]
    if not past:
        return None
    # 三档联动:与注入同口径同档位
    _, _, hit_rate = _strict_hit_rate(history, window=30)
    tier = _reflection_tier(hit_rate)
    if tier == "success":
        top_n = 0  # 优秀档不注入失败样本
    elif tier == "reinforce":
        top_n = len(past)
    elif tier == "light":
        top_n = 1
    else:
        top_n = 3
    past_sorted = sorted(past, key=lambda s: (s.get("backfilled_via") or ""), reverse=True)[:top_n]
    dir_fail = sum(1 for s in past_sorted if s.get("failure_type") == "direction_fail")
    return {
        "n": len(past),
        "injected_n": len(past_sorted),
        "dir_fail": dir_fail,
        "tier": tier,
        "hit_rate": round(hit_rate, 3) if hit_rate is not None else None,
        "samples": [
            {
                "date": s.get("date"),
                "type": s.get("failure_type"),
                "summary": (s.get("expected_gap_summary") or "")[:120],
            }
            for s in past_sorted
        ],
        "generated_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def archive_injected_text(ref_path: Path, date: str, text: str) -> None:
    """按 date 归档注入文本(破坏模式 A 历史重跑可复现:重跑某历史日期能还原当时注入了什么)。"""
    if not text:
        return
    try:
        ref_path.parent.mkdir(parents=True, exist_ok=True)
        d = {}
        if ref_path.exists():
            try:
                d = json.loads(ref_path.read_text(encoding="utf-8")) or {}
            except Exception:
                d = {}
        d[date] = text
        ref_path.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        print(f"[gen_daily_brief] ⚠ 注入归档写盘失败(不阻塞): {e}")


def _merge_usage(usages: list[dict]) -> dict:
    """汇总多角色调用的 token 用量(成本监控)。"""
    pt = sum((u or {}).get("prompt_tokens") or 0 for u in usages)
    ct = sum((u or {}).get("completion_tokens") or 0 for u in usages)
    return {"prompt_tokens": pt, "completion_tokens": ct}


def run_multi_agent(date: str, data: dict, cfg: dict, log, reflections: dict | None = None,
                    history: list | None = None) -> tuple[dict | None, dict | None]:
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
    e_raw = call_deepseek(build_editor_messages(role_results, researcher, date, cfg, data, reflections, history), cfg, log)
    if not e_raw:
        log("主编调用失败,降级单 prompt")
        return None, None
    total_usage = _merge_usage(usages + [e_raw.get("usage") or {}])
    parsed = parse_ai_output(e_raw, data, date)
    if not parsed:
        log(f"主编输出解析失败,降级单 prompt; AI原始区间字段={_raw_range_fields(e_raw)}")
        return None, None
    parsed["meta"]["version"] = "ai-multi"
    # 观测纠盲: 主编区间非法降级时打印 AI 原始区间字段,区分"没给"vs"给了非法区间"
    if parsed["meta"].get("range_status") == "range_missing_invalid":
        log(f"[观测] 主编区间校验降级(range_status=range_missing_invalid); "
            f"AI原始 range/index_ranges/sector_ranges={_raw_range_fields(e_raw)}")
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
        # ── 区间与中间层上色(A股红涨绿跌: 🔴偏强/🟢偏弱/⚪震荡,同多头辩论段配色) ──
        RISE_COL, FALL_COL, FLAT_COL = "#c62828", "#2e7d32", "#999"  # 红涨/绿跌/灰震荡

        def _interval_color(lo: float, hi: float, is_yield: bool) -> str:
            """区间方向取色。is_yield(10年国债收益率bp):负=收益率下行=债涨=红,正=债跌=绿。
            涨跌幅%:lo>=0红 / hi<=0绿 / 跨0灰。"""
            if is_yield:
                return RISE_COL if hi <= 0 else (FALL_COL if lo >= 0 else FLAT_COL)
            return RISE_COL if lo >= 0 else (FALL_COL if hi <= 0 else FLAT_COL)

        def _interval_emoji(lo: float, hi: float, is_yield: bool) -> str:
            return {"#c62828": "🔴", "#2e7d32": "🟢", "#999": "⚪"}[_interval_color(lo, hi, is_yield)]

        rng = meta.get("range") or {}
        range_s = ""          # 纯文本(用于 subject / 飞书)
        range_s_html = ""     # 邮件 body 上色版
        range_emoji = "⚪"
        if isinstance(rng, dict) and rng.get("lo") is not None and rng.get("hi") is not None:
            _lo, _hi = float(rng["lo"]), float(rng["hi"])
            range_s = f"{_lo:+.2f}% ~ {_hi:+.2f}%"
            range_emoji = _interval_emoji(_lo, _hi, is_yield=False)
            range_s_html = (f"<span style=\"color:{_interval_color(_lo, _hi, is_yield=False)};\">"
                            f"{_lo:+.2f}% ~ {_hi:+.2f}%</span>")
        # 中间层 7 个全押展示(2026-08-15 三层命中): 前6涨跌幅%,10年国债收益率变化基点
        index_s_plain = ""    # 飞书 纯文本(每指数一行 + emoji)
        index_s_html = ""     # 邮件 body 分条上色版(每指数一行)
        mids = meta.get("index_ranges") or []
        if mids:
            def _mid_row(m, emoji: bool = False):
                name = m.get("name") or ""
                is_y = (m.get("type") == "yield") or (name == "10年国债")
                if is_y:
                    lo, hi = float(m.get("lo", 0)), float(m.get("hi", 0))
                    _t = f"{name}: {lo:+.0f}~{hi:+.0f}bp"
                else:
                    lo, hi = float(m.get("lo", 0)), float(m.get("hi", 0))
                    _t = f"{name}: {lo:+.2f}~{hi:+.2f}%"
                _col = _interval_color(lo, hi, is_yield=is_y)
                _e = _interval_emoji(lo, hi, is_yield=is_y)
                _html = (f"<br/>{_html_esc(name)}: <span style=\"color:{_col};\">"
                         f"{_t.split(': ', 1)[1]}</span>")
                return (_t if not emoji else f"{_e} {_t}"), _e, _html
            _rows_html = []
            for _m in mids:
                _plain, _e, _html = _mid_row(_m, emoji=True)
                _rows_html.append(_html)
                index_s_plain = (index_s_plain + "\n" if index_s_plain else "") + _plain
            index_s_html = "<b>中间层7押:</b>" + "".join(_rows_html)

        # 板块区间(三层之一): 1-3 个领涨/领跌板块,红涨绿跌上色分条
        sector_s_plain = ""    # 飞书 纯文本
        sector_s_html = ""     # 邮件 body 分条上色版
        sectors = meta.get("sector_ranges") or []
        if sectors:
            _rows_html_s = []
            for _s in sectors:
                if _s.get("lo") is None or _s.get("hi") is None:
                    continue
                _slo, _shi = float(_s["lo"]), float(_s["hi"])
                _sname = _s.get("name") or ""
                _scol = _interval_color(_slo, _shi, is_yield=False)
                _se = _interval_emoji(_slo, _shi, is_yield=False)
                _stxt = f"{_sname}: {_slo:+.2f}~{_shi:+.2f}%"
                _rows_html_s.append(
                    f"<br/>{_html_esc(_sname)}: <span style=\"color:{_scol};\">{_slo:+.2f}~{_shi:+.2f}%</span>")
                sector_s_plain = (sector_s_plain + "\n" if sector_s_plain else "") + f"{_se} {_stxt}"
            if _rows_html_s:
                sector_s_html = "<b>板块区间:</b>" + "".join(_rows_html_s)
        subject = f"📊 AI预测 {date}:{dir_label}（把握度 {conf_s}{('·区间' + range_s) if range_s else ''}{('·中间' + str(len(mids)) + '押') if mids else ''}）"

        # ═══ 总结段(开头): 方向/区间/信心/要点/多空结论 ═══
        sum_lines = [f"明日方向: <b>{_html_esc(dir_label)}</b> · 把握度: <b>{conf_s}</b>"]
        if range_s_html:
            sum_lines.append(f"预测区间: <b>{range_s_html}</b>(上证指数次日涨跌幅)")
        if index_s_html:
            sum_lines.append(f"{index_s_html}（前6涨跌幅%,10年国债收益率变化基点）")
        if sector_s_html:
            sum_lines.append(f"{sector_s_html}（领涨/领跌板块次日涨跌幅%）")
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
        if range_s:
            lines.append([notify.post_text(f"区间{range_emoji}: {range_s}")])
        if index_s_plain:
            lines.append([notify.post_text("中间层7押:")])
            for _l in index_s_plain.split("\n"):
                lines.append([notify.post_text(_l)])
        if sector_s_plain:
            lines.append([notify.post_text("板块区间:")])
            for _l in sector_s_plain.split("\n"):
                lines.append([notify.post_text(_l)])
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
        # 超 80 行分段由 send_feishu 内部处理（2026-08-16 用户定：放开行数+超长分段连发）。
        # 此处不再截断省略；完整 lines（含细讲/风险项/辩论/四角色）交 build_feishu_post，
        # send_feishu 按 FEISHU_POST_MAX_ROWS 每段切分、多段连发（标题带 N/M 序号），与页面一致。
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
    ap.add_argument("--no-tts", action="store_true", help="跳过 edge-tts 语音合成(自测/开发用)")
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

    # AI 预测自成长闭环(Step 1):加载失败反思(根 data/,本地不进 git),供注入与落盘
    reflections_path = repo / "data" / REFLECTIONS_FILE
    reflections = _load_reflections(reflections_path)

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
            _multi_brief, _multi_usage = run_multi_agent(date, data, cfg, log, reflections, history)
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
            # AI 预测自成长 Step 1:单 prompt 路径叠加反思注入(方向命中率 + 最近失败模式,三档联动)
            refl_inject = build_reflection_inject(reflections, date, cfg, history)
            if refl_inject and known_bias:
                known_bias += " " + refl_inject
            elif refl_inject:
                known_bias = refl_inject
            if refl_inject:
                archive_injected_text(repo / "data" / REFLECTIONS_INJECTED_FILE, date, refl_inject)
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
                    # 观测纠盲: 单 prompt 区间非法降级时打印 AI 原始区间字段
                    if brief['meta'].get('range_status') == 'range_missing_invalid':
                        log(f"[观测] 单prompt区间校验降级(range_status=range_missing_invalid); "
                            f"AI原始 range/index_ranges/sector_ranges={_raw_range_fields(raw)}")
                else:
                    log(f"AI 输出解析失败,降级规则版; AI原始区间字段={_raw_range_fields(raw)}")
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
                "range": {"lo": 0.05, "hi": 0.50},          # MOCK 区间(宽度<0.5)
                "index_ranges": [   # MOCK 中间层 7 个全押: 前6涨跌幅%,cn10y 收益率变化基点
                    {"name": "深证成指", "lo": 0.2, "hi": 0.7, "type": "index", "index_id": "sz"},
                    {"name": "创业板指", "lo": 0.3, "hi": 0.8, "type": "index", "index_id": "cyb"},
                    {"name": "科创50", "lo": 0.1, "hi": 0.6, "type": "index", "index_id": "kc50"},
                    {"name": "北证50", "lo": -0.3, "hi": 0.2, "type": "index", "index_id": "bj50"},
                    {"name": "恒生指数", "lo": -0.3, "hi": 0.2, "type": "index", "index_id": "hsi"},
                    {"name": "恒生科技", "lo": -0.5, "hi": 0.0, "type": "index", "index_id": "hstech"},
                    {"name": "10年国债", "lo": -1, "hi": 1, "type": "yield", "index_id": None},
                ],
                "sector_ranges": [{"name": "电子", "lo": 0.5, "hi": 1.0,
                                   "index_id": "sw_801080"}],
                "range_status": "ok",
                "range_note": "",
                "confidence": 75,
                "confidence_reason": "MOCK 测试数据",
                "watch_list": [{"index_id": "hs300", "name": "沪深300", "win_rate": 0.65}],
                "risk_items": ["均线转弱预警", "主力净流出"],
                "hit": {"direction": None, "actual_sh_pct": None, "actual_direction": None,
                        "range_hit": None, "sector_hits": None, "middle_hits": None},
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

    # 回填上一日 hit + 写输出(传入已回填 history,防 write_outputs 重载丢弃回填)
    backfill_hits(history, db_path, date)
    # AI 预测自成长闭环(Step 1):回填后失败样本自动落盘(规则级归因 + 分桶校准统计,幂等)
    reflections = record_reflections(history, reflections_path, db_path, date)
    # 多角色路径的反思注入同样按 date 归档(可复现;单 prompt 路径已在生成段归档)
    if version == "ai-multi":
        multi_inject = build_reflection_inject(reflections, date, cfg, history)
        if multi_inject:
            archive_injected_text(repo / "data" / REFLECTIONS_INJECTED_FILE, date, multi_inject)
    # AI 预测语音播报(edge-tts): 只对 AI 完整版(ai/ai-multi)合成;rule/minimal 兜底版内容单薄不值得播(方案 §三)。
    #   先合成 mp3(成功 → meta.tts_available=True 才随 write_outputs 归档进 history);失败置 False,前端隐藏按钮不阻塞主流程。
    tts_file = None
    tts_ok = False
    if not args.no_tts and version in ("ai", "ai-multi"):
        tt = time.time()
        tts_file = _synth_tts(brief, static_dir, date, log)
        tts_ok = bool(tts_file)
        brief["meta"]["tts_available"] = tts_ok
        timings["tts"] = round(time.time() - tt, 2)
    else:
        brief["meta"]["tts_available"] = False
        timings["tts"] = 0
    # AI 预测自成长闭环(Step 1 透明展示):本次预测实际注入的「历史反思校准」要点,随 meta 归档进
    # daily_brief.json + history(§22 单一数据源)。与 build_reflection_inject 同源同时间隔离,
    # 前端展示 = 本次实际注入的样本(样本数/方向失败数/最近样本日期+类型+简短归因),非另算一套。
    # rule/minimal 兜底版无 AI 反思注入,meta.reflection 置 None(前端优雅降级,不显示反思块)。
    refl_meta = None
    if version in ("ai", "ai-multi"):
        refl_meta = build_reflection_meta(reflections, date, cfg, history)
    brief["meta"]["reflection"] = refl_meta
    tw = time.time()
    stats = write_outputs(static_dir, brief, cfg, history)
    timings["write"] = round(time.time() - tw, 2)
    log(f"写 {static_dir / BRIEF_FILE} + history({len(history)}条) hit_stats={stats}")

    # 生成成功通知(2026-08-11 追加需求):邮件+飞书报告群,同日去重,失败不阻塞
    # --mock/--rule-only 是开发/自验 flag:跳过通知,防发"MOCK 测试数据"给真实用户
    # + 写 daily_brief_notify_<date> dedup key 阻断同日 20:40 真实生成的通知(P1-1)
    if not args.mock and not args.rule_only:
        notify_daily_brief(brief, cfg, log, dry_run=args.notify_dry_run)

    # 成本日志
    log_cost(repo, cfg, date, version, usage, ok=(version in ("ai", "ai-multi")))

    # 新闻快讯独立产物上线闭环(2026-08-16 §22): news_digest.json(fetch_news.py 16:45 产,仅落 data/)
    # 需随 daily_brief 一起同步到 static-site/data/ + R2 data/ 前缀 + staticdata,前端"今日要闻/明日关键事件/历史事件对照"
    # 三个展示位才读得到(只写 data/ 不随 deploy 上线=前端 404)。当 news 面可用且为当日数据时复制,否则不强制(前端空态)。
    # 根因修(2026-08-16,§23.2): files_out 必须在分支判断前兜底初始化,否则 news_meta.available=False 走
    # else 分支时引用未定义变量 files_out 直接 NameError,导致 R2/staticdata 上传被整段跳过(主站留旧版)。
    # 上传清单 = 主数据 2 件(BRIEF_FILE + HISTORY_FILE) + tts mp3(若有);news_digest 同步只在基础上 append。
    files_out = [BRIEF_FILE, HISTORY_FILE] + ([tts_file] if tts_ok and tts_file else [])
    news_meta = (data.get("news") or {})
    if news_meta.get("available"):
        # 源文件 = 后端 _load_news_inject 读到的 news_digest.json(trade-data/data/ 或 ROOT/data 兜底)
        news_src = db_path.parent / "news_digest.json"
        if not news_src.exists():
            news_src = ROOT / "data" / "news_digest.json"
        if news_src.exists():
            try:
                shutil.copy2(news_src, static_dir / "news_digest.json")
                # 归档目录累积同步(2026-08-16 用户定): 把 data/news_digest/*.json 全量
                # copy 到 static-site/data/news_digest/ + 追加 R2 data/news_digest/<date>.json
                # 与 staticdata 上传链,让历史日归档也能被前端/重跑读到(幂等覆盖,不删除历史)。
                arch_files: list[str] = ["news_digest.json"]
                arch_src_dir = news_src.parent / "news_digest"
                if arch_src_dir.is_dir():
                    sd_nd = static_dir / "news_digest"
                    sd_nd.mkdir(parents=True, exist_ok=True)
                    # 年目录结构 news_digest/<YYYY>/<date>.json(2026-08-16 主控存储结构决定)全量同步
                    for ydir in sorted(arch_src_dir.iterdir()):
                        if not ydir.is_dir() or not ydir.name.isdigit():
                            continue
                        dest_y = sd_nd / ydir.name
                        dest_y.mkdir(parents=True, exist_ok=True)
                        for arch_f in sorted(ydir.glob("*.json")):
                            shutil.copy2(arch_f, dest_y / arch_f.name)
                            arch_files.append(f"news_digest/{ydir.name}/{arch_f.name}")
                    # 索引
                    idx = arch_src_dir / "_index.json"
                    if idx.exists():
                        shutil.copy2(idx, sd_nd / "_index.json")
                        arch_files.append("news_digest/_index.json")
                    # 旧扁平路径(迁移期)同步到 static-site 扁平位(前端旧路径 fallback 兼容 #13)
                    for arch_f in arch_src_dir.glob("*.json"):
                        if arch_f.name == "_index.json":
                            continue
                        shutil.copy2(arch_f, sd_nd / arch_f.name)
                        if f"news_digest/{arch_f.name}" not in arch_files:
                            arch_files.append(f"news_digest/{arch_f.name}")
                files_out = files_out + arch_files
                log(f"news_digest.json + {len(arch_files)-1} 个日期归档已同步到 static_dir + 加入 R2/staticdata 上传链")
            except Exception as e:
                log(f"⚠ news_digest.json 复制/加入上传链失败(不阻塞): {e}")
                # files_out 已有主数据 2 件 + tts 兜底,不上传 news_digest 也能保证主数据上线
    # 无论 news_meta.available True/False、news_src 是否存在、复制成功与否,files_out 均含完整上传清单
    files_out_n = files_out
    # R2 上传(主数据 2 件 + news_digest.json(当日可用时) + tts mp3(若有);run_log 在 write_run_log 后单独传)
    tu = time.time()
    upload_to_r2(repo, args.no_upload, files=files_out_n)
    timings["r2"] = round(time.time() - tu, 2)
    # staticdata 同步(数据仓库留档,防 deploy 外生成器留旧版;best-effort)
    ts2 = time.time()
    staticdata_sync(repo, args.no_upload, files=files_out_n)
    timings["staticdata"] = round(time.time() - ts2, 2)

    # 结构化运行日志双写(run_log 审计缺口#4: 每步耗时+数据量+新鲜度+AI参数+输出摘要)
    run_entry = {
        "date": date,
        "version": version,
        "direction": brief["meta"].get("direction"),
        # 区间概览(2026-08-15): 大盘 range + 板块数 + 状态,供 run_log 快速核对
        "range": brief["meta"].get("range"),
        "range_status": brief["meta"].get("range_status"),
        "index_count": len(brief["meta"].get("index_ranges") or []),  # 中间层7全押
        "sector_count": len(brief["meta"].get("sector_ranges") or []),
        "confidence": brief["meta"].get("confidence"),
        "watch_count": len(brief["meta"].get("watch_list") or []),
        "risk_count": len(brief["meta"].get("risk_items") or []),
        "tts": {"ok": tts_ok, "file": tts_file or None, "ms": timings.get("tts", 0)},
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
