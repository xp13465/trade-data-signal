#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API key 管理脚本（统一数据查询 API /api/data/* 配套，2026-08-17）。

用途：为 UUMit 平台付费 API 的 key 生成/吊销/列表。key 只在 KV 存 SHA-256 hash（api_key:<hash>），
真实 key 生成后只打印一次，不落盘。

KV 键空间（SUBSCRIBE_KV namespace，id 7d373c3365314ec7a334ac47a73f1578，见 wrangler.jsonc）：
  api_key:<hash>            = "1"（存在的 key hash）
  api_quota:<hash>:minute   = 每分钟配额（默认 60）
  api_quota:<hash>:day      = 每日配额（默认 5000）
  api_usage_lim:<hash>:m:<yyyyMMddHHmm>  = 每分钟请求计数（限流）
  api_usage_lim:<hash>:d:<yyyyMMdd>      = 每日请求计数（限流）
  api_usage:<hash>:<yyyyMMddHH<5min桶>>  = 计量明细（每 5 分钟聚合，JSON 数组）

用法（需在仓库根目录跑，wrangler 读 wrangler.jsonc 的 namespace）：
  python3 scripts/api_key_mgmt.py gen [--quota-minute 60] [--quota-day 5000]
  python3 scripts/api_key_mgmt.py revoke <key>
  python3 scripts/api_key_mgmt.py list
  python3 scripts/api_key_mgmt.py usage <key_hash>

依赖：npx wrangler（GH Actions deploy 同款）。
真实 key 只在 gen 输出一次，务必立即保存；丢了只能 revoke 重发。
"""

import argparse
import hashlib
import secrets
import subprocess
import sys

NS_ID = "7d373c3365314ec7a334ac47a73f1578"
HASH_PREFIX = "api_key:"


def hash_key(key: str) -> str:
    return hashlib.sha256(("api-key:" + key).encode("utf-8")).hexdigest()


def run_wrangler(args):
    # 用 npx wrangler kv 子命令操作 remote namespace
    cmd = ["npx", "wrangler", "kv", *args, "--namespace-id", NS_ID]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr or r.stdout, file=sys.stderr)
        sys.exit(1)
    return r.stdout


def kv_put(key, value):
    run_wrangler(["key", "put", key, value])


def kv_delete(key):
    run_wrangler(["key", "delete", key])


def kv_get(key):
    # 返回 (exists, value)
    r = subprocess.run(
        ["npx", "wrangler", "kv", "key", "get", key, "--namespace-id", NS_ID],
        capture_output=True, text=True,
    )
    return r.returncode == 0, r.stdout.strip()


def gen(args):
    key = "tk_" + secrets.token_urlsafe(24)
    h = hash_key(key)
    kv_put(HASH_PREFIX + h, "1")
    if args.quota_minute:
        kv_put(f"api_quota:{h}:minute", str(args.quota_minute))
    if args.quota_day:
        kv_put(f"api_quota:{h}:day", str(args.quota_day))
    print("API key 已生成（只打印这一次，请立即保存）：")
    print(f"  key   : {key}")
    print(f"  hash  : {h}")
    print(f"  minute: {args.quota_minute}  day: {args.quota_day}")


def revoke(args):
    h = hash_key(args.key)
    exists, _ = kv_get(HASH_PREFIX + h)
    if not exists:
        print(f"key {args.key} 的 hash 不存在（可能已吊销）")
        sys.exit(1)
    kv_delete(HASH_PREFIX + h)
    print(f"已吊销 key（hash {h}）")


def list_keys(args):
    out = run_wrangler(["key", "list", "--prefix", HASH_PREFIX])
    lines = [l for l in out.splitlines() if HASH_PREFIX in l]
    if not lines:
        print("（无已登记的 API key）")
        return
    print("已登记 API key（仅 hash，真实 key 不可逆）：")
    for l in lines:
        # wrangler list 输出含 key 名，提取 hash 部分
        if "=" in l:
            keyname = l.split("=")[0].strip()
        else:
            keyname = l.strip()
        print("  ", keyname.replace(HASH_PREFIX, ""))


def usage(args):
    exists, _ = kv_get(HASH_PREFIX + args.key_hash)
    if not exists:
        print(f"hash {args.key_hash} 未登记")
        sys.exit(1)
    # 列出该 key 的计量与限流键（前缀 api_usage:<hash> 与 api_usage_lim:<hash>）
    for prefix in (f"api_usage:{args.key_hash}:", f"api_usage_lim:{args.key_hash}:"):
        try:
            out = run_wrangler(["key", "list", "--prefix", prefix])
            cnt = len([l for l in out.splitlines() if prefix in l])
            print(f"前缀 {prefix} 共 {cnt} 个键")
        except SystemExit:
            pass


def main():
    p = argparse.ArgumentParser(description="统一数据查询 API key 管理")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen", help="生成新 key")
    g.add_argument("--quota-minute", type=int, default=60)
    g.add_argument("--quota-day", type=int, default=5000)
    g.set_defaults(fn=gen)
    r = sub.add_parser("revoke", help="吊销 key")
    r.add_argument("key")
    r.set_defaults(fn=revoke)
    l = sub.add_parser("list", help="列出已登记 key")
    l.set_defaults(fn=list_keys)
    u = sub.add_parser("usage", help="查看某 key 的计量/限流键（传 hash）")
    u.add_argument("key_hash")
    u.set_defaults(fn=usage)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
