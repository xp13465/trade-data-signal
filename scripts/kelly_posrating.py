#!/usr/bin/env python3
"""kelly_posrating.py - AI仓位建议 K 档评级全史动态计算(后端注入首页方案 B, #54)

目的:
    在每日快照链(signal_kelly_snapshot.py)内增量计算「AI仓位建议 K 档评级」四档
    (K=1..4)全史数值, 输出到 static-site/data/signal_kelly_snapshots/latest_posrating.json。
    首页首屏经 app.js 注入首页槽(_AI_POSCAP_RATING_DYNAMIC_HOME)展示, 替代旧静态快照
    _AI_POSCAP_RATING(v1.1.4 八键历史数字), 消除「首页读静态 86.60% ↔ lab 动态 163%」跳变。

方法口径:
    复刻 lab.js _kellyApplyFeeRecompute K 档段(2026-09-04 用户拍板方案一数据驱动), 逐位对齐:
      - A 模式 all 伪象限 = rating_high+mid+low 三象限 A 模式并集(_posRaw)
      - basePool = 16 象限 × 10 卖出模式, S06 per-date passesFade 过滤 + baseKey 去重
      - S06 per-date 基座: 读 kelly_mode_s06_state.json, 每笔按 signal_date 取当日
        effective_mode(a9/new14)键集过滤; 快照缺行/未就绪 = fail-open 放行(与前端降级契约一致);
        覆盖期外 = 按快照 off_base(new14)兜底过滤; 基座未知 = 按 off_base 兜底过滤。
      - 每日资金池等分 + top-K: 当日保留前 K 基笔(排序 track_score DESC→rating→signal→buy_date ASC),
        每笔金额 = buy_amount / 当日保留基笔数; 每日总投入恒 1 万。
      - 费率重算(_kellyRecomputeTrade): 还原无滑点收盘价 → 按当前费率档(默认 etf_main
        万0.5/最低0.1元/滑点0.001)重算 profit/return_pct。
      - 统计(_kellyComputeStats): return_pct_max_holding = 总盈亏 / 峰值同时持仓资金 ×100;
        峰值资金回撤 = 最大回撤金额 / 峰值同时持仓资金 ×100; ra = 收益率/峰值资金回撤; n = 样本数。
      - 档位名称(name)按 ddNum 从大到小排序派生(与 common.js _aiPoscapRatingNameByDd 同源):
        dd最大→最激进/次大→次稳健/次小→最稳健/最小→最保守; ★主推 = 收益率 retNum 最高档。

输入依赖:
    - <DATA_DIR>/signal_kelly_trades.json        (回测交易记录, export.py 同批生成)
    - <DATA_DIR>/signal_kelly_backtest.json      (回测统计, 取 config.sell_modes A-J 模式表)
    - <DATA_DIR>/kelly_mode_s06_state.json       (S06 大盘领先切换快照, gen_kelly_mode_s06_state.py 产出)
    - <DATA_DIR>/kelly_loss_features.json        (AI降亏 12 特征全史序列 + meta.rules 规格)
输出:
    - <DATA_DIR>/signal_kelly_snapshots/latest_posrating.json
      { computed:true, date:<快照日>, mode:"s06", fee:"ETF主流(万0.5/最低0.1元)",
        values:{1..4:{name,ret,dd,ra,n,retNum,ddNum,nNum}} }
关键参数(常量, 与 lab.js/common.js 逐位对齐, 改参数必须同步前端 §22/§23.13):
    - KELLY_ORIG_SLIPPAGE=0.001, FEE_ETF_MAIN(默认费率档)
    - FADE_MODE_PRESETS a9/new14 键集 = common.js _KELLY_FADE_MODE_PRESETS(单源咬合 §22)
    - LEGACY_SPECS(FRONT 10 + GATE 27) = common.js _KELLY_FADE_LEGACY_SPECS
    - MONTH_MASK = lab.js _kellyMonthMask
复现命令:
    python scripts/kelly_posrating.py --data-dir <DATA_DIR> [--write]
    # --write 缺省=只计算打印摘要(不落盘); 快照链 signal_kelly_snapshot.py 以 --write 调用
    python scripts/check_posrating_parity.mjs TRADES_JSON S06_JSON FEAT_JSON  # 对账机检
"""
import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
DEFAULT_DATA_DIR = ROOT / "static-site" / "data"

# ---------------------------------------------------------------------------
# 常量(与前端逐位对齐)
# ---------------------------------------------------------------------------
KELLY_ORIG_SLIPPAGE = 0.001           # lab.js KELLY_ORIG_SLIPPAGE
BUY_AMOUNT_DEFAULT = 10000            # trades.buy_amount 缺省
# 默认费率档 etf_main(lab.js KELLY_FEE_PRESETS, 前端默认 labSigKellyFeePreset="etf_main")
FEE_ETF_MAIN = {
    "commission_rate": 0.00005, "min_commission": 0.1, "slippage": 0.001,
    "transfer_fee_rate_sh": 0.00001, "stamp_duty_rate": 0.0,
}
# 买入价位五分位边界(lab.js _kellyBuypriceBin)
PRICE_BINS = [0.841441, 1.015314, 1.194593, 1.446645]  # <= → vlow/low/mid/high, 更大 → vhigh

