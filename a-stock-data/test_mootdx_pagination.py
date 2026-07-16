"""
补测：mootdx bars() 分页拉 10 年日线
通达信协议单次上限 800 行，需用 start 参数多次请求拼回 10 年。
"""
import socket
import time
from mootdx.quotes import Quotes

_TDX_SERVERS = [
    ('119.97.185.59', 7709), ('124.70.133.119', 7709), ('116.205.183.150', 7709),
    ('123.60.73.44', 7709),  ('116.205.163.254', 7709), ('121.36.225.169', 7709),
    ('123.60.70.228', 7709), ('124.71.9.153', 7709),    ('110.41.147.114', 7709),
    ('124.71.187.122', 7709),
]

def _probe(ip, port, timeout=2.0):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False

def tdx_client(market='std'):
    for ip, port in _TDX_SERVERS:
        if _probe(ip, port):
            return Quotes.factory(market=market, server=(ip, port))
    return Quotes.factory(market=market, bestip=True)


def fetch_full_klines(client, symbol, target_rows=2600, page_size=800):
    """
    分页拉取日线，每页 800 行，start 从 0 递增。
    mootdx bars(start=N) 中 N 是从最新往前的偏移。
    """
    import pandas as pd
    all_dfs = []
    start = 0
    total_elapsed = 0.0
    pages = 0
    while len(all_dfs) == 0 or (sum(len(d) for d in all_dfs) < target_rows):
        t0 = time.time()
        try:
            df = client.bars(symbol=symbol, frequency=9, offset=page_size, start=start)
        except Exception as e:
            print(f"    [page start={start}] 异常: {type(e).__name__}: {e}")
            break
        elapsed = time.time() - t0
        total_elapsed += elapsed
        pages += 1
        if df is None or len(df) == 0:
            print(f"    [page start={start}] 返回空，停止")
            break
        all_dfs.append(df)
        rows_this = len(df)
        earliest = str(df['datetime'].iloc[0]) if 'datetime' in df.columns else '?'
        latest = str(df['datetime'].iloc[-1]) if 'datetime' in df.columns else '?'
        print(f"    [page start={start}] {rows_this} 行, {earliest} ~ {latest}, {elapsed:.2f}s")
        if rows_this < page_size:
            # 不足一页 = 已到最早数据
            break
        start += rows_this
        if pages > 10:  # 安全上限
            print(f"    达到 10 页安全上限，停止")
            break

    if not all_dfs:
        return None, 0, 0.0
    merged = pd.concat(all_dfs, ignore_index=True)
    merged = merged.drop_duplicates(subset='datetime', keep='first').sort_values('datetime').reset_index(drop=True)
    return merged, pages, total_elapsed


def main():
    print("=" * 70)
    print("mootdx 分页拉 10 年日线 补测")
    print("=" * 70)

    client = tdx_client()
    print("[OK] 客户端已建立\n")

    # 测试 2 只
    for sym, name in [('600519', '贵州茅台'), ('000001', '平安银行')]:
        print(f"\n--- {sym} {name} 分页拉取 ---")
        df, pages, elapsed = fetch_full_klines(client, sym, target_rows=2600)
        if df is not None:
            print(f"  汇总: {len(df)} 行, {pages} 次请求, 总耗时 {elapsed:.2f}s")
            print(f"  日期范围: {df['datetime'].iloc[0]} ~ {df['datetime'].iloc[-1]}")
            # 估算年份跨度
            first_year = df['datetime'].iloc[0][:4]
            last_year = df['datetime'].iloc[-1][:4]
            print(f"  年份跨度: {first_year} ~ {last_year} (约 {int(last_year)-int(first_year)} 年)")
            # 单只 2600 行预估
            per_page = elapsed / pages
            print(f"  每页均耗时: {per_page:.2f}s")
            print(f"  5500 只 × 4 页/只 ÷ 10 并发 预估: {per_page * 4 * 5500 / 10 / 60:.1f} 分钟")


if __name__ == '__main__':
    main()
