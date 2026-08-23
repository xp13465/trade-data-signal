# -*- coding: utf-8 -*-
"""AI降亏 20 条新键规则单源(T1 2026-08-23, 规格集中风格, 为谓词同源债清理铺路)。

【目的】把二轮挖掘(docs/kelly/analysis/scripts/sim_window_loss_mining_20260822/ 下
    mine21_bigtour.build_rules L23-62 + mine22_joint.build_r2 L24-34)的 20 条成员谓词
    提为生产级单一事实源——此前它们只活在挖掘脚本内存里, 数据断档即失传(T0 调研定案)。
【消费方】① app/queries.py `_ai_macro_hit_filters`(首页 ai_macro.filters 注入)
          ② static-site/lab.js `_kellyPassesFadeFilters` + static-site/app.js `_simPassesFade`
            (前端经 data/kelly_loss_features.json 的 meta.rules/meta.thresholds 读同一份规格,
             本文件 = 生成该 meta 的源头, 两端规格同源咬合 §22)
          ③ scripts/gen_kelly_loss_features.py(import QTH/RULE_SPECS 写出 meta)
【口径纪律】与挖掘脚本逐字对齐:
    ① 特征按 buy_date 查值(FR 工厂 series.get(str(t[3]))); 回测 buy_date ≡ signal_date
      (signal_kelly_backtest.py L559/605/681/717 直接赋信号日), 故 queries 信号级用 signal_date 无漂移
    ② 特征值缺失(None / 该日不在序列) → 不判命中(不拦), 与 FR 工厂 `if v is None: return False` 一致;
      天然兜底数据源边界(如 margin_chg20 两融仅 2021-02-10 起)
    ③ direction: 'low' = v < th, 'high' = v > th(严格不等号, 与挖掘一致)
    ④ 20 条新键均无月门(独立于 v3/v4/r3/jan/k2 门控组; 挖掘语义即无月门, 勿套 monthMask 短路)
    ⑤ tier 条件 = trades market_tier 字段语义(hs300 四档 × 仅 A股类注入, 非A股为 "" 天然不命中);
       mkt 条件 = _mktD 象限维度短名(a/concept/industry/hk/global/hk_industry)
    ⑥ R2g 月份取 signal_date(mine22 r2g 用 str(t[0])); ts 缺失视为 999(→ <75 不成立, 不拦)
【分位阈值 = 硬编码快照】QTH 数字从挖掘用的 mine10_features.json(2026-08-22 版, 与回测结论咬合)
    按 qth() 公式算出后固化, 不做每日滚动重算 —— 保证线上谓词判定与回测结论逐位一致
    (§23.6 口径一致性优先于自适应性, 2026-08-23 用户拍板)。重算快照需发版。
【复现】阈值计算命令:
    python3 - <<'EOF'
    import json
    feats=json.load(open('docs/kelly/analysis/scripts/sim_window_loss_mining_20260822/data/mine10_features.json'))
    def qth(f,p):
        vals=sorted(v for v in feats[f].values() if v is not None)
        return vals[min(int(p*(len(vals)-1)),len(vals)-1)]
    print(qth('north_d20',0.30))  # 其余同理
    EOF
    全链校验: python3 scripts/check_loss_rules_vs_mining.py(生产实现 vs 挖掘版命中集合全等断言)
"""
import json
import os

# ---------------------------------------------------------------------------
# 分位阈值快照(qth(fname, p), 来源=mine10_features.json 2026-08-22 版全史分位)
# ---------------------------------------------------------------------------
QTH = {
    "north_d20@0.30": -58.28060000000005,
    "turn_pct@0.30": 32.05298013245033,
    "div_yield@0.50": 2.59,
    "div_yield@0.70": 2.93,
    "qvix_pct@0.10": 4.105960264900662,
    "h_volchg@0.30": -23.622241791161258,
    "margin_chg20@0.70": 2.083932002876776,
    "div_pct@0.30": 28.60927152317881,
    "h_vol20@0.90": 30.65633657121166,
    "h_vol20@0.10": 10.728937386655433,
    "sent_a@0.20": 33.27,
    "vol_ratio_all@0.10": 0.8760650767911703,
    "sent_hs300@0.20": 35.07,
    "adline_gap@0.70": 0.06007314674006633,
}
# V2 用固定常数(非分位), 与挖掘 build_rules 'V2': FR('h_vol20','high',25.0) 一致
H_VOL20_V2_CONST = 25.0

# queries 端长形式市场名 → trades _mktD 短名(象限维度)映射(MARKET_QUAD_MAP 同源)
MKT_LONG2SHORT = {
    "mkt_a": "a",
    "mkt_concept": "concept",
    "mkt_industry": "industry",
    "mkt_hk": "hk",
    "mkt_global": "global",
    "mkt_hk_industry": "hk_industry",
}

