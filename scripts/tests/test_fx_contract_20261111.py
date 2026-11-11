"""HC18 real functions, temporary SQLite, transport and notifications forbidden."""
import ast
import copy
import json
import socket
import sqlite3
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import fx_contract as fx

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 11, 10, 0, tzinfo=fx.TZ)


def extract(path, name, namespace=None):
    tree = ast.parse((ROOT / path).read_text())
    node = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    node.decorator_list = []
    ns = dict(namespace or {})
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), ns)
    return ns[name]


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("REPO", str(tmp_path))
    monkeypatch.setenv("GIT_REPO", str(tmp_path))
    monkeypatch.setenv("MAIN_REPO", str(tmp_path))
    def denied(*args, **kwargs):
        raise AssertionError("external transport forbidden")
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(subprocess, "run", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)
    with pytest.raises(AssertionError, match="transport forbidden"):
        subprocess.run(["not-permitted"])


@pytest.fixture
def db(tmp_path):
    c = sqlite3.connect(tmp_path / "fx.db")
    c.row_factory = sqlite3.Row
    c.executescript("""
      CREATE TABLE daily_metric(date TEXT,metric_id TEXT,value REAL,source TEXT,updated_at TEXT,PRIMARY KEY(date,metric_id));
      CREATE TABLE signal_daily(date TEXT,index_id TEXT,signal TEXT,reason TEXT,PRIMARY KEY(date,index_id,signal));
      CREATE TABLE score_daily(date TEXT,score_id TEXT,value REAL,is_freeze INT,is_overheat INT,components TEXT,updated_at TEXT,PRIMARY KEY(date,score_id));
    """)
    yield c
    c.close()


def quote(**changes):
    fields = ["10:00:00", "7.15", "7.16", "7.1", "62", "7", "7.3", "7", "7.2", "离岸人民币（香港）", "123", "456", "", "", "", "", "", "2026-11-11"]
    q = fx.parse_quote('var hq_str_fx_susdcnh="' + ','.join(fields) + '";')
    q.update(changes)
    return q


def history(n=120):
    days = []
    day = NOW.date() - timedelta(days=1)
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    wire = "|".join(f"{d},7.1,7.0,7.3,7.2" for d in reversed(days))
    return fx.parse_day_candidate("fx_history(" + json.dumps(wire) + ");", source_url=fx.DAY_URL, fetched_at=NOW)["rows"]


def test_field_contract_not_numeric_similarity():
    q = quote()
    assert q["price"] == 7.2 and q["pre_close"] == 7.1
    assert q["pct_change"] == pytest.approx((7.2 / 7.1 - 1) * 100)
    assert fx.parse_quote('var hq_str_fx_susdcny="' + ','.join(['7.2']*18) + '";') is None
    assert fx.parse_quote('var hq_str_fx_susdcnh_extra="' + ','.join(['7.2']*18) + '";') is None
    assert fx.validate_quote(q, NOW) == "20261111"


@pytest.mark.parametrize("change", [
    {"instrument_id": "USD/CNY"}, {"base_amount": 100}, {"quote_currency": "CNY"},
    {"source_id": None}, {"contract_version": "old"}, {"price_type": "bid"},
    {"code": "fx_susdcny"}, {"name": "在岸人民币"}, {"source_timezone": "UTC"},
    {"datetime": "20261110"}, {"as_of": "2026-11-10T10:00:00+08:00"},
    {"as_of": "2026-11-11T09:44:59+08:00"}, {"as_of": "2026-11-11T10:00:01+08:00"},
    {"as_of": "2026-11-11T10:00:00"}, {"price": float("nan")}, {"price": float("inf")},
    {"price": 0}, {"price": -1}, {"price": True},
])
def test_rejected_contracts_do_not_write(db, change):
    with pytest.raises((ValueError, TypeError, KeyError)):
        fx.store_quote(db, quote(**change), NOW)
    assert db.execute("SELECT COUNT(*) FROM daily_metric").fetchone()[0] == 0


