# -*- coding: utf-8 -*-
"""2026-11-25 存储治理三机制单测共用夹具(纯本地 journal/payload 树, 零网络/零外发)。

为什么单独放一个下划线模块: 块2(保守保留)与块3(GC 预算拆分)都要构造「顶层 journal +
history + payloads + pairs」四件套, 复制两份容易漂移成第二份实现。这里只做**落盘形状**,
不含任何生产逻辑; 生产代码仍是 scripts/r2_safe_write.py 单一事实源。

时点: 全部 mtime 用固定历史 epoch(L51 禁写死「今天」, 与本文件运行日无关)。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

PAIR = ('data/overfit_monitor.json', 'data/overfit_monitor_ext.json')
BASE_MTIME = 1700000000  # 固定历史时点(2023-11-14 UTC), 与时敏无关


def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def wid(n: int) -> str:
    """32 位十六进制 write_id(生产契约 re.fullmatch('[a-f0-9]{32}'))。"""
    return '%032x' % n


def pid(n: int) -> str:
    """32 位十六进制 pair_id。"""
    return '%032x' % n


class ProtectedTree:
    """构造一份可被 SafeWriter.gc() 直接读取的本地 protected 树。"""

    def __init__(self, tmp_path):
        self.static_dir = Path(tmp_path) / 'static-site'
        self.static_dir.mkdir(parents=True, exist_ok=True)
        # 与生产同构: SafeWriter.root = STATIC_DIR.parent / 'data' / '.r2-protected'
        self.root = self.static_dir.parent / 'data' / '.r2-protected'
        for sub in ('', 'history', 'payloads', 'pairs'):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        # SafeWriter 只需要这几个键; gc 不触达网络/锁以外的东西。
        self.api = {
            'STATIC_DIR': self.static_dir,
            'BUCKET': 'public',
            'BACKUP_BUCKET': 'backup',
            '_work_budget_check': lambda *a, **k: None,
            '_work_sleep': lambda *a, **k: None,
        }

    # ---- 落盘原语 ----
    def journal_path(self, key: str) -> Path:
        digest = hashlib.sha256(('public/' + key).encode()).hexdigest()
        return self.root / (digest + '.json')

    def write(self, path: Path, body, mtime: int = BASE_MTIME) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, str):
            body = body.encode()
        path.write_bytes(body)
        os.utime(path, (mtime, mtime))
        return path

    def payload(self, digest: str, body: bytes, mtime: int = BASE_MTIME) -> Path:
        return self.write(self.root / 'payloads' / digest, body, mtime)

    # ---- 对象构造 ----
    def add(self, key, body: bytes, write_id: str, *, state='confirmed',
            old_body: bytes | None = None, pair_id: str | None = None,
            pending_purge: bool = False, top_level: bool = True,
            mtime: int = BASE_MTIME):
        """写一条 history + (可选)顶层 journal + 对应 payload; 返回 row。"""
        digest = sha256_bytes(body)
        self.payload(digest, body, mtime)
        row = {
            'version': 1, 'bucket': 'public', 'key': key, 'sha256': digest,
            'size': len(body), 'write_id': write_id, 'state': state,
            'confirmed': state == 'confirmed', 'pending_purge': pending_purge,
            'run_id': 'r' * 32, 'old_sha256': None, 'backup_key': None,
        }
        if old_body is not None:
            old_digest = sha256_bytes(old_body)
            self.payload(old_digest, old_body, mtime)
            row['old_sha256'] = old_digest
        if pair_id is not None:
            row['pair_id'] = pair_id
        encoded = json.dumps(row, sort_keys=True).encode()
        if top_level:
            self.write(self.journal_path(key), encoded, mtime)
        self.write(self.root / 'history' / (write_id + '.json'), encoded, mtime)
        return row

    def add_pair(self, pair_id, bodies, write_ids, *, state='prepared', mtime=BASE_MTIME):
        """PAIR 两件 + pair manifest(pair 引用闭包递归测试用)。"""
        rows = {key: self.add(key, bodies[key], write_ids[key], state=state,
                              pair_id=pair_id, mtime=mtime) for key in PAIR}
        manifest = {'version': 1, 'pair_id': pair_id, 'objects': rows}
        self.write(self.root / 'pairs' / (pair_id + '.json'),
                   json.dumps(manifest, sort_keys=True).encode(), mtime)
        return rows

    # ---- 断言辅助 ----
    def files(self):
        """相对 root 的文件路径集合(排序稳定, 便于断言)。"""
        return {p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file()}

    def history_path(self, write_id: str) -> Path:
        return self.root / 'history' / (write_id + '.json')

    def payload_path(self, digest: str) -> Path:
        return self.root / 'payloads' / digest
