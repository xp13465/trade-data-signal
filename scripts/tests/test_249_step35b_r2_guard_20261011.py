# -*- coding: utf-8 -*-
"""#249 回归测试: staticdata_backup_async.sh step3.5b R2 上传的「非生产机守卫」(2026-10-11)。

病灶(B3 执行报告 §6.7 / docs/ops/next-steps-b3-exec-20261011.md):
  step3.5b `upload_r2.py upload-large-json` 在写权限守卫(git 段, 段2)**之前**跑, 且属
  upload_r2.py `_PRIVATE_ONLY_CMDS`(本机允许)→ mac 若跑该脚本, 会把本机 staticdata 的
  large-json 目录(可能与云上正本代际不一致)gzip PUT 覆盖 signal-backup2 固定前缀唯一副本。
本测试守护修法 = 在 step3.5b 前加 `staticdata_write_guard.py --check-write-auth`(与 git 段
**同款判据/同风格提示**), 生产机 rc=0 原逻辑不动, 非生产机 rc=1 默认跳过。

隔离(全程零生产接触, §18 L48/L50):
  · REPO/GIT_REPO 指向 tmp_path 内**假仓库**: `scripts/` 目录整体换成 5 个桩
    (notify/with_lock/upload_r2 = 纯日志桩, 绝不真发/真上传; staticdata_write_guard/
    large_json_excludes = 真脚本或桩, 按用例)。
  · STATICDATA_REPO 指向 tmp_path 内独立 git 仓(非 /home/ubuntu/ → 守卫必判非生产机)。
  · notify 走桩(零邮件/零飞书/零网络); upload_r2 走桩(零 R2 接触) —— 桩是否被调用 = 外发证据点。
  · 绝不 exec 生产 staticdata 仓库 / 生产 R2; 假仓库 scripts 目录用桩 + 真 guard 只读判定。

四条用例:
  ① 判据纯函数(真 guard): /home/ubuntu/... → rc0 生产机; tmp 路径 → rc1 非生产机。
  ② 非生产机形态: 真 guard + tmp 仓库 → step3.5b **被拦**, upload 桩**零调用**(无外发证据)。
  ③ 生产机形态: guard 桩 rc=0(模拟云上) → step3.5b **过守卫**, upload 桩**被调用一次**(行为不变)。
  ④ 逃生门 + fail-closed: STATICDATA_ALLOW_R2_UPLOAD=1 放行; guard 异常 rc=2 → fail-closed 跳过。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
SCRIPT = SCRIPTS / "staticdata_backup_async.sh"
REAL_GUARD = SCRIPTS / "staticdata_write_guard.py"

pytestmark = pytest.mark.skipif(
    not all(shutil.which(x) for x in ("bash", "git", "rsync")),
    reason="需 bash/git/rsync(CI ubuntu 具备); 缺失即跳过, 不假绿(§18 L49)",
)

# ── 桩脚本源码(纯日志, 零外发) ──
_FAKE_NOTIFY = """\
import os, sys
with open(os.environ["SB_NOTIFY_LOG"], "a", encoding="utf-8") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\\n")
sys.exit(0)
"""
_FAKE_UPLOAD = """\
import os, sys
with open(os.environ["SB_UPLOAD_LOG"], "a", encoding="utf-8") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\\n")
print("fake upload_r2 upload-large-json invoked")
sys.exit(0)
"""
_FAKE_WITHLOCK = """\
import os, sys
with open(os.environ["SB_WITHLOCK_LOG"], "a", encoding="utf-8") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
i = 0
while i < len(args) and args[i].startswith("-"):
    i += 2 if args[i] in ("--block-timeout", "--timeout", "--wait") else 1
