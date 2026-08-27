#!/usr/bin/env python3
"""check_north_gap_backfill.py — 北向深缺口分轮回补逻辑机检(v1.1.7 P1 修复验证)。

目的: 证明 a_fund_north HKEX 主源在「长假/长停机后缺口 >10 自然日」场景下,
分轮累积回补能在 3 轮内闭合缺口、不再递增丢日;并回归 days 显式/plain 等旧行为。
方法口径: 纯逻辑级 mock(monkeypatch gap 查询/闭合探测/HKEX 请求/state 三件套),
不触网、不读写真实 sentiment.db 与 state 文件,可任意时段安全运行(盘中亦可)。
输入依赖: 无(全部内存模拟)。
输出: 终端逐场景 PASS/FAIL 单行摘要;exit 0=全 PASS / 1=有 FAIL。
复现命令: python3 scripts/check_north_gap_backfill.py
数据版本/口径: today 锚定 2026-08-27(周四);D0=2026-08-12 为库内既有连续段最后一天
(gap=15 自然日>上限10→触发深缺口);HKEX 源保留窗下界 2025-12-29(早于此全 404);
周末无数据。真值链路: fetch_north_fund_hkex(app/collector/direct.py)/plan_north_gap_window。
"""
import contextlib
import datetime as dt
import io
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.collector import direct  # noqa: E402

TODAY = dt.date(2026, 8, 27)        # 周四(锚定固定日期保证断言确定性)
D0 = dt.date(2026, 8, 12)           # 最后好日子(周三)
SRC_FLOOR = dt.date(2025, 12, 29)   # HKEX 源保留窗下界(实测),更早全 404
ONE_DAY = dt.timedelta(days=1)

FAKE_JS = ('tabData = [{"market":"SSE Northbound","content":[{"table":{"tr":'
           '[{"td":[["136,054.83"]]}]}}]},{"market":"SZSE Northbound","content":'
           '[{"table":{"tr":[{"td":[["147,782.45"]]}]}}]}];')


class PinnedDate(dt.date):
    """date 子类,today() 钉死到 TODAY(mock direct._dt.date 用)。"""

    @classmethod
    def today(cls):
        return TODAY


class DTProxy:
    """转发 datetime 模块,仅 date 换成 PinnedDate(fetch 内 today=_dt.date.today())。"""

    def __getattr__(self, name):
        if name == "date":
            return PinnedDate
        return getattr(dt, name)


class FakeWorld:
    """内存模拟库 + HKEX 源 + 分轮 state。"""

    def __init__(self, last_good_day=D0):
        self.db_rows = set()
        d = last_good_day                       # 既有完好段:last_good_day 及更早全在库
        floor = min(last_good_day - ONE_DAY * 300, SRC_FLOOR - ONE_DAY * 60)
        while d >= floor:
            if d.weekday() < 5:
                self.db_rows.add(d.strftime("%Y%m%d"))
            d -= ONE_DAY
        self.last_good_day = last_good_day
        self.state_earliest = None              # 分轮前沿(date or None)
        self.events = []                        # state 变更轨迹 [("save","YYYYMMDD")/"clear"]
        self.existed_hit = False                # 本轮闭合探测是否命中既有行
        self.fail_once = None                   # 瞬态故障注入:此日期首次请求抛异常(reviewer F1 证伪用)
        self.hkex_calls = 0

    def gap(self):                               # mock _north_fund_gap_days(按模拟库 MAX 重算)
        mx = max(self.db_rows)
        return (TODAY - dt.datetime.strptime(mx, "%Y%m%d").date()).days, True

    def exists(self, ds):                        # mock 闭合探测
        hit = ds in self.db_rows
        if hit:
            self.existed_hit = True
        return hit

    def hkex_get(self, url, **kw):               # mock HKEX 请求
        ds = url.split("data_tab_daily_")[1][:8]
        d = dt.datetime.strptime(ds, "%Y%m%d").date()
        if d.strftime("%Y%m%d") == str(self.fail_once):
            # 瞬态故障注入:只抛一次,之后同日正常(模拟网络抖动/超时)
            self.fail_once = None
            raise RuntimeError("mock transient network timeout")
        self.hkex_calls += 1

        class R:
            status_code = 200 if (SRC_FLOOR <= d <= TODAY and d.weekday() < 5) else 404
            text = FAKE_JS
        return R()

    def st_load(self):
        return self.state_earliest

    def st_save(self, d):
        self.state_earliest = d
        self.events.append(("save", d.strftime("%Y%m%d")))

    def st_clear(self):
        self.state_earliest = None
        self.events.append("clear")

    def ingest(self, rows):
        for r in rows:
            self.db_rows.add(r[0])


