# -*- coding: utf-8 -*-
"""#309 收尾 C: 结案行真实 sub-rc → last_exit≠0 + exit_source 正确(2026-10-31, V4)。

验证 `intraday_snapshot.sh` / `us_stock_morning.sh` 结案行改写后, gen_schedule_stats
解析能得到真实 sub-rc(不再被字面 退出码=0 吞掉):
  - intraday: `退出码=$SNAP_RC 采集=${ETF_RC:-0}` —— ETF 失败(采集≠0)⇒ log-collect severe;
  - us_stock: `退出码=$COLLECT_RC 采集=$COLLECT_RC deploy=$DEPLOY_RC` —— deploy 失败 ⇒ log-deploy warning;
  - 主码非 0 ⇒ log severe。
全程用 gen_schedule_stats 真实正则 + _log_exit_evidence 纯函数, 不跑业务脚本。
"""
import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).absolute().parent.parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import gen_schedule_stats as gss

_TS = r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})'
END_RE = re.compile(r'=== (\S+\.sh) 结束.*?' + _TS + r'(?:.*?退出码=(\d+))?')


def _parse_end_line(line):
    """复用 gen_schedule_stats 的 END_RE + 子字段正则解析结案行 → meta dict。"""
    m = END_RE.search(line)
    assert m, f"END_RE 未命中: {line}"
    tail = line[m.start():]
    exit_field = None
    deploy = None
    collect = None
    em = gss._EXIT_FIELD_RE.search(tail)
    if em:
        exit_field = int(em.group(1))
    dm = gss._DEPLOY_FIELD_RE.search(tail)
    if dm:
        deploy = int(dm.group(1))
    cm = gss._COLLECT_FIELD_RE.search(tail)
    if cm:
        collect = int(cm.group(1))
    return {"exit_field": exit_field, "deploy": deploy, "collect": collect}


def test_intraday_etf_fail_surfaces_as_log_collect():
    """intraday: 采集(ETF)=N≠0, 退出码=0 ⇒ last_exit=N, source=log-collect, severe。"""
    line = "=== intraday_snapshot.sh 结束 2026-10-31 10:05:00 退出码=0 采集=1 ==="
    meta = _parse_end_line(line)
    ev = gss._log_exit_evidence(meta)
    assert ev["code"] == 1
    assert ev["source"] == "log-collect"
    assert ev["tier"] == "severe"
    assert ev["collect_failed"] is True


def test_intraday_all_ok_zero():
    """intraday: 退出码=0 采集=0 ⇒ last_exit=0(source=log, tier=None)。"""
    line = "=== intraday_snapshot.sh 结束 2026-10-31 10:05:00 退出码=0 采集=0 ==="
    meta = _parse_end_line(line)
    ev = gss._log_exit_evidence(meta)
    assert ev["code"] == 0
    assert ev["source"] == "log"


def test_us_stock_deploy_fail_surfaces_as_log_deploy():
    """us_stock: 退出码=0 采集=0 deploy=1 ⇒ log-deploy warning(子步骤失败不被吞)。"""
    line = "=== us_stock_morning.sh 结束 2026-10-31 05:10:00 退出码=0 采集=0 deploy=1 ==="
    meta = _parse_end_line(line)
    ev = gss._log_exit_evidence(meta)
    assert ev["code"] == 1
    assert ev["source"] == "log-deploy"
    assert ev["tier"] == "warning"


def test_us_stock_collect_fail_severe():
    """us_stock: 采集≠0 ⇒ log-collect severe(数据层真故障)。"""
    line = "=== us_stock_morning.sh 结束 2026-10-31 05:10:00 退出码=1 采集=1 deploy=0 ==="
    meta = _parse_end_line(line)
    ev = gss._log_exit_evidence(meta)
    assert ev["code"] == 1
    assert ev["source"] == "log"
    assert ev["tier"] == "severe"


def test_source_scripts_no_hardcoded_zero_in_target_lines():
    """形状守卫: 目标两脚本的结案行已不含字面 `退出码=0`(已改 $VAR)。"""
    root = Path(__file__).absolute().parent.parent.parent / "scripts"
    intraday = (root / "intraday_snapshot.sh").read_text(encoding="utf-8")
    us_stock = (root / "us_stock_morning.sh").read_text(encoding="utf-8")
    for name, text in (("intraday_snapshot.sh", intraday), ("us_stock_morning.sh", us_stock)):
        for line in text.splitlines():
            if "结束" in line and "退出码=0" in line and "===" in line:
                # 允许的早期失败路径写 退出码=$VAR; 字面 0 不应再出现在主结案行
                pytest.fail(f"{name} 仍含字面 退出码=0 结案行: {line.strip()}")
