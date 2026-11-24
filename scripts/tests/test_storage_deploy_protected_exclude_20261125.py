# -*- coding: utf-8 -*-
"""2026-11-25 存储治理块1: deploy.sh 数据镜像 rsync 精确排除 .r2-protected/(方案 §3.1)。

病灶(11-25 复核 §5 实证): 每趟 deploy 把 REPO/data/.r2-protected(protected 本地恢复锚点)
rsync 抄进代码仓 GIT_REPO/data/ 且不带 --delete ⇒ 目标树副本永不清理、下次再抄一遍
(C 根 9286 文件/10.68GB 只进不出, GC 卡死)。

修法边界: 只加 `--exclude=.r2-protected/` 一条精确排除; 不加全目录 --delete(会连带删
目标树正常 JSON/parquet 镜像); 不取消任何现有 DB/JSON/parquet 镜像排除。

测试方式(禁真跑 deploy, §18 L50):
  ① 从 deploy.sh 源码抽「逻辑命令」(续行合并), 锁定排除项与无 --delete;
  ② 把抽出的那条 rsync **原样**喂给 bash, 目标/源都是 /tmp 夹具 —— 先 dry-run 断言
     protected 不会被列出、正常 JSON/parquet 会被列出; 再真跑断言复制结果。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from test_253_disk_reclaim_20261028 import _rsync_into_git_repo

SCRIPTS = Path(__file__).resolve().parents[1]
DEPLOY = SCRIPTS / 'deploy.sh'
EXCLUDE = '--exclude=.r2-protected/'


def _data_mirror_rsync() -> str:
    """deploy.sh 中 REPO/data -> GIT_REPO/data 的那一条 rsync(去掉 tee 管道)。"""
    cmds = [c for c in _rsync_into_git_repo(DEPLOY.read_text(encoding='utf-8'))
            if '"$REPO/data/"' in c]
    assert len(cmds) == 1, f'应恰有 1 条 $REPO/data/ -> $GIT_REPO/data/ rsync, 实际 {len(cmds)}'
    return cmds[0].split(' 2>&1')[0]


def _run(cmd, tmp_path, with_dry_run=False):
    env = {
        'PATH': '/usr/bin:/bin:/usr/local/bin',
        'REPO': str(tmp_path),
        'GIT_REPO': str(tmp_path / 'git'),
        'LOG': str(tmp_path / 'deploy.log'),
    }
    if with_dry_run:
        cmd = cmd.replace('rsync -a ', 'rsync -a -n -i ', 1)
    return subprocess.run(['bash', '-c', cmd], env=env, capture_output=True,
                          text=True, timeout=60)


def test_mirror_rsync_excludes_protected_without_delete():
    cmd = _data_mirror_rsync()
    assert EXCLUDE in cmd
    assert '--delete' not in cmd, '禁开全目录 --delete(会删目标树正常镜像)'
    # 原有镜像排除不能因本改动被误删(test_253 守 DB 三件; 这里补 JSON 侧关键项)
    for keep in ('--exclude=logs/', "--exclude='*.db'", '--exclude=alerts/',
                 '--exclude=backups/', '--exclude=index_etf_map.json'):
        assert keep in cmd, f'原有排除 {keep} 被误删; 实文: {cmd}'


def test_fixture_protected_not_copied_normal_mirror_kept(tmp_path):
    cmd = _data_mirror_rsync()
    src = tmp_path / 'data'
    dst = tmp_path / 'git' / 'data'
    (src / '.r2-protected' / 'history').mkdir(parents=True)
    (src / '.r2-protected' / 'gc-manifest.json').write_text('{"keep": []}')
    (src / '.r2-protected' / 'history' / 'j.json').write_text('{"key": "nav_bucket/1.json"}')
    (src / '.r2-protected' / 'payloads').mkdir()
    (src / '.r2-protected' / 'payloads' / ('a' * 64)).write_bytes(b'PAYLOAD')
    (src / 'normal.json').write_text('{"a": 1}')
    (src / 'hist.parquet').write_bytes(b'PAR1')
    (src / 'nested').mkdir()
    (src / 'nested' / 'x.json').write_text('{"b": 2}')
    dst.mkdir(parents=True)
    # 目标树预置旧 protected 副本: 本改动不加 --delete ⇒ 旧副本原地保留(由 A 阶段治理)
    (dst / '.r2-protected').mkdir()
    (dst / '.r2-protected' / 'stale.json').write_text('{"stale": 1}')

    dry = _run(cmd, tmp_path, with_dry_run=True)
    assert dry.returncode == 0, dry.stderr
    assert '.r2-protected' not in dry.stdout, f'dry-run 仍列出 protected: {dry.stdout!r}'
    for name in ('normal.json', 'hist.parquet', 'nested/x.json'):
        assert name in dry.stdout, f'dry-run 缺正常镜像 {name}: {dry.stdout!r}'

    real = _run(cmd, tmp_path)
    assert real.returncode == 0, real.stderr
    assert not (dst / '.r2-protected' / 'history').exists()
    assert not (dst / '.r2-protected' / 'payloads').exists()
    assert (dst / '.r2-protected' / 'stale.json').exists()   # 无 --delete: 旧副本不被删
    assert (dst / 'normal.json').read_text() == '{"a": 1}'
    assert (dst / 'hist.parquet').read_bytes() == b'PAR1'
    assert (dst / 'nested' / 'x.json').read_text() == '{"b": 2}'