def test_boundary_idempotent_legacy_and_real_jump(db):
    db.execute("INSERT INTO daily_metric VALUES('20261111','usdcnh',700,'akshare','old')")
    assert fx.store_quote(db, quote(as_of="2026-11-11T09:45:00+08:00"), NOW) == 1
    assert fx.store_quote(db, quote(price=14.4), NOW) == 1
    assert fx.store_quote(db, quote(price=14.4), NOW) == 0
    assert fx.store_quote(db, quote(as_of="2026-11-11T09:59:59+08:00"), NOW) == 0
    assert db.execute("SELECT value FROM daily_metric WHERE metric_id='usdcnh'").fetchone()[0] == 700
    assert db.execute("SELECT value FROM daily_metric WHERE metric_id=?", (fx.QUOTE_METRIC,)).fetchone()[0] == 14.4
    assert fx.availability()["active"] is False


@pytest.mark.parametrize("n", [0, 19, 20, 59, 60, 89, 90, 119, 120])
def test_staging_warmup_does_not_activate(db, n):
    rows = history(n) if n else []
    result = fx.stage_day_history(db, rows)
    for window in (20,60,90,120):
        assert result["windows"][str(window)] == (n >= window)
    assert not result["active"]
    assert fx.stage_day_history(db, rows)["count"] == n
    assert db.execute("SELECT COUNT(*) FROM daily_metric WHERE metric_id='usdcnh'").fetchone()[0] == 0


def test_batch_conflict_is_atomic(db):
    rows = history(2)
    fx.stage_day_history(db, rows[1:])
    bad = copy.deepcopy(rows)
    bad[1]["value"] = 8
    with pytest.raises(ValueError, match="conflict"):
        fx.stage_day_history(db, bad)
    assert fx.candidate_status(db)["count"] == 1


@pytest.mark.parametrize("change", [{"base_amount":100}, {"source_id":None}, {"price_type":"provider_latest"}, {"instrument_id":"USD/CNY"}, {"payload_sha256":""}, {"as_of":"2026-11-11"}, {"source_url":"https://example.com"}])
def test_import_negative_controls(db, change):
    row = history(1)[0]
    row.update(change)
    with pytest.raises((ValueError, KeyError)):
        fx.stage_day_history(db, [row])
    assert fx.candidate_status(db)["count"] == 0


def test_old_signals_consumption_and_cache(db):
    db.executemany("INSERT INTO signal_daily VALUES(?,?,?,?)", [
        ("20261111","g.usdcnh","sell","old"), ("20261111","sh","buy","ok"),
        ("20261111","s.cross_market","sell","old"), ("20261111","s.fear_greed","buy","old")])
    fn = extract("app/queries.py", "signals", {"fx_filter_signals":fx.filter_signals})
    for cache in (None, {}, {("signals",None): [dict(r) for r in db.execute("SELECT * FROM signal_daily")]}):
        assert [r["index_id"] for r in fn(db,None,"20261101","20261130",cache=cache)] == ["sh"]
    assert db.execute("SELECT COUNT(*) FROM signal_daily").fetchone()[0] == 4
    assert not fx.filter_signals([dict(index_id="s.cross_market",reason="[fx-excluded-v1] x")])


def test_old_metric_and_score_query_guard(db):
    db.execute("INSERT INTO daily_metric VALUES('20261111','usdcnh',700,'akshare','old')")
    metric = extract("app/queries.py", "metric_series")
    assert metric(db,"usdcnh","20260101","20261231",cache={("metric","usdcnh"):[dict(date="20261111",value=700)]}) == []
    db.executemany("INSERT INTO score_daily VALUES(?,?,?,0,0,?,NULL)", [
        ("20261110","cross_market",30,"{}"),
        ("20261111","cross_market",40,json.dumps({"_fx_contract":fx.SCORE_VERSION,"_fx_available":True}))])
    score = extract("app/queries.py", "score_series", {"fx_guard_score":fx.guard_score})
    for cache in (None, {}):
        rows = score(db,"cross_market","20260101","20261231",cache=cache)
        assert rows[0]["value"] is None and rows[0]["is_freeze"] is None
        assert rows[1]["value"] is None  # row flags are not verified activation
    db.execute("INSERT INTO score_daily VALUES('20261111','a_sentiment',0,1,0,'{}',NULL)")
    assert score(db,"a_sentiment","20260101","20261231")[0]["value"] == 0
    assert db.execute("SELECT value FROM score_daily WHERE date='20261110'").fetchone()[0] == 30


def test_generic_writers_block_all_fx_before_db():
    for name,args in [("upsert_metric",("20261111","usdcnh",7)), ("upsert_metrics_many",("usdcnh",[("20261111",7)]))]:
        fn = extract("app/collector/runner.py",name)
        with pytest.raises(ValueError,match="dedicated"):
            fn(*args)


