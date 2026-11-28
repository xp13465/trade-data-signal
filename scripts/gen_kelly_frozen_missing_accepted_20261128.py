#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成/核对 config/signal_kelly_frozen_missing_accepted.json 的 2026-11-28 批(34 键)。

背景(告警风暴 RCA P2, /tmp/alert-storm-rca-report-20261128.md §1.1/§2.1):
  2026-11-28 00:15 「冻结表缺失历史信号事件 34 个」重复告警; 34 键全部在 signal_daily
  真实存在, 但冻结表 signal_kelly_etf_freeze.json(28821 键)里同 index 只有更早日期键。
  既有 accepted 表只登记旧 122 键, 这 34 键未登记 → 每次回测重新告警。

证据(逐键可复核, 不伪造 appeared 链):
  - 归档 2d1b21f1a8b6493dbbea8d0427ca515b@2026-11-28T05:08:35, filtered_missing 34 条,
    filtered_missing_sha256=e573f3a43f04658228f0022385475668e42406555ccccfcdaf19265be7b1aee2,
    latest_signal_date=20261127(云上 data/audit/frozen_missing/, 只读拉取本地副本)。
  - 本批 34 键在 history_overwrite_audit **没有** signal_daily appeared 记录(只有 6 键有
    index_daily changed 记录), 因此不能套既有 B_changed_appeared_chain(那类要求逐键
    changed→appeared 时序)。改用的证据是 signal_daily 的 SQLite rowid:
    每个键的 rowid 都落在一段**同一 index、跨多个年份/日期的连续 rowid 块**里
    (如 thsc_300830 的 2026-07-21→2026-11-27 六个不同日期占 104442..104451 连续 rowid),
    说明整块是一次批量回补写入, 该行不是信号日当天入库的; 首次入库必然晚于冻结时点,
    冻结分时点防御闸(signal_kelly_backtest.py:591-647)拒绝补冻 date<latest 的历史键,
    读侧 fallback 也接不住 → 只能跳过。冻结表 28821 键无该 (date,index) 任何变体,
    云上 signal_daily 现有该行, 三源互证为「晚到回填」。
  - 逐键 rowid/邻块明细来源: 云上 sentiment.db `select rowid,date,index_id,signal from
    signal_daily` 只读查询(2026-11-28)。

用法(仓库根目录):
  # 生成:旧 122 基线 + 本批 34 → 156
  .venv/bin/python scripts/gen_kelly_frozen_missing_accepted_20261128.py \
      --base config/signal_kelly_frozen_missing_accepted.json \
      --archive /tmp/frozen_missing_20261128.json --out /tmp/accepted_new.json
  # 核对:已提交 config 的本批 34 条逐字段可由本脚本重算复现(无需 --base)
  .venv/bin/python scripts/gen_kelly_frozen_missing_accepted_20261128.py \
      --archive /tmp/frozen_missing_20261128.json --check config/signal_kelly_frozen_missing_accepted.json
