#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R2 上传锁的**路径推导 + 产物域白名单**单一事实源(2026-10-28 返工)。

为什么单独一个模块: 「域锁路径怎么拼」「有哪些合法域」这两件事有三个消费者 ——
  ① `scripts/upload_r2.py`(真正取锁的写者);
  ② `scripts/r2_lock_probe.py`(排障探针, 超时后要说清「哪把锁被占」);
  ③ `scripts/r2_lock_gradient_audit.py`(静态审计, 检查调用方声明与梯度)。
三处各写一份 = 必然漂移(2026-10-28 审查实证: 探针只登记了全局锁/小锁, 认不出 20 把域锁,
超时诊断会指向错误文件)。故收敛到这里, 其余模块一律 import, 禁止手抄第二份列表。

纯函数 / 纯常量: 不读写文件、不起子进程、不碰网络(§18 L50 static-only 精神)。

⚠ 与 `upload_r2.py` 的历史兼容: 该文件的 `_LOCK_DOMAIN_ENV` / `_global_upload_lock_path` /
`_domain_upload_lock_path` 名字被既有单测与审计脚本按源码形状断言, 故保留这些薄封装, 实现一律
委托本模块(机检见 `r2_lock_gradient_audit.py` 的「实现侧契约」段: 常量必须与本模块同值)。
"""
from __future__ import annotations

import os
from pathlib import Path

# ── env 名与缺省路径(生产现路径, 改这里就够; 三处消费者自动跟随) ──────────────
DOMAIN_ENV = "R2_UPLOAD_LOCK_DOMAIN"
GLOBAL_ENV = "R2_UPLOAD_LOCK"
GLOBAL_DEFAULT = "/tmp/trade_r2_upload.lock"
SMALL_ENV = "R2_UPLOAD_SMALL_LOCK"
SMALL_DEFAULT = "/tmp/trade_r2_upload_small.lock"

# ── 产物域白名单(20 个) ─────────────────────────────────────────────────────
# 单一事实源。新增域 = 改这里 + `r2_lock_gradient_audit.py` 的 DOMAINS(说明文字表)并在
# `docs/ops/r2-lock-domains-20261028.md` §2 补一行对象 key 前缀; 三处不一致审计 FAIL。
# 白名单的必要性(2026-10-28 审查): 域名字典原先只校验「形状」, 打错成另一个合法名会**自建一把
# 新锁**, 与真正的同 key 写者静默互斥失效 ⇒ 未登记域名一律回落全局锁 + WARN(fail-open 到串行)。
LOCK_DOMAINS = frozenset({
    "data",
    "kelly_parts",
    "kelly_sdc",
    "kelly_snapshots",
    "lab",
    "trade_sim",
    "trade_sim_data",
    "index",
    "etf",
    "accum_nav",
    "industry",
    "public_fund",
    "offshore_fund",
    "fund_score",
    "etf_score",
    "fund_nav",
    "backup_db",
    "large_json",
    "claude_backup",
    "decommissioned",
})

# 探针标签前缀: 「域锁:<domain>」。`r2_lock_probe.probe_locks` 靠它把「无占用的域锁」折叠成一行。
DOMAIN_LABEL_PREFIX = "域锁:"


def global_lock_path() -> Path:
    """全局上传锁路径(env R2_UPLOAD_LOCK 覆盖; 缺省 = 生产现路径)。"""
    return Path(os.environ.get(GLOBAL_ENV, GLOBAL_DEFAULT))


def small_lock_path() -> Path:
    """小载荷专用锁路径(env R2_UPLOAD_SMALL_LOCK 覆盖; 缺省 = 生产小锁路径)。"""
    return Path(os.environ.get(SMALL_ENV, SMALL_DEFAULT))


def domain_lock_path(domain: str) -> Path:
    """域锁路径 = 全局锁路径同目录派生(stem + '_' + domain + suffix)。

    例: /tmp/trade_r2_upload.lock → /tmp/trade_r2_upload_data.lock。
    """
    base = global_lock_path()
    return base.with_name(f"{base.stem}_{domain}{base.suffix}")


def lock_endpoints(include_domains: bool = True) -> list[tuple[str, str]]:
    """返回 [(标签, 锁路径), ...]: 上传可能用到的全部锁(全局 → 小锁 → 各域锁, 域名排序)。

    `include_domains=False` 只返回全局锁 + 小锁(2026-10-23 方案 A 起的两把锁)。
    纯读环境变量, 不 stat/不打开文件。
    """
    out = [("全局锁", str(global_lock_path())), ("小锁", str(small_lock_path()))]
    if include_domains:
        out.extend((f"{DOMAIN_LABEL_PREFIX}{d}", str(domain_lock_path(d)))
                   for d in sorted(LOCK_DOMAINS))
    return out