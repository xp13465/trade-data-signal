# -*- coding: utf-8 -*-
"""2026-11-25 存储治理块3: GC 回收预算与新增写入配额拆开(方案 §3.3 / §6 反例对)。

修复前反例(云上实证, /tmp/storage-recheck-20261125.md §6): C 根 9286 文件 > 8192 且
10.68GB > 2GiB cap, gc() 在 unlink 前用「全部旧文件」跑 check_capacity ⇒ 必抛 UnsafeWrite
⇒ 永远清不动(夹具 /tmp/codex-reports/storage-cleanup-20261124-gc-fixture.json)。

修复后契约:
  ① 超 cap / 超文件预算的**无引用**文件能本地回收(引用已证明 + 同锁域 + 清单先落盘);
  ② 新增写入仍被原 cap/8192/reserve 拦截(只保留集合本身超预算 ⇒ 照旧拒绝新写);
  ③ 坏 JSON / 缺引用(kept payload 缺失) / symlink / 文件身份变化 / 计划后新引用 / 锁冲突
     全部阻断删除;
  ④ 清单落盘失败零删除。

全部临时目录, 零网络零外发, 不触生产 data/。时点固定历史 epoch(L51)。
"""
from __future__ import annotations

import fcntl
import json

import pytest

import r2_safe_write
from _storage_mechfix_fixture_20261125 import BASE_MTIME, ProtectedTree, sha256_bytes, wid


def _superseded(tree, n, key='nav_bucket/gc.json'):
    """n 条已被取代的 confirmed 历史(每条自带 payload) + 1 条当前 confirmed。"""
    rows = [tree.add(key, ('old-%02d' % i).encode(), wid(100 + i),
                     top_level=False, mtime=BASE_MTIME + i) for i in range(n)]
    tree.add(key, b'current', wid(999), mtime=BASE_MTIME + 10_000)
    return rows


def _gc(tree):
    safe = r2_safe_write.SafeWriter(tree.api)
    with safe.storage_lock():
        return safe.gc(), safe


def test_over_budget_unreferenced_files_are_reclaimed(tmp_path, monkeypatch, capsys):
    tree = ProtectedTree(tmp_path)
    rows = _superseded(tree, 10)
    before = tree.files()
    assert len(before) > 5
    monkeypatch.setenv('R2_PROTECTED_MAX_BYTES', '1')      # cap 远小于现存(修复前必拒)
    monkeypatch.setattr(r2_safe_write, 'PROTECTED_FILE_BUDGET', 5)  # 文件数远小于现存

    kept, safe = _gc(tree)

    for row in rows:
        assert not tree.history_path(row['write_id']).exists()
        assert not tree.payload_path(row['sha256']).exists()
    assert tree.journal_path('nav_bucket/gc.json').exists()
    manifest = json.loads((tree.root / 'gc-manifest.json').read_text())
    assert manifest['retired_count'] == 2 * len(rows)
    assert all((tree.root / rel).exists() for rel in manifest['keep'])
    err = capsys.readouterr().err
    assert 'reclaim-over-write-budget' in err   # 超预算回收有可观测日志


def test_new_write_still_refused_by_original_cap(tmp_path, monkeypatch):
    tree = ProtectedTree(tmp_path)
    rows = _superseded(tree, 3)
    monkeypatch.setenv('R2_PROTECTED_MAX_BYTES', '1')
    safe = r2_safe_write.SafeWriter(tree.api)
    target = tree.root / 'payloads' / ('f' * 64)

    with pytest.raises(r2_safe_write.UnsafeWrite, match='capacity budget exhausted'):
        safe.store_many({target: b'x'})
    assert not target.exists()
    # 回收本身照常发生(旧无引用行被清掉), 只是新写入被原配额拦住
    assert not tree.history_path(rows[0]['write_id']).exists()


