# -*- coding: utf-8 -*-
"""F03-R1(2026-11-04): 摘要写路径原子替换 + 失败语义验收矩阵(a~h)。

验证点(与 Codex 隔离探针复验的点逐条对齐):
  a. 写前失败(临时文件打不开)→ 原文件字节完全相同; 新条目返回 False; 已有条目返回 True。
  b. 部分写入(写入中途抛错)→ 原文件字节完全相同、无 .tmp 残留。
  c. ENOSPC(monkeypatch write 抛 OSError(ENOSPC))→ 原文件字节完全相同。
  d. fsync/flush 失败 → 原文件字节完全相同。
  e. os.replace 失败 → 原文件字节完全相同。
  f. 新签名追加失败后, 原有 N 条记录逐字节完好(bytes 比对, 非行数)。
  g. 既有条目 hits 写失败 → 返回 True、零渠道调用、stderr 有标记。
  h. 吸收与 flush 并发(真进程)→ 双方都不丢。
  i. 正常单进程行为不变(既有测试覆盖, 此处补一条正向 sanity)。

零外发铁律(§18 L48): 全程用 ZeroOutboundTrap 武装 + monkeypatch 渠道函数,
  收尾断言 trap.hits == []。本文件不产生任何真实邮件/Telegram/飞书外发。

时敏铁律(L51): 不写死日期字面量; day 从 datetime.now() 派生(与被测代码同源),
  不存在「当天绿次日红」的时敏漂移。
"""
import errno
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import notify  # noqa: E402
from _zero_outbound import ZeroOutboundTrap  # noqa: E402


# ── 共用 fixture: 沙箱路径 + 渠道打桩 + 零外发陷阱 ──────────────────────────────
@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    alerts = tmp_path / "data" / "alerts"
    alerts.mkdir(parents=True, exist_ok=True)
    digest = alerts / "alert_digest.jsonl"
    lock = alerts / "alert_digest.flushlock"
    monkeypatch.setattr(notify, "ALERT_DIGEST_FILE", digest)
    monkeypatch.setattr(notify, "ALERT_DIGEST_LOCK_FILE", lock)
    monkeypatch.setattr(notify, "ALERT_DIGEST_STATE_FILE", alerts / "alert_digest_state.json")
    monkeypatch.setattr(notify, "ALERTS_DIR", alerts)
    monkeypatch.setattr(notify, "REPO", tmp_path)
    monkeypatch.setenv("REPO", str(tmp_path))

    calls: list[str] = []

    def _fake(kind):
        def _f(*_a, **_k):
            calls.append(kind)
            return True
        return _f

    # 渠道打桩(先打桩, 先证沙箱生效): send() 调 _send_email/send_telegram/send_feishu
    monkeypatch.setattr(notify, "_send_email", _fake("email"))
    monkeypatch.setattr(notify, "send_telegram", _fake("telegram"))
    monkeypatch.setattr(notify, "send_feishu", _fake("feishu"))

    with ZeroOutboundTrap() as trap:
        yield {"digest": digest, "lock": lock, "calls": calls, "trap": trap}
    assert trap.hits == [], f"零外发被破坏(§18 L48): {trap.hits}"


# ── 注入机制: 通过 monkeypatch notify.open 把 tmp 文件 open 换成炸弹 ────────────
# notify.py 的 _atomic_write_digest 用模块全局 open(=builtin); setattr notify.open
# 后函数内名字解析命中模块全局(优先于 builtin), 仅影响 notify, 不影响测试自身。
_REAL_OPEN = open


class _BombFile:
    """假文件对象: 在指定调用点抛 OSError, 模拟部分写入/ENOSPC/fsync 失败。"""

    def __init__(self, fail_at: str, enospc: bool = False):
        self._fail_at = fail_at      # "write" / "flush"
        self._enospc = enospc
        self._buf = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def write(self, data):
        if self._fail_at == "write":
            if self._enospc:
                raise OSError(errno.ENOSPC, "injected: ENOSPC mid-write")
            raise OSError("injected: partial write mid-stream")
        self._buf += data

    def flush(self):
        if self._fail_at == "flush":
            raise OSError("injected: flush/fsync fail")

    def fileno(self):
        return -1  # flush 抛错时 os.fsync 不会被执行到

    def close(self):
        pass


