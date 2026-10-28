# -*- coding: utf-8 -*-
"""腾磁盘第一批的三处改动守卫(2026-10-28, 任务 #322 / docs/ops/disk-reclaim-20261028.md)。

背景(实测, 见 docs/ops/system-health-audit-20261028.md §P0-3 与 /tmp/disk-reclaim-plan-20261028.md):
云上 59G 盘只剩 13G, 三个全量库副本:
  - 代码仓 `trade-data-signal/data/*.db` 3.5G —— 零读取方, 却被每次部署 rsync 全量复制;
  - 灾备仓 `trade-data-signal-staticdata/db/` 3.4G —— 全仓零读取方, 恢复一律走 R2;
  - 主库 `trade-data/data/*.db` —— 唯一活副本。
两处重复副本停掉后 `stock_daily.db`(183MB)只剩主库一份, 而 backup_db.sh / upload-db
清单里都没有它 ⇒ 必须先补进备份链, 否则盘毁即全失。

本文件守的 5 条(源码形状守卫 + 1 条行为守卫):
  ① deploy.sh 的 data rsync 含 *.db / *.db-wal / *.db-shm 三项排除, 且日志文案不再自称「DB 同步」;
  ② deploy.sh 里没有别的「把 *.db 搬进 $GIT_REPO」语句(rsync 必须带 DB 排除; cp/mv 不许搬 .db);
  ③ staticdata_backup_async.sh 的 DB rsync 被 STATICDATA_DB_LOCAL_COPY 门控(默认跳过, =1 才跑);
  ④ backup_db.sh 本地热备清单含 stock_daily.db;
  ⑤ upload_r2.py 的 upload-db 清单含 ("stock_daily.db", "stock_daily")(按 ast 取 targets 实值)。

零执行: 不跑 deploy.sh / staticdata_backup_async.sh / backup_db.sh, 不碰网络。③ 的行为守卫
只把源码里那一段 if 块**抽出来**喂给 bash(带假 rsync), 不 source 整个业务脚本(§18 L50)。
"""
from __future__ import annotations

import ast
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
DEPLOY = SCRIPTS / "deploy.sh"
STATICDATA = SCRIPTS / "staticdata_backup_async.sh"
BACKUP_DB = SCRIPTS / "backup_db.sh"
UPLOAD_R2 = SCRIPTS / "upload_r2.py"

DB_EXCLUDES = ("--exclude='*.db'", "--exclude='*.db-wal'", "--exclude='*.db-shm'")


# ── 公共: 把脚本拆成「逻辑命令」(行尾反斜杠续行合并) ────────────────────────
def _logical_commands(text: str, suffix: str = ".sh") -> list[str]:
    out: list[str] = []
    buf = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if not buf and (line.lstrip().startswith("#") or not line.strip()):
            continue
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        buf += line
        if buf.strip():
            out.append(buf.strip())
        buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out


def _rsync_into_git_repo(text: str) -> list[str]:
    """所有目标为 $GIT_REPO/data/ 的 rsync 逻辑命令。"""
    hits = []
    for cmd in _logical_commands(text):
        if not re.search(r"(^|\s)(sudo\s+)?rsync\b", cmd):
            continue
        if "$GIT_REPO/data/" not in cmd:
            continue
        hits.append(cmd)
    return hits


# ── ① deploy.sh data rsync 带三项 DB 排除 + 日志文案已改 ────────────────────
def test_c1_deploy_rsync_excludes_db():
    text = DEPLOY.read_text(encoding="utf-8")
    datas = [c for c in _rsync_into_git_repo(text) if '"$REPO/data/"' in c]
    assert len(datas) == 1, f"应恰有 1 条 $REPO/data/ -> $GIT_REPO/data/ 的 rsync, 实际 {len(datas)} 条"
    cmd = datas[0]
    for exc in DB_EXCLUDES:
        assert exc in cmd, f"data rsync 缺排除项 {exc}; 实文: {cmd}"
    # 防误伤: 原有 4 个 clone 种子排除必须还在(本改动只加不删)
    for exc in ("--exclude=trade.db", "--exclude=trade_dates.txt",
                "--exclude=index_etf_map.json", "--exclude=stock_codes.json"):
        assert exc in cmd, f"原有 clone 种子排除 {exc} 被误删; 实文: {cmd}"

    # 日志文案: 不再自称「DB 同步到」(验收用例 V3 要 grep 这条)
    assert "DB 同步到" not in text, "deploy.sh 日志文案仍有「DB 同步到」(与「不再复制 DB」矛盾)"
    assert "不含 DB" in text, "deploy.sh 完成日志应写明不含 DB"


# ── ② 没有第二处把 *.db 搬进 $GIT_REPO ──────────────────────────────────────
def test_c2_no_other_db_copy_into_git_repo():
    text = DEPLOY.read_text(encoding="utf-8")
    md5_only = ("hashlib", "md5", "sha", "stat ", "ls ", "test ")   # 只读校验类, 允许出现路径
    offenders = []
    for cmd in _logical_commands(text):
        if "$GIT_REPO/data" not in cmd:
            continue
        is_rsync = bool(re.search(r"(^|\s)(sudo\s+)?rsync\b", cmd))
        is_cp = bool(re.search(r"(^|\s)(sudo\s+)?(cp|mv|install|tar)\b", cmd))
        if is_rsync:
            if '"$GIT_REPO/data/"' in cmd and not all(e in cmd for e in DB_EXCLUDES):
                offenders.append(cmd)
        elif is_cp:
            # cp/mv 只许搬 JSON(双树单源 board_etf_map.json); 任何 .db 源都算漏网
            if re.search(r"[\w./-]+\.db(['\"]|\s|$)", cmd) or "*.db" in cmd:
                offenders.append(cmd)
        else:
            # 其余(md5/stat/echo 判定)允许读过路径, 但若同时出现搬库动作关键字则排查
            if any(k in cmd for k in md5_only):
                continue
    assert not offenders, "deploy.sh 另有把 *.db 搬进 $GIT_REPO 的语句:\n" + "\n".join(offenders)