def test_new_write_still_refused_by_original_file_budget(tmp_path, monkeypatch):
    tree = ProtectedTree(tmp_path)
    _superseded(tree, 2)
    monkeypatch.setenv('R2_PROTECTED_MAX_BYTES', str(10 * 1024**3))
    monkeypatch.setattr(r2_safe_write, 'PROTECTED_FILE_BUDGET', 5)
    safe = r2_safe_write.SafeWriter(tree.api)
    target = tree.root / 'payloads' / ('e' * 64)

    with pytest.raises(r2_safe_write.UnsafeWrite, match='capacity budget exhausted'):
        safe.store_many({target: b'y'})
    assert not target.exists()


def test_bad_json_stops_whole_batch_with_zero_deletion(tmp_path):
    tree = ProtectedTree(tmp_path)
    rows = _superseded(tree, 3)
    (tree.root / 'history' / 'corrupt.json').write_text('{"version": 1, "key": ')
    safe = r2_safe_write.SafeWriter(tree.api)

    with pytest.raises(ValueError):
        with safe.storage_lock():
            safe.gc()
    for row in rows:
        assert tree.history_path(row['write_id']).exists()
        assert tree.payload_path(row['sha256']).exists()
    assert not (tree.root / 'gc-manifest.json').exists()


def test_invalid_payload_reference_stops_whole_batch(tmp_path):
    tree = ProtectedTree(tmp_path)
    rows = _superseded(tree, 2)
    bad = {'version': 1, 'bucket': 'public', 'key': 'nav_bucket/bad.json',
           'sha256': 'not-a-sha256', 'write_id': wid(500), 'state': 'preparing'}
    tree.write(tree.journal_path('nav_bucket/bad.json'),
               json.dumps(bad, sort_keys=True))
    safe = r2_safe_write.SafeWriter(tree.api)

    with pytest.raises(r2_safe_write.UnsafeWrite, match='invalid payload reference'):
        with safe.storage_lock():
            safe.gc()
    for row in rows:
        assert tree.history_path(row['write_id']).exists()
        assert tree.payload_path(row['sha256']).exists()


def test_missing_referenced_payload_stops_whole_batch(tmp_path):
    """§6「缺引用整批停」: kept journal 引用的 payload 不在盘上 ⇒ 整批零删除(审查 P1-1)。"""
    tree = ProtectedTree(tmp_path)
    rows = _superseded(tree, 2)
    # 当前 confirmed journal(顶层)引用的 payload 缺失
    tree.payload_path(sha256_bytes(b'current')).unlink()
    safe = r2_safe_write.SafeWriter(tree.api)

    with pytest.raises(r2_safe_write.UnsafeWrite, match='payload reference missing'):
        with safe.storage_lock():
            safe.gc()
    for row in rows:
        assert tree.history_path(row['write_id']).exists()
        assert tree.payload_path(row['sha256']).exists()
    assert not (tree.root / 'gc-manifest.json').exists()


def test_missing_nonconfirmed_payload_only_warns(tmp_path, capsys):
    """口径锁定: nonconfirmed 锚点的 payload 缺失 = 协议内合法瞬态(prepare 先写引用后存 bytes /
    崩溃残留), 只打可观测告警并照常回收无引用文件, 不整批炸 —— 否则一条崩溃残留会让此后每次
    写入(store_many→gc)都失败 = 生产写入整体停摆。confirmed 行缺失才是硬失败(上一条用例)。"""
    tree = ProtectedTree(tmp_path)
    row = tree.add('nav_bucket/pending.json', b'never-stored', wid(600), state='unknown')
    tree.payload_path(row['sha256']).unlink()
    orphan = tree.root / 'payloads' / ('9' * 64)
    orphan.write_bytes(b'orphan')
    safe = r2_safe_write.SafeWriter(tree.api)

    with safe.storage_lock():
        safe.gc()

    assert tree.history_path(row['write_id']).exists()   # 恢复锚点保留
    assert not orphan.exists()                           # 无引用文件照常回收
    err = capsys.readouterr().err
    assert 'missing_nonconfirmed_payload' in err          # 缺失可观测, 不静默


