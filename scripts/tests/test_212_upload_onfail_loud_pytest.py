# -*- coding: utf-8 -*-
"""#212(2026-10-07): R2 上传通道「失败 loud 化」落地自验(pytest, CI 门禁 ⑧ 收集)。

落地内容(证据表见 docs/ops/212-channel-failure-matrix-20261007.md):
  - A 类 13 条增量通道接 `_incremental_upload(..., on_fail=_channel_on_fail(...))`;
  - B 类 data_files 在 L2289 失败处命令级单点接 `_notify_channel_upload_fail(label="data-files")`。

断言分组:
  [A] 端到端失败路径(参数化 13 通道): cmd 真跑引擎(_upload_glob 打桩 ok!=total)
      → exit 1 + 恰发 1 条 severe 告警, 标题含通道+计数, 「含义」括注 = 本通道 note,
      去重键 = r2_channel_upload_fail_{label}, 窗口 21600。
  [B] data_files 失败路径: cmd_upload_data_files 打桩失败 → exit 1 + 1 条 label="data-files" 告警。
  [C] 成功路径(ok==total): 零告警不制造噪音。
  [D] 回归/改前对照: 引擎 on_fail 默认 None; 不接 on_fail 时失败仍 exit 1 且零告警(= 改前 13 通道静默);
      data_files 反事实对照: 屏蔽新增 notify 调用即复现「exit 1 零外发」= 改前形态;
      静态对照(未提交态可得): HEAD 版无 _channel_on_fail / data_files 失败分支无 notify = 病灶真存在。
  [E] §18 L48 硬门: 真实 notify.send 挂陷阱全程零触达; _upload_glob 全打桩零真实 PUT。

⚠️ §18 L48 / memory notify-script-selftest-must-stub: 本文件**只做 static 打桩**, 绝不执行任何
   真实上传/告警路径。三重防线: ① notify 桩先装 + 真实 send 挂陷阱(触达即炸); ② `_upload_glob` /
   `_backup_overwritten_keys` / `purge_cache` 全打桩; ③ ur.STATIC_DIR / ur.ROOT 重定向到临时树。

跑法: python3 -m pytest -q scripts/tests/test_212_upload_onfail_loud_pytest.py
"""
import inspect
import json
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).absolute().parent.parent  # scripts/tests -> scripts
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import upload_r2 as ur  # noqa: E402  (conftest §④ 已铺 .env 垫片, CI 可 import)


