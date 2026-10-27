# -*- coding: utf-8 -*-
"""噪音计数尺子（scripts/alert_noise_count.py）自验，2026-10-28。

真实样本核实（L49 防假样本养绿）：fixture 的字段形状**逐字段照抄云上真实台账**
（2026-10-28 只读拉取 `~/code/trade-data/data/alerts/alert_ledger.jsonl` 815 行核实）：
    ts / tree / tier / key / subject / channels{email,feishu} / source / group
    （ts 真实格式 "YYYY-MM-DD HH:MM:SS"，无时区后缀；group 取值 alert/report/agent_done/follow）
当前台账**没有任何行**带 noise_class（实测 noise_class 出现 0 次）⇒ 本轮打标未上线，
故 fixture 里没标签属常态，带标签场景是「将来打标」的预留测试。

时间敏感性（L51）：被测的计数函数**不取墙钟**（日期由 --date 显式给），
本文件用「整个 fixture 平移一天，结果逐位相同」+「把 date.today() 打成抛异常仍能跑」
两条来钉死，不依赖跑测试的真实日期。

跑法：python3 -m pytest -q scripts/tests/test_alert_noise_count_20261028.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import alert_noise_count as anc  # noqa: E402


def rec(ts: str, subject: str, tier: str = "notice", group: str = "alert", **kw) -> dict:
    """构造一条与云上真实台账同形状的记录。"""
    r = {
        "ts": ts,
        "tree": "/home/ubuntu/code/trade-data",
        "tier": tier,
        "key": "0123456789ab",
        "subject": subject,
        "channels": {"email": True, "feishu": True},
        "source": "notify.py",
        "group": group,
    }
    r.update(kw)
    return r


def _write_ledger(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 1. 六类各一条 + 计数/构成正确（repeat 需要两条同签名：首报真故障 + 第 2 条 repeat）
# ---------------------------------------------------------------------------
def test_six_classes_counts_and_render():
    rows = [
        rec("2026-10-27 00:00:34", "[告警·摘要] 当日合并 2 条 (含前日遗留 2 条)(r2 2)", tier="digest"),
        rec("2026-10-27 01:00:00", "[告警·聚合] 3 条 warning 汇总"),
        rec("2026-10-27 02:00:00", "[告警] 【持续故障升级】foo 异常", tier="critical"),
        rec("2026-10-27 03:00:00", "[恢复] foo 异常 10-27 03:00"),
        rec("2026-10-27 04:00:00", "[kelly] 冻结表新增孤儿买事件 3 条"),
        rec("2026-10-27 05:00:00", "[告警] 信号凯利回测停滞 10-27 05:00", tier="critical"),
        rec("2026-10-27 06:00:00", "[告警] 信号凯利回测停滞 10-27 06:00", tier="critical"),
    ]
    res = anc.classify_rows(rows, ["2026-10-27"])
    d = res["days"][0]
    assert (d["alert"], d["noise"], d["real"]) == (7, 6, 1)
    assert d["breakdown"] == {
        "digest": 1, "warning_batch": 1, "escalation": 1,
        "recovery": 1, "routine": 1, "repeat": 1,
    }
    assert d["pass"] is False
    assert res["totals"]["noise"] == 6 and res["totals"]["real"] == 1
    assert res["warn_untagged"] == []  # 全未标注 ⇒ 不报漏标

    text = anc.render({
        "date": "2026-10-27", "date_range": ["2026-10-27", "2026-10-27"],
        "days": res["days"], "totals": res["totals"],
        "warn_untagged": res["warn_untagged"],
    })
    assert "日期 2026-10-27  告警群 7 条 = 噪音 6 条 + 真故障 1 条" in text
    assert "构成：digest 1 / warning_batch 1 / escalation 1 / recovery 1 / routine 1 / repeat 1" in text
    assert "验收：噪音 6 <= 3 ? FAIL（真故障不设上限）" in text
    # repeat 诚实提示必须每次出现（A3 未修，不许静默）
    assert anc.REPEAT_CAVEAT in text


def test_pass_when_noise_within_budget():
    rows = [rec("2026-10-27 00:00:34", "[告警·摘要] 当日合并 1 条", tier="digest")]
    d = anc.classify_rows(rows, ["2026-10-27"])["days"][0]
    assert d["noise"] == 1 and d["pass"] is True


# ---------------------------------------------------------------------------
# 2. group != alert 的行不计（report 群的 [状态说明] 不进噪音）
# ---------------------------------------------------------------------------
def test_non_alert_group_excluded():
    rows = [
        rec("2026-10-27 10:00:00", "[状态说明] 监控自检正常", group="report"),
        rec("2026-10-27 10:05:00", "[kelly] 冻结表新增孤儿买事件 3 条", group="report"),
        rec("2026-10-27 10:10:00", "买卖点提醒", group="follow"),
        rec("2026-10-27 10:15:00", "任务完成", group="agent_done"),
        rec("2026-10-27 11:00:00", "[kelly] 冻结表新增孤儿买事件 3 条", group="alert"),
    ]
    d = anc.classify_rows(rows, ["2026-10-27"])["days"][0]
    assert (d["alert"], d["noise"], d["real"]) == (1, 1, 0)
    assert d["breakdown"]["routine"] == 1

    # 无 group 的行（真实台账里 5 行 group=null）同样不算 alert
    rows_null = [rec("2026-10-27 12:00:00", "[告警] 某消息", group=None)]
    d2 = anc.classify_rows(rows_null, ["2026-10-27"])["days"][0]
    assert d2["alert"] == 0


# ---------------------------------------------------------------------------
# 3. 24h 边界：23:59 ⇒ repeat；24:01 ⇒ 不算；恰好 24:00 ⇒ 算（窗口含边界，docstring 已写明）
# ---------------------------------------------------------------------------
def test_repeat_24h_boundary():
    rows = [
        # A：间隔 23h59m ⇒ 第二天那条算 repeat
        rec("2026-10-26 10:00:00", "[告警] A 任务异常 2026-10-26 10:00"),
        rec("2026-10-27 09:59:00", "[告警] A 任务异常 2026-10-27 09:59"),
        # B：间隔 24h01m ⇒ 第二天那条不算 repeat（真故障）
        rec("2026-10-26 10:00:00", "[告警] B 任务异常 2026-10-26 10:00"),
        rec("2026-10-27 10:01:00", "[告警] B 任务异常 2026-10-27 10:01"),
        # C：恰好 24h00m ⇒ 算 repeat（边界的明确口径）
        rec("2026-10-26 10:00:00", "[告警] C 任务异常 2026-10-26 10:00"),
        rec("2026-10-27 10:00:00", "[告警] C 任务异常 2026-10-27 10:00"),
    ]
    d = anc.classify_rows(rows, ["2026-10-27"])["days"][0]
    assert (d["alert"], d["noise"], d["real"]) == (3, 2, 1)
    assert d["breakdown"]["repeat"] == 2


def test_repeat_cross_day_history_outside_window():
    # 窗口前一天的行虽不计入当天，但可作为 repeat 的历史参照
    rows = [
        rec("2026-10-26 23:30:00", "[告警] D 任务异常 2026-10-26 23:30"),
        rec("2026-10-27 00:00:10", "[告警] D 任务异常 2026-10-27 00:00"),
    ]
    d = anc.classify_rows(rows, ["2026-10-27"])["days"][0]
    assert (d["alert"], d["noise"], d["real"]) == (1, 1, 0)
    assert d["breakdown"]["repeat"] == 1


# ---------------------------------------------------------------------------
# 4. 归一化：同任务不同时间 ⇒ 同签名；不同任务名 ⇒ 不同签名；数字归一但单位保留
# ---------------------------------------------------------------------------
def test_normalization_same_task_same_signature():
    a = anc.normalize_subject("[告警] 信号凯利回测停滞 2026-10-26 02:18")
    b = anc.normalize_subject("[告警] 信号凯利回测停滞 10-27 05:00")
    c = anc.normalize_subject("[告警] 信号凯利回测停滞 20261027")
    assert a == b == c


def test_normalization_different_task_different_signature():
    a = anc.normalize_subject("[告警] A 任务异常 10-27 05:00")
    b = anc.normalize_subject("[告警] B 任务异常 10-27 05:00")
    assert a != b


def test_normalization_keeps_units():
    a = anc.normalize_subject("[kelly] 冻结表新增孤儿买事件 21 条")
    b = anc.normalize_subject("[kelly] 冻结表新增孤儿买事件 24 条")
    assert a == b
    assert a.endswith("条") and "#" in a


# ---------------------------------------------------------------------------
# 5. noise_class 优先 + 混合场景 WARN（命中谓词却没标 ⇒ WARN，但不判 FAIL）
# ---------------------------------------------------------------------------
def test_noise_class_wins_over_predicate():
    rows = [
        # tier=digest 会被谓词算 digest，但标签优先 ⇒ warning_batch
        rec("2026-10-27 01:00:00", "[告警·摘要] 当日合并 2 条", tier="digest",
            noise_class="warning_batch"),
    ]
    res = anc.classify_rows(rows, ["2026-10-27"])
    d = res["days"][0]
    assert (d["noise"], d["real"]) == (1, 0)
    assert d["breakdown"]["warning_batch"] == 1 and d["breakdown"]["digest"] == 0
    assert res["warn_untagged"] == []  # 该行已标, 不产生 WARN


def test_partial_tagging_produces_warn_not_fail():
    rows = [
        rec("2026-10-27 01:00:00", "[告警·摘要] 当日合并 2 条", tier="digest",
            noise_class="digest"),
        # 未标注但命中 routine 谓词 ⇒ WARN
        rec("2026-10-27 02:00:00", "[kelly] 冻结表新增孤儿买事件 3 条"),
        # 未标注且不命中 ⇒ 真故障, 不 WARN
        rec("2026-10-27 03:00:00", "[告警] 某真故障 10-27", tier="critical"),
    ]
    res = anc.classify_rows(rows, ["2026-10-27"])
    d = res["days"][0]
    assert (d["alert"], d["noise"], d["real"]) == (3, 2, 1)
    assert len(res["warn_untagged"]) == 1
    w = res["warn_untagged"][0]
    assert w["date"] == "2026-10-27"
    assert "孤儿买" in w["subject"]
    assert w["suggested_class"] == "routine"

    text = anc.render({
        "date": "2026-10-27", "date_range": ["2026-10-27", "2026-10-27"],
        "days": res["days"], "totals": res["totals"],
        "warn_untagged": res["warn_untagged"],
    })
    assert "WARN 漏标 1 条" in text and "建议 routine" in text
    # WARN 只提示、不把验收判成 FAIL：噪音 2 <= 3 ⇒ PASS
    assert "验收：噪音 2 <= 3 ? PASS（真故障不设上限）" in text


# ---------------------------------------------------------------------------
# 6. 空台账 / 该 date 无行 ⇒ 0/0 不崩（不除零）
# ---------------------------------------------------------------------------
def test_empty_ledger_and_day_without_rows():
    res = anc.classify_rows([], ["2026-10-27"])
    d = res["days"][0]
    assert (d["alert"], d["noise"], d["real"]) == (0, 0, 0)
    assert res["totals"]["pass"] is True

    rows = [rec("2026-10-26 10:00:00", "[告警] 别的日期", tier="critical")]
    res2 = anc.classify_rows(rows, ["2026-10-27"])
    assert res2["days"][0]["alert"] == 0

    # --days 多天窗口也允许 0（不除零）
    res3 = anc.classify_rows([], ["2026-10-25", "2026-10-26", "2026-10-27"])
    assert res3["totals"]["noise"] == 0
    text = anc.render({"date": "2026-10-27",
                       "date_range": ["2026-10-25", "2026-10-27"],
                       "days": res3["days"], "totals": res3["totals"],
                       "warn_untagged": []})
    assert "日均噪音 0.00 条/天" in text


def test_missing_ledger_file_is_zero_and_warns(tmp_path, capsys):
    missing = tmp_path / "nope.jsonl"
    rc = anc.main(["--date", "2026-10-27", "--ledger", str(missing), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ledger_exists"] is False
    assert payload["totals"]["alert"] == 0


# ---------------------------------------------------------------------------
# 7. --json 结构稳定、可 json.loads、字段齐全
# ---------------------------------------------------------------------------
def test_json_output_schema(tmp_path, capsys):
    rows = [
        rec("2026-10-27 00:00:34", "[告警·摘要] 当日合并 2 条", tier="digest"),
        rec("2026-10-27 01:00:00", "[告警] 某真故障 10-27", tier="critical"),
    ]
    p = _write_ledger(tmp_path / "alert_ledger.jsonl", rows)
    rc = anc.main(["--date", "2026-10-27", "--ledger", str(p), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    for key in ("date", "date_range", "ledger", "ledger_exists", "noise_max",
                "days", "totals", "repeat_caveat", "warn_untagged",
                "skipped_bad_lines", "skipped_undated_alert_rows", "records_scanned"):
        assert key in payload, key
    assert payload["noise_max"] == 3
    assert payload["date"] == "2026-10-27"
    assert payload["date_range"] == ["2026-10-27", "2026-10-27"]
    assert payload["records_scanned"] == 2
    d = payload["days"][0]
    for key in ("date", "alert", "noise", "real", "breakdown", "pass"):
        assert key in d, key
    assert set(d["breakdown"]) >= set(anc.CANONICAL_CLASSES)
    assert payload["totals"]["alert"] == 2
    assert payload["totals"]["noise"] == 1 and payload["totals"]["real"] == 1


def test_json_days_window(tmp_path, capsys):
    rows = [
        rec("2026-10-26 10:00:00", "[告警·摘要] 当日合并 1 条", tier="digest"),
        rec("2026-10-27 10:00:00", "[告警·摘要] 当日合并 1 条", tier="digest"),
    ]
    p = _write_ledger(tmp_path / "alert_ledger.jsonl", rows)
    rc = anc.main(["--date", "2026-10-27", "--days", "2", "--ledger", str(p), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["date_range"] == ["2026-10-26", "2026-10-27"]
    assert [d["noise"] for d in payload["days"]] == [1, 1]
    assert payload["totals"]["noise"] == 2


# ---------------------------------------------------------------------------
# 8. 时间敏感（L51）：计数不取墙钟；整个 fixture 平移一天结果逐位相同
# ---------------------------------------------------------------------------
def _fixture_all_classes(day: str) -> list[dict]:
    return [
        rec(f"{day} 00:00:34", "[告警·摘要] 当日合并 2 条", tier="digest"),
        rec(f"{day} 01:00:00", "[告警·聚合] 3 条 warning 汇总"),
        rec(f"{day} 02:00:00", "[告警] 【持续故障升级】foo 异常", tier="critical"),
        rec(f"{day} 03:00:00", "[恢复] foo 异常"),
        rec(f"{day} 04:00:00", "[kelly] 冻结表新增孤儿买事件 3 条"),
        rec(f"{day} 05:00:00", "[告警] 信号凯利回测停滞", tier="critical"),
        rec(f"{day} 06:00:00", "[告警] 信号凯利回测停滞", tier="critical"),
    ]


def test_counts_stable_across_days_shift():
    """把整个 fixture 平移一天（含 --date），结果必须逐位相同 ⇒ 证明不依赖真实今天。"""
    a = anc.classify_rows(_fixture_all_classes("2026-10-27"), ["2026-10-27"])["days"][0]
    b = anc.classify_rows(_fixture_all_classes("2026-10-28"), ["2026-10-28"])["days"][0]
    for key in ("alert", "noise", "real", "breakdown", "pass"):
        assert a[key] == b[key], key


def test_no_wall_clock_dependency(tmp_path, capsys, monkeypatch):
    """把 date.today() 打成抛异常，显式 --date 仍必须正常跑（L51 防跨天红）。"""
    class _NoToday:
        @staticmethod
        def today():
            raise AssertionError("计数不应读取真实今天（请用 --date）")

    monkeypatch.setattr(anc, "date", _NoToday)
    p = _write_ledger(tmp_path / "alert_ledger.jsonl", _fixture_all_classes("2026-10-27"))
    rc = anc.main(["--date", "2026-10-27", "--ledger", str(p), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["totals"]["noise"] == 6


def test_bad_lines_skipped(tmp_path, capsys):
    p = tmp_path / "alert_ledger.jsonl"
    p.write_text('{"ts": "2026-10-27 00:00:00", "group": "alert", "subject": "[告警] x", '
                 '"tier": "critical"}\n{broken json\n', encoding="utf-8")
    rc = anc.main(["--date", "2026-10-27", "--ledger", str(p), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["skipped_bad_lines"] == 1
    assert payload["totals"]["alert"] == 1


def test_invalid_date_returns_2(capsys):
    assert anc.main(["--date", "2026/10/27", "--ledger", "/tmp/whatever.jsonl"]) == 2
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_invalid_days_returns_2(capsys):
    assert anc.main(["--date", "2026-10-27", "--days", "0",
                     "--ledger", "/tmp/whatever.jsonl"]) == 2
    assert "--days" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 9. 无法归日的 alert 行：显式计数（不静默丢），且 date-only ts 仍可归日
# ---------------------------------------------------------------------------
def test_undated_alert_rows_counted_not_silently_dropped(tmp_path, capsys):
    p = _write_ledger(tmp_path / "alert_ledger.jsonl", [
        rec("不是时间", "[告警] 没有 ts 的坏行", tier="critical"),
        rec("2026-10-27 01:00:00", "[告警] 正常行", tier="critical"),
    ])
    rc = anc.main(["--date", "2026-10-27", "--ledger", str(p), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["totals"]["alert"] == 1
    assert payload["skipped_undated_alert_rows"] == 1


def test_date_only_ts_accepted():
    d = anc.classify_rows([rec("2026-10-27", "[告警] 只有日期")], ["2026-10-27"])["days"][0]
    assert (d["alert"], d["real"]) == (1, 1)