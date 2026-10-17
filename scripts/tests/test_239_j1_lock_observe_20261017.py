# -*- coding: utf-8 -*-
"""#239-J1 自测: 等锁可观测性(2026-10-17)。

权威规格 = docs/ops/next-steps-b4a-cloud-20261011.md §3(四点机检口径)+ 派单任务书 A 段;
实施报告 = /tmp/upload-j1c1-report.md。
被测面 = `scripts/r2_upload_async.sh` 的 #239-J1 段(_mirror_lock_heartbeat 镜像 + run_r2_upload
  包装层「等锁统计」累加 + 收尾 banner 两指标)+ `scripts/upload_r2.py::_acquire_r2_upload_lock`
  的排队心跳文案(跨文件字面量契约)。

背景(为什么做的可证伪依据): 止血步(#239, 10-09)把等锁心跳只打到 stderr → 落 tmp_log, 而
  成功轮 tmp_log 只 `tail -1` 进主日志后 rm ⇒ 生产日志里「等待 R2 上传锁」0 命中
  (b4a §3 云上 16 轮 grep 实证), 「没等到锁」与「等到但靠心跳逃生」不可区分。

§18 L50(探针一律 static-only): 本测试**绝不 source/exec `r2_upload_async.sh` 主体**
  (主体一跑就真发 R2 上传)。判据经**函数体抽取**(`_extract_func`, 按行首 `}` 闭合)落到临时
  fixture 再 `bash -s` source —— 只执行被抽出的**纯可见性函数**(只 grep 文件 + echo), 零网络/
  零 R2/零落盘(除测试自己的 tmp LOG)。抽取在 test 函数体内做(模块级只放纯 helper)。

自测零外发证据(本文件内机检):
  - `test_harness_is_side_effect_free` 断言抽出的函数体不含任何上传/外发调用(`upload_r2.py` /
    `"$PY"` / rclone / aws / curl);
  - 唯一外部命令 = `grep`/`tail`(只读 tmp 文件)。

跑法: python3 -m pytest -q scripts/tests/test_239_j1_lock_observe_20261017.py
"""
import fcntl
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
R2SH = ROOT / "scripts" / "r2_upload_async.sh"
UR_PY = ROOT / "scripts" / "upload_r2.py"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import upload_r2 as ur  # noqa: E402  (顶层 load_env 由 conftest .env 垫片兜住)


# ── 纯 helper(模块级, 无副作用)────────────────────────────────────────────
def _extract_func(src: str, name: str) -> str:
    """从 shell 源里抽出 `name() { ... }` 函数体(行首 `}` 闭合; 本文件两个目标函数内无裸 `}`)。"""
    lines = src.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith(f"{name}() {{")), None)
    assert start is not None, f"未找到函数 {name}()"
    end = next((j for j in range(start + 1, len(lines)) if lines[j] == "}"), None)
    assert end is not None, f"函数 {name}() 未闭合"
    return "\n".join(lines[start:end + 1])


def _build_harness(mirror_src: str, wrapper_src: str, log_path: Path) -> str:
    """拼测试壳: 常量 + 两个被抽出的函数 + 一个**桩** `_run_r2_upload_impl`(绝不碰真上传)。"""
    return "\n".join([
        "set -u",
        f'LOG="{log_path}"',
        "_LOCK_BEAT_MIRROR_SECS=300",
        "R2_LOCK_WAIT_N=0 R2_LOCK_WAIT_MAX=0 R2_LOCK_WAIT_LAST=0",
        "_LOCK_BEAT_AT=0 _LOCK_BEAT_LOGGED=0",
        mirror_src,
        wrapper_src,
        '_run_r2_upload_impl() { R2_LOCK_WAIT_LAST="${2:-0}"; return "${3:-0}"; }',
        "true",
    ]) + "\n"


def _bash(harness: str, expr: str, log_path: Path):
    """跑 harness+expr, 返回 (CompletedProcess, 主日志内容)。"""
    r = subprocess.run(["bash", "-s"], input=harness + expr + "\ntrue\n",
                       capture_output=True, text=True, timeout=60)
    log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    return r, log


