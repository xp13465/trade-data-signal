#!/usr/bin/env python3
"""util_atomic.py - 原子写公共模块(2026-09-21 同类错误面根治抽取)。

解决 signal_kelly_backtest.py / kelly_posrating.py / signal_kelly_backtest_bond.py /
signal_kelly_snapshot.py 四处重复的原子写实现(裸 write_text / mkstemp / 私有 _atomic_write
三份不同形态, 且 mkstemp 版缺 fchmod 0644 权限修正)。

核心(与 signal_kelly_backtest.py 原 _atomic_write 同款语义):
    - 同目录唯一 .tmp(pid+随机) + write → flush → fsync → os.replace:
      读侧要么旧完整要么新完整, 绝不半截(§22 数据一致性); os.replace 同分区原子替换;
      fsync 落盘防断电后 replace 指到空/截断 inode。
    - os.fchmod(fd, 0o644): 新建文件默认 0600(mkstemp)/umask(open), replace 后最终文件
      权限偏紧会与现状产物(0644)不一致、其他进程/静态服务可能读不了; 统一修正 0644。
    - finally 清理残留 tmp。

约束:
    tmp 名格式固定 {path}.{pid}.{rand}.tmp —— signal_kelly_backtest.py _cleanup_stale_tmp
    解析此格式识别「仍在被写的 tmp」防并发误删(pid 段存活则跳过不删), 改格式必须同步该函数。
"""
import json
import os
import random as _random


def _tmp_path(path) -> str:
    """同目录唯一临时文件路径: {path}.{pid}.{随机}.tmp。"""
    return f"{path}.{os.getpid()}.{_random.randint(100000, 999999)}.tmp"


def atomic_write_text(path, payload: str) -> None:
    """字符串原子写(payload 为 str)。path 接受 str 或 Path。"""
    tmp = _tmp_path(path)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            os.fchmod(f.fileno(), 0o644)
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def atomic_write_json(path, obj, ensure_ascii=False, indent=None, separators=None) -> None:
    """JSON 原子写。kwargs 透传 json.dump(默认行为与 json.dumps(obj, ensure_ascii=False) 一致,
    即 indent=None 时保持默认 separators=', ' 与 ': ', 输出逐字节与裸 dumps 相同)。"""
    tmp = _tmp_path(path)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            os.fchmod(f.fileno(), 0o644)
            json.dump(obj, f, ensure_ascii=ensure_ascii, indent=indent, separators=separators)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
