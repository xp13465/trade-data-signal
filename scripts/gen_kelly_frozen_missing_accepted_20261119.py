#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成/核对 config/signal_kelly_frozen_missing_accepted.json(方案 B1, 2026-11-19)。

用途: 把 2026-11-19 归档 run 里「有双源证据」的冻结表缺失事件登记进 accepted 白名单。
核心铁律: **无证据不得登记**——只登记 11-09 复审四分类里可复核的两类,
其余键(含证据文件已丢失的 13 键)一律留报, 未登记的新事件照常告警。

依据(全部可复核):
- 基线归档: 云上 data/audit/frozen_missing/5bc33ec582cc4c6cbbdd3e0aa7f84d51.json
  (--archive 传本地只读副本; run_id=5bc33ec582cc4c6cbbdd3e0aa7f84d51,
  recorded_at=2026-11-19T07:10:18, filtered_missing_sha256=1a66c6b6...b88396e,
  filtered_missing 121 条, latest_signal_date=20261118)
- 11-09 四分类: docs/codex-reviews/alert-rootfix-20261109/freeze.md
  §4 = 96 早年 csi_000813 + 1 待定(20261019) + 17 THS + 18 appeared 链 + 4 余键 = 136
- 映射 ETF 首现(本地 etf_daily 权威表, 上市日不会变; 数据源 data/etf_national_team.db
  表 etf_daily): csi_000813 当前映射 13 只, 最早 159870=20210303, 最晚 158032=20260914;
  etf_daily(2005-02-23 起)无任何化工 ETF 早于 20210303
- 9/18 产品文档: docs/kelly/analysis/kelly-freeze-timespot-rootfix-20260918.md:50
  「csi_000813 等 track_score=None 被 best_etf 过滤的新指数, 其历史信号在云上本来就未冻结
  (云上冻结表 0 条)」

用法(仓库根目录):
  # 核对:用同一归档重算, 必须与已提交 config 逐字节一致(复现性检查)
  .venv/bin/python scripts/gen_kelly_frozen_missing_accepted_20261119.py \
      --archive /tmp/frozen_missing_latest_20261119.json \
      --check config/signal_kelly_frozen_missing_accepted.json
  # 生成到新文件(人工 diff 后再替换 config)
  .venv/bin/python scripts/gen_kelly_frozen_missing_accepted_20261119.py \
      --archive /tmp/frozen_missing_latest_20261119.json --out /tmp/accepted_new.json
