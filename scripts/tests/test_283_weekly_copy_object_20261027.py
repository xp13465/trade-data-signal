# -*- coding: utf-8 -*-
"""周备份副本改「同桶服务端复制(CopyObject)」+ 失败回退 PUT 的自测(2026-10-27)。

背景(实测,`/tmp/agent-progress-r2-lock-congestion.md`): `upload-db` 每晚持全局上传锁约 3290s,
其中 public_fund 的日备份 + 周副本各走一次 790MB 跨境(实测 500-580KB/s)≈ 1.77GB;
而周副本源/目标**同桶同账号**(都在 BACKUP_BUCKET=signal-backup2)⇒ 本可服务端复制,
原实现却把同一个 .gz 重新 PUT 一遍,白占锁 ~28 分钟。

本文件覆盖(全部 s3_request / _upload_file_to_key 打桩,零网络零外发):
  ① 本周首次 ⇒ 走服务端复制(唯一一次 s3_request,带 x-amz-copy-source,源目标同桶),**不**再 PUT;
  ② 本周已有(哪怕不同日期)⇒ 全跳过,零请求;
  ③ 复制抛异常 ⇒ 回退 PUT(参数与改动前逐字一致),打「回退 PUT 上传」日志,返回回退结果;
  ④ 复制返回非 200 ⇒ 同上回退;
  ⑤ 复制返回 200 但 body 是 <Error>(S3/R2「响应开始后才失败」语义)⇒ 同上回退;
  ⑥ 复制失败 + 回退也失败 ⇒ 返回 False 并打「周备份上传失败」(告警行保留);
  ⑦ 范围锁:源码形状守卫「copy 只在 file 版周/月副本函数里, 且互不越界(周函数无 monthly key,
     月函数无 weekly key)」;内存版 payload 入口仍走原 s3_request PUT(本次不改);
  ⑧ 零外发交叉证据: ZeroOutboundTrap 武装下跑复制路径,hits 必须为空。
  ⑨ 月副本(2026-10-27 追加, 与周副本逐字同构): 本月首次复制成功 / 本月已有零请求 /
     异常回退 / 非 200 或 200+<Error> 回退 / 复制与回退都失败 / 零外发。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import upload_r2 as ur  # noqa: E402
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

BKT = "signal-backup2"
TODAY = "20261027"          # 周二, ISO 2026-W44
PREV_WEEK_KEY = "weekly/public_fund_20261020.db.gz"   # 2026-10-20 同二, ISO 2026-W43
SAME_WEEK_KEY = "weekly/public_fund_20261026.db.gz"   # 2026-10-26 周一, 同一 ISO 周

SRC_KEY = f"backup/public_fund_{TODAY}.db.gz"
DST_KEY = f"weekly/public_fund_{TODAY}.db.gz"


class FakeS3:
    """s3_request 替身: 只记录调用并返回预设结果(默认空 200 = 复制成功)。"""

    def __init__(self, result=(200, b"<CopyObjectResult/>"), raises=None):
        self.calls = []
        self.result = result
        self.raises = raises

    def __call__(self, method, key, payload=b"", query="", bucket=None, content_type=None,
                 with_headers=False, keep_alive=False, extra_headers=None, progress_label=None):
        self.calls.append({
            "method": method, "key": key, "payload": payload, "bucket": bucket,
            "content_type": content_type, "extra_headers": extra_headers,
        })
        if self.raises is not None:
            raise self.raises
        return self.result


@pytest.fixture
def env(monkeypatch, tmp_path):
    """隔离环境: 备份桶名钉住 / 本地 gz 用小文件 / 日上传与 listing 全打桩。"""
    monkeypatch.setattr(ur, "BACKUP_BUCKET", BKT)
    gz = tmp_path / "public_fund.db.gz"
    gz.write_bytes(b"fake-gz-payload" * 64)
    uploads = []

    def fake_upload(key, path, content_type, bucket=None):
        uploads.append({"key": key, "path": str(path), "content_type": content_type, "bucket": bucket})
        return 200, b""

    monkeypatch.setattr(ur, "_upload_file_to_key", fake_upload)
    return {"gz": gz, "uploads": uploads}


def _latest(monkeypatch, value):
    monkeypatch.setattr(ur, "_latest_dated_key", lambda *a, **k: value)


# ── ① 本周首次 ⇒ 服务端复制(不重传) ────────────────────────────────────────
def test_copy_used_on_first_run_of_week(env, monkeypatch, capsys):
    _latest(monkeypatch, ("20261020", PREV_WEEK_KEY))
    fake = FakeS3()
    monkeypatch.setattr(ur, "s3_request", fake)

    ret = ur._maybe_upload_weekly_file("public_fund", env["gz"], TODAY)

    assert ret is True
    assert len(fake.calls) == 1, "本周首次只应发一次请求(复制), 不得再有 PUT"
    call = fake.calls[0]
    assert call["method"] == "PUT" and call["key"] == DST_KEY
    assert call["payload"] == b"", "CopyObject 不带请求体(不跨境传字节)"
    src = call["extra_headers"]["x-amz-copy-source"]
    assert src == f"/{BKT}/{SRC_KEY}", f"源应指向同桶当日日备份 key: {src}"
    # 同桶同账号铁律(验1): copy-source 的桶 == 目标请求的桶
    assert call["bucket"] == src.split("/")[1] == BKT
    assert env["uploads"] == [], "复制成功时不得回退 PUT"
    out = capsys.readouterr().out
    assert "服务端复制" in out and "回退" not in out


# ── ② 同一 ISO 周已有(含周一那条)⇒ 全跳过 ─────────────────────────────────
@pytest.mark.parametrize("latest", [("20261027", DST_KEY), ("20261026", SAME_WEEK_KEY)])
def test_same_iso_week_skips_all_io(env, monkeypatch, capsys, latest):
    _latest(monkeypatch, latest)
    fake = FakeS3()
    monkeypatch.setattr(ur, "s3_request", fake)

    ret = ur._maybe_upload_weekly_file("public_fund", env["gz"], TODAY)

    assert ret is False
    assert fake.calls == [] and env["uploads"] == []
    assert "本周已有" in capsys.readouterr().out


# ── ③ 复制抛异常 ⇒ 回退 PUT, 参数与改动前逐字一致 ──────────────────────────
def test_fallback_to_put_on_exception(env, monkeypatch, capsys):
    _latest(monkeypatch, ("20261020", PREV_WEEK_KEY))
    monkeypatch.setattr(ur, "s3_request", FakeS3(raises=OSError("copy boom")))

    ret = ur._maybe_upload_weekly_file("public_fund", env["gz"], TODAY)

    assert ret is True
    assert env["uploads"] == [{
        "key": DST_KEY, "path": str(env["gz"]),
        "content_type": "application/gzip", "bucket": BKT,
    }], "回退路径必须与原 PUT 调用逐字一致"
    out = capsys.readouterr().out
    assert "回退 PUT 上传" in out and "OSError" in out and "copy boom" in out


# ── ④ / ⑤ 复制非 200 / 200+<Error> ⇒ 同样回退 ──────────────────────────────
@pytest.mark.parametrize("result", [
    (403, b"<Error><Code>AccessDenied</Code></Error>"),
    (404, b"<Error><Code>NoSuchKey</Code></Error>"),
    (500, b"<Error><Code>InternalError</Code></Error>"),
    (200, b"<Error><Code>InternalError</Code></Error>"),   # S3 语义: 200 + Error 体 = 失败
])
def test_fallback_on_failed_copy_result(env, monkeypatch, capsys, result):
    _latest(monkeypatch, ("20261020", PREV_WEEK_KEY))
    monkeypatch.setattr(ur, "s3_request", FakeS3(result=result))

    ret = ur._maybe_upload_weekly_file("public_fund", env["gz"], TODAY)

    assert ret is True
    assert len(env["uploads"]) == 1 and env["uploads"][0]["key"] == DST_KEY
    out = capsys.readouterr().out
    assert "回退 PUT 上传" in out
    assert f"status={result[0]}" in out


# ── ⑥ 复制失败 + 回退也失败 ⇒ False + 原告警行 ─────────────────────────────
def test_copy_and_fallback_both_fail(env, monkeypatch, capsys):
    _latest(monkeypatch, ("20261020", PREV_WEEK_KEY))
    monkeypatch.setattr(ur, "s3_request", FakeS3(raises=RuntimeError("net down")))

    def fail_upload(key, path, content_type, bucket=None):
        env["uploads"].append({"key": key})
        return 503, b"still down"

    monkeypatch.setattr(ur, "_upload_file_to_key", fail_upload)

    ret = ur._maybe_upload_weekly_file("public_fund", env["gz"], TODAY)

    assert ret is False
    out = capsys.readouterr().out
    assert "回退 PUT 上传" in out
    assert "周备份上传失败 status=503" in out, "分项失败告警行必须保留"


# ── ⑦ 范围锁: 源码形状守卫(周/月各自只碰自己的 prefix) ────────────────────
def test_source_shape_copy_scoped_per_prefix():
    """源码形状守卫(L52 同精神): copy-source 只在 file 版周/月副本函数里, 且各不越界。"""
    src = (REPO / "scripts" / "upload_r2.py").read_text(encoding="utf-8")
    weekly = src.split("def _maybe_upload_weekly_file", 1)[1].split("\ndef ", 1)[0]
    monthly = src.split("def _maybe_upload_monthly_file", 1)[1].split("\ndef ", 1)[0]
    weekly_mem = src.split("def _maybe_upload_weekly", 1)[1].split("\ndef ", 1)[0]
    monthly_mem = src.split("def _maybe_upload_monthly", 1)[1].split("\ndef ", 1)[0]
    # 两处都走服务端复制, 且回退 PUT 在 copy 之后
    for fn in (weekly, monthly):
        assert 'extra_headers={"x-amz-copy-source"' in fn
        assert fn.index("copy-source") < fn.index("_upload_file_to_key(")
    # 范围锁: 周副本函数不许出现 monthly key, 反之亦然
    assert 'f"monthly/{name}' not in weekly
    assert 'f"weekly/{name}' not in monthly
    # 内存版(payload 入口)本次不改: 仍在用 s3_request PUT 原样上传
    for fn in (weekly_mem, monthly_mem):
        assert "copy-source" not in fn
        assert "s3_request(" in fn


# ══════════════════ 月副本同根因同批改(2026-10-27 追加) ══════════════════
# 与周副本**逐字同构**: 本月首次服务端复制 / 三种失败入口回退 / 本月已有零请求。
MONTHLY_SRC = f"backup/public_fund_{TODAY}.db.gz"
MONTHLY_DST = f"monthly/public_fund_{TODAY}.db.gz"
PREV_MONTH_KEY = "monthly/public_fund_20260930.db.gz"    # 上个月 ⇒ 本月首次
SAME_MONTH_KEY = "monthly/public_fund_20261001.db.gz"    # 同月不同日 ⇒ 跳过


def test_monthly_copy_used_on_first_run_of_month(env, monkeypatch, capsys):
    _latest(monkeypatch, ("20260930", PREV_MONTH_KEY))
    fake = FakeS3()
    monkeypatch.setattr(ur, "s3_request", fake)

    ret = ur._maybe_upload_monthly_file("public_fund", env["gz"], TODAY)

    assert ret is True
    assert len(fake.calls) == 1, "本月首次只应发一次请求(复制), 不得再有 PUT"
    call = fake.calls[0]
    assert call["method"] == "PUT" and call["key"] == MONTHLY_DST
    assert call["payload"] == b""
    assert call["extra_headers"]["x-amz-copy-source"] == f"/{BKT}/{MONTHLY_SRC}"
    assert call["bucket"] == BKT
    assert env["uploads"] == [], "复制成功时不得回退 PUT"
    out = capsys.readouterr().out
    assert "月备份副本(同桶服务端复制)" in out and "回退" not in out


@pytest.mark.parametrize("latest", [("20261027", MONTHLY_DST), ("20261001", SAME_MONTH_KEY)])
def test_monthly_same_month_skips_all_io(env, monkeypatch, capsys, latest):
    _latest(monkeypatch, latest)
    fake = FakeS3()
    monkeypatch.setattr(ur, "s3_request", fake)

    ret = ur._maybe_upload_monthly_file("public_fund", env["gz"], TODAY)

    assert ret is False
    assert fake.calls == [] and env["uploads"] == []
    assert "本月已有" in capsys.readouterr().out


def test_monthly_fallback_to_put_on_exception(env, monkeypatch, capsys):
    _latest(monkeypatch, ("20260930", PREV_MONTH_KEY))
    monkeypatch.setattr(ur, "s3_request", FakeS3(raises=OSError("copy boom")))

    ret = ur._maybe_upload_monthly_file("public_fund", env["gz"], TODAY)

    assert ret is True
    assert env["uploads"] == [{
        "key": MONTHLY_DST, "path": str(env["gz"]),
        "content_type": "application/gzip", "bucket": BKT,
    }], "回退路径必须与原 PUT 调用逐字一致"
    out = capsys.readouterr().out
    assert "月备份服务端复制失败" in out and "回退 PUT 上传" in out and "OSError" in out


@pytest.mark.parametrize("result", [
    (403, b"<Error><Code>AccessDenied</Code></Error>"),
    (404, b"<Error><Code>NoSuchKey</Code></Error>"),
    (500, b"<Error><Code>InternalError</Code></Error>"),
    (200, b"<Error><Code>InternalError</Code></Error>"),   # 200 + Error 体 = 失败
])
def test_monthly_fallback_on_failed_copy_result(env, monkeypatch, capsys, result):
    _latest(monkeypatch, ("20260930", PREV_MONTH_KEY))
    monkeypatch.setattr(ur, "s3_request", FakeS3(result=result))

    ret = ur._maybe_upload_monthly_file("public_fund", env["gz"], TODAY)

    assert ret is True
    assert len(env["uploads"]) == 1 and env["uploads"][0]["key"] == MONTHLY_DST
    out = capsys.readouterr().out
    assert "回退 PUT 上传" in out and f"status={result[0]}" in out


def test_monthly_copy_and_fallback_both_fail(env, monkeypatch, capsys):
    _latest(monkeypatch, ("20260930", PREV_MONTH_KEY))
    monkeypatch.setattr(ur, "s3_request", FakeS3(raises=RuntimeError("net down")))

    def fail_upload(key, path, content_type, bucket=None):
        env["uploads"].append({"key": key})
        return 503, b"still down"

    monkeypatch.setattr(ur, "_upload_file_to_key", fail_upload)

    ret = ur._maybe_upload_monthly_file("public_fund", env["gz"], TODAY)

    assert ret is False
    out = capsys.readouterr().out
    assert "回退 PUT 上传" in out
    assert "月备份上传失败 status=503" in out, "分项失败告警行必须保留"


def test_monthly_copy_path_zero_outbound(env, monkeypatch):
    _latest(monkeypatch, ("20260930", PREV_MONTH_KEY))
    monkeypatch.setattr(ur, "s3_request", FakeS3())
    with ZeroOutboundTrap() as trap:
        assert ur._maybe_upload_monthly_file("public_fund", env["gz"], TODAY) is True
        assert trap.hits == [], f"零外发被破坏: {trap.hits}"


# ── ⑧ 零外发交叉证据 ───────────────────────────────────────────────────────
def test_copy_path_zero_outbound(env, monkeypatch):
    _latest(monkeypatch, ("20261020", PREV_WEEK_KEY))
    monkeypatch.setattr(ur, "s3_request", FakeS3())
    with ZeroOutboundTrap() as trap:
        assert ur._maybe_upload_weekly_file("public_fund", env["gz"], TODAY) is True
        assert trap.hits == [], f"零外发被破坏: {trap.hits}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s"]))