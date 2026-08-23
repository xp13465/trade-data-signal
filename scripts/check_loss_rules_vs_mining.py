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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
MINING = os.environ.get("MINING_DIR") or os.path.join(
    ROOT, "docs", "kelly", "analysis", "scripts", "sim_window_loss_mining_20260822")

sys.path.insert(0, HERE)
from loss_rules import QTH, RULE_SPECS, MINING_TO_PROD_KEY, make_feat_at, rule_hit  # noqa: E402

MINING_KEY_ORDER = ["N1", "T1", "D1", "Q1", "H1", "M1", "D2", "P1", "V1", "S1", "R1",
                    "R2b", "R2g", "N2", "V2", "S2", "W1", "A1", "V3", "AD1"]


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
    rows, fIdx = R.prepare_rows(trades_path)  # mode A + 8键基座(与生产 trades 同源)
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
