# -*- coding: utf-8 -*-
"""#228 M1「EXTRA 轮次完整性」通道 + M2「fetch_news 轮次开始标记」回归测试(2026-10-07)。

被测语义(schedule_monitor 第 6 通道): EXTRA 两任务(gen_daily_brief / fetch_news)不在 TASKS 表、
不经 systemd 退出码通道 ⇒ 被 systemd TimeoutStartSec 杀时监控原报「OK 无漏跑」。M1 = 直接判
「本轮开始了没跑完」(round_state=='started_unfinished' + unit 非运行态 + age>宽限)。

取用方式(防第二份实现漂移, memory repro-script-second-implementation-drift):
  - 数据层(gen_schedule_stats.py): **import 真模块**, 直接调 scan_marker_log / _unit_active_state,
    不抄副本。
  - 判定层(schedule_monitor.sh): 从 python heredoc 里 **ast 提取**常量 + M1 那个 for 块源码后
    exec(同一份实现), 与 test_monitor_resource_inprogress_20261005.py 同法。

样本铁律(§18 L49「断言输入必须取真实生产实测样本」): fixtures/228/*.log 全部是**云上生产日志
逐行原样切片**(ssh 只读拉取, 字节级保真, 未做任何改写)。唯一例外 = fetch_news 两个 fixture 的
`轮次开始` **合成标记行**(M2 尚未上线, 该行按 M2 代码 format string 生成): 被杀轮 fixture 时间戳取
报告 §1.3 直证的真实被杀轮启动时点(2026-10-04 20:01:00), 已完成轮 fixture 取该轮真实起始时刻
(2026-10-07 10:01:02, 与同居真实日志行 `date=2026-10-07` 对齐) —— 二者均非「看起来合理」的杜撰样本;
daily_brief 的 3 个 fixture 与其余各行均为真实切片, 无合成。fixture 出处/切片行号见
各用例注释; 拉取命令:
  ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cat /home/ubuntu/code/trade-data/data/logs/daily_brief.log'
  ssh ... 'cat /home/ubuntu/code/trade-data/data/logs/fetch_news_launchd.log'
本测试 static-only: 只读文件 + 纯函数, 绝不 source/exec 业务脚本主体, 无任何外发(§18 L50/L48)。
"""
import ast
import datetime
import sys
from pathlib import Path
from unittest import mock

import pytest

import gen_schedule_stats as G  # conftest 已把 scripts/ 入 sys.path

FIX = Path(__file__).absolute().parent / "fixtures" / "228"
ROOT = Path(__file__).absolute().parent.parent.parent
MONITOR = ROOT / "scripts" / "schedule_monitor.sh"

DB = "gen_daily_brief"
FN = "fetch_news"
EXTRA = {x["task"]: x for x in G.EXTRA_MARKER_SCANS}


def _scan(task, log_path, tail=600):
    """按 EXTRA_MARKER_SCANS 的真配置调真 scan_marker_log → (state, ts, completion, anomaly)。"""
    m = EXTRA[task]
    anomaly, _skip, ts, comp, _wrt = G.scan_marker_log(
        Path(log_path), tail,
        round_start_re=G._compile_rsre(m.get("round_start_re")),
        completion_re=G._compile_rsre(m.get("completion_re")),
        round_begin_re=G._compile_rsre(m.get("round_begin_re")),
    )
    state = "no_start" if ts is None else ("completed" if comp else "started_unfinished")
    return state, ts, comp, anomaly


# ══════════════════════════════ 数据层: scan_marker_log 轮次完整性 ══════════════════════════

def test_real_sample_completed_round():
    """真实云上 L2..L32(09-14/09-15 两条「开始生成」+ L29 `✓ 完成`) → completed。

    正常收尾轮不得被误报(M1 判据成立的前提)。"""
    state, ts, comp, _ = _scan(DB, FIX / "daily_brief_20260914_completed.log")
    assert (state, comp) == ("completed", True)
    assert ts == "2026-09-15 20:40:00"  # 最后一个「开始生成」行的真实时间戳