# ---------------------------------------------------------------------------
# 20 条新键规格(键 → 参数 → 语义集中一处; 全部默认关, 现有默认组合零改动 §23.7)
# 字段: feature/direction/threshold = 特征条件(可选); sig = 信号类型条件(可选);
#       tier = A股类四档条件(可选); mkt = _mktD 短名域类条件(可选);
#       rating/max_ts/months/date_field = R2g 专用(rating==low × signal_date月∈months × ts<max_ts)
# group: 归属 lab.js _kellyFadeFlagGroups 4 大分类(calendar/market)
# vs9: vs9键边际净额元(口径=mime20_pool 补位口径 K1 / R2 族=round3 9键边际), 仅供文案引用非每日池比值
# ---------------------------------------------------------------------------
RULE_SPECS = {
    # ---- 新池 13(mine20_pool pool_in 11 + R2b/R2g; R2a≡k3ConceptBuy 生产已有键, 不重复)----
    "N1": dict(group="market", feature="north_d20", direction="low", threshold=QTH["north_d20@0.30"],
               desc="北向20日净流入<全史30分位(-58.3亿)", vs9=13695.43),
    "T1": dict(group="market", feature="turn_pct", direction="low", threshold=QTH["turn_pct@0.30"],
               sig="buy_special", desc="换手率3年分位<30 × 追关注", vs9=10548.90),
    "D1": dict(group="market", feature="div_yield", direction="low", threshold=QTH["div_yield@0.50"],
               desc="股息率<全史50分位(2.59%)", vs9=8552.36),
    "Q1": dict(group="market", feature="qvix_pct", direction="low", threshold=QTH["qvix_pct@0.10"],
               desc="QVIX 3年分位<10(波动率过度自满)", vs9=4341.45),
    "H1": dict(group="market", feature="h_volchg", direction="high", threshold=QTH["h_volchg@0.30"],
               mkt="a", desc="沪深300升波(5/20日波比>全史30分位) × A股", vs9=6646.89),
    "M1": dict(group="market", feature="margin_chg20", direction="low", threshold=QTH["margin_chg20@0.70"],
               tier="牛市·主升", desc="两融20日变化<70分位 × 牛市·主升", vs9=3035.14),
    "D2": dict(group="market", feature="div_yield", direction="low", threshold=QTH["div_yield@0.70"],
               tier="牛市·主升", desc="股息率<70分位 × 牛市·主升", vs9=5300.60),
    "P1": dict(group="market", feature="div_pct", direction="low", threshold=QTH["div_pct@0.30"],
               sig="buy_backup", desc="股息率3年分位<30 × 备买", vs9=571.34),
    "V1": dict(group="market", feature="h_vol20", direction="high", threshold=QTH["h_vol20@0.90"],
               desc="沪深300 20日已实现波动>90分位(30.7%)", vs9=3566.16),
    "S1": dict(group="market", feature="sent_a", direction="low", threshold=QTH["sent_a@0.20"],
               desc="A股情绪分<全史20分位", vs9=981.53),
    "R1": dict(group="market", feature="vol_ratio_all", direction="low", threshold=QTH["vol_ratio_all@0.10"],
               desc="全市场量能萎缩(<10分位)", vs9=1553.03),
    "R2b": dict(group="market", sig="buy_special", mkt="global",
                desc="追关注 × 全球类(R2 替补族)", vs9=8254.00),
    "R2g": dict(group="calendar", rating="low", max_ts=75, months=("07", "08", "09"), date_field="signal_date",
                desc="低评级 × 7-9月 × track_score<75(R2 替补族)", vs9=19442.00),
    # ---- 落池 7(mine20 dropped, 协同定性强加测试用)----
    "N2": dict(group="market", feature="north_d20", direction="low", threshold=QTH["north_d20@0.30"],
               mkt="concept", desc="北向20日净流出<30分位 × 概念类(N1 子集)", vs9=7053.81),
    "V2": dict(group="market", feature="h_vol20", direction="high", threshold=H_VOL20_V2_CONST,
               desc="20日已实现波动≥25%(固定常数)", vs9=-8635.64),
    "S2": dict(group="market", feature="sent_hs300", direction="low", threshold=QTH["sent_hs300@0.20"],
               desc="沪深300情绪分<全史20分位", vs9=-879.07),
    "W1": dict(group="market", sig="buy_backup", tier="下降期",
               desc="备买 × 下降期(A股类四档)", vs9=-2484.65),
    "A1": dict(group="market", tier="牛市·主升",
               desc="牛市·主升全类型全停(bullAuxBackupStop 超集)", vs9=-11884.00),
    "V3": dict(group="market", feature="h_vol20", direction="low", threshold=QTH["h_vol20@0.10"],
               desc="20日已实现波动<10分位(低波动)", vs9=-2470.24),
    "AD1": dict(group="market", feature="adline_gap", direction="high", threshold=QTH["adline_gap@0.70"],
                desc="AD线距MA20缺口>70分位(广度过热)", vs9=-235.61),
}

