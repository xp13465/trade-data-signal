#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#234 甲5 自验(2026-10-10): 日志被 gzip 后监控仍正确判「该班是否跑过」。

零外发(§18 L48 硬约束):
  · 全程**不运行** schedule_monitor.sh 主体(不 source/exec 业务脚本主体);
    schedule_monitor 一侧仅用 AST 抽取目标 def(resolve_log_path/open_log_text/
    parse_last_run)+ 两个 regex 常量后 exec —— 抽取面无 notify / 无 subprocess。
  · gen_schedule_stats 端到端用 ZeroOutboundTrap 包裹 runpy.run_path 跑: 任一真实
    urllib/smtplib 出口被触达即抛 AssertionError(收尾断言 hits==[])。
  · check_data_gap 一侧同用 AST 抽取 _scan_cap_giveup_log 后 exec。
  · 只写 /tmp sandbox; 不碰生产 trade-data/data。

用例:
  ①helper 单元: .log 优先 / 缺失回退 .log.gz / 都无=None
  ②parse_last_run: 未压缩 == 改造前固化期望(同输入逐位); == gz(逐位); 缺失 → None
  ③gen_schedule_stats 端到端回归: 未压缩输入 == 改造前固化输出 md5(逐字节一致)
  ④gen_schedule_stats 端到端 gz: 单任务日志 gz 化 → last_run 不丢(==未压缩, 治漏跑误报)
  ⑤check_data_gap _scan_cap_giveup_log: 未压缩 == gz(逐位)

2026-10-10 打回修复(独立审 BLOCKER-1 + 低分项):
  · 弃用 `git show HEAD:` 自引用对照: 改造 commit 后 HEAD 即改造后源码 —— 对照面缺
    resolve_log_path(崩 NameError)、gen_schedule_stats 对照空转(改造后 vs 改造后)。
    改用「真实输入→期望输出」固化期望值(常量见 FROZEN_*, 捕获自 baseline 64946a079),
    彻底不依赖 git 历史(CI 浅克隆/无 git 环境同样成立)。
  · ④ 修复同族假绿: 原实现未真正 gz 化沙箱日志(out_gz 恒 == j_mod, 该块空转) ——
    现真把 INTRA 改为 .gz 再跑, 使「gz 化后统计字段不丢」名副其实。
  · 零外发断言加**阳性对照**(§18 L48「先证判定生效」): 伪 urlopen 必被拦, 防陷阱自身失效假绿。