# 模式预设(common.js _KELLY_FADE_MODE_PRESETS 单源转录; s06/s06p1 为 dynamic 无 keys)
# S06 快照 effective_mode 当前为 a9/new14; 历史基座(new15 等)经 bad_mode_fallback 按原键集过滤。
# §22 键集号登记点, 改动必须同步 common.js/lab.js。
FADE_MODE_PRESETS = {
    "p8": ["excludeSpecialBear", "n2NovSpecialIndustry", "janMidRating", "janMidSpecial",
           "k2c5HkChase", "r7MayReinforced", "excludeAuxCross", "greedy15"],
    "p9": ["excludeSpecialBear", "n2NovSpecialIndustry", "janMidRating", "janMidSpecial",
           "k2c5HkChase", "r7MayReinforced", "excludeAuxCross", "greedy15",
           "bullAuxBackupStop"],
    "a9": ["excludeSpecialBear", "n2NovSpecialIndustry", "janMidRating", "janMidSpecial",
           "k2c5HkChase", "r7MayReinforced", "excludeAuxCross", "greedy15",
           "bullAuxBackupStop", "t1LowTurnSpecial", "q1QvixLowPct", "m1MarginDownBull",
           "v1HighVol20", "r1VolRatioLow", "k3ConceptBuy", "r2bSpecialGlobal",
           "r2gLowRatingQ3"],
    "b9": ["excludeSpecialBear", "n2NovSpecialIndustry", "janMidRating", "janMidSpecial",
           "k2c5HkChase", "r7MayReinforced", "excludeAuxCross", "greedy15",
           "bullAuxBackupStop", "t1LowTurnSpecial", "q1QvixLowPct", "m1MarginDownBull",
           "r1VolRatioLow", "r2bSpecialGlobal", "r2gLowRatingQ3"],
    "c9": ["excludeSpecialBear", "n2NovSpecialIndustry", "janMidRating", "janMidSpecial",
           "k2c5HkChase", "r7MayReinforced", "excludeAuxCross", "greedy15",
           "bullAuxBackupStop", "n1NorthOutflow", "t1LowTurnSpecial", "d1LowDivYield",
           "h1VolChgHighA", "m1MarginDownBull", "p1LowDivBackup", "r2bSpecialGlobal"],
    "new14": ["r10May6NonMay", "greedy15", "janMidSpecial", "k2c5HkChase", "k3ConceptBuy",
              "declinePhaseSpecial", "n1NorthOutflow", "t1LowTurnSpecial", "d1LowDivYield",
              "q1QvixLowPct", "h1VolChgHighA", "m1MarginDownBull", "p1LowDivBackup",
              "r2bSpecialGlobal"],
    "new15": ["r10May6NonMay", "greedy15", "janMidSpecial", "k2c5HkChase", "k3ConceptBuy",
              "declinePhaseSpecial", "n1NorthOutflow", "t1LowTurnSpecial", "d1LowDivYield",
              "q1QvixLowPct", "h1VolChgHighA", "m1MarginDownBull", "p1LowDivBackup",
              "r2bSpecialGlobal", "excludeTierNone"],
}

# FRONT 10 + GATE 27 键规格(common.js _KELLY_FADE_LEGACY_SPECS 逐条转录; T1 走 loss_rules.py)
# 组件字段: sig/sigIn/mm/mmIn/ddMin/ddMax/wd/bpb/q/tsMax/mkt(→mktD)/etf(→etfD)/rat(→ratD)/
#           tier/tierIn/tierAll/tierCybIn/ratingIsLow/mstateNotTrue/mstateFalse
LEGACY_SPECS = {
    "excludeAux":            {"any": [{"sig": "buy_aux"}]},
    "marketTiming":          {"any": [{"mstateNotTrue": 1}]},
    "excludeMonth":          {"any": [{"mmIn": ["03", "05"]}]},
    "excludeRatingLow":      {"any": [{"ratingIsLow": 1}]},
    "excludeAuxCross":       {"any": [{"sig": "buy_aux", "mmIn": ["03", "05"]}]},
    "excludeSpecialBear":    {"any": [{"sig": "buy_special", "tierIn": ["熊市·主跌", "下降期"]}]},
    "legacyMa60Special":     {"any": [{"sig": "buy_special", "mstateFalse": 1}]},
    "declinePhaseSpecial":   {"any": [{"sig": "buy_special", "tierAll": "下降期"}]},
    "excludeSpecialBearCyb": {"any": [{"sig": "buy_special", "tierCybIn": ["熊市·主跌", "下降期"]}]},
    "bullAuxBackupStop":     {"any": [{"sigIn": ["buy_aux", "buy_backup"], "tier": "牛市·主升"}]},
    "n1MarTueHigh":          {"any": [{"mm": "03", "wd": 2, "bpb": "high"}]},
    "n2NovSpecialIndustry":  {"any": [{"sig": "buy_special", "mm": "11", "mkt": "industry"}]},
    "r8PureNonMay":          {"any": [{"mm": "03", "wd": 2, "bpb": "high"},
                                      {"sig": "buy_special", "mm": "11", "mkt": "industry"},
                                      {"sig": "buy_special", "mm": "11", "wd": 0}]},
    "n3NovSpecialMon":       {"any": [{"sig": "buy_special", "mm": "11", "wd": 0}]},
    "n4AMay":                {"any": [{"mkt": "a", "mm": "05"}]},
    "r7MayReinforced":       {"any": [{"mkt": "a", "mm": "05"}, {"rat": "mid", "mm": "05"},
                                      {"mm": "05", "bpb": "vlow"}, {"mm": "03", "wd": 2, "bpb": "high"},
                                      {"sig": "buy_special", "mm": "11", "mkt": "industry"},
                                      {"sig": "buy_special", "mm": "11", "wd": 0}]},
    "n5MayVlow":             {"any": [{"mm": "05", "bpb": "vlow"}]},
    "n6MidMay":              {"any": [{"rat": "mid", "mm": "05"}]},
    "r10May6NonMay":         {"any": [{"mm": "05"}, {"mm": "03", "wd": 2, "bpb": "high"},
                                      {"sig": "buy_special", "mm": "11", "mkt": "industry"},
                                      {"sig": "buy_special", "mm": "11", "wd": 0},
                                      {"sig": "buy_special", "mm": "11", "bpb": "low"},
                                      {"sig": "buy_special", "mm": "03", "mkt": "industry"},
                                      {"mm": "03", "wd": 2, "sig": "buy_aux"}]},
    "v4cSimple":             {"any": [{"mm": "03", "wd": 2, "sig": "buy_aux"}]},
    "v4b":                   {"any": [{"mkt": "a", "mm": "05", "sig": "buy_special", "etf": "related"}]},
    "greedy7":               {"any": [{"sig": "buy_special", "mm": "05"},
                                      {"sig": "buy_special", "mm": "11", "mkt": "concept"},
                                      {"sig": "buy_special", "mm": "03"}, {"sig": "buy_aux", "mm": "01"},
                                      {"q": 2, "bpb": "vlow", "sig": "buy_aux", "mkt": "concept"},
                                      {"sig": "buy", "mm": "01"}, {"mm": "03", "wd": 2, "mkt": "concept", "rat": "low"}]},
    "v4d":                   {"any": [{"mm": "12", "wd": 1, "sig": "buy_aux", "tsMax": 50}]},
    "v4j":                   {"any": [{"mm": "05", "bpb": "vlow", "sig": "buy_special"}]},
    "v4i":                   {"any": [{"sig": "buy_special", "mm": "05", "mkt": "concept", "wd": 0}]},
    "greedy10":              {"any": [{"sig": "buy_special", "mm": "05"},
                                      {"sig": "buy_special", "mm": "11", "mkt": "concept"},
                                      {"sig": "buy_special", "mm": "03"}, {"sig": "buy_aux", "mm": "01"},
                                      {"q": 2, "bpb": "vlow", "sig": "buy_aux", "mkt": "concept"},
                                      {"sig": "buy", "mm": "01"}, {"mm": "03", "wd": 2, "mkt": "concept", "rat": "low"},
                                      {"sig": "buy_aux", "mm": "12", "tsMax": 50},
                                      {"mm": "06", "bpb": "vlow", "rat": "low"}, {"sig": "buy_aux", "mm": "05"}]},
    "v4f":                   {"any": [{"sig": "buy", "mm": "06", "wd": 2, "etf": "related"}]},
    "v4g":                   {"any": [{"mkt": "global", "q": 1, "sig": "buy_aux", "rat": "low"}]},
    "v4m":                   {"any": [{"sig": "buy_special", "mm": "09", "wd": 2}]},
    "v4k":                   {"any": [{"sig": "buy", "mm": "01", "bpb": "high"}]},
    "greedy15":              {"any": [{"sig": "buy_special", "mm": "05"},
                                      {"sig": "buy_special", "mm": "11", "mkt": "concept"},
                                      {"sig": "buy_special", "mm": "03"}, {"sig": "buy_aux", "mm": "01"},
                                      {"q": 2, "bpb": "vlow", "sig": "buy_aux", "mkt": "concept"},
                                      {"sig": "buy", "mm": "01"}, {"mm": "03", "wd": 2, "mkt": "concept", "rat": "low"},
                                      {"sig": "buy_aux", "mm": "12", "tsMax": 50},
                                      {"mm": "06", "bpb": "vlow", "rat": "low"}, {"sig": "buy_aux", "mm": "05"},
                                      {"sig": "buy_special", "mm": "11", "mkt": "industry"},
                                      {"mm": "04", "wd": 1, "mkt": "concept", "tsMax": 50},
                                      {"mkt": "global", "q": 1, "sig": "buy_aux", "rat": "low"},
                                      {"mm": "01", "bpb": "low", "sig": "buy_special", "mkt": "concept"},
                                      {"sig": "buy_special", "mm": "09", "wd": 2}]},
    "a5NovMidSpecial":       {"any": [{"sig": "buy_special", "mm": "11", "ddMin": 11, "ddMax": 20}]},
    "a45NovMidLateSpecial":  {"any": [{"sig": "buy_special", "mm": "11", "ddMin": 11}]},
    "janMidRating":          {"any": [{"mm": "01", "ddMin": 11, "ddMax": 20, "rat": "mid"}]},
    "janMidSpecial":         {"any": [{"sig": "buy_special", "mm": "01", "ddMin": 11, "ddMax": 20}]},
    "k2c5HkChase":           {"any": [{"sigIn": ["buy_special", "buy_backup"], "mkt": "hk"}]},
    "k3ConceptBuy":          {"any": [{"sig": "buy", "mkt": "concept"}]},
}
FRONT_KEY_ORDER = ["excludeAux", "marketTiming", "excludeMonth", "excludeRatingLow",
                   "excludeAuxCross", "excludeSpecialBear", "legacyMa60Special",
                   "declinePhaseSpecial", "excludeSpecialBearCyb", "bullAuxBackupStop"]
