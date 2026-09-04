"""只读探针: 定位信号凯利回测 9/1-9/4 信号断链点。复用 signal_kelly_backtest 加载函数, 不写业务文件。"""
import sys, os
sys.path.insert(0, '/Users/linhuichen/code/trade/scripts')
sys.path.insert(0, '/Users/linhuichen/code/trade')
import signal_kelly_backtest as skb

# 1. 信号源(sentiment.db signal_daily)
conn = skb.get_conn()
buy_rows = conn.execute(
    f"SELECT date, index_id, signal FROM signal_daily "
    f"WHERE signal IN ({','.join('?' * len(skb.BUY_SIGNALS))}) AND date >= '20260901' ORDER BY date",
    skb.BUY_SIGNALS,
).fetchall()
print(f"9月 buy 系信号共 {len(buy_rows)} 条")
for r in buy_rows:
    print("  信号:", r)

# 2. 各信号 resolve ETF + score + 回测A模式
signal_stats = skb._load_signal_stats()
etf_map = skb._load_board_etf_map()
best_etf = skb._build_best_etf(etf_map)
etf_freeze = skb._load_etf_freeze()
market_map = skb._load_market_map()
market_state, market_dates = skb._load_market_state(conn)
market_tiers = skb._load_market_tiers(conn)
cyb_tiers = skb._load_market_tiers(conn, index_id='cyb')
# 价格加载(只用9月相关 ETF)
needed = set()
for _date, iid, _sig in buy_rows:
    be, _fr = skb._resolve_etf(_date, iid, _sig, best_etf, etf_freeze)
    if be:
        needed.add(be["code"])
print(f"9月信号涉及 {len(needed)} 只 ETF")
price_map, open_map, close_map, sorted_dates_map = skb._batch_load_etf_prices(needed)
# 各 ETF 价格日期范围
for code in needed:
    ds = sorted_dates_map.get(code, [])
    tail = ds[-5:] if ds else []
    print(f"  ETF {code}: {len(ds)} 个交易日, 最近5日={tail}")

today_str = max((ds[-1] for ds in sorted_dates_map.values() if ds), default=None)
print(f"全局最新数据日: {today_str}")

# 3. 逐信号跑 A 模式, 观察断链
for date, iid, sig in buy_rows:
    be, be_frozen = skb._resolve_etf(date, iid, sig, best_etf, etf_freeze)
    if not be:
        print(f"[{date} {iid} {sig}] → 无ETF映射(断链1)"); continue
    stats_entry = signal_stats.get(iid, {}).get(sig, {})
    score_10d = stats_entry.get("10d", {}).get("score") if isinstance(stats_entry, dict) else None
    if score_10d is None:
        print(f"[{date} {iid} {sig}] → 无评级score(断链2), ETF={be['code']} {be.get('track_tier')}"); continue
    prices = price_map.get(be["code"], {})
    sdates = sorted_dates_map.get(be["code"], [])
    # 检查信号日有没有价格
    if date not in prices:
        # 分原因: 是 accum_nav 空(表里有行但 nav null) 还是根本没行
        have_close = close_map.get(be["code"], {}).get(date)
        print(f"[{date} {iid} {sig}] → A模式: 信号日无accum_nav(断链3), ETF={be['code']}, "
              f"该日close={'有' if have_close else '无'}, sorted_dates最近={sdates[-3:] if sdates else '空'}")
        continue
    # 有价格, 跑A模式
    res = skb._backtest_one(date, prices, sdates, be["code"], be["name"], skb.SELL_MODES["A"]["stop_profit"],
                            iid, sig, be.get("track_tier"), be.get("track_score"),
                            be.get("match_method"), be.get("track_low_confidence"),
                            today=today_str, hold_days=skb.SELL_MODES["A"]["hold_days"],
                            market_state=skb._is_market_bull(date, market_state, market_dates),
                            rating=('high' if score_10d>=skb.RATING_HIGH else 'mid' if score_10d>=skb.RATING_MID else 'low'),
                            sell_mode="A", sell_signals=[], market_tier="", market_tier_all="",
                            market_tier_cyb="", open_map=open_map, close_map=close_map)
    if res:
        print(f"[{date} {iid} {sig}] → A模式 成交! buy_price={res['buy_price']:.4f} sell_date={res['sell_date']} reason={res['sell_reason']}")
    else:
        # 详细看为何None
        sig_close = close_map.get(be["code"], {}).get(date) if close_map else None
        nxt = skb._next_trading_day(date, sdates)
        nxt_open = open_map.get(be["code"], {}).get(nxt) if (open_map and nxt) else None
        print(f"[{date} {iid} {sig}] → A模式 返回None(断链4): sig_close={sig_close}, 次日={nxt} 次日open={nxt_open}, "
              f"signal日nav={prices.get(date)}")
conn.close()