i += 1  # skip lock path
cmd = args[i:]
os.execvp(cmd[0], cmd)
"""
# guard 桩: 按 SB_FAKE_GUARD_RC_SEQ 逐次返回(逗号分隔, 用尽后沿用最后一个)。
_FAKE_GUARD = """\
import os, sys
seq = os.environ.get("SB_FAKE_GUARD_RC_SEQ", "0")
vals = [v for v in seq.split(",") if v != ""] or ["0"]
state = os.environ.get("SB_FAKE_GUARD_STATE")
idx = 0
if state and os.path.exists(state):
    idx = int(open(state).read().strip() or "0")
rc = int(vals[idx]) if idx < len(vals) else int(vals[-1])
if state:
    open(state, "w").write(str(idx + 1))
print("[fake guard] rc=%d" % rc, file=sys.stderr)
sys.exit(rc)
"""


def _git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _mk_env(base: Path, guard_kind: str, guard_seq: str = "0"):
    """造 tmp 假仓库(REPO==GIT_REPO)+ 独立 staticdata git 仓 + 桩 scripts; 返回 (env, sd, logs)。"""
    repo = base / "fake-repo"
    (repo / "data" / "logs").mkdir(parents=True)
    (repo / "data" / "dummy.db").write_text("db", encoding="utf-8")
    (repo / "static-site" / "data").mkdir(parents=True)
    (repo / "static-site" / "data" / "dummy.json").write_text("{}", encoding="utf-8")
    venv_bin = repo / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").symlink_to(sys.executable)

    stub = base / "stub-scripts"
    stub.mkdir()
    (stub / "notify.py").write_text(_FAKE_NOTIFY, encoding="utf-8")
    (stub / "upload_r2.py").write_text(_FAKE_UPLOAD, encoding="utf-8")
    (stub / "with_lock.py").write_text(_FAKE_WITHLOCK, encoding="utf-8")
    if guard_kind == "real":
        (stub / "staticdata_write_guard.py").symlink_to(REAL_GUARD)
    else:
        (stub / "staticdata_write_guard.py").write_text(_FAKE_GUARD, encoding="utf-8")
    # large_json_excludes 用真脚本(stdlib only; 生产同款, 保证 .gitignore 受管区块行为一致)
    (stub / "large_json_excludes.py").symlink_to(SCRIPTS / "large_json_excludes.py")
    (repo / "scripts").symlink_to(stub, target_is_directory=True)

    # 独立 staticdata git 仓(带一个 base commit + 裸远端, 供生产机形态 push)
    remote = base / "remote.git"
    _git("init", "--bare", "-q", str(remote))
    sd = base / "sd-repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(sd)], check=True, capture_output=True)
    _git("-C", str(sd), "config", "user.email", "t@example.com")
    _git("-C", str(sd), "config", "user.name", "t")
    (sd / "data").mkdir()
    (sd / "data" / "base.json").write_text("base", encoding="utf-8")
    _git("-C", str(sd), "add", "-A")
    _git("-C", str(sd), "commit", "-q", "-m", "base")
    _git("-C", str(sd), "remote", "add", "origin", str(remote))
    _git("-C", str(sd), "push", "-q", "-u", "origin", "main")

    logs = {
        "notify": base / "notify.log",
        "upload": base / "upload.log",
        "withlock": base / "withlock.log",
        "guard_state": base / "guard.state",
    }
    env = dict(os.environ)
    for k in ("STATICDATA_ALLOW_PUSH", "STATICDATA_ALLOW_R2_UPLOAD",
              "STATICDATA_BACKUP_SKIP_R2_UPLOAD", "STATICDATA_BACKUP_ASYNC_R2_DONE",
              "STATICDATA_BACKUP_NOTIFY_DRY_RUN"):
        env.pop(k, None)
    env.update({
        "REPO": str(repo), "GIT_REPO": str(repo), "PY": sys.executable,
        "STATICDATA_REPO": str(sd),
        "STATICDATA_BACKUP_NOTIFY_DRY_RUN": "1",  # 双保险: 即便通知桩失效也不真发
        "SB_NOTIFY_LOG": str(logs["notify"]), "SB_UPLOAD_LOG": str(logs["upload"]),
        "SB_WITHLOCK_LOG": str(logs["withlock"]), "SB_FAKE_GUARD_STATE": str(logs["guard_state"]),
        "SB_FAKE_GUARD_RC_SEQ": guard_seq,
    })
    return env, sd, logs


def _run(env, extra=None):
    e = dict(env)
    if extra:
        e.update(extra)
    return subprocess.run(["bash", str(SCRIPT), "test-249"], env=e, cwd=str(REPO),
                          capture_output=True, text=True, timeout=180)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _heartbeat(base_repo: Path) -> str:
    return (base_repo / "data" / "staticdata_backup_heartbeat.json").read_text(encoding="utf-8")


# ① 判据纯函数(真 guard)
def test_judge_unit_prod_vs_nonprod(tmp_path):
    prod = subprocess.run([sys.executable, str(REAL_GUARD), "--check-write-auth",
                           "--repo", "/home/ubuntu/code/trade-data-signal-staticdata"],
                          capture_output=True, text=True)
    assert prod.returncode == 0 and "生产机" in prod.stderr
    local = subprocess.run([sys.executable, str(REAL_GUARD), "--check-write-auth",
                            "--repo", str(tmp_path)],
                           capture_output=True, text=True)
    assert local.returncode == 1 and "非生产机" in local.stderr


# ② 非生产机形态: 真 guard + tmp 仓库 → step3.5b 被拦, upload 桩零调用(无外发证据)
def test_nonprod_blocks_r2_upload(tmp_path):
    env, sd, logs = _mk_env(tmp_path, guard_kind="real")
    p = _run(env)
    assert "跳过(非生产机守卫拦截" in p.stdout, p.stdout[-3000:]
    assert _read(logs["upload"]) == "", f"非生产机仍触发了 upload_r2: {_read(logs['upload'])!r}"
    assert "staticdata_backup_r2_nonprod_skip" in _read(logs["notify"])
    assert '"result":"skip_nonprod"' in _heartbeat(tmp_path / "fake-repo")
    assert p.returncode == 0


# ③ 生产机形态: guard 桩 rc=0(模拟云上) → step3.5b 过守卫, upload 桩被调用一次(行为不变)
def test_prod_passes_r2_upload(tmp_path):
    env, sd, logs = _mk_env(tmp_path, guard_kind="stub", guard_seq="0")
    p = _run(env)
    up = _read(logs["upload"])
    assert "upload-large-json" in up, f"生产机形态下 upload_r2 未被调用; stdout={p.stdout[-3000:]}"
    assert up.count("upload-large-json") == 1
    assert "staticdata_backup_r2_nonprod_skip" not in _read(logs["notify"])


# ④a 逃生门: 非生产机 + STATICDATA_ALLOW_R2_UPLOAD=1 → 放行(仍非生产机, git 段仍拦)
def test_nonprod_escape_hatch_allows_upload(tmp_path):
    env, sd, logs = _mk_env(tmp_path, guard_kind="real")
    p = _run(env, {"STATICDATA_ALLOW_R2_UPLOAD": "1"})
    assert "显式放行" in p.stdout, p.stdout[-3000:]
    assert "upload-large-json" in _read(logs["upload"])


# ④b fail-closed: R2 守卫判定异常(rc=2) → 跳过上传 + 置 FAIL(收口 exit 1)
def test_guard_error_fails_closed(tmp_path):
    # 段1 首次调用 rc=2(R2 守卫) → 段2 第二次调用 rc=1(禁 git 段, 免 push 干扰)
    env, sd, logs = _mk_env(tmp_path, guard_kind="stub", guard_seq="2,1")
    p = _run(env)
    assert _read(logs["upload"]) == "", "守卫异常时仍上传了(非 fail-closed)"
    assert "fail-closed 跳过 R2 上传" in p.stdout, p.stdout[-3000:]
    assert p.returncode == 1, p.stdout[-3000:]  # STATICDATA_FAIL=1 → 收口 severe 分支 exit 1