def run_round(w, days=None, auto_ingest=True, dt_proxy=None):
    """模拟执行一轮 fetch_north_fund_hkex(auto/manual),吞 stdout,返回 (rows, round_info)。"""
    ev_before = len(w.events)
    w.existed_hit = False
    with contextlib.redirect_stdout(io.StringIO()), \
         mock.patch.object(direct, "_dt", dt_proxy or DTProxy()), \
         mock.patch.object(direct, "_north_fund_gap_days", w.gap), \
         mock.patch.object(direct, "_north_fund_date_exists", w.exists), \
         mock.patch.object(direct, "_north_backfill_load_earliest", w.st_load), \
         mock.patch.object(direct, "_north_backfill_save_earliest", w.st_save), \
         mock.patch.object(direct, "_north_backfill_clear", w.st_clear), \
         mock.patch.object(direct.requests, "get", w.hkex_get):
        rows = direct.fetch_north_fund_hkex(days=days)
    new_ev = w.events[ev_before:]
    n_save = sum(1 for e in new_ev if e[0] == "save")
    n_clear = sum(1 for e in new_ev if e == "clear")
    frontier = next((e[1] for e in reversed(new_ev) if e[0] == "save"), None)
    if w.existed_hit and n_clear:
        kind = f"closed_on_existing({frontier}->{w.db_rows and ''}既有行)"
    elif n_clear:
        kind = "capped_giveup" if w.state_earliest is None else "plain_residue_clear"
    elif n_save:
        kind = f"deep_advance(frontier={frontier})"
    else:
        kind = "plain_or_noop"
    info = {
        "kind": kind,
        "cleared": w.state_earliest is None,
        "frontier": frontier,
        "nrows": len(rows),
    }
    if auto_ingest and days is None:
        w.ingest(rows)   # 真实链路=runner upsert 入库后再进入下一槽
    return rows, info


RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), str(detail)))


# ═══ 场景A(核心验收): 节假日后 15 自然日缺口,分轮回补 3 轮内闭合 ═══
w = FakeWorld()
rounds_a = []
for i in range(6):                                # 上限 6 轮防死循环;断言实际 ≤3
    _, info = run_round(w)
    rounds_a.append(info)
    if info["cleared"]:
        break
check("A1 缺口15自然日 ≤3 轮闭合", len(rounds_a) <= 3,
      f"轮数={len(rounds_a)} 序列={[(r['kind'], r['nrows']) for r in rounds_a]}")
expect = {(D0 + ONE_DAY * k).strftime("%Y%m%d")
          for k in range(1, (TODAY - D0).days + 1)
          if (D0 + ONE_DAY * k).weekday() < 5}
missing = expect - w.db_rows
check("A2 闭合后缺口区间全覆盖(D0+1..TODAY)", not missing,
      f"missing={sorted(missing)[:8]}")
check("A3 闭合后分轮前沿已清", w.state_earliest is None)
mx_now = dt.datetime.strptime(max(w.db_rows), "%Y%m%d").date()
gap_after = (TODAY - mx_now).days
check("A4 闭合后 gap 回归常规(≤上限)", gap_after + 1 <= direct.HKEX_DAYS_MAX,
      f"gap={gap_after}")
_, plain_probe = run_round(w, auto_ingest=False)
check("A5 闭合后再跑一轮回归常规增量(plain 窗=HKEX_DAYS_MIN 天)",
      plain_probe["kind"] == "plain_or_noop" and plain_probe["nrows"] ==
      len([d for d in (TODAY - ONE_DAY * k for k in range(direct.HKEX_DAYS_MIN))
           if d.weekday() < 5]),
      f"post_gap={gap_after} kind={plain_probe['kind']} nrows={plain_probe['nrows']}")

# ═══ 场景B: 常规增量 plan 窗口与旧公式逐位一致(min/max 夹紧,+1 含今日) ═══
for g in (0, 2, 3, 9):
    ws, we, m = direct.plan_north_gap_window(TODAY, gap=g, known=True)
    n_old = min(direct.HKEX_DAYS_MAX, max(direct.HKEX_DAYS_MIN, g + 1))
    check(f"B plain窗口=旧公式 gap={g}",
          m == "plain" and we == TODAY and ws == TODAY - ONE_DAY * (n_old - 1),
          f"plan=({ws},{we},{m}) old_n={n_old}")
