# -*- coding: utf-8 -*-
"""AI降亏特征数据通道·生产版生成脚本(T1 2026-08-23)。

【目的】为 15 条特征依赖型降亏新键(loss_rules.py RULE_SPECS 中含 feature 的键)生成
    裁剪版全史特征 JSON, 供 ①前端 lab.js/app.js 重放谓词查值(fetch data/kelly_loss_features.json)
    ②后端 queries.py ai_macro 注入查值(loss_rules.load_features)。
    只保留谓词需要的 12 个特征字段(mine10_features.json 全量 25 特征裁剪), 控制体积。
【输入】① sentiment.db: daily_metric(metric_id 见 METRIC_OF)/score_daily(score_id 见 SCORE_OF)
          —— 优先读主库 trade-data/data/sentiment.db(launchd 实时写), 缺失回退 trade/data 滞后镜像
       ② static-site/data/index/hs300-all.json(ohlc.close 序列, 价格衍生族)
【输出】static-site/data/kelly_loss_features.json:
          { meta: {generated_at, source, thresholds(QTH快照), rules(21键规格+生产键名)},
            features: {12特征名: {YYYYMMDD: value}} }
        上线渠道(static-site/data/ 自 2026-08-08 起 .gitignore `static-site/data/*` 全量排除,
          本体不入 git): ①R2 = REPO=<仓库根> python3 scripts/upload_r2.py upload-data-files
          kelly_loss_features.json —— R2 data/ 前缀=唯一数据来源(前端 ./data/ 相对路径经
          worker rewrite 读 R2), 上传后自动 purge CF 边缘缓存; ②bash scripts/deploy.sh 推
          代码/min(git 只带非 ignore 文件)。upload_r2 需显式 REPO(#75 缺省分级闸): 本生成器
          按 __file__ 写 trade 树, 故传 REPO=<trade 仓库根>。
【口径】特征算法与挖掘版 mine10_features.py 逐字一致(无前视: 当日值用截至当日收盘数据):
    north_d20=a_fund_north 年内累计的 20 日差 / turn_pct=turn_mean 滚动3年分位 / div_yield=a_div_yield /
    qvix_pct=qvix100 滚动3年分位 / h_volchg=hs300 (5日std/20日std-1)*100(均年化) /
    margin_chg20=a_fund_margin 20日变化率% / div_pct=div_yield 滚动3年分位 / h_vol20=hs300 20日年化波动% /
    sent_a=score_daily a_sentiment / vol_ratio_all=a_volume_ratio / sent_hs300=score_daily sentiment_hs300 /
    adline_gap=(a_ad_line-a_ad_line_ma20)/|a_ad_line_ma20|
【阈值】分位阈值 = 硬编码快照(scripts/loss_rules.py QTH, 源=mine10_features.json 2026-08-22 版),
    本脚本不重算阈值, 只把 QTH/RULE_SPECS 写进 meta 供前端读同一份(§23.6 口径一致性)。
【复现】python3 scripts/gen_kelly_loss_features.py
    校验: python3 scripts/check_loss_rules_vs_mining.py(重叠日期 vs mine10_features.json 逐位对比)
"""
import json
import math
import os
import sqlite3
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "static-site", "data", "kelly_loss_features.json")

import sys
sys.path.insert(0, HERE)
from loss_rules import QTH, RULE_SPECS, MINING_TO_PROD_KEY, H_VOL20_V2_CONST  # noqa: E402

METRIC_OF = {
    "div_yield": "a_div_yield",
    "vol_ratio_all": "a_volume_ratio",
    "turn_mean": "a_turnover_mean",      # 衍生 turn_pct 的源
    "fund_north_cum": "a_fund_north",    # 衍生 north_d20 的源
    "margin_lvl": "a_fund_margin",       # 衍生 margin_chg20 的源
    "ad_line": "a_ad_line",              # 衍生 adline_gap 的源
    "ad_line_ma20": "a_ad_line_ma20",
    "qvix100": "a_qvix_1000",            # 衍生 qvix_pct 的源
}
SCORE_OF = {
    "sent_a": "a_sentiment",
    "sent_hs300": "sentiment_hs300",
}
ROLL_WIN = 756  # 滚动3年分位窗口(~756交易日), 与 mine10_features.py 一致


def _db_path():
    """主库优先(trade-data/data/sentiment.db, launchd 实时写), 回退 trade/data 滞后镜像。

    候选顺序: ①env LOSS_FEAT_DB 显式指定(worktree 隔离自测用, 如
    LOSS_FEAT_DB=/Users/linhuichen/code/trade-data/data/sentiment.db)
    ② dirname(ROOT)/trade-data(生产布局, 与 signal_kelly_backtest._get_etf_db_path 同款)
    ③ ROOT/data 滞后镜像(deploy rsync 同步后与主库一致, 仅回退)。"""
    cand = []
    if os.environ.get("LOSS_FEAT_DB"):
        cand.append(os.environ["LOSS_FEAT_DB"])
    cand.append(os.path.abspath(os.path.join(os.path.dirname(ROOT), "trade-data", "data", "sentiment.db")))
    cand.append(os.path.join(ROOT, "data", "sentiment.db"))
    for p in cand:
        if os.path.exists(p):
            return p
    raise SystemExit("sentiment.db not found in %s" % cand)