# ---- 13 A 类通道参数表(与 upload_r2.py 挂点逐条对应; 改挂点必须同步本表) ----
# local_rel: 引擎 local_dir 相对 STATIC_DIR; file: 该通道 glob 命中的样本文件(直接位于 local_dir)
_A_CHANNELS = [
    dict(label="lab", cmd="cmd_upload_lab", cmd_name="upload-lab", prefix="lab",
         state=".r2_lab_state.json", local_rel="data/lab", file="a.json",
         patterns=["*.json"], fp=None, excl=None),
    dict(label="trade-sim", cmd="cmd_upload_trade_sim", cmd_name="upload-trade-sim",
         prefix="trade_sim", state=".r2_trade_sim_html_state.json", local_rel="",
         file="trade_sim_1.html", patterns=["trade_sim_*.html"], fp=None, excl=None),
    dict(label="trade-sim-json", cmd="cmd_upload_trade_sim_json", cmd_name="upload-trade-sim-json",
         prefix="trade_sim_data", state=".r2_trade_sim_json_state.json",
         local_rel="data/trade_sim", file="ts1_stats.json", patterns=["*.json"], fp=None, excl=None),
    dict(label="index", cmd="cmd_upload_index", cmd_name="upload-index", prefix="index",
         state=".r2_index_state.json", local_rel="data/index", file="iid-all.json",
         patterns=["*.json"], fp=None, excl=None),
    dict(label="etf-hist", cmd="cmd_upload_etf_hist", cmd_name="upload-etf-hist", prefix="etf",
         state=".r2_etf_hist_state.json", local_rel="data/etf", file="000001-all.json",
         patterns=["*.json"], fp="etf", excl=None),
    dict(label="accum-nav", cmd="cmd_upload_accum_nav", cmd_name="upload-accum-nav",
         prefix="accum_nav", state=".r2_accum_nav_state.json", local_rel="data/accum_nav",
         file="000001.json", patterns=["*.json"], fp=None, excl=None),
    dict(label="industry", cmd="cmd_upload_industry", cmd_name="upload-industry", prefix="industry",
         state=".r2_industry_state.json", local_rel="data", file="industry-1m.json",
         patterns=["industry-all-indices/*", "industry-5y-indices/*",
                   "industry-3y-indices/*", "industry-*.json"], fp=None, excl=None),
    dict(label="public-fund", cmd="cmd_upload_public_fund", cmd_name="upload-public-fund",
         prefix="public_fund", state=".r2_public_fund_state.json", local_rel="data",
         file="public_fund-x.json", patterns=["public_fund*.json"], fp=None, excl=None),
    dict(label="kelly-parts", cmd="cmd_upload_kelly_parts", cmd_name="upload-kelly-parts",
         prefix="data/signal_kelly_trades_parts", state=".r2_kelly_parts_state.json",
         local_rel="data/signal_kelly_trades_parts", file="recent.json",
         patterns=["*.json"], fp="kelly", excl=None),
    dict(label="kelly-parts-sdc", cmd="cmd_upload_kelly_parts_sdc", cmd_name="upload-kelly-parts-sdc",
         prefix="data/signal_kelly_trades_sdc_parts", state=".r2_kelly_sdc_state.json",
         local_rel="data/signal_kelly_trades_sdc_parts", file="recent.json",
         patterns=["*.json"], fp="kelly", excl=None),
    dict(label="kelly-snapshots", cmd="cmd_upload_kelly_snapshots", cmd_name="upload-kelly-snapshots",
         prefix="data/signal_kelly_snapshots", state=".r2_kelly_snapshots_state.json",
         local_rel="data/signal_kelly_snapshots", file="index.json",
         patterns=["*.json"], fp=None, excl=None),
    dict(label="data-large", cmd="cmd_upload_data_large", cmd_name="upload-data-large", prefix="data",
         state=".r2_data_large_state.json", local_rel="data", file="foo-all.json",
         patterns=["*.json"], fp=None, excl="large"),
    dict(label="all-data", cmd="cmd_upload_all_data", cmd_name="upload-all-data", prefix="data",
         state=".r2_all_data_state.json", local_rel="data", file="overview.json",
         patterns=["*.json"], fp=None, excl="all"),
]

# 期望的 impact_note 结尾片段(逐通道唯一可辨识子串, 防把 fund_score 文案误挂)
_NOTE_FRAG = {
    "lab": "策略实验室", "trade-sim": "模拟回测详情页", "trade-sim-json": "回测弹窗走势",
    "index": "指数K线", "etf-hist": "弹窗长历史K线", "accum-nav": "全站净值走势",
    "industry": "行业卡", "public-fund": "公募筛选器", "kelly-parts": "凯利分片",
    "kelly-parts-sdc": "当日收盘", "kelly-snapshots": "凯利演进曲线",
    "data-large": "过拟合监控", "all-data": "新闻看板",
}


# ============================ 打桩工具 ============================

def _install_notify_stub():
    """sys.modules['notify'] -> Fake; 真实 notify.send 挂陷阱(证打桩生效, §18 L48)。"""
    import notify as real_notify
    trap = []
    prev_send = real_notify.send

    def _trap(*a, **k):
        trap.append((a, k))
        raise AssertionError("真实 notify.send 被触达 = 打桩失效(§18 L48)!")

    real_notify.send = _trap  # 兜底: 任何漏网的真实调用立刻炸

    calls = []
    fake = types.ModuleType("notify")

    def _send(subject, body, **kw):
        calls.append(("send", subject, body, dict(kw)))

    def _check_dedup(key, window):
        calls.append(("check_dedup", key, window))
        return False  # 未发过 -> 允许发

    def _update_dedup(key):
        calls.append(("update_dedup", key))

    fake.send = _send
    fake.check_dedup = _check_dedup
    fake.update_dedup = _update_dedup
    prev_mod = sys.modules.get("notify")
    sys.modules["notify"] = fake
    return calls, trap, real_notify, prev_mod, prev_send