# 键名规范(生产键 = 小写前缀风格, 与现有 k2c5HkChase/k3ConceptBuy 命名族一致):
#   挖掘代号 N1 → 生产键 n1NorthOutflow 等; 映射单源在此, lab/app/queries 共用
MINING_TO_PROD_KEY = {
    "N1": "n1NorthOutflow",
    "T1": "t1LowTurnSpecial",
    "D1": "d1LowDivYield",
    "Q1": "q1QvixLowPct",
    "H1": "h1VolChgHighA",
    "M1": "m1MarginDownBull",
    "D2": "d2LowDivBull",
    "P1": "p1LowDivBackup",
    "V1": "v1HighVol20",
    "S1": "s1SentALow",
    "R1": "r1VolRatioLow",
    "R2b": "r2bSpecialGlobal",
    "R2g": "r2gLowRatingQ3",
    "N2": "n2NorthOutConcept",
    "V2": "v2Vol20Gt25",
    "S2": "s2SentHs300Low",
    "W1": "w1BackupDecline",
    "A1": "a1BullAllStop",
    "V3": "v3Vol20LowPct",
    "AD1": "ad1AdlineHot",
}
PROD_TO_MINING_KEY = {v: k for k, v in MINING_TO_PROD_KEY.items()}
NEW_KEYS_PROD = [MINING_TO_PROD_KEY[m] for m in (
    "N1", "T1", "D1", "Q1", "H1", "M1", "D2", "P1", "V1", "S1", "R1",
    "R2b", "R2g", "N2", "V2", "S2", "W1", "A1", "V3", "AD1")]


def spec_by_prod_key(prod_key):
    """生产键名 → 规格 dict(含 mining 代号)。未知键返回 None。"""
    mining_key = PROD_TO_MINING_KEY.get(prod_key)
    if mining_key is None:
        return None
    spec = dict(RULE_SPECS[mining_key])
    spec["mining_key"] = mining_key
    return spec


def rule_hit(prod_key, ctx):
    """判定某新键是否命中(=该笔被拦)。True=命中。

    ctx 字段(queries 端由 _ai_macro_hit_filters 组装; JS 端同构):
      sig     : str  信号类型(buy/buy_aux/buy_special/buy_backup...)
      mkt     : str|None  _mktD 域类短名(a/concept/industry/hk/global/hk_industry)
      tier    : str  A股类四档(hs300; 非A股为 "")
      date    : str  buy_date(YYYYMMDD, ≡signal_date) — 特征查询日
      smonth  : str  signal_date 月份两位("07") — R2g 用
      rating  : str  评级(high/mid/low)
      ts      : float|None  track_score(None → 999)
      feat_at : callable(name, date) -> float|None  特征查值(缺失返 None → 条件不成立)
    """
    spec = spec_by_prod_key(prod_key)
    if spec is None:
        return False
    cond = True
    # 特征条件(FR 工厂语义: 缺失值 → 整条不命中)
    if spec.get("feature"):
        v = (ctx.get("feat_at") or (lambda n, d: None))(spec["feature"], str(ctx.get("date") or ""))
        if v is None:
            return False
        th = spec["threshold"]
        if spec["direction"] == "low":
            cond = cond and v < th
        else:
            cond = cond and v > th
    if spec.get("sig") is not None:
        cond = cond and (ctx.get("sig") or "") == spec["sig"]
    if spec.get("tier") is not None:
        cond = cond and (ctx.get("tier") or "") == spec["tier"]
    if spec.get("mkt") is not None:
        cond = cond and (ctx.get("mkt") or "") == spec["mkt"]
    if spec.get("rating") is not None:
        cond = cond and (ctx.get("rating") or "") == spec["rating"]
        # R2g: ts 缺失视为 999 → <75 不成立(mine22: 空 ts 视为 999)
        ts = ctx.get("ts")
        ts_v = float(ts) if ts not in (None, "") else 999.0
        cond = cond and ts_v < spec["max_ts"]
        cond = cond and str(ctx.get("smonth") or "") in spec["months"]
    return bool(cond)


def load_features(path=None):
    """读取裁剪版特征 JSON(static-site/data/kelly_loss_features.json)。

    返回 dict{feat_name: {YYYYMMDD: value}}; 文件缺失/损坏返回 None(调用方降级: 特征类键不拦)。
    """
    if path is None:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "..", "static-site", "data", "kelly_loss_features.json")
    try:
        with open(path) as f:
            data = json.load(f)
        feats = data.get("features")
        return feats if isinstance(feats, dict) else None
    except (OSError, ValueError):
        return None


def make_feat_at(feats):
    """由特征序列构造 feat_at(name, date) 闭包(供 rule_hit ctx 用)。feats=None → 恒 None。"""
    if not feats:
        return lambda name, date: None
    def _at(name, date):
        series = feats.get(name)
        if not series:
            return None
        return series.get(str(date))
    return _at