def test_notification_reader_no_send(db, tmp_path):
    path = tmp_path / "fx.db"
    db.executemany("INSERT INTO signal_daily VALUES(?,?,?,?)", [("20261111","g.usdcnh","sell","old"),("20261111","sh","buy","ok")]);db.commit()
    fn=extract("scripts/check_signals.py","query_signals",{"DB_PATH":path,"sqlite3":sqlite3,"get_conn":lambda:sqlite3.connect(path)})
    assert [r["index_id"] for r in fn("20261111")] == ["sh"]


def test_actual_normalize_and_alert_loaders(db,tmp_path,monkeypatch):
    import pandas as pd
    path=tmp_path/"fx.db"
    db.executemany("INSERT INTO score_daily VALUES(?,?,?,0,0,?,NULL)",[("20261110","cross_market",12,"{}"),("20261111","cross_market",23,json.dumps({"_fx_contract":fx.SCORE_VERSION,"_fx_available":True}))]);db.commit()
    def conn():
        c=sqlite3.connect(path);c.row_factory=sqlite3.Row;return c
    for name in ("load_metric_value","load_metric_series"):
        fn=extract("app/compute/normalize.py",name,{"pd":pd,"get_conn":lambda:pytest.fail("must not read legacy")})
        assert fn("usdcnh").empty
    fn=extract("app/compute/normalize.py","load_score_value",{"pd":pd,"get_conn":conn,"__package__":"app.compute"})
    assert fn("cross_market").empty
    fn=extract("app/alert_score.py","load_score",{"pd":pd,"_conn_sent":conn,"DEPENDENT_SCORES":fx.DEPENDENT_SCORES,"guard_score":fx.guard_score})
    assert fn("cross_market").empty


def test_fear_greed_uses_available_valid_scores_only(db,tmp_path):
    import pandas as pd
    path=tmp_path/"fx.db"
    db.executemany("INSERT INTO score_daily VALUES('20261111',?,?,0,0,'{}',NULL)",[("cross_market",100),("a_sentiment",20),("sentiment_sz50",20),("sentiment_hs300",20),("sentiment_csi500",20)]);db.commit()
    def conn():
        c=sqlite3.connect(path);c.row_factory=sqlite3.Row;return c
    fn=extract("app/compute/fear_greed.py","compute_fear_greed",{"pd":pd,"datetime":datetime,"json":json,"get_conn":conn,"INPUT_SCORES":["cross_market","a_sentiment","sentiment_sz50","sentiment_hs300","sentiment_csi500"],"OUTPUT_SCORE_ID":"fear_greed","get_label":lambda v:"极度恐惧","__package__":"app.compute"})
    assert fn()==1
    row=db.execute("SELECT * FROM score_daily WHERE score_id='fear_greed'").fetchone()
    assert row["value"]==20
    assert json.loads(row["components"])["available_scores"]==4
    assert fx.guard_score(row)["value"] is None  # 4 remaining dimensions must not look complete


def test_import_cli_refuses_application_db(db, tmp_path):
    from app.collector.fx_history import import_snapshot
    snapshot=tmp_path/"wire.txt"
    snapshot.write_text('fx_history("2026-11-10,7.1,7.0,7.3,7.2");')
    with pytest.raises(ValueError,match="non-staging"):
        import_snapshot(snapshot,tmp_path/"fx.db",source_url=fx.DAY_URL,fetched_at=NOW)
    out=tmp_path/"candidate.sqlite"
    assert import_snapshot(snapshot,out,source_url=fx.DAY_URL,fetched_at=NOW)["count"]==1
    assert import_snapshot(snapshot,out,source_url=fx.DAY_URL,fetched_at=NOW)["count"]==1
    link=tmp_path/"link.sqlite";link.symlink_to(out)
    with pytest.raises(ValueError,match="symlink"):
        import_snapshot(snapshot,link,source_url=fx.DAY_URL,fetched_at=NOW)


