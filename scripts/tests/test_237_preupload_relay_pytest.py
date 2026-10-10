# -*- coding: utf-8 -*-
"""test_237_preupload_relay_pytest.py — #237 覆盖前备份「客户端中转」修复的 static-only 单测。

覆盖内容(对应设计文 docs/ops/237-r2-overwrite-backup-guard-design-20261009.md §5.2 验收 2/3/6):
  ① 对照矩阵 4 场景: (a) 正常 key ⇒ copied;
     (b) 已备同内容 key ⇒ skipped(减量仍生效);
     (c) 源对象缺失 ⇒ 按现状语义跳过, **不误报 failed**;
     (d) GET 短读 / PUT 非 200 / 回读不一致(200-but-not-landed 兜底) ⇒ failed + 样本完整;
  ② 返回值契约: `_backup_overwritten_keys` 返回 4 元组 (copied, skipped, failed, samples);
  ③ 失败语义第一阶段: 调用点(_incremental_upload)不阻断 + 打结构化行 `备份完成 copied=.. failed=..`;
  ④ D① fail-loud: BACKUP2 桶凭据缺失时 `_route_bucket` 抛错, 不静默回退老账号;
  ⑤ 减量/并行不回归: 8 线程并行结构仍在(L1166-1169 减量判据等价语义)。

零外发 / 零真 R2 接触: 全部 s3_head / s3_request / _upload_multipart / _list_keys 打桩,
本文件不产生任何网络调用(§18 L48 精神: 具备真实发送链路的路径必须先打桩)。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import upload_r2 as ur  # noqa: E402  (conftest §④ 已铺 .env 垫片, CI 可 import)

SCRIPTS = Path(__file__).absolute().parent.parent
SRC_BKT = "bkt-src-test237"
TGT_BKT = "bkt-tgt-test237"


def _body(key: str) -> bytes:
    return f'{{"key":"{key}","payload":"x"}}'.encode("utf-8")


def _md5_b(bs: bytes) -> str:
    return hashlib.md5(bs).hexdigest()


class FakeR2:
    """极简 R2 桩: src/tgt 两个 key->(etag, size) 表 + GET/PUT 行为注入。"""

    def __init__(self, src, tgt, *, get_truncate=None, put_status=200,
                 put_not_landed=False, head_len_mismatch=False):
        self.src = dict(src)
        self.tgt = dict(tgt)
        self.get_truncate = get_truncate or {}   # {key: 截断后长度}
        self.put_status = put_status
        self.put_not_landed = put_not_landed   # True: PUT 200 但目标桶不落地(平台静默失败形态)
        self.head_len_mismatch = head_len_mismatch
        self.gets = []
        self.puts = []

    # --- 桩实现 ---
    def s3_head(self, key, bucket=None, keep_alive=False, with_len=False):
        store = self.src if (bucket or SRC_BKT) == SRC_BKT else self.tgt
        v = store.get(key)
        if v is None:
            return (404, None, None) if with_len else (404, None)
        etag, size = v
        if with_len and self.head_len_mismatch:
            size = size + 1
        return (200, etag, str(size)) if with_len else (200, etag)

    def s3_request(self, method, key, payload=b"", query="", bucket=None, content_type=None,
                   with_headers=False, keep_alive=False, extra_headers=None, progress_label=None):
        if method == "GET" and not query:
            self.gets.append(key)
            body = _body(key)
            if key in self.get_truncate:
                body = body[:self.get_truncate[key]]
            return (200, body)
        if method == "GET":   # LIST(pre-upload prune)
            return (200, b"<ListBucketResult><IsTruncated>false</IsTruncated></ListBucketResult>")
        if method == "PUT":
            self.puts.append(key)
            if self.put_status == 200 and not self.put_not_landed:
                self.tgt[key] = (_md5_b(bytes(payload)), len(payload))
            return (self.put_status, b"")
        if method == "DELETE":
            return (204, b"")
        raise AssertionError(f"未预期调用 {method} {key}")

    def _upload_multipart(self, key, payload, content_type, bucket=None):
        self.puts.append(key)
        # multipart 对象 ETag 非 md5(分片组合), 只比 Content-Length
        self.tgt[key] = ("fake-multipart-etag-2", len(payload))
        return (200, b"")


@pytest.fixture
def patch_env(monkeypatch):
    monkeypatch.setattr(ur, "BUCKET", SRC_BKT, raising=True)
    monkeypatch.setattr(ur, "BACKUP_BUCKET", TGT_BKT, raising=True)
    yield monkeypatch


def _install(patch_env, fake):
    patch_env.setattr(ur, "s3_head", fake.s3_head, raising=True)
    patch_env.setattr(ur, "s3_request", fake.s3_request, raising=True)
    patch_env.setattr(ur, "_upload_multipart", fake._upload_multipart, raising=True)
    return fake


# ── ① 场景 (a): 正常 key ⇒ copied, 且 P6 回读校验通过 ──────────────────────────
def test_scenario_a_normal_copied(patch_env):
    key = "nav_bucket/01.json"
    body = _body(key)
    fake = FakeR2(src={key: (_md5_b(body), len(body))}, tgt={})
    _install(patch_env, fake)
    copied, skipped, failed, samples = ur._backup_overwritten_keys({key: "deadbeef"}, "t")
    assert (copied, skipped, failed, samples) == (1, 0, 0, [])
    assert fake.gets == [key] and fake.puts == [f"pre-upload/{_today()}/{key}"]


# ── ① 场景 (b): 已备同内容 ⇒ skipped(减量不回归), 且不发生 GET/PUT ──────────────
def test_scenario_b_skip_when_backed_and_same(patch_env):
    key = "index/x-all.json"
    body = _body(key)
    md5 = _md5_b(body)
    fake = FakeR2(src={key: (md5, len(body))},
                  tgt={f"pre-upload/{_today()}/{key}": ("whatever", len(body))})
    _install(patch_env, fake)
    copied, skipped, failed, samples = ur._backup_overwritten_keys({key: md5}, "t")
    assert (copied, skipped, failed, samples) == (0, 1, 0, [])
    assert fake.gets == [] and fake.puts == []


# ── ① 场景 (c): 源对象缺失 ⇒ 跳过 且 不误报 failed ─────────────────────────────
def test_scenario_c_source_missing_not_failed(patch_env):
    key = "nav_bucket/99.json"
    fake = FakeR2(src={}, tgt={})
    _install(patch_env, fake)
    copied, skipped, failed, samples = ur._backup_overwritten_keys({key: "deadbeef"}, "t")
    assert (copied, skipped, failed, samples) == (0, 0, 0, [])
    assert fake.puts == []


# ── ① 场景 (d1): GET 短读 ⇒ failed + 样本 ─────────────────────────────────────
def test_scenario_d1_get_short_read(patch_env):
    key = "nav_bucket/02.json"
    body = _body(key)
    fake = FakeR2(src={key: (_md5_b(body), len(body))}, tgt={}, get_truncate={key: 3})
    _install(patch_env, fake)
    copied, skipped, failed, samples = ur._backup_overwritten_keys({key: "deadbeef"}, "t")
    assert (copied, skipped) == (0, 0)
    assert failed == 1 and samples[0]["stage"] == "GET" and "短读" in samples[0]["detail"]
    assert fake.puts == []


# ── ① 场景 (d2): PUT 非 200 ⇒ failed + 样本 ───────────────────────────────────
def test_scenario_d2_put_non_200(patch_env):
    key = "nav_bucket/03.json"
    body = _body(key)
    fake = FakeR2(src={key: (_md5_b(body), len(body))}, tgt={}, put_status=403)
    _install(patch_env, fake)
    copied, skipped, failed, samples = ur._backup_overwritten_keys({key: "deadbeef"}, "t")
    assert copied == 0 and failed == 1
    assert samples[0]["stage"] == "PUT" and "403" in samples[0]["detail"]


# ── ① 场景 (d3): PUT 200 但目标未落地(静默失败形态)⇒ P6 兜住 ⇒ failed ─────────
def test_scenario_d3_200_but_not_landed(patch_env):
    key = "nav_bucket/04.json"
    body = _body(key)
    fake = FakeR2(src={key: (_md5_b(body), len(body))}, tgt={}, put_not_landed=True)
    _install(patch_env, fake)
    copied, skipped, failed, samples = ur._backup_overwritten_keys({key: "deadbeef"}, "t")
    assert copied == 0 and failed == 1
    assert samples[0]["stage"] == "回读" and "不存在" in samples[0]["detail"]


# ── ① 场景 (d4): 源 md5 与 ETag 不一致 ⇒ failed(源读不一致) ─────────────────────
def test_scenario_d4_source_md5_mismatch(patch_env):
    key = "nav_bucket/05.json"
    body = _body(key)
    fake = FakeR2(src={key: ("0" * 32, len(body))}, tgt={})
    _install(patch_env, fake)
    copied, skipped, failed, samples = ur._backup_overwritten_keys({key: "deadbeef"}, "t")
    assert failed == 1 and samples[0]["stage"] == "源校验"


# ── multipart 源(ETag 含 '-')⇒ 只比长度, 不拿 ETag 当 md5 比 ─────────────────
def test_multipart_source_len_only(patch_env):
    key = "kelly/trades.json"
    body = _body(key)
    fake = FakeR2(src={key: ("abc123-2", len(body))}, tgt={})
    _install(patch_env, fake)
    copied, skipped, failed, samples = ur._backup_overwritten_keys({key: "deadbeef"}, "t")
    assert (copied, failed) == (1, 0)   # ETag 非 md5 也不误判失败; 回读比 Content-Length


# ── ② 返回值契约: 4 元组 + 空输入 ────────────────────────────────────────────
def test_return_contract_empty(patch_env):
    fake = FakeR2(src={}, tgt={})
    _install(patch_env, fake)
    assert ur._backup_overwritten_keys({}, "t") == (0, 0, 0, [])


# ── ④ D① fail-loud: BACKUP2 凭据缺失 ⇒ 抛错(不静默回退老账号) ─────────────────
def test_route_bucket_fail_loud(patch_env):
    patch_env.setattr(ur, "BACKUP2_BUCKET", "signal-backup2-t237", raising=True)
    patch_env.setattr(ur, "BACKUP2_HOST", None, raising=True)
    patch_env.setattr(ur, "BACKUP2_AK", "", raising=True)
    patch_env.setattr(ur, "BACKUP2_SK", "", raising=True)
    with pytest.raises(RuntimeError, match="拒绝静默回退老账号"):
        ur._route_bucket("signal-backup2-t237")
    # 老账号桶不受影响(保持原回退语义)
    assert ur._route_bucket(SRC_BKT) == (ur.HOST, ur.AK, ur.SK)


# ── ③ 第一阶段失败语义: 调用点不阻断 + 打结构化行(static 源核) ─────────────────
def test_call_site_structured_line_and_non_blocking():
    src = (SCRIPTS / "upload_r2.py").read_text(encoding="utf-8")
    assert "备份完成 copied={_bc} skipped={_bs} failed={_bf}" in src
    # 取调用点上下文窗口(锚点唯一): 不阻断 = try/except 包住、无 raise/sys.exit/中止分支
    anchor = "_bc, _bs, _bf, _bsamples = _backup_overwritten_keys("
    i = src.index(anchor)
    seg = src[i - 400:i + 700]
    assert "raise" not in seg and "sys.exit" not in seg
    assert "failed > 0" not in seg and "failed>0" not in seg   # C 级阻断未开
    # 备份段整体仍在 _upload_glob(真 PUT 批)之前
    assert src.index("_backup_overwritten_keys(") < src.index("ok, total, failed_rels, uploaded_keys = _upload_glob(")


# ── ⑤ 减量/并行不回归(结构核) ───────────────────────────────────────────────
def test_parallel_and_dedup_kept():
    src = (SCRIPTS / "upload_r2.py").read_text(encoding="utf-8")
    fn = src.split("def _backup_overwritten_keys", 1)[1].split("\ndef _incremental_upload", 1)[0]
    assert "ThreadPoolExecutor(max_workers=8)" in fn          # 并行度 10-05 优化保留
    assert "bk_st == 200 and local_md5 is not None" in fn      # 减量判据保留
    assert 'extra_headers={"x-amz-copy-source"' not in fn      # 服务端 COPY 调用已移除(文档提及不算)


def _today() -> str:
    import datetime
    return datetime.date.today().strftime("%Y%m%d")