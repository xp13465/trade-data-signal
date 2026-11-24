# -*- coding: utf-8 -*-
"""2026-11-25 存储治理块2: protected GC 保守保留全部 nonconfirmed 历史。

方案依据(/tmp/codex-reports/claude-storage-cleanup-20261124-execution-plan.md §3.2)+
11-25 复核(/tmp/storage-recheck-20261125.md §3): 旧 gc 只保留 unknown/pending_purge/
非 confirmed pair, 55 条 plain preparing 历史及其 old_sha256 payload(103 个/0.29GiB)
落在可删集合; 修法 = 普遍保留 state != confirmed 的全部历史, 其 new/old payload 与 pair
由既有引用闭包递归保住。禁 HISTORY_KEEP=0、禁改写状态。

判据: ①preparing/plain/unknown(pending_purge)/failed 的历史文件 + payload 全保留;
②pair 两件与 pair manifest 保留(非 confirmed 场景); ③已终结且被取代的 confirmed 仍按
HISTORY_KEEP 回收(证明不是「永不删」); ④HISTORY_KEEP=0 也不能丢 nonconfirmed、状态不被改写。
全部临时目录, 不碰生产数据、不发通知、不触网。时点固定历史 epoch(L51)。
"""
from __future__ import annotations

import json

import pytest

import r2_safe_write
from _storage_mechfix_fixture_20261125 import BASE_MTIME, PAIR, ProtectedTree, pid, wid


def _gc(tree, monkeypatch=None):
    safe = r2_safe_write.SafeWriter(tree.api)
    with safe.storage_lock():
        return safe.gc(), safe


def test_all_nonconfirmed_states_hold_with_payloads_and_pair(tmp_path):
    tree = ProtectedTree(tmp_path)
    prep = tree.add('nav_bucket/prep.json', b'prep-new', wid(1),
                    state='preparing', old_body=b'prep-old')
    plain = tree.add('nav_bucket/plain.json', b'plain-new', wid(2),
                     state='plain', old_body=b'plain-old')
    unk = tree.add('nav_bucket/unk.json', b'unk-new', wid(3),
                   state='unknown', pending_purge=True)
    failed = tree.add('nav_bucket/fail.json', b'fail-new', wid(4),
                      state='failed', old_body=b'fail-old')
    pair_id = pid(50)
    pair_rows = tree.add_pair(pair_id,
                              {PAIR[0]: b'pair-main', PAIR[1]: b'pair-ext'},
                              {PAIR[0]: wid(5), PAIR[1]: wid(6)}, state='prepared')
    # 已终结且被取代的 confirmed(旧点应被回收, 证明保留不是无上限)
    superseded = tree.add('nav_bucket/done.json', b'done-old', wid(7),
                          top_level=False, mtime=BASE_MTIME)
    tree.add('nav_bucket/done.json', b'done-new', wid(8), mtime=BASE_MTIME + 100)

    kept, safe = _gc(tree)

    for row in (prep, plain, unk, failed, *pair_rows.values()):
        assert tree.history_path(row['write_id']).exists(), row
        assert tree.payload_path(row['sha256']).exists(), row
        if row.get('old_sha256'):
            assert tree.payload_path(row['old_sha256']).exists(), row
    assert (tree.root / 'pairs' / (pair_id + '.json')).exists()
    # 旧 confirmed 历史与其 payload 仍可回收(只保留最新一个 confirmed)
    assert not tree.history_path(superseded['write_id']).exists()
    assert not tree.payload_path(superseded['sha256']).exists()
    # 清单必须与现存文件对齐(keep 里每个路径都存在)
    manifest = json.loads((tree.root / 'gc-manifest.json').read_text())
    assert all((tree.root / rel).exists() for rel in manifest['keep'])
    # 状态不得被改写(保守保留 ≠ 造假状态)
    assert json.loads(tree.history_path(prep['write_id']).read_text())['state'] == 'preparing'
    assert json.loads(tree.history_path(plain['write_id']).read_text())['state'] == 'plain'


def test_history_keep_zero_cannot_drop_nonconfirmed_or_rewrite_state(tmp_path, monkeypatch):
    tree = ProtectedTree(tmp_path)
    prep = tree.add('nav_bucket/prep.json', b'prep-new', wid(11),
                    state='preparing', old_body=b'prep-old')
    superseded = tree.add('nav_bucket/done.json', b'done-old', wid(12),
                          top_level=False, mtime=BASE_MTIME)
    latest = tree.add('nav_bucket/done.json', b'done-new', wid(13), mtime=BASE_MTIME + 100)
    monkeypatch.setenv('R2_PROTECTED_HISTORY_KEEP', '0')

    _gc(tree, monkeypatch)

    assert tree.history_path(prep['write_id']).exists()
    assert tree.payload_path(prep['sha256']).exists()
    assert tree.payload_path(prep['old_sha256']).exists()
    assert json.loads(tree.history_path(prep['write_id']).read_text())['state'] == 'preparing'
    # count=0 时被取代的 confirmed 历史可回收; 当前顶层 journal 的 history 仍由引用闭包保住
    assert not tree.history_path(superseded['write_id']).exists()
    assert not tree.payload_path(superseded['sha256']).exists()
    assert tree.journal_path('nav_bucket/done.json').exists()
    assert tree.history_path(latest['write_id']).exists()
    assert tree.payload_path(latest['sha256']).exists()


def test_history_keep_out_of_range_still_rejected(tmp_path, monkeypatch):
    """禁 HISTORY_KEEP=0 造假: 允许 0, 但越界(>16)仍拒(既有契约不变)。"""
    tree = ProtectedTree(tmp_path)
    tree.add('nav_bucket/a.json', b'a', wid(21))
    safe = r2_safe_write.SafeWriter(tree.api)
    monkeypatch.setenv('R2_PROTECTED_HISTORY_KEEP', '17')
    with pytest.raises(r2_safe_write.UnsafeWrite):
        with safe.storage_lock():
            safe.gc()