# 边界: gap=10 → gap+1=11>上限10 → 进深缺口是修复预期;本轮窗口仍与旧公式同宽(不丢当日行为)
ws, we, m = direct.plan_north_gap_window(TODAY, gap=10, known=True)
check("B 边界 gap+1=11>上限→deep_start 但窗口与旧版同宽",
      m == "deep_start" and we == TODAY
      and ws == TODAY - ONE_DAY * (direct.HKEX_DAYS_MAX - 1),
      f"plan=({ws},{we},{m})")

# ═══ 场景C: days 显式传参不走 state(manual 行为与旧版兼容) ═══
w2 = FakeWorld()
probe = {"load_touched": False}


def _probe_load():
    probe["load_touched"] = True
    return None


with mock.patch.object(direct, "_north_backfill_load_earliest", _probe_load), \
     mock.patch.object(direct, "_dt", DTProxy()), \
     mock.patch.object(direct, "_north_fund_gap_days", w2.gap), \
     mock.patch.object(direct, "_north_fund_date_exists", w2.exists), \
     mock.patch.object(direct.requests, "get", w2.hkex_get), \
     contextlib.redirect_stdout(io.StringIO()):
    rows_c = direct.fetch_north_fund_hkex(days=5)
c_expect = {(TODAY - ONE_DAY * k).strftime("%Y%m%d")
            for k in range(5) if (TODAY - ONE_DAY * k).weekday() < 5}
got_c = {r[0] for r in rows_c}
check("C1 days显式不读state(manual路径)", not probe["load_touched"])
check("C2 days=5 取数与旧版一致(5自然日内全部非周末日)", got_c == c_expect,
      f"got={sorted(got_c)} expect={sorted(c_expect)}")

# ═══ 场景D: plan 纯函数各模式边界 ═══
ws, we, m = direct.plan_north_gap_window(TODAY, gap=None, known=False)
check("D1 no_db 保守上限窗", m == "no_db" and we == TODAY
      and ws == TODAY - ONE_DAY * (direct.HKEX_DAYS_MAX - 1))
ws, we, m = direct.plan_north_gap_window(TODAY, gap=None, known=True)
# S1(2026-08-27 用户拍板): full 库空场景恢复 HKEX_DAYS_FULL=90 既定口径——
# 210 是深缺口 backfill 硬顶(cap 场景),不混用于 full 初始化;此断言防再静默漂移
check("D2 full 库空全量窗=HKEX_DAYS_FULL(90)既定口径", m == "full"
      and ws == TODAY - ONE_DAY * (direct.HKEX_DAYS_FULL - 1),
      f"plan=({ws},{we},{m}) days_full={direct.HKEX_DAYS_FULL}")
check("D2b HKEX_DAYS_FULL 数值锁 90(S1)", direct.HKEX_DAYS_FULL == 90,
      f"got={direct.HKEX_DAYS_FULL}")
ws, we, m = direct.plan_north_gap_window(TODAY, gap=20, known=True)
check("D3 deep_start 首轮", m == "deep_start" and we == TODAY
      and ws == TODAY - ONE_DAY * (direct.HKEX_DAYS_MAX - 1))
res = dt.date(2026, 8, 18)
ws, we, m = direct.plan_north_gap_window(TODAY, gap=15, known=True, resume_from=res)
check("D4 deep_resume 无缝衔接(前沿前一天起向回 span_max)",
      m == "deep_resume" and we == res - ONE_DAY
      and ws == res - ONE_DAY * direct.HKEX_DAYS_MAX)
ws, we, m = direct.plan_north_gap_window(
    TODAY, gap=300, known=True, resume_from=TODAY - ONE_DAY * 400)
check("D5 deep_cap 越硬顶放弃并回归常规窗", m == "deep_cap")
# 回归用例(卡死锁防线): 前沿恰好等于硬顶下界必须同样放弃(曾因 < vs <= 判定
# 致窗口倒挂 win_start>win_end 零迭代死锁,v1.1.7 P1 修复实测抓出)
lower_b = TODAY - ONE_DAY * (direct.HKEX_BACKFILL_CAP_DAYS - 1)
ws, we, m = direct.plan_north_gap_window(TODAY, gap=300, known=True,
                                         resume_from=lower_b)