def test_real_sample_killed_round_is_started_unfinished():
    """真实云上 L184..L195(09-28/29/30 三条「开始生成」, 其后无 ✓) → started_unfinished。

    即报告 §1.5 的 8 次杀之一(09-30): M1 的核心真阳性场景 —— 修 M1 前该轮永不被报。"""
    state, ts, comp, _ = _scan(DB, FIX / "daily_brief_20260928_killed.log")
    assert state == "started_unfinished"
    assert comp is False
    assert ts == "2026-09-30 20:40:00"


def test_real_sample_holiday_tail_skip_counts_as_terminal():
    """真实云上 L183..L205(09-30 开始生成 后紧跟 10-01..10-06 六条「非交易日,跳过」) → completed。

    ⚠️ 实施期按真实样本发现的修正(报告 §3 M1 未建模「跳过轮」): 跳过行是脚本的**自终结**终态
    (run_daily_brief.sh L26/L34/L41, 0 退出)。若不算终态, 最后一个「开始生成」轮窗口会兜到文件尾
    并越过整个长假 ⇒ 长假全程挂一条 7 天前的假 SEVERE。"""
    state, ts, comp, _ = _scan(DB, FIX / "daily_brief_20260927_holiday_tail.log")
    assert state == "completed", "长假跳过轮必须被认作终态, 否则假期全程假阳性"
    assert ts == "2026-09-30 20:40:00"


def test_mid_round_notify_skip_text_is_not_terminal(tmp_path):
    """降判别力守卫: 真实生产日志里同轮**中途**有
    `[notify] telegram bot_token/chat_id ... 跳过发送`(云上 L186/192/197, 正常轮的中间输出)。

    该行若被当作终态, 被杀轮就被掩盖 ⇒ 终态正则必须**前缀锚定** `[run_daily_brief]`, 不能裸「跳过」。"""
    raw = (FIX / "daily_brief_20260927_holiday_tail.log").read_text(encoding="utf-8")
    assert "[notify] telegram bot_token/chat_id 占位符或缺失，跳过发送" in raw, \
        "fixture 里少了真实的中途跳过行? 本用例判别力前提消失, 需重新取样本"
    # 去掉 10-01..10-06 六条真终态后: 窗口只剩 09-30 开始生成 + 中途 notify 跳过
    truncated = "".join(l for l in raw.splitlines(True) if "非交易日,跳过" not in l)
    tmp = tmp_path / "mid_round_notify.log"
    tmp.write_text(truncated, encoding="utf-8")
    state, _, comp, _ = _scan(DB, tmp)
    assert state == "started_unfinished", "[notify] 中途跳过行不得被当作轮次终态"
    assert comp is False


def test_real_sample_fetch_news_killed_round():
    """真实云上 fetch_news 尾部 + M2 标记行 → started_unfinished
    (报告 §1.3: 10-04 20:01 轮 20:11 被 600s 外墙杀, 该轮原日志零痕迹)。"""
    state, ts, comp, _ = _scan(FN, FIX / "fetch_news_20261004_killed.log", tail=400)
    assert state == "started_unfinished"
    assert comp is False
    assert ts == "2026-10-04 20:01:00"


def test_real_sample_fetch_news_completed_round():
    """真实云上最后一轮三行(`已写`/`R2 同步 OK`/`同步上线完成`) + M2 标记行 → completed。"""
    state, ts, comp, _ = _scan(FN, FIX / "fetch_news_20261004_completed.log", tail=400)
    assert (state, comp) == ("completed", True)
    assert ts == "2026-10-07 10:01:02"


def test_fetch_news_pre_m2_log_is_no_start():
    """M2 上线前的老日志(无「轮次开始」行) → no_start(优雅降级不误报); 且既有异常窗口
    (从「已写」起)行为不变 ⇒ 新轴不取代旧判据。"""
    state, ts, _, _ = _scan(FN, FIX / "fetch_news_20261007_tail.log", tail=400)
    assert (state, ts) == ("no_start", None)