GATE_KEY_ORDER = ["n1MarTueHigh", "n2NovSpecialIndustry", "r8PureNonMay", "n3NovSpecialMon",
                  "n4AMay", "r7MayReinforced", "n5MayVlow", "n6MidMay", "r10May6NonMay",
                  "v4cSimple", "v4b", "greedy7", "v4d", "v4j", "v4i", "greedy10", "v4f",
                  "v4g", "v4m", "v4k", "greedy15", "a5NovMidSpecial", "a45NovMidLateSpecial",
                  "janMidRating", "janMidSpecial", "k2c5HkChase", "k3ConceptBuy"]
# T1 20+X1(loss_rules.py RULE_SPECS 生产键名, 与 common.js _KELLY_FADE_T1_KEYS 同源 §22)
T1_KEY_ORDER = ["r2gLowRatingQ3", "n1NorthOutflow", "t1LowTurnSpecial", "d1LowDivYield",
                "q1QvixLowPct", "h1VolChgHighA", "m1MarginDownBull", "d2LowDivBull",
                "p1LowDivBackup", "v1HighVol20", "s1SentALow", "r1VolRatioLow",
                "r2bSpecialGlobal", "n2NorthOutConcept", "v2Vol20Gt25", "s2SentHs300Low",
                "w1BackupDecline", "a1BullAllStop", "v3Vol20LowPct", "ad1AdlineHot",
                "excludeTierNone"]
ALL_FADE_KEYS = FRONT_KEY_ORDER + GATE_KEY_ORDER + T1_KEY_ORDER

# 月门 mask(lab.js _kellyMonthMask; 值=JS 手算 bitmask, 汉语注释保留原语义)
MONTH_MASK = {
    "a5NovMidSpecial": 1 << 10, "a45NovMidLateSpecial": 1 << 10, "n1MarTueHigh": 1 << 2,
    "n2NovSpecialIndustry": 1 << 10, "r8PureNonMay": (1 << 2) | (1 << 10),
    "n3NovSpecialMon": 1 << 10, "n4AMay": 1 << 4, "r7MayReinforced": (1 << 4) | (1 << 2) | (1 << 10),
    "n5MayVlow": 1 << 4, "n6MidMay": 1 << 4, "r10May6NonMay": (1 << 4) | (1 << 2) | (1 << 10),
    "v4cSimple": 1 << 2, "v4b": 1 << 4,
    "greedy7": (1 << 4) | (1 << 10) | (1 << 2) | (1 << 0) | (1 << 3) | (1 << 5),
    "v4d": 1 << 11, "v4j": 1 << 4, "v4i": 1 << 4,
    "greedy10": (1 << 4) | (1 << 10) | (1 << 2) | (1 << 0) | (1 << 3) | (1 << 5) | (1 << 11),
    "v4f": 1 << 5, "v4g": (1 << 0) | (1 << 1) | (1 << 2), "v4m": 1 << 8, "v4k": 1 << 0,
    "greedy15": (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5) | (1 << 8) | (1 << 10) | (1 << 11),
    "janMidRating": 1 << 0, "janMidSpecial": 1 << 0,
    "k2c5HkChase": 0x1FFF, "k3ConceptBuy": 0x1FFF,
}
LOG_TAG = "[kelly_posrating]"


def log(msg):
    print(f"{LOG_TAG} {msg}", flush=True)


def _r4(x):
    """JS Math.round(x*10000)/10000 四舍五入到 4 位小数(银行家无关, Python round 同款半进退, JS 为标准四舍五入退 0.5 向上)。"""
    return math.floor(x * 10000 + 0.5) / 10000


def _r4f(x):
    """JS (x).toFixed(2) 字符串两位小数。"""
    return ("%.2f" % x)


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def _base_key(t, fIdx):
    return (str(t[fIdx["signal_date"]] or "") + "|" + str(t[fIdx["index_id"]] or "") + "|"
            + str(t[fIdx["signal"]] or "") + "|" + str(t[fIdx["buy_date"]] or "") + "|"
            + str(t[fIdx["etf_code"]] or ""))


