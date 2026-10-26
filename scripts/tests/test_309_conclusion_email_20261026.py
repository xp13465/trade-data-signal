# -*- coding: utf-8 -*-
"""#309 F2: 结论「状态说明」邮件(可见性补位)用例。

任务书 4 条实现预期(逐条对应):
  A 结论非 OK + 本轮已发 ≥1 封告警邮件 ⇒ 不发(不冗余)
  B 结论非 OK + 本轮零告警邮件(如账本旧码不可信 / 同码去重) ⇒ 补发 1 封「状态说明」:
    标题一眼看出是状态说明、正文含完整结论行 + 一句「为什么不重复告警」
  C 结论 OK ⇒ 不发
  频率保护: 同一份结论内容 active 时不重发; 内容变化重发; 恢复后解除(恢复本身不发信);
  恢复后 6h 内同内容复发不重发(防结论 OK/异常抖动刷屏)。

全程 static-only: notify_runner 是可断言的 stub(不启子进程、不跑业务脚本、不碰 notify.py
真实渠道)⇒ 零真实外发(§18 L48)。判定/正文/落签全部来自 schedule_monitor.sh 的**生产
实现**(AST 提取, 非第二份实现 —— memory repro-script-second-implementation-drift)。
"""
import datetime

import pytest

import _monitor_conclusion_309 as m309

NOW = datetime.datetime(2026, 10, 26, 9, 42, 0)
OK_LINE = "OK 所有任务按计划执行，无漏跑，无退出失败; 覆盖 43/43(40 业务+基础, 3 自监控)"
OK_LINE_LOG_ONLY = "OK(仅日志口径, 覆盖 17/40; 本机无 systemd)"
BAD_LEDGER = ("1 个任务退出失败: ab_direction_anchor(Result=exit-code, exit=1, "
              "账本补位码, 新鲜度未确认, 不单独告警); 漏跑 0; "
              "覆盖 43/43(40 业务+基础, 3 自监控)")
BAD_DEDUP = ("有 1 条告警(见上方), 不判 OK; 覆盖 43/43(40 业务+基础, 3 自监控)")
BAD_OTHER = "stats 刷新失败(本轮读旧快照), 无法确认成功, 不判 OK; 覆盖 43/43(40 业务+基础, 3 自监控)"
SENT_OUT = "[notify] 汇总：已发出 email/feishu\n"
FAILED_OUT = "[notify] 汇总：全部渠道未发出（email=False feishu=False）\n"


class StubNotify:
    """notify.py 子进程替身: 记录每次命令, 返回固定输出(默认=确认送达)。"""

    def __init__(self, out=SENT_OUT):
        self.calls = []
        self.out = out

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        return self.out


def _run(concl, alert_mail_sent=0, state=None, now=NOW, out=SENT_OUT):
    """跑一次生产判定+发送动作; 返回 (结果, stub, save 记录, state)。"""
    state = {} if state is None else state
    stub = StubNotify(out)
    saves = []
    res = m309.maybe_send_conclusion_status_email()(
        concl, alert_mail_sent, state, now, stub, lambda s: saves.append(dict(s)))
    return res, stub, saves, state


# ── 场景 A: 结论非 OK, 但本轮已有告警邮件真发出 ⇒ 不发 ──────────────────────
def test_scene_a_has_alert_mail_no_extra_mail():
    res, stub, saves, state = _run(BAD_DEDUP, alert_mail_sent=1)
    assert res["reason"] == "has_alert_mail"
    assert res["sent"] is False
    assert stub.calls == []                      # 0 次调用
    assert saves == []                           # 不写 state
    assert not any(k.startswith("conclusion_status|") for k in state)


# ── 场景 B: 结论非 OK + 本轮零告警邮件 ⇒ 补发 1 封状态说明 ────────────────────
def test_scene_b_zero_alert_mail_sends_one_status_mail():
    res, stub, saves, state = _run(BAD_LEDGER, alert_mail_sent=0)
    assert res["sent"] is True
    assert len(stub.calls) == 1                  # 只发 1 封
    cmd = stub.calls[0]
    assert "notify.py" in cmd[1]
    subject, body = cmd[2], cmd[3]
    assert subject.startswith("[状态说明]")
    assert "状态说明" in subject                 # 标题一眼看出是状态说明
    assert "监控结论异常" in subject
    assert "计划任务异常" not in subject         # 不许长得像新故障告警
    assert "--severe" not in cmd                 # 不是 SEVERE 新故障
    assert "--from-prefix" in cmd and "[状态说明]" in cmd
    assert BAD_LEDGER in body                    # 正文含完整结论行
    assert "为什么没有对应的告警邮件" in body     # 一句「为什么不重复告警」
    assert "新鲜度未确认" in body                # 结合结论给出具体原因
    # 确认送达才落签 active
    key = res["key"]
    assert key.startswith("conclusion_status|") and len(res["digest"]) == 8
    assert state[key]["status"] == "active"
    assert state[key]["keyword"] == "conclusion_status"
    assert BAD_LEDGER[:50] in state[key]["line_sample"]
    assert len(saves) == 1 and saves[0][key]["status"] == "active"


