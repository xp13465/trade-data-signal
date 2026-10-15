#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""alert_weekly_review.py — 告警周 review 轻量工具(#264 包3「治理」件F)

用途:把「告警面扩张纳入预算」的**周度复核**做成一键可跑(不靠人肉记忆),对齐
      RCA §4.1 F 的「每周 review top-talkers + 被吞条目找回核对」。

四件事(全部只读 + 打印,零外发,不碰通知链路 —— §18 L48 精神):
  1. **top-talkers**:近 N 天(默认 7)实发告警按 source / subject 排序,看谁在刷屏。
  2. **tier / 重复率**:按 tier 分布 + 完全同主题多余行(重复下限口径,对齐 RCA §1.3)。
  3. **被吞条目找回核对**:读 alert_daily.json 的 merged_in_digest,提示去摘要里核对
     「被合并条目是否都出现」(降噪不变式 4:被合并条目必须出现在摘要)。
  4. **四元组缺失扫描**(`--check-four-tuple`):静态扫 scripts/ 下**调 notify.py 发外发告警**
     的脚本,列 缺 `--tier/--severe` / 缺 `--dedup-key` / `--dedup-window 0`(关死抑制=违规)。
     对齐 `docs/ops/alert-checker-registry-20261015.md`(新 checker 缺一不上线,reviewer skill §11)。

数据源:云上权威机台账 `data/alerts/alert_ledger.jsonl`(10-10 08:27 上线后的**全量外发**逐行)
        + `data/alerts/alert_daily.json`(日计数,幂等重算)。**跨两树聚合**(双树分裂是结构性根因,
        RCA §1.1/收敛计划 W1:不跨树会「又变成两个数字」违反 §22)。
用法:
  python3 scripts/alert_weekly_review.py --ledger /path/a.jsonl --ledger /path/b.jsonl
  python3 scripts/alert_weekly_review.py --ledger <...> --days 7 --check-four-tuple
  python3 scripts/alert_weekly_review.py --selftest        # 自测(合成台账,零外发)

退出码:0=正常;2=参数/数据缺失(如台账文件不存在)。
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 云上两树台账缺省候选(本机 mac 无台账 ⇒ 缺省会 exit 2 提示从云上取;不硬编码 mac 路径)
DEFAULT_LEDGER_CANDIDATES = [
    "/home/ubuntu/code/trade-data/data/alerts/alert_ledger.jsonl",
    "/home/ubuntu/code/trade-data-signal/data/alerts/alert_ledger.jsonl",
]
ALERT_DAILY_CANDIDATES = [
    "/home/ubuntu/code/trade-data/data/alerts/alert_daily.json",
    "/home/ubuntu/code/trade-data-signal/data/alerts/alert_daily.json",
]

# 四元组静态扫描:排除自身/工具/测试
SCAN_EXCLUDE = {"notify.py", "notify_sent.py", "alert_weekly_review.py",
                "alert_meter.py", "merge_notify_dedup_trees.py"}
_NOTIFY_CALL = re.compile(r"notify\.py\b")
# 「调用形态」提示:行内含这些 = 真在把 notify.py 当命令/子进程调(排除散文/docstring 提及)
_INVOKE_HINT = re.compile(r"subprocess|sys\.executable|\$PY|\$REPO/scripts/notify|os\.system|\.run\(|cmd\s*=|notify\.py[\"']")
_IS_COMMENT = re.compile(r"^\s*#")


def _load_ledger(paths):
    rows = []
    missing = []
    for p in paths:
        fp = Path(p)
        if not fp.exists():
            missing.append(p)
            continue
        for line in fp.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows, missing


def report_ledger(rows, days, now=None):
    now = now or datetime.now()
    cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    recent = [r for r in rows if str(r.get("ts", ""))[:10] >= cutoff]
    print(f"== top-talkers(近 {days} 天,cutoff>={cutoff})== 共 {len(recent)} 条")
    for label, key in (("source(来源脚本)", "source"), ("subject(主题)", "subject")):
        c = collections.Counter(str(r.get(key)) for r in recent)
        print(f"-- 按 {label} top 12 --")
        for k, v in c.most_common(12):
            print(f"  {v:>4}  {k}")
    tiers = collections.Counter(str(r.get("tier")) for r in recent)
    print("-- 按 tier --")
    for k, v in tiers.most_common():
        print(f"  {v:>4}  {k}")
    # 完全同主题多余行(重复下限口径)
    sc = collections.Counter(r.get("subject") for r in recent)
    dup = {s: n for s, n in sc.items() if n >= 2}
    extras = sum(dup.values()) - len(dup) if dup else 0
    print(f"-- 完全同主题重复:组 {len(dup)} / 行 {sum(dup.values())} / 多余行 {extras} "
          f"(下限,语义重复未计)—— 对齐 RCA §1.3")


def report_recovery(daily_paths):
    print("== 被吞条目找回核对(降噪不变式 4)== ")
    found = False
    for p in daily_paths:
        fp = Path(p)
        if not fp.exists():
            continue
        found = True
        try:
            d = json.loads(fp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"  {p}: JSON 解析失败")
            continue
        merged = d.get("merged_in_digest")
        total = d.get("total")
        print(f"  {p}: date={d.get('date')} total={total} merged_in_digest={merged}")
    if not found:
        print("  (无 alert_daily.json;请在云上跑)")
    print("  人工核对项:merged_in_digest 的条目,是否**都出现在当日摘要正文**里"
          "(被合并条目必须可检索;缺 = 静默吞掉真故障判别维度,须上报)")