# ══════════════════════════════ 冻结守卫: 既有窗口逐字不变(§23.7) ══════════════════════════

def test_frozen_round_start_windows_byte_for_byte():
    """既有 P1-A/P1-B 轮次作用域窗口(round_start_re)不得因 M1 改动而变。"""
    assert EXTRA[DB]["round_start_re"] == r'\[run_daily_brief\] schedule_enabled=true,开始生成 '
    assert EXTRA[FN]["round_start_re"] == r'\[fetch_news\] 已写 '


def test_m1_fields_present_and_marker_separated():
    """M1 三字段齐; fetch_news「开始」标记刻意与异常窗口起点分离(round_begin_re != round_start_re)。"""
    for t in (DB, FN):
        assert {"round_begin_re", "completion_re", "systemd_label"} <= set(EXTRA[t])
    assert EXTRA[DB]["round_begin_re"] is None, "daily_brief 两窗口重合 ⇒ None 复用"
    assert EXTRA[FN]["round_begin_re"] == r'\[fetch_news\] 轮次开始 '
    assert EXTRA[FN]["round_begin_re"] != EXTRA[FN]["round_start_re"], \
        "fetch_news 轮次起点必须与「已写」实窗口分离(否则被杀轮仍零痕迹)"
    assert EXTRA[DB]["systemd_label"] == "com.trade.daily-brief"
    assert EXTRA[FN]["systemd_label"] == "com.trade.fetch-news"


def test_completion_re_covers_real_terminal_texts():
    """终态正则覆盖真实终态行(逐字取自生产日志 / run_daily_brief.sh 源码)。"""
    d = G._compile_rsre(EXTRA[DB]["completion_re"])
    for line in ("[run_daily_brief] ✓ 完成",
                 "[run_daily_brief] ✗ 失败 rc=1(不阻塞主流程)",
                 "[run_daily_brief] 非交易日,跳过(不生成不覆盖不通知) 2026-10-06 20:40:02",
                 "[run_daily_brief] 配置缺失 /x/config/daily_brief.yaml,跳过"):
        assert d.search(line), line
    assert not d.search("[notify] telegram bot_token/chat_id 占位符或缺失，跳过发送（subject=x）")
    f = G._compile_rsre(EXTRA[FN]["completion_re"])
    assert f.search("[fetch_news] 已写 /home/ubuntu/.../news_digest.json + 归档 ... date=2026-10-07")
    assert f.search("✗ [fetch_news] 上传失败")


# ══════════════════════════════ 数据层: _unit_active_state 的 LoadState 守卫(§18 L49) ═════════

class _R:
    def __init__(self, rc, out):
        self.returncode, self.stdout = rc, out


def _uactive(label, rc, out, monkeypatch):
    """按 Linux 分支跑真 _unit_active_state(subprocess 打桩; platform 强制 linux, 尺子跨环境自验)。"""
    monkeypatch.setattr(G.subprocess, "run", lambda cmd, **kw: _R(rc, out))
    with mock.patch.object(G.sys, "platform", "linux"):
        return G._unit_active_state(label)


def test_unit_active_state_requires_loaded(monkeypatch):
    """⚠️ #223-4 教训: `systemctl show <不存在的 unit>` 不报错、会回填编译期默认
    (ActiveState=inactive) ⇒ 必须先核 LoadState=='loaded' 才敢采信 ActiveState。"""
    assert _uactive("com.trade.daily-brief", 0, "LoadState=not-found\nActiveState=inactive\n",
                    monkeypatch) is None
    assert _uactive("com.trade.daily-brief", 0, "LoadState=loaded\nActiveState=activating\n",
                    monkeypatch) == "activating"
    assert _uactive("com.trade.daily-brief", 0, "LoadState=loaded\nActiveState=inactive\n",
                    monkeypatch) == "inactive"


