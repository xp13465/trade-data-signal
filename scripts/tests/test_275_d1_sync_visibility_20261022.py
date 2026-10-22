# -*- coding: utf-8 -*-
"""#275 D1 同步失败可见化 + 凭据巡检回归测试(2026-10-22)。

背景: `sync_fund_score_to_d1.sh` 自 2026-10-01 起连续 **39 次**失败(云上 wrangler 未登录),
调用方只 echo「失败不阻塞主流程」⇒ D1 数据静默停更 20 天。修法:
  - 同步脚本失败时写 `<REPO>/data/d1_sync_state/<script>.json`(连续计数, 原子写), 成功删除;
  - 既有巡检 check_failed_units.py 消费: 连续 >= 2 次 ⇒ **只告警一次**(alerted 标记防轰炸);
  - 同步开始前 `wrangler whoami` 预检, 凭据无效 = 明确错误(且绝不打印 token)。

证据用例(任务书口径):
  ① 连续 2 次失败 ⇒ 恰好 1 条告警(含脚本名/连续次数/首失败时间/最后错误/凭据状态)
  ② 第 3 次失败不重复告警
  ③ 成功 ⇒ 状态清零, 不告警
  ④ 单次失败 ⇒ 不告警
  ⑤ whoami 失败 ⇒ 凭据类明确错误(模块级 + bash 端到端)
  ⑥ 真实成功路径不残留状态(bash 端到端: 假 wrangler 全链路跑真脚本)
  + 告警未送达 ⇒ rc=4 且不落 alerted(下轮重试, 不吞真故障)
  + dry 模式绝不动通知链(L48 零外发)
  + 状态写失败可见化(2026-10-22 审查缺口 A): 目录不可写 ⇒ 记录器 rc!=0 + 摘要,
    bash `_fail` 转述摘要(旧版 >/dev/null 2>&1 ⇒ 零输出静默); 全程不含 token

跑法: python3 -m pytest -q scripts/tests/test_275_d1_sync_visibility_20261022.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import check_failed_units as cfu  # noqa: E402
import d1_sync_state as d1ss  # noqa: E402

ROOT = Path(__file__).absolute().parent.parent.parent
SYNC_SCORE = ROOT / "scripts" / "sync_fund_score_to_d1.sh"

_ERROR = "wrangler 凭据无效/过期（whoami 失败）。请重新登录: npx wrangler login"


class _NotifySpy:
    """替掉 cfu._send_notify: 记录调用, 绝不触达真通知链(L48)。"""

    def __init__(self, sent=True):
        self.sent = sent
        self.calls = []

    def __call__(self, repo, subject, body, dedup_key=None):
        self.calls.append({"subject": subject, "body": body, "dedup_key": dedup_key})
        if self.sent:
            return True, "status=sent channels={'email': True}"
        return False, "status=failed channels={'email': False}"


def _repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "data").mkdir(parents=True)
    return repo


def _state_dir(repo):
    return repo / "data" / d1ss.STATE_DIRNAME


def _fail_n(repo, script, n, credential="invalid", error=_ERROR, start_hour=10):
    for i in range(n):
        d1ss.record_failure(_state_dir(repo), script, error, credential=credential,
                            now=datetime(2026, 10, 22, start_hour, i))


# ══════════════════════════════════════════════════════════════════
# ① 连续 2 次 ⇒ 恰好 1 条告警(内容齐全)
# ══════════════════════════════════════════════════════════════════
def test_case1_two_failures_exactly_one_alert(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path)
    _fail_n(repo, "sync_fund_score_to_d1", 2)
    spy = _NotifySpy()
    monkeypatch.setattr(cfu, "_send_notify", spy)

    rc = cfu._check_d1_sync(repo, do_notify=True)
    assert rc == 1
    assert len(spy.calls) == 1, f"连续 2 次失败应恰好 1 条告警, 实际 {len(spy.calls)}"
    call = spy.calls[0]
    assert call["dedup_key"] == d1ss.DEDUP_KEY
    for must in ("sync_fund_score_to_d1", "连续 2 次", "2026-10-22 10:00:00",
                 "wrangler 凭据无效/过期", "无效/过期"):
        assert must in call["body"], f"告警正文缺 {must!r}: {call['body']}"
    st = d1ss.load_state(_state_dir(repo), "sync_fund_score_to_d1")
    assert st is not None and st["alerted"] is True, "发出后必须落 alerted 标记"


# ══════════════════════════════════════════════════════════════════
# ② 第 3 次失败不重复告警
# ══════════════════════════════════════════════════════════════════
def test_case2_third_failure_no_repeat(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path)
    _fail_n(repo, "sync_fund_score_to_d1", 2)
    spy = _NotifySpy()
    monkeypatch.setattr(cfu, "_send_notify", spy)
    cfu._check_d1_sync(repo, do_notify=True)
    assert len(spy.calls) == 1

    d1ss.record_failure(_state_dir(repo), "sync_fund_score_to_d1", _ERROR,
                        credential="invalid", now=datetime(2026, 10, 22, 11, 0))
    rc = cfu._check_d1_sync(repo, do_notify=True)
    out = capsys.readouterr().out
    assert rc == 0, "已告警过的连续段不应再产生行动"
    assert len(spy.calls) == 1, f"第 3 次失败不得重复告警, 实际 {len(spy.calls)}"
    assert "已告警过, 不重复" in out


# ══════════════════════════════════════════════════════════════════
# ③ 成功 ⇒ 清零且不告警
# ══════════════════════════════════════════════════════════════════
def test_case3_success_clears_and_no_alert(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _fail_n(repo, "sync_fund_score_to_d1", 2)
    assert d1ss.record_success(_state_dir(repo), "sync_fund_score_to_d1") is True
    assert not list(_state_dir(repo).glob("*.json")), "成功后不得残留状态文件"

    spy = _NotifySpy()
    monkeypatch.setattr(cfu, "_send_notify", spy)
    rc = cfu._check_d1_sync(repo, do_notify=True)
    assert rc == 0 and spy.calls == []


# ══════════════════════════════════════════════════════════════════
# ④ 单次失败 ⇒ 不告警
# ══════════════════════════════════════════════════════════════════
def test_case4_single_failure_no_alert(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path)
    _fail_n(repo, "sync_fund_score_to_d1", 1)
    spy = _NotifySpy()
    monkeypatch.setattr(cfu, "_send_notify", spy)
    rc = cfu._check_d1_sync(repo, do_notify=True)
    out = capsys.readouterr().out
    assert rc == 0 and spy.calls == [], "单次失败属偶发, 不告警"
    assert "未达告警阈值" in out


# ══════════════════════════════════════════════════════════════════
# 未送达 ⇒ rc=4 且不落 alerted(下轮重试)
# ══════════════════════════════════════════════════════════════════
def test_undelivered_alert_returns_4_and_keeps_retrying(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _fail_n(repo, "sync_fund_score_to_d1", 2)
    spy = _NotifySpy(sent=False)
    monkeypatch.setattr(cfu, "_send_notify", spy)
    rc = cfu._check_d1_sync(repo, do_notify=True)
    assert rc == 4
    st = d1ss.load_state(_state_dir(repo), "sync_fund_score_to_d1")
    assert st["alerted"] is False, "未送达不得落 alerted(否则该连续段永不重试)"
    # 下一轮再来: 仍会尝试发送一次
    rc2 = cfu._check_d1_sync(repo, do_notify=True)
    assert rc2 == 4 and len(spy.calls) == 2


# ══════════════════════════════════════════════════════════════════
# dry 模式零外发
# ══════════════════════════════════════════════════════════════════
def test_dry_run_never_calls_notify(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _fail_n(repo, "sync_fund_score_to_d1", 2)

    def _boom(*a, **kw):  # pragma: no cover
        raise AssertionError("dry-run 不得触达通知链(L48)")

    monkeypatch.setattr(cfu, "_send_notify", _boom)
    rc = cfu._check_d1_sync(repo, do_notify=False)
    assert rc == 1
    st = d1ss.load_state(_state_dir(repo), "sync_fund_score_to_d1")
    assert st["alerted"] is False, "dry 不得改生产状态"


# ══════════════════════════════════════════════════════════════════
# ⑤ 凭据预检: whoami 失败 ⇒ 凭据类明确错误(且不打印 token)
# ══════════════════════════════════════════════════════════════════
def _fake_npx(bin_dir: Path, mode: str) -> None:
    """假 npx: whoami 失败/成功 + d1 execute 成功(count 返回 1) —— 零网络。"""
    bin_dir.mkdir(parents=True, exist_ok=True)
    p = bin_dir / "npx"
    if mode == "fail":
        body = ('#!/bin/bash\n'
                'if [ "$1" = "wrangler" ] && [ "$2" = "whoami" ]; then\n'
                "  echo 'You are not authenticated. Please run wrangler login.' >&2\n"
                '  exit 1\n'
                'fi\n'
                'exit 1\n')
    else:
        body = ('#!/bin/bash\n'
                'if [ "$1" = "wrangler" ] && [ "$2" = "whoami" ]; then\n'
                '  echo "You are logged in with an OAuth Token."\n'
                '  exit 0\n'
                'fi\n'
                'if [ "$1" = "wrangler" ] && [ "$2" = "d1" ]; then\n'
                '  case "$*" in\n'
                '    *--json*) echo \'[{"results":[{"n":1}],"success":true}]\' ;;\n'
                '    *) echo "Executed 1 command" ;;\n'
                '  esac\n'
                '  exit 0\n'
                'fi\n'
                'exit 0\n')
    p.write_text(body, encoding="utf-8")
    p.chmod(0o755)


def test_credential_precheck_returns_invalid_without_token(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    _fake_npx(bin_dir, "fail")
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "SECRET-TOKEN-XYZ")
    rc, msg = d1ss.check_wrangler_credentials(timeout=10)
    assert rc == 1, msg
    assert "凭据无效/过期" in msg
    assert "SECRET-TOKEN-XYZ" not in msg, "凭据预检输出绝不能带 token"


def test_timeout_or_missing_npx_is_unknown(monkeypatch):
    """npx 不存在 ⇒ 2(无法验证, 按失败处理), 不误判成"凭据无效"。"""
    monkeypatch.setenv("PATH", "/nonexistent-dir-for-test")
    rc, msg = d1ss.check_wrangler_credentials(timeout=5)
    assert rc == 2 and "npx 不存在" in msg


# ══════════════════════════════════════════════════════════════════
# bash 端到端: 真脚本 + 假 npx(零网络/零云上)
# ══════════════════════════════════════════════════════════════════
_FIXTURE_DDL = """
CREATE TABLE fund_basic (fund_code TEXT, fund_name TEXT, fund_type TEXT, fund_company TEXT,
  fund_manager TEXT, setup_date TEXT, scale REAL, management_fee REAL, custody_fee REAL,
  purchase_fee REAL, strategy TEXT, benchmark TEXT);
