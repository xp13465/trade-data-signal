#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2026-11-28 P2 端到端 dry 验证(不真发通知, 不落归档): 34 个晚到键登记后不再告警。

做法(与 2026-11-19 版同一套打桩口径): 读一份冻结缺失诊断归档(--archive, 即云上
`data/audit/frozen_missing/<run_id>.json` 的只读本地副本), 喂给
`signal_kelly_backtest._alert_frozen_missing`, 把「写归档」与「发告警」两处出口都打桩,
只断言分类结果。

为何必须打桩(§18 L48): 本脚本会走真实告警判定链, 不打桩就会给用户发真邮件/飞书。

期望(2026-11-28 归档 2d1b21f1a8b6493dbbea8d0427ca515b, filtered_missing 34 条,
sha256=e573f3a4…; config 为 122 + 34 = 156 条版本):
  accepted_hit = 34(全部命中 C_late_rowid_bulk_backfill)
  new_events   = 0  ⇒ 不写归档、不发任何通知

用法(仓库根目录):
  .venv/bin/python scripts/verify_kelly_frozen_missing_denoise_20261128.py \
      --archive /tmp/frozen_missing_20261128.json
退出码 0 = DRY_PASS; 非 0 = 断言失败(打印原因)。
"""
import argparse
import hashlib
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

EXPECT_ACCEPTED_HIT = 34
EXPECT_KEPT = 0
EXPECT_SHA256 = "e573f3a43f04658228f0022385475668e42406555ccccfcdaf19265be7b1aee2"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive", required=True, help="冻结缺失归档(本地只读副本)")
    args = ap.parse_args()

    import signal_kelly_backtest as sk  # noqa: E402

    d = json.load(open(args.archive, encoding="utf-8"))
    keys = d["filtered_missing"]
    raw_sha = hashlib.sha256(
        json.dumps(keys, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert raw_sha == EXPECT_SHA256, "归档事件集合指纹变了: " + raw_sha
    assert len(keys) == EXPECT_ACCEPTED_HIT, len(keys)
    events = set(tuple(k.split("|")) for k in keys)

    sent = []
    archived = []

    def fake_send_alert(*a, **kw):
        sent.append((a, kw))
        return types.SimpleNamespace(rc=0, route="dry")

    def fake_archive(new_events, accepted_hit, context=None):
        archived.append((sorted(new_events), sorted(accepted_hit)))

    sk._archive_frozen_missing_diagnostics = fake_archive
    import app.notify_hook  # noqa: E402
    app.notify_hook.send_alert = fake_send_alert

    sk._alert_frozen_missing(events)

    new_events = archived[0][0] if archived else []
    accepted_hit = archived[0][1] if archived else sorted(events)
    print("input events:", len(events))
    print("accepted_hit:", len(accepted_hit))
    print("new_events(留报):", len(new_events))
    print("sent alerts:", len(sent))
    assert len(accepted_hit) == EXPECT_ACCEPTED_HIT, \
        "accepted_hit 应为 %d, 实 %d" % (EXPECT_ACCEPTED_HIT, len(accepted_hit))
    assert len(new_events) == EXPECT_KEPT, \
        "留报应为 %d, 实 %d: %s" % (EXPECT_KEPT, len(new_events), new_events[:5])
    assert not sent, "全部登记后不应再发任何通知, 实 %d" % len(sent)
    assert not archived, "无表外事件时不应写归档, 实 %d" % len(archived)
    print("DRY_PASS")


if __name__ == "__main__":
    main()