def _base_key_full(t, fIdx):
    """含 sell_date 的 6 字段键(_kellyBuildTradeDims 用)。"""
    return (str(t[fIdx["signal_date"]] or "") + "|" + str(t[fIdx["index_id"]] or "") + "|"
            + str(t[fIdx["signal"]] or "") + "|" + str(t[fIdx["buy_date"]] or "") + "|"
            + str(t[fIdx["etf_code"]] or "") + "|" + str(t[fIdx["sell_date"]] or ""))


def _is_sh_etf(ec):
    """lab.js _kellyIsShEtf: 沪市 ETF(51/58 开头)。"""
    return bool(ec) and (ec.startswith("51") or ec.startswith("58"))


def _buy_weekday(buy_date_str):
    """lab.js _kellyBuyWeekday: JS Date getDay → (jsDay+6)%7, Python 0=Monday。"""
    s = str(buy_date_str or "")
    if len(s) < 8:
        return -1
    y, m, d = int(s[0:4]), int(s[4:6]), int(s[6:8])
    js_day = datetime(y, m, d).weekday()  # Python: 0=Monday
    # JS: getDay 0=Sun..6=Sat; Python weekday 0=Mon..6=Sun。换算: jsDay = (pyWd + 1) % 7
    js_day = (js_day + 1) % 7
    return (js_day + 6) % 7  # 0=Mon 1=Tue 2=Wed


def _buyprice_bin(price):
    """lab.js _kellyBuypriceBin: 五分位边界。"""
    if price is None:
        return ""
    if price <= PRICE_BINS[0]:
        return "vlow"
    if price <= PRICE_BINS[1]:
        return "low"
    if price <= PRICE_BINS[2]:
        return "mid"
    if price <= PRICE_BINS[3]:
        return "high"
    return "vhigh"


def _tds_fade_spec_hit(key, c, specs=None):
    """common.js _tdsFadeSpecHit 逐字段等效。c 字段: sig/mm/dd/wd/bpb/q/ts/mktD/etfD/ratD/
    tier/tierAll/tierCyb/rating/mstate。"""
    sp = (specs or LEGACY_SPECS).get(key)
    if not sp:
        return False
    for p in sp.get("any", []):
        ok = True
        if "sig" in p and c.get("sig") != p["sig"]:
            ok = False
        if "sigIn" in p and c.get("sig") not in p["sigIn"]:
            ok = False
        if "mm" in p and c.get("mm") != p["mm"]:
            ok = False
        if "mmIn" in p and c.get("mm") not in p["mmIn"]:
            ok = False
        if "ddMin" in p and not (c.get("dd", 0) >= p["ddMin"]):
            ok = False
        if "ddMax" in p and not (c.get("dd", 0) <= p["ddMax"]):
            ok = False
        if "wd" in p and c.get("wd") != p["wd"]:
            ok = False
        if "bpb" in p and c.get("bpb") != p["bpb"]:
            ok = False
        if "q" in p and c.get("q") != p["q"]:
            ok = False
        if "tsMax" in p and not (float(c.get("ts", 0)) < p["tsMax"]):
            ok = False
        if "mkt" in p and c.get("mktD") != p["mkt"]:
            ok = False
        if "etf" in p and c.get("etfD") != p["etf"]:
            ok = False
        if "rat" in p and c.get("ratD") != p["rat"]:
            ok = False
        if "tier" in p and c.get("tier") != p["tier"]:
            ok = False
        if "tierIn" in p and c.get("tier") not in p["tierIn"]:
            ok = False
        if "tierAll" in p and c.get("tierAll") != p["tierAll"]:
            ok = False
        if "tierCybIn" in p and c.get("tierCyb") not in p["tierCybIn"]:
            ok = False
        if "ratingIsLow" in p and c.get("rating") != "low":
            ok = False
        if "mstateNotTrue" in p and c.get("mstate") is True:
            ok = False
        if "mstateFalse" in p and c.get("mstate") is not False:
            ok = False
        if ok:
            return True
    return False


def _active_month_mask(filters):
    """lab.js _kellyActiveMonthMask: 活跃键月门 bitmask 并集。"""
    mask = 0
    for k, v in MONTH_MASK.items():
        if filters.get(k):
            mask |= v
    return mask


# ---------------------------------------------------------------------------
# S06 解析器(common.js _tdsS06BaseForDate/_tdsS06FiltersForDate 等效)
# ---------------------------------------------------------------------------
class S06Resolver:
    """日期 → 生效基座 → 58 键 filters。fail-open/兜底语义与前端降级契约一致(§23.15)。"""

    def __init__(self, s06_doc):
        # 结构校验(与 common.js _tdsS06StateEnsure 同: daily 数组非空 + threshold 为数字 + on/off_base 存在)
        state = s06_doc or {}
        if (not state or not isinstance(state.get("daily"), list) or not state.get("daily")
                or not isinstance(state.get("threshold"), (int, float))
                or not state.get("on_base") or not state.get("off_base")):
            self.state = None
        else:
            self.state = state
        self.by_date = {}
        if self.state:
            for row in self.state.get("daily") or []:
                nd = str(row.get("date") or "").replace("-", "").replace("/", "")
                self.by_date[nd] = row
        self.coverage_start = str((self.state or {}).get("coverage_start") or "").replace("-", "").replace("/", "")
        self.coverage_end = str((self.state or {}).get("coverage_end") or "").replace("-", "").replace("/", "")
        self.off_base = (self.state or {}).get("off_base") or "new14"
        self._filters_cache = {}

    def base_for_date(self, date_str):
        """返回 (ok, base, reason); ok=False = fail-open(前端真降级 no_row/not_loaded/load_err)。"""
        nd = str(date_str or "").replace("-", "").replace("/", "")
        if not self.state:
            return (False, None, "not_loaded")
        row = self.by_date.get(nd)
        if row is None:
            out_of_range = (self.coverage_start and nd < self.coverage_start) or (
                self.coverage_end and nd > self.coverage_end)
            if not out_of_range:
                return (False, None, "no_row")
            return (True, self.off_base, "out_of_range_fallback")
        base = row.get("effective_mode")
        if base not in ("a9", "new14"):
            # bad_mode_fallback: 基座非主键集 → 前端口径=按原键集(历史合法基座)或 off_base 兜底
            if base in FADE_MODE_PRESETS:
                return (True, base, "bad_mode_fallback")
            return (True, self.off_base, "bad_mode_fallback")
        return (True, base, "ok")

    def filters_for_date(self, date_str):
        """该日生效基座的 58 键 filters(共享只读, 与 _tdsS06FiltersForDate 同构); 不可用返回 None。"""
        ok, base, _ = self.base_for_date(date_str)
        if not ok:
            return None
        f = self._filters_cache.get(base)
        if f is None:
            f = {k: False for k in ALL_FADE_KEYS}
            for k in FADE_MODE_PRESETS.get(base, []):
                if k in f:
                    f[k] = True
            self._filters_cache[base] = f
        return f