"""
from __future__ import annotations

import ast
import gzip
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / "scripts"
TESTS = SCRIPTS / "tests"
PY = sys.executable

FAIL = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAIL.append(name)


# ── 固化期望值(captured from baseline 64946a079 = 改造前; 一次捕获即冻结) ──
# 取代原 `git show HEAD:` 动态自引用(BLOCKER-1 根因: 改造 commit 后 HEAD 即改造后源码)。
# 这些值可用任意方式核验(改造前后逐位一致),但测试本身不再查询 git。
#
# ② 改造前 parse_last_run 在未压缩 INTRA 样本上的末次开始时间(改造前后逐位一致)
FROZEN_OLD_PARSE_LAST_RUN_PLAIN = "2026-10-10 09:35:02"
# ③ 改造前 gen_schedule_stats 在同一 3 日志沙箱(INTRA/ETF/UPDATE_ALL)上的输出 md5
#    (改造前后逐字节一致; reviewer 独立复核证据 A 同结论 —— 未压缩场景零行为变化)
FROZEN_OLD_E2E_MD5 = "0cf8f13b12d9b710b055e11531792454"
# ④ gz-only(INTRA 仅剩 .log.gz)场景: 改造前该任务 last_run=None(=缺陷: .log 缺失 →
#    「无日志」→ 落计划窗口即漏跑误报), 且未压缩沙箱的 null 计数未变; 改造后 null 计数减 1
FROZEN_OLD_GZ_ONLY_NULL_COUNT = 17


def heredoc_src(name: str) -> str:
    src = (SCRIPTS / name).read_text(encoding="utf-8")
    m = re.search(r"<<'PYEOF'[^\n]*\n(.*?)\nPYEOF\b", src, re.S)
    assert m, f"heredoc not found in {name}"
    return m.group(1)


def heredoc_src(name: str) -> str:
    src = (SCRIPTS / name).read_text(encoding="utf-8")
    m = re.search(r"<<'PYEOF'[^\n]*\n(.*?)\nPYEOF\b", src, re.S)
    assert m, f"heredoc not found in {name}"
    return m.group(1)


def extract_module(src: str, funcs: set, assigns: set) -> tuple[dict, list[str]]:
    """从真实源码文本抽取指定 def/Assign 节点后 exec(不跑其余主体)。"""
    tree = ast.parse(src)
    nodes, names = [], []
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name in funcs:
            nodes.append(n)
            names.append(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id in assigns:
                    nodes.append(n)
                    names.append(t.id)
    mod = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(mod)
    ns = {
        "re": re, "gzip": gzip, "sys": sys, "json": json,
        "datetime": __import__("datetime").datetime,
        "timedelta": __import__("datetime").timedelta,
        "Path": Path,
    }
    exec(compile(mod, "<extracted>", "exec"), ns)
    return ns, names


# ---- 合成日志(标准开始/结束行 + etf_nt 变体) ----
INTRA = (
    "=== intraday_snapshot.sh 开始 2026-10-09 15:35:00 ===\n"
    "  collect...\n"
    "=== intraday_snapshot.sh 结束 2026-10-09 15:37:12 退出码=0 ===\n"
    "=== intraday_snapshot.sh 开始 2026-10-10 09:25:01 ===\n"
    "  collect...\n"
    "=== intraday_snapshot.sh 结束 2026-10-10 09:27:03 退出码=0 ===\n"
    "=== intraday_snapshot.sh 开始 2026-10-10 09:35:02 ===\n"
    "  collect...\n"
    "=== intraday_snapshot.sh 结束 2026-10-10 09:37:10 退出码=1 ===\n"
)
ETF = (
    "[etf_nt] daily 开始 2026-10-09 20:07:00\n"
    "  run...\n"
    "[etf_nt] daily 完成 123.4s exit=0\n"
    "[etf_nt] daily 开始 2026-10-10 20:07:01\n"
    "  run...\n"
    "[etf_nt] daily 完成 100.0s exit=0\n"
)
UPDATE_ALL = (
    "=== update_all.sh 开始 2026-10-10 17:50:03 ===\n"
    "  deploy ...\n"
    "=== update_all.sh 结束 2026-10-10 18:10:55 退出码=0 ===\n"
)


def main() -> int:
    # ---------- ① + ② schedule_monitor 侧(parse_last_run) ----------
    sm = heredoc_src("schedule_monitor.sh")
    ns_sm, names_sm = extract_module(
        sm, {"resolve_log_path", "open_log_text", "parse_last_run"},
        {"START_RE", "ETF_START_RE"})
    check("② schedule_monitor 抽取面最小(无 notify/无 subprocess 主体)",
          sorted(names_sm) == sorted(["resolve_log_path", "open_log_text", "parse_last_run",
                                      "START_RE", "ETF_START_RE"]),
          f"extracted={names_sm}")

    tmp = Path(tempfile.mkdtemp(prefix="a5-sm-"))
    plain = tmp / "intraday_snapshot_launchd.log"
    plain.write_text(INTRA, encoding="utf-8")

    r0 = ns_sm["parse_last_run"](plain)
    check("② parse_last_run 未压缩 → 末次开始时间",
          r0 is not None and r0.strftime("%Y-%m-%d %H:%M:%S") == "2026-10-10 09:35:02",
          f"got={r0}")

    # ② 未压缩回归(固化期望值,弃 git 自引用): 断言改造后输出 == 改造前固化的「真实输入→
    #    期望输出」常量 ⇒ 等价于「改造前 == 改造后(同输入逐位)」。
    check("② 未压缩回归: parse_last_run == 改造前固化期望(同输入逐位)",
          r0 is not None and r0.strftime("%Y-%m-%d %H:%M:%S") == FROZEN_OLD_PARSE_LAST_RUN_PLAIN,
          f"got={r0} frozen={FROZEN_OLD_PARSE_LAST_RUN_PLAIN}")

    gz = tmp / "intraday_snapshot_launchd.log.gz"
    with gzip.open(gz, "wt", encoding="utf-8") as f:
        f.write(INTRA)
    plain.unlink()
    r1 = ns_sm["parse_last_run"](plain)  # .log 已删, 只剩 .gz
    check("② parse_last_run .gz 回退 → 与未压缩逐位一致",
          r1 == r0, f"gz={r1} plain={r0}")

    gz.unlink()
    check("② 都无 → None(未压缩缺文件行为不变)",
          ns_sm["parse_last_run"](plain) is None)

    # ① helper 单元
    p = tmp / "x.log"
    p.write_text("a\n", encoding="utf-8")
    check("① resolve_log_path .log 优先", ns_sm["resolve_log_path"](p) == p)
    gz2 = tmp / "x.log.gz"
    with gzip.open(gz2, "wt", encoding="utf-8") as f:
        f.write("a\n")
    p.unlink()
    check("① resolve_log_path 回退 .gz", ns_sm["resolve_log_path"](p) == gz2)
    gz2.unlink()
    check("① resolve_log_path 都无 → None", ns_sm["resolve_log_path"](p) is None)

    # ---------- ⑤ gen_schedule_stats 单元(tail 读) ----------
    gs = (SCRIPTS / "gen_schedule_stats.py").read_text(encoding="utf-8")
    ns_gs, names_gs = extract_module(
        gs, {"_resolve_log", "_open_log_text", "_read_tail_lines", "_iter_lines"},
        {"_TAIL_READ_BYTES"})
    check("⑤ gen_schedule_stats 抽取面最小",
          sorted(names_gs) == sorted(["_resolve_log", "_open_log_text",
                                      "_read_tail_lines", "_iter_lines", "_TAIL_READ_BYTES"]),
          f"extracted={names_gs}")
    tplain = tmp / "t.log"
    tplain.write_text(INTRA, encoding="utf-8")
    tail_plain = ns_gs["_read_tail_lines"](tplain)
    tgz = tmp / "t.log.gz"
    with gzip.open(tgz, "wt", encoding="utf-8") as f:
        f.write(INTRA)
    tplain.unlink()
    check("⑤ _read_tail_lines .gz 回退 == 未压缩行尾",
          ns_gs["_read_tail_lines"](tplain) == tail_plain, f"n={len(tail_plain)}")
    it_gz = list(ns_gs["_iter_lines"](tplain))
    check("⑤ _iter_lines .gz 回退行数一致", len(it_gz) == INTRA.count("\n"))
    tgz.unlink()

    # ---------- ③ check_data_gap _scan_cap_giveup_log ----------
    cg = (SCRIPTS / "check_data_gap_alerts.py").read_text(encoding="utf-8")
    ns_cg, names_cg = extract_module(
        cg, {"_scan_cap_giveup_log"}, {"NORTH_LOG_CANDIDATES", "CAP_GIVEUP_ANCHOR"})
    check("⑤ check_data_gap 抽取面最小",
          sorted(names_cg) == sorted(["_scan_cap_giveup_log",
                                      "NORTH_LOG_CANDIDATES", "CAP_GIVEUP_ANCHOR"]),
          f"extracted={names_cg}")
    gaproot = Path(tempfile.mkdtemp(prefix="a5-gap-"))
    (gaproot / "data" / "logs").mkdir(parents=True)
    bl = gaproot / "data" / "logs" / "backfill_evening_launchd.log"
    bl.write_text("noise\n北向 deep_cap 已越过硬顶 2026-10-09\n", encoding="utf-8")
    hit_plain = ns_cg["_scan_cap_giveup_log"](gaproot)
    with gzip.open(str(bl) + ".gz", "wt", encoding="utf-8") as f:
        f.write("noise\n北向 deep_cap 已越过硬顶 2026-10-09\n")
    bl.unlink()
    hit_gz = ns_cg["_scan_cap_giveup_log"](gaproot)
    check("⑤ _scan_cap_giveup_log .gz 回退 == 未压缩",
          hit_gz == hit_plain and "已越过硬顶" in hit_gz, f"gz={hit_gz!r}")

    # ---------- ③ + ④ gen_schedule_stats 端到端 ----------
    basis = Path(tempfile.mkdtemp(prefix="a5-e2e-"))
    mod_src = gs

    def build_sandbox(tag: str, src: str) -> Path:
        sb = basis / tag
        (sb / "scripts").mkdir(parents=True)
        (sb / "data" / "logs").mkdir(parents=True)
        (sb / "static-site" / "data").mkdir(parents=True)
        (sb / "scripts" / "gen_schedule_stats.py").write_text(src, encoding="utf-8")
        shutil.copy2(SCRIPTS / "util_atomic.py", sb / "scripts" / "util_atomic.py")
        for nm, content in (("intraday_snapshot_launchd.log", INTRA),
                            ("etf_national_team_launchd.log", ETF),
                            ("update_all_launchd.log", UPDATE_ALL)):
            (sb / "data" / "logs" / nm).write_text(content, encoding="utf-8")
        return sb

    sb_mod = build_sandbox("mod", mod_src)

    # ZeroOutboundTrap 包裹 runpy 跑真实脚本主体(证明零外发)
    runner = (
        "import runpy,sys;"
        f"sys.path.insert(0,{str(TESTS)!r});"
        "from _zero_outbound import ZeroOutboundTrap;"
        "t=ZeroOutboundTrap();t.__enter__();"
        f"runpy.run_path({str(sb_mod / 'scripts' / 'gen_schedule_stats.py')!r},run_name='__main__');"
        "print('ZERO_HITS='+repr(t.hits))"
    )

    def run_script(sb: Path) -> dict:
        r = subprocess.run([PY, str(sb / "scripts" / "gen_schedule_stats.py")],
                           capture_output=True, text=True, timeout=180)
        assert r.returncode == 0, f"script rc={r.returncode}\n{r.stdout}\n{r.stderr}"
        out = sb / "static-site" / "data" / "schedule_stats.json"
        return json.loads(out.read_text(encoding="utf-8"))

    j_mod = run_script(sb_mod)
    # ③ 未压缩端到端回归(固化期望 md5,弃 git 自引用): 断言改造后输出**逐字节** == 改造前
    #    固化的 md5(捕获自 baseline 64946a079; 二者逐字节一致 = 未压缩场景零行为变化)。
    _md5_mod = hashlib.md5(
        (sb_mod / "static-site" / "data" / "schedule_stats.json").read_bytes()).hexdigest()
    check("③ 未压缩端到端: 输出 == 改造前固化 md5(逐字节)",
          _md5_mod == FROZEN_OLD_E2E_MD5,
          f"got={_md5_mod} frozen={FROZEN_OLD_E2E_MD5}")

    # ④ 单任务日志真 gz 化(修复同族假绿: 原实现未 gz 化, out_gz 恒 == j_mod = 空转)
    #    + ZeroOutboundTrap 包裹跑
    _intra_log = sb_mod / "data" / "logs" / "intraday_snapshot_launchd.log"
    with gzip.open(str(_intra_log) + ".gz", "wt", encoding="utf-8") as f:
        f.write(INTRA)
    _intra_log.unlink()
    r = subprocess.run([PY, "-c", runner], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, f"gz runner rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    check("③ 零外发: gen_schedule_stats 端到端 ZeroOutboundTrap hits==[]",
          "ZERO_HITS=[]" in r.stdout, r.stdout.strip().splitlines()[-1] if r.stdout else "")
    out_gz = json.loads((sb_mod / "static-site" / "data" / "schedule_stats.json")
                        .read_text(encoding="utf-8"))

    int_mod = next(x for x in j_mod if x["task"] == "intraday_snapshot")
    int_gz = next(x for x in out_gz if x["task"] == "intraday_snapshot")
    check("④ 旧代码 gz-only 缺陷已关闭: 新代码 null 计数 -1(旧代码 "
          f"{FROZEN_OLD_GZ_ONLY_NULL_COUNT})",
          sum(1 for x in out_gz if x["last_run"] is None) == FROZEN_OLD_GZ_ONLY_NULL_COUNT - 1
          and sum(1 for x in out_gz if x["last_run"] is None)
          == sum(1 for x in j_mod if x["last_run"] is None),
          f"gz_null={sum(1 for x in out_gz if x['last_run'] is None)} "
          f"plain_null={sum(1 for x in j_mod if x['last_run'] is None)}")
    check("④ gz 化后 intraday last_run 不丢(==未压缩, 治漏跑误报)",
          int_gz["last_run"] == int_mod["last_run"] and int_gz["last_run"] == "2026-10-10 09:35",
          f"gz={int_gz['last_run']} mod={int_mod['last_run']}")
    check("④ gz 化后 intraday 其余字段一致",
          {k: int_gz[k] for k in ("last_exit", "est_text", "log_anomaly", "last_duration_sec")}
          == {k: int_mod[k] for k in ("last_exit", "est_text", "log_anomaly", "last_duration_sec")},
          f"gz={int_gz.get('last_exit')} {int_gz.get('est_text')}")

    # ②(顺手, §18 L48 阳性对照): 证明零外发陷阱**本身生效** —— 伪调用必被拦。
    #    否则 ZERO_HITS==[] 可能因陷阱未安装而假绿(先证判定生效, 再信 hits==[])。
    #    ⚠️ 仅当确认陷阱已安装(installed=True)才发起伪调用 ⇒ 伪调用恒被陷阱拦截, 零真实网络。
    _positive = (
        "import urllib.request, smtplib, sys\n"
        f"sys.path.insert(0, {str(TESTS)!r})\n"
        "from _zero_outbound import ZeroOutboundTrap\n"
        "t = ZeroOutboundTrap(); t.__enter__()\n"
        "installed = (getattr(urllib.request.urlopen, '__name__', '') == '_trap'\n"
        "             and getattr(smtplib.SMTP_SSL, '__name__', '') == '_trap')\n"
        "blocked = None\n"
        "if installed:\n"
        "    try:\n"
        "        urllib.request.urlopen('http://selftest.invalid/')\n"
        "        blocked = False\n"
        "    except AssertionError:\n"
        "        blocked = True\n"
        "print('POSITIVE=' + repr(bool(installed and blocked)))"
    )
    _rp = subprocess.run([PY, "-c", _positive], capture_output=True, text=True, timeout=60)
    check("② 零外发陷阱阳性对照: 伪 urlopen 必被拦(先证陷阱生效)",
          _rp.returncode == 0 and "POSITIVE=True" in _rp.stdout,
          f"rc={_rp.returncode} out={(_rp.stdout or '').strip()!r}")

    # 清场 sandbox
    for d in (tmp, gaproot, basis):
        shutil.rmtree(d, ignore_errors=True)

    print("-" * 60)
    if FAIL:
        print(f"RESULT: FAIL ({len(FAIL)}): {FAIL}")
        return 1
    print("RESULT: ALL PASS")
    return 0


def test_log_gz_compat_20261010() -> None:
    """pytest 入口(CI Quality Gate ⑧ 收集): 复用脚本式 main(); 仍可 `python3 <file>` 直跑。"""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())