check("D5b 前沿==硬顶下界也放弃(防窗口倒挂死锁)", m == "deep_cap",
      f"lower_bound={lower_b} plan_mode={m}")
ws, we, m = direct.plan_north_gap_window(
    TODAY, gap=300, known=True, resume_from=TODAY - ONE_DAY * 25)
check("D6 前沿存在期间即使 gap 收窄也续采(deep 优先于 plain)", m == "deep_resume")
ws2, we2, m2 = direct.plan_north_gap_window(TODAY, gap=9, known=True,
                                            resume_from=TODAY - ONE_DAY * 60)
check("D6b 有前沿时窗口不以 TODAY 为终点(继续向更早推进)",
      m2 == "deep_resume" and we2 < TODAY)

# ═══ 场景E: 超长停机(缺口>硬顶)推到硬顶后收敛放弃,不崩不死循环不空转 ═══
far_d0 = TODAY - ONE_DAY * 240                   # 缺口 240 自然日 > cap 210
w3 = FakeWorld(last_good_day=far_d0)
e_kinds = []
e_frontiers = []
for i in range(60):                              # 硬顶预算 ~cap/span_max≈21+全量窗缓冲,60 安全阀
    _, info = run_round(w3)
    e_kinds.append(info["kind"])
    e_frontiers.append(info["frontier"])
    if info["cleared"]:
        break
budget = direct.HKEX_BACKFILL_CAP_DAYS // direct.HKEX_DAYS_MAX + 5
check("E1 超长缺口在硬顶预算内收敛终止(state清空)", w3.state_earliest is None
      and len(e_kinds) <= budget,
      f"轮数={len(e_kinds)}(预算{budget}) 尾两轮={e_kinds[-2:]}")
stalls = [i for i in range(1, len(e_frontiers))
          if e_frontiers[i] == e_frontiers[i - 1] and e_frontiers[i]]
check("E2 无前沿停滞轮(死锁/空转防线:相邻轮frontier不得重复)", not stalls,
      f"停滞位置={stalls}" if stalls else "每轮前沿均推进")
check("E3 终止方式=闭合于既有行或放弃分轮",
      any(k.startswith(("closed_on_existing", "capped_giveup")) for k in e_kinds),
      f"尾轮={e_kinds[-1]}")
covered_ws = {(TODAY - ONE_DAY * k).strftime("%Y%m%d") for k in range(0, 100)}
haved = covered_ws & {d for d in w3.db_rows if d > far_d0.strftime("%Y%m%d")}
check("E4 停机区间近端已被多轮大幅回补", len(haved) >= 55,
      f"近100自然日内已补={len(haved)}行")

# ═══ 场景F: 软 deadline 半途中断 → 前沿按实际覆盖写,下轮接力最终闭合(审计主场景) ═══
_SLOW = {"n": 0}