@pytest.mark.parametrize("bad", [BAD_LEDGER, BAD_DEDUP, BAD_OTHER])
def test_scene_b_all_non_ok_text_variants_send_with_full_conclusion(bad):
    """三种真实结论形状(账本旧码 / 有N条告警被去重 / stats 刷新失败)都补发, 正文含原结论。"""
    res, stub, _saves, _state = _run(bad)
    assert res["sent"] is True and len(stub.calls) == 1
    assert bad in stub.calls[0][3]
    assert "为什么没有对应的告警邮件" in stub.calls[0][3]


def test_scene_b_dedup_wording_explains_dedup():
    _res, stub, _s, _st = _run(BAD_DEDUP)
    body = stub.calls[0][3]
    assert "同码去重或并入当日摘要" in body


def test_conclusion_html_special_chars_are_escaped():
    weird = "1 个任务退出失败: a<b>c & d; 覆盖 43/43(40 业务+基础, 3 自监控)"
    _res, stub, _s, _st = _run(weird)
    body = stub.calls[0][3]
    assert "a&lt;b&gt;c" in body and "a<b>c" not in body


def test_empty_conclusion_never_sends():
    res, stub, saves, state = _run("   ")
    assert res["reason"] == "empty" and res["sent"] is False
    assert stub.calls == [] and saves == [] and state == {}


def test_alert_mail_takes_precedence_over_same_content_state():
    """非 OK + 已有告警邮件 + 同内容摘要仍 active ⇒ 仍不发(先判已发邮件, 不改 state)。"""
    state = {}
    _run(BAD_DEDUP, state=state)
    res, stub, saves, _st = _run(BAD_DEDUP, alert_mail_sent=2, state=state)
    assert res["reason"] == "has_alert_mail" and stub.calls == [] and saves == []


def test_new_subject_and_key_are_not_absorbed_by_notify_gates():
    """新主题/键不得落进 notify 的域聚合/预算类别 —— 否则状态说明会被静默并入摘要。"""
    import alert_denoise_rules as adr

    key = "conclusion_status|deadbeef"
    subject = "[状态说明] 监控结论异常(本轮无告警邮件) 10-26 09:42"
    assert adr.domain_of(key, subject) is None
    assert adr.category_of(key, subject) is None


# ── 场景 C: 结论 OK ⇒ 不发(两种 OK 文案都算) ───────────────────────────────
@pytest.mark.parametrize("ok", [OK_LINE, OK_LINE_LOG_ONLY])
def test_scene_c_ok_never_sends(ok):
    res, stub, saves, state = _run(ok)
    assert res["reason"] == "ok"
    assert res["sent"] is False
    assert stub.calls == []
    assert saves == []
    assert state == {}


# ── 频率保护: 同一结论连跑两轮 ⇒ 第二轮 0 次调用 ────────────────────────────
def test_frequency_same_conclusion_twice_only_first_sends():
    state = {}
    res1, stub1, saves1, state = _run(BAD_LEDGER, state=state)
    res2, stub2, saves2, state = _run(BAD_LEDGER, state=state)
    assert res1["sent"] is True and len(stub1.calls) == 1
    assert res2["reason"] == "same_content_sent"
    assert res2["sent"] is False and stub2.calls == []
    assert saves2 == []                          # 无变化不重复落盘
    assert len(state) == 1                       # 摘要键不膨胀


# ── 内容变化 ⇒ 重新发一次, 且旧摘要键退休(仍只留 1 条) ─────────────────────
def test_content_change_resends_and_retires_old_key():
    state = {}
    _run(BAD_LEDGER, state=state)
    res2, stub2, _saves2, state = _run(BAD_OTHER, state=state)
    assert res2["sent"] is True and len(stub2.calls) == 1
    assert len(state) == 1
    assert res2["key"] in state


