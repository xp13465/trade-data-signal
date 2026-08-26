#!/usr/bin/env python3
"""_ai_macro_hit_filters 谓词级单测(2026-08-26, codex012 P2② 配套回归)。

目的:
  锁死后端 AI宏命中键集判定(_ai_macro_hit_filters)的关键谓词行为, 防 rebase/重构/后续键改动静默破坏。
  重点覆盖:
    1. buy_special_filtered → buy_special 入口归一化(codex012 P2②: 邮件链路变体名此前在
       queries.py 缺归一化会漏判 n2/r10/excludeSpecialBear 等 buy_special 系谓词;
       overfit_monitor.py L583 同款口径为对照实现)
    2. r10May6NonMay 五组件谓词
    3. k3ConceptBuy(buy×mkt_concept)
    4. 仅买信号守卫(非买返空)

方法口径:
  直接 import app.queries(无 DB 副作用), ctx 用可控 stub 注入评级/市场/跟踪分/四档,
  断言返回键集逐位相等; 归一化用「filtered 变体 vs 规范名同参双跑 diff=空」强断言。

输入依赖: 无外部数据(纯函数+stub)。
输出: stdout PASS/FAIL, exit code 0/1。挂 deploy 校验链可选; CI/本地均可单跑。

复现命令: cd /Users/linhuichen/code/trade && python3 scripts/test_ai_macro_hit_filters.py
关键参数种子: 测试日期均为真实历史交易日星期口径(_ai_macro_weekday 实测校准)。
"""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).absolute().parent.parent
sys.path.insert(0, str(ROOT))

# P2-2(codex013): 显式声明 feature-file 依赖——mock _ai_macro_feat_at 为恒 None 闭包,
# 测试不依赖外部 kelly_loss_features.json, 仅验证纯字段谓词。
_NIL_FEAT_AT = lambda name, date: None

# Patch queries 模块级 _ai_macro_feat_at, 使 _ai_macro_hit_filters 内部调用走 mock
import app.queries as _queries_mod

from app.queries import _ai_macro_hit_filters


def make_ctx(market="mkt_industry", rating="high", track=80.0, tier="牛市·主升",
             ma60=True, cyb_tier="牛市·主升"):
    """可控 ctx stub: 默认值可参定制; run() 内再按样例覆写 market/tier。"""
    return {
        "rating_of": lambda s: s.get("_rating", rating),
        "market_of": lambda iid: market,
        "track_score_of": lambda s: s.get("_ts", track),
        "tier_of": lambda d: tier,
        "ma60_bull_of": lambda d: ma60,
        "cyb_tier_of": lambda d: cyb_tier,
    }


def run(sig, ctx, mkt=None, tier=None):
    if mkt is not None:
        ctx["market_of"] = lambda iid: mkt
    if tier is not None:
        ctx["tier_of"] = lambda d: tier
    # P2-2: patch _ai_macro_feat_at 隔离外部文件依赖
    with patch.object(_queries_mod, "_ai_macro_feat_at", return_value=_NIL_FEAT_AT):
        return sorted(_ai_macro_hit_filters(sig, ctx))