# ---------------------------------------------------------------------------
# 特征与谓词(T1 走 loss_rules.py, 与 lab.js _kellyLossRuleHit/spec 同构)
# ---------------------------------------------------------------------------
def _trade_dims(quads, fIdx):
    """lab.js _kellyBuildTradeDims: quadrant key 前缀 → dims{rating/etf/sig/mkt} 映射。"""
    dims = {}
    for qk, modes in quads.items():
        parts = qk.split("_")
        dim_type, dim_val = parts[0], "_".join(parts[1:])
        if not isinstance(modes, dict):
            continue
        for arr in modes.values():
            if not isinstance(arr, list):
                continue
            for t in arr:
                key = (str(t[fIdx["signal_date"]] or "") + "|" + str(t[fIdx["index_id"]] or "") + "|"
                       + str(t[fIdx["signal"]] or "") + "|" + str(t[fIdx["buy_date"]] or "") + "|"
                       + str(t[fIdx["etf_code"]] or "") + "|" + str(t[fIdx["sell_date"]] or ""))
                d = dims.setdefault(key, {})
                d[dim_type] = dim_val
    return dims


def _trade_features(t, fIdx, trade_dims):
    """lab.js _kellyTradeFeatures 逐字段等效。"""
    bd = str(t[fIdx["buy_date"]] or "")
    mm = bd[4:6] if len(bd) >= 6 else ""
    dd = 0
    try:
        dd = int(bd[6:8]) if len(bd) >= 8 else 0
    except (ValueError, TypeError):
        dd = 0
    sig = str(t[fIdx["signal"]] or "") if fIdx.get("signal") is not None else ""
    wd = _buy_weekday(bd)
    bpb = _buyprice_bin(t[fIdx["buy_price"]]) if fIdx.get("buy_price") is not None else ""
    mkt_d = ""
    rat_d = ""
    if trade_dims:
        dk = (str(t[fIdx["signal_date"]] or "") + "|" + str(t[fIdx["index_id"]] or "") + "|"
              + sig + "|" + bd + "|" + str(t[fIdx["etf_code"]] or "") + "|"
              + str(t[fIdx["sell_date"]] or ""))
        d = trade_dims.get(dk) or {}
        mkt_d = d.get("mkt", "")
        rat_d = d.get("rating", "")
    ts = t[fIdx["track_score"]] if fIdx.get("track_score") is not None else 999
    if ts is None:
        ts = 999
    etf_d = str(t[fIdx["track_tier"]] or "") if fIdx.get("track_tier") is not None else ""
    q = 0
    if mm:
        try:
            q = math.ceil(int(mm) / 3)
        except (ValueError, TypeError):
            q = 0
    return {"mm": mm, "dd": dd, "sig": sig, "wd": wd, "bpb": bpb, "mktD": mkt_d,
            "ratD": rat_d, "ts": ts, "etfD": etf_d, "q": q}


def _loss_rule_hit(key, ctx, loss_spec_map, feat_at):
    """lab.js _kellyLossRuleHit 等效(与 loss_rules.py rule_hit 同构; 此处直接移植 JS 判定
    共用 loss_spec_map(meta.rules)/feat_at 特征查值闭包, 保证与前端同源)。"""
    spec = loss_spec_map.get(key)
    if not spec:
        return False
    if spec.get("feature"):
        v = feat_at(spec["feature"], str(ctx.get("date") or ""))
        if v is None:
            return False
        th = spec.get("threshold")
        if spec["direction"] == "low":
            if not (v < th):
                return False
        else:
            if not (v > th):
                return False
    if spec.get("sig") is not None and str(ctx.get("sig") or "") != spec["sig"]:
        return False
    if spec.get("tier") is not None and str(ctx.get("tier") or "") != spec["tier"]:
        return False
    if spec.get("mkt") is not None and str(ctx.get("mkt") or "") != spec["mkt"]:
        return False
    if spec.get("track_tier") is not None:
        ctx_tt = str(ctx.get("track_tier") or "")
        spec_tt = spec["track_tier"]
        if isinstance(spec_tt, list):
            if ctx_tt not in spec_tt:
                return False
        else:
            if ctx_tt != spec_tt:
                return False
    if spec.get("rating") is not None:
        if str(ctx.get("rating") or "") != spec["rating"]:
            return False
        tv = 999.0 if ctx.get("ts") in (None, "") else float(ctx["ts"])
        if not (tv < spec["max_ts"]):
            return False
        if str(ctx.get("smonth") or "") not in (spec.get("months") or []):
            return False
    return True


