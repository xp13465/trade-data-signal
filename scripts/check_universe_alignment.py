#!/usr/bin/env python3
"""check_universe_alignment.py - 凯利回测/首页AI建议「入样宇宙规则」对称校验(§23.6)

规范: CLAUDE.md §23.6(2026-08-14 用户定)。入样宇宙规则(哪些信号进凯利回测/首页 AI 建议)必须
①显式声明(config/universe_rules.yaml 单一事实源) ②强制公示 ③1:1遵从 ④对称校验 ⑤变更联动。
本脚本做 ④对称校验: 自动比对「回测/首页注入的入样判定」vs「board_etf_map 重算 + 白名单 + yaml 声明」。

4 断言(任一 FAIL 打印明确错误并以非0退出, FAIL 阻断上线, 同 §22 数据一致性校验逻辑):
  断言1 - 入样判定对称: overview.json signals_today 每信号 _bt_in_universe ⟺ 用 board_etf_map 重算
          (该 key 的 ETF 列表任一有非空 track_score; key 缺失=空=不在宇宙)逐条相等, 逐条不等 → FAIL 列明细。
          注: self-ETF(cgb_10y_etf 等 func=fund_etf_hist_sina)由 queries.py _self_etf_for 注入且无
          track_score → board_etf_map 无 key → 重算=False, 与注入值一致, 天然通过。
  断言2 - 候选信号类型 ⊆ 白名单: overview 信号中, _bt_in_universe=True 且为买入候选的信号, 其类型必须
          ∈ config/universe_rules.yaml buy_whitelist; 其余 in-universe 信号必须是已知展示类
          (sell/sell_stop_loss/band_hold/band_sell, 展示不入选); 出现未知类型泄漏 → FAIL。
  断言3 - 回测交易无排除类别: signal_kelly_trades.json 全部交易标的(index_id)不得属排除类别
          (债类 cgb_* / 情绪 s.* / 全球商品利率 g.* / 港股行业 hk_* / 空数组 ftse100·kospi), 且
          交易 signal 必须 ⊆ buy_whitelist。
  断言4 - yaml 排除类别 ⟺ map 实际缺失: yaml 声明排除类别的匹配指数 id(indicators.yaml indices +
          overview 信号中出现的 id)必须按 mode 正确体现在 board_etf_map:
          absent      → 该 id 不应是 map key(或为 self_etf_exception 由 self 兜底);
          empty_array → 该 id 是 map key 且值为空数组 [];
          反向: 遍历 map 全部 key, 任何命中排除类别 pattern 却「应 absent 却带数据」的 key → FAIL。

数据源:
  - config/universe_rules.yaml  规则单一事实源(排除类别/白名单/self例外)
  - config/indicators.yaml      指数目录(枚举排除类别匹配的指数 id)
  - data/board_etf_map.json     map[key]=list(ETF)(入样依赖判定基准)
  - data/signal_kelly_trades.json 回测交易(嵌套 quadrants[quadrant][mode]=[trade,...], 行内 index 1=index_id, 2=signal)
  - static-site/data/overview.json 今日 overview(signals_today 每信号 _bt_in_universe + signal 类型)

用法:
  python scripts/check_universe_alignment.py                          # 全量校验(默认路径相对脚本)
  python scripts/check_universe_alignment.py --repo /path/to/trade     # 指定仓库根(相对解析所有输入)
  python scripts/check_universe_alignment.py --overview X --board-map Y --trades Z --config C --indicators I
  python scripts/check_universe_alignment.py --deploy-mode            # deploy 接入(任何 FAIL 以非0退出)

退出码:
  0 = 全部 PASS
  1 = 有 FAIL(任一断言 FAIL → 阻断上线)

deploy.sh 接入(step 1.1 check_data_integrity 之后同链):
  "$PY" "$REPO/scripts/check_universe_alignment.py" --repo "$REPO" --deploy-mode
  rc=$?; [ $rc -ne 0 ] && exit $rc
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent          # .../scripts
DEFAULT_REPO = SCRIPT_DIR.parent                       # .../trade

# 已知展示类信号(overview 展示用, 永不作为 AI 建议/回测候选, 不入白名单)
DISPLAY_ONLY_SIGNALS = {"sell", "sell_stop_loss", "band_hold", "band_sell"}

# 排除类别 pattern 从 yaml 读, 本处仅放「排除类别之外」的展示信号说明, 供日志参考
RESULTS: dict[str, str] = {}   # 断言名 -> "PASS"/"FAIL"


def load_yaml(path: Path):
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _fmt_assert(name: str, ok: bool, detail: str) -> str:
    status = "PASS" if ok else "FAIL"
    RESULTS[name] = status
    return f"[{status}] {name}\n    {detail}"


def _match_any(id_: str, patterns) -> bool:
    """patterns 可为 str 或 list[str], 命中任一前缀/字面即 True。"""
    if isinstance(patterns, str):
        patterns = [patterns]
    return any(id_.startswith(p) or id_ == p for p in patterns)


def build_excluded_ids(rules, indicators, overview) -> dict[str, dict]:
    """枚举每个排除类别的匹配指数 id → 该 id 的 mode/name。

    id 来源: indicators.yaml indices + overview signals_today(补 g.*/s.* 等不在指数目录的信号)。
    """
    idx_ids = [i.get("id") for i in indicators.get("indices", []) if i.get("id")]
    ov_ids = []
    for s in overview.get("signals_today", []) or []:
        if s.get("index_id"):
            ov_ids.append(s["index_id"])
    all_ids = set(idx_ids) | set(ov_ids)

    out: dict[str, dict] = {}   # id -> {mode, name}
    for cat in rules.get("excluded_categories", []):
        patterns = cat.get("match")
        for iid in all_ids:
            if _match_any(iid, patterns):
                out[iid] = {"mode": cat.get("mode"), "name": cat.get("name")}
    return out


def assertion1(overview, board_map) -> bool:
    """断言1: overview _bt_in_universe ⟺ board_etf_map 重算。"""
    st = overview.get("signals_today", []) or []
    mismatches = []
    for s in st:
        iid = s.get("index_id")
        etfs = board_map.get(iid) or []
        recompute = any(e.get("track_score") is not None for e in etfs)
        if recompute != s.get("_bt_in_universe"):
            mismatches.append((iid, s.get("signal"), s.get("_bt_in_universe"), recompute))
    if mismatches:
        det = f"共 {len(st)} 信号, {len(mismatches)} 条不一致:\n    " + \
              "\n    ".join(f"{m[0]} signal={m[1]} overview_bt={m[2]} recompute={m[3]}" for m in mismatches)
    else:
        det = f"{len(st)} 个 signals_today 的 _bt_in_universe 与 board_etf_map 重算全部一致"
    return (len(mismatches) == 0, det)


def assertion2(overview, buy_whitelist) -> bool:
    """断言2: overview 候选信号类型 ⊆ buy_whitelist(未知类型泄漏拦截)。"""
    st = overview.get("signals_today", []) or []
    whitelist = set(buy_whitelist)
    bad = []
    n_cand = 0
    for s in st:
        if not s.get("_bt_in_universe"):
            continue
        sig = s.get("signal")
        if sig in whitelist:
            n_cand += 1
        elif sig in DISPLAY_ONLY_SIGNALS:
            continue
        else:
            bad.append((s.get("index_id"), sig))
    if bad:
        det = f"{len(bad)} 条 in-universe 信号类型既非白名单亦非已知展示类:\n    " + \
              "\n    ".join(f"{b[0]} signal={b[1]}" for b in bad)
    else:
        det = (f"in-universe 候选买入信号 {n_cand} 条全部 ∈ buy_whitelist{list(whitelist)}, "
               f"其余 in-universe 均为展示类{DISPLAY_ONLY_SIGNALS}")
    return (not bad, det)


def assertion3(trades, buy_whitelist, excluded_categories) -> bool:
    """断言3: 回测交易无排除类别 + 交易 signal ⊆ buy_whitelist。"""
    whitelist = set(buy_whitelist)
    quadrants = trades.get("quadrants", {}) or {}
    bad_ids, bad_sigs = [], []
    total = 0
    for qk, modes in quadrants.items():
        if not isinstance(modes, dict):
            continue
        for mk, rows in modes.items():
            for r in rows:
                if not isinstance(r, (list, tuple)) or len(r) < 3:
                    continue
                total += 1
                iid, sig = r[1], r[2]
                if sig not in whitelist:
                    bad_sigs.append((qk, mk, iid, sig))
                for cat in excluded_categories:
                    if _match_any(iid, cat.get("match")):
                        bad_ids.append((qk, mk, iid, sig, cat.get("name")))
    if bad_ids or bad_sigs:
        det = f"共 {total} 笔交易, 违规 {len(bad_ids)} 条类别 + {len(bad_sigs)} 条信号:"
        if bad_ids:
            det += "\n    排除类别命中: " + "\n    ".join(
                f"{b[0]}/{b[1]} {b[2]} {b[3]} ({b[4]})" for b in bad_ids[:30])
        if bad_sigs:
            det += "\n    非白名单信号: " + "\n    ".join(
                f"{b[0]}/{b[1]} {b[2]} {b[3]}" for b in bad_sigs[:30])
    else:
        det = f"{total} 笔交易全部 ∈ buy_whitelist 且无排除类别(债/情绪/商品/港股行业/空数组)标的"
    return (not bad_ids and not bad_sigs, det)


def assertion4(board_map, excluded_ids, self_etf_exception, excluded_categories) -> bool:
    """断言4: yaml 排除类别 ⟺ board_etf_map 实际缺失/空数组一致(双向)。"""
    problems = []
    empty_array_ids = {iid for iid, v in excluded_ids.items() if v["mode"] == "empty_array"}
    absent_ids = {iid for iid, v in excluded_ids.items() if v["mode"] == "absent"}

    # 正向: 排除类别 id 必须按 mode 正确体现
    for iid in sorted(absent_ids):
        if iid in board_map and board_map[iid]:
            problems.append(f"应 absent({excluded_ids[iid]['name']}) 却带数据: {iid}")
        elif iid in board_map and not board_map[iid]:
            # absent 类但 map 有该 key 为空数组 —— 债类意外留空数组, 提示但非严格 FAIL
            problems.append(f"应 absent({excluded_ids[iid]['name']}) 却为空数组(建议整类不建 key): {iid}")
    for iid in sorted(empty_array_ids):
        if iid not in board_map:
            problems.append(f"应 empty_array({excluded_ids[iid]['name']}) 却缺失 key: {iid}")
        elif board_map.get(iid):
            problems.append(f"应 empty_array({excluded_ids[iid]['name']}) 却有 {len(board_map[iid])} 个ETF: {iid}")

    # 反向: 遍历 map 全 key, 命中排除类别 pattern 却应 absent 却带数据 → FAIL
    for key in board_map:
        if key == "_meta" or not board_map.get(key):
            continue
        for cat in excluded_categories:
            if cat.get("mode") == "absent" and _match_any(key, cat.get("match")):
                problems.append(f"map 意外含应 absent({cat['name']}) 且带数据的 key: {key}")
                break

    # self_etf_exception 只作信息提示(它在 map 里天然 absent, 由 self 兜底)
    exc_notes = []
    for iid in (self_etf_exception or {}):
        if iid not in board_map:
            exc_notes.append(f"self例外 {iid}({self_etf_exception[iid].get('match_method')}) 无 map key, 由 self 兜底")

    if problems:
        det = f"{len(problems)} 处排除类别未正确体现在 board_etf_map:\n    " + "\n    ".join(problems[:30])
    else:
        det = (f"排除类别全部正确: absent={sorted(absent_ids)}, empty_array={sorted(empty_array_ids)}"
               + (f"; {', '.join(exc_notes)}" if exc_notes else ""))
    return (not problems, det)


def main() -> int:
    ap = argparse.ArgumentParser(description="凯利回测/首页AI建议入样宇宙规则对称校验(§23.6)")
    ap.add_argument("--repo", default=str(DEFAULT_REPO), help="仓库根(相对解析所有输入)")
    ap.add_argument("--config", default=None, help="universe_rules.yaml 路径(默认 {repo}/config/universe_rules.yaml)")
    ap.add_argument("--indicators", default=None, help="indicators.yaml 路径(默认 {repo}/config/indicators.yaml)")
    ap.add_argument("--overview", default=None, help="overview.json 路径(默认 {repo}/static-site/data/overview.json)")
    ap.add_argument("--board-map", default=None, help="board_etf_map.json 路径(默认 {repo}/data/board_etf_map.json)")
    ap.add_argument("--trades", default=None, help="signal_kelly_trades.json 路径(默认 {repo}/data/signal_kelly_trades.json)")
    ap.add_argument("--deploy-mode", action="store_true", help="deploy 接入模式(任一 FAIL 以非0退出阻断上线)")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    cfg_path = Path(args.config) if args.config else repo / "config" / "universe_rules.yaml"
    ind_path = Path(args.indicators) if args.indicators else repo / "config" / "indicators.yaml"
    ov_path = Path(args.overview) if args.overview else repo / "static-site" / "data" / "overview.json"
    map_path = Path(args.board_map) if args.board_map else repo / "data" / "board_etf_map.json"
    tr_path = Path(args.trades) if args.trades else repo / "data" / "signal_kelly_trades.json"

    for p, label in [(cfg_path, "universe_rules.yaml"), (ind_path, "indicators.yaml"),
                     (ov_path, "overview.json"), (map_path, "board_etf_map.json"), (tr_path, "signal_kelly_trades.json")]:
        if not p.exists():
            print(f"✗ 缺少数据源 {label}: {p}", file=sys.stderr)
            return 1

    rules = load_yaml(cfg_path)
    indicators = load_yaml(ind_path)
    overview = json.load(open(ov_path, encoding="utf-8"))
    board_map = json.load(open(map_path, encoding="utf-8"))
    trades = json.load(open(tr_path, encoding="utf-8"))

    buy_whitelist = rules.get("buy_whitelist", [])
    excluded_categories = rules.get("excluded_categories", [])
    self_etf_exception = rules.get("self_etf_exception", {})

    # 断言4 需要排除类别匹配的 id 全集
    excluded_ids = build_excluded_ids(rules, indicators, overview)

    print("=== check_universe_alignment.py(§23.6 入样宇宙规则对称校验) ===")
    print(f"  universe_rules.yaml : {cfg_path}")
    print(f"  overview            : {ov_path}  signals_today={len(overview.get('signals_today', []) or [])}")
    print(f"  board_etf_map       : {map_path}  keys={len([k for k in board_map if k != '_meta'])}")
    print(f"  signal_kelly_trades : {tr_path}  quadrants={len(trades.get('quadrants', {}) or {})}")
    print()

    ok = True
    results = []
    for a in (assertion1, assertion2, assertion3):
        passed, detail = a(overview, board_map) if a is assertion1 else (
            a(overview, buy_whitelist) if a is assertion2 else a(trades, buy_whitelist, excluded_categories))
        results.append((a.__name__, passed, detail))
        ok = ok and passed
    passed4, det4 = assertion4(board_map, excluded_ids, self_etf_exception, excluded_categories)
    results.append(("assertion4", passed4, det4))
    ok = ok and passed4

    for name, passed, detail in results:
        print(_fmt_assert(name, passed, detail))
        print()

    if not ok:
        print("✗ 校验未通过: 入样宇宙规则存在不一致(§23.6 对称校验 FAIL, 阻断上线)")
        return 1
    print("✓ 入样宇宙规则全部对齐(§23.6 对称校验 PASS)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