class SlowClockProxy(DTProxy):
    """datetime.now() 按调用次数加速流逝,模拟处理 ~4 个工作日后撞 60s 软 deadline。"""

    def __getattr__(self, name):
        if name == "date":
            return PinnedDate
        if name == "datetime":
            base = dt.datetime

            class FakeDT(base):
                @classmethod
                def now(cls, tz=None):
                    _SLOW["n"] += 1
                    return base.now(tz) + dt.timedelta(seconds=40 * max(0, _SLOW["n"] - 1) // 2)
            return FakeDT
        return getattr(dt, name)


w4 = FakeWorld()
f_rounds = []
for i in range(6):
    _SLOW["n"] = 0                      # 只让第一轮撞 deadline,后续轮正常速率
    _, info = run_round(w4, dt_proxy=None if i else SlowClockProxy())
    f_rounds.append(info)
    if info["cleared"]:
        break
# 慢时钟节奏推导: t0 后各工作日 check 时钟 +0/+40/+40/+80s → 第3个日子的
# deadline 判定前中断 → 首轮实收前2个工作日,前沿记到 20260826(第2个工作日,
# 而非计划窗口底 20260818)——「部分采集按实际覆盖写前沿」的行为锁定
adv0 = f_rounds[0]
plan_wd = len([d for d in ((TODAY - ONE_DAY * k) for k in range(direct.HKEX_DAYS_MAX))
               if d.weekday() < 5])
check("F1 首轮因 deadline 部分采集且前沿记到实际覆盖日(非计划窗口底)",
      adv0["kind"].startswith("deep_advance") and adv0["frontier"] == "20260826"
      and 0 < adv0["nrows"] < plan_wd,
      f"首轮(kind={adv0['kind'][:20]}, frontier={adv0['frontier']}, "
      f"nrows={adv0['nrows']}, 计划工作日={plan_wd})")
missing_f = expect - w4.db_rows
check("F2 多轮接力后缺口区间仍全覆盖", not missing_f,
      f"missing={sorted(missing_f)[:8]}" if missing_f else "全覆盖")
check("F3 最终闭合清态", w4.state_earliest is None)

# ═══ 场景G: state 三件套真实文件 IO 往返 + 损坏容错(临时目录,不触真库) ═══
import tempfile  # noqa: E402
with tempfile.TemporaryDirectory() as td:
    fake_db = Path(td) / "sentiment.db"
    with mock.patch("app.db.DB_PATH", fake_db):
        e = dt.date(2026, 8, 18)
        direct._north_backfill_save_earliest(e)
        got = direct._north_backfill_load_earliest()
        check("G1 save/load 往返一致(原子写)", got == e,
              f"saved={e} loaded={got} file={direct._north_backfill_state_path().name}")
        direct._north_backfill_clear()
        check("G2 clear 后读 None", direct._north_backfill_load_earliest() is None)
        p = direct._north_backfill_state_path()
        p.write_text("{bad json!!", encoding="utf-8")
        check("G3 损坏 state 容错为 None(不影响主流程)",
              direct._north_backfill_load_earliest() is None)
        direct._north_backfill_clear()   # 清理残片

# ═══ 场景H(reviewer F1 证伪式): 窗口中段单日瞬态失败 → 多轮最终闭合且无洞 ═══
# bug 假设: 现实现 oldest_done=d 在发请求前记录、except-continue 不回滚 → 该日被标
# "已覆盖"却从未入库,后续轮 resume 只向更早推进不再回头 → 该日永久有洞。
# 预期: 修复前 H2 FAIL(missing 含故障日);修复后(处方a: 瞬态失败立即停轮不推进)
# 下轮整窗重试,H 全 PASS。
w6 = FakeWorld()
w6.fail_once = "20260819"                       # 深缺口首轮窗口(0818~0827)中段的工作日
h_rounds = []
for i in range(8):
    _, info = run_round(w6)
    h_rounds.append(info)
    if info["cleared"]:
        break
check("H1 瞬态失败场景多轮内收敛闭合", w6.state_earliest is None and len(h_rounds) <= 5,
      f"轮数={len(h_rounds)} 序列={[(r['kind'][:24], r['nrows']) for r in h_rounds]}")
missing_h = expect - w6.db_rows
check("H2 无永久洞(含曾瞬态失败的 0819 必须最终入库)", not missing_h,
      f"missing={sorted(missing_h)[:8]}" if missing_h else "缺口区间全覆盖")
check("H3 曾失败日 20260819 有数据行", "20260819" in w6.db_rows)

# ═══ 场景I(codex P2): _north_fund_date_exists 校验 value——NULL/0 占位不当闭合 ═══
import sqlite3 as _sq3  # noqa: E402
with tempfile.TemporaryDirectory() as td_i:
    fake_db_i = Path(td_i) / "sentiment.db"
    conn = _sq3.connect(fake_db_i)
    conn.execute("CREATE TABLE daily_metric (date TEXT, metric_id TEXT, value REAL)")
    conn.executemany(
        "INSERT INTO daily_metric VALUES (?, 'a_fund_north', ?)",
        [("20260812", None),      # NULL 占位行
         ("20260811", 0.0),       # 0 异常占位
         ("20260810", 2838.37)])  # 正常有效值
    conn.commit()
    conn.close()
    with mock.patch("app.db.DB_PATH", fake_db_i):
        check("I1 NULL 行不算已存在(不得据此闭合)", not direct._north_fund_date_exists("20260812"))
        check("I2 0 值行不算已存在", not direct._north_fund_date_exists("20260811"))
        check("I3 有效值行算已存在", direct._north_fund_date_exists("20260810"))
        check("I4 无行日 False", not direct._north_fund_date_exists("20260805"))

# ── 汇总 ──
fails = [r for r in RESULTS if not r[1]]
print(f"===== 北向分轮回补机检: {len(RESULTS) - len(fails)}/{len(RESULTS)} PASS =====")
for name, ok, detail in RESULTS:
    print(f"{'PASS' if ok else 'FAIL'}  {name}  |  {detail}")
sys.exit(1 if fails else 0)
