#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取 LOF（上市开放式基金）的跟踪指数，缓存到 data/lof_track_index.json。

目的：让 160225（国泰国证新能源汽车LOF A）等 LOF 进入 ETF 匹配候选池。
akshare fund_etf_spot_em() 只含场内 ETF 不含 LOF，build_board_etf_map.py
三层匹配（track_index/overlap/KW）无源可查 LOF。本脚本补 LOF 数据源。

数据源（2026-08-05 实测）：
  - fund_lof_spot_em() 不稳定（RemoteDisconnected，3-5 次重试仍断）
  - fund_open_fund_rank_em(symbol='全部') 稳定（20071 行开放式基金）
  - fundf10.eastmoney.com/jbgk_<code>.html 稳定（和 ETF 同源，复用 fetch_etf_track_index 逻辑）

流程：
  1. fund_open_fund_rank_em(symbol='全部') 拿全量开放式基金（20071 只）
  2. 预筛 LOF 候选：简称含'LOF' OR (简称含'指数' AND 代码 LOF 段 16/15/501/502)
     预筛后约 600 只（160225 简称'国泰国证新能源汽车指数A'含'指数'+代码16开头命中）
  3. fundf10 抓每只，提取"基金全称/跟踪标的/基金类型"
  4. 只保留：基金全称含'(LOF)' 且 跟踪标的非空'该基金无跟踪标的' -> 存入缓存
  5. fund_type='lof' 标记，供 build_board_etf_map.py 纳入候选池

注意：
  - fundf10 的"基金全称"含'(LOF)'才是真 LOF（160225 全称'...证券投资基金(LOF)'）
    简称不一定含 LOF（160225 简称'国泰国证新能源汽车指数A'无 LOF 字样）
  - LOF 成交额 fund_open_fund_rank_em 不返回，amount 暂置 0（靠 track_index 匹配，
    不按 amount 排序；后续路A-2b 用相似度排序替代 amount 排序）
  - 增量更新：已抓且 fetched_at 当天的不重抓（除非 --force）
  - SSL 证书验证关闭（eastmoney 自签证书，和 fetch_etf_track_index 同策略）

可重复跑：python scripts/fetch_lof_track_index.py [--force] [--timeout 15]
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
OUT = ROOT / "data" / "lof_track_index.json"

# 关闭 SSL 验证（eastmoney 自签证书，和 fetch_etf_track_index 同策略）
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

# "跟踪标的"字段正则（和 fetch_etf_track_index._TRACK_PATTERNS 同源）
_TRACK_PATTERNS = [
    re.compile(r'跟踪标的[^<]*</th>\s*<td[^>]*>([^<]+)</td>', re.S),
    re.compile(r'跟踪标的.*?<td[^>]*>\s*([^<\s][^<]*?)\s*</td>', re.S),
]
# "基金全称"字段正则（用于判断是否 LOF：全称含'(LOF)')
_FULLNAME_PAT = re.compile(r'基金全称[^<]*</th>\s*<td[^>]*>([^<]+)</td>', re.S)
# "基金类型"字段正则（如'指数型-股票'）
_TYPE_PAT = re.compile(r'基金类型[^<]*</th>\s*<td[^>]*>([^<]+)</td>', re.S)


