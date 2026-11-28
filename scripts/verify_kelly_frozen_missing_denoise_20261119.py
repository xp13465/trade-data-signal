#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冻结缺失降噪方案 B1 的端到端 dry 验证(不真发通知, 不落归档, 不写生产状态)。

做法: 读一份冻结缺失诊断归档(--archive), 喂给 signal_kelly_backtest._alert_frozen_missing,
把「写归档」与「发告警」两处出口都打桩(monkeypatch), 只断言分类结果:
- 已登记(有证据)的键进 accepted_hits → 只写日志、不告警
- 未登记的键进 new_events → 继续告警(>=10 条 → 1 条 SEVERE; <10 条 → 非 SEVERE 延后摘要)
并断言登记键不出现在告警正文(防「登记了却仍报」/「留报键被静默吞掉」)。

为何必须打桩(§18 L48): 本脚本会走真实告警判定链, 不打桩就会给用户发真邮件/飞书。
状态文件隔离(2026-11-28 M1): 告警判定会读写 `SIGNAL_KELLY_FROZEN_MISSING_SEEN_STATE`;
脚本用临时文件覆盖该 env, 绝不写仓库 `data/alerts/kelly_frozen_missing_seen.json`
(否则在生产树跑一次就把 7 个留报键预静音, 抵消降噪回退)。

基线期望(2026-11-19 归档 5bc33ec582cc4c6cbbdd3e0aa7f84d51, 121 条 filtered_missing;
config 为 2026-11-20 补登记 13 键后的 122 条版本):
  accepted_hits = 114(A 96 + B 5 + 11-20 补证 13 + legacy 命中 0: 8 条 legacy 键不在本归档内)
  new_events(留报) = 7 = 20261009 三键 + 20261019|csi_000813 + 20261105|dax
                     + 2 真故障嫌疑(20261111|cac40、20261113|csi_931946)
  告警 = 1 条非 SEVERE(7 < 10, severe=False + defer_digest=True 进摘要), 主题含「7 个」

用法(仓库根目录):
  .venv/bin/python scripts/verify_kelly_frozen_missing_denoise_20261119.py \
      --archive /tmp/frozen_missing_latest_20261119.json \
      --config config/signal_kelly_frozen_missing_accepted.json
退出码 0 = DRY_PASS; 非 0 = 断言失败(打印原因)。
"""
import argparse
import json
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

EXPECT_ACCEPTED_HIT = 114
EXPECT_KEPT = 7
# 2026-11-20 补登记 13 键后剩余必须留报的 7 键(5 证据不全/真实缺冻 + 2 真故障嫌疑)
MUST_KEEP = [
    "20261009|csi_000330|buy_aux", "20261009|csi_970070|buy_aux",
    "20261009|sz_div|buy",
    "20261019|csi_000813|buy_aux",
    "20261105|dax|buy_special",
    "20261111|cac40|buy_special",
    "20261113|csi_931946|buy_special",
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive", required=True)
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    import signal_kelly_backtest as sk  # noqa: E402

    d = json.load(open(args.archive, encoding="utf-8"))
    keys = d["filtered_missing"]
    events = set()
    for k in keys:
        a, b, c = k.split("|")
        events.add((a, b, c))

    sent = []
    archived = []

    def fake_send_alert(*a, **kw):
        sent.append((a, kw))
        # 真实投递成功形态(status=sent 才算已报; rc 单独不足以判定, 见 notify_hook B1)
        return types.SimpleNamespace(rc=0, route="dry", status="sent")

    def fake_archive(new_events, accepted_hit, context=None):
        archived.append((sorted(new_events), sorted(accepted_hit)))

    sk.FROZEN_MISSING_ACCEPTED_PATH = args.config
    sk._archive_frozen_missing_diagnostics = fake_archive
    import app.notify_hook  # noqa: E402
    app.notify_hook.send_alert = fake_send_alert

    # M1: 状态文件只写临时路径, 不写仓库生产状态(防把 7 个留报键预静音)
    repo_state_existed = os.path.exists(sk.FROZEN_MISSING_SEEN_PATH)
    fd, state_path = tempfile.mkstemp(prefix="kelly_frozen_missing_state_", suffix=".json")
    os.close(fd)
    os.unlink(state_path)  # 首跑形态 = 状态缺失
    prev_state_env = os.environ.get(sk.FROZEN_MISSING_SEEN_ENV)
    os.environ[sk.FROZEN_MISSING_SEEN_ENV] = state_path
    try:
        sk._alert_frozen_missing(events)
    finally:
        if prev_state_env is None:
            os.environ.pop(sk.FROZEN_MISSING_SEEN_ENV, None)
        else:
            os.environ[sk.FROZEN_MISSING_SEEN_ENV] = prev_state_env

    assert len(archived) == 1, "归档应恰好 1 次, 实 %d" % len(archived)
    new_events, accepted_hit = archived[0]
    print("input events:", len(events))
    print("accepted_hit:", len(accepted_hit))
    print("new_events(留报):", len(new_events))
    assert len(accepted_hit) == EXPECT_ACCEPTED_HIT, \
        "accepted_hit 应为 %d, 实 %d" % (EXPECT_ACCEPTED_HIT, len(accepted_hit))
    assert len(new_events) == EXPECT_KEPT, \
        "留报应为 %d, 实 %d" % (EXPECT_KEPT, len(new_events))
    assert len(sent) == 1, "应发 1 条留报告警, 实 %d" % len(sent)
    subject, body = sent[0][0][0], sent[0][0][1]
    print("subject:", subject)
    assert ("%d 个" % EXPECT_KEPT) in subject, subject
    assert sent[0][1].get("severe") is False, sent[0][1]
    assert sent[0][1].get("defer_digest") is True, sent[0][1]

    new_keys = ["%s|%s|%s" % (a, b, c) for a, b, c in new_events]
    for k in MUST_KEEP:
        assert k in new_keys, "应留报但被登记: " + k
    # 登记键不得出现在告警正文(防「登记了却仍报」)
    accepted_keys = [k for k in keys if k not in set(new_keys)]
    for k in accepted_keys:
        assert k not in body, "登记键泄漏进告警: " + k

    # M1 证据: 状态只落临时隔离路径; 仓库生产状态文件未被创建/改动
    assert os.path.exists(state_path), "状态未写临时隔离路径(应写一次)"
    assert os.path.exists(sk.FROZEN_MISSING_SEEN_PATH) == repo_state_existed, \
        "生产状态文件被本脚本创建/改动: %s" % sk.FROZEN_MISSING_SEEN_PATH
    print("state_file(isolated):", state_path)

    print("留报键:")
    for k in new_keys:
        print("  ", k)
    try:
        os.unlink(state_path)
    except OSError:
        pass
    print("DRY_PASS")


if __name__ == "__main__":
    main()
