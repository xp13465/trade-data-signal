# -*- coding: utf-8 -*-
"""AI降亏 20 新键·三层一致性校验(T1 2026-08-23, §23.6 口径一致性)。

【目的】断言生产实现与挖掘权威版逐位一致, 防移植走样:
    层1 特征: gen_kelly_loss_features.py 产出 vs 挖掘用 mine10_features.json 重叠日期逐位相等
    层2 谓词: scripts/loss_rules.py rule_hit vs 挖掘 mine21_bigtour.build_rules / mine22_joint.build_r2
              在 signal_kelly_trades.json mode A 全部行上命中集合全等
    层3 阈值: loss_rules.QTH 重算(从 mine10_features.json) vs 固化快照逐位相等
【输入】static-site/data/kelly_loss_features.json(先生成) + 挖掘目录 mine10_features.json +
        static-site/data/signal_kelly_trades.json + 挖掘脚本 sim_core/mine21/mine22
【输出】终端逐层 PASS/FAIL; 任一层 FAIL exit 1
【复现】python3 scripts/gen_kelly_loss_features.py && python3 scripts/check_loss_rules_vs_mining.py
    (worktree 隔离时先 LOSS_FEAT_DB=... HS300_JSON=... 跑生成, 本脚本读 worktree 内产物)
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
MINING = os.environ.get("MINING_DIR") or os.path.join(
    ROOT, "docs", "kelly", "analysis", "scripts", "sim_window_loss_mining_20260822")

sys.path.insert(0, HERE)
from loss_rules import QTH, RULE_SPECS, MINING_TO_PROD_KEY, make_feat_at, rule_hit  # noqa: E402

MINING_KEY_ORDER = ["N1", "T1", "D1", "Q1", "H1", "M1", "D2", "P1", "V1", "S1", "R1",
                    "R2b", "R2g", "N2", "V2", "S2", "W1", "A1", "V3", "AD1"]


def _prepare_rows_legacy_compat(R, trades_path):
    """unique 三表时先写还原旧结构临时文件再走 R.prepare_rows; 旧 quadrants 文件原样直走。"""
    with open(trades_path) as f:
        raw = json.load(f)
    if isinstance(raw, dict) and "base" in raw and "variants" in raw:
        legacy = _restore_unique_to_legacy(raw)
        fd, tmp = tempfile.mkstemp(suffix=".json", prefix="trades_legacy_")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(legacy, f)
            return R.prepare_rows(tmp)
        finally:
            os.unlink(tmp)
    return R.prepare_rows(trades_path)

# L42 数据瘦身 Phase D(2026-09-21): 兼容「基笔唯一化三表」(signal_kelly_trades_unique.json)。
# 27 列序单一事实源 = scripts/signal_kelly_backtest.py TRADE_FIELDS(L173); 三表还原为旧
# quadrants 形态后写临时文件, 复用 R.prepare_rows(sim_core.load) 零改动消费, 不产第二份实现。
TRADE_FIELDS_27 = ["signal_date", "index_id", "signal", "buy_date", "sell_date", "etf_code", "etf_name",
                   "track_tier", "track_score", "match_method", "track_low_confidence", "buy_price",
                   "sell_price", "shares", "profit", "return_pct", "hold_days", "sell_reason",
                   "current_price", "real_buy_price", "real_buy_date", "real_current_price",
                   "market_state", "market_tier", "market_tier_all", "market_tier_cyb", "rating"]


def _restore_unique_to_legacy(uniq):
    """unique 三表 → {fields: TRADE_FIELDS_27, quadrants:{qk:{mode:[27列行]}}}。
    规则: base[i]=19共享列+4归属枚举码(qk_groups 键序); variants[mode][i]=8卖出列;
    variants[mode][i]==None = R8 哨兵该 mode 无有效回测, 跳过。"""
    share, varf = uniq["fields"], uniq["variant_fields"]
    if len(share) + len(varf) != len(TRADE_FIELDS_27):
        raise ValueError("unique 列数漂移: fields(%d)+variant_fields(%d) != 27" % (len(share), len(varf)))
    share_idx = {f: i for i, f in enumerate(share)}
    var_idx = {f: i for i, f in enumerate(varf)}
    col_build = []
    for f in TRADE_FIELDS_27:
        if f in share_idx:
            col_build.append((0, share_idx[f]))
        elif f in var_idx:
            col_build.append((1, var_idx[f]))
        else:
            raise ValueError("TRADE_FIELDS 字段 %s 不在 unique schema" % f)
    group_keys = list(uniq.get("qk_groups") or {})
    n_share = len(share)
    qk_list = []
    for g in group_keys:
        for qk in (uniq["qk_groups"].get(g) or []):
            qk_list.append(qk)
    modes = list(uniq.get("variants") or {})
    quads = {qk: {m: [] for m in modes} for qk in qk_list}
    base = uniq.get("base") or []
    for i, b in enumerate(base):
        if not isinstance(b, list) or len(b) < n_share:
            continue
        if len(b) != n_share + len(group_keys):
            raise ValueError("unique base 行%d 走样: %d 列 != share(%d)+归属(%d)" % (i, len(b), n_share, len(group_keys)))
        for gi, g in enumerate(group_keys):
            code = b[n_share + gi]
            if not isinstance(code, int) or code < 0:
                continue
            group = uniq["qk_groups"].get(g) or []
            if code >= len(group):
                continue
            qk = group[code]
            for m in modes:
                v = uniq["variants"][m][i]
                if v is None:
                    continue
                if not isinstance(v, list) or len(v) != len(varf):
                    raise ValueError("unique variants[%s][%d] 走样: %d 列 != %d" % (m, i, len(v), len(varf)))
                quads[qk][m].append([b[idx] if src == 0 else v[idx] for src, idx in col_build])
    return {"fields": TRADE_FIELDS_27[:], "quadrants": quads}


def layer3_thresholds():
    """QTH 快照 vs 从 mine10_features.json 重算, 逐位相等。"""
    feats = json.load(open(os.path.join(MINING, "data", "mine10_features.json")))

    def qth(fname, p):
        vals = sorted(v for v in feats[fname].values() if v is not None)
        return vals[min(int(p * (len(vals) - 1)), len(vals) - 1)]

    expect = {
        "north_d20@0.30": qth("north_d20", 0.30),
        "turn_pct@0.30": qth("turn_pct", 0.30),
        "div_yield@0.50": qth("div_yield", 0.50),
        "div_yield@0.70": qth("div_yield", 0.70),
        "qvix_pct@0.10": qth("qvix_pct", 0.10),
        "h_volchg@0.30": qth("h_volchg", 0.30),
        "margin_chg20@0.70": qth("margin_chg20", 0.70),
        "div_pct@0.30": qth("div_pct", 0.30),
        "h_vol20@0.90": qth("h_vol20", 0.90),
        "h_vol20@0.10": qth("h_vol20", 0.10),
        "sent_a@0.20": qth("sent_a", 0.20),
        "vol_ratio_all@0.10": qth("vol_ratio_all", 0.10),
        "sent_hs300@0.20": qth("sent_hs300", 0.20),
        "adline_gap@0.70": qth("adline_gap", 0.70),
    }
    bad = {k: (QTH[k], v) for k, v in expect.items() if QTH[k] != v}
    print("层3 阈值快照: %s (%d 项, 不符 %d)" % ("PASS" if not bad else "FAIL", len(expect), len(bad)))
    for k, (got, exp) in bad.items():
        print("   %s 快照=%r 重算=%r" % (k, got, exp))
    return not bad


def layer1_features():
    """生产特征 JSON vs 挖掘 mine10_features.json, 12 特征重叠日期值逐位相等。"""
    prod = json.load(open(os.path.join(ROOT, "static-site", "data", "kelly_loss_features.json")))["features"]
    mining = json.load(open(os.path.join(MINING, "data", "mine10_features.json")))
    bad_total = 0
    for name in prod:
        p, m = prod[name], mining.get(name)
        if m is None:
            print("   %s: 挖掘版无此特征(裁剪新增?) SKIP" % name)
            continue
        common = set(p) & set(m)
        diff = [d for d in common if p[d] != m[d]]
        only_p = len(set(p) - set(m))
        status = "PASS" if not diff else "FAIL"
        if diff:
            bad_total += len(diff)
        print("   %-14s 重叠%d日 不等%d 只生产有%d %s" % (name, len(common), len(diff), only_p, status))
    print("层1 特征逐位: %s" % ("PASS" if not bad_total else "FAIL(%d)" % bad_total))
    return not bad_total


def layer2_predicates():
    """loss_rules.rule_hit vs 挖掘规则工厂, mode A 全行命中集合全等。"""
    sys.path.insert(0, MINING)
    import r2_common as R  # noqa: E402
    from mine21_bigtour import build_rules  # noqa: E402
    from mine22_joint import build_r2  # noqa: E402

    feats_mining = json.load(open(os.path.join(MINING, "data", "mine10_features.json")))
    # trades 路径: env TRADES_JSON 显式指定(worktree 隔离) → ROOT/static-site/data/(生产)
    trades_path = os.environ.get("TRADES_JSON") or os.path.join(ROOT, "static-site", "data", "signal_kelly_trades.json")
    if not os.path.exists(trades_path):
        trades_path = "/Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json"
    # Phase D: unique 三表还原为旧 quadrants 形态临时文件, R.prepare_rows 零改动消费
    rows, fIdx = _prepare_rows_legacy_compat(R, trades_path)
    mD = len(fIdx)

    mining_rules = build_rules(feats_mining, fIdx)
    mining_rules.update(build_r2(fIdx))

    prod_feats = json.load(open(os.path.join(ROOT, "static-site", "data", "kelly_loss_features.json")))["features"]
    feat_at = make_feat_at(prod_feats)

    def prod_ctx(t):
        return dict(
            sig=t[fIdx["signal"]] or "",
            mkt=t[mD] or "",
            tier=t[fIdx["market_tier"]] or "",
            date=t[fIdx["buy_date"]] or "",
            smonth=str(t[fIdx["signal_date"]] or "")[4:6],
            rating=t[fIdx["rating"]] or "",
            ts=t[fIdx["track_score"]],
            feat_at=feat_at,
        )

    all_ok = True
    for mk in MINING_KEY_ORDER:
        pk = MINING_TO_PROD_KEY[mk]
        fn = mining_rules[mk]
        diff = []
        for t in rows:
            a = bool(fn(t))
            b = rule_hit(pk, prod_ctx(t))
            if a != b:
                diff.append((str(t[fIdx["signal_date"]]), t[fIdx["signal"]], a, b))
        ok = not diff
        all_ok = all_ok and ok
        print("   %-4s->%-20s 行数%d 不一致%d %s" % (mk, pk, len(rows), len(diff), "PASS" if ok else "FAIL"))
        for d in diff[:3]:
            print("      样本: %s %s 挖掘=%s 生产=%s" % d)
    print("层2 谓词全等: %s" % ("PASS" if all_ok else "FAIL"))
    return all_ok


def main():
    ok3 = layer3_thresholds()
    ok1 = layer1_features()
    ok2 = layer2_predicates()
    print("总结: 层1=%s 层2=%s 层3=%s" % ("PASS" if ok1 else "FAIL", "PASS" if ok2 else "FAIL", "PASS" if ok3 else "FAIL"))
    sys.exit(0 if (ok1 and ok2 and ok3) else 1)


if __name__ == "__main__":
    main()