def test_compute_respects_enabled_and_fx_guard():
    # Execute the real global-metric loop with only its numerical callee replaced.
    tree=ast.parse((ROOT/"app/compute/signals.py").read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="compute")
    begin=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="enabled_metrics" for t in n.targets))
    chunk=ast.Module(body=fn.body[begin:begin+2],type_ignores=[])
    import pandas as pd
    loaded=[];computed=[]
    ns=dict(cfg={"metrics":[{"id":"usdcnh","enabled":True},{"id":"gold","enabled":True},{"id":"oil","enabled":False}]},GLOBAL_METRIC_IDS=["usdcnh","gold","oil"],capture_loaded=lambda k,v:v,load_metric_value=lambda mid:(loaded.append(mid) or pd.Series({"20261111":1.0})),_SKIP_BUY_IDS=set(),_SKIP_SELL_IDS=set(),sell_no_trend_filters={},buy_aux_filters={},signals=[],_compute_value_signals=lambda *a,**k:(computed.append(a[1]) or []))
    exec(compile(chunk,"global_metric_loop","exec"),ns)
    assert loaded==["gold"] and computed==["g.gold"]


def test_preserve_old_fx_signal_on_real_store(db,tmp_path,monkeypatch):
    import types,sys
    path=tmp_path/"fx.db"
    db.execute("INSERT INTO signal_daily VALUES('20261110','g.usdcnh','sell','old')");db.commit()
    def conn():
        c=sqlite3.connect(path);c.row_factory=sqlite3.Row;return c
    audit=types.ModuleType("app.history_audit")
    audit.today_ymd=lambda:"20261111";audit.snapshot_signal_daily_history=lambda *a:set();audit.audit_signal_daily_store=lambda *a:None
    monkeypatch.setitem(sys.modules,"app.history_audit",audit)
    tree=ast.parse((ROOT/"app/compute/signals.py").read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="store");fn.decorator_list=[]
    noop=lambda *a,**kw:None
    ns=dict(__package__="app.compute",get_conn=conn,capture_loaded=noop,capture_event=noop,capture_signal_visibility=noop,capture_connection=noop)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),"store","exec"),ns)
    ns["store"]([("20261110","g.usdcnh","sell","replacement"),("20261111","sh","buy","ok")])
    assert db.execute("SELECT reason FROM signal_daily WHERE index_id='g.usdcnh'").fetchone()[0]=="old"
    assert db.execute("SELECT COUNT(*) FROM signal_daily").fetchone()[0]==2