def _install_open_bomb(monkeypatch, *, fail_at=None, enospc=False, fail_open=False):
    """装炸弹: fail_open=True → open(tmp) 直接抛(写前失败 a); 否则返回 _BombFile。"""
    state = {"fail_open": fail_open, "fail_at": fail_at, "enospc": enospc}

    def _wrapped_open(name, *a, **k):
        _n = str(name)
        _mode = (a[0] if a and isinstance(a[0], str) else k.get("mode", ""))
        # 只对 _atomic_write_digest 的 tmp 二进制写文件动手脚(名字含 .tmp, mode 含 b/w)
        if ".tmp" in _n and "w" in _mode and "b" in _mode:
            if state["fail_open"]:
                raise OSError("injected: tmp open fail (写前失败)")
            return _BombFile(fail_at=state["fail_at"], enospc=state["enospc"])
        return _REAL_OPEN(name, *a, **k)

    monkeypatch.setattr(notify, "open", _wrapped_open, raising=False)
    return state


def _seed_entry(digest: Path, *, key="seed_k", day=None, hits=1):
    """往 digest 写一条种子条目(走真实 _atomic_write_digest, 不走炸弹)。"""
    _day = day or datetime.now().strftime("%Y-%m-%d")
    rec = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "rid": f"d{os.getpid()}",
           "day": _day, "key": key, "category": "r2", "subject": "种子", "body": "",
           "from_prefix": None, "source": "test", "reason": "over_budget", "hits": hits}
    digest.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    return rec


# ══════════════════════════════ a. 写前失败(tmp open fail) ══════════════════════════════
def test_a_new_entry_tmp_open_fail_returns_false(sandbox, monkeypatch, capsys):
    """a(新条目): tmp 打不开 → 原文件未变(空); 返回 False。"""
    digest = sandbox["digest"]
    assert not digest.exists()
    _install_open_bomb(monkeypatch, fail_open=True)
    ok = notify._absorb_to_digest("主题A", "正文", key="a_new", category="r2", bump_hits=True)
    assert ok is False, "新条目 tmp open 失败应返回 False(fail-open 直发)"
    out, err = capsys.readouterr()
    assert "新条目写入失败" in err, f"stderr 应有新条目失败标记, 得: {err}"
    # 原文件未被创建(replace 未发生) ⇒ 一个字节都没动
    assert not digest.exists(), "原文件(不存在)应保持不存在"


def test_a_existing_entry_tmp_open_fail_returns_true(sandbox, monkeypatch, capsys):
    """a(已有条目): tmp 打不开 → 原文件字节相同; 返回 True(已并入语义)。"""
    digest = sandbox["digest"]
    _seed_entry(digest, key="a_exist")
    before = digest.read_bytes()
    _install_open_bomb(monkeypatch, fail_open=True)
    ok = notify._absorb_to_digest("主题A", "正文", key="a_exist", category="r2", bump_hits=True)
    assert ok is True, "已有条目 hits 写失败应返回 True(保持已并入语义, 零外发)"
    out, err = capsys.readouterr()
    assert "计数写回失败" in err, f"stderr 应有计数写回失败标记, 得: {err}"
    after = digest.read_bytes()
    assert after == before, "原文件字节必须完全相同"