"""
import argparse
import json
import sys

RUN_ID = "5bc33ec582cc4c6cbbdd3e0aa7f84d51"
RECORDED_AT = "2026-11-19T07:10:18"
ARCHIVE_SHA = "1a66c6b6c6724ff6a87c0889333be1438c25319ebc0253cbe47c16749b88396e"

# 2026-10-11 降噪拍板已登记的 8 条(legacy), 迁移为对象格式 entries
LEGACY = [
    "20260922|sz_div|buy", "20260929|gz_399395|buy_aux", "20261002|cac40|buy",
    "20261002|dax|buy_aux", "20261005|hscei|buy_aux", "20261005|hstech|buy",
    "20261006|cac40|buy", "20261006|hsi|buy_aux",
]

# csi_000813 当前映射化工 ETF 全 13 只(board_etf_map.json)及 etf_daily 首现
ETF_13 = ("561620/158006/159870/159087/158017/159093/159082/158032/159129/"
          "516020/516120/159133/516220")

# 11-09 freeze.md §2 DataGap 5 时序表(行号 46-50): index_daily 改写 → signal 事后 appeared
DATAGAP = {
    "20261028|csi_000102|buy": "freeze.md:46 10/29 17:59:32 index_daily close 3276.07→3335.87 后 10/29 18:01:01 signal appeared",
    "20261028|sw_801770|buy": "freeze.md:47 10/29 17:57:06 close 5379.48→5493.52 后 10/29 18:01:01 signal appeared",
    "20261102|csi_000102|buy": "freeze.md:48 11/3 17:57:41 close 3105.86→3155.19 后 11/3 17:59:09 signal appeared",
    "20261102|gz_399365|buy": "freeze.md:49 11/3 17:56:34 close 10215.3→10380 后 11/3 17:59:09 signal appeared",
    "20261104|csi_000102|buy": "freeze.md:50 11/5 17:55:14 close 3081.81→3240.09 后 11/5 17:56:48 signal appeared",
}


def build(archive_path):
    d = json.load(open(archive_path, encoding="utf-8"))
    miss = d["filtered_missing"]
    early = [k for k in miss if "|csi_000813|" in k and k[:4] <= "2016"]
    x2026_c813 = [k for k in miss if "|csi_000813|" in k and k[:4] >= "2026"]
    others = [k for k in miss if "|csi_000813|" not in k]
    assert len(early) == 96, f"早年 csi_000813 应为 96, 实 {len(early)}"
    assert len(x2026_c813) == 1, f"2026 csi_000813 应恰 1 条(待定), 实 {x2026_c813}"
    assert len(others) == 24, f"非 csi_000813 应 24 条, 实 {len(others)}"

    accepted = []
    for k in LEGACY:
        accepted.append({
            "key": k,
            "category": "legacy_accepted_20260921_20261011",
            "evidence": "2026-10-11 降噪拍板登记(approval_log 2026-09-21/2026-10-11); 事件为信号事后回填致 (date,index) 从未冻结, 用户拍板接受跳过。",
        })
    for k in early:
        date = k.split("|")[0]
        accepted.append({
            "key": k,
            "category": "A_new_listing_etf_no_tradable_historically",
            "evidence": (
                f"归档 {RUN_ID}@{RECORDED_AT}(filtered_missing_sha256={ARCHIVE_SHA}) 列入本键; "
                f"信号日 {date} 早于全部 13 只当前映射化工ETF({ETF_13})最早首现 20210303"
                f"(159870, 见本地 etf_daily min(date)); etf_daily(2005-02-23 起)无任何"
                f"化工ETF早于 20210303; 9/18 文档(kelly-freeze-timespot-rootfix-20260918.md:50)载该指数当时 "
                f"track_score=None 不进 best_etf 且云上冻结表 0 键 → 该信号日当时无任何可交易映射 ETF, 历史 buy 从未有可交易 ETF。"
            ),
        })
    for k in sorted(DATAGAP):
        assert k in miss, f"DataGap 键缺失: {k}"
        accepted.append({
            "key": k,
            "category": "B_changed_appeared_chain",
            "evidence": (
                f"归档 {RUN_ID}@{RECORDED_AT}(filtered_missing_sha256={ARCHIVE_SHA}) 列入本键; "
                f"11-09 复审 {DATAGAP[k]}; 冻结表无此键 → 历史行情改写后信号事后 appeared, 非信号日当时产生。"
            ),
        })

    return {
        "_meta": {
            "purpose": "凯利回测「冻结表缺失历史信号事件」已确认接受(跳过)登记表",
            "single_source_of_truth": "本文件是「哪些冻结缺失事件已被人工确认接受(跳过处理)」的单一事实源; signal_kelly_backtest._alert_frozen_missing 只对不在 accepted 表内的事件告警",
            "why": "部分历史信号事件(date < latest_signal_date)在冻结表里完全无键——信号是事后回填进 signal_daily 的(冻结分时点防御闸 2026-09-18 拒绝补冻历史信号), 读侧 _freeze_fallback(2026-09-22) 也接不住((date,index) 从没冻结过)。这些事件在回测中被跳过, 不影响基线口径。",
            "format": "accepted[] 每条必须是对象且带非空 key/category/evidence 三字段; 缺任一字段的条目被 loader 拒绝(该事件继续告警)——「无证据不得 accepted」(11-09 复审铁律)。",
            "discriminator_preserved": "出现「不在本表内」的新缺键事件(新出现的/异常的/规模超常的)照常告警: n<10 → WARN(24h dedup/摘要), n>=10 → SEVERE(1h dedup 直发)",
            "how_to_extend": "新增已确认接受的事件 → accepted 追加 {\"key\":\"date|index_id|signal\",\"category\":\"分类\",\"evidence\":\"可复核证据锚点(归档run_id+sha/文档行号/数据出处)\"} + approval_log 追加一行(日期/依据/审批人)。无证据条目会被 loader 拒绝。",
            "fail_safe": "文件缺失/损坏 ⇒ 视为空表(全量告警, 绝不静默吞真告警); 单条目缺 key/category/evidence ⇒ 只拒绝该条(继续告警)",
            "decision": "2026-09-21 用户拍板「接受跳过」; 2026-10-11 用户拍板「直接干」告警降噪三项; 2026-11-19 方案 B1 按 11-09 四分类登记有双源证据的存量事件(96 早年 csi_000813 + 5 个 changed→appeared 键), 无证据项一律留报",
            "baseline_archive": {
                "run_id": RUN_ID,
                "recorded_at": RECORDED_AT,
                "source": "云上 data/audit/frozen_missing/5bc33ec582cc4c6cbbdd3e0aa7f84d51.json(主控只读拉取本地副本 /tmp/frozen_missing_latest_20261119.json)",
                "filtered_missing_count": 121,
                "filtered_missing_sha256": ARCHIVE_SHA,
                "latest_signal_date": "20261118",
            },
            "generated_at": "2026-11-19",
        },
        "accepted": accepted,
        "approval_log": [
            {"date": "2026-09-21", "event": "20260918|sz_div|buy_aux", "decision": "接受跳过(用户拍板)", "note": "该 (date,index) 冻结表无键, 事后延迟回填所致"},
            {"date": "2026-10-11", "event": "8 个事件(legacy_accepted_20260921_20261011)", "decision": "接受跳过→登记入本表", "note": "2026-10-11 告警降噪三项拍板; 均为信号事后回填致 (date,index) 从未冻结"},
            {"date": "2026-11-19", "event": "96 个 2012-2016 csi_000813 键", "decision": "登记 accepted(方案 B1, A 类)", "note": "全部 13 只当前映射化工ETF最早首现 20210303(159870), 最晚 20260914, 全部晚于 2016; etf_daily(2005-02-23 起)无任何化工ETF早于 20210303; 9/18 文档载当时 track_score=None 不进 best_etf 且冻结表 0 键 → 信号日当时无可交易 ETF"},
            {"date": "2026-11-19", "event": "5 个 changed→appeared 链键(20261028/20261102/20261104)", "decision": "登记 accepted(方案 B1, B 类)", "note": "11-09 freeze.md §2 逐键时序表:index_daily changed → signal appeared, 冻结表无键; 归档 run 5bc33ec5…"},
            {"date": "2026-11-19", "event": "20261019|csi_000813|buy_aux", "decision": "留报不登记", "note": "信号日晚于映射 ETF 上市, 不适用 A 类; 11-09 复审列为待定(无 appeared 记录)"},
            {
                "date": "2026-11-19",
                "event": "其余 19 条(20261009~20261113 非 DataGap 键)",
                "decision": "留报不登记",
                "note": "与 dry 留报清单逐条对账(共 20 条留报 = 1 待定 + 19 条本行): "
                        "4 余键(20261009|csi_000330|csi_970070|sz_div 三键 + 20261105|dax|buy_special, "
                        "11-09 复审证据不足, 13 键证据文件已丢失按无证据) + "
                        "1 THS(20261016|thsc_300008|buy_aux) + "
                        "2 真故障嫌疑(20261023|sw_801050|buy、20261026|sw_801160|buy_aux, SW 映射链疑真故障) + "
                        "12 无逐键 appeared 证据键(20261013 csi_000330/csi_000673/csi_970070、"
                        "20261019|sz_div、20261023 csi_970070/gz_399395/sz_div、"
                        "20261104 csi_000330/csi_000673/gz_399395、20261111|cac40|buy_special、"
                        "20261113|csi_931946|buy_special); 均证据不全 → 留报, 补新证据后再登记",
            },
        ],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive", required=True,
                    help="冻结缺失诊断归档 JSON(本地只读副本)")
    ap.add_argument("--out", help="输出路径; 与 --check 二选一")
    ap.add_argument("--check", help="与给定 config 逐字节比对(复现性检查)")
    args = ap.parse_args()
    config = build(args.archive)
    text = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        cur = open(args.check, encoding="utf-8").read()
        if cur != text:
            print("FAIL: 重算结果与 %s 不一致" % args.check)
            sys.exit(1)
        n = len(config["accepted"])
        print("PASS: 重算结果与 %s 逐字节一致(accepted=%d)" % (args.check, n))
    elif args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        a = sum(1 for x in config["accepted"] if x["category"].startswith("A_"))
        b = sum(1 for x in config["accepted"] if x["category"].startswith("B_"))
        legacy = sum(1 for x in config["accepted"] if x["category"].startswith("legacy_"))
        print("registered:", len(config["accepted"]), "| A=", a, "| B=", b, "| legacy=", legacy)
    else:
        ap.error("--out 或 --check 必选其一")


if __name__ == "__main__":
    main()