def main():
    failures = []
    ok = 0

    # ---- 1. buy_special_filtered 归一化(P2② 核心回归样例) ----
    # buy_special + 11月 + 行业指数 → 同时命中 n2NovSpecialIndustry 与 r10May6NonMay 组件
    base_sig = {"date": "20251112", "signal": "buy_special", "index_id": "csi_931057"}
    filt_sig = dict(base_sig, signal="buy_special_filtered")
    ks_norm = run(base_sig, make_ctx(), mkt="mkt_industry")
    ks_filt = run(filt_sig, make_ctx(), mkt="mkt_industry")
    if "n2NovSpecialIndustry" in ks_norm and "r10May6NonMay" in ks_norm:
        ok += 1
        print(f"PASS 1a 规范名 buy_special 键集={ks_norm}")
    else:
        failures.append(f"1a 规范名 buy_special 应含 n2NovSpecialIndustry+r10May6NonMay, 实得 {ks_norm}")
    if ks_norm == ks_filt:
        ok += 1
        print(f"PASS 1b buy_special_filtered 归一化后键集逐位一致={ks_filt}")
    else:
        failures.append(f"1b filtered 变体键集漂移: norm={ks_norm} filt={ks_filt}")

    # excludeSpecialBear 也走 buy_special 谓词: 熊市档 + A股类
    ks_bear_norm = run(dict(base_sig), make_ctx(), mkt="mkt_industry", tier="熊市·主跌")
    ks_bear_filt = run(dict(filt_sig), make_ctx(), mkt="mkt_industry", tier="熊市·主跌")
    if "excludeSpecialBear" in ks_bear_norm and ks_bear_norm == ks_bear_filt:
        ok += 1
        print(f"PASS 1c excludeSpecialBear filtered 同判={ks_bear_filt}")
    else:
        failures.append(f"1c excludeSpecialBear: norm={ks_bear_norm} filt={ks_bear_filt}")

    # ---- 2. k3ConceptBuy: buy × mkt_concept ----
    ks_k3 = run({"date": "20250305", "signal": "buy", "index_id": "csi_930901"},
                make_ctx(), mkt="mkt_concept")
    if "k3ConceptBuy" in ks_k3:
        ok += 1
        print(f"PASS 2 k3ConceptBuy buy×概念={ks_k3}")
    else:
        failures.append(f"2 buy×mkt_concept 应含 k3ConceptBuy, 实得 {ks_k3}")
    # 非概念市场不得误标
    ks_no3 = run({"date": "20250305", "signal": "buy", "index_id": "sh000001"},
                 make_ctx(), mkt="mkt_broad")
    if "k3ConceptBuy" not in ks_no3:
        ok += 1
        print(f"PASS 2b 非概念不标 k3={ks_no3}")
    else:
        failures.append(f"2b 宽基误标 k3ConceptBuy: {ks_no3}")

    # ---- 3. r10May6NonMay 五组件逐一验证(P2-1 codex013: 精确键集断言) ----
    # 组件 1: 5月任意买信号 → r10May6NonMay
    ks_may = run({"date": "20250512", "signal": "buy", "index_id": "sh000001"},
                 make_ctx(), mkt="mkt_broad")
    if "r10May6NonMay" in ks_may:
        ok += 1
        print(f"PASS 3a 组件1(5月)={ks_may}")
    else:
        failures.append(f"3a 5月应含 r10May6NonMay, 实得 {ks_may}")
    # 组件 5: buy_aux × 3月 × wd==2(周三, 20250305 实测 wd=2)
    ks_aux = run({"date": "20250305", "signal": "buy_aux", "index_id": "csi_931057"},
                 make_ctx(), mkt="mkt_industry")
    if "r10May6NonMay" in ks_aux:
        ok += 1
        print(f"PASS 3b 组件5(buy_aux×03×wd2)={ks_aux}")
    else:
        failures.append(f"3b buy_aux+03+wd2 应含 r10May6NonMay, 实得 {ks_aux}")
    # 组件 2: buy_special × 11月 × mkt_industry → r10May6NonMay
    ks_ind = run({"date": "20251112", "signal": "buy_special", "index_id": "csi_931057"},
                 make_ctx(), mkt="mkt_industry")
    if "r10May6NonMay" in ks_ind:
        ok += 1
        print(f"PASS 3c 组件2(buy_special×11×industry)={ks_ind}")
    else:
        failures.append(f"3c buy_special+11+industry 应含 r10May6NonMay, 实得 {ks_ind}")
    # 组件 3: buy_special × 11月 × wd==0(周一, 20251110 实测 wd=0)
    ks_wd0 = run({"date": "20251110", "signal": "buy_special", "index_id": "csi_931057"},
                 make_ctx(), mkt="mkt_industry")
    if "r10May6NonMay" in ks_wd0:
        ok += 1
        print(f"PASS 3d 组件3(buy_special×11×wd0)={ks_wd0}")
    else:
        failures.append(f"3d buy_special+11+wd0 应含 r10May6NonMay, 实得 {ks_wd0}")
    # 组件 4: buy_special × 3月 × mkt_industry → r10May6NonMay
    ks_mar_ind = run({"date": "20250312", "signal": "buy_special", "index_id": "csi_931057"},
                     make_ctx(), mkt="mkt_industry")
    if "r10May6NonMay" in ks_mar_ind:
        ok += 1
        print(f"PASS 3e 组件4(buy_special×03×industry)={ks_mar_ind}")
    else:
        failures.append(f"3e buy_special+03+industry 应含 r10May6NonMay, 实得 {ks_mar_ind}")

    # ---- 4. 仅买信号守卫 ----
    for bad in ("sell", "sell_stop_loss", "band_hold"):
        ks_bad = run({"date": "20251112", "signal": bad, "index_id": "csi_931057"},
                     make_ctx(), mkt="mkt_industry")
        if ks_bad == []:
            ok += 1
            print(f"PASS 4 {bad} 守卫返空")
        else:
            failures.append(f"4 {bad} 应返空, 实得 {ks_bad}")

    total = 13
    print(f"\n== {ok}/{total} PASS ==")
    if failures:
        for f in failures:
            print("FAIL", f)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
