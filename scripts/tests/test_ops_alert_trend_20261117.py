#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""admin/ops 每日告警量走势（2026-11-17 需求，方案 B）纯函数自验。

覆盖：
  A. 窗口与日期归一化：显式末日 + 7/90 天窗口、升序连续、90 天截断；
  B. 缺日判定：无 alert 行的天 = no_data=True 且各计数 0（不是「当天零告警」）；
  C. 口径恒等式：真故障 + 噪音 = 总数（直接复用 alert_noise_count.classify_rows）；
  D. 幂等/确定性：同台账同末日两次重算逐位一致（无墙钟），写进每棵树且内容相同；
  E. 跨树聚合：两棵树的台账合并计数（§22 多树一致）；
  F. 冻结运行日：显式 end_day 时 build_trend/trend_recount 不得取真实 today()（L51）。

说明：POST payload 校验（坏日期/重复日/负数/真故障+噪音≠总数/91 天上限）与
       GET 鉴权、缺日合成、不变不写、180 天保留，由真 Miniflare 路由测试覆盖：
       ops/monitoring/tests/worker-alert-trend.test.mjs。
跑法：python3 -m pytest -q scripts/tests/test_ops_alert_trend_20261117.py
"""
import hashlib
import json
from pathlib import Path

import alert_meter


def _row(day: str, tier: str, subject: str, noise_class: str | None = None) -> dict:
    rec = {"ts": f"{day} 09:00:00", "group": "alert", "tier": tier, "subject": subject,
           "key": subject, "source": "fixture", "channels": ["feishu"]}
    if noise_class:
        rec["noise_class"] = noise_class
    return rec


def _write_ledger(tree: Path, records: list[dict]) -> None:
    path = alert_meter.ledger_path(tree)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                    encoding="utf-8")


def _tree(tmp_path: Path, name: str, records: list[dict]) -> Path:
    tree = tmp_path / name
    _write_ledger(tree, records)
    return tree


def _sample_records(day: str) -> list[dict]:
    # 2 条真故障（不同 subject 避免被判 repeat）+ 1 条 digest 噪音。
    return [
        _row(day, "notice", "磁盘使用率偏高 a"),
        _row(day, "warning", "采集任务超时 b"),
        _row(day, "digest", "每日摘要 c"),
    ]


def test_window_and_date_normalisation(tmp_path):
    tree = _tree(tmp_path, "t1", _sample_records("2026-11-17"))
    trend = alert_meter.build_trend([tree], "2026-11-17", days=7)
    assert trend["window"] == ["2026-11-11", "2026-11-17"]
    assert trend["days_count"] == 7
    assert [d["date"] for d in trend["days"]] == [
        "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14",
        "2026-11-15", "2026-11-16", "2026-11-17"]
    # 末日之外的行不进入窗口
    assert trend["days"][-1]["total"] == 3


def test_ninety_day_truncation(tmp_path):
    tree = _tree(tmp_path, "t1", _sample_records("2026-11-17"))
    trend = alert_meter.build_trend([tree], "2026-11-17", days=90)
    assert trend["days_count"] == 90
    assert trend["window"] == ["2026-08-20", "2026-11-17"]
    assert trend["days"][0]["date"] == "2026-08-20"
    assert trend["days"][-1]["date"] == "2026-11-17"


def test_missing_day_is_no_data_not_zero(tmp_path):
    tree = _tree(tmp_path, "t1", _sample_records("2026-11-17"))
    trend = alert_meter.build_trend([tree], "2026-11-17", days=7)
    gap = trend["days"][1]  # 2026-11-12 台账无行
    assert gap["date"] == "2026-11-12"
    assert gap["no_data"] is True
    assert (gap["total"], gap["real"], gap["noise"], gap["escalation"]) == (0, 0, 0, 0)
    assert gap["by_tier"] == {}


def test_real_plus_noise_equals_total_and_escalation(tmp_path):
    tree = _tree(tmp_path, "t1", _sample_records("2026-11-17") + [
        _row("2026-11-16", "critical", "升级提醒 x", noise_class="escalation"),
        _row("2026-11-16", "critical", "数据库连接失败 y"),
    ])
    trend = alert_meter.build_trend([tree], "2026-11-17", days=7)
    for d in trend["days"]:
        assert d["real"] + d["noise"] == d["total"], d
    by_day = {d["date"]: d for d in trend["days"]}
    assert (by_day["2026-11-17"]["total"], by_day["2026-11-17"]["real"],
            by_day["2026-11-17"]["noise"]) == (3, 2, 1)
    esc = by_day["2026-11-16"]
    assert (esc["total"], esc["real"], esc["noise"], esc["escalation"]) == (2, 1, 1, 1)
    assert esc["by_tier"] == {"critical": 2}
    assert by_day["2026-11-17"]["by_tier"] == {"digest": 1, "notice": 1, "warning": 1}


def test_idempotent_recount_writes_every_tree(tmp_path):
    recs = _sample_records("2026-11-17")
    a = _tree(tmp_path, "tree-a", recs)
    b = _tree(tmp_path, "tree-b", [])
    first = alert_meter.trend_recount([a, b], "2026-11-17")
    assert len(first["written"]) == 2
    contents = {p: Path(p).read_bytes() for p in first["written"]}
    assert len(set(contents.values())) == 1  # §22：每棵树逐位相同
    digests = {p: hashlib.md5(c).hexdigest() for p, c in contents.items()}
    second = alert_meter.trend_recount([a, b], "2026-11-17")
    assert hashlib.md5(Path(second["written"][0]).read_bytes()).hexdigest() == digests[first["written"][0]]
    assert second["trend"] == first["trend"]


def test_two_trees_aggregate(tmp_path):
    a = _tree(tmp_path, "tree-a", [_row("2026-11-17", "notice", "故障 a")])
    b = _tree(tmp_path, "tree-b", [_row("2026-11-17", "notice", "故障 b"),
                                   _row("2026-11-17", "digest", "摘要 c")])
    trend = alert_meter.build_trend([a, b], "2026-11-17", days=7)
    today = trend["days"][-1]
    assert (today["total"], today["real"], today["noise"]) == (3, 2, 1)


def test_frozen_run_day_does_not_read_today(tmp_path, monkeypatch):
    tree = _tree(tmp_path, "t1", _sample_records("2026-11-17"))

    class _NoToday:
        @staticmethod
        def today():
            raise AssertionError("显式 end_day 时不得读取真实 today()（L51 冻结运行日）")

    monkeypatch.setattr(alert_meter, "date", _NoToday)
    trend = alert_meter.build_trend([tree], "2026-11-17", days=7)
    assert trend["window"][-1] == "2026-11-17"
    recounted = alert_meter.trend_recount([tree], "2026-11-17")
    assert recounted["end_day"] == "2026-11-17"


def test_payload_projects_wire_contract(tmp_path):
    """上报体（发送端唯一契约）：只 6 键、不带 no_data、只发有数据的天。

    2026-11-18 审查 P0-1：此前 schedule_monitor 直接把本地 7 键行（含 no_data）发出去，
    worker 固定键白名单整批 400 ⇒ 生产静默空转。这里锁死投影规则。
    """
    tree = _tree(tmp_path, "t1", _sample_records("2026-11-17"))
    trend = alert_meter.build_trend([tree], "2026-11-17", days=7)
    # 本地产物仍是 7 键（含 no_data），供前端/本地排查。
    assert "no_data" in trend["days"][-1]
    payload = alert_meter.build_trend_payload(trend, computed_ms=1234)
    assert payload["computed_ms"] == 1234
    assert len(payload["days"]) == 1  # 7 天里只有 11-17 有数据，缺日不外发
    assert set(payload["days"][0]) == {"date", "total", "real", "noise",
                                       "escalation", "by_tier"}
    assert payload["days"][0]["date"] == "2026-11-17"
    assert payload["days"][0]["total"] == (payload["days"][0]["real"]
                                           + payload["days"][0]["noise"])
    assert alert_meter.build_trend_payload({"days": []}, computed_ms=1)["days"] == []