def test_unit_active_state_none_paths(monkeypatch):
    """rc!=0 / 抛异常 / 非 Linux / label 空 或 非 com.trade. 前缀 ⇒ None(不猜运行态, 退化纯 age)。"""
    assert _uactive("com.trade.daily-brief", 1, "", monkeypatch) is None

    def _boom(cmd, **kw):
        raise OSError("no systemctl")

    monkeypatch.setattr(G.subprocess, "run", _boom)
    with mock.patch.object(G.sys, "platform", "linux"):
        assert G._unit_active_state("com.trade.daily-brief") is None
    with mock.patch.object(G.sys, "platform", "darwin"):
        assert G._unit_active_state("com.trade.daily-brief") is None
    assert G._unit_active_state(None) is None
    assert G._unit_active_state("some.other.label") is None


# ══════════════════════════════ 判定层: 从 schedule_monitor.sh 提取真实现 ══════════════════════════

def _heredoc_source():
    lines = MONITOR.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next(i for i, l in enumerate(lines) if "<<'PYEOF'" in l)
    end = next(i for i, l in enumerate(lines) if i > start and l.strip() == "PYEOF")
    return "".join(lines[start + 1:end])


@pytest.fixture(scope="module")
def m1_src():
    """提取 M1 常量 + M1 那个 for 块(以 EXTRA_ROUND_INCOMPLETE 出现为判别, 与停摆块同型区分)。"""
    src = _heredoc_source()
    consts, block = [], None
    # M1 块在 module 级 `try:` 体内(不在 tree.body 顶层) ⇒ 用 ast.walk 深搜。
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in ("EXTRA_ROUND_INCOMPLETE", "ROUND_INCOMPLETE_GRACE")
                for t in node.targets):
            consts.append(ast.get_source_segment(src, node) + "\n")
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Name) and node.iter.id == "stats":
            seg = ast.get_source_segment(src, node)
            if "EXTRA_ROUND_INCOMPLETE" in seg:
                block = seg + "\n"
    assert len(consts) == 2, "schedule_monitor.sh 未找到 M1 两条常量(被改名/删除? 本测试锚点需同步)"
    assert block, "未找到 M1 判定块(含 EXTRA_ROUND_INCOMPLETE 的 `for _es in stats`)"
    return "".join(consts), block


@pytest.fixture()
def m1_run(m1_src):
    """exec 真源码 → (rows, alert_state={}) -> (alerts, alert_state, seen_keys_this_run)。"""
    consts, block = m1_src

    def _drive(rows, now=None, alert_state=None):
        ns = {"datetime": datetime.datetime, "timedelta": datetime.timedelta,
              "NOW": now or datetime.datetime(2026, 10, 7, 21, 30, 0),
              "alerts": [], "alert_state": {} if alert_state is None else alert_state,
              "seen_keys_this_run": set(), "print": lambda *a, **k: None}
        exec(compile(consts, "<m1-consts>", "exec"), ns)  # noqa: S102
        ns["stats"] = rows
        exec(compile(block, "<m1-block>", "exec"), ns)    # noqa: S102
        return ns["alerts"], ns["alert_state"], ns["seen_keys_this_run"]

    return _drive


def test_m1_threshold_constants(m1_src):
    """阈值须 > 对应 unit 现 TimeoutStartSec(1740s/1080s) 且 << 停摆阈值(26h/4h) —— 漂移守卫。"""
    consts, _ = m1_src
    ns = {"datetime": datetime.datetime, "timedelta": datetime.timedelta}
    exec(compile(consts, "<c>", "exec"), ns)  # noqa: S102
    assert ns["EXTRA_ROUND_INCOMPLETE"] == {DB: datetime.timedelta(minutes=45),
                                            FN: datetime.timedelta(minutes=30)}
    assert ns["ROUND_INCOMPLETE_GRACE"] == datetime.timedelta(minutes=10)


def _row(task, state, ts="2026-10-07 20:40:00", ustate="inactive", uexit=143, anomaly=None):
    return {"task": task, "round_state": state, "round_start_ts": ts,
            "unit_active_state": ustate, "unit_last_exit": uexit, "log_anomaly": anomaly}