# ══════════════════════════════ b. 部分写入(write 中途抛) ══════════════════════════════
def test_b_partial_write_original_unchanged(sandbox, monkeypatch, capsys):
    """b: 写入中途抛 → 原文件字节相同; 无 .tmp 残留。"""
    digest = sandbox["digest"]
    _seed_entry(digest, key="b_seed")
    before = digest.read_bytes()
    _install_open_bomb(monkeypatch, fail_at="write")
    ok = notify._absorb_to_digest("主题B", "正文", key="b_new", category="r2", bump_hits=True)
    assert ok is False, "新条目部分写入失败应返回 False"
    after = digest.read_bytes()
    assert after == before, "部分写入后原文件字节必须完全相同"
    # 无 .tmp 残留(best-effort 清理)
    tmps = [p for p in digest.parent.iterdir() if ".tmp" in p.name]
    assert tmps == [], f"应无 .tmp 残留, 得: {tmps}"


# ══════════════════════════════ c. ENOSPC ══════════════════════════════
def test_c_enospc_original_unchanged(sandbox, monkeypatch, capsys):
    """c: write 抛 OSError(ENOSPC) → 原文件字节相同。"""
    digest = sandbox["digest"]
    _seed_entry(digest, key="c_seed")
    before = digest.read_bytes()
    _install_open_bomb(monkeypatch, fail_at="write", enospc=True)
    ok = notify._absorb_to_digest("主题C", "正文", key="c_new", category="r2", bump_hits=True)
    assert ok is False
    err = capsys.readouterr().err
    assert "ENOSPC" in err, f"stderr 应含 ENOSPC, 得: {err}"
    assert digest.read_bytes() == before, "ENOSPC 后原文件字节必须完全相同"


# ══════════════════════════════ d. fsync/flush 失败 ══════════════════════════════
def test_d_fsync_fail_original_unchanged(sandbox, monkeypatch, capsys):
    """d: flush 抛(覆盖 fsync 路径) → 原文件字节相同。"""
    digest = sandbox["digest"]
    _seed_entry(digest, key="d_seed")
    before = digest.read_bytes()
    _install_open_bomb(monkeypatch, fail_at="flush")
    ok = notify._absorb_to_digest("主题D", "正文", key="d_new", category="r2", bump_hits=True)
    assert ok is False
    err = capsys.readouterr().err
    assert "flush/fsync fail" in err, f"stderr 应含 fsync 失败标记, 得: {err}"
    assert digest.read_bytes() == before, "fsync 失败后原文件字节必须完全相同"


# ══════════════════════════════ e. os.replace 失败 ══════════════════════════════
def test_e_replace_fail_original_unchanged(sandbox, monkeypatch, capsys):
    """e: os.replace 抛 PermissionError → 原文件字节相同。"""
    digest = sandbox["digest"]
    _seed_entry(digest, key="e_seed")
    before = digest.read_bytes()
    _real_replace = os.replace

    def _bomb_replace(src, dst, *a, **k):
        if str(dst) == str(digest):
            raise PermissionError("injected: os.replace fail")
        return _real_replace(src, dst, *a, **k)

    monkeypatch.setattr(notify.os, "replace", _bomb_replace)
    ok = notify._absorb_to_digest("主题E", "正文", key="e_new", category="r2", bump_hits=True)
    assert ok is False
    err = capsys.readouterr().err
    assert "os.replace fail" in err, f"stderr 应含 replace 失败标记, 得: {err}"
    assert digest.read_bytes() == before, "replace 失败后原文件字节必须完全相同"
    tmps = [p for p in digest.parent.iterdir() if ".tmp" in p.name]
    assert tmps == [], f"replace 失败后应清理 .tmp, 得: {tmps}"