def _hold_lock(path: Path):
    """同进程内以 LOCK_EX 持锁(flock 对不同 fd 互斥, 可同进程模拟占用)。"""
    f = open(path, "w")
    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    return f


# ── ① 静态: 停滞判据 vs R2_UPLOAD_HTTP_TIMEOUT 梯度防倒置护栏 ────────────────
def test_stall_vs_http_gradient_guard_intact():
    """① 梯度防倒置护栏在位: 停滞阈值 ≤ 内层 HTTP 超时 ⇒ 自动抬到 HTTP+300, 默认 900。"""
    s = R2SH.read_text(encoding="utf-8")
    impl = _extract_func(s, "_run_r2_upload_impl")
    assert 'local _http_to="${R2_UPLOAD_HTTP_TIMEOUT:-30}"' in impl, "内层 HTTP 超时读值丢失"
    assert 'local _stall_secs="${R2_UPLOAD_STALL_SECS:-900}"' in impl, "停滞阈值默认 900 丢失"
    assert 'if [ "$_stall_secs" -le "$_http_to" ]; then' in impl, "梯度倒置判定分支丢失"
    assert '_stall_secs=$((_http_to + 300))' in impl, "自动抬升 +300 丢失(倒置会回归)"
    assert '自动抬到 $((_http_to + 300))s' in impl, "抬升动作未留痕(不可观测)"
    # 7200s 硬兜底仍在
    assert '[ "$_slept" -ge 7200 ]' in impl, "7200s 硬兜底丢失"


# ── ② 静态: 排队分支行为(默认排队 + 字面量契约 + 未动锁语义) ─────────────────
def test_queue_branch_static_contract():
    """② 排队分支: 默认排队(无 skip), 心跳文案前缀 = 镜像 grep 锚点(跨文件契约), 阈值 30s。"""
    s = R2SH.read_text(encoding="utf-8")
    p = UR_PY.read_text(encoding="utf-8")
    # 默认排队: 只读/单文件小命令豁免, 其余持锁排队; skip 仅在显式 flag 下生效
    assert 'if cmd and cmd not in {"list", "delete", "download-db", "clean-data-backup", "upload"}:' in p
    assert "_acquire_r2_upload_lock(skip_if_locked=_SKIP_IF_LOCKED)" in p, "排队分支接线丢失"
    # 跨文件字面量契约: 镜像函数 grep 的锚点必须仍是生产心跳的文案前缀
    assert "等待 R2 上传锁" in p, "生产心跳文案漂移(镜像会静默失效)"
    assert re.search(r"等待 R2 上传锁 \{int\(now - wait_started_at\)\}s", p), \
        "心跳文案格式漂移(秒数正则 '等待 R2 上传锁 [0-9]+s' 将解析不到)"
    mirror = _extract_func(s, "_mirror_lock_heartbeat")
    assert "等待 R2 上传锁" in mirror and "${_hb##*等待 R2 上传锁 }" in mirror, "镜像锚点/解析丢失"
    assert "grep -Eo '[0-9]+'" not in mirror, \
        "禁止用 `grep -o '[0-9]+'` 抠秒数(会带出文案里 R2 的 2 ⇒ 脏值; 见本函数注释)"
    # 未动锁语义: 心跳常量 30s 未变 + 锁文件默认路径未变 + 超时语义未变(仍在排队超时时报错)
    assert ur._R2_LOCK_HEARTBEAT_SECS == 30
    assert 'R2_UPLOAD_LOCK", "/tmp/trade_r2_upload.lock"' in p
    assert "排队等待超" in p