def _restore_notify(real_notify, prev_mod, prev_send):
    real_notify.send = prev_send
    if prev_mod is None:
        sys.modules.pop("notify", None)
    else:
        sys.modules["notify"] = prev_mod


def _install_engine_stubs(fail):
    """打桩引擎落地动作; fail=True 时 _upload_glob 返回 ok!=total。"""
    put_calls = []

    def _fake_upload_glob(local_dir, patterns, r2_prefix, **kw):
        items = kw.get("only_files")
        src = list(items) if items is not None else list(patterns)
        rels = []
        for p in src:
            if isinstance(p, str):          # data_files: patterns 是文件名字符串
                rels.append(p)
                continue
            try:
                rels.append(p.relative_to(local_dir).as_posix())
            except (TypeError, ValueError):
                rels.append(str(p))
        put_calls.append({"prefix": r2_prefix, "rels": rels})
        if fail:
            return (max(len(rels) - 1, 0), len(rels), rels[-1:], [])
        return (len(rels), len(rels), [], [])

    prev = (ur._upload_glob, ur._backup_overwritten_keys, ur.purge_cache, ur._DRY_RUN)
    ur._upload_glob = _fake_upload_glob
    ur._backup_overwritten_keys = lambda *a, **k: None
    ur.purge_cache = lambda *a, **k: None
    ur._DRY_RUN = False
    return prev, put_calls


def _restore_engine(prev):
    (ur._upload_glob, ur._backup_overwritten_keys, ur.purge_cache, ur._DRY_RUN) = prev


@pytest.fixture
def stub_env():
    """装 notify + 引擎打桩 + 临时树重定向; yield 句柄, 收尾全还原。"""
    calls, trap, real_notify, prev_mod, prev_send = _install_notify_stub()
    prev_engine, put_calls = _install_engine_stubs(fail=True)
    old_static, old_root = ur.STATIC_DIR, ur.ROOT
    trees = []
    handle = types.SimpleNamespace(calls=calls, trap=trap, put_calls=put_calls, trees=trees,
                                   ur=ur)
    try:
        yield handle
    finally:
        for t in trees:
            shutil.rmtree(t, ignore_errors=True)
        ur.STATIC_DIR, ur.ROOT = old_static, old_root
        _restore_engine(prev_engine)
        _restore_notify(real_notify, prev_mod, prev_send)


def _mk_tree(spec):
    """临时树: 造该通道的样本文件 + 旧状态(指纹不一致 → 待传, 且绕过 export-guard L3 首次全量拦截)。"""
    root = Path(tempfile.mkdtemp(prefix=f"t212-{spec['label']}-"))
    sd = root / "static-site"
    fpath = (sd / spec["local_rel"] / spec["file"]) if spec["local_rel"] else (sd / spec["file"])
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text('{"a": 1}', encoding="utf-8")
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / spec["state"]).write_text(
        json.dumps({"version": 1, "files": {spec["file"]: {"size": 1, "md5": "deadbeef"}}}),
        encoding="utf-8")
    ur.STATIC_DIR, ur.ROOT = sd, root
    return root


def _engine_kwargs(spec):
    kw = {"label": spec["label"]}
    fp = {"etf": ur._etf_hist_md5, "kelly": ur._kelly_parts_md5}.get(spec["fp"])
    if fp:
        kw["fingerprint"] = fp
    if spec["excl"] == "large":
        kw["exclude_fn"] = lambda f: not ur._is_data_large_file(f)
    elif spec["excl"] == "all":
        kw["exclude_fn"] = ur._is_all_data_excluded
    return kw


def _local_dir(spec):
    return (ur.STATIC_DIR / spec["local_rel"]) if spec["local_rel"] else ur.STATIC_DIR


def _sends(calls):
    return [c for c in calls if c[0] == "send"]


# ============================ [A] 13 通道失败路径端到端 ============================