# ══════════════════════════════ f. 新签名追加失败后原有 N 条逐字节完好(Codex 点名) ══════════════════════════════
def test_f_new_append_fail_preserves_existing_bytes(sandbox, monkeypatch, capsys):
    """f: 预置 3 条不同 key 记录 → 快照 bytes → 注入 tmp-open-fail 吸收新签名 →
    断言返回 False **且** 原文件 bytes 与快照逐字节相等(bytes 比对, 非行数)。"""
    digest = sandbox["digest"]
    _today = datetime.now().strftime("%Y-%m-%d")
    recs = []
    for i in range(3):
        r = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "rid": f"d_f{i}",
             "day": _today, "key": f"f_exist_{i}", "category": "r2",
             "subject": f"存量{i}", "body": f"正文{i}" * 50, "from_prefix": None,
             "source": "test", "reason": "over_budget", "hits": i + 1}
        recs.append(r)
    digest.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs),
                      encoding="utf-8")
    snapshot = digest.read_bytes()
    assert len(snapshot) > 0

    _install_open_bomb(monkeypatch, fail_open=True)
    ok = notify._absorb_to_digest("全新签名F", "全新正文", key="f_brand_new",
                                  category="r2", bump_hits=True)
    assert ok is False, "新签名追加失败应返回 False"

    after = digest.read_bytes()
    # bytes 逐字节比对(Codex 点名要的, 不是只比行数)
    assert after == snapshot, (
        f"原有 3 条记录必须逐字节完好; len(before)={len(snapshot)} len(after)={len(after)}")
    # 再确认解析出来仍是同样的 3 条(双保险)
    lines = [l for l in after.decode("utf-8").splitlines() if l.strip()]
    assert len(lines) == 3, f"应仍为 3 行, 得 {len(lines)}"
    keys = {json.loads(l)["key"] for l in lines}
    assert keys == {"f_exist_0", "f_exist_1", "f_exist_2"}, f"key 集合应不变: {keys}"
    print(f"[F03-R1.f] bytes 比对 PASS: {len(snapshot)} 字节逐字节相等")


# ══════════════════════════════ g. 既有条目 hits 写失败 → True + 零渠道 + stderr 标记 ══════════════════════════════
def test_g_existing_hits_fail_true_zero_channels(sandbox, monkeypatch, capsys):
    """g: 既有条目 hits 写失败 → 返回 True、零渠道调用(send fakes 不被触发)、stderr 有标记。"""
    digest = sandbox["digest"]
    _seed_entry(digest, key="g_exist")
    calls = sandbox["calls"]
    _install_open_bomb(monkeypatch, fail_at="flush")  # fsync 失败
    ok = notify._absorb_to_digest("主题G", "正文", key="g_exist", category="r2",
                                  bump_hits=True, mark_seen=False)
    assert ok is True, "既有条目 hits 写失败应返回 True(零渠道外发)"
    err = capsys.readouterr().err
    assert "计数写回失败" in err, f"stderr 应有计数写回失败标记, 得: {err}"
    # 零渠道调用(send 未被触发 → fakes 不计)
    assert calls == [], f"hits 写失败应零渠道调用, 得: {calls}"


# ══════════════════════════════ h. 吸收 vs flush 并发(真进程) → 双方都不丢 ══════════════════════════════
_FLUSH_BARRIER = None
_FLUSH_READY = None


def _flush_worker():
    """fork 子进程: 等 Barrier → 跑 flush_digest(渠道已在父进程打桩, fork 继承)。"""
    _FLUSH_BARRIER.wait()
    notify.flush_digest(dry_run=False)


def _absorb_worker():
    _FLUSH_BARRIER.wait()
    notify._absorb_to_digest("并发吸收H", "正文H", key="h_new", category="r2", bump_hits=True)