def test_symlink_in_tree_refuses_gc_with_zero_deletion(tmp_path):
    """§6「symlink 整批停」: 树内任一 symlink ⇒ UnsafeWrite 零删除(审查 P1-2)。"""
    tree = ProtectedTree(tmp_path)
    rows = _superseded(tree, 2)
    link = tree.root / 'payloads' / ('d' * 64)
    link.symlink_to(tree.payload_path(rows[0]['sha256']))
    safe = r2_safe_write.SafeWriter(tree.api)

    with pytest.raises(r2_safe_write.UnsafeWrite, match='symlink'):
        with safe.storage_lock():
            safe.gc()
    assert link.is_symlink()
    for row in rows:
        assert tree.history_path(row['write_id']).exists()
        assert tree.payload_path(row['sha256']).exists()
    assert not (tree.root / 'gc-manifest.json').exists()


def test_file_identity_change_after_manifest_write_blocks_deletion(tmp_path, monkeypatch):
    tree = ProtectedTree(tmp_path)
    rows = _superseded(tree, 2)
    victim = tree.payload_path(rows[0]['sha256'])
    original = r2_safe_write.durable

    def hook(path, body):
        original(path, body)
        if path.name == 'gc-manifest.json':
            victim.write_bytes(b'tampered')   # 清单落盘后、unlink 前身份变化

    monkeypatch.setattr(r2_safe_write, 'durable', hook)
    safe = r2_safe_write.SafeWriter(tree.api)
    with pytest.raises(r2_safe_write.UnsafeWrite, match='file identity changed'):
        with safe.storage_lock():
            safe.gc()
    assert victim.exists() and victim.read_bytes() == b'tampered'
    for row in rows:
        assert tree.history_path(row['write_id']).exists()


def test_new_reference_file_after_plan_blocks_deletion(tmp_path, monkeypatch):
    tree = ProtectedTree(tmp_path)
    rows = _superseded(tree, 2)
    original = r2_safe_write.durable

    def hook(path, body):
        original(path, body)
        if path.name == 'gc-manifest.json':
            # 计划后出现新 journal(可能引用待删 payload) ⇒ 文件集变化 ⇒ 整批零删除
            tree.write(tree.root / 'history' / (wid(501) + '.json'),
                       json.dumps({'version': 1}, sort_keys=True))

    monkeypatch.setattr(r2_safe_write, 'durable', hook)
    safe = r2_safe_write.SafeWriter(tree.api)
    with pytest.raises(r2_safe_write.UnsafeWrite, match='file set changed'):
        with safe.storage_lock():
            safe.gc()
    for row in rows:
        assert tree.history_path(row['write_id']).exists()
        assert tree.payload_path(row['sha256']).exists()


def test_manifest_write_failure_zero_deletion(tmp_path, monkeypatch):
    tree = ProtectedTree(tmp_path)
    rows = _superseded(tree, 2)
    original = r2_safe_write.durable

    def fail(path, body):
        if path.name == 'gc-manifest.json':
            raise OSError(28, 'ENOSPC')
        original(path, body)

    monkeypatch.setattr(r2_safe_write, 'durable', fail)
    safe = r2_safe_write.SafeWriter(tree.api)
    with pytest.raises(OSError):
        with safe.storage_lock():
            safe.gc()
    for row in rows:
        assert tree.history_path(row['write_id']).exists()
        assert tree.payload_path(row['sha256']).exists()
    assert not (tree.root / 'gc-manifest.json').exists()


def test_lock_conflict_blocks_gc(tmp_path, monkeypatch):
    tree = ProtectedTree(tmp_path)
    rows = _superseded(tree, 2)
    now = [100.0]
    monkeypatch.setattr(r2_safe_write.time, 'monotonic', lambda: now[0])
    api = dict(tree.api)

    def sleep(_seconds):
        now[0] += 11.0   # 直接越过 10s 锁等待上限, 避免测试真等

    api['_work_sleep'] = sleep
    safe = r2_safe_write.SafeWriter(api)

    with open(tree.root / '.gc.lock', 'a+b') as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with pytest.raises(r2_safe_write.UnsafeWrite, match='storage lock timeout'):
                with safe.storage_lock():
                    pass
        finally:
            fcntl.flock(held, fcntl.LOCK_UN)

    for row in rows:
        assert tree.history_path(row['write_id']).exists()
        assert tree.payload_path(row['sha256']).exists()
    assert not (tree.root / 'gc-manifest.json').exists()