def scan_four_tuple(scripts_dir):
    """静态扫 scripts/ 下调 notify.py 的脚本,列四元组缺项(不执行任何脚本)。"""
    print("== 四元组缺失扫描(--check-four-tuple)== ")
    candidates = []
    for p in sorted(Path(scripts_dir).glob("*.py")) + sorted(Path(scripts_dir).glob("*.sh")):
        if p.name in SCAN_EXCLUDE or p.name.startswith("test_") or "tests" in p.parts:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        invokes = any(_NOTIFY_CALL.search(l) and _INVOKE_HINT.search(l) and not _IS_COMMENT.match(l)
                      for l in text.splitlines())
        if not invokes:
            continue
        has_tier = ("--tier" in text) or ("--severe" in text)
        has_dedup = "--dedup-key" in text
        window0 = bool(re.search(r"--dedup-window[\"']?\s*,\s*[\"']0[\"']", text)) or \
            bool(re.search(r"--dedup-window\s+0\b", text))
        missing = []
        if not has_tier:
            missing.append("tier未声明")
        if not has_dedup:
            missing.append("dedup-key未声明")
        if window0:
            missing.append("dedup-window=0(违规)")
        candidates.append((p.name, missing))
    if not candidates:
        print("  (未发现调 notify.py 的脚本,检查 scripts_dir)")
    for name, missing in candidates:
        flag = "OK " if not missing else "缺 "
        print(f"  [{flag}] {name}" + (f"  →  {'/'.join(missing)}" if missing else ""))
    n_bad = sum(1 for _, m in candidates if m)
    print(f"  小结:扫描 {len(candidates)} 个告警产生点,{n_bad} 个有缺项 "
          f"(全量登记表见 docs/ops/alert-checker-registry-20261015.md)")


def _selftest():
    import tempfile
    rows = [
        {"ts": "2026-10-15 18:00:00", "tier": "critical", "source": "a.sh", "subject": "S1", "group": "alert"},
        {"ts": "2026-10-15 18:05:00", "tier": "critical", "source": "a.sh", "subject": "S1", "group": "alert"},
        {"ts": "2026-10-15 19:00:00", "tier": "notice", "source": "b.sh", "subject": "S2", "group": "report"},
    ]
    with tempfile.TemporaryDirectory() as d:
        lp = Path(d) / "ledger.jsonl"
        lp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        loaded, missing = _load_ledger([str(lp)])
        assert len(loaded) == 3 and not missing, (len(loaded), missing)
        print("[selftest] ledger 加载 OK(3 行)")
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            report_ledger(loaded, days=7, now=datetime(2026, 10, 15, 23, 0))
        out = buf.getvalue()
        assert "多余行 1" in out, "重复行统计未生效:\n" + out
        assert "a.sh" in out, "top-talkers 未含 a.sh"
        print("[selftest] top-talkers / 重复率 OK")
        # 四元组扫描:合成两个脚本
        (Path(d) / "good.sh").write_text('"$PY" scripts/notify.py "x" "y" --severe --dedup-key k --dedup-window 3600\n', encoding="utf-8")
        (Path(d) / "bad.sh").write_text('"$PY" scripts/notify.py "x" "y"\n', encoding="utf-8")
        (Path(d) / "zero.sh").write_text('"$PY" scripts/notify.py "x" "y" --severe --dedup-key k --dedup-window 0\n', encoding="utf-8")
        # 散文提及(非调用)应被过滤
        (Path(d) / "prose.py").write_text('# 参见 scripts/notify.py 的说明\nx = 1\n', encoding="utf-8")
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            scan_four_tuple(d)
        out2 = buf2.getvalue()
        assert "good.sh" in out2 and "[OK ] good.sh" in out2, out2
        assert "bad.sh" in out2 and "tier未声明" in out2 and "dedup-key未声明" in out2, out2
        assert "zero.sh" in out2 and "dedup-window=0" in out2, out2
        assert "prose.py" not in out2, "散文提及未被过滤:\n" + out2
        print("[selftest] 四元组扫描 OK(OK/缺/违规 三态均判对;散文提及已过滤)")
    print("[selftest] ALLPASS")


def main(argv=None):
    ap = argparse.ArgumentParser(description="告警周 review 轻量工具(#264 包3 件F)")
    ap.add_argument("--ledger", action="append", default=None,
                    help="台账 jsonl 路径(可多次;缺省用云上两树候选)")
    ap.add_argument("--daily", default=None, help="alert_daily.json 路径(缺省云上候选)")
    ap.add_argument("--days", type=int, default=7, help="top-talkers 回看天数(默认 7)")
    ap.add_argument("--scripts-dir", default=None, help="scripts 目录(缺省=本脚本同级)")
    ap.add_argument("--check-four-tuple", action="store_true", help="跑四元组缺失扫描")
    ap.add_argument("--selftest", action="store_true", help="自测(合成台账,零外发)")
    args = ap.parse_args(argv)

    if args.selftest:
        _selftest()
        return 0

    sdir = args.scripts_dir or str(Path(__file__).resolve().parent)
    if args.check_four_tuple:
        scan_four_tuple(sdir)

    ledgers = args.ledger or DEFAULT_LEDGER_CANDIDATES
    rows, missing = _load_ledger(ledgers)
    if not rows:
        print(f"[warn] 未读到台账(缺:{missing})。台账在云上,请在云上跑或传 --ledger", file=sys.stderr)
        if not args.check_four_tuple:
            return 2
    else:
        report_ledger(rows, args.days)
    dailies = [args.daily] if args.daily else ALERT_DAILY_CANDIDATES
    report_recovery(dailies)
    return 0


if __name__ == "__main__":
    sys.exit(main())