def test_real_cross_compute_store_and_global_export_chain(db,tmp_path):
    import numpy as np
    import pandas as pd
    path=tmp_path/"fx.db"
    days=[r["date"] for r in history(120)]
    db.executemany("INSERT INTO daily_metric VALUES(?,?,?,?,NULL)",[(d,mid,float(i%30+1),"fixture") for i,d in enumerate(days) for mid in ("gold","oil","brent")]+[(d,"usdcnh",700 if i<119 else 6.67,"akshare") for i,d in enumerate(days)])
    db.execute("INSERT INTO signal_daily VALUES(?,?,?,?)",(days[-1],"g.usdcnh","sell","old polluted sell"))
    db.execute("INSERT INTO score_daily VALUES(?,?,7,1,0,'{}','original')",(days[-1],"cross_market"));db.commit()
    def conn():
        c=sqlite3.connect(path);c.row_factory=sqlite3.Row;return c
    cfg={"metrics":[dict(id=m,type="simple",enabled=True,group="global") for m in ("gold","oil","brent","usdcnh")],"indices":[]}
    load=extract("app/compute/normalize.py","load_metric_series",{"pd":pd,"get_conn":conn})
    rank=extract("app/compute/normalize.py","rolling_percentile",{"pd":pd,"_WINDOW":120,"_MIN_PERIODS":10})
    normalize=extract("app/compute/normalize.py","normalized",{"pd":pd,"load_metric_series":load,"rolling_percentile":rank,"directions":lambda:{},"_WINDOW":120})
    compute=extract("app/compute/cross.py","compute",{"pd":pd,"np":np,"load_config":lambda:cfg,"normalized":normalize,"GROUP_LABELS":{"global":"全球"}})
    score,components=compute()
    assert score.notna().sum()>90
    store=extract("app/compute/cross.py","store",{"pd":pd,"datetime":datetime,"json":json,"get_conn":conn,"__package__":"app.compute"})
    assert store(score,components)>90
    queryscore=extract("app/queries.py","score_series",{"fx_guard_score":fx.guard_score})
    exported=queryscore(db,"cross_market",days[0],days[-1])
    assert exported and all(r["value"] is None and r["is_freeze"] is None and r["is_overheat"] is None for r in exported)
    qs=extract("app/queries.py","signals",{"fx_filter_signals":fx.filter_signals})
    qm=extract("app/queries.py","metric_series")
    st=extract("app/queries.py","stats_for")
    global_query=extract("app/queries.py","global_market",{"indices_for_market":lambda *a:[],"_enrich_etfs_since_return":lambda *a:None,"metric_series":qm,"signals":qs,"stats_for":st,"strategy_desc":lambda *a:{},"fx_availability":fx.availability})
    payload=global_query(db,cfg,days[0],days[-1],stats_all_dict={"g.usdcnh":{"sell":{"n":88,"score":50}}})
    assert payload["extras"]["usdcnh"]==[] and payload["extras_signals"]["usdcnh"]==[]
    assert payload["extras_stats"]["usdcnh"]=={} and payload["extras_availability"]["usdcnh"]["active"] is False
    # Real signal engine after the score write, using only the isolated SQLite readers.
    value_reader=extract("app/compute/normalize.py","load_metric_value",{"pd":pd,"get_conn":conn})
    score_reader=extract("app/compute/normalize.py","load_score_value",{"pd":pd,"get_conn":conn,"__package__":"app.compute"})
    pure={"pd":pd,"np":np,"_STD_SELL_IDS":{"usdcnh"}}
    for name in ("_rsi","_bollinger","_macd"):
        pure[name]=extract("app/compute/signals.py",name,pure)
    value_signals=extract("app/compute/signals.py","_compute_value_signals",pure)
    engine=extract("app/compute/signals.py","compute",dict(pure,load_config=lambda:cfg,capture_loaded=lambda k,v,**kw:v,_load_cross_score=lambda:score_reader("cross_market"),_load_buy_aux_filters=lambda c:{},_load_buy_filters=lambda c:{},_load_sell_no_trend_filters=lambda c:{},GLOBAL_METRIC_IDS=["usdcnh","gold"],SCORE_IDS=["cross_market","fear_greed"],_SKIP_BUY_IDS={"usdcnh"},_SKIP_SELL_IDS=set(),load_metric_value=value_reader,load_score_value=score_reader,_compute_value_signals=value_signals))
    calculated=engine()
    assert all(r[1] not in ("g.usdcnh","s.cross_market","s.fear_greed") for r in calculated)
    assert score_reader("cross_market").empty
    oldscore=db.execute("SELECT value,is_freeze,updated_at FROM score_daily WHERE date=? AND score_id='cross_market'",(days[-1],)).fetchone()
    assert tuple(oldscore)==(7,1,"original")
    # The actual static export adapter delegates to the real guarded query.
    import types
    export=extract("static-site/export.py","export_global",{"queries":types.SimpleNamespace(range_for=lambda r:(days[0],days[-1]),global_market=global_query),"_series_cache":{},"_get_stats":lambda:{}})
    assert json.loads(json.dumps(export(db,cfg,"all")))["extras"]["usdcnh"]==[]
    assert db.execute("SELECT COUNT(*) FROM daily_metric WHERE metric_id='usdcnh'").fetchone()[0]==120
    assert db.execute("SELECT reason FROM signal_daily WHERE index_id='g.usdcnh'").fetchone()[0]=="old polluted sell"


def test_incomplete_fx_does_not_become_healthy_alert():
    import pandas as pd
    import numpy as np
    dims=pd.DataFrame({"x":[1.0,99.0]},index=["20261110","20261111"])
    fn=extract("app/alert_score.py","compute_alert_scores",{"pd":pd,"np":np,"compute_high_dims":lambda:dims,"compute_low_dims":lambda:dims.rename(columns={"x":"y"}),"_weighted_score":lambda d,w:d.iloc[:,0],"HIGH_WEIGHTS":{},"LOW_WEIGHTS":{},"load_score":lambda name:pd.Series(dtype=float)})
    result=fn()
    assert result["high_alert"].isna().all() and result["low_alert"].isna().all()


def test_candidate_source_loss_and_large_gap(db):
    rows=history(120)
    fx.stage_day_history(db,rows[:60]+rows[-1:])
    assert fx.candidate_status(db)["windows"]["60"] is False
    row=rows[-1].copy();row.pop("source_url")
    db.execute("UPDATE daily_metric SET source=? WHERE date=?",(json.dumps(row),row["date"]))
    assert fx.candidate_status(db)["status"]=="invalid_candidate"