# ── ③ staticdata DB rsync 被 STATICDATA_DB_LOCAL_COPY 门控 ─────────────────
def _step1_block() -> str:
    """抽取 staticdata_backup_async.sh 的「# 1. rsync DB原件 ... fi」整块(不 source 全脚本)。"""
    lines = STATICDATA.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("# 1. rsync DB原件"))
    for j in range(start, len(lines)):
        if lines[j].strip() == "fi":
            return "\n".join(lines[start:j + 1])
    raise AssertionError("staticdata step1 段落找不到收尾 fi")


def test_c3_staticdata_db_rsync_gated():
    block = _step1_block()
    assert 'if [ "${STATICDATA_DB_LOCAL_COPY:-0}" = "1" ]; then' in block, \
        "DB rsync 必须被 STATICDATA_DB_LOCAL_COPY 门控且默认 0(关)"
    # 门控之后必须仍有 skipped 日志(心跳/步耗时结论可读, 不静默)
    assert "skipped" in block and "STATICDATA_DB_LOCAL_COPY=1" in block, \
        "跳过时须打一行 skipped 并写明开关名"
    # 未闭合误置失败: STATICDATA_FAIL=1 只在门内(=1 分支)出现
    assert block.count("STATICDATA_FAIL=1") == 1

    # 行为守卫: 只跑这一块 + 假 rsync, 证「默认不执行 / =1 才执行」
    # 临时目录放系统 /tmp(不放 tests/ 下): 中途失败也不在仓库里留垃圾
    tmp = Path(tempfile.mkdtemp(prefix="step1-harness-"))
    try:
        fake_bin = tmp / "bin"
        fake_bin.mkdir()
        marker = tmp / "rsync_called"
        rsync = fake_bin / "rsync"
        rsync.write_text(f'#!/usr/bin/env bash\necho "$@" >> "{marker}"\n', encoding="utf-8")
        rsync.chmod(0o755)

        script = (
            "set -u\n"
            f'LOG="{tmp}/log.txt"\n'
            f'REPO="{tmp}/repo"\n'
            f'STATICDATA_REPO="{tmp}/sd"\n'
            "STATICDATA_FAIL=0\n"
            f"{block}\n"
            'echo "FAIL_FLAG=$STATICDATA_FAIL"\n'
        )
        env_default = {"PATH": f"{fake_bin}:/usr/bin:/bin"}
        r = subprocess.run(["bash", "-s"], input=script, text=True, capture_output=True,
                           env=env_default, timeout=60)
        assert r.returncode == 0, r.stderr
        assert not marker.exists(), "默认(未设开关)不应调用 rsync"
        assert "FAIL_FLAG=0" in r.stdout, "跳过时不得把 STATICDATA_FAIL 置 1"
        assert "skipped" in r.stdout

        env_on = {"PATH": f"{fake_bin}:/usr/bin:/bin", "STATICDATA_DB_LOCAL_COPY": "1"}
        r2 = subprocess.run(["bash", "-s"], input=script, text=True, capture_output=True,
                            env=env_on, timeout=60)
        assert r2.returncode == 0, r2.stderr
        assert marker.exists(), "STATICDATA_DB_LOCAL_COPY=1 时应调用 rsync(逃生门可用)"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── ④ backup_db.sh 本地热备含 stock_daily.db ────────────────────────────────
def test_c4_backup_db_includes_stock_daily():
    text = BACKUP_DB.read_text(encoding="utf-8")
    calls = [ln.strip() for ln in text.splitlines()
             if ln.strip().startswith("backup_one ") and not ln.strip().startswith("backup_one()")]
    names = [c for c in calls if "stock_daily.db" in c]
    assert len(names) == 1, f"backup_db.sh 应恰有 1 条 stock_daily.db 热备调用, 实文: {calls}"
    # 形态照抄 etf_national_team 那条: 失败也要置 RC=1(不能静默跳过失败)
    assert "|| RC=1" in names[0], f"stock_daily 备份失败须计入退出码: {names[0]}"
    assert 'sentiment.db' in text and 'etf_national_team.db' in text, "原有两库热备不得被替换"


# ── ⑤ upload_r2.py upload-db 清单含 stock_daily ────────────────────────────
def _upload_db_targets() -> list[tuple[str, str]]:
    tree = ast.parse(UPLOAD_R2.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "cmd_upload_db":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id == "targets" for t in sub.targets):
                    return ast.literal_eval(sub.value)
    raise AssertionError("upload_r2.py cmd_upload_db 里找不到 targets 清单")


def test_c5_upload_db_includes_stock_daily():
    targets = _upload_db_targets()
    assert ("stock_daily.db", "stock_daily") in targets, f"upload-db 清单缺 stock_daily: {targets}"
    assert ("sentiment.db", "sentiment") in targets
    assert ("etf_national_team.db", "etf_national_team") in targets
    # 保留天数不动(per_name_days 只覆盖 public_fund 大库)
    src = UPLOAD_R2.read_text(encoding="utf-8")
    assert "_PUBLIC_FUND_RETENTION_DAYS" in src
    m = re.search(r"_PUBLIC_FUND_RETENTION_DAYS\s*=\s*\{(.*?)\}", src, re.S)
    assert m, "找不到 _PUBLIC_FUND_RETENTION_DAYS 常量"
    body = m.group(1)
    assert "stock_daily" not in body, "stock_daily 不应另立保留期(沿用默认 14/28/365, 天数不动)"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))