@pytest.mark.parametrize("spec", _A_CHANNELS, ids=[s["label"] for s in _A_CHANNELS])
def test_a_failure_alerts(stub_env, spec):
    root = _mk_tree(spec)
    stub_env.trees.append(root)
    calls = stub_env.calls

    rc = None
    try:
        getattr(ur, spec["cmd"])()
    except SystemExit as e:
        rc = e.code
    assert rc == 1, f"[A] {spec['label']} 失败 exit 1(实得 {rc})"

    sends = _sends(calls)
    assert len(sends) == 1, f"[A] {spec['label']} 恰发 1 条告警(实得 {len(sends)})"
    subj, body, kw = sends[0][1], sends[0][2], sends[0][3]
    assert spec["label"] in subj and "/" in subj, f"[A] 标题含通道+计数: {subj!r}"
    assert kw.get("severe") is True, f"[A] {spec['label']} severe=True"
    assert spec["cmd_name"] in body, f"[A] body 含补传命令 {spec['cmd_name']}"
    assert spec["prefix"] in body, f"[A] body 含 R2 前缀 {spec['prefix']}"
    assert _NOTE_FRAG[spec["label"]] in body, f"[A] 「含义」括注 = 本通道 note"
    assert "fund_score 为场外基金评分" not in body, f"[A] 未误挂 fund_score 默认括注"
    dk = [c for c in calls if c[0] == "check_dedup"]
    assert any(c[1] == f"r2_channel_upload_fail_{spec['label']}" and c[2] == 21600 for c in dk), \
        f"[A] 去重键 = r2_channel_upload_fail_{spec['label']} / 21600(实得 {dk})"
    assert any(c[0] == "update_dedup" and c[1] == f"r2_channel_upload_fail_{spec['label']}"
               for c in calls), f"[A] 发送后落去重"
    assert stub_env.put_calls, f"[A] 引擎真跑到上传步骤(打桩零真实 PUT)"
    assert not stub_env.trap, f"[E] 真实 notify.send 全程零触达"


# ============================ [B] data_files 命令级单点 ============================

def test_b_data_files_failure_alerts(stub_env):
    root = Path(tempfile.mkdtemp(prefix="t212-datafiles-"))
    stub_env.trees.append(root)
    sd = root / "static-site"
    (sd / "data").mkdir(parents=True)
    (sd / "data" / "schedule_stats.json").write_text('{"a": 1}', encoding="utf-8")
    ur.STATIC_DIR, ur.ROOT = sd, root
    calls = stub_env.calls

    from upload_r2 import cmd_upload_data_files
    rc = None
    try:
        cmd_upload_data_files(["schedule_stats.json"])
    except SystemExit as e:
        rc = e.code
    assert rc == 1, f"[B] data_files 失败 exit 1(实得 {rc})"
    sends = _sends(calls)
    assert len(sends) == 1, f"[B] data_files 恰发 1 条告警(实得 {len(sends)})"
    subj, body, kw = sends[0][1], sends[0][2], sends[0][3]
    assert "data-files" in subj, f"[B] 标题含 data-files: {subj!r}"
    assert kw.get("severe") is True, "[B] severe=True"
    assert "upload-data-files" in body, "[B] body 含补传命令 upload-data-files"
    dk = [c for c in calls if c[0] == "check_dedup"]
    assert any(c[1] == "r2_channel_upload_fail_data-files" and c[2] == 21600 for c in dk), \
        f"[B] 去重键 = r2_channel_upload_fail_data-files(实得 {dk})"
    assert not stub_env.trap, "[E] 真实 notify.send 全程零触达"


def test_b2_data_files_pre_change_counterfactual(stub_env):
    """[D] 反事实对照: 屏蔽新增的 notify 调用 ⇒ 复现改前形态(exit 1 + 零外发)。"""
    root = Path(tempfile.mkdtemp(prefix="t212-datafiles-cf-"))
    stub_env.trees.append(root)
    sd = root / "static-site"
    (sd / "data").mkdir(parents=True)
    (sd / "data" / "schedule_stats.json").write_text('{"a": 1}', encoding="utf-8")
    ur.STATIC_DIR, ur.ROOT = sd, root
    saved = ur._notify_channel_upload_fail
    ur._notify_channel_upload_fail = lambda *a, **k: None  # 模拟改前(无该调用)
    try:
        rc = None
        try:
            ur.cmd_upload_data_files(["schedule_stats.json"])
        except SystemExit as e:
            rc = e.code
    finally:
        ur._notify_channel_upload_fail = saved
    assert rc == 1, "[D] 无 notify 时 data_files 失败仍 exit 1(改前形态)"
    assert not _sends(stub_env.calls), "[D] 无 notify 调用时零外发(= 改前静默)"
    assert not stub_env.trap, "[E] 真实 notify.send 全程零触达"


