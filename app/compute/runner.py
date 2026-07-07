"""计算编排：跑 §4 情绪分 → §6 跨市场分 → §7 买卖点 → 派生公式指标 → 买卖点 stats，落库。"""
from . import derived, sentiment, cross, signals, signal_stats


def run(verbose=True):
    s_score, s_comps = sentiment.compute()
    n_s = sentiment.store(s_score, s_comps)

    c_score = cross.compute()
    n_c = cross.store(c_score)

    sigs = signals.compute()
    n_sig = signals.store(sigs)

    d_out = derived.compute_derived_formulas()
    n_d = derived.store_derived(d_out)

    # step 10：买卖点 stats（forward 收益胜率/盈亏比/样本数，写 data/signal_stats.json）
    stats = signal_stats.compute()
    n_stats_bytes = signal_stats.store(stats)
    n_stats_iid = len([k for k in stats if not k.startswith("_")])

    if verbose:
        print(f"=== 计算完成: §4情绪分={n_s}天  §6跨市场={n_c}天  买卖点={n_sig}个  派生公式={n_d}行  买卖点stats={n_stats_iid}品种({n_stats_bytes}B) ===")
    return {"sentiment": n_s, "cross": n_c, "signals": n_sig, "derived": n_d, "stats_iid": n_stats_iid}


if __name__ == "__main__":
    run()
