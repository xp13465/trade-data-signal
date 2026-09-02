#!/usr/bin/env python3
"""冷却+高峰+全冷却退避逻辑重放自测(与 sensenova-rotate-proxy.py 同目录运行)

用法:同感,cd 到 worktree 根,运行 python3 docs/sensenova/self_check_cooling_logic.py
"""
import sys
import os
import importlib.util

_scripts = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))
_spec = importlib.util.spec_from_file_location(
    "sensenova_rotate_proxy", os.path.join(_scripts, "sensenova-rotate-proxy.py"))
sp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sp)

import time
import unittest.mock as mock


class _T:
    def __init__(self, h):
        self.tm_hour = h


def main():
    # ① 档位单调 + 封顶 48min
    durs = [sp._cool_duration_sec(lv) for lv in (0, 1, 2, 3, 4, 5, 9)]
    assert durs == [180, 360, 720, 1440, 2880, 2880, 2880], durs
    print("① COOL 档位:", durs, "PASS(180/360/720/1440/2880 单调且封顶 48min)")

    # ② 高峰窗口含头不含尾
    sp.PEAK_START_HOUR, sp.PEAK_END_HOUR = 9, 14
    for h, expect in [(8, False), (9, True), (12, True), (13, True), (14, False), (15, False)]:
        with mock.patch.object(mock, 'patch') as _:
            pass
    with mock.patch.object(sp.time, 'localtime', return_value=_T(8)):
        assert sp._is_peak_hour() is False
    with mock.patch.object(sp.time, 'localtime', return_value=_T(10)):
        assert sp._is_peak_hour() is True
    with mock.patch.object(sp.time, 'localtime', return_value=_T(13)):
        assert sp._is_peak_hour() is True
    with mock.patch.object(sp.time, 'localtime', return_value=_T(14)):
        assert sp._is_peak_hour() is False
    with mock.patch.object(sp.time, 'localtime', return_value=_T(15)):
        assert sp._is_peak_hour() is False
    print("② 高峰窗口:9<=h<14 命中判断 PASS")

    # ③ 高峰退避:高峰 1.5,非高峰 0.3
    sp.ROTATE_BACKOFF = 0.3
    with mock.patch.object(sp.time, 'localtime', return_value=_T(10)):
        assert sp._rotate_backoff() == 1.5, sp._rotate_backoff()
    with mock.patch.object(sp.time, 'localtime', return_value=_T(16)):
        assert sp._rotate_backoff() == 0.3, sp._rotate_backoff()
    print("③ 高峰退避 1.5s/非高峰 0.3s PASS")

    # ④ 高峰冷却时长翻倍(直接 patch _is_peak_hour,不碰 time.localtime 以免影响 strftime)
    sp._cool = {}
    with mock.patch.object(sp, '_is_peak_hour', return_value=True):
        sp._mark_cool('testkey', 5, 'Allocated quota')
        entry = sp._cool['testkey']
        dur = entry['until'] - time.time()
        assert abs(dur - 360) < 4, dur
        assert entry['level'] == 0
    with mock.patch.object(sp, '_is_peak_hour', return_value=False):
        sp._mark_cool('testkey2', 5, 'Allocated quota')
        entry2 = sp._cool['testkey2']
        dur2 = entry2['until'] - time.time()
        assert abs(dur2 - 180) < 4, dur2
    print("④ 高峰冷却 ×2(360s)/非高峰 180s PASS")

    # ⑤ 全冷却退避参数 + 累计封顶收敛(不真正 sleep)
    assert sp.ALL_COOL_BACKOFF_L0 == 30 and sp.ALL_COOL_BACKOFF_MAX == 480 and sp.ALL_COOL_BACKOFF_CAP == 480
    _wait = sp.ALL_COOL_BACKOFF_L0
    _waited = 0
    _seq = []
    while True:
        _wait = min(_wait, sp.ALL_COOL_BACKOFF_CAP - _waited)
        _waited += _wait
        _seq.append(_wait)
        if _waited >= sp.ALL_COOL_BACKOFF_CAP:
            break
        _wait = min(_wait * 2, sp.ALL_COOL_BACKOFF_MAX)
    assert _seq == [30, 60, 120, 240, 30], _seq
    assert _waited == 480, _waited
    print("⑤ 全冷却退避序列(30 起步 ×2 封顶 480,cap 剩余累计,累计恰 480):", _seq, "PASS")

    # ⑥ 成功清冷却重置 + 冷却期内再触发 escalation
    sp._cool = {}
    sp._cool['k'] = {'until': time.time() - 1, 'level': 3}
    sp._unmark_cool('k')
    assert 'k' not in sp._cool
    sp._cool['k2'] = {'until': time.time() + 100, 'level': 1}
    with mock.patch.object(sp, '_is_peak_hour', return_value=False):
        sp._mark_cool('k2', 2, 'token plan entitlement')
    assert sp._cool['k2']['level'] == 2
    print("⑥ 成功清冷却重置 + 冷却期内再触发 escalation PASS")

    print("\nALL SELF-TEST PASS")


if __name__ == '__main__':
    main()