# ============================ [C] 成功路径不误报 ============================

@pytest.mark.parametrize("spec", _A_CHANNELS, ids=[s["label"] for s in _A_CHANNELS])
def test_c_success_no_alert(stub_env, spec):
    root = _mk_tree(spec)
    stub_env.trees.append(root)
    (_, put_calls) = _install_engine_stubs(fail=False)  # 覆盖为「成功」桩
    calls = stub_env.calls
    rc = None
    try:
        getattr(ur, spec["cmd"])()
    except SystemExit as e:
        rc = e.code
    assert rc is None, f"[C] {spec['label']} 成功不 exit(实得 rc={rc})"
    assert not _sends(calls), f"[C] {spec['label']} 成功零告警(不制造噪音)"
    assert not stub_env.trap, f"[E] 真实 notify.send 全程零触达"


# ============================ [D] 改前对照: 13 通道不接 on_fail 时静默 ============================

@pytest.mark.parametrize("spec", _A_CHANNELS, ids=[s["label"] for s in _A_CHANNELS])
def test_d_pre_change_engine_silent(stub_env, spec):
    """不传 on_fail 的引擎失败 = 改前该通道行为: exit 1 且零告警(证明病灶真存在)。"""
    root = _mk_tree(spec)
    stub_env.trees.append(root)
    calls = stub_env.calls
    rc = None
    try:
        ur._incremental_upload(_local_dir(spec), spec["patterns"], spec["prefix"],
                               spec["state"], **_engine_kwargs(spec))
    except SystemExit as e:
        rc = e.code
    assert rc == 1, f"[D] {spec['label']} 无 on_fail 失败仍 exit 1(实得 {rc})"
    assert not _sends(calls), f"[D] {spec['label']} 无 on_fail 零告警(= 改前静默)"
    assert not stub_env.trap, f"[E] 真实 notify.send 全程零触达"


def test_d2_default_none_and_scope_locked():
    """[D] on_fail 默认 None(其余不接的通道零行为变化)+ 本批挂点数量锁定(不多不少)。"""
    assert inspect.signature(ur._incremental_upload).parameters["on_fail"].default is None, \
        "[D] _incremental_upload.on_fail 默认仍为 None"
    src = (SCRIPTS / "upload_r2.py").read_text(encoding="utf-8")
    assert src.count("on_fail=_channel_on_fail(") == len(_A_CHANNELS) == 13, \
        "[D] A 类挂点恰 13 条(改范围须同步本表)"
    # data_files 挂点: 实参对恰 1 处
    assert src.count('"data-files", "upload-data-files"') == 1, "[D] data_files 告警挂点恰 1 处"


# ============================ [E] 静态对照: 改前源码无本批接线 ============================

def test_e_pre_change_source_static():
    """改前(HEAD 版, 仅未提交态可得)无 _channel_on_fail / data_files 失败分支无 notify。

    = 病灶真存在的静态证据; 且反向机检: 改前 13 通道 on_fail 挂点为 0(那时确实静默)。
    CI(改动已提交, HEAD==工作区)自动 skip, 不误杀。
    """
    repo = SCRIPTS.parent
    try:
        r = subprocess.run(["git", "show", "HEAD:scripts/upload_r2.py"],
                           cwd=repo, capture_output=True, text=True, timeout=20)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"git 不可用: {e}")
    if r.returncode != 0 or not r.stdout:
        pytest.skip("无法取 HEAD 版 upload_r2.py(CI 浅克隆等)")
    head_src = r.stdout
    cur_src = (SCRIPTS / "upload_r2.py").read_text(encoding="utf-8")
    if head_src == cur_src:
        pytest.skip("已提交态(HEAD==工作区): 改前版不可得, 跳过静态对照")
    assert head_src.count("_channel_on_fail") == 0, "改前版不应有 _channel_on_fail(病灶证据)"
    assert head_src.count("on_fail=_etf_score_on_fail") == 1, "改前版仅 #204 etf-score 一处挂点"
    seg = head_src.split("def cmd_upload_data_files", 1)[1].split("\ndef ", 1)[0]
    assert "_notify_channel_upload_fail" not in seg, "改前版 data_files 失败分支无 notify(病灶证据)"