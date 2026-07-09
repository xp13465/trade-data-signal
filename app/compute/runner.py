"""计算编排：跑 §4 情绪分 → §6 跨市场分 → §7 买卖点 → 派生公式指标 → AD Line → 量比 → 买卖点 stats，落库。"""
from . import ad_line, derived, sentiment, cross, signals, signal_stats, volume_ratio, position, market_summary, fear_greed, new_high_low, ma_alignment, rotation


def run(verbose=True):
    s_score, s_comps = sentiment.compute()
    n_s = sentiment.store(s_score, s_comps)

    # 六个指数情绪分
    index_ids = ["sz50", "hs300", "csi500", "csi1000", "cyb", "kc50"]
    n_idx = {}
    for idx_id in index_ids:
        idx_score, idx_comps = sentiment.compute_index_sentiment(idx_id)
        score_id = f"sentiment_{idx_id}"
        n_idx[idx_id] = sentiment.store(idx_score, idx_comps, score_id=score_id)

    c_score = cross.compute()
    n_c = cross.store(c_score)

    sigs = signals.compute()
    n_sig = signals.store(sigs)

    d_out = derived.compute_derived_formulas()
    n_d = derived.store_derived(d_out)

    ad_out = ad_line.compute_ad_line()
    n_ad = ad_line.store_ad_line(ad_out)

    vr_n = volume_ratio.compute_volume_ratio()

    # step 9：大盘位置感（8 指数 × 3 窗口分位）
    pos_list = position.compute_position()
    n_pos = position.store_position(pos_list)

    # step 11：恐贪指数（等权平均 8 个情绪分）
    n_fg = fear_greed.compute_fear_greed()

    # step 12：买卖点 stats（forward 收益胜率/盈亏比/样本数，写 data/signal_stats.json）
    stats = signal_stats.compute()
    n_stats_bytes = signal_stats.store(stats)
    n_stats_iid = len([k for k in stats if not k.startswith("_")])

    # step 13：新高新低家数（8 指数 52周/20日 NH-NL）
    nhl_out = new_high_low.compute_new_highs_lows()
    n_nhl = new_high_low.store_new_highs_lows(nhl_out)

    # step 14：均线排列状态（8 指数 MA5/MA10/MA20/MA60）
    ma_out = ma_alignment.compute_ma_alignment()
    n_ma = ma_alignment.store_ma_alignment(ma_out)

    # step 15：板块轮动速度（SW 行业 + 概念板块领涨变化频率）
    rot_data = rotation.compute_rotation()
    n_rot = rotation.store_rotation(rot_data)

    if verbose:
        idx_summary = "  ".join(f"{k}={v}天" for k, v in n_idx.items())
        print(f"=== 计算完成: §4情绪分={n_s}天  {idx_summary}  §6跨市场={n_c}天  买卖点={n_sig}个  派生公式={n_d}行  AD Line={n_ad}行  量比={vr_n}天  位置感={n_pos}行  恐贪指数={n_fg}天  买卖点stats={n_stats_iid}品种({n_stats_bytes}B)  新高新低={n_nhl}行  均线排列={n_ma}行  板块轮动={n_rot}行 ===")
    return {"sentiment": n_s, "cross": n_c, "signals": n_sig, "derived": n_d, "ad_line": n_ad, "volume_ratio": vr_n, "position": n_pos, "fear_greed": n_fg, "stats_iid": n_stats_iid, "index_sentiment": n_idx, "new_high_low": n_nhl, "ma_alignment": n_ma, "rotation": n_rot}


if __name__ == "__main__":
    run()