def test_source_day_parser_not_executable_or_unfinished():
    for payload in ('fx_history("2026-11-12,7,6,8,7");', 'fx_history("2026-11-10,7,6,8,7|2026-11-10,7,6,8,7");', 'fx_history(__import__("os"));', 'fx_history("2026-11-10,7,8,6,7");'):
        with pytest.raises((ValueError,TypeError)):
            fx.parse_day_candidate(payload,source_url=fx.DAY_URL,fetched_at=NOW)


def test_browser_notification_export_thresholds_unknown(db):
    db.executemany("INSERT INTO score_daily VALUES('20261111',?,?,1,1,'{}',NULL)",[("high_alert",99),("low_alert",99),("fear_greed",99)])
    db.executemany("INSERT INTO signal_daily VALUES('20261111',?,?,?)",[("g.usdcnh","sell","old"),("sh","buy","old,情绪分=99[过热]")])
    sigs=extract("scripts/export_notifications.py","_query_signals")(db,"20261111")
    assert len(sigs)==1 and sigs[0]["index_id"]=="sh" and "情绪分" not in sigs[0]["reason"]
    scores=extract("scripts/export_notifications.py","_query_alert_scores",{"_high_level":lambda v:"数据不足" if v is None else "高危","_low_level":lambda v:"数据不足" if v is None else "机遇","HIGH_ALERT_SHOW":72,"LOW_ALERT_SHOW":85})(db,"20261111")
    assert all(r["score"] is None and not r["triggered"] and r["level"]=="数据不足" for r in scores.values())
    fear=extract("scripts/export_notifications.py","_query_fear_greed",{"FEAR_GREED_LOW":20,"FEAR_GREED_HIGH":80})(db,"20261111")
    assert fear is None


def test_current_day_is_reported_exclusion_not_lost_history(tmp_path):
    from app.collector.fx_history import import_snapshot
    wire='fx_history("2026-11-10,7,6,8,7|2026-11-11,7,6,8,7.2");'
    parsed=fx.parse_day_candidate(wire,source_url=fx.DAY_URL,fetched_at=NOW)
    assert [r["date"] for r in parsed["rows"]]==["20261110"]
    assert parsed["excluded_dates"]==[{"date":"2026-11-11","reason":"current_day_unfinished"}]
    source=tmp_path/"wire.txt";source.write_text(wire)
    receipt=import_snapshot(source,tmp_path/"stage.db",source_url=fx.DAY_URL,fetched_at=NOW)
    assert receipt["count"]==1 and receipt["excluded_dates"]==parsed["excluded_dates"]
    for suffix in ("2026-11-12,7,6,8,7", "2026-11-11,7,8,6,7", "2026-11-11,7,6,8,7|2026-11-11,7,6,8,7"):
        with pytest.raises(ValueError):
            fx.parse_day_candidate('fx_history("2026-11-10,7,6,8,7|'+suffix+'");',source_url=fx.DAY_URL,fetched_at=NOW)


