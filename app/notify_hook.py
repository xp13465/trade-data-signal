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
  · 返回 `SendResult`(rc / absorbed / route / detail),供调用方与测试判定**真实投递路径**。

摘要通道的 fail-open(2026-10-28 ★4 审查 F1,治「消息黑洞」)
  `defer_digest=True` 表示「常态事件只进当日 23:25 摘要、不单发」。但 notify.py 有三个口
  会让条目**既没直发也没进摘要**: `ALERT_BUDGET_DISABLE=1`(defer 直接返回 noop 不写 buffer)、
  `ALERT_DIGEST_DISABLE=1`(buffer 照写但 flush 全停 ⇒ 永不外发)、吸收失败(rc=1)。
  本模块按 `scripts/check_failed_units.py::_defer_digest` 的既有口径统一处置(**宁多勿吞**):
    · defer 前先探测 `ALERT_DIGEST_DISABLE=1` ⇒ 直接走直发(不写永不 flush 的 buffer);
    · defer 时传 `--result-file`,**只有 status == "digested" 且 rc == 0 才算吸收成功**;
    · noop / failed / rc!=0 / 结果文件缺失 / JSON 坏 / 超时 / 异常 ⇒ **一律 fail-open 退回直发**
      (同一 subject + body,不带 --defer-digest)。
  直发也失败时按既有 `_fail` 留痕(stderr / fail_hook),不静默、也不向上抛。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, NamedTuple

# app/notify_hook.py -> app/ -> 仓库根 -> scripts/notify.py
NOTIFY_PY = Path(__file__).absolute().parent.parent / "scripts" / "notify.py"


class SendResult(NamedTuple):
    """一次告警投递的真实结果(供调用方判定, 不再只靠 rc 猜)。

    rc       : 实际生效那条路径的 notify.py 返回码(失败/异常 None)
    absorbed : defer 通道是否真被摘要吸收; True=已进摘要(未直发) / False=未吸收已 fail-open 直发 /
               None=非 defer(普通直发)
    route    : "direct"(普通直发) / "digest"(已进摘要) / "fail_open_direct"(defer 未吸收, 退回直发)
    detail   : defer 探测细节(status=… rc=…)或失败说明, 便于日志定位
    """
    rc: int | None
    absorbed: bool | None
    route: str
    detail: str = ""


def send_alert(subject: str, body: str, *,
               dedup_key: str,
               dedup_window: int = 86400,
               severe: bool = True,
               from_prefix: str = "[告警]",
               feishu_group: str | None = None,
               timeout: int = 60,
               defer_digest: bool = False,
               digest_category: str | None = None,
               fail_hook: Callable[[str, str], None] | None = None) -> SendResult:
    """发一条告警(邮件+TG+飞书)。返回 SendResult;失败不外抛。

    defer_digest(2026-10-28 ★4 加): True = 优先并入当日 23:25 摘要 buffer
      (`notify.py --defer-digest`, 摘要由 schedule_monitor 每轮尾部 `--flush-digest` 批发)。
      用于「常态事件只进摘要、不单独发信」的提示级告警(如历史行改写 notice)。
      **摘要没吸收成功一律 fail-open 直发**(见模块 docstring), 故调用方无需再判 rc 决定要不要补发。
      注意: defer 模式下 notify.py 在去重逻辑之前直接返回, **--dedup-key 不生效**(摘要 buffer
      自身按「同日同 key(无 key 时用 subject 哈希)」幂等); 参数仍原样传过去只为日志可读 +
      将来若回退 defer 时去重语义在场, 不要据此认为 defer 条目也吃 dedup 窗。
    feishu_group: 透传 `--feishu-group`(如 kelly 的 "alert" 群); None = 用 notify 默认。
    fail_hook 语义与 `runner._notify_fail_trace` 一致:告警通道自身故障时留痕,不向上抛。
    """
    base = [sys.executable, str(NOTIFY_PY), subject, body,
            "--from-prefix", from_prefix,
            "--dedup-key", dedup_key, "--dedup-window", str(dedup_window)]
    if severe:
        base.append("--severe")
    if feishu_group:
        base += ["--feishu-group", feishu_group]

    if not defer_digest:
        return _deliver(base, subject, timeout, fail_hook, route="direct", absorbed=None)

    absorbed, rc, detail = _absorb_into_digest(base, subject, digest_category, timeout)
    if absorbed:
        return SendResult(rc=rc, absorbed=True, route="digest", detail=detail)
    # 摘要没吸收 ⇒ 退回直发(宁多勿吞): 与批次2 check_failed_units._defer_digest 同口径。
    print(f"[alert-notify] 摘要未吸收({detail}) ⇒ fail-open 直发 subject={subject!r}",
          file=sys.stderr, flush=True)
    return _deliver(base, subject, timeout, fail_hook,
                    route="fail_open_direct", absorbed=False, detail=detail)


