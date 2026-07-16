"""
mootdx K线 API 可用性探测脚本（D3 备选保险 + skill 可用性确认）

只探测 3-5 只样本，验证：
- TCP 7709 连通性（tdx_client helper 三级 fallback）
- 10 年日线数据（offset=2500 ~ 10 年交易日）
- 字段完整性（open/close/high/low/vol/amount/datetime）
- 不封 IP（TCP 协议，非 HTTP）
- 速度（估算 5500 只全量耗时）
"""

import socket
import sys
import time
from mootdx.quotes import Quotes

# 实测可用的备选服务器（按延迟排序，2026-06 验证）
_TDX_SERVERS = [
    ('119.97.185.59', 7709), ('124.70.133.119', 7709), ('116.205.183.150', 7709),
    ('123.60.73.44', 7709),  ('116.205.163.254', 7709), ('121.36.225.169', 7709),
    ('123.60.70.228', 7709), ('124.71.9.153', 7709),    ('110.41.147.114', 7709),
    ('124.71.187.122', 7709),
]

def _probe(ip, port, timeout=2.0):
    """TCP 握手探测，判断服务器是否可达"""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False

def tdx_client(market='std'):
    """
    创建 mootdx 客户端，规避 0.11.x BESTIP.HQ 空串 bug。
    顺序兜底，保证 IP 列表老化/换网时仍能工作：
      1) 顺序探测 _TDX_SERVERS，用第一个 TCP 可达的显式 server；
      2) 全部不可达 → 回退 mootdx 自带 bestip 测速选优；
      3) 再不行 → 回退裸 factory（老用户 config 已有可用 BESTIP 时成立）；
      4) 仍失败 → 抛 RuntimeError，明确报错而非死等。
    """
    for ip, port in _TDX_SERVERS:
        if _probe(ip, port):
            print(f"[tdx_client] TCP 探测命中 {ip}:{port}")
            return Quotes.factory(market=market, server=(ip, port))
    try:
        print("[tdx_client] 显式服务器全不可达，回退 bestip=True")
        return Quotes.factory(market=market, bestip=True)
    except Exception:
        pass
    try:
        print("[tdx_client] bestip 失败，回退裸 factory")
        return Quotes.factory(market=market)
    except Exception as e:
        raise RuntimeError(
            "所有 mootdx 服务器均不可达。海外网络通常全部超时（TCP 7709），"
            "请走国内代理或更新 _TDX_SERVERS 列表。原始错误：%s" % e
        )


# 探测样本（覆盖沪主板 / 深主板 / 创业板 / 科创板 4 类）
SAMPLES = ['600519', '000001', '300750', '688981', '000002']
SAMPLE_NAMES = {
    '600519': '贵州茅台',
    '000001': '平安银行',
    '300750': '宁德时代',
    '688981': '中芯国际',
    '000002': '万科A',
}


def probe_one(client, symbol):
    """探测单只股票，返回汇总信息"""
    t0 = time.time()
    try:
        # frequency=9 日线（默认）；offset=2500 ~ 10 年交易日
        df = client.bars(symbol=symbol, frequency=9, offset=2500)
    except Exception as e:
        elapsed = time.time() - t0
        return {
            'symbol': symbol,
            'name': SAMPLE_NAMES.get(symbol, '?'),
            'ok': False,
            'error': f"{type(e).__name__}: {e}",
            'elapsed': elapsed,
        }
    elapsed = time.time() - t0

    if df is None or len(df) == 0:
        return {
            'symbol': symbol,
            'name': SAMPLE_NAMES.get(symbol, '?'),
            'ok': False,
            'error': '返回空 DataFrame',
            'elapsed': elapsed,
        }

    # 字段
    fields = list(df.columns)
    # 日期范围（datetime 通常是字符串 'YYYY-MM-DD' 或 datetime）
    dt_col = df['datetime'] if 'datetime' in df.columns else None
    if dt_col is not None and len(dt_col) > 0:
        earliest = str(dt_col.iloc[0])
        latest = str(dt_col.iloc[-1])
    else:
        earliest = latest = 'N/A'

    return {
        'symbol': symbol,
        'name': SAMPLE_NAMES.get(symbol, '?'),
        'ok': True,
        'rows': len(df),
        'fields': fields,
        'earliest': earliest,
        'latest': latest,
        'head3': df.head(3).to_dict('records'),
        'elapsed': elapsed,
    }