def test_real_signal_count_to_alert_score_to_json_export(db,tmp_path,monkeypatch):
    # Import real modules; patch only local paths, never algorithms or row factory.
    import importlib.util
    from app import alert_score as alerts
    path=tmp_path/"fx.db"
    monkeypatch.setattr(alerts,"resolve_db_path",lambda:path)
    monkeypatch.setattr(alerts,"_NT_DB",path)
    db.executescript("CREATE TABLE index_daily(date TEXT,index_id TEXT,close REAL); CREATE TABLE etf_signal(date TEXT,signal_type TEXT);")
    days=[r["date"] for r in history(140)]
    metric_ids=("a_volume_ratio","a_volume_signal","a_nhnl_52w","a_ma_bullish","a_ma_bearish","cn_us_spread","a_amount","a_nl_52w","a_qvix_300","a_div_yield")
    for i,d in enumerate(days):
        db.executemany("INSERT INTO index_daily VALUES(?,?,?)",[(d,iid,100+i%17+i/5) for iid in [*alerts._BROAD_INDICES,"us_spx"]])
        db.executemany("INSERT INTO daily_metric VALUES(?,?,?,?,NULL)",[(d,mid,i%19+1,"fixture") for mid in metric_ids])
        flags=json.dumps({"_fx_contract":fx.SCORE_VERSION,"_fx_available":True})
        db.executemany("INSERT INTO score_daily VALUES(?,?,?,0,0,?,NULL)",[(d,"a_sentiment",20,"{}"),(d,"cross_market",99,flags),(d,"fear_greed",99,flags)])
        db.executemany("INSERT INTO signal_daily VALUES(?,?,?,?)",[(d,"g.usdcnh","sell","old"),(d,"s.cross_market","sell","old"),(d,"sh","buy","independent")])
    db.executemany("INSERT INTO score_daily VALUES(?,?,99,1,1,?,'original')",[(days[-1],"high_alert",flags),(days[-1],"low_alert",flags)]);db.commit()
    # Uses sqlite3's real default tuple rows, unlike app.db's Row factory.
    assert alerts.load_score("cross_market").empty
    assert alerts._signal_count_daily(["sell"]).empty
    assert alerts._signal_count_daily(["buy"]).iloc[-1]==1
    hd,ld=alerts.compute_high_dims(),alerts.compute_low_dims()
    assert alerts._weighted_score(hd,alerts.HIGH_WEIGHTS).notna().any()
    assert alerts._weighted_score(ld,alerts.LOW_WEIGHTS).notna().any()
    scores=alerts.compute_alert_scores()
    assert scores.high_alert.isna().all() and scores.low_alert.isna().all()
    monkeypatch.syspath_prepend(str(ROOT/"scripts"))
    spec=importlib.util.spec_from_file_location("fx_test_export_alert",ROOT/"scripts/export_alert.py")
    exporter=importlib.util.module_from_spec(spec);spec.loader.exec_module(exporter)
    monkeypatch.setattr(exporter,"resolve_db_path",lambda:path)
    monkeypatch.setattr(exporter,"DATA_DIR",tmp_path/"output")
    monkeypatch.setattr(exporter,"ALERT_JSON",tmp_path/"output/alert.json")
    result=exporter.export_for_date(days[-1])
    payload=json.loads((tmp_path/"output/alert.json").read_text())
    assert result==payload and payload["availability"]=="unavailable"
    for side in ("high","low"):
        assert payload[side]["score"] is None and payload[side]["triggered"] is False
        assert payload[side]["level"]=="数据不足"
    assert payload["history"]==[]
    assert [tuple(r) for r in db.execute("SELECT value,is_freeze,updated_at FROM score_daily WHERE score_id IN ('high_alert','low_alert')")]==[(99,1,"original"),(99,1,"original")]


def test_stale_summary_cannot_be_reissued_or_turn_into_neutral(tmp_path):
    import logging
    old={"date":"20261111","fear_greed_value":99,"buy_count":99,"sell_count":0,"summary_short":"旧过热"}
    source=tmp_path/"summary_history.json"; source.write_text(json.dumps({"items":[old]}))
    load=extract("scripts/daily_summary_email.py","load_summary_item",{"SUMMARY_SRC":source,"json":json,"log":logging.getLogger("fx_test")})
    assert load("20261111") is None
    assert json.loads(source.read_text())["items"][0]==old
    rebuilt={**old,"fx_contract":fx.SCORE_VERSION,"fear_greed_value":None}
    source.write_text(json.dumps({"items":[rebuilt]}))
    assert load("20261111")==rebuilt
    desc=extract("scripts/gen_rss.py","_desc")
    title=extract("scripts/gen_rss.py","_title",{"_iso_date":lambda x:x})
    assert "不可用" in desc(old) and "不可用" in title(old)
    assert "99" not in desc(old)+title(old)
    brief=extract("scripts/gen_daily_brief.py","load_data",{"Path":Path,"_read_json":lambda p:old})
    with pytest.raises(ValueError,match="不能以旧分数或中性补位"):
        brief(tmp_path,tmp_path/"nonexistent.db","20261111")
    assert not (tmp_path/"nonexistent.db").exists()


def test_current_plan_and_simulation_do_not_consume_legacy_fx(db):
    for sid in ("g.usdcnh","s.cross_market","s.fear_greed"):
        fn=extract("scripts/simulate_trade.py","get_signals",{"get_conn":lambda:pytest.fail("must reject before loading data")})
        with pytest.raises(ValueError,match="已有历史归档保留"):
            fn(sid)
    db.execute("INSERT INTO signal_daily VALUES('20261111','g.usdcnh','sell','legacy')")
    fn=extract("scripts/nextday_plan_generator.py","_signal_candidates",{"capture_sql_rows":lambda *a,**k:None,"capture_event":lambda *a,**k:None})
    assert fn(db,{},"20261111",{}, {})==[]
    assert db.execute("SELECT COUNT(*) FROM signal_daily").fetchone()[0]==1