CREATE TABLE fund_score (fund_code TEXT, score_date TEXT, composite_score REAL, star_rating INTEGER,
  score_return REAL, score_risk_adjusted REAL, score_drawdown REAL, score_stability REAL,
  score_scale REAL, score_fee REAL, sharpe REAL, sortino REAL, calmar REAL, information_ratio REAL,
  alpha REAL, manager_score REAL, m1_tenure REAL, m2_scale REAL, m3_perf_stability REAL,
  m4_drawdown REAL, m5_coherence REAL, m6_focus REAL, kelly_fraction REAL,
  half_kelly_position REAL, kelly_win_rate REAL, kelly_win_loss_ratio REAL, kelly_tier TEXT,
  market_adjustment REAL, final_suggestion REAL, benchmark TEXT, score_method TEXT,
  data_completeness REAL, update_date TEXT);
INSERT INTO fund_basic VALUES ('F1','基金一','股票型','公司A','经理甲','20150501',
  12.5,1.5,0.25,0.15,'策略1','基准1');
INSERT INTO fund_score (fund_code, score_date, composite_score, star_rating, update_date)
  VALUES ('F1','20261021',70.0,4,'20261021');
"""


def _make_sync_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "sync-repo"
    (repo / "data").mkdir(parents=True)
    (repo / ".venv" / "bin").mkdir(parents=True)
    (repo / ".venv" / "bin" / "python").symlink_to(sys.executable)
    con = sqlite3.connect(repo / "data" / "public_fund.db")
    con.executescript(_FIXTURE_DDL)
    con.commit()
    con.close()
    return repo


def _run_sync(repo: Path, npx_mode: str, tmp_path: Path):
    bin_dir = tmp_path / f"bin-{npx_mode}"
    _fake_npx(bin_dir, npx_mode)
    env = dict(os.environ)
    env.update({
        "REPO": str(repo), "GIT_REPO": str(repo),
        "PATH": f"{bin_dir}:{env.get('PATH', '')}",
        "CLOUDFLARE_API_TOKEN": "SECRET-TOKEN-XYZ",
    })
    r = subprocess.run(["bash", str(SYNC_SCORE)], capture_output=True, text=True,
                       env=env, timeout=120, check=False)
    return r


def test_case5b_bash_whoami_failure_records_credential_error(tmp_path):
    repo = _make_sync_repo(tmp_path)
    r = _run_sync(repo, "fail", tmp_path)
    assert r.returncode == 1, f"whoami 失败应 rc=1\n{r.stdout}\n{r.stderr}"
    assert "凭据无效/过期" in r.stderr, r.stderr
    st = d1ss.load_state(_state_dir(repo), "sync_fund_score_to_d1")
    assert st is not None, "失败必须落状态文件(巡检才能看见)"
    assert st["consecutive_failures"] == 1
    assert st["credential"] == "invalid"
    leaked = r.stdout + r.stderr + json.dumps(st, ensure_ascii=False)
    assert "SECRET-TOKEN-XYZ" not in leaked, "任何输出/状态都不得带 token"


def test_case7_state_write_failure_is_loud_not_silent(tmp_path):
    """审查缺口 A(2026-10-22 批内修): 状态目录不可写 ⇒ 记录器 rc!=0 + stderr 摘要。

    旧版写失败只 warn(stderr) 且 rc 恒 0, 同步脚本又 `>/dev/null 2>&1` ⇒ 复合命令
    零输出、无状态文件 —— 「巡检看不见本次失败」这件事本身也静默。
    """
    if os.geteuid() == 0:  # root 无视目录权限, 无法构造不可写(CI 为普通用户)
        pytest.skip("root 下 chmod 不生效, 无法复现不可写目录")
    ro_parent = tmp_path / "ro"
    ro_parent.mkdir()
    state_dir = ro_parent / d1ss.STATE_DIRNAME
    ro_parent.chmod(0o500)
    try:
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "d1_sync_state.py"), "record-failure",
             "--script", "sync_fund_score_to_d1", "--error", "boom",
             "--credential", "invalid", "--state-dir", str(state_dir)],
            capture_output=True, text=True, timeout=60, check=False)
    finally:
        ro_parent.chmod(0o755)
    assert r.returncode != 0, f"状态写失败必须非零退出(旧版静默 rc=0): {r.stdout}\n{r.stderr}"
    assert "失败状态写入失败" in r.stderr, f"必须给出可见错误摘要: {r.stderr}"
    assert str(state_dir) in r.stderr, "摘要须带路径, 便于现场定位"
    if state_dir.exists():
        assert not list(state_dir.glob("*.json")), "写失败时不得留下半截状态文件"


@pytest.mark.skipif(os.geteuid() == 0, reason="root 下目录权限不生效")
def test_case8_bash_fail_path_surfaces_state_write_error(tmp_path):
    """bash 端到端: 状态写失败时 `_fail` 必须把摘要转述到脚本日志(不再整段丢弃)。"""
    repo = _make_sync_repo(tmp_path)
    (repo / "data").chmod(0o500)  # DB 仍可读, 但状态目录无法创建/写入
    try:
        r = _run_sync(repo, "fail", tmp_path)
    finally:
        (repo / "data").chmod(0o755)
    assert r.returncode == 1, f"同步失败码保持 1(whoami 失败): {r.stdout}\n{r.stderr}"
    assert "失败状态写入失败（巡检会漏报本次失败）" in r.stderr, \
        f"写状态失败必须可见(旧版被 2>&1 吞掉): {r.stderr}"
    assert "原因:" in r.stderr, f"须转述记录器摘要: {r.stderr}"
    assert "SECRET-TOKEN-XYZ" not in (r.stdout + r.stderr), "转述摘要绝不能带 token"


def test_case6_bash_success_path_leaves_no_state(tmp_path):
    repo = _make_sync_repo(tmp_path)
    # 先制造一段失败, 证明成功会清零
    _fail_n(repo, "sync_fund_score_to_d1", 2)
    assert list(_state_dir(repo).glob("*.json"))
    r = _run_sync(repo, "ok", tmp_path)
    assert r.returncode == 0, f"假 wrangler 全成功应 rc=0\n{r.stdout}\n{r.stderr}"
    assert "同步成功且校验一致" in r.stdout, r.stdout
    leftovers = list(_state_dir(repo).glob("*")) if _state_dir(repo).is_dir() else []
    assert leftovers == [], f"成功路径不得残留状态(含 .tmp): {leftovers}"
    assert "SECRET-TOKEN-XYZ" not in (r.stdout + r.stderr)