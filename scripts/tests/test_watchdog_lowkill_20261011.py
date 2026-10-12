# -*- coding: utf-8 -*-
"""#253 r2_upload_async 低速 kill 判据修复(a1 窗口防倒置 + a2 收尾豁免)——正/负控自验(2026-10-11)。

权威规格 = docs/ops/watchdog-tradesim-slowkill-20261011.md §5-a1/a2 + §6;实施报告
  = docs/ops/watchdog-lowkill-fix-exec-20261011.md。被测面 = `scripts/lib/upload_watchdog.sh`
  的三个纯判定函数(r2_low_speed_window / r2_low_speed_need / r2_tail_near_complete /
  r2_low_speed_should_kill)+ `scripts/r2_upload_async.sh` 的接线(静态文本)。

CI 挂载: 位于 `scripts/tests/` ⇒ 被 CI 门禁 ⑧(`python3 -m pytest -q scripts/tests/`)收集。

§18 L50(探针一律 static-only)
  本测试**不 source/exec 任何业务脚本主体**(r2_upload_async.sh 会真的发起 R2 上传)。
  判据被抽成**无副作用纯函数库** `scripts/lib/upload_watchdog.sh`,测试只经 `bash -s` 的
  **stdin 管道 source 该库**(与 lib/repo_paths.sh 同款 pattern),零网络/零 R2/零落盘。
  抽取在 **test 函数体内**做,模块级只定义常量/纯 helper(仿 test_223: 收集期抛异常会
  让本目录全部用例不跑的 P0 已由该文件记载)。

跑法: python3 -m pytest -q scripts/tests/test_watchdog_lowkill_20261011.py
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]              # scripts/tests -> scripts -> 仓库根
LIB = ROOT / "scripts" / "lib" / "upload_watchdog.sh"
R2SH = ROOT / "scripts" / "r2_upload_async.sh"
MIN_ASSERTIONS = 45                                     # 断言下限(防收集/执行异常致假绿)


# ── 断言计数器(仿 test_223;仅本用例内部,无全局副作用)─────────────────────
class _Ck:
    def __init__(self):
        self.p = self.f = 0

    def __call__(self, ok, name, extra=""):
        if ok:
            self.p += 1
            print(f"  PASS  {name}")
        else:
            self.f += 1
            print(f"  FAIL  {name} {extra}")


def test_watchdog_lowkill_a1a2():
    if shutil.which("bash") is None:
        pytest.skip("本机无 bash, 跳过")
    ck = _Ck()

    def sh(expr: str, lib: Path = LIB) -> str:
        """经 bash -s 的 stdin 管道 source 纯函数库后执行 expr, 返回 stdout(strip)。"""
        script = f'set -u\nsource "{lib}"\n{expr}\n'
        r = subprocess.run(["bash", "-s"], input=script, capture_output=True,
                           text=True, timeout=60)
        assert r.returncode == 0, f"bash rc={r.returncode} expr={expr!r}\n{r.stderr}"
        return r.stdout.strip()

    def kill(m, w, M, N):
        out = sh(f'if r2_low_speed_should_kill {m} {w} {M} {N}; then echo KILL; '
                 f'else echo NOKILL; fi')
        return out == "KILL"

    print("\n[A] a1 梯度护栏: 低速窗口 = max(900, HTTP超时+300), 且必须 > 内层自愈周期")
    # (入参, 规范化后的 HTTP 超时) —— 缺省/非法均回落 30
    for raw, norm in (("600", 600), ("30", 30), ("900", 900), ("1200", 1200),
                      ("abc", 30), ("", 30)):
        w = int(sh(f'r2_low_speed_window "{raw}"'))
        ck(w == max(900, norm + 300), f"window({raw!r}) == max(900,{norm}+300)", f"got {w}")
        ck(w > norm + 75, f"window({raw!r}) > 内层自愈周期上界({norm}+75)", f"got {w}")
    w_def = int(sh("r2_low_speed_window"))          # 无参默认
    ck(w_def == 900, "window() 无参默认 = 900", f"got {w_def}")
    ck(int(sh("r2_low_speed_window 600")) > 675,
       "生产事实(云上 HTTP=600): 窗口 900 > 内层自愈周期 ≈675 ⇒ 内层活着杀不掉")
    ck(int(sh("r2_low_speed_window 600")) >= 900, "窗口下限 ≥ 900")
    ck(int(sh("r2_low_speed_window 900")) == 1200, "HTTP=900 ⇒ 1200(仍按 +300 抬)")
    for win, need in ((900, 15), (1200, 20), (300, 5), (961, 17)):
        ck(int(sh(f"r2_low_speed_need {win}")) == need, f"need({win}) == {need}")
    ck(int(sh('r2_low_speed_need "abc"')) == 15, "need 非法输入回落 900 ⇒ 15")

    print("\n[B] a2 收尾豁免: 接近完成(剩 ≤2 个文件)不杀")
    for M, N in ((103, 102), (103, 101), (103, 103), (158, 156), (11, 9)):
        ck(not kill(15, 900, M, N), f"收尾豁免: M={M} N={N} 达窗口也不杀")
    ck(not kill(20, 900, 158, 156), "窗口 1200 时收尾豁免仍生效(与窗口无关)")
    # 边界: 剩 3 个文件(N=M-3)= 不在豁免面 ⇒ 仍杀(防豁免过宽)
    ck(kill(15, 900, 103, 100), "边界: N=M-3(剩 3 个)⇒ 不豁免, 仍杀")

    print("\n[C] 保留判据(红线): 未接近完成 + 零输出 ≥ 窗口 ⇒ 照杀")
    ck(kill(15, 900, 103, 50), "中段真空 M=103 N=50 ⇒ 杀")
    ck(kill(15, 900, 103, 1), "通道开头 M=103 N=1 ⇒ 杀")
    ck(kill(15, 900, 103, 0), "零完成行 M=103 N=0 ⇒ 杀")
    ck(kill(15, 900, 158, 128), "历史形态(10-09 index [128/158], 非收尾)⇒ 仍杀(诚实标注: 该例不被 a2 豁免)")
    ck(not kill(14, 900, 103, 50), "未达窗口(m=14<15)⇒ 不杀")
    ck(not kill(5, 900, 103, 50), "旧 300s 口径计数(5)对新 900s 窗口 ⇒ 不杀(证明窗口真变长)")
    ck(not kill(15, 900, 10, 10), "非批量通道(M=10 ≤ min_batch)⇒ 低速判据不适用, 不杀")
    ck(not kill(15, 900, 5, 5), "单文件/小通道(M=5)⇒ 不杀")

    print("\n[F] 进度行解析(收尾豁免取 N 的来源)")
    for tok, exp in (("[102/103]", "102 103"), ("[1/158]", "1 158"),
                     ("[73/103]", "73 103"), ("", "0 0"), ("abc", "0 0"),
                     ("[x/y]", "0 0")):
        ck(sh(f'r2_parse_progress "{tok}"') == exp, f"parse({tok!r}) == {exp!r}")

    print("\n[D] 静态接线: r2_upload_async.sh 真调用新判据 + 保留判据未被削")
    s = R2SH.read_text(encoding="utf-8")
    ck("lib/upload_watchdog.sh" in s, "已 source 判据纯函数库")
    ck('_low_win="$(r2_low_speed_window "$_http_to")"' in s, "窗口取自 r2_low_speed_window($_http_to)")
    ck('_low_need="$(r2_low_speed_need "$_low_win")"' in s, "need 取自 r2_low_speed_need")
    ck('r2_low_speed_should_kill "$_low_bad" "$_low_win" "$_batch_total" "$_batch_done"' in s,
       "kill 判定接线(r2_low_speed_should_kill)")
    ck('r2_tail_near_complete "$_batch_total" "$_batch_done"' in s, "收尾豁免接线(r2_tail_near_complete)")
    ck('r2_parse_progress "$_prog"' in s, "N/M 解析接线(r2_parse_progress)")
    ck("read -r _pn _pm <<<" in s, "解析结果经 read 取出 N/M")
    ck("a2 收尾豁免" in s, "豁免落一行日志(可观测)")
    ck('近5分钟字节增量<1MB' not in s, "旧硬编码文案「近5分钟」已消失")
    ck('_low_bad" -ge 5' not in s, "旧硬编码阈值 `_low_bad -ge 5` 已消失")
    ck('近$((_low_win / 60))分钟' in s, "kill 文案改为随窗口动态「近 N 分钟」")
    ck("$R2_LOW_SPEED_MIN_BATCH" in s, "批量下限用库常量(单点定义, 无第二份 magic number)")
    # 红线: 停滞判据(900s, > 内层超时)+ 7200s 硬兜底仍在, 未被本次改动削弱
    ck('R2_UPLOAD_STALL_SECS:-900' in s, "停滞判据默认 900s 仍在(真死仍被守)")
    ck('_stall_secs=$((_http_to + 300))' in s, "停滞判据防倒置护栏仍在")
    ck('总时长超 7200s 硬兜底' in s, "7200s 硬兜底仍在")
    ck('R2_KILLED="$R2_KILLED $desc"' in s, "kill 仍登记 R2_KILLED(告警不静默, #177)")
    ck(s.count('_dump_kill_tail "$tmp_log" "$desc"') == 3,
       "三处 kill 分支(停滞/硬兜底/低速)仍各 dump 尾部 30 行(#217③)")

    print("\n[E] 负控变异: 断言真能咬住(去掉库内 900s 下限 ⇒ window(30) 变化)")
    mut = ROOT / "scripts" / "tests" / "fixtures" / "_mut_watchdog_floor.sh"
    mut.parent.mkdir(parents=True, exist_ok=True)
    body = LIB.read_text(encoding="utf-8").replace('[ "$w" -lt 900 ] && w=900', ":")
    mut.write_text(body, encoding="utf-8")
    try:
        ck(sh("r2_low_speed_window 30") == "900", "原库: window(30)=900(下限生效)")
        ck(sh("r2_low_speed_window 30", lib=mut) == "330",
           "变异(去下限): window(30)=330 ≠ 900 ⇒ 下限断言真被判")
    finally:
        mut.unlink(missing_ok=True)

    print(f"\n===== 汇总: PASS={ck.p} FAIL={ck.f} =====")
    assert ck.f == 0, f"#253 低速判据修复自测 FAIL={ck.f}(明细见上方 stdout)"
    assert ck.p >= MIN_ASSERTIONS, f"断言数仅 {ck.p}(下限 {MIN_ASSERTIONS}), 疑似收集/执行异常"
    print("ALL_PASS")


if __name__ == "__main__":
    import sys
    try:
        test_watchdog_lowkill_a1a2()
    except AssertionError as e:
        print(f"\nSOME_FAIL: {e}")
        sys.exit(1)
    sys.exit(0)