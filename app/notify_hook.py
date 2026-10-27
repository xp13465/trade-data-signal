"""app 侧统一告警出口(subprocess 调 scripts/notify.py)——单一实现(§23.2③ 根因修复)。

为什么单独一个模块
  `app/collector/runner.py::_notify`(2026-08-14 reviewer P3-②)与新增的历史行改写审计
  (`app/history_audit.py`, 2026-10-14)都要「subprocess 调 scripts/notify.py 发告警 + dedup
  + 失败留痕」。同一事实(notify.py 的调用协议:参数位序/--severe/--from-prefix/--dedup-*)
  存在多份副本时必然静默漂移(memory `repro-script-second-implementation-drift`),故收敛为
  本模块单一实现;runner._notify 改为委托本模块(行为逐字不变,含 timeout=60/check=False)。

契约
  · subprocess 调 scripts/notify.py,**不抛异常**(通知失败不阻塞主流程)。
  · 失败(rc!=0 / 异常 / 超时)经 fail_hook(subject, detail) 留痕;未传 fail_hook 时打印 stderr。
  · 成功/失败均返回 rc(int|None),供调用方与测试断言。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable

# app/notify_hook.py -> app/ -> 仓库根 -> scripts/notify.py
NOTIFY_PY = Path(__file__).absolute().parent.parent / "scripts" / "notify.py"


def send_alert(subject: str, body: str, *,
               dedup_key: str,
               dedup_window: int = 86400,
               severe: bool = True,
               from_prefix: str = "[告警]",
               timeout: int = 60,
               defer_digest: bool = False,
               digest_category: str | None = None,
               fail_hook: Callable[[str, str], None] | None = None) -> int | None:
    """发一条告警(邮件+TG+飞书)。返回 notify.py 返回码;失败返回 None。

    defer_digest(2026-10-28 ★4 加): True = 不即时外发, 并入当日 23:25 摘要 buffer
      (`notify.py --defer-digest`, 摘要由 schedule_monitor 每轮尾部 `--flush-digest` 批发)。
      用于「常态事件只进摘要、不单独发信」的提示级告警(如历史行改写 notice)。
      注意: defer 模式下 notify.py 在去重逻辑之前直接返回, **--dedup-key 不生效**(摘要 buffer
      自身按「同日同 key(无 key 时用 subject 哈希)」幂等); 参数仍原样传过去只为日志可读 +
      将来若回退 defer 时去重语义在场, 不要据此认为 defer 条目也吃 dedup 窗。
    fail_hook 语义与 `runner._notify_fail_trace` 一致:告警通道自身故障时留痕,不向上抛。
    """
    cmd = [sys.executable, str(NOTIFY_PY), subject, body,
           "--from-prefix", from_prefix,
           "--dedup-key", dedup_key, "--dedup-window", str(dedup_window)]
    if severe:
        cmd.append("--severe")
    if defer_digest:
        cmd.append("--defer-digest")
        if digest_category:
            cmd += ["--digest-category", digest_category]
    try:
        r = subprocess.run(cmd, timeout=timeout, check=False,
                           capture_output=True, text=True)
    except Exception as e:  # noqa: BLE001  通知失败不阻塞主流程, 但必须留痕
        _fail(fail_hook, subject, f"subprocess 异常 {type(e).__name__}: {e}")
        return None
    if r.returncode != 0:
        tail = (((r.stderr or "") + " " + (r.stdout or "")).strip())[-300:]
        _fail(fail_hook, subject, f"rc={r.returncode} {tail}")
    return r.returncode


def _fail(fail_hook: Callable[[str, str], None] | None, subject: str, detail: str) -> None:
    if fail_hook is not None:
        try:
            fail_hook(subject, detail)
            return
        except Exception:  # noqa: BLE001  留痕本身再失败也不能放大
            pass
    print(f"[alert-notify] 告警发送失败 subject={subject!r} {detail}",
          file=sys.stderr, flush=True)