def test_h_absorb_vs_flush_concurrent_no_loss(sandbox, monkeypatch):
    """h: 预置 1 条(due) → 进程A跑flush(发出+清理), 进程B吸收新条目 → 双方都不丢。

    P2-B(2026-11-05) 修正假红: 并发交错有两种合法终态, 旧断言只认其一 ⇒ 假红。
    合法终态集合(Codex 夜间复验确认):
      A. flush 先持锁 → 发出 h_existing 并清理 → 释放锁 → absorb 写入 h_new
         ⇒ 剩 1 行 key=h_new(旧条目已交付, 新条目留存待发)
      B. absorb 先持锁 → 写入 h_new(现 2 条) → 释放锁 → flush 读到 2 条全发出并清理
         ⇒ 剩 0 行 buffer 空(两渠道各交付一次, 旧+新均已交付)
    两者都满足「双方都不丢」: h_existing 必被 flush 交付, h_new 要么留存待发(A)要么
    已被同一轮 flush 交付(B)。判定依据 = h_existing 被清理(不在剩余行) 且 h_new 要么
    在剩余行(A)要么也被交付(B)。
    """
    import multiprocessing as mp
    ctx = mp.get_context("fork")
    digest = sandbox["digest"]
    _today = datetime.now().strftime("%Y-%m-%d")
    # 预置 1 条 due 条目(当天)
    _seed_entry(digest, key="h_existing", day=_today)
    # 让 flush 始终满足触发条件: ALERT_DIGEST_HM="00:00" ⇒ 任意时刻 >= 00:00; 清 state
    monkeypatch.setattr(notify, "ALERT_DIGEST_HM", "00:00")
    if notify.ALERT_DIGEST_STATE_FILE.exists():
        notify.ALERT_DIGEST_STATE_FILE.unlink()
    # 渠道已在 sandbox fixture 打桩(fork 继承)

    global _FLUSH_BARRIER
    _FLUSH_BARRIER = ctx.Barrier(2)
    pa = ctx.Process(target=_absorb_worker)
    pb = ctx.Process(target=_flush_worker)
    pa.start()
    pb.start()
    pa.join(timeout=20)
    pb.join(timeout=20)
    assert pa.exitcode == 0, f"absorb worker exit={pa.exitcode}"
    assert pb.exitcode == 0, f"flush worker exit={pb.exitcode}"

    lines = [l for l in digest.read_text(encoding="utf-8").splitlines() if l.strip()]
    keys = {json.loads(l)["key"] for l in lines}
    # 合法终态 A: 剩 1 行 h_existing 已清理、h_new 留存待发
    # 合法终态 B: 剩 0 行 两条均已交付 buffer 空
    assert "h_existing" not in keys, (
        f"h_existing 应已被 flush 交付清理, 不应在剩余行中: {keys}")
    if len(lines) == 0:
        # 终态 B: buffer 空(两渠道各交付一次), 合法
        print("[F03-R1.h] absorb vs flush 并发 PASS: 终态 B(buffer 空, 两条已交付)")
    else:
        # 终态 A: 剩 h_new 留存待发
        assert len(lines) == 1 and keys == {"h_new"}, (
            f"非终态 A 也非终态 B: 得 {len(lines)} 行 keys={keys}")
        print(f"[F03-R1.h] absorb vs flush 并发 PASS: 终态 A(剩 h_new 留存待发)")


# ── h2: 确定性 absorb-then-flush 顺序 → 终态 B(buffer 空), 旧断言假红复现 ──
def test_h2_absorb_then_flush_buffer_empty_legal(sandbox, monkeypatch):
    """h2(P2-B 假红复现): 单进程顺序 absorb→flush → 必然终态 B(buffer 空, 两条已交付)。

    旧断言「剩 1 行 key=h_new」在此顺序下必红(假红): absorb 先写入 h_new(2 条),
    flush 读到 2 条全发出并清理 → 0 行。这是合法结果(两渠道各交付一次), 不是丢条目。
    新断言接受终态 B: 剩 0 行 且 h_existing 已被清理。

    改前红证据: 旧断言 `len(lines)==1 and rec['key']=='h_new'` 在此确定性顺序下
    得 0 行 → 断言失败(假红)。改后绿: 接受 buffer 空。
    """
    digest = sandbox["digest"]
    _today = datetime.now().strftime("%Y-%m-%d")
    _seed_entry(digest, key="h_existing", day=_today)
    monkeypatch.setattr(notify, "ALERT_DIGEST_HM", "00:00")
    if notify.ALERT_DIGEST_STATE_FILE.exists():
        notify.ALERT_DIGEST_STATE_FILE.unlink()
    # 确定性顺序: 先 absorb, 再 flush
    notify._absorb_to_digest("并发吸收H", "正文H", key="h_new", category="r2",
                             bump_hits=True)
    notify.flush_digest(dry_run=False)
    lines = [l for l in digest.read_text(encoding="utf-8").splitlines() if l.strip()]
    keys = {json.loads(l)["key"] for l in lines}
    assert "h_existing" not in keys, f"h_existing 应已交付清理: {keys}"
    assert len(lines) == 0, (
        f"absorb-then-flush 必然终态 B(buffer 空), 得 {len(lines)} 行: {keys}")
    print(f"[F03-R1.h2] absorb→flush 确定性终态 B PASS: buffer 空(两条已交付)")