def make_passes_fade(fIdx, trade_dims, loss_spec_map, feat_at, s06):
    """构造 S06 per-date passesFade(等效 lab.js _kellyApplyFeeRecompute L8487-8495),
    外加完整 _kellyPassesFadeFilters(FRONT+GATE+T1 三层)。T1 纯字段键(w1/a1/r2b/r2g/X1)
    不依赖特征 JSON, 直接判定; 特征类键缺失特征 = 不拦(诚实降级)。"""
    T1_KEY_SET = set(T1_KEY_ORDER)

    def passes(t):
        f6 = s06.filters_for_date(str(t[fIdx["signal_date"]] or "")) if s06 else None
        if s06 and f6 is None:
            return True  # fail-open(前端降级契约: 快照缺行/未就绪 → 放行)
        # 兜底: s06 未提供时用静态默认?不可能——本计算恒走 s06。防御: f6 为 None 时放行。
        filters = f6
        if filters is None:
            return True
        mm = _active_month_mask(filters)
        # ---- FRONT 10 键(前置简单键, 不进月门区) ----
        bd_str = str(t[fIdx["buy_date"]] or "")
        front_ctx = {
            "sig": str(t[fIdx["signal"]] or "") if fIdx.get("signal") is not None else "",
            "mm": bd_str[4:6] if len(bd_str) >= 6 else "",
            "rating": str(t[fIdx["rating"]] or "") if fIdx.get("rating") is not None else "",
            "tier": str(t[fIdx["market_tier"]] or "") if fIdx.get("market_tier") is not None else "",
            "tierAll": str(t[fIdx["market_tier_all"]] or "") if fIdx.get("market_tier_all") is not None else "",
            "tierCyb": str(t[fIdx["market_tier_cyb"]] or "") if fIdx.get("market_tier_cyb") is not None else "",
            "mstate": t[fIdx["market_state"]] if fIdx.get("market_state") is not None else None,
        }
        for k in FRONT_KEY_ORDER:
            if filters.get(k) and _tds_fade_spec_hit(k, front_ctx):
                return False
        # ---- GATE 27 键(月门 + 特征) ----
        v3_on = any(filters.get(k) for k in
                    ["n1MarTueHigh", "n2NovSpecialIndustry", "r8PureNonMay", "n3NovSpecialMon",
                     "n4AMay", "r7MayReinforced", "n5MayVlow", "n6MidMay", "r10May6NonMay"])
        v4_on = any(filters.get(k) for k in
                    ["greedy7", "greedy10", "greedy15", "v4cSimple", "v4b", "v4d", "v4j", "v4i",
                     "v4f", "v4g", "v4m", "v4k"])
        r3_on = filters.get("a5NovMidSpecial") or filters.get("a45NovMidLateSpecial")
        jan_on = filters.get("janMidRating") or filters.get("janMidSpecial")
        k2_on = filters.get("k2c5HkChase") or filters.get("k3ConceptBuy")
        if v3_on or v4_on or r3_on or jan_on or k2_on:
            mm_g = str(t[fIdx["buy_date"]] or "")[4:6] if len(str(t[fIdx["buy_date"]] or "")) >= 6 else ""
            mm_int = 0
            try:
                mm_int = int(mm_g) if mm_g else 0
            except (ValueError, TypeError):
                mm_int = 0
            if mm_int and not (mm & (1 << (mm_int - 1))):
                return True  # 月门短路: 该月不在任何活跃 toggle 月集合 → 直接通过
            feats = _trade_features(t, fIdx, trade_dims)
            for k in GATE_KEY_ORDER:
                if filters.get(k) and _tds_fade_spec_hit(k, feats):
                    return False
        # ---- T1 20+X1(loss_rules 规格, 无月门) ----
        m20_on = any(filters.get(k) for k in T1_KEY_ORDER)
        if m20_on:
            bd20 = str(t[fIdx["buy_date"]] or "")
            sd20 = str(t[fIdx["signal_date"]] or "") if fIdx.get("signal_date") is not None else ""
            sig20 = str(t[fIdx["signal"]] or "") if fIdx.get("signal") is not None else ""
            mkt20 = ""
            if trade_dims is not None:
                dk20 = (sd20 + "|" + str(t[fIdx["index_id"]] or "") + "|" + sig20 + "|" + bd20 + "|"
                        + str(t[fIdx["etf_code"]] or "") + "|" + str(t[fIdx["sell_date"]] or ""))
                mkt20 = (trade_dims.get(dk20) or {}).get("mkt", "")
            # track_tier 三态: 显式 null → "null"; 缺列/undefined → ""(诚实不命中)
            tt_val = ""
            if fIdx.get("track_tier") is not None:
                v = t[fIdx["track_tier"]]
                if v is None:
                    tt_val = "null"
                else:
                    tt_val = str(v)
            ctx20 = {
                "sig": sig20,
                "mkt": mkt20,
                "tier": str(t[fIdx["market_tier"]] or "") if fIdx.get("market_tier") is not None else "",
                "track_tier": tt_val,
                "date": bd20,
                "smonth": sd20[4:6] if len(sd20) >= 6 else "",
                "rating": str(t[fIdx["rating"]] or "") if fIdx.get("rating") is not None else "",
                "ts": t[fIdx["track_score"]] if fIdx.get("track_score") is not None else None,
            }
            for k in T1_KEY_ORDER:
                if filters.get(k):
                    # 纯字段键(无 feature)不依赖特征 JSON, 恒可判定; 特征类键缺特征=不拦
                    if _loss_rule_hit(k, ctx20, loss_spec_map, feat_at):
                        return False
        return True

    return passes


# ---------------------------------------------------------------------------
# K 档计算(复刻 lab.js L8712-8791)
# ---------------------------------------------------------------------------
def _position_cap_kept_keys(pool, fIdx, K):
    """lab.js _kellyPositionCapKeptKeys: 按 signal_date 分组, 组内排序 track_score DESC→rating
    (high>mid>low)→signal(buy_backup>buy>buy_aux>buy_special)→buy_date ASC, 保留前 K。"""
    kept = {}
    if not K or K <= 0 or not pool:
        return kept
    rating_rank = {"high": 0, "mid": 1, "low": 2, "": 3}
    sig_rank = {"buy_backup": 0, "buy": 1, "buy_aux": 2, "buy_special": 3, "": 9}
    by_date = {}
    for t in pool:
        sd = str(t[fIdx["signal_date"]] or "")
        if not sd:
            continue
        by_date.setdefault(sd, []).append(t)
    for sd, rows in by_date.items():
        def _cmp(a, b):
            sa = float(a[fIdx["track_score"]]) if fIdx.get("track_score") is not None else -1.0
            sb = float(b[fIdx["track_score"]]) if fIdx.get("track_score") is not None else -1.0
            if sb != sa:
                return -1 if sa > sb else 1  # track_score DESC(大在前)
            rak = str(a[fIdx["rating"]] or "") if fIdx.get("rating") is not None else ""
            rbk = str(b[fIdx["rating"]] or "") if fIdx.get("rating") is not None else ""
            ra = rating_rank.get(rak, 3)
            rb = rating_rank.get(rbk, 3)
            if ra != rb:
                return -1 if ra < rb else 1
            sgak = str(a[fIdx["signal"]] or "") if fIdx.get("signal") is not None else ""
            sgbk = str(b[fIdx["signal"]] or "") if fIdx.get("signal") is not None else ""
            sga = sig_rank.get(sgak, 9)
            sgb = sig_rank.get(sgbk, 9)
            if sga != sgb:
                return -1 if sga < sgb else 1
            da = str(a[fIdx["buy_date"]] or "")
            db = str(b[fIdx["buy_date"]] or "")
            if da != db:
                return -1 if da < db else 1
            return 0
        import functools
        rows.sort(key=functools.cmp_to_key(_cmp))
        n = min(K, len(rows))
        for j in range(n):
            kept[_base_key(rows[j], fIdx)] = True
    return kept


def _kept_day_counts(kept):
    """lab.js _kellyKeptDayCounts: baseKey 首字段=signal_date, 统计每日保留数。"""
    m = {}
    for k in kept:
        sd = str(k or "").split("|")[0]
        if sd:
            m[sd] = m.get(sd, 0) + 1
    return m


def _per_trade_amount(t, fIdx, buy_amount, day_kept_count):
    if day_kept_count and day_kept_count > 0:
        return buy_amount / day_kept_count
    return buy_amount