"""
import argparse
import json
import sys

RUN_ID = "2d1b21f1a8b6493dbbea8d0427ca515b"
RECORDED_AT = "2026-11-28T05:08:35"
ARCHIVE_SHA = "e573f3a43f04658228f0022385475668e42406555ccccfcdaf19265be7b1aee2"
EXPECTED_ARCHIVE_COUNT = 34
EXPECTED_BASE_COUNT = 122
EXPECTED_TOTAL = 156

# key -> (rowid, lo_rid, hi_rid, lo_date, hi_date); 云上 signal_daily 只读取证(2026-11-28)。
# rowid 前后邻块均为同一 index, 跨多年/多期连续 → 批量回补一次插入。
LATE34 = {
    "20261009|csi_000330|buy_aux": (118578, 118574, 118582, "20260714", "20261123"),
    "20261009|csi_970070|buy_aux": (108734, 108730, 108738, "20260702", "20261023"),
    "20261009|sz_div|buy": (78981, 78977, 78985, "20060403", "20261127"),
    "20261009|thsc_300830|buy_aux": (104446, 104442, 104450, "20260721", "20261126"),
    "20261009|thsc_308300|buy_aux": (104804, 104800, 104808, "20260529", "20261123"),
    "20261019|csi_000813|buy_aux": (117369, 117365, 117373, "20121221", "20261127"),
    "20261019|thsc_308491|buy_aux": (105055, 105051, 105059, "20260714", "20261123"),
    "20261020|thsc_307940|buy": (102162, 102158, 102166, "20260721", "20261104"),
    "20261020|thsc_308300|buy": (104807, 104803, 104811, "20211117", "20261126"),
    "20261020|thsc_308725|buy": (104659, 104655, 104663, "20230202", "20261126"),
    "20261023|thsc_307940|buy": (102163, 102159, 102167, "20260731", "20261123"),
    "20261023|thsc_308491|buy": (105056, 105052, 105060, "20260721", "20261126"),
    "20261028|thsc_307940|buy": (102164, 102160, 102168, "20261013", "20261126"),
    "20261028|thsc_308491|buy": (105057, 105053, 105061, "20260723", "20261127"),
    "20261028|thsc_309049|buy": (101856, 101852, 101860, "20231120", "20261123"),
    "20261102|thsc_300830|buy": (104448, 104444, 104452, "20200707", "20261127"),
    "20261102|thsc_307940|buy": (102165, 102161, 102169, "20231113", "20261126"),
    "20261102|thsc_308491|buy": (105058, 105054, 105062, "20200227", "20261127"),
    "20261102|thsc_309049|buy": (101857, 101853, 101861, "20231120", "20261123"),
    "20261104|thsc_307940|buy": (102166, 102162, 102170, "20231113", "20261126"),
    "20261104|thsc_309049|buy": (101858, 101854, 101862, "20231120", "20261123"),
    "20261105|dax|buy_special": (127079, 127075, 127083, "20221027", "20261105"),
    "20261111|cac40|buy_special": (127235, 127231, 127239, "20230414", "20261111"),
    "20261113|csi_931946|buy_special": (124473, 124469, 124477, "20260213", "20261113"),
    "20261123|thsc_300830|buy": (104449, 104445, 104453, "20200707", "20261127"),
    "20261123|thsc_308300|buy_aux": (104808, 104804, 104812, "20211117", "20261126"),
    "20261123|thsc_308491|buy": (105059, 105055, 105063, "20200227", "20261127"),
    "20261123|thsc_309049|buy_aux": (101859, 101855, 101863, "20231120", "20261123"),
    "20261126|dax|buy_aux": (126992, 126988, 126996, "20221101", "20261126"),
    "20261126|thsc_300830|buy_aux": (104450, 104446, 104454, "20200707", "20261127"),
    "20261126|thsc_307940|buy_aux": (102168, 102164, 102172, "20231113", "20261126"),
    "20261126|thsc_308300|buy_aux": (104809, 104805, 104813, "20211117", "20261126"),
    "20261126|thsc_308491|buy_aux": (105060, 105056, 105064, "20200227", "20261127"),
    "20261126|thsc_308725|buy_aux": (104661, 104657, 104665, "20230202", "20261126"),
}

# history_overwrite_audit 里本批仅 6 键有 index_daily changed 时序记录(无 signal appeared)。
INDEX_CHANGED = {
    "20261019|thsc_308491|buy_aux": "2026-10-20T17:57:05",
    "20261020|thsc_307940|buy": "2026-10-21T17:55:34",
    "20261020|thsc_308300|buy": "2026-10-21T17:55:44",
    "20261020|thsc_308725|buy": "2026-10-21T17:55:43",
    "20261023|thsc_307940|buy": "2026-10-26T17:56:17",
    "20261023|thsc_308491|buy": "2026-10-26T17:56:28",
}

CATEGORY = "C_late_rowid_bulk_backfill"

# signal_intraday_log 当日盘内扫描行数(云上只读取证 2026-11-28): >0 = 信号盘内真实出现过,
# 只是 EOD 的 signal_daily 行批量回补晚到; =0 = 无盘内正向佐证(仅 rowid 回补证据)。
INTRADAY_COUNT = {
    "20261009|csi_000330|buy_aux": 0,
    "20261009|csi_970070|buy_aux": 0,
    "20261009|sz_div|buy": 0,
    "20261009|thsc_300830|buy_aux": 10,
    "20261009|thsc_308300|buy_aux": 13,
    "20261019|csi_000813|buy_aux": 24,
    "20261019|thsc_308491|buy_aux": 21,
    "20261020|thsc_307940|buy": 16,
    "20261020|thsc_308300|buy": 29,
    "20261020|thsc_308725|buy": 26,
    "20261023|thsc_307940|buy": 9,
    "20261023|thsc_308491|buy": 9,
    "20261028|thsc_307940|buy": 24,
    "20261028|thsc_308491|buy": 29,
    "20261028|thsc_309049|buy": 30,
    "20261102|thsc_300830|buy": 20,
    "20261102|thsc_307940|buy": 15,
    "20261102|thsc_308491|buy": 24,
    "20261102|thsc_309049|buy": 15,
    "20261104|thsc_307940|buy": 16,
    "20261104|thsc_309049|buy": 11,
    "20261105|dax|buy_special": 0,
    "20261111|cac40|buy_special": 0,
    "20261113|csi_931946|buy_special": 0,
    "20261123|thsc_300830|buy": 11,
    "20261123|thsc_308300|buy_aux": 15,
    "20261123|thsc_308491|buy": 13,
    "20261123|thsc_309049|buy_aux": 28,
    "20261126|dax|buy_aux": 0,
    "20261126|thsc_300830|buy_aux": 29,
    "20261126|thsc_307940|buy_aux": 29,
    "20261126|thsc_308300|buy_aux": 27,
    "20261126|thsc_308491|buy_aux": 29,
    "20261126|thsc_308725|buy_aux": 29,
}

# 2026-11-20 拍板「先补证据再登记」时明确留报的 7 键(见 config 原 approval_log 末条):
# 其中 2 键当时标「真故障嫌疑」; 本次登记不得抹掉这条历史判断, 单列字段留痕。
PRIOR_LEFT = {
    "20261009|csi_000330|buy_aux", "20261009|csi_970070|buy_aux",
    "20261009|sz_div|buy", "20261019|csi_000813|buy_aux",
    "20261105|dax|buy_special", "20261111|cac40|buy_special",
    "20261113|csi_931946|buy_special",
}
SUSPECTED = {"20261111|cac40|buy_special", "20261113|csi_931946|buy_special"}


def evidence(key):
    date, idx, _ = key.split("|")
    rowid, lo_rid, hi_rid, lo_date, hi_date = LATE34[key]
    n_intraday = INTRADAY_COUNT[key]
    text = (
        f"归档 {RUN_ID}@{RECORDED_AT}(filtered_missing_sha256={ARCHIVE_SHA}) 列入本键; "
        f"云上 signal_daily rowid={rowid}, 紧邻 rowid {lo_rid}..{hi_rid} 为同一 index({idx})的连续块, "
        f"覆盖 {lo_date}..{hi_date} 多期键 → 该行随整块一次批量回补写入, 非信号日 {date} 当天入库"
        f"(首次入库晚于冻结时点; history_overwrite_audit 无该键 signal appeared 记录); "
        f"冻结表 28821 键无该 (date,index) 任何变体, 云上 signal_daily 现有该行 "
        f"→ 晚到回填, 信号日冻结时不可得。"
    )
    if n_intraday:
        text += f" signal_intraday_log 该日盘内 {n_intraday} 条同键扫描行 → 信号盘内真实出现过(正向佐证)。"
    else:
        text += " signal_intraday_log 无该键盘内记录(无盘内正向佐证, 仅 rowid 回补证据)。"
    if key in INDEX_CHANGED:
        text += f" 另 history_overwrite_audit {INDEX_CHANGED[key]} 有 index_daily changed 记录。"
    if key in PRIOR_LEFT:
        text += (" 该键 2026-11-20 拍板时属「留报」7 键之一; 本次按 rowid 批量回补证据登记, "
                 "历史留报判断保留可查。")
    if key in SUSPECTED:
        text += " 注: 2026-11-20 曾标「真故障嫌疑」, 本次未核销该嫌疑, 仅登记为晚到回填。"
    return text


def _entry(key):
    entry = {"key": key, "category": CATEGORY, "evidence": evidence(key)}
    if key in PRIOR_LEFT:
        entry["prior_left_reported"] = "2026-11-20"
    if key in SUSPECTED:
        entry["suspicion_unresolved"] = "真故障嫌疑(2026-11-20), 本次仅登记晚到回填, 未核销"
    return entry


def _validate_archive(archive):
    miss = archive["filtered_missing"]
    assert archive["run_id"] == RUN_ID, archive["run_id"]
    assert archive["metadata_count"] == len(miss) == EXPECTED_ARCHIVE_COUNT, len(miss)
    assert archive["hashes"]["filtered_missing_sha256"] == ARCHIVE_SHA
    assert set(miss) == set(LATE34), (set(miss) ^ set(LATE34))
    return miss


def build(base_path, archive_path):
    base = json.load(open(base_path, encoding="utf-8"))
    archive = json.load(open(archive_path, encoding="utf-8"))
    _validate_archive(archive)
    assert len(base["accepted"]) == EXPECTED_BASE_COUNT, len(base["accepted"])
    existing = {a["key"] for a in base["accepted"]}
    assert not (existing & set(LATE34)), "本批键与既有 accepted 重叠"

    accepted = list(base["accepted"])
    for key in sorted(LATE34):
        accepted.append(_entry(key))
    assert len(accepted) == EXPECTED_TOTAL, len(accepted)
    assert len({a["key"] for a in accepted}) == EXPECTED_TOTAL

    meta = dict(base["_meta"])
    meta["late_backfill_archive"] = {
        "run_id": RUN_ID,
        "recorded_at": RECORDED_AT,
        "source": "云上 data/audit/frozen_missing/2d1b21f1a8b6493dbbea8d0427ca515b.json"
                  "(只读拉取本地副本 /tmp/frozen_missing_20261128.json)",
        "filtered_missing_count": EXPECTED_ARCHIVE_COUNT,
        "filtered_missing_sha256": ARCHIVE_SHA,
        "latest_signal_date": archive["latest_signal_date"],
    }
    meta["decision"] = meta["decision"] + (
        "; 2026-11-28 告警风暴 P2: 34 个晚到键按新类别 "
        "C_late_rowid_bulk_backfill 登记(证据=signal_daily rowid 同 index 跨多年连续块=批量回补, "
        "非伪造 appeared 链; 旧 122 + 34 = 156)"
    )
    meta["discriminator_note"] = (
        "登记只精确屏蔽「冻结缺失(晚到回填)」告警本身, 不等于确认信号值正确: "
        "signal_daily 信号值改动仍由 history_overwrite_audit changed 链路独立检测(不被本表屏蔽); "
        "其中 20261111|cac40|buy_special / 20261113|csi_931946|buy_special 的 2026-11-20「真故障嫌疑」"
        "未核销, 以 suspicion_unresolved 字段与 evidence 原文保留; 7 个 2026-11-20 留报键以 "
        "prior_left_reported 字段留痕, 便于后续复核。"
    )
    meta["generated_at"] = "2026-11-28"

    approval = list(base["approval_log"])
    approval.append({
        "date": "2026-11-28",
        "event": "34 个晚到冻结缺失键(20261009~20261126, 以 THS 为主)",
        "decision": "登记 accepted(P2, C 类)",
        "note": "依据=告警风暴 RCA §1.1/§2.1 + 云上归档 2d1b21f1…(34 键, sha e573f3a4…) "
                "+ 云上 sentiment.db signal_daily rowid 逐键核验: 每键的 rowid 均落在同 index "
                "跨多年/多期的连续批量回补块内, 证明非信号日当天入库; 冻结表 28821 键无该 "
                "(date,index) 任何变体。history_overwrite_audit 仅 6 键有 index_daily changed, "
                "全批无 signal appeared, 故不用 B 类、不伪造 appeared 链, 单列 C 类。",
    })
    return {**base, "_meta": meta, "accepted": accepted, "approval_log": approval}


def check(config_path, archive_path):
    """核对已提交 config: 本批 34 条逐字段可由脚本重算复现(其余 122 条不动)。"""
    import hashlib
    cfg = json.load(open(config_path, encoding="utf-8"))
    archive = json.load(open(archive_path, encoding="utf-8"))
    _validate_archive(archive)
    entries = cfg["accepted"]
    assert len(entries) == EXPECTED_TOTAL, len(entries)
    assert len({e["key"] for e in entries}) == EXPECTED_TOTAL
    by_key = {e["key"]: e for e in entries}
    for key in LATE34:
        assert by_key.get(key) == _entry(key), "本批条目与重算不一致: " + key
    others = [e for e in entries if e["key"] not in LATE34]
    assert len(others) == EXPECTED_BASE_COUNT, len(others)
    assert not any(e["category"].startswith("C_") for e in others)
    expected_meta = {
        "run_id": RUN_ID,
        "recorded_at": RECORDED_AT,
        "filtered_missing_count": EXPECTED_ARCHIVE_COUNT,
        "filtered_missing_sha256": ARCHIVE_SHA,
        "latest_signal_date": archive["latest_signal_date"],
    }
    got_meta = cfg["_meta"]["late_backfill_archive"]
    for k, v in expected_meta.items():
        assert got_meta.get(k) == v, "late_backfill_archive.%s 不一致: %r != %r" % (k, got_meta.get(k), v)
    assert cfg["approval_log"][-1]["date"] == "2026-11-28", cfg["approval_log"][-1]
    raw = open(config_path, "rb").read()
    print("PASS: %s 可复现(accepted=%d, C=%d, sha256=%s)"
          % (config_path, len(entries), len(LATE34), hashlib.sha256(raw).hexdigest()[:16]))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive", required=True, help="34 键冻结缺失归档(本地只读副本)")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--out", help="输出路径(需配 --base 指向旧 122 键表)")
    group.add_argument("--check", help="核对已提交 config(无需 --base)")
    ap.add_argument("--base", help="既有 122 键 accepted 表(仅 --out 需要)")
    args = ap.parse_args()
    if args.check:
        check(args.check, args.archive)
        return
    assert args.base, "--out 必须配 --base(旧 122 键表)"
    config = build(args.base, args.archive)
    text = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    print("registered:", len(config["accepted"]), "| C=",
          sum(1 for x in config["accepted"] if x["category"].startswith("C_")))


if __name__ == "__main__":
    main()