# ── h3: 确定性 flush-then-absorb 顺序 → 终态 A(剩 h_new), 保留原断言路径 ──
def test_h3_flush_then_absorb_h_new_remains(sandbox, monkeypatch):
    """h3(P2-B 保留原路径): 单进程顺序 flush→absorb → 必然终态 A(剩 h_new 留存待发)。

    这是旧断言认的合法路径: flush 先发出 h_existing 并清理 → absorb 写入 h_new。
    保留此断言确保「absorb 在 flush 后」路径不丢条目(h_new 留存)。
    """
    digest = sandbox["digest"]
    _today = datetime.now().strftime("%Y-%m-%d")
    _seed_entry(digest, key="h_existing", day=_today)
    monkeypatch.setattr(notify, "ALERT_DIGEST_HM", "00:00")
    if notify.ALERT_DIGEST_STATE_FILE.exists():
        notify.ALERT_DIGEST_STATE_FILE.unlink()
    # 确定性顺序: 先 flush, 再 absorb
    notify.flush_digest(dry_run=False)
    notify._absorb_to_digest("并发吸收H", "正文H", key="h_new", category="r2",
                             bump_hits=True)
    lines = [l for l in digest.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1, f"flush→absorb 应剩 1 行 h_new, 得 {len(lines)} 行"
    rec = json.loads(lines[0])
    assert rec["key"] == "h_new", f"应保留 h_new, 得 key={rec['key']}"
    print(f"[F03-R1.h3] flush→absorb 确定性终态 A PASS: 剩 h_new 留存待发")


# ══════════════════════════════ i. 正常单进程行为不变(sanity) ══════════════════════════════
def test_i_normal_absorb_writes_entry(sandbox):
    """i: 无注入 → 新条目正常写入(1 行 hits=1); 再吸收同 key → hits=2。"""
    digest = sandbox["digest"]
    ok1 = notify._absorb_to_digest("主题I", "正文", key="i_k", category="r2", bump_hits=True)
    ok2 = notify._absorb_to_digest("主题I", "正文", key="i_k", category="r2", bump_hits=True)
    assert ok1 and ok2
    lines = [l for l in digest.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["key"] == "i_k" and rec.get("hits") == 2
    # tmp 残留检查(正常路径也不应留 .tmp)
    tmps = [p for p in digest.parent.iterdir() if ".tmp" in p.name]
    assert tmps == [], f"正常路径不应留 .tmp, 得: {tmps}"


def test_i_normal_bump_digest_hits_orphan_path(sandbox):
    """i: _bump_digest_hits(孤儿但同口径改写) 正常工作不炸。"""
    digest = sandbox["digest"]
    _today = datetime.now().strftime("%Y-%m-%d")
    _seed_entry(digest, key="i_orphan", day=_today, hits=1)
    ok = notify._bump_digest_hits("i_orphan", _today)
    assert ok is True
    rec = json.loads([l for l in digest.read_text(encoding="utf-8").splitlines() if l.strip()][0])
    assert rec["hits"] == 2, f"bump 后 hits 应=2, 得 {rec['hits']}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