def test_m1_fires_on_started_unfinished(m1_run):
    """三元素满足 → 一条 SEVERE + alert_state active + seen key(结构对齐停摆块)。"""
    alerts, st, seen = m1_run([_row(DB, "started_unfinished")])
    assert len(alerts) == 1
    a = alerts[0]
    assert a.startswith("SEVERE: gen_daily_brief 轮次未正常收尾(开始 2026-10-07 20:40:00")
    assert "unit last_exit=143" in a and "systemd" in a
    assert seen == {"gen_daily_brief|round_incomplete"}
    assert st["gen_daily_brief|round_incomplete"]["status"] == "active"
    assert st["gen_daily_brief|round_incomplete"]["keyword"] == "round_incomplete"


def test_m1_suppresses_when_unit_still_running(m1_run):
    """unit 仍在跑(慢跑) ⇒ 不报(ActiveState 三态全宽容)。"""
    for ustate in ("active", "activating", "reloading"):
        alerts, st, seen = m1_run([_row(DB, "started_unfinished", ts="2026-10-07 20:00:00",
                                        ustate=ustate)])
        assert (alerts, st, seen) == ([], {}, set()), ustate


def test_m1_grace_window(m1_run):
    """unit 状态可读时: 未超宽限(10min) ⇒ 不报; 刚过 ⇒ 报。"""
    assert m1_run([_row(DB, "started_unfinished", ts="2026-10-07 21:25:00")])[0] == []   # age 5min
    assert len(m1_run([_row(DB, "started_unfinished", ts="2026-10-07 21:19:00")])[0]) == 1  # age 11min


def test_m1_fallback_pure_age_when_unit_unreadable(m1_run):
    """读不到 unit 状态(非 Linux/unit 不存在) ⇒ 退化纯 age, 用更大阈值(45/30min)防误报。"""
    assert m1_run([_row(DB, "started_unfinished", ts="2026-10-07 21:10:00", ustate=None)])[0] == []
    assert len(m1_run([_row(DB, "started_unfinished", ts="2026-10-07 20:44:00", ustate=None)])[0]) == 1
    assert m1_run([_row(FN, "started_unfinished", ts="2026-10-07 21:09:00", ustate=None)])[0] == []
    assert len(m1_run([_row(FN, "started_unfinished", ts="2026-10-07 20:58:00", ustate=None)])[0]) == 1


def test_m1_denoise_when_log_anomaly_present(m1_run):
    """同轮 log_anomaly 已命中(✗/⚠) ⇒ M1 不报(更具体信号优先, 防双响; 不削弱既有判别力)。"""
    alerts, st, seen = m1_run([_row(DB, "started_unfinished", anomaly={"keyword": "✗"})])
    assert (alerts, st, seen) == ([], {}, set())


def test_m1_skips_other_states_and_bad_ts(m1_run):
    """completed/no_start/空 ts/坏格式 ts/非 EXTRA 任务/缺字段 ⇒ 全不报(不误伤, 不因脏数据崩)。"""
    rows = [
        _row(DB, "completed"), _row(DB, "no_start"),
        _row(DB, "started_unfinished", ts=""), _row(DB, "started_unfinished", ts="不是日期"),
        _row("update_all", "started_unfinished"),
        {"task": DB},
    ]
    alerts, st, seen = m1_run(rows)
    assert (alerts, st, seen) == ([], {}, set())


def test_m1_repeat_uses_existing_state(m1_run):
    """持续中(已 active) ⇒ 只更新 last_alerted, 不重发(与停摆块去重口径一致)。"""
    st = {"gen_daily_brief|round_incomplete": {"status": "active",
                                               "first_seen": "2026-10-07 20:40:00",
                                               "last_alerted": "2026-10-07 20:40:00"}}
    alerts, st2, _ = m1_run([_row(DB, "started_unfinished")], now=datetime.datetime(2026, 10, 7, 22, 0, 0),
                            alert_state=st)
    assert alerts == []
    assert st2["gen_daily_brief|round_incomplete"]["last_alerted"] == "2026-10-07 22:00:00"


