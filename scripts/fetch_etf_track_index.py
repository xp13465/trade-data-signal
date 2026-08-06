#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取全量 ETF 的跟踪指数（track_index），缓存到 data/etf_track_index.json。

数据源：fundf10.eastmoney.com/jbgk_<code>.html（HTML 页面"跟踪标的"字段）。
akshare fund_etf_spot_em() 不返回 track_index_code 字段（gen_etf_index_map.py 只能名称反推
14 个宽基/红利/港股指数），行业/概念 ETF 的 track_index 无数据源。本脚本抓 fundf10 HTML
填补该空缺，让 build_board_etf_map.py 用 track_index_name 精准匹配行业/概念 ETF。

设计：
  - 抓全量 ETF（akshare fund_etf_spot_em 的 ~1567 只），sleep 0.4-0.6s 防限流
  - 解析"跟踪标的"字段（页面声明 utf-8 实际可能 gbk，健壮解码两种）
  - 增量更新：已抓且 fetched_at 当天的不重抓（除非 --force）
  - SSL 证书验证关闭（eastmoney 自签证书）

可重复跑：python scripts/fetch_etf_track_index.py [--force] [--timeout 15]
"""
import argparse
import json
import random
import re
import ssl
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

import akshare as ak

ROOT = Path(__file__).absolute().parent.parent
OUT = ROOT / "data" / "etf_track_index.json"

# 关闭 SSL 验证（eastmoney 自签证书）
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

# "跟踪标的"字段正则：fundf10 jbgk HTML 表格 <th>跟踪标的</th><td>xxx</td>
_TRACK_PATTERNS = [
    re.compile(r'跟踪标的[^<]*</th>\s*<td[^>]*>([^<]+)</td>', re.S),
    re.compile(r'跟踪标的.*?<td[^>]*>\s*([^<\s][^<]*?)\s*</td>', re.S),
]


def fetch_fundf10(code: str, timeout: int = 15) -> str:
    """抓 fundf10 jbgk HTML，返回解码后的字符串。"""
    url = f'https://fundf10.eastmoney.com/jbgk_{code}.html'
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Referer': 'https://fundf10.eastmoney.com/',
    })
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
        raw = resp.read()
    # 健壮解码：先 utf-8 再 gbk 再 gb18030
    for enc in ('utf-8', 'gbk', 'gb18030'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def parse_track_index(html: str) -> str | None:
    """解析"跟踪标的"字段，返回 track_index 名（如"沪深300指数"）或 None。"""
    for pat in _TRACK_PATTERNS:
        m = pat.search(html)
        if m:
            v = m.group(1).strip()
            v = re.sub(r'<[^>]+>', '', v).strip()  # 去 inner tags
            if v:
                return v
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true', help='强制重抓（忽略缓存）')
    ap.add_argument('--timeout', type=int, default=15)
    ap.add_argument('--sleep-min', type=float, default=0.4)
    ap.add_argument('--sleep-max', type=float, default=0.7)
    args = ap.parse_args()

    today = date.today().isoformat()

    # 加载已有缓存（增量更新）
    cache: dict = {}
    if OUT.exists() and not args.force:
        try:
            cache = json.loads(OUT.read_text(encoding='utf-8'))
            print(f"-> 加载已有缓存 {len(cache)} 条（增量更新，已抓且 fetched_at={today} 的跳过）")
        except Exception as e:
            print(f"⚠ 缓存读取失败 {e}，全量重抓")
            cache = {}
    elif args.force:
        print("-> --force 强制重抓")

    # 拉 akshare 全量 ETF 行情
    print(f"-> 拉取 akshare fund_etf_spot_em() 全量 ETF 行情 ...")
    df = ak.fund_etf_spot_em()
    df['成交额'] = df['成交额'].fillna(0)
    print(f"   共 {len(df)} 只 ETF")

    # 过滤：剔除跨境/债券/商品/货币 ETF（这些走 etf_index_map.json 已精准匹配，不需 fundf10）
    # 但保留所有 A 股行业/概念/宽基 ETF
    EXCLUDE = ["债", "货币", "黄金", "白银", "原油", "海外", "美国", "日本", "德国",
               "法国", "英国", "韩国", "中韩", "亚太", "纳斯达克", "纳指", "标普", "日经",
               "恒生", "港股", "香港", "QDII", "商品", "豆粕", "REIT", "可转债",
               "国债", "信用", "MOM", "FOF"]
    names = df['名称'].astype(str)
    excl_mask = names.apply(lambda n: any(ex in n for ex in EXCLUDE))
    # 保留：非EXCLUDE 或 已在缓存中的（缓存里有的不丢）
    df_keep = df[~excl_mask].copy()
    # 成交额 >=100万的优先抓（冷门ETF抓了也用不上）
    df_keep = df_keep[df_keep['成交额'] >= 1e6]
    print(f"   过滤 EXCLUDE + 成交额>=100万 后: {len(df_keep)} 只待抓")

    # 统计
    ok = 0
    no_track = 0
    err = 0
    skipped = 0
    total = len(df_keep)
    cache_meta = cache.pop('_meta', {}) if isinstance(cache.get('_meta'), dict) else {}

    # 已抓且 fetched_at=today 的跳过
    to_fetch = []
    for _, r in df_keep.iterrows():
        code = str(r['代码'])
        name = str(r['名称'])
        amount = float(r['成交额']) or 0.0
        existing = cache.get(code)
        if (not args.force and isinstance(existing, dict)
                and existing.get('fetched_at') == today
                and existing.get('track_index')):
            skipped += 1
            # 更新 amount（实时值）
            existing['amount'] = round(amount, 2)
            existing['name'] = name
            cache[code] = existing
            continue
        to_fetch.append((code, name, amount))

    print(f"   跳过已抓（今日）: {skipped} 只")
    print(f"   待抓: {len(to_fetch)} 只，预估 {len(to_fetch) * 0.55:.0f}s")

    for i, (code, name, amount) in enumerate(to_fetch, 1):
        try:
            html = fetch_fundf10(code, timeout=args.timeout)
            track = parse_track_index(html)
            if track:
                cache[code] = {
                    'name': name,
                    'track_index': track,
                    'amount': round(amount, 2),
                    'fetched_at': today,
                }
                ok += 1
            else:
                # 解析失败：仍记录（status=no_track），避免重抓
                cache[code] = {
                    'name': name,
                    'track_index': '',
                    'amount': round(amount, 2),
                    'fetched_at': today,
                    'status': 'no_track',
                }
                no_track += 1
        except Exception as e:
            # 抓取失败：不写缓存（下次重试）
            err += 1
            print(f"  [{i}/{total}] {code} {name}: ERROR {e}")
        # 进度（每50只一次）
        if i % 50 == 0 or i == total:
            print(f"  [{i}/{total}] ok={ok} no_track={no_track} err={err}")
            # 中途写盘（防中断丢进度）
            cache['_meta'] = {
                'source': 'fundf10.eastmoney.com/jbgk_<code>.html',
                'fetched_at': today,
                'total': total,
                'ok': ok,
                'no_track': no_track,
                'error': err,
                'skipped': skipped,
            }
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
        time.sleep(random.uniform(args.sleep_min, args.sleep_max))

    # 最终写盘
    cache['_meta'] = {
        'source': 'fundf10.eastmoney.com/jbgk_<code>.html',
        'fetched_at': today,
        'total': total,
        'ok': ok,
        'no_track': no_track,
        'error': err,
        'skipped': skipped,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"\n✓ 生成 {OUT.name}：本次抓 {total} 只（ok={ok}, no_track={no_track}, err={err}, skipped={skipped}）")
    print(f"   缓存总条目: {len(cache) - 1}（含历史）")


if __name__ == '__main__':
    main()