def fetch_fundf10(code: str, timeout: int = 15) -> str:
    """抓 fundf10 jbgk HTML，返回解码后的字符串。

    和 fetch_etf_track_index.fetch_fundf10 同实现（LOF 也用 fundf10.eastmoney.com/jbgk_<code>.html）。
    复制而非 import 是为保持脚本独立可跑（fetch_etf_track_index 在 scripts/ 同目录）。
    """
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
    for enc in ('utf-8', 'gbk', 'gb18030'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def _find(pat: re.Pattern, html: str) -> str | None:
    """正则查找字段值，去 inner tags。"""
    m = pat.search(html)
    if m:
        v = m.group(1).strip()
        v = re.sub(r'<[^>]+>', '', v).strip()
        return v or None
    return None


def parse_lof_info(html: str) -> tuple[str | None, str | None, str | None]:
    """解析 fundf10 jbgk 页面，返回 (基金全称, 跟踪标的, 基金类型)。"""
    fullname = _find(_FULLNAME_PAT, html)
    track = _find(_TRACK_PATTERNS[0], html) or _find(_TRACK_PATTERNS[1], html)
    ftype = _find(_TYPE_PAT, html)
    return fullname, track, ftype


def prefilter_lof_candidates(df) -> list[tuple[str, str]]:
    """预筛 LOF 候选，返回 [(code, name), ...]。

    策略C（实测 600 只，覆盖 160225）：
      简称含'LOF' OR (简称含'指数' AND 代码在 LOF 段 16/15/501/502 开头)

    LOF 代码段：
      - 深市 LOF: 160xxx-169xxx, 150xxx（部分转型）
      - 沪市 LOF: 501xxx, 502xxx
    """
    code = df['基金代码'].astype(str)
    name = df['基金简称'].astype(str)
    has_lof = name.str.contains('LOF', case=False, na=False)
    has_idx = name.str.contains('指数', na=False)
    # 代码 LOF 段：16/15 开头（深市），501/502 开头（沪市）
    lof_seg = code.str.match(r'^(16|15|50[12])')
    mask = has_lof | (has_idx & lof_seg)
    cand = df[mask]
    return [(str(r['基金代码']), str(r['基金简称'])) for _, r in cand.iterrows()]


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
            print(f"-> 加载已有缓存 {len(cache)} 条（增量更新，已有 track_index 的跳过）")
        except Exception as e:
            print(f"⚠ 缓存读取失败 {e}，全量重抓")
            cache = {}
    elif args.force:
        print("-> --force 强制重抓")

    # 拉 akshare 全量开放式基金（fund_lof_spot_em 不稳定，改用 fund_open_fund_rank_em）
    print(f"-> 拉取 akshare fund_open_fund_rank_em(symbol='全部') ...")
    df = ak.fund_open_fund_rank_em(symbol='全部')
    print(f"   共 {len(df)} 只开放式基金")

    # 预筛 LOF 候选
    candidates = prefilter_lof_candidates(df)
    print(f"   预筛 LOF 候选: {len(candidates)} 只（简称含'LOF' OR 简称含'指数'且代码LOF段）")

    # 统计
    ok = 0           # 是 LOF 且有跟踪标的
    no_track = 0     # 是 LOF 但无跟踪标的
    not_lof = 0      # 基金全称不含 (LOF)，非 LOF
    err = 0
    skipped = 0
    total = len(candidates)

    # 已有 track_index 的跳过（增量）
    to_fetch = []
    for code, name in candidates:
        existing = cache.get(code)
        if (not args.force and isinstance(existing, dict)
                and existing.get('track_index')
                and existing.get('fund_type') == 'lof'):
            skipped += 1
            existing['name'] = name  # 更新简称（实时值）
            cache[code] = existing
            continue
        to_fetch.append((code, name))

    print(f"   跳过已抓: {skipped} 只")
    print(f"   待抓: {len(to_fetch)} 只，预估 {len(to_fetch) * 0.55:.0f}s")

    for i, (code, name) in enumerate(to_fetch, 1):
        try:
            html = fetch_fundf10(code, timeout=args.timeout)
            fullname, track, ftype = parse_lof_info(html)
            # 判断是否 LOF：基金全称含 '(LOF)'（大小写不敏感）
            is_lof = bool(fullname and 'LOF' in fullname.upper())
            if not is_lof:
                # 非 LOF：记录但 status=not_lof（避免重抓，但不入候选）
                not_lof += 1
                cache[code] = {
                    'name': name,
                    'fullname': fullname or '',
                    'track_index': '',
                    'fund_type': ftype or '',
                    'amount': 0.0,
                    'fetched_at': today,
                    'status': 'not_lof',
                }
            elif track and '该基金无跟踪标的' not in track:
                # 是 LOF 且有跟踪标的：入候选
                cache[code] = {
                    'name': name,
                    'fullname': fullname,
                    'track_index': track,
                    'fund_type': 'lof',
                    'fund_subtype': ftype or '',
                    'amount': 0.0,  # fund_open_fund_rank_em 无成交额，置 0
                    'fetched_at': today,
                }
                ok += 1
            else:
                # 是 LOF 但无跟踪标的（主动管理 LOF，如兴全合润）
                no_track += 1
                cache[code] = {
                    'name': name,
                    'fullname': fullname,
                    'track_index': '',
                    'fund_type': 'lof',
                    'fund_subtype': ftype or '',
                    'amount': 0.0,
                    'fetched_at': today,
                    'status': 'no_track',
                }
        except Exception as e:
            err += 1
            print(f"  [{i}/{total}] {code} {name}: ERROR {e}")
        # 进度（每50只一次）
        if i % 50 == 0 or i == total:
            print(f"  [{i}/{total}] ok={ok} no_track={no_track} not_lof={not_lof} err={err}")
            # 中途写盘（防中断丢进度）
            cache['_meta'] = {
                'source': 'fundf10.eastmoney.com/jbgk + fund_open_fund_rank_em(全部)',
                'fetched_at': today,
                'total': total,
                'ok': ok,
                'no_track': no_track,
                'not_lof': not_lof,
                'error': err,
                'skipped': skipped,
            }
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
        time.sleep(random.uniform(args.sleep_min, args.sleep_max))

    # 最终写盘
    cache['_meta'] = {
        'source': 'fundf10.eastmoney.com/jbgk + fund_open_fund_rank_em(全部)',
        'fetched_at': today,
        'total': total,
        'ok': ok,
        'no_track': no_track,
        'not_lof': not_lof,
        'error': err,
        'skipped': skipped,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')

    # 统计真 LOF（fund_type=lof 且 track_index 非空）
    lof_with_track = sum(1 for k, v in cache.items()
                         if not k.startswith('_') and isinstance(v, dict)
                         and v.get('fund_type') == 'lof' and v.get('track_index'))
    print(f"\n✓ 生成 {OUT.name}：本次抓 {total} 只（ok={ok}, no_track={no_track}, not_lof={not_lof}, err={err}, skipped={skipped}）")
    print(f"   缓存中真 LOF（fund_type=lof 且 track_index 非空）: {lof_with_track} 只")

    # 抽样验证 160225
    hit = cache.get('160225')
    if hit:
        print(f"\n   160225 验证: name={hit.get('name')}, track_index={hit.get('track_index')!r}, fund_type={hit.get('fund_type')}")
    else:
        print(f"\n   ⚠ 160225 未在缓存中")


if __name__ == '__main__':
    main()