def _recompute_trade(t, fIdx, fee_params, buy_amount):
    """lab.js _kellyRecomputeTrade 逐位等效。t 为 compact 数组(列表)。"""
    bp = t[fIdx["buy_price"]] or 0
    sp = t[fIdx["sell_price"]] or 0
    cp = t[fIdx["current_price"]] or 0
    ec = str(t[fIdx["etf_code"]] or "") if fIdx.get("etf_code") is not None else ""
    sell_date = str(t[fIdx["sell_date"]] or "") if fIdx.get("sell_date") is not None else ""
    if bp <= 0:
        return {"profit": 0, "return_pct": 0, "fee_cost": 0}
    close_buy = bp / (1 + KELLY_ORIG_SLIPPAGE)
    close_sell = (sp / (1 - KELLY_ORIG_SLIPPAGE)) if sell_date else cp
    c = fee_params["commission_rate"]
    s = fee_params["slippage"]
    min_c = fee_params["min_commission"]
    sh = fee_params["transfer_fee_rate_sh"] if _is_sh_etf(ec) else 0
    stamp = fee_params["stamp_duty_rate"]
    buy_price_new = close_buy * (1 + s)
    if buy_price_new <= 0:
        return {"profit": 0, "return_pct": 0, "fee_cost": 0}
    shares_new = buy_amount / (buy_price_new * (1 + c + sh))
    gross_new = shares_new * buy_price_new
    comm_buy = gross_new * c
    if comm_buy < min_c:
        shares_new = (buy_amount - min_c) / (buy_price_new * (1 + sh))
        gross_new = shares_new * buy_price_new
        comm_buy = min_c
    sell_price_new = close_sell * (1 - s)
    sell_amount_new = shares_new * sell_price_new
    comm_sell = max(sell_amount_new * c, min_c)
    transfer_fee_sell = sell_amount_new * sh
    stamp_duty = sell_amount_new * stamp
    net_new = sell_amount_new - comm_sell - transfer_fee_sell - stamp_duty
    profit_new = net_new - buy_amount
    return_pct_new = profit_new / buy_amount * 100
    shares0 = buy_amount / close_buy
    profit0 = shares0 * close_sell - buy_amount
    fee_cost = profit0 - profit_new
    return {
        "profit": _r4(profit_new),
        "return_pct": _r4(return_pct_new),
        "fee_cost": _r4(fee_cost),
    }


def _max_concurrent(trades):
    """lab.js _kellyMaxConcurrent: 计数扫描线(先减后加)。trades 元素为 recompute dict
    (buy_date/sell_date 字段)。"""
    if not trades:
        return 0
    sentinel = "99999999"
    deltas = {}
    dates = []
    for tr in trades:
        bd = tr["buy_date"]
        sd = tr.get("sell_date") or sentinel
        db = deltas.setdefault(bd, {"b": 0, "s": 0})
        db["b"] += 1
        ds = deltas.setdefault(sd, {"b": 0, "s": 0})
        ds["s"] += 1
        if bd not in dates:
            dates.append(bd)
        if sd not in dates:
            dates.append(sd)
    dates.sort()
    cur = 0
    max_conc = 0
    for d in dates:
        dd = deltas[d]
        cur -= dd["s"]
        cur += dd["b"]
        if cur > max_conc:
            max_conc = cur
    return max_conc


def _max_concurrent_capital(trades):
    """lab.js _kellyMaxConcurrentCapital: 金额扫描线(先减后加), Math.round(x*10000)/10000。"""
    if not trades:
        return 0
    sentinel = "99999999"
    deltas = {}
    dates_set = set()
    for tr in trades:
        bd = tr["buy_date"]
        sd = tr.get("sell_date") or sentinel
        amt = tr.get("amount") or 0
        db = deltas.setdefault(bd, {"b": 0.0, "s": 0.0})
        db["b"] += amt
        ds = deltas.setdefault(sd, {"b": 0.0, "s": 0.0})
        ds["s"] += amt
        dates_set.add(bd)
        dates_set.add(sd)
    dates = sorted(dates_set)
    cur = 0.0
    max_c = 0.0
    for d in dates:
        dd = deltas[d]
        cur -= dd["s"]
        cur += dd["b"]
        if cur > max_c:
            max_c = cur
    return _r4(max_c)


def _max_drawdown(trades, buy_amount):
    """lab.js _kellyMaxDrawdown: 按 sell_date 排序累加 profit, abs/pct(总投入=每笔 amount 和)。"""
    if not trades:
        return {"abs": 0, "pct": 0}
    sorted_tr = sorted(trades, key=lambda tr: (tr.get("sell_date") or "99999999"))
    cumulative = 0.0
    peak = 0.0
    max_dd_abs = 0.0
    for tr in sorted_tr:
        cumulative += tr["profit"]
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd_abs:
            max_dd_abs = dd
    total_invest = sum((tr.get("amount") or buy_amount) for tr in trades)
    pct = (max_dd_abs / total_invest * 100) if total_invest > 0 else 0
    return {"abs": _r4(max_dd_abs), "pct": _r4(pct)}


def _compute_stats(trades, buy_amount):
    """lab.js _kellyComputeStats 全史(periodKey="all")所需字段: return_pct_max_holding/
    max_concurrent_capital/max_drawdown/n。trades 元素为 recompute dict。"""
    n = len(trades)
    if n == 0:
        return {"n": 0, "max_concurrent_capital": 0, "max_drawdown": 0,
                "max_concurrent": 0, "return_pct_max_holding": 0, "total_profit": 0}
    total_profit = _r4(sum((tr["profit"] or 0) for tr in trades))
    total_amount = sum((tr.get("amount") or buy_amount) for tr in trades)
    total_return = (total_amount > 0 and
                    sum((tr["profit"] or 0) for tr in trades) / total_amount * 100) or 0
    max_conc = _max_concurrent(trades)
    max_conc_cap = _max_concurrent_capital(trades)
    return_pct_max_holding = _r4(total_profit / max_conc_cap * 100) if max_conc_cap > 0 else 0
    dd = _max_drawdown(trades, buy_amount)
    return {
        "n": n,
        "total_return": _r4(total_return),
        "max_concurrent": max_conc,
        "max_concurrent_capital": max_conc_cap,
        "max_drawdown": dd["abs"],
        "max_drawdown_pct": dd["pct"],
        "return_pct_max_holding": return_pct_max_holding,
        "total_profit": total_profit,
    }