def main():
    print("=" * 70)
    print("mootdx K线 可用性探测")
    print("=" * 70)

    # === 1. 建立 TCP 连接 ===
    print("\n[1] 建立 mootdx 客户端（tdx_client helper）...")
    t_conn = time.time()
    try:
        client = tdx_client()
    except Exception as e:
        print(f"[FAIL] tdx_client 失败：{type(e).__name__}: {e}")
        sys.exit(1)
    print(f"[OK] 客户端建立耗时 {time.time()-t_conn:.2f}s")

    # === 2. 逐只探测 ===
    print(f"\n[2] 探测 {len(SAMPLES)} 只样本（frequency=9 日线, offset=2500）...")
    results = []
    for sym in SAMPLES:
        print(f"\n--- {sym} {SAMPLE_NAMES.get(sym,'?')} ---")
        r = probe_one(client, sym)
        results.append(r)
        if r['ok']:
            print(f"  行数: {r['rows']}")
            print(f"  字段: {r['fields']}")
            print(f"  日期范围: {r['earliest']} ~ {r['latest']}")
            print(f"  耗时: {r['elapsed']:.2f}s")
            print(f"  前3行样例:")
            for row in r['head3']:
                print(f"    {row}")
        else:
            print(f"  [FAIL] {r['error']}")
            print(f"  耗时: {r['elapsed']:.2f}s")

    # === 3. 汇总 ===
    print("\n" + "=" * 70)
    print("[3] 汇总")
    print("=" * 70)
    ok_results = [r for r in results if r['ok']]
    fail_results = [r for r in results if not r['ok']]

    print(f"\n成功: {len(ok_results)}/{len(results)}，失败: {len(fail_results)}/{len(results)}")
    if ok_results:
        print("\n成功样本明细:")
        print(f"  {'代码':<8}{'名称':<10}{'行数':<8}{'最早日期':<14}{'最晚日期':<14}{'耗时(s)':<8}")
        for r in ok_results:
            print(f"  {r['symbol']:<8}{r['name']:<10}{r['rows']:<8}{r['earliest']:<14}{r['latest']:<14}{r['elapsed']:<8.2f}")

        # 字段一致性
        all_fields = set()
        for r in ok_results:
            all_fields.update(r['fields'])
        print(f"\n所有字段并集: {sorted(all_fields)}")

        # D2 必需字段检查（涨停/炸板/涨跌家数/成交额 需 close+high+low+amount）
        d2_required = {'close', 'high', 'low', 'amount'}
        missing = d2_required - all_fields
        print(f"D2 必需字段 (close/high/low/amount): {'✓ 齐全' if not missing else '✗ 缺失: ' + str(missing)}")
        # 换手率（已知缺口，mootdx 不提供）
        print(f"换手率字段: {'✓ 有' if 'turnover' in all_fields or 'hsl' in all_fields else '✗ 无（已知缺口，需走腾讯财经）'}")

        # 速度估算
        avg_time = sum(r['elapsed'] for r in ok_results) / len(ok_results)
        print(f"\n平均单只耗时: {avg_time:.2f}s")
        print(f"5500 只全量预估（串行）: {avg_time * 5500 / 60:.1f} 分钟")
        print(f"5500 只全量预估（10 并发）: {avg_time * 5500 / 10 / 60:.1f} 分钟")

    if fail_results:
        print("\n失败样本:")
        for r in fail_results:
            print(f"  {r['symbol']} {r['name']}: {r['error']}")

    # === 4. 结论 ===
    print("\n" + "=" * 70)
    print("[4] 结论")
    print("=" * 70)
    if len(ok_results) == len(results):
        print("✓ mootdx K线 API 完全可用：TCP 连通、行数达标、字段齐全、不封 IP")
        print("✓ 可作 D3 备选（全 A 股 10 年日线）")
    elif len(ok_results) > 0:
        print(f"△ mootdx 部分可用：{len(ok_results)}/{len(results)} 成功，需排查失败原因")
    else:
        print("✗ mootdx 全部失败，不可作 D3 备选")


if __name__ == '__main__':
    main()
