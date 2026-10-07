# -*- coding: utf-8 -*-
"""#213 共享工具: 零外发陷阱(§18 L48「通知类脚本自测必须先打桩 + 先证打桩生效」)。

用途
  给 `scripts/tests/` 下 #213 批1/批2 的薄包装用: 在跑被包装的历史自测脚本时, 包裹
  **真实网络/邮件出口**(`urllib.request.urlopen` / `smtplib.SMTP` / `smtplib.SMTP_SSL`),
  一旦有代码路径越过用例自身的 mock 触达真实出口, 立即**计数并抛 AssertionError**(响亮失败,
  不静默)。收尾断言 `hits == []` 即「本次自测全程零真实外发」。

为什么选这三个出口(而非 notify.send)
  notify 家族的真正外发原语只有三处(notify.py 实查):
    · send_telegram            → urllib.request.urlopen (notify.py:446)
    · _feishu_http_post_json   → urllib.request.urlopen (notify.py:536/547)
    · _send_email              → smtplib.SMTP_SSL      (notify.py:938)
  各用例通常 mock 的是**上一层**渠道函数(send_telegram/send_feishu/_send_email)或本层
  (如 _feishu_http_post_json)。本陷阱挂在**最底层 syscall 出口**, 与用例 mock **正交**:
  mock 命中时出口根本不被调用(计数 0, 正确); 任何 mock 漏网的路径一触真实出口即炸。
  这比「trap notify.send」更稳(notify.send 是编排层, dedup/flush 等用例会**合法**调用它)。

范围/局限(诚实标注)
  · 只覆盖**当前进程**: spawn 子进程(notify_dedup U11 / flush_race T1)是全新解释器, 不继承
    本陷阱; 那些子进程自身在 `_patch_channels`/worker 内重新 mock 渠道(既有设计), 故零外发
    由「子进程自打桩」保证, 不由本陷阱保证。
  · 只覆盖 urllib/smtplib 两条协议出口; R2 写入由各脚本自身的 `_upload_glob`/`s3_head` 打桩
    承担(test_204 / test_193 / test_188 均有), 不在本工具范围。
  · 不 trap `socket.*`: 避免与 multiprocessing / DNS 等正常调用误撞(白名单式最小面)。

用法
  from _zero_outbound import ZeroOutboundTrap
  with ZeroOutboundTrap() as trap:
      ...run tests...
      assert trap.hits == [], f"零外发被破坏: {trap.hits}"
"""
from __future__ import annotations

import smtplib
import urllib.request


class ZeroOutboundTrap:
    """包裹真实网络/邮件出口; 触达即计数 + 抛 AssertionError。退出时精确还原原属性。"""

    def __init__(self):
        self.hits: list[str] = []
        self._orig: dict[str, object] = {}

    def __enter__(self) -> "ZeroOutboundTrap":
        self._orig["urlopen"] = urllib.request.urlopen
        self._orig["SMTP"] = smtplib.SMTP
        self._orig["SMTP_SSL"] = smtplib.SMTP_SSL

        def _boom(kind: str):
            def _trap(*_a, **_k):
                self.hits.append(kind)
                raise AssertionError(
                    f"零外发被破坏(§18 L48): 真实 {kind} 被触达 — 用例打桩失效!")
            return _trap

        urllib.request.urlopen = _boom("urllib.request.urlopen")
        smtplib.SMTP = _boom("smtplib.SMTP")
        smtplib.SMTP_SSL = _boom("smtplib.SMTP_SSL")
        return self

    def __exit__(self, *_exc) -> bool:
        urllib.request.urlopen = self._orig["urlopen"]
        smtplib.SMTP = self._orig["SMTP"]
        smtplib.SMTP_SSL = self._orig["SMTP_SSL"]
        return False