# ── ③ 静态: 镜像接线(60s 采样块内、批次判定之前、节流常量) ──────────────────
def test_mirror_wiring_static():
    """③ 镜像调用接在 60s 采样块内且在批次判定之前(不依赖 [N/M] 行 ⇒ 全通道一视同仁)。"""
    s = R2SH.read_text(encoding="utf-8")
    impl = _extract_func(s, "_run_r2_upload_impl")
    assert '[ $((_slept % 60)) -eq 0 ]' in impl, "60s 采样块丢失"
    i_mirror = impl.index('_mirror_lock_heartbeat "$tmp_log" "$desc" "$_slept"')
    i_prog = impl.index("_prog=$(grep -Eo")
    assert i_mirror < i_prog, "镜像应在取进度行之前(与是否批量无关)"
    # 节流常量 + 非法值回落
    assert 'R2_LOCK_BEAT_MIRROR_SECS:-300' in s, "镜像节流常量默认 300 丢失"
    assert "case \"$_LOCK_BEAT_MIRROR_SECS\" in ''|*[!0-9]*) _LOCK_BEAT_MIRROR_SECS=300 ;; esac" in s, \
        "节流常量非法值未回落(可能被注入非数字)"
    assert "心跳每 30s 刷新 tmp_log mtime 防停滞判据误杀" in s, "镜像日志未说明与防误杀的关系"


# ── ④ 静态: 收尾汇总两指标(每通道 + 本轮 banner) ────────────────────────────
def test_daily_summary_metrics_landing():
    """④ 两个指标落在既有收尾位: 每通道「等锁统计」+ 本轮 banner「等锁: 次数=/最长=」。"""
    s = R2SH.read_text(encoding="utf-8")
    wrapper = _extract_func(s, "run_r2_upload")
    assert "等锁统计: 最长等锁 ${R2_LOCK_WAIT_LAST}s" in wrapper, "每通道「等锁统计」行丢失"
    assert "R2_LOCK_WAIT_N=$((R2_LOCK_WAIT_N + 1))" in wrapper, "本轮等锁次数未累加"
    assert '[ "$R2_LOCK_WAIT_LAST" -gt "$R2_LOCK_WAIT_MAX" ] && R2_LOCK_WAIT_MAX="$R2_LOCK_WAIT_LAST"' in wrapper, \
        "最长等锁未取本轮最大值"
    assert "等锁: 次数=$R2_LOCK_WAIT_N 最长=${R2_LOCK_WAIT_MAX}s" in s, "收尾 banner 两指标丢失"
    # banner 仍在 r2_upload_async 收尾(既有落点, 未新造汇总脚本)
    banner_line = [ln for ln in s.splitlines() if "等锁: 次数=$R2_LOCK_WAIT_N" in ln][0]
    assert banner_line.strip().startswith("echo \"=== r2_upload_async 结束"), \
        "两指标未追加在既有收尾 banner 上"
    # run_r2_upload 仍是唯一入口: 原实现整体下移为 _run_r2_upload_impl, 调用点全走包装层
    assert "run_r2_upload() {" in s and "_run_r2_upload_impl() {" in s
    # 原实现整体下移为 _run_r2_upload_impl: 调用点只有包装层 1 处(其余为定义 + 注释说明)
    calls = [ln.strip() for ln in s.splitlines() if ln.strip().startswith("_run_r2_upload_impl ")]
    assert calls == ['_run_r2_upload_impl "$@"'], f"调用点应唯一且走包装层, 实得 {calls}"
    wrapper_calls = [ln for ln in s.splitlines()
                     if re.match(r"\s*run_r2_upload \"", ln)]
    assert len(wrapper_calls) >= 15, f"通道调用点应全走包装层, 实得 {len(wrapper_calls)}"


# ── 零外发证据(机检) ───────────────────────────────────────────────────────
def test_harness_is_side_effect_free():
    """抽出的函数体不含任何上传/外发调用; 外部命令只读(证明自测零外发)。"""
    s = R2SH.read_text(encoding="utf-8")
    for fn in ("_mirror_lock_heartbeat", "run_r2_upload"):
        body = _extract_func(s, fn)
        for bad in ("upload_r2.py", '"$PY"', "rclone", "aws ", "curl", "systemd-run", "nohup"):
            assert bad not in body, f"{fn} 含疑似外发/执行调用 {bad!r} ⇒ 不满足 static-only"
        # 只允许只读命令 grep/tail/cat 与内建 echo/printf
    assert 'grep -F ' in _extract_func(s, "_mirror_lock_heartbeat"), "镜像应只 grep 只读"