def test_m1_recovered_state_refires(m1_run):
    """恢复后再现(status != active) ⇒ 重新发(不因历史状态静默)。"""
    st = {"gen_daily_brief|round_incomplete": {"status": "recovered",
                                               "first_seen": "2026-10-01 20:40:00",
                                               "last_alerted": "2026-10-01 20:40:00"}}
    alerts, st2, _ = m1_run([_row(DB, "started_unfinished")], alert_state=st)
    assert len(alerts) == 1
    assert st2["gen_daily_brief|round_incomplete"]["status"] == "active"


# ══════════════════════════════ M2: fetch_news「轮次开始」标记 ══════════════════════════════

def test_m2_marker_has_flush_true():
    """标记行必须 flush=True —— 全文件原 0 处 flush, 块缓冲下 SIGTERM 被杀即丢(报告 §1.3)。"""
    src = (ROOT / "scripts" / "fetch_news.py").read_text(encoding="utf-8")
    line = next(l for l in src.splitlines() if "[fetch_news] 轮次开始 " in l)
    assert "flush=True" in line, "标记行丢了 flush=True ⇒ 被杀轮仍零痕迹(M2 失效)"
    assert line.index("轮次开始") < src.index("[fetch_news] 已写 "), \
        "标记必须在首个「已写」之前打(否则不是「开始」信号)"


def test_m2_main_emits_marker_and_zero_outbound(monkeypatch, tmp_path, capsys):
    """打桩跑真 main(): ①「轮次开始」行落 stdout ②全程零真实外发(§18 L48 验收点)。

    零外发硬闸: urlopen / subprocess.run 被替换为「一调用即 AssertionError」⇒ 任何真实
    网络上传/子进程都会让本测试响亮失败, 而不是静默发出真邮件/真 R2 上传。"""
    import re
    import fetch_news as F

    calls = {"sync": 0, "write": 0}
    monkeypatch.setattr(F, "fetch_eastmoney", lambda *a, **k: [])
    monkeypatch.setattr(F, "fetch_cls", lambda *a, **k: [])
    monkeypatch.setattr(F, "fetch_jin10", lambda *a, **k: [])
    monkeypatch.setattr(F, "build_digest", lambda *a, **k: ([], []))
    monkeypatch.setattr(F, "read_existing_archive", lambda *a, **k: {})
    monkeypatch.setattr(F, "_merge_new_into_archive", lambda *a, **k: ([], []))
    monkeypatch.setattr(F, "archive_path", lambda d: tmp_path / f"{d}.json")
    monkeypatch.setattr(F, "OUT_FILE", tmp_path / "news_digest.json")
    monkeypatch.setattr(F, "DATA_DIR", tmp_path / "d")
    monkeypatch.setattr(F, "ARCHIVE_DIR", tmp_path / "a")
    monkeypatch.setattr(F, "_write_index", lambda *a, **k: None)
    monkeypatch.setattr(F, "atomic_write_json",
                        lambda *a, **k: calls.__setitem__("write", calls["write"] + 1))
    monkeypatch.setattr(F, "sync_news_digest_live",
                        lambda *a, **k: calls.__setitem__("sync", calls["sync"] + 1))

    def _boom(*_a, **_k):
        raise AssertionError("自测发生真实外发/子进程 —— 违反 §18 L48 零外发约束")

    monkeypatch.setattr(F.urllib.request, "urlopen", _boom)
    monkeypatch.setattr(F.subprocess, "run", _boom)
    monkeypatch.setattr(sys, "argv", ["fetch_news.py"])

    F.main()

    out = capsys.readouterr().out
    assert re.search(r"\[fetch_news\] 轮次开始 \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", out), \
        f"未看到轮次开始标记; stdout={out!r}"
    assert calls["write"] == 2 and calls["sync"] == 1  # 走完了主流程(全被打桩截住)