#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""notify_sent.py - 「notify.py 子进程是否真发出过」的**唯一判据**(2026-10-09, #240 F1 + #241)。

背景(同一病根, 已两处命中)
  `scripts/notify.py` 的 `main()` **所有出口都 `return 0`** —— 包括
  「全部渠道未发出」(notify.py:2362 通用路径)与 tier 分支 `defer_status='append_failed'`
  (notify.py:2189 分级路径)。因此**子进程 `returncode == 0` 完全不含「告警送达/入队」的
  告知力**: 渠道全挂也 rc=0。
  历史事故面:
    · #240 F1 → `check_failed_units.py` 用 `rc==0` 当落签判据 ⇒ 全渠道失败照样落签名 ⇒
      当日同集合告警被全部抑制 = **当天失报**。
    · #241 同根 → `check_s06_freshness.py:135` `sent_ok = rc==0` ⇒ 通知全失败仍当成功 ⇒
      落签 ⇒ 下次不重试 ⇒ **S06 快照过期告警静默丢失**。
  修法(两处共用本模块, 杜绝第二份实现漂移 —— memory repro-script-second-implementation-drift):
  **不看 rc, 改解析 notify.py 子进程输出文本里的真实路由结果**。

判据覆盖 notify.py 的两类出口形态(逐字对齐源码)
  ① 通用 / `--severe` 路径:
       · 成功   → `[notify] 汇总：已发出 email/feishu`(notify.py:2359)
       · 全失败 → `[notify] 汇总：全部渠道未发出（...）`(notify.py:2362)
       · #196③ 连续异常升 critical 走 `send_tiered(critical)` 后 **early return**, 不发①的
         通用汇总行, 只发 → `[notify][196] 升级档路由完成：{'email': True, ...}`(notify.py:2335)
  ② 分级 `--tier` 路径(notify.py:2189-2198, 恒 return 0):
       · `[notify][tier=<t>] 路由完成：{res}`。res 语义随 tier 变(`_tier_send_ok`, notify.py:2101):
           - tier=warning → `defer_warning` 三态, 真处理 ⇔ `deferred=True`
             (`defer_status ∈ {enqueued, suppressed}`); `append_failed` ⇒ `deferred=False`
             = **未入聚合 buffer** = 不得当发出(否则漏告警)。
           - tier=critical → `send()`, 真发出 ⇔ 任一渠道 True。
           - tier=info → `log_info` 已落 dashboard(`info_logged=True`)。
       (check_s06_freshness #241 走的正是 `--tier warning` 分支。)

判据 = 「出现的 `已发出`」或「`路由完成：` 之后的 res dict 里出现 `True`」;
      命中 `全部渠道未发出` 一律 False。
  为何这两式够用(逐形态核对):
      ① 通用汇总行: 只会有 `已发出` / `全部渠道未发出` 两态, 无 dict ⇒ 精确。
      ② `路由完成：` 后的 res dict 只含固定键(tier + 渠道三个 bool + deferred/info_logged),
         不含任何用户文本 ⇒ 字典串里出现 `True` 即「有某渠道真发出 / 真入队或真抑制」;
         全失败(res 全 False) ⇒ 无 `True` ⇒ False。
  **fail-safe 语义(核心)**: 判不出「真发出过」时**保守返回 False** ⇒ 调用方不落去重状态
  ⇒ 下轮重试(宁可重复一次, 也绝不吞真故障)。

边界(诚实标注)
  · 只解析**输出文本**; 调用方须把 notify 子进程 stdout **与** stderr 合并后传入
    (notify.py 两路都打 stderr, 但合并更稳)。
  · 不覆盖「dry-run」: dry-run 输出(如 `[notify][warning][dry-run] 模拟入聚合 buffer`)
    不含 `路由完成：`/`已发出` ⇒ 判 False(不落签), 与「dry-run 不占窗」契约一致。

关联: `check_failed_units._notify_sent`(#240 F1) / `check_s06_freshness`(#241)均委托本函数;
      规范 §23.2③(根因修复不只表面症状: 判据只此一份)。notify.py 为冻结面(§23.7), 本判据
      只读其**输出**, 不改其一行。
"""
from __future__ import annotations


def notify_sent(output: str) -> bool:
    """从 notify.py 子进程输出文本判定「是否真的发出/入队过」(rc 不参与, 见模块 docstring)。

    真发出/入队 → True; 全渠道失败 / buffer 追加失败 / 无法判定 → False(fail-safe)。
    """
    if not output:
        return False
    # ① 通用路径: 全失败优先级最高("全部渠道未发出" 不含 "已发出", 但显式前置更清晰)
    if "全部渠道未发出" in output:
        return False
    # ② 通用路径成功(含 "--severe", 以及 #196③ 升级档前置的一般汇总)
    if "已发出" in output:
        return True
    # ③ 分级/升级档路径: "...路由完成：{<res dict>}"(#196③ notify.py:2334 / --tier notify.py:2190)
    _i = output.find("路由完成：")
    if _i >= 0:
        _j = output.find("}", _i)
        _seg = output[_i:_j + 1] if _j >= 0 else output[_i:]
        return "True" in _seg
    # ④ 未知形态 → 保守 False(下轮重试)
    return False


# ══════════════════════════════════════════════════════════════════════════════
# 三态判据 notify_state()（#241 Pattern B / W2, 2026-10-10）—— 纯新增, 既有 notify_sent
# 一字不改（存量 9 个调用方零回归: 7 个 .py 直调 + 2 个 .sh 内嵌 python）。消费者: check_monitor_heartbeat / nextday_gap_check /
# nextday_plan_generator 三个巡检站点（它们此前用 rc 判 notify 是否真发出, 而 CLI 13 个分支
# 恒 return 0 ⇒ rc 无判别力; 需区分「真发出」与「被 dedup 抑制」两种成功态）。
# ══════════════════════════════════════════════════════════════════════════════
# 抑制行签名表: (行首前缀, 行内必需标记 | None)。**必须行首锚定 + 行内标记同时满足**,
# **严禁裸 "suppress" 子串分类** —— tier 分支的成功行
# `[notify][tier=<t>] 路由完成：{... 'defer_status': 'suppressed'}` 也含 "suppressed" 子串,
# 但那必须判 sent（反向用例, 见 notify_state docstring）。签名字面量对齐 notify.py 既有 5 类
# 抑制行打印（这些行措辞被冻结: 唯一文本消费者 retry_failed_metrics.py:130 按
# "dedup 窗口内 suppress" 匹配 notify.py:2183 那行, 禁改）。
_SUPPRESS_SIGNATURES: tuple[tuple[str, str | None], ...] = (
    # 通用 / tier 的 check_dedup 抑制（notify.py:1272-1273）
    ("[notify][dedup] suppress key=", None),
    # defer_warning 4h 指纹层「同源抑制」（notify.py:1779-1780）
    ("[notify][dedup] 同源抑制(", None),
    # tier 分支窗口内抑制（notify.py:2183-2184, tier 名变 ⇒ 前缀 + 固定标记）
    ("[notify][tier=", "dedup 窗口内 suppress"),
    # R4 / R7 / #196 升级档窗口内已发抑制（notify.py:2232 / 2274 / 2325）
    ("[notify][r4] staticdata_backup_fail 21600s 窗口内已发, suppress", None),
    ("[notify][r7] 升级档窗口内已发, suppress", None),
    ("[notify][196] 升级档窗口内已发, suppress", None),
    # agent-done 5min 抑制（notify.py:1348）
    ("[notify][agent-done] suppress", None),
    # #245 批2 L2 预算+摘要层（2026-10-10）：超日预算的 SEVERE 被并入当日摘要 buffer
    # （「成功且已知」——消息未即时外发但已登记待 23:25 摘要出线，**不是**未发出，勿判 failed
    #  触发调用方重试/包装层重复告警。原始行 notify.py:[notify][budget] 并入当日摘要 ...）。
    ("[notify][budget] 并入当日摘要", None),
    # --defer-digest 直接并入 buffer 的成功行（monitor 行级吸收/恢复补列；同构登记防后续调试）。
    ("[notify][digest] 已并入摘要 buffer", None),
)


def _is_suppress_line(line: str) -> bool:
    """单行是否为既有抑制行（行首锚定 + 行内标记同时满足）。"""
    s = line.lstrip()
    for prefix, marker in _SUPPRESS_SIGNATURES:
        if s.startswith(prefix) and (marker is None or marker in line):
            return True
    return False


def notify_state(output: str) -> str:
    """三态判定: 返回 "sent" / "suppressed" / "failed"（notify.py 子进程输出, 不看 rc）。

    语义:
      · "sent"       = notify_sent(output) 为真（真发出/真入队, 与既有判据逐字同源）;
      · "suppressed" = 命中 notify.py 既有抑制行（**行首锚定**的 5 类, 见 _SUPPRESS_SIGNATURES）
                       ⇒ 已由 dedup 窗口抑制 = **成功且已知**（不重试、不报错）;
      · "failed"     = 其余（全渠道失败 / 未知形态 / 空输出）—— **保守**, 沿用 #241
                       「不吞真故障」精神（调用方据此重试/告警）。

    判定顺序 sent → suppressed → failed（反向用例是这条顺序的硬约束）:
      tier=warning 的 `[notify][tier=warning] 路由完成：{... 'defer_status': 'suppressed'}`
      行同时含 `路由完成：` + `True` ⇒ notify_sent 为真 ⇒ 先判 **sent**（**不得**因为该行里
      有 "suppressed" 子串就误判 suppressed）;
      而真抑制路径（check_dedup）只打抑制行、不打任何 `已发出`/`路由完成：` ⇒ notify_sent 为假
      ⇒ 落到 suppressed 判定。

    并入 stdout/stderr 后传入更稳（notify.py 两路都打 stderr）。
    """
    if not output:
        return "failed"
    if notify_sent(output):
        return "sent"
    for line in output.splitlines():
        if _is_suppress_line(line):
            return "suppressed"
    return "failed"