# ── 行为: 镜像 + 节流 + 负控(等价重放抽出的纯函数) ─────────────────────────
def test_mirror_behavior_and_throttle(tmp_path):
    if shutil.which("bash") is None:
        pytest.skip("本机无 bash, 跳过")
    s = R2SH.read_text(encoding="utf-8")
    h = _build_harness(_extract_func(s, "_mirror_lock_heartbeat"),
                       _extract_func(s, "run_r2_upload"), tmp_path / "main.log")
    tlog = tmp_path / "ch.log"
    h = h.replace('LOG="', f'TMPLOG="{tlog}"\nLOG="', 1)

    # (a) 无心跳 ⇒ 不镜像, 状态保持未记录
    expr = (f': > "$TMPLOG"\n'
            '_mirror_lock_heartbeat "$TMPLOG" "d" 0\n'
            'echo "S=$_LOCK_BEAT_LOGGED/A=$_LOCK_BEAT_AT/L=$R2_LOCK_WAIT_LAST"')
    r, log = _bash(h, expr, tmp_path / "main.log")
    assert r.returncode == 0, r.stderr
    assert "S=0/A=0/L=0" in r.stdout and "等锁中" not in log

    # (b) 首次观测(_slept=0)即时镜像; 60s 时被节流; 300s 时再落一行; LAST 始终跟最新心跳
    newline = ("⏳ 等待 R2 上传锁 30s(上限 7300s, 进程 fsync 中)")
    expr = ("\n".join([
        f'printf "%s\\n" "{newline}" > "$TMPLOG"',
        '_mirror_lock_heartbeat "$TMPLOG" "d" 0',
        'echo "A1=$_LOCK_BEAT_AT/L1=$R2_LOCK_WAIT_LAST"',
        f'printf "%s\\n" "⏳ 等待 R2 上传锁 90s(上限 7300s)" > "$TMPLOG"',
        '_mirror_lock_heartbeat "$TMPLOG" "d" 60',
        'echo "A2=$_LOCK_BEAT_AT/L2=$R2_LOCK_WAIT_LAST"',
        '_mirror_lock_heartbeat "$TMPLOG" "d" 300',
        'echo "A3=$_LOCK_BEAT_AT/L3=$R2_LOCK_WAIT_LAST"',
    ]))
    r, log = _bash(h, expr, tmp_path / "main.log")
    assert r.returncode == 0, r.stderr
    assert "A1=0/L1=30" in r.stdout, f"首次应即时镜像并记 30, 实得 {r.stdout!r}"
    assert "A2=0/L2=90" in r.stdout, "60s 应被节流(AT 不变)但 LAST 跟到 90"
    assert "A3=300/L3=90" in r.stdout, "300s 应再落一行并刷新 AT=300"
    lines = [ln for ln in log.splitlines() if "等锁中 已等待" in ln]
    assert len(lines) == 2, f"30 分钟级等待应约 2 行(非刷屏), 实得 {len(lines)}: {lines}"
    assert "已等待 30s" in lines[0] and "已等待 90s" in lines[1]

    # (c) 负控: 秒数解析不出(文案漂移)⇒ 不镜像, LAST 不被污染
    expr = ('printf "%s\\n" "⏳ 等待 R2 上传锁 abcs(上限 7300s)" > "$TMPLOG"\n'
            'R2_LOCK_WAIT_LAST=7\n'
            '_mirror_lock_heartbeat "$TMPLOG" "d" 9999\n'
            'echo "S=$_LOCK_BEAT_LOGGED/L=$R2_LOCK_WAIT_LAST"')
    r, log2 = _bash(h, expr, tmp_path / "main2.log")
    assert r.returncode == 0, r.stderr
    assert "S=0/L=7" in r.stdout, "解析不出的心跳不应污染 LAST/触发镜像"


