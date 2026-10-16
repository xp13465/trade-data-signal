# -*- coding: utf-8 -*-
"""#252 「冻结表孤儿买事件 → 定向补账登记表」纯函数 pytest 套(2026-10-16 A1 包)。

【目的】锁死 #252 A1 定向补账机制的三件事, 防日后重构静默改变入账面/告警面:
  ① 登记表读取 fail-safe(缺失/损坏 ⇒ 空集 = 改动前现行为, 绝不静默造账);
  ② 定向补账护栏(只补登记键 / 只补冻结表仍在的键 / 只补现值表整行仍缺失的真孤儿 = 不重复计数);
  ③ 告警降噪拆分(已登记的不再重复报, 未登记的新孤儿照常报 = 判别维度保留)。
另锁登记表 JSON 本体格式(committed 文件)与生成器 build_registry 的输出格式一致(单一格式来源)。

【背景】signal_daily 每日全表 DELETE+重算, 上游 index_daily 整段重写后历史买行消失 ⇒
  冻结表里 frozen_at 齐全的事件既不成账也不报孤儿。止血包 = 登记表 + 引擎读侧补账(不改 signal_daily、
  不翻 T2 全局 union 默认)。台账: docs/ops/252-freeze-orphan-backfill-20261016.md。

【方法口径】固定输入→断言输出(纯函数, 无外部数据; 临时 sqlite 仅本套自建自删)。
  告警路径**不实跑**(不调 notify.py; 只测拆分纯函数) —— 自测绝不许打出真告警(§18 L48)。
【依赖】import scripts/signal_kelly_backtest → 需 yaml(CI ⑧ 已装; 缺则 pytest.skip, 不 FAIL)。
【输入依赖】config/signal_kelly_freeze_orphan_backfill.json(committed; 缺则相关用例 skip)。
【输出】pytest PASS/FAIL。CI 挂载: .github/workflows/ci.yml ⑧(pytest -q scripts/tests/)。
【复现命令】cd <repo> && python3 -m pytest -q scripts/tests/test_252_freeze_orphan_backfill.py
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

pytest.importorskip("yaml", reason="CI 需 pip install pyyaml 才能 import signal_kelly_backtest")

ROOT = Path(__file__).absolute().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:
    import signal_kelly_backtest as sk
    import trades_orphan_backfill as tobf
except Exception as _e:  # pragma: no cover - 环境缺依赖时降级 skip
    pytest.skip(f"依赖不可用: {_e}", allow_module_level=True)

REGISTRY_FILE = ROOT / "config" / "signal_kelly_freeze_orphan_backfill.json"


# ────────────────────────────────────────────────────────────────────────────
# ① 登记表读取 fail-safe
# ────────────────────────────────────────────────────────────────────────────
def test_registry_missing_file_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(sk, "FREEZE_BACKFILL_REGISTRY_PATH", str(tmp_path / "nope.json"))
    assert sk._load_freeze_backfill_registry() == set()


def test_registry_corrupt_file_returns_empty(monkeypatch, tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(sk, "FREEZE_BACKFILL_REGISTRY_PATH", str(p))
    assert sk._load_freeze_backfill_registry() == set()


def test_registry_wrong_shape_returns_empty(monkeypatch, tmp_path):
    p = tmp_path / "shape.json"
    p.write_text(json.dumps({"keys": "20261012|csi_x|buy"}), encoding="utf-8")  # 不是 list
    monkeypatch.setattr(sk, "FREEZE_BACKFILL_REGISTRY_PATH", str(p))
    assert sk._load_freeze_backfill_registry() == set()


def test_registry_ok(monkeypatch, tmp_path):
    p = tmp_path / "ok.json"
    p.write_text(json.dumps({"keys": ["20261012|csi_x|buy", "20261014|sz_div|buy_aux"]}),
                 encoding="utf-8")
    monkeypatch.setattr(sk, "FREEZE_BACKFILL_REGISTRY_PATH", str(p))
    assert sk._load_freeze_backfill_registry() == {"20261012|csi_x|buy", "20261014|sz_div|buy_aux"}


# ────────────────────────────────────────────────────────────────────────────
# ② 定向补账护栏(核心: 不越界、不重复计数)
# ────────────────────────────────────────────────────────────────────────────
FREEZE = {
    "20261012|csi_orphan|buy": {"code": "159999", "frozen_at": "2026-10-12 16:38"},
    "20261014|sz_orphan|buy_aux": {"code": "159999", "frozen_at": "2026-10-14 16:38"},
    "20261015|sh_drifted|buy": {"code": "159999", "frozen_at": "2026-10-15 16:38"},   # 行还在(漂移)
    "20261015|sh_other|buy": {"code": "159999", "frozen_at": "2026-10-15 16:38"},     # 未登记
    "20261015|sh_sell|sell": {"code": "159999", "frozen_at": "2026-10-15 16:38"},     # 非买类
}
PRESENT_DI = {("20261015", "sh_drifted"), ("20261015", "sh_other")}   # 这两行仍在现值表里


def test_union_only_registered_and_true_orphan():
    """登记键 2 条真孤儿应补入; 登记但行还在(漂移)的不补; 未登记的不补; 非买类不补。"""
    rows = [("20261015", "sh_other", "buy")]
    out = sk._union_freeze_backfill_rows(
        rows, FREEZE, {"20261012|csi_orphan|buy", "20261015|sh_drifted|buy"}, PRESENT_DI)
    got = {tuple(r[:3]) for r in out}
    assert got == {("20261015", "sh_other", "buy"), ("20261012", "csi_orphan", "buy")}


def test_union_sorted_and_dedup():
    """补入后保持 (date,index,signal) 稳定排序; 已在 buy_rows 里的不重复加。"""
    rows = [("20261020", "zz", "buy"), ("20261012", "csi_orphan", "buy")]
    out = sk._union_freeze_backfill_rows(
        rows, FREEZE, {"20261012|csi_orphan|buy", "20261014|sz_orphan|buy_aux"}, PRESENT_DI)
    assert [tuple(r[:3]) for r in out] == [
        ("20261012", "csi_orphan", "buy"),
        ("20261014", "sz_orphan", "buy_aux"),
        ("20261020", "zz", "buy"),
    ]


def test_union_empty_registry_is_noop():
    rows = [("20261015", "sh_other", "buy")]
    assert sk._union_freeze_backfill_rows(rows, FREEZE, set(), PRESENT_DI) is rows


def test_union_key_not_in_freeze_ignored():
    """登记表里有、但冻结表已无此键(§25 冻结表是单一事实源) ⇒ 不补, 不报错。"""
    rows = []
    out = sk._union_freeze_backfill_rows(rows, FREEZE, {"20260101|ghost|buy"}, set())
    assert out == []


# ────────────────────────────────────────────────────────────────────────────
# ③ 告警降噪拆分(已登记不重报 / 未登记照报)
# ────────────────────────────────────────────────────────────────────────────
def test_split_registered_orphans():
    orphans = [("20261012", "csi_orphan", "buy"), ("20261015", "sh_new", "buy")]
    unreg, handled = sk._split_registered_orphans(orphans, {"20261012|csi_orphan|buy"})
    assert unreg == [("20261015", "sh_new", "buy")]
    assert handled == 1


def test_split_all_registered_means_no_alert_subject():
    """全部已登记 ⇒ 未登记集为空(告警函数据此直接返回, 不产生通知)。"""
    orphans = [("20261012", "csi_orphan", "buy")]
    unreg, handled = sk._split_registered_orphans(orphans, {"20261012|csi_orphan|buy"})
    assert unreg == [] and handled == 1


def test_alert_orphans_empty_is_silent(capsys):
    """未登记空集 + 全登记 ⇒ 不调用 notify(只打印一行)。告警路径绝不在自测里实跑。"""
    sk._alert_freeze_orphans([], handled_n=0)
    sk._alert_freeze_orphans([], handled_n=3)
    err = capsys.readouterr().err
    assert "已处置" in err or err == ""


# ────────────────────────────────────────────────────────────────────────────
# ④ 生成器(build_registry)+ 候选清单纯函数(临时 sqlite, 自建自删)
# ────────────────────────────────────────────────────────────────────────────
def test_generator_registry_from_cloud_shape():
    """用线上实测形状的候选结果 dict 走生成器: keys = 候选 + 跳过(真孤儿全收), 稳定排序。"""
    result = {
        "candidates": [{"date": "20261012", "index_id": "csi_000330", "signal": "buy"}],
        "skipped_no_price": [{"date": "20261016", "index_id": "sz_div", "signal": "buy"}],
        "stats": {"orphan_events": 2, "candidates": 1, "no_price": 1},
    }
    reg = tobf.build_registry(result, generated_at="2026-10-16 23:59:00")
    assert reg["keys"] == ["20261012|csi_000330|buy", "20261016|sz_div|buy"]
    assert reg["counts"]["orphan_events"] == 2
    assert reg["generated_at"] == "2026-10-16 23:59:00"


def _mk_dbs(tmp_path):
    db = tmp_path / "sent.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE signal_daily (date TEXT, index_id TEXT, signal TEXT)")
    c.execute("INSERT INTO signal_daily VALUES ('20261012','csi_kept','sell')")  # 该 (date,index) 行还在
    c.commit()
    c.close()
    etf = tmp_path / "etf.db"
    c = sqlite3.connect(etf)
    c.execute("CREATE TABLE etf_daily (etf_code TEXT, date TEXT, open REAL)")
    c.execute("INSERT INTO etf_daily VALUES ('159999','20261013',1.23)")        # 信号日后首个有行情日
    c.execute("INSERT INTO etf_daily VALUES ('159999','20261012',9.99)")        # 信号日当天不许用(防前视)
    c.commit()
    c.close()
    return str(db), str(etf)


def test_build_candidates_antilookahead_and_no_price(tmp_path):
    db, etf = _mk_dbs(tmp_path)
    freeze = {
        "20261012|csi_orphan|buy": {"code": "159999", "name": "测试ETF", "frozen_at": "2026-10-12 16:38"},
        "20261012|csi_kept|buy": {"code": "159999", "frozen_at": "2026-10-12 16:38"},     # 行还在 → 非孤儿
        "20261020|csi_nodata|buy": {"code": "159999", "frozen_at": "2026-10-20 16:38"},   # 无次日行情
    }
    present_di = tobf.load_present_di(db)
    res = tobf.build_candidates(freeze, present_di, etf)
    assert res["stats"]["orphan_events"] == 2
    assert res["stats"]["candidates"] == 1
    assert res["stats"]["no_price"] == 1
    cand = res["candidates"][0]
    assert (cand["date"], cand["index_id"], cand["signal"]) == ("20261012", "csi_orphan", "buy")
    assert cand["buy_date"] == "20261013" and cand["buy_price"] == 1.23   # 次日 open, 非当日 9.99
    reg = tobf.build_registry(res, generated_at="fixed")
    assert reg["keys"] == ["20261012|csi_orphan|buy", "20261020|csi_nodata|buy"]


# ────────────────────────────────────────────────────────────────────────────
# ⑤ committed 登记表本体格式(防手改漂移)
# ────────────────────────────────────────────────────────────────────────────
def test_committed_registry_format():
    if not REGISTRY_FILE.exists():
        pytest.skip("committed 登记表未生成")
    data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    keys = data["keys"]
    assert isinstance(keys, list) and keys, "登记表不得为空(为空等于没登记, 应删文件回退)"
    assert keys == sorted(set(keys)), "keys 必须去重且稳定排序(生成器契约)"
    for k in keys:
        d, iid, sig = k.split("|")
        assert len(d) == 8 and d.isdigit(), f"日期格式非法: {k}"
        assert sig in sk.BUY_SIGNALS, f"非买类键不得进登记表: {k}"
        assert iid, f"index_id 为空: {k}"
    assert data["counts"]["orphan_events"] == len(keys), "counts 与 keys 数必须一致"
    assert "freeze" in data.get("meta", {}), "meta 须留生成时冻结表路径(可反查)"