def main():
    con = sqlite3.connect(_db_path())
    cur = con.cursor()
    feats = {}

    def add_metric(name, metric_id):
        cur.execute("SELECT date, value FROM daily_metric WHERE metric_id=? AND value IS NOT NULL ORDER BY date", (metric_id,))
        feats[name] = {d: v for d, v in cur.fetchall()}

    def add_score(name, score_id):
        cur.execute("SELECT date, value FROM score_daily WHERE score_id=? AND value IS NOT NULL ORDER BY date", (score_id,))
        feats[name] = {d: v for d, v in cur.fetchall()}

    for name, mid in METRIC_OF.items():
        add_metric(name, mid)
    for name, sid in SCORE_OF.items():
        add_score(name, sid)

    # ---- 衍生特征(逐字对齐 mine10_features.py)----
    # AD 线距其 MA20 标准化差
    g = {}
    for d, v in feats["ad_line"].items():
        m = feats["ad_line_ma20"].get(d)
        if m not in (None, 0):
            g[d] = (v - m) / abs(m)
    feats["adline_gap"] = g

    # 北向:年内累计 -> 20日差(近20日净流入, 亿)
    ds = sorted(feats["fund_north_cum"])
    g = {}
    for i, d in enumerate(ds):
        if i >= 20:
            g[d] = feats["fund_north_cum"][d] - feats["fund_north_cum"][ds[i - 20]]
    feats["north_d20"] = g

    # 两融 20日变化率%
    ds = sorted(feats["margin_lvl"])
    g = {}
    for i, d in enumerate(ds):
        if i >= 20 and feats["margin_lvl"][ds[i - 20]]:
            g[d] = (feats["margin_lvl"][d] / feats["margin_lvl"][ds[i - 20]] - 1) * 100
    feats["margin_chg20"] = g

    # 滚动3年分位(div_yield/turn_mean/qvix100): 当前值在过去~756交易日分位 0-100
    def rolling_pctile(name, win=ROLL_WIN):
        src = feats[name]
        ds_ = sorted(src)
        import bisect
        window_vals = []
        out = {}
        for d in ds_:
            window_vals.append(src[d])
            if len(window_vals) > win:
                window_vals.pop(0)
            s = sorted(window_vals)
            rank = bisect.bisect_left(s, src[d])
            out[d] = rank / max(len(s) - 1, 1) * 100
        return out

    feats["div_pct"] = rolling_pctile("div_yield")
    feats["turn_pct"] = rolling_pctile("turn_mean")
    feats["qvix_pct"] = rolling_pctile("qvix100")

    # ---- hs300 价格衍生 ----
    # 路径: env HS300_JSON 显式指定(worktree 隔离自测用) → ROOT/static-site/data/index/(生产, gitignore 本地保留)
    hs_path = os.environ.get("HS300_JSON") or os.path.join(ROOT, "static-site", "data", "index", "hs300-all.json")
    if not os.path.exists(hs_path):
        hs_path = "/Users/linhuichen/code/trade/static-site/data/index/hs300-all.json"
    with open(hs_path) as f:
        ohlc = json.load(f)["ohlc"]
    dates = [o["date"] for o in ohlc]
    closes = [o["close"] for o in ohlc]
    n = len(closes)
    f_vol20, f_volchg = {}, {}
    for i in range(n):
        c = closes[i]
        if i >= 20:
            rets = [(closes[j] / closes[j - 1] - 1) for j in range(i - 19, i + 1)]
            mu = sum(rets) / len(rets)
            var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
            f_vol20[dates[i]] = math.sqrt(var) * math.sqrt(252) * 100
        if i >= 24:
            def _std(a, b):
                rets = [(closes[j] / closes[j - 1] - 1) for j in range(a, b + 1)]
                mu = sum(rets) / len(rets)
                return math.sqrt(sum((r - mu) ** 2 for r in rets) / max(len(rets) - 1, 1))
            s5, s20 = _std(i - 4, i), _std(i - 19, i)
            if s20 > 1e-12:
                f_volchg[dates[i]] = (s5 / s20 - 1) * 100  # >0 升波 <0 降波
    feats["h_vol20"] = f_vol20
    feats["h_volchg"] = f_volchg

    # ---- 裁剪: 只留谓词需要的 12 特征 ----
    KEEP = ["north_d20", "turn_pct", "div_yield", "qvix_pct", "h_volchg", "margin_chg20",
            "div_pct", "h_vol20", "sent_a", "vol_ratio_all", "sent_hs300", "adline_gap"]
    out_feats = {k: feats[k] for k in KEEP}

    # ---- meta: 规格与阈值快照单源写出(JS 读同一份)----
    rules_meta = []
    for mining_key, spec in RULE_SPECS.items():
        r = {"key": MINING_TO_PROD_KEY[mining_key], "mining": mining_key, "group": spec.get("group"),
             "desc": spec.get("desc"), "vs9": spec.get("vs9")}
        for fld in ("feature", "direction", "threshold", "sig", "tier", "track_tier", "mkt", "rating", "max_ts", "months", "date_field"):
            if fld in spec:
                r[fld] = spec[fld]
        rules_meta.append(r)

    doc = {
        "meta": {
            "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "sentiment.db daily_metric/score_daily + static-site/data/index/hs300-all.json "
                      "(算法=mine10_features.py 逐字移植, 无前视)",
            "threshold_note": "分位阈值=硬编码快照(scripts/loss_rules.py QTH, 源=mine10_features.json 2026-08-22 版"
                              "全史分位), 不随每日数据滚动重算; 重算快照需发版(§23.6 口径一致性)",
            "v2_const": H_VOL20_V2_CONST,
            "thresholds": QTH,
            "rules": rules_meta,
        },
        "features": out_feats,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(OUT)
    print("written %s (%.1f KB)" % (OUT, size / 1024))
    print("%-14s %6s %10s %10s" % ("feat", "days", "first", "last"))
    for k in KEEP:
        ks = sorted(out_feats[k])
        print("%-14s %6d %10s %10s" % (k, len(ks), ks[0], ks[-1]))


if __name__ == "__main__":
    main()
