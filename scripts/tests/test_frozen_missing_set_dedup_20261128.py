# -*- coding: utf-8 -*-
"""冻结表缺失告警「事件集合指纹」持久去重(2026-11-28 审查 B2 返修)回归套。

需求(返修指令第 2 条): 降噪走告警层——同一表外事件集合已实报过则后续静音(持久状态),
集合出现新键才再报;判别力保留(新缺失键必报);状态缺失/损坏 fail-open 照常告警。
2026-11-28 复审返修追加:
  · B1 投递判定 = notify status ∈ {sent,digested,suppressed},**不是 rc==0**——真实失败形态是
    rc=0 + status=failed(全渠道失败),此时不记状态、下次同集合必须再报(L49 禁假桩);
  · M3 同一集合距上次实报 >30 天周期重报一次并刷新时间戳,≤30 天静音。

同时覆盖:
  · S1 category 白名单(只认已定义类目);
  · S2 打桩有效性自证(归档/send 两个桩都真被调用 = 尺子本身有效);
  · 交付 config 复原为 122 条且不含 C_late_rowid_bulk_backfill 类目(审查 B1 回退)。

【零外发(§18 L48/L50)】全程 static-only: 真 send_alert 替换为记录参数的桩 +
`_zero_outbound.ZeroOutboundTrap` 兜底; 归档写盘替换为记录桩; 状态文件指到 pytest 临时目录。
【复现】/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q \\
          scripts/tests/test_frozen_missing_set_dedup_20261128.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

import _zero_outbound  # noqa: E402  (conftest 已把 scripts/tests 与 scripts 入 sys.path)

ROOT = Path(__file__).absolute().parent.parent.parent

sk = pytest.importorskip("signal_kelly_backtest", reason="CI 需 pyyaml 才能 import")
import app.notify_hook as notify_hook  # noqa: E402

EV_A = ("20261009", "csi_000813", "buy_aux")
EV_B = ("20261105", "dax", "buy_aux")
EV_C = ("20261126", "dax", "buy_aux")


class _Harness:
    def __init__(self, tmp_path, monkeypatch):
        self.tmp = tmp_path
        self.monkeypatch = monkeypatch
        self.seen_path = tmp_path / "alerts" / "kelly_frozen_missing_seen.json"
        self.sends = []
        self.archives = []
        # 真实 notify 形态: 正常路径恒 rc=0, 成败只看 status(全渠道失败时 rc=0 + status=failed)。
        self.rc = 0
        self.status = "sent"
        monkeypatch.setattr(sk, "FROZEN_MISSING_SEEN_PATH", str(self.seen_path))
        # 双保险隔离: env 优先于模块常量, 防外部环境把状态写到生产路径(M1 同精神)。
        monkeypatch.setenv(sk.FROZEN_MISSING_SEEN_ENV, str(self.seen_path))
        # 接受表指向不存在文件 = fail-safe 空表 ⇒ 传入事件全部视为「表外」。
        monkeypatch.setattr(sk, "FROZEN_MISSING_ACCEPTED_PATH", str(tmp_path / "no_accepted.json"))
        monkeypatch.setattr(sk, "_archive_frozen_missing_diagnostics", self._archive)
        monkeypatch.setattr(notify_hook, "send_alert", self._send)

    def _archive(self, events, accepted_hit, context=None):
        self.archives.append((set(events), set(accepted_hit), context))

    def _send(self, subject, body, **kwargs):
        self.sends.append({"subject": subject, "body": body, **kwargs})
        delivered = self.status in notify_hook.DELIVERED_STATUSES
        return types.SimpleNamespace(rc=self.rc,
                                     route="direct" if delivered else "failed",
                                     status=self.status)

    def alert(self, events):
        sk._alert_frozen_missing(set(events))

    def seen(self):
        return set(json.loads(self.seen_path.read_text(encoding="utf-8"))["seen_keys"])

    def stamps(self):
        return json.loads(self.seen_path.read_text(encoding="utf-8"))["fingerprints"]

    def age_stamps(self, seconds):
        """把状态里所有 last_reported 时间统一往回拨 seconds(模拟 30 天窗口边界)。"""
        import datetime as _dt
        data = json.loads(self.seen_path.read_text(encoding="utf-8"))
        old = (_dt.datetime.now() - _dt.timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S")
        data["fingerprints"] = {fp: old for fp in data["fingerprints"]}
        self.seen_path.write_text(json.dumps(data), encoding="utf-8")

    def stamp_of(self, keys):
        return self.stamps()[_fp(keys)]


def _fp(keys):
    return hashlib.sha256("\n".join(sorted(keys)).encode("utf-8")).hexdigest()


def test_first_set_alerts_then_same_set_silent(tmp_path, monkeypatch):
    """S2 尺子自证: 第一次调用两个桩都真被调到; 第二次同集合静音。"""
    h = _Harness(tmp_path, monkeypatch)
    with _zero_outbound.ZeroOutboundTrap() as trap:
        h.alert({EV_A, EV_B})
        assert len(h.sends) == 1, "首次集合应告警 1 次"
        assert len(h.archives) == 1, "首次集合应归档 1 次(证明归档桩真的接住了)"
        assert h.seen() == {f"{d}|{i}|{s}" for d, i, s in (EV_A, EV_B)}
        h.alert({EV_A, EV_B})
    assert len(h.sends) == 1, "同一集合第二次应静音"
    assert len(h.archives) == 1, "同一集合第二次不应重复归档"
    assert trap.hits == [], f"零外发被破坏: {trap.hits}"


def test_subset_of_seen_is_silent(tmp_path, monkeypatch):
    """集合缩小(无新键)不重复告警——「出现新缺失键才再报」。"""
    h = _Harness(tmp_path, monkeypatch)
    h.alert({EV_A, EV_B})
    h.alert({EV_A})
    assert len(h.sends) == 1
    assert h.seen() == {f"{d}|{i}|{s}" for d, i, s in (EV_A, EV_B)}


def test_new_key_alerts_and_fingerprint_changes(tmp_path, monkeypatch):
    """判别力: 出现新键 ⇒ 集合指纹变化 ⇒ 必报, 并并集持久化。"""
    h = _Harness(tmp_path, monkeypatch)
    h.alert({EV_A, EV_B})
    fp_before = h.sends[0]["dedup_key"]
    h.alert({EV_A, EV_B, EV_C})
    assert len(h.sends) == 2, "新缺失键必须再报"
    assert h.sends[1]["dedup_key"] != fp_before, "集合变化后 dedup key 必须变化"
    assert h.seen() == {f"{d}|{i}|{s}" for d, i, s in (EV_A, EV_B, EV_C)}
    # 再跑一次同集合(含新键后的完整集合)⇒ 静音
    h.alert({EV_A, EV_B, EV_C})
    assert len(h.sends) == 2


def test_dedup_key_is_set_fingerprint_and_window(tmp_path, monkeypatch):
    """去重键形态 = signal_kelly_frozen_missing|<sha256 前 16 位>, 窗口 = 30 天。"""
    h = _Harness(tmp_path, monkeypatch)
    h.alert({EV_A, EV_B})
    kw = h.sends[0]
    keys = {f"{d}|{i}|{s}" for d, i, s in (EV_A, EV_B)}
    assert kw["dedup_key"] == f"signal_kelly_frozen_missing|{_fp(keys)[:16]}"
    assert kw["dedup_window"] == 30 * 24 * 3600
    assert len(kw["dedup_key"].split("|")[1]) == 16


def test_missing_state_failsafe_alerts(tmp_path, monkeypatch):
    """状态文件缺失 ⇒ fail-open 照常告警一次。"""
    h = _Harness(tmp_path, monkeypatch)
    assert not h.seen_path.exists()
    h.alert({EV_A})
    assert len(h.sends) == 1
    assert h.seen_path.exists()


def test_corrupt_state_failsafe_alerts(tmp_path, monkeypatch):
    """状态文件损坏/形状不对 ⇒ fail-open 照常告警(绝不静默)。"""
    h = _Harness(tmp_path, monkeypatch)
    h.seen_path.parent.mkdir(parents=True, exist_ok=True)
    h.seen_path.write_text("{not json", encoding="utf-8")
    h.alert({EV_A})
    assert len(h.sends) == 1
    h.seen_path.write_text(json.dumps({"seen_keys": "not-a-list"}), encoding="utf-8")
    h.alert({EV_A})
    assert len(h.sends) == 2


def test_state_write_failure_fails_open(tmp_path, monkeypatch):
    """状态写失败 ⇒ 只留痕, 下次同集合照常重发(fail-open, 绝不永久静默)。"""
    h = _Harness(tmp_path, monkeypatch)
    monkeypatch.setattr(sk, "atomic_write_json",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    h.alert({EV_A})
    assert len(h.sends) == 1
    assert not h.seen_path.exists()
    h.alert({EV_A})
    assert len(h.sends) == 2, "状态写失败后应按无状态照常重发"


def test_all_channel_failure_rc0_does_not_record_state(tmp_path, monkeypatch):
    """B1 真实失败形态: rc=0 + status=failed(notify 全渠道失败)⇒ 不记状态, 下次再报。

    L49 假样本教训: 禁止用 rc=1 假桩代替真实形态——生产上 notify 失败恰恰是 rc=0。
    """
    h = _Harness(tmp_path, monkeypatch)
    h.rc = 0
    h.status = "failed"
    h.alert({EV_A})
    assert len(h.sends) == 1
    assert not h.seen_path.exists(), "全渠道失败(rc=0/status=failed)不应落状态"
    h.alert({EV_A})
    assert len(h.sends) == 2, "未投递就绝不能静音: 下次同集合必须再告警"
    # 真投递成功后落状态 → 再同集合静音
    h.status = "sent"
    h.alert({EV_A})
    assert len(h.sends) == 3
    assert h.seen_path.exists()
    h.alert({EV_A})
    assert len(h.sends) == 3, "真投递后同集合应静音"


@pytest.mark.parametrize("status,recorded", [
    ("sent", True), ("digested", True), ("suppressed", True),
    ("failed", False), ("noop", False), (None, False),
])
def test_only_delivered_statuses_record_state(tmp_path, monkeypatch, status, recorded):
    """投递判定单一事实源 = notify_hook.DELIVERED_STATUSES(不看 rc, rc 恒 0)。"""
    h = _Harness(tmp_path, monkeypatch)
    h.status = status
    h.alert({EV_A})
    assert len(h.sends) == 1
    assert h.seen_path.exists() == recorded, f"status={status!r} 落状态={recorded}"


def test_first_report_records_last_reported_timestamp(tmp_path, monkeypatch):
    """首次告警后状态文件记下该集合指纹的 last_reported 时间戳。"""
    h = _Harness(tmp_path, monkeypatch)
    keys = {f"{d}|{i}|{s}" for d, i, s in (EV_A, EV_B)}
    assert not h.seen_path.exists()
    h.alert({EV_A, EV_B})
    stamp = h.stamp_of(keys)
    import datetime as _dt
    ts = _dt.datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
    assert abs((_dt.datetime.now() - ts).total_seconds()) < 120, stamp


def test_same_set_within_30_days_is_silent(tmp_path, monkeypatch):
    """同集合距上次实报 <30 天 ⇒ 静音(不打桩 rc, 只看 status 成功基线)。"""
    h = _Harness(tmp_path, monkeypatch)
    keys = {f"{d}|{i}|{s}" for d, i, s in (EV_A, EV_B)}
    h.alert({EV_A, EV_B})
    old_stamp = h.stamp_of(keys)
    h.age_stamps(29 * 24 * 3600)
    aged_stamp = h.stamp_of(keys)
    h.alert({EV_A, EV_B})
    assert len(h.sends) == 1, "29 天应仍在静音窗口内"
    assert h.stamp_of(keys) == aged_stamp != old_stamp, "静音时不得刷新时间戳"


def test_same_set_after_30_days_realerts_and_refreshes(tmp_path, monkeypatch):
    """同集合距上次实报 >30 天 ⇒ 周期重报一次并刷新时间戳(真故障不永久沉默)。"""
    h = _Harness(tmp_path, monkeypatch)
    keys = {f"{d}|{i}|{s}" for d, i, s in (EV_A, EV_B)}
    h.alert({EV_A, EV_B})
    h.age_stamps(31 * 24 * 3600)
    old_stamp = h.stamp_of(keys)
    h.alert({EV_A, EV_B})
    assert len(h.sends) == 2, "超过 30 天必须周期重报一次"
    new_stamp = h.stamp_of(keys)
    assert new_stamp != old_stamp, "重报后时间戳必须刷新"
    import datetime as _dt
    ts = _dt.datetime.strptime(new_stamp, "%Y-%m-%d %H:%M:%S")
    assert abs((_dt.datetime.now() - ts).total_seconds()) < 120, new_stamp
    h.alert({EV_A, EV_B})
    assert len(h.sends) == 2, "重报后同集合应重新进入静音窗口"


def test_loader_category_whitelist(tmp_path, monkeypatch):
    """S1: 未定义类目即使三字段齐全也不生效; 已定义类目生效。"""
    p = tmp_path / "accepted.json"
    p.write_text(json.dumps({"accepted": [
        {"key": "20261009|csi_000813|buy_aux", "category": "C_unknown_new_category",
         "evidence": "x"},
        {"key": "20261105|dax|buy_aux", "category": "B_changed_appeared_chain",
         "evidence": "x"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(sk, "FROZEN_MISSING_ACCEPTED_PATH", str(p))
    assert sk._load_frozen_missing_accepted() == {"20261105|dax|buy_aux"}


def test_verify_script_isolates_production_state(tmp_path):
    """M1 回归: verify dry 脚本跑完不写仓库生产状态文件(否则会把留报键预静音)。

    真实跑子进程(脚本内部 send/archive 已打桩, 零外发), 用 114 条非 legacy accepted +
    7 条必留报键合成 121 条基线归档; 断言 DRY_PASS 且生产状态文件存在性前后不变。
    """
    config = ROOT / "config/signal_kelly_frozen_missing_accepted.json"
    accepted = json.loads(config.read_text(encoding="utf-8"))["accepted"]
    keys = [e["key"] for e in accepted
            if e["category"] != "legacy_accepted_20260921_20261011"]
    keep = [
        "20261009|csi_000330|buy_aux", "20261009|csi_970070|buy_aux",
        "20261009|sz_div|buy", "20261019|csi_000813|buy_aux",
        "20261105|dax|buy_special", "20261111|cac40|buy_special",
        "20261113|csi_931946|buy_special",
    ]
    archive = tmp_path / "archive.json"
    archive.write_text(json.dumps({"filtered_missing": keys + keep}), encoding="utf-8")
    state_path = ROOT / "data/alerts/kelly_frozen_missing_seen.json"
    existed = state_path.exists()
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/verify_kelly_frozen_missing_denoise_20261119.py"),
         "--archive", str(archive), "--config", str(config)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DRY_PASS" in r.stdout, r.stdout
    assert state_path.exists() == existed, "verify 脚本写了生产状态文件(M1 回归)"


def test_shipped_config_reverted_to_122_without_late_rowid_category():
    """审查 B1 回退证据: 交付 config 恢复 122 条, 不含 C_late_rowid_bulk_backfill。"""
    data = json.loads((ROOT / "config/signal_kelly_frozen_missing_accepted.json")
                      .read_text(encoding="utf-8"))
    entries = data["accepted"]
    assert len(entries) == 122, f"应为 122 条, 实得 {len(entries)}"
    categories = {e["category"] for e in entries}
    assert "C_late_rowid_bulk_backfill" not in categories, categories
    assert categories == {
        "legacy_accepted_20260921_20261011",
        "A_new_listing_etf_no_tradable_historically",
        "B_changed_appeared_chain",
    }, categories
