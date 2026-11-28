# -*- coding: utf-8 -*-
"""冻结表缺失告警「事件集合指纹」持久去重(2026-11-28 审查 B2 返修)回归套。

需求(返修指令第 2 条): 降噪走告警层——同一表外事件集合已报过则后续静音(持久状态),
集合出现新键才再报;判别力保留(新缺失键必报);状态缺失/损坏 fail-open 照常告警。

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
        self.rc = 0
        monkeypatch.setattr(sk, "FROZEN_MISSING_SEEN_PATH", str(self.seen_path))
        # 接受表指向不存在文件 = fail-safe 空表 ⇒ 传入事件全部视为「表外」。
        monkeypatch.setattr(sk, "FROZEN_MISSING_ACCEPTED_PATH", str(tmp_path / "no_accepted.json"))
        monkeypatch.setattr(sk, "_archive_frozen_missing_diagnostics", self._archive)
        monkeypatch.setattr(notify_hook, "send_alert", self._send)

    def _archive(self, events, accepted_hit, context=None):
        self.archives.append((set(events), set(accepted_hit), context))

    def _send(self, subject, body, **kwargs):
        self.sends.append({"subject": subject, "body": body, **kwargs})
        return types.SimpleNamespace(rc=self.rc, route="direct" if self.rc == 0 else "failed")

    def alert(self, events):
        sk._alert_frozen_missing(set(events))

    def seen(self):
        return set(json.loads(self.seen_path.read_text(encoding="utf-8"))["seen_keys"])


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


def test_send_failure_does_not_record_state(tmp_path, monkeypatch):
    """发送失败 ⇒ 不记状态, 下次同集合照常重试(notice 可重发)。"""
    h = _Harness(tmp_path, monkeypatch)
    h.rc = 1
    h.alert({EV_A})
    assert len(h.sends) == 1
    assert not h.seen_path.exists(), "失败不应落状态"
    h.rc = 0
    h.alert({EV_A})
    assert len(h.sends) == 2
    assert h.seen_path.exists()


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