# ── 行为: 包装层「等锁统计」累加 + 退出码透传 ───────────────────────────────
def test_wrapper_stats_accumulation(tmp_path):
    if shutil.which("bash") is None:
        pytest.skip("本机无 bash, 跳过")
    s = R2SH.read_text(encoding="utf-8")
    logp = tmp_path / "main.log"
    h = _build_harness(_extract_func(s, "_mirror_lock_heartbeat"),
                       _extract_func(s, "run_r2_upload"), logp)
    expr = "\n".join([
        'run_r2_upload "ch-none" 0 0; echo "rc0=$?"',
        'run_r2_upload "ch-a" 120 0; echo "rc1=$?"',
        'run_r2_upload "ch-b" 45 0',
        'run_r2_upload "ch-c" 900 1; echo "rc3=$?"',
        'echo "N=$R2_LOCK_WAIT_N MAX=$R2_LOCK_WAIT_MAX"',
    ])
    r, log = _bash(h, expr, logp)
    assert r.returncode == 0, r.stderr
    # 无等锁通道不计入; 有等锁通道各落一行「等锁统计」; max 取本轮最大; 退出码透传
    assert "rc0=0" in r.stdout and "rc3=1" in r.stdout, f"退出码未透传: {r.stdout!r}"
    assert "N=3 MAX=900" in r.stdout, f"次数/最长统计错: {r.stdout!r}"
    stats = [ln for ln in log.splitlines() if "等锁统计: 最长等锁" in ln]
    assert len(stats) == 3, f"应有 3 条通道收尾统计, 实得 {len(stats)}"
    assert "ch-none 等锁统计" not in log, "零等待通道不应产生统计行"
    assert any("最长等锁 900s" in ln for ln in stats)


# ── 跨组件契约(最强): 生产真心跳 → 抽出的镜像函数能解析 ─────────────────────
def test_real_heartbeat_is_parseable_by_mirror(tmp_path, monkeypatch, capsys):
    """把 _acquire_r2_upload_lock 的**真实** stderr 心跳喂给抽出的镜像函数 ⇒ 必须解析成功。

    这条是「止血步(文案) ↔ J1 镜像(grep 锚点)」两实现的同构对账, 防未来任一侧漂移致镜像静默失效。
    """
    if shutil.which("bash") is None:
        pytest.skip("本机无 bash, 跳过")
    lock = tmp_path / "held.lock"
    holder = _hold_lock(lock)
    try:
        monkeypatch.setenv("R2_UPLOAD_LOCK", str(lock))
        monkeypatch.setenv("R2_UPLOAD_LOCK_TIMEOUT", "3")
        monkeypatch.setattr(ur, "_R2_LOCK_HEARTBEAT_SECS", 1)
        with pytest.raises(SystemExit):
            ur._acquire_r2_upload_lock()
        err = capsys.readouterr().err
        real = [ln for ln in err.splitlines() if "等待 R2 上传锁" in ln]
        assert real, "生产排队分支未产生心跳(止血步回归)"

        s = R2SH.read_text(encoding="utf-8")
        logp = tmp_path / "main.log"
        h = _build_harness(_extract_func(s, "_mirror_lock_heartbeat"),
                           _extract_func(s, "run_r2_upload"), logp)
        tlog = tmp_path / "ch.log"
        tlog.write_text(real[-1] + "\n", encoding="utf-8")
        h = h.replace('LOG="', f'TMPLOG="{tlog}"\nLOG="', 1)
        r, log = _bash(h, '_mirror_lock_heartbeat "$TMPLOG" "d" 0; echo "L=$R2_LOCK_WAIT_LAST"',
                       logp)
        assert r.returncode == 0, r.stderr
        secs = int(r.stdout.split("L=")[1].split()[0])
        assert secs >= 1, f"生产心跳未被镜像解析(secs={secs}) ⇒ 跨组件契约断"
        assert "等锁中 已等待" in log, "生产心跳镜像后主日志无留痕"
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))