def _collect_base_pool(quads, sell_modes, fIdx, pass_fn):
    """lab.js _kellyCollectBasePool: 3 评级象限 × 10 模式, passFn 过滤 + baseKey 去重。
    (异步分片在前端, 后端同步即可)。"""
    pool = []
    seen = set()
    rks = ["rating_high", "rating_mid", "rating_low"]
    for rk in rks:
        for mk in sell_modes:
            arr = (quads.get(rk) or {}).get(mk) or []
            for t in arr:
                if pass_fn and not pass_fn(t):
                    continue
                bk = _base_key(t, fIdx)
                if bk not in seen:
                    seen.add(bk)
                    pool.append(t)
    return pool


def _derive_names(pos_vals):
    """common.js _aiPoscapRatingNameByDd: 按 ddNum 从大到小排序派生档名。"""
    order = [k for k in (1, 2, 3, 4) if k in pos_vals]
    order.sort(key=lambda k: pos_vals[k]["ddNum"], reverse=True)
    names = ["最激进", "次稳健", "最稳健", "最保守"]
    for idx, k in enumerate(order[:4]):
        pos_vals[k]["name"] = names[idx]
    return pos_vals


def compute_posrating(trades_doc, backtest_doc, s06_doc, loss_feat_doc):
    """主计算入口。返回 { computed, date, mode, fee, values:{1..4} }。"""
    fields = trades_doc.get("fields") or []
    fIdx = {f: i for i, f in enumerate(fields)}
    for need in ("signal_date", "index_id", "signal", "buy_date", "sell_date", "etf_code",
                 "buy_price", "sell_price", "current_price", "track_tier", "track_score",
                 "market_tier", "market_tier_all", "market_tier_cyb", "market_state", "rating"):
        if need not in fIdx:
            raise ValueError(f"trades.fields 缺必需字段: {need}")
    quads = trades_doc.get("quadrants") or {}
    buy_amount = trades_doc.get("buy_amount") or BUY_AMOUNT_DEFAULT
    sell_modes = ((backtest_doc.get("config") or {}).get("sell_modes")) or {}
    if not sell_modes:
        raise ValueError("backtest.config.sell_modes 缺失")
    # A 模式 all 伪象限(rating 三区并集) = quadsAll["A"]
    pos_raw = []
    for rk in ("rating_high", "rating_mid", "rating_low"):
        pos_raw += (quads.get(rk) or {}).get("A") or []
    # tradeDims(特征 mkt/rating 维度)
    trade_dims = _trade_dims(quads, fIdx)
    # T1 特征规格: loss_feat_doc.meta.rules → {key: spec}; feat_at 闭包
    spec_map = {}
    feat_at = lambda name, date: None
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
    s06 = S06Resolver(s06_doc)
    passes_fade = make_passes_fade(fIdx, trade_dims, spec_map, feat_at, s06)

    base_pool = _collect_base_pool(quads, sell_modes, fIdx, passes_fade)
    log(f"basePool={len(base_pool)} posRaw={len(pos_raw)}")
    if not base_pool or not pos_raw:
        raise ValueError("空基笔池/空 A 模式并集, 无法计算 K 档评级")
    fee = FEE_ETF_MAIN
    pos_vals = {}
    for K in (1, 2, 3, 4):
        kept = _position_cap_kept_keys(base_pool, fIdx, K)
        day_counts = _kept_day_counts(kept)
        kept_arr = []
        for tb in pos_raw:
            if not passes_fade(tb):
                continue
            if not kept.get(_base_key(tb, fIdx)):
                continue
            kept_arr.append(tb)
        recomp = []
        for tt in kept_arr:
            amt = _per_trade_amount(tt, fIdx, buy_amount,
                                    day_counts.get(str(tt[fIdx["signal_date"]] or "")))
            r = _recompute_trade(tt, fIdx, fee, amt)
            recomp.append({
                "profit": r["profit"],
                "return_pct": r["return_pct"],
                "fee_cost": r["fee_cost"],
                "buy_date": str(tt[fIdx["buy_date"]] or ""),
                "sell_date": str(tt[fIdx["sell_date"]] or ""),
                "hold_days": tt[fIdx["hold_days"]] or 0,
                "amount": amt,
            })
        st = _compute_stats(recomp, buy_amount)
        ret = st["return_pct_max_holding"]
        dd = _r4(st["max_drawdown"] / st["max_concurrent_capital"] * 100) if st["max_concurrent_capital"] > 0 else 0
        ra = _r4(ret / dd) if dd > 0 else None
        pos_vals[K] = {
            "name": "",
            "ret": "%.2f%%" % ret,
            "dd": "%.2f%%" % dd,
            "ra": "%.2f" % ra if ra is not None else "-",
            "n": f"{st['n']:,}",
            "retNum": ret,
            "ddNum": dd,
            "nNum": st["n"],
        }
        log(f"K{K}: ret={pos_vals[K]['ret']} dd={pos_vals[K]['dd']} ra={pos_vals[K]['ra']} n={pos_vals[K]['n']}")
    _derive_names(pos_vals)
    return {
        "computed": True,
        "date": datetime.now().strftime("%Y%m%d"),
        "generated_at": trades_doc.get("generated_at"),
        "mode": "s06",
        "fee": "ETF主流(万0.5/最低0.1元)",
        "values": pos_vals,
    }


def _resolve_ro_frame(path_str):
    p = Path(path_str)
    if not p.is_absolute():
        p = DEFAULT_DATA_DIR / p
    return p


def _main():
    ap = argparse.ArgumentParser(description="AI仓位建议 K 档评级全史动态计算")
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="数据目录(默认 static-site/data)")
    ap.add_argument("--write", action="store_true", help="写 latest_posrating.json(缺省只打印)")
    args = ap.parse_args()
    data_dir = _resolve_ro_frame(args.data_dir)
    trades_path = data_dir / "signal_kelly_trades.json"
    bt_path = data_dir / "signal_kelly_backtest.json"
    s06_path = data_dir / "kelly_mode_s06_state.json"
    feats_path = data_dir / "kelly_loss_features.json"
    with open(trades_path, "r", encoding="utf-8") as f:
        trades_doc = json.load(f)
    with open(bt_path, "r", encoding="utf-8") as f:
        bt_doc = json.load(f)
    s06_doc = None
    if s06_path.exists():
        with open(s06_path, "r", encoding="utf-8") as f:
            s06_doc = json.load(f)
    else:
        log("⚠ kelly_mode_s06_state.json 缺失, 按无 S06 处理(全放行, 不推荐)")
    loss_doc = None
    if feats_path.exists():
        with open(feats_path, "r", encoding="utf-8") as f:
            loss_doc = json.load(f)
    else:
        log("⚠ kelly_loss_features.json 缺失, T1 特征类键将不拦")
    result = compute_posrating(trades_doc, bt_doc, s06_doc, loss_doc)
    if args.write:
        snap_dir = data_dir / "signal_kelly_snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        out = snap_dir / "latest_posrating.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        log(f"已写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())