# ── 恢复正常: 解除频率保护但不额外发信; 6h 内同内容复发不重发 ────────────────
def test_recovery_releases_guard_without_mail_then_cooldown_blocks_flicker():
    state = {}
    _run(BAD_LEDGER, state=state)
    key = next(k for k in state if k.startswith("conclusion_status|"))

    res_ok, stub_ok, saves_ok, _state = _run(OK_LINE, state=state)
    assert res_ok["reason"] == "ok" and stub_ok.calls == []
    assert len(saves_ok) == 1                    # 状态翻转要落盘
    assert state[key]["status"] == "recovered"
    assert state[key]["last_recovered"] == "2026-10-26 09:42:00"

    # 恢复后 1h 同内容复发 ⇒ 抖动, 不重发
    res_flip, stub_flip, _s, _st = _run(
        BAD_LEDGER, state=state, now=NOW + datetime.timedelta(hours=1))
    assert res_flip["reason"] == "recurrence_cooldown"
    assert stub_flip.calls == []

    # 恢复后恰好 6h(边界: 判据是 >=)⇒ 已解除, 重新发一次
    res_edge, stub_edge, _se, _ste = _run(
        BAD_LEDGER, state=state, now=NOW + datetime.timedelta(hours=6))
    assert res_edge["sent"] is True and len(stub_edge.calls) == 1
    assert state[key]["status"] == "active"

    # 再过一轮同内容 ⇒ 频率保护(active)不再发
    res_again, stub_again, _sa, _sta = _run(
        BAD_LEDGER, state=state, now=NOW + datetime.timedelta(hours=7))
    assert res_again["reason"] == "same_content_sent" and stub_again.calls == []


# ── 发送未确认送达 ⇒ 不落签(下轮重试), 绝不把未发出当已通知 ─────────────────
def test_notify_not_confirmed_does_not_record_state():
    res, stub, saves, state = _run(BAD_LEDGER, out=FAILED_OUT)
    assert len(stub.calls) == 1                  # 试过了
    assert res["sent"] is False
    assert "error" not in res
    assert saves == []
    assert not any(k.startswith("conclusion_status|") for k in state)


def test_notify_runner_exception_is_swallowed_and_retried_next_round():
    state = {}
    calls = []

    def _boom(cmd):
        calls.append(list(cmd))
        raise TimeoutError("notify 超时")

    res = m309.maybe_send_conclusion_status_email()(
        BAD_LEDGER, 0, state, NOW, _boom, lambda s: calls.append(["save"]))
    assert len(calls) == 1
    assert res["sent"] is False and "notify 超时" in res["error"]
    assert not any(k.startswith("conclusion_status|") for k in state)


# ── 判别力辅助(源码形状守卫): 关键接线不许被后人悄悄拆掉 ──────────────────
def test_severe_alert_paths_all_increment_alert_mail_counter():
    src = m309.MONITOR.read_text(encoding="utf-8")
    # 三个 severe 发送点(升级提醒/停摆直发/收尾聚合)都必须计数, 否则场景 A 会误发冗余邮件
    assert src.count('_ALERT_MAIL_COUNTER["sent"] += 1') >= 3
    # 判定必须用「真发出数」而不是 len(alerts)(后者含被去重/吸收的行)
    assert '_concl, _ALERT_MAIL_COUNTER["sent"], alert_state, NOW,' in src


def test_production_helper_never_spawns_notify_itself():
    """§18 L48 static-only 证明: 生产 helper 只调注入的 notify_runner, 自己不起子进程。

    测试里 runner 是 stub(断言过被调用), 因此「stub 生效 ⇒ 零真实外发」结构性成立。
    """
    src = m309.heredoc_source()
    i = src.find("def _maybe_send_conclusion_status_email")
    assert i > 0
    j = src.find("\ndef ", i + 10)
    seg = src[i:j if j > 0 else len(src)]
    assert "notify_runner(cmd)" in seg
    assert "subprocess" not in seg, "生产 helper 不许自己起子进程(否则单测会真外发)"


def test_recovery_loop_skips_conclusion_status_key():
    src = m309.MONITOR.read_text(encoding="utf-8")
    i = src.find("for _key, _info in list(alert_state.items()):")
    assert i > 0
    seg = src[i:i + 4000]
    assert "CONCLUSION_STATUS_KEY_PREFIX" in seg, (
        "恢复检测循环必须跳过 conclusion_status| 键, 否则会被误判「异常已消失」发假恢复邮件")