def _absorb_into_digest(base: list[str], subject: str, digest_category: str | None,
                        timeout: int) -> tuple[bool, int | None, str]:
    """尝试把告警并入当日摘要 buffer。返回 (absorbed, rc, detail)。

    判定口径与 `scripts/check_failed_units.py::_defer_digest`(批次2)一致:
      · `ALERT_DIGEST_DISABLE=1` ⇒ 摘要 flush 全停(buffer 永不外发)⇒ 直接判「未吸收」,
        调用方 fail-open 直发, 绝不写进永不外发的 buffer;
      · 只有 `--result-file` 里 `status == "digested"` 且 rc == 0 才算吸收成功;
      · `ALERT_BUDGET_DISABLE=1` 回滚态下 defer 返回 `noop`(不写 buffer)⇒ 未吸收 ⇒ 直发;
      · rc!=0 / 结果文件缺失 / JSON 坏 / 超时 / 异常 ⇒ 一律未吸收(不猜, 宁多勿吞)。
    """
    if os.environ.get("ALERT_DIGEST_DISABLE") == "1":
        return False, None, "ALERT_DIGEST_DISABLE=1(摘要 flush 全停)"
    fd, result_path = tempfile.mkstemp(prefix="notify_defer_", suffix=".json")
    os.close(fd)
    cmd = list(base) + ["--defer-digest", "--result-file", result_path]
    if digest_category:
        cmd += ["--digest-category", digest_category]
    try:
        try:
            r = subprocess.run(cmd, timeout=timeout, check=False,
                               capture_output=True, text=True)
        except Exception as e:  # noqa: BLE001  通知失败不阻塞主流程, 调用方 fail-open
            return False, None, f"subprocess 异常 {type(e).__name__}: {e}"
        status = None
        try:
            status = json.loads(Path(result_path).read_text(encoding="utf-8")).get("status")
        except Exception:  # noqa: BLE001  结果文件缺失/损坏: 按「未吸收」处理(不猜)
            status = None
        detail = f"status={status} rc={r.returncode}"
        return (status == "digested" and r.returncode == 0), r.returncode, detail
    finally:
        try:
            os.unlink(result_path)
        except OSError:  # 清理失败不外抛(临时文件残留可容忍)
            pass


def _deliver(base: list[str], subject: str, timeout: int,
             fail_hook: Callable[[str, str], None] | None, *,
             route: str, absorbed: bool | None, detail: str = "") -> SendResult:
    """真正发出去(不带 --defer-digest)。失败按既有 `_fail` 留痕, 不上抛。"""
    try:
        r = subprocess.run(base, timeout=timeout, check=False,
                           capture_output=True, text=True)
    except Exception as e:  # noqa: BLE001  通知失败不阻塞主流程, 但必须留痕
        _fail(fail_hook, subject, f"subprocess 异常 {type(e).__name__}: {e}")
        return SendResult(rc=None, absorbed=absorbed, route=route, detail=detail)
    if r.returncode != 0:
        tail = (((r.stderr or "") + " " + (r.stdout or "")).strip())[-300:]
        _fail(fail_hook, subject, f"rc={r.returncode} {tail}")
    return SendResult(rc=r.returncode, absorbed=absorbed, route=route, detail=detail)


def _fail(fail_hook: Callable[[str, str], None] | None, subject: str, detail: str) -> None:
    if fail_hook is not None:
        try:
            fail_hook(subject, detail)
            return
        except Exception:  # noqa: BLE001  留痕本身再失败也不能放大
            pass
    print(f"[alert-notify] 告警发送失败 subject={subject!r} {detail}",
          file=sys.stderr, flush=True)