#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R2 全局上传锁「只读」探测与超时诊断文案(C 方案, 2026-10-23)。

背景: 2026-10-22 22:38 云上 `trade-nextday-plan` 因内层 480s 超时 exit 1, 但
`nextday_plan_generator.py` 用 `capture_output=True` 调 `upload_r2.py`, 把子进程 stderr
(每 30s 一行「⏳ 等待 R2 上传锁 Ns」心跳)全吞掉 ⇒ 日志里看不见「在等锁」, 只能反推。
根因报告 docs/ops/r2-lock-contention-20261023.md; 方案 docs/ops/r2-lock-plan-20261023.md §4。

本模块只做两件事, 都是**只读/纯函数**, 零业务副作用:
  1) `probe_lock_holder(lock_path)` —— lsof 找出「打开了锁文件」的进程(候选集), ps 补运行时长与命令行;
  2) `build_lock_timeout_diag(...)` —— 把 `subprocess.TimeoutExpired` 变成
     (日志文本, 告警标题, 告警正文), 正文说人话:「上传前排队等锁超时(等了 N 秒, 被 X 占着)」。

⚠ 语义边界(诚实标注): `lsof` 只能看到「打开了这个锁文件」的进程, 而 `upload_r2.py` 的**排队者**
也会 `os.open` 锁文件后再 flock 阻塞 ⇒ 结果是「候选集」而非精确持锁者。本模块按已运行时长
从长到短排序(先启动的通常就是持锁者), 输出里逐条带 etime, 不做过度断言。

§18 L50 / §25 对齐: 纯只读(lsof + ps), 不 exec 任何业务脚本、不写文件、不碰网络;
任何异常(含 lsof 不存在的精简镜像)一律返回空串, **绝不让诊断反过来把链路弄挂**。
"""
import re
import subprocess

# ps etime 形如 `MM:SS` / `HH:MM:SS` / `DD-HH:MM:SS`; 行首是 pid。
_PS_ROW_RE = re.compile(r"^\s*(\d+)\s+([\d:-]+)\s+(.*)$")


def _etime_secs(etime: str) -> int:
    """ps etime → 秒(仅用于排序);解析不了返回 -1。"""
    days = 0
    rest = etime
    if "-" in rest:
        d, rest = rest.split("-", 1)
        if not d.isdigit():
            return -1
        days = int(d)
    try:
        nums = [int(x) for x in rest.split(":")]
    except ValueError:
        return -1
    secs = 0
    for n in nums:
        secs = secs * 60 + n
    return days * 86400 + secs


def probe_lock_holder(lock_path, max_items: int = 3, row_limit: int = 160) -> str:
    """返回人类可读的持锁进程候选摘要(单行);探测不到返回 ""。永不抛异常。"""
    try:
        lsof = subprocess.run(["lsof", "-t", str(lock_path)],
                              capture_output=True, text=True, timeout=5)
        pids = [x for x in (lsof.stdout or "").split() if x.isdigit()]
    except Exception:  # noqa: BLE001  (lsof 缺失/超时/权限不足都不阻断)
        return ""
    if not pids:
        return ""
    try:
        ps = subprocess.run(
            ["ps", "-ww", "-p", ",".join(pids), "-o", "pid=,etime=,args="],
            capture_output=True, text=True, timeout=5)
        rows = [ln.strip() for ln in (ps.stdout or "").splitlines() if ln.strip()]
    except Exception:  # noqa: BLE001
        rows = []
    if not rows:
        return ""
    rows.sort(key=lambda r: _etime_secs((_PS_ROW_RE.match(r).group(2)
                                         if _PS_ROW_RE.match(r) else "")), reverse=True)
    out = []
    for r in rows[:max_items]:
        m = _PS_ROW_RE.match(r)
        if m:
            out.append(f"pid={m.group(1)}(已运行 {m.group(2)}) {m.group(3)[:row_limit]}")
        else:
            out.append(r[:row_limit])
    return "; ".join(out)


def subprocess_output_tail(exc, limit: int = 2000) -> str:
    """取 TimeoutExpired 上挂的超时前输出尾段。

    `subprocess.run(capture_output=True)` 超时时把已读到的 stdout/stderr **原始字节**
    挂在异常对象上(text=True 也不解码) ⇒ 这里统一 bytes→str;超时前的等锁心跳都在里面。
    """
    chunks = []
    for name in ("stderr", "stdout"):
        raw = getattr(exc, name, None)
        if not raw:
            continue
        if isinstance(raw, (bytes, bytearray)):
            raw = bytes(raw).decode("utf-8", errors="replace")
        chunks.append(str(raw))
    return "\n".join(chunks).strip()[-limit:]


def parse_lock_wait_secs(text: str):
    """从心跳行里取最后一次「等待 R2 上传锁 Ns」的 N;没有心跳返回 None。"""
    found = re.findall(r"等待 R2 上传锁 (\d+)s", text or "")
    return max((int(x) for x in found), default=None)


def build_lock_timeout_diag(exc, *, lock_path, log_path, date_tag,
                            subject_prefix="[告警]", source="", file_names=None,
                            limit: int = 2000, probe=None) -> tuple:
    """超时诊断三件套:(日志文本, 告警标题, 告警正文)。纯函数(除只读 lsof), 不触发任何通知。

    「等锁秒数」优先取子进程心跳里的最大值;没有心跳(例如子进程还没轮到打第一行)则回落到
    本次超时上限 —— 后者是「最多等了这么久」的保守说法, 不谎称精确值。
    """
    lock_path = str(lock_path)
    timeout_s = int(getattr(exc, "timeout", 0) or 0)
    tail = subprocess_output_tail(exc, limit=limit)
    waited_s = parse_lock_wait_secs(tail)
    waited_exact = waited_s is not None
    if waited_s is None:
        waited_s = timeout_s
    holder = (probe or probe_lock_holder)(lock_path) or (
        "未知(只读探测不到持锁进程, 可人工 `lsof " + lock_path + "` 排查)")
    files_txt = ""
    if file_names:
        files_txt = f"本次要传的是 {len(file_names)} 个小文件({', '.join(map(str, file_names))}); "
    waited_txt = f"等了 {waited_s} 秒" if waited_exact else f"等了约 {waited_s} 秒"
    src_txt = f"{source}: " if source else ""

    log_text = (
        f"⚠ {src_txt}上传前排队等锁超时({waited_txt} / 上限 {timeout_s}s), "
        f"占锁进程候选={holder}, 锁文件={lock_path}\n"
        f"子进程输出尾段(等锁心跳):\n{tail or '(空)'}"
    )
    subject = f"{subject_prefix} 上传前排队等锁超时 {date_tag}"
    body = (
        f"{src_txt}上传前排队等锁超时({waited_txt}, 被 {holder} 占着)。"
        f"{files_txt}"
        f"本地已落盘但 R2 未同步(线上备站可能滞后)。"
        f"<br>锁文件: {lock_path}"
        f"<br>子进程输出尾段(等锁心跳): <pre>{tail or '(空)'}</pre>"
        f"<br>日志: {log_path}"
    )
    return log_text, subject, body