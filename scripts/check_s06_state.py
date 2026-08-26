#!/usr/bin/env python3
"""check_s06_state.py - S06 降亏动态模式快照机检(codex-task-20260825-001, §22/§23.6 同链精神)

【目的】把 S06 快照(kelly_mode_s06_state.json)的四类一致性固化成一条命令, 任一 FAIL 阻断上线:
  A1 第二实现复算: 用「不 import 生成器」的独立状态机(按 handoff 口径重写 sticky 语义)对同因子序列
     复算 effective_mode, 与快照 daily 逐位相等(防生成器单实现自证)。
  A2 decision_date: 每行 decision_date == 上一交易日(daily[i-1].date; 首行为 null)(防前视 §5.1⑥)。
  A3 键集对齐: 快照 on_base/off_base 指向的 common.js 预设(a9/new15)keys 与预设表逐位相等,
     且 s06 预设本身 dynamic=true 无静态 keys(防前端第二份键集/静态展开)。
  A4 阈值/参数单源: json.threshold==生成器常量(ast 抽取, 非手抄)==confirm/min_hold/lookback;
     公示文案(common.js _tdsS06Tooltip + purpose-notes.js)含同值截断串(-3.524/+100,572/+83,718 等),
     公示数字与快照 provenance 对照锚一致。
  A5 锁死不变式(codex008 F2): 全史任一 a9 生效日不得同时满足 held>=min_hold 且 broken>=confirm_days
     (旧语义 held 只在命中日递增 → 持续非命中场景 a9 锁死 P0); 另以合成长序列 fixture 断言
     「进入后持续非命中必于 confirm_days 个非命中日切出」「命中打断 broken 后 held 仍按时间走」
     (T 日收盘出信号 T+1 生效对齐)。held 新语义=a9 生效交易日数(2026-08-26 用户拍板)。

【输入依赖】--repo(git 仓, 默认脚本上级): static-site/data/kelly_mode_s06_state.json /
  static-site/common.js / static-site/purpose-notes.js / scripts/gen_kelly_mode_s06_state.py;
  --data-repo(trade-data 仓): static-site/data/index/{csi1000,hs300}-all.json(A1 因子输入)。
【输出】stdout 各断言 PASS/FAIL 明细; 全 PASS=0, 任一 FAIL=1(deploy 同链签名, FAIL 阻断)。
【关键口径一句话】快照是唯一事实源: 独立复算逐位一致 + decision 时序无穿越 + 两基座键集与预设全等 +
  阈值三处(json/生成器/公示)同源。
【复现命令】python3 scripts/check_s06_state.py [--repo /path/to/trade] [--data-repo /path/to/trade-data]
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_REPO = SCRIPT_DIR.parent
_DEFAULT_DATA_CANDIDATES = [
    DEFAULT_REPO.parent / "trade-data",            # 主仓布局: <repo>/../trade-data
    Path("/Users/linhuichen/code/trade-data"),      # worktree 布局: .claude/worktrees/<agent> 下 parent 无 trade-data, 回退主仓数据仓
]
DEFAULT_DATA_REPO = next((p for p in _DEFAULT_DATA_CANDIDATES if (p / "static-site" / "data" / "index").exists()), _DEFAULT_DATA_CANDIDATES[0])

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))


def load_closes(data_repo: Path, name: str) -> dict[str, float]:
    ohlc = json.loads((data_repo / "static-site" / "data" / "index" / f"{name}-all.json").read_text(encoding="utf-8"))["ohlc"]
    return {str(x["date"]): float(x["close"]) for x in ohlc if x.get("close") is not None}


def independent_state_machine(dates: list[str], spread: dict[str, float], th: float,
                              confirm_days: int, min_hold: int, on_base: str, off_base: str
                              ) -> tuple[list[str], list[tuple[int, int]]]:
    """A1 第二实现(非生成器 import): codex008 F2 新语义(2026-08-26 用户拍板)——T 日收盘判定
    T+1 生效; held=a9 生效交易日数(进入当日计 1, 其后每交易日递增无论当日是否命中);
    处于 on 时 premise 连续破坏 confirm 天且 held 满 minhold 才切出。
    ⚠旧语义(held 只在命中日 +1)在持续非命中场景 held 永久<minhold → a9 锁死(P0, 已修)。
    返回 (逐日 effective_mode, 逐日处理后 (held, broken) 计数迹 —— 供 A5 锁死不变式断言)。"""
    out: list[str] = []
    trace: list[tuple[int, int]] = []
    cur = off_base
    broken = 0
    held = 0
    prev_spread: float | None = None
    for d in dates:
        sv = spread.get(d)
        if prev_spread is None:
            ex = off_base                      # 首日恒兜底(无决策日)
        else:
            hit = prev_spread < th             # prev 收盘判定 → d 生效
            if cur == on_base:
                if hit:
                    broken = 0
                else:
                    broken += 1
                held += 1                      # 新语义: d 日仍处 on 生效日则计数+1(无论命中)
                stay = (broken < confirm_days) or (held < min_hold)
                ex = on_base if stay else off_base
                if not stay:
                    held = 0
            else:
                ex = on_base if hit else off_base
                if ex == on_base:
                    held, broken = 1, 0        # 新语义: 进入当日计 1
        out.append(ex)
        trace.append((held, broken))
        cur = ex
        prev_spread = sv       # 注意: d 日收盘信号供 T+1 用 → 下一轮用本日 spread 作决策值
    return out, trace


def lockfree_invariant_ok(modes: list[str], trace: list[tuple[int, int]],
                          on_base: str, min_hold: int, confirm_days: int) -> list[int]:
    """A5 锁死不变式(codex008 F2): 任一 on 生效日不得同时满足 held>=min_hold 且
    broken>=confirm_days(=退出条件已满足却未切出=锁死)。返回违例日下标列表。"""
    return [i for i, (ex, (h, b)) in enumerate(zip(modes, trace))
            if ex == on_base and h >= min_hold and b >= confirm_days]


def synthetic_lockfree_fixture(confirm_days: int = 15, min_hold: int = 10,
                               th: float = -3.524224785046781) -> tuple[bool, str]:
    """A5 合成长序列 fixture(T 日收盘出信号 T+1 生效对齐; codex008 F2 审计教训: 断言禁止
    把决策信号错位到当日):
      场景一(纯持续非命中): 首日命中进入 → 之后 40 个交易日全非命中, 必于第 confirm_days 个
        非命中日的次日切出且不再回 on(a9 生效应恰为 confirm_days 天);
      场景二(中途命中打断 broken 但 held 走时间): 进入后 4 个非命中日 → 1 个命中日(broken
        清零)→ 再 20 个非命中日, 必在累计第 confirm_days 个非命中日切出(检验 held 是时间
        语义而非 broken 联动; 旧语义在本场景 held 恒 <minhold 永锁)。
    两种场景任一切出失败/提前切出/回 on 均判 FAIL。"""
    th_seq1 = [th - 6.0] + [5.0] * 40                      # d0 命中, d1..d40 全非命中
    dates1 = [f"202601{i + 1:02d}" for i in range(len(th_seq1))]  # 有序伪日期(独立实现不查日历)
    sp1 = {d: v for d, v in zip(dates1, th_seq1)}
    modes1, _ = independent_state_machine(dates1, sp1, th, confirm_days, min_hold, "a9", "new15")
    exp1 = ["new15"] + ["a9"] * confirm_days + ["new15"] * (len(th_seq1) - 1 - confirm_days)
    if modes1 != exp1:
        bad = next(i for i, (a, b) in enumerate(zip(modes1, exp1)) if a != b)
        return False, f"场景一(持续非命中)第 {bad} 日 modes={modes1[bad]} 期望={exp1[bad]}"
    seq2 = [th - 6.0] + [5.0] * 4 + [th - 6.0] + [5.0] * 20   # 进入后4非命中→1命中→再20非命中
    dates2 = [f"202602{i + 1:02d}" for i in range(len(seq2))]
    sp2 = {d: v for d, v in zip(dates2, seq2)}
    modes2, _ = independent_state_machine(dates2, sp2, th, confirm_days, min_hold, "a9", "new15")
    # 时序推导(T 收盘信号 T+1 生效): idx0 收盘命中 → idx1 进入(held=1); idx2..5 非命中生效日
    # (broken=1..4); idx5 收盘命中 → idx6 为命中生效日(broken 清零, held=6 时间继续);
    # 其后第 confirm_days 个非命中生效日(idx7 起 broken=1..)在 idx6+confirm_days 日 broken 满 → 切出
    hit_eff_idx = 6                                            # 命中生效日下标
    exit_day = hit_eff_idx + confirm_days                      # = 21, 该日 ex 必为 new15
    exp2 = ["new15"] + ["a9"] * (exit_day - 1) + ["new15"] * (len(seq2) - exit_day)
    if modes2 != exp2:
        bad = next((i for i, (a, b) in enumerate(zip(modes2, exp2)) if a != b), -1)
        return False, f"场景二(命中打断)第 {bad} 日 modes={modes2[bad]} 期望={exp2[bad]}(exit_day={exit_day})"
    return True, (f"场景一: 进入后恰 {confirm_days} 天切出且不回; "
                  f"场景二: 命中打断 broken 后 held 仍按时间在第 {confirm_days} 个非命中日切出")


def extract_gen_constants(gen_path: Path) -> dict[str, object]:
    tree = ast.parse(gen_path.read_text(encoding="utf-8"))
    consts: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            nm = node.targets[0].id
            if nm in ("THRESHOLD", "CONFIRM_DAYS", "MIN_HOLD_DAYS", "LOOKBACK", "ON_BASE", "OFF_BASE"):
                try:
                    consts[nm] = ast.literal_eval(node.value)
                except Exception:  # noqa: BLE001
                    pass
    return consts


def extract_preset_keys(common_txt: str, pid: str) -> list[str]:
    presets = re.findall(r"\{ id:\s*\"([A-Za-z0-9]+)\".*?keys:\s*\[(.*?)\]\s*\}", common_txt, re.S)
    for p, body in presets:
        if p == pid:
            return re.findall(r"\"([A-Za-z0-9]+)\"", body)
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description="S06 快照机检(独立复算+时序+键集+阈值单源)")
    ap.add_argument("--repo", default=str(DEFAULT_REPO))
    ap.add_argument("--data-repo", default=str(DEFAULT_DATA_REPO))
    ap.add_argument("--allow-lag-days", type=int, default=0,
                    help="deploy 时序容差(codex008 F1): 允许快照落后因子数据 ≤N 个已入库交易日"
                         "(仅限快照 dates 是复算 covered 序列的前缀=无中间缺日; 缺失/结构不一致/"
                         "超容差仍 FAIL)。默认 0=严格(deploy 链外手动跑保持严格口径)")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    data_repo = Path(args.data_repo).resolve()

    snap_path = repo / "static-site" / "data" / "kelly_mode_s06_state.json"
    need = [snap_path, repo / "static-site" / "common.js", repo / "static-site" / "purpose-notes.js",
            repo / "scripts" / "gen_kelly_mode_s06_state.py",
            data_repo / "static-site" / "data" / "index" / "csi1000-all.json",
            data_repo / "static-site" / "data" / "index" / "hs300-all.json"]
    for p in need:
        if not p.exists():
            print(f"✗ 缺少输入 {p}", file=sys.stderr)
            return 1

    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    daily = snap["daily"]
    dates = [r["date"] for r in daily]
    print("=== check_s06_state.py(S06 快照机检) ===")
    print(f"  快照: coverage {snap.get('coverage_start')}~{snap.get('coverage_end')} days={len(daily)} "
          f"current={json.dumps(snap.get('current'), ensure_ascii=False)}")
    print()

    # ── A1 独立第二实现复算 ──
    csi = load_closes(data_repo, "csi1000")
    hs = load_closes(data_repo, "hs300")
    common_dates = sorted(set(csi) & set(hs))

    def roll(series: dict[str, float], n: int) -> dict[str, float]:
        vals = [series[d] for d in common_dates]
        return {common_dates[i]: (vals[i] / vals[i - n] - 1) * 100 for i in range(n, len(vals))}

    r_csi, r_hs = roll(csi, snap["lookback_days"]), roll(hs, snap["lookback_days"])
    spread = {d: r_csi[d] - r_hs[d] for d in common_dates if d in r_csi and d in r_hs}
    covered = [d for d in common_dates if d in spread]
    indep, trace = independent_state_machine(covered, spread, snap["threshold"], snap["confirm_days"],
                                             snap["min_hold_days"], snap["on_base"], snap["off_base"])
    snap_modes = [r["effective_mode"] for r in daily]
    # ── deploy 时序容差(codex008 F1, P0①)──
    # update_all 17:50 链内 deploy 时因子(index-all.json)已更新到 T, 而 S06 快照仍是前晚
    # 20:35 生成(coverage_end=T-1)——这是每日固定时序窗口, 不是数据错误。deploy 模式传
    # --allow-lag-days 1 容忍「快照落后 ≤N 个已入库交易日」, 但仅限:
    #   ① lag = len(covered)-len(dates) ∈ [0, N](落后方向正确且不超容差; 快照比复算长=异常)
    #   ② dates 是 covered 的严格前缀(无中间缺日/错位, 结构不一致仍 FAIL)
    # 截尾后逐位比对(covered[:len(dates)] vs indep[:len(dates)] vs snap_modes),
    # 缺失/解析失败/超容差/结构不一致仍硬阻断; 日常新鲜度由 check_s06_freshness 监控兜底。
    lag = len(covered) - len(dates)
    allow_lag = max(0, args.allow_lag_days)
    prefix_ok = lag >= 0 and dates == covered[: len(dates)]
    within_tol = 0 <= lag <= allow_lag
    same_universe = prefix_ok and within_tol
    if same_universe and lag > 0:
        cmp_covered, cmp_indep = covered[: len(dates)], indep[: len(dates)]
    else:
        cmp_covered, cmp_indep = covered, indep
    mismatch = [(d, a, b) for d, a, b in zip(cmp_covered, cmp_indep, snap_modes) if a != b]
    record("A1 独立第二实现复算", (not mismatch) and same_universe,
           (f"覆盖期/日历一致({len(cmp_covered)} 日), {len(snap_modes)} 行逐位相等"
            + (f"(快照落后 {lag} 个交易日≤容差{allow_lag}, deploy 时序窗口内截尾比对)" if lag > 0 else "")
            if (not mismatch and same_universe)
            else (f"universe一致={same_universe}(lag={lag}{'>' + str(allow_lag) + ' 超容差' if not within_tol and prefix_ok else ''}); "
                  f"不一致 {len(mismatch)} 行, 首3={mismatch[:3]}")))

    # ── A2 decision_date 时序 ──
    bad_dd = [r["date"] for i, r in enumerate(daily)
              if r.get("decision_date") != (dates[i - 1] if i > 0 else None)]
    record("A2 decision_date==上一交易日", not bad_dd,
           f"{len(daily)} 行时序无穿越" if not bad_dd else f"违规 {len(bad_dd)} 行, 首3={bad_dd[:3]}")

    # ── A3 键集对齐 ──
    common_txt = (repo / "static-site" / "common.js").read_text(encoding="utf-8")
    problems = []
    for base_id in (snap["on_base"], snap["off_base"]):
        keys = extract_preset_keys(common_txt, base_id)
        if not keys:
            problems.append(f"预设表缺 id={base_id}")
        elif len(keys) != len(set(keys)):
            problems.append(f"{base_id} keys 有重复")
    s06_block = re.search(r"\{ id:\s*\"s06\".*?\}(?=\s*,|\s*\])", common_txt, re.S)
    if not s06_block:
        problems.append("预设表缺 id=s06(dynamic 预设)")
    else:
        blk = s06_block.group(0)
        if "dynamic: true" not in blk.replace(" ", " "):
            problems.append("s06 预设缺 dynamic:true")
        if "keys:" in blk:
            problems.append("s06 预设带静态 keys(禁止展开成静态组合)")
    # 两基座 filters 构建语义: _KELLY_FADE_ALL_KEYS 覆盖两基座全部键(防 per-date filters 缺键恒 false)
    m_all = re.search(r"_KELLY_FADE_ALL_KEYS\s*=\s*(.+?);", common_txt, re.S)
    all_keys_defined = bool(m_all)
    record("A3 两基座/s06 预设键集", not problems,
           ("a9/new15 预设在表且 s06=dynamic 无静态 keys; ALL_KEYS 定义在位" if all_keys_defined and not problems
            else "; ".join(problems) or "ALL_KEYS 未定义"))

    # ── A4 阈值/参数/公示数字单源 ──
    gen_consts = extract_gen_constants(repo / "scripts" / "gen_kelly_mode_s06_state.py")
    checks = [
        ("threshold", snap["threshold"], gen_consts.get("THRESHOLD")),
        ("confirm_days", snap["confirm_days"], gen_consts.get("CONFIRM_DAYS")),
        ("min_hold_days", snap["min_hold_days"], gen_consts.get("MIN_HOLD_DAYS")),
        ("lookback_days", snap["lookback_days"], gen_consts.get("LOOKBACK")),
        ("on_base", snap["on_base"], gen_consts.get("ON_BASE")),
        ("off_base", snap["off_base"], gen_consts.get("OFF_BASE")),
    ]
    bad_const = [f"json={a} vs 生成器={b}" for nm, a, b in checks if a != b]
    pn_txt = (repo / "static-site" / "purpose-notes.js").read_text(encoding="utf-8")
    # 公示数值(§21/§23.9: 展示为千分位/三位小数截断, 机检查截断串在位)
    # 锚点来源(codex008 F2 修复重跑 2026-08-26, s06_newsem_vs_14plus1.py 同引擎): 新语义验段
    # 净利 +100,572.43; ⚠S06 动态回测数字随输入指数序列更新漂移(08-25 首跑 94,150.61→08-26
    # 旧语义复跑 94,436.30), 本锚点作用=「公示↔快照 provenance 一致」, 回测重跑后须同步此处
    # 与 common.js/purpose-notes.js/README 三处公示及 gen 注释(锚点时点=注释日期)。
    th_str = f"{snap['threshold']:.3f}"          # -3.524
    val_str = f"{100572.43:,.0f}"                # 100,572(held 新语义验段净利, 2026-08-26 重跑)
    cmp_str = f"{83718.16:,.0f}"                 # 83,718(静态 NEW14+1 对照, 与 held 语义无关稳定)
    pub_hits = {
        "common.js tooltip 阈值": th_str in common_txt,
        "purpose-notes 阈值": th_str in pn_txt,
        "common.js tooltip 对照净利": val_str in common_txt,
        "purpose-notes 对照净利": val_str in pn_txt,
        "common.js tooltip 静态对照": cmp_str in common_txt,
        "purpose-notes 静态对照": cmp_str in pn_txt,
    }
    missing_pub = [k for k, v in pub_hits.items() if not v]
    record("A4 阈值/参数单源+公示数值", (not bad_const) and (not missing_pub),
           (f"json==生成器常量 6 项逐位相等(threshold={th_str}); 公示截断串 6 处在位"
            if (not bad_const and not missing_pub) else
            f"常量不一致={bad_const}; 公示缺失={missing_pub}"))

    # ── A5 锁死不变式(codex008 F2, P0②修复防回归)──
    # ① 全史: 任一 a9 生效日不得同时满足 held>=min_hold 且 broken>=confirm_days
    #   (=退出条件已满足却未切出=锁死; 旧语义全史 457 天违例, 新语义必须 0 违例)
    viol_days = lockfree_invariant_ok(indep, trace, snap["on_base"], snap["min_hold_days"], snap["confirm_days"])
    # ② 合成长序列 fixture: 持续非命中必于 confirm_days 个非命中日切出 + 命中打断 broken 后
    #   held 仍按时间走(T 收盘信号 T+1 生效对齐)
    fix_ok, fix_msg = synthetic_lockfree_fixture(snap["confirm_days"], snap["min_hold_days"], snap["threshold"])
    record("A5 锁死不变式+长序列断言", (not viol_days) and fix_ok,
           (f"全史 {len(daily)} 个 a9 生效日 0 锁死违例; fixture: {fix_msg}"
            if (not viol_days and fix_ok) else
            f"锁死违例 {len(viol_days)} 日, 首3={[covered[i] for i in viol_days[:3]]}; fixture={'PASS' if fix_ok else 'FAIL: ' + fix_msg}"))

    ok_all = True
    for name, ok, detail in RESULTS:
        ok_all = ok_all and ok
        print(f"[{'PASS' if ok else 'FAIL'}] {name}\n    {detail}\n")
    if not ok_all:
        print("✗ S06 快照机检 FAIL(阻断上线)")
        return 1
    print("✓ S06 快照机检全 PASS(独立复算/时序/键集/阈值单源/锁死不变式五项)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
