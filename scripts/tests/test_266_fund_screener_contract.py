# -*- coding: utf-8 -*-
"""#266 一期 公募基金筛选器: 前后端参数契约 + 同步脚本口径机检（2026-10-19）。

为什么放在 pytest（而不是只做一次性自测）
  · 筛选器有 **三份参数名清单**（worker/fund_screener.js 的 RANGE_FIELDS / static-site/app.js 的
    FUND_SCREENER_* / 同步脚本产出的表列），改一处漏一处 = 静默失效（§22 代码内常量登记点一致性）。
  · 同步脚本的核心口径「**每只基金取各自最近可用评分分区**」是工作日不缩水到 2000 只的唯一保障，
    一旦被改成「取全局最新分区」= 线上静默回到旧病灶 —— 必须有回归守卫。

覆盖的断言
  ① 前后端参数名逐字对齐（node 读 worker 导出 vs 正则读 app.js 清单）;
  ② buildFilter 行为 + 注入不落 SQL（scripts/tests/fund_screener_buildfilter_check.mjs）;
  ③ 同步脚本端到端（DRY_RUN 合成库）: 每只基金最近可用分区 / 宇宙=fund_basic / 幂等 /
     worker 引用的每一列都真在表里 / 覆盖率 meta 与实表一致;
  ④ DRY_RUN 不触云（输出无 wrangler、退出码 0）。

说明: ③ 用**合成 fixture 库**跑**真实脚本**（不是复刻第二份实现, §5.4⑦）;
     派生年限列（setup_years 等）随运行日变, 故只断言非空不写死数值（L51 时敏）。
"""
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent.parent
APP_JS = ROOT / "static-site" / "app.js"
SYNC_SH = ROOT / "scripts" / "sync_fund_screener_to_d1.sh"
NODE_CHECK = ROOT / "scripts" / "tests" / "fund_screener_buildfilter_check.mjs"

# ---------- 合成 fixture 库（列名取自同步脚本实际 SELECT, 缺列会在生成期响亮失败）----------
FIXTURE_DDL = """
CREATE TABLE fund_basic (fund_code TEXT, fund_name TEXT, fund_type TEXT, fund_company TEXT,
  fund_manager TEXT, setup_date TEXT, scale REAL, management_fee REAL, custody_fee REAL,
  purchase_fee REAL, service_fee REAL, strategy TEXT, benchmark TEXT, update_date TEXT);
CREATE TABLE fund_performance (fund_code TEXT, update_date TEXT, return_1m REAL, return_3m REAL,
  return_6m REAL, return_1y REAL, return_2y REAL, return_3y REAL, return_ytd REAL,
  return_since_inception REAL);
CREATE TABLE fund_risk_indicator (fund_code TEXT, period TEXT, update_date TEXT,
  annual_volatility REAL, max_drawdown REAL);
CREATE TABLE fund_score (fund_code TEXT, score_date TEXT, composite_score REAL, star_rating INTEGER,
  score_return REAL, score_risk_adjusted REAL, score_drawdown REAL, score_stability REAL,
  score_scale REAL, score_fee REAL, sharpe REAL, sortino REAL, calmar REAL, information_ratio REAL,
  alpha REAL, manager_score REAL, m1_tenure REAL, m2_scale REAL, m3_perf_stability REAL,
  m4_drawdown REAL, m5_coherence REAL, m6_focus REAL, kelly_fraction REAL,
  half_kelly_position REAL, kelly_win_rate REAL, kelly_win_loss_ratio REAL, kelly_tier TEXT,
  market_adjustment REAL, final_suggestion REAL, score_method TEXT, data_completeness REAL,
  update_date TEXT);
CREATE TABLE fund_manager (fund_code TEXT, update_date TEXT, manager_name TEXT,
  appoint_date TEXT, tenure_days INTEGER, work_days INTEGER, managed_scale REAL, best_return REAL);
CREATE TABLE fund_rating (fund_code TEXT, rating_date TEXT, shanghai_securities INTEGER,
  cms INTEGER, jajx INTEGER, morningstar INTEGER, five_star_count INTEGER);
CREATE TABLE fund_purchase_status (fund_code TEXT, update_date TEXT, purchase_status TEXT,
  redeem_status TEXT, purchase_min REAL, daily_limit REAL);
CREATE TABLE fund_industry_alloc (fund_code TEXT, report_date TEXT, industry_name TEXT,
  weight_pct REAL);
"""

# 期望值（设计要点: 「全局最新分区」只含 F1 → 若脚本误取全局最新, F2/F3 的 score_date 会变空）
EXPECT = {
    "F1": {"score_date": "20260913", "composite_score": 70.0, "perf_date": "20260911",
           "return_1y": 24.86, "volatility_1y": 15.0, "volatility_3y": 18.0,
           "manager_name": "经理乙",
           "rating_date": "20260911", "rating_morningstar": 5, "purchase_status": "开放申购",
           "industry_top1": None, "industry_n": None},
    "F2": {"score_date": "20260912", "composite_score": 60.0, "perf_date": None,
           "return_1y": None, "manager_name": "经理丙", "industry_top1": "金融业",
           "industry_top1_weight": 30.0, "industry_n": 2},
    "F3": {"score_date": "20260912", "composite_score": 65.0, "perf_date": "20260911",
           "return_1y": 5.0},
}


def _build_fixture_db(path):
    con = sqlite3.connect(path)
    con.executescript(FIXTURE_DDL)
    con.executemany("INSERT INTO fund_basic VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("F1", "基金一", "股票型", "公司A", "经理甲", "20150501", 12.5, 1.5, 0.25, 0.15, 0.0,
         "策略1", "基准1", "20260913"),
        ("F2", "基金二", "混合型", "公司B", "经理丙", "20180301", 3.2, 1.2, 0.2, 0.1, 0.0,
         "策略2", "基准2", "20260913"),
        ("F3", "基金三", "债券型", "公司C", "经理丁", "20200715", 0.8, 0.7, 0.15, 0.0, 0.2,
         "策略3", "基准3", "20260912"),
    ])
    # 收益: F3 有两期 → 取新的 20260911; F2 无收益行 → NULL（不隐藏, 只是空值）
    con.executemany("INSERT INTO fund_performance VALUES (?,?,?,?,?,?,?,?,?,?)", [
        ("F1", "20260911", 1.1, 3.3, 6.6, 24.86, 40.0, 88.0, 12.0, 120.0),
        ("F3", "20260911", 0.5, 1.2, 2.4, 5.0, 9.0, 15.0, 3.0, 30.0),
        ("F3", "20260910", 0.4, 1.0, 2.0, 4.0, 8.0, 14.0, 2.5, 28.0),
    ])
    # 风险: 同日不同 period 必须各取各的; period='5y' 不在一期口径内（须被忽略）
    con.executemany("INSERT INTO fund_risk_indicator VALUES (?,?,?,?,?)", [
        ("F1", "1y", "20260911", 15.0, 20.0),
        ("F1", "3y", "20260911", 18.0, 35.0),
        ("F1", "5y", "20260911", 99.0, 99.0),
    ])
    # 评分: 全局最新分区 20260913 只有 F1（模拟工作日头部 2000 只）; 20260912 有 F2/F3
    #   F2 在 20260913 有一行但 composite_score 为 NULL → 必须跳过, 回落到 20260912
    con.executemany("INSERT INTO fund_score (fund_code, score_date, composite_score, star_rating) "
                    "VALUES (?,?,?,?)", [
                        ("F1", "20260913", 70.0, 4),
                        ("F1", "20260912", 50.0, 3),
                        ("F2", "20260913", None, None),
                        ("F2", "20260912", 60.0, 3),
                        ("F3", "20260912", 65.0, 4),
                    ])
    # 经理: 同日两人 → 取任期更长者（并列再按姓名升序）
    con.executemany("INSERT INTO fund_manager VALUES (?,?,?,?,?,?,?,?)", [
        ("F1", "20260911", "经理甲", "2019-01-01", 100, 3000, 5.0, 30.0),
        ("F1", "20260911", "经理乙", "2016-01-01", 200, 5000, 9.0, 55.0),
        ("F2", "20260911", "经理丙", "2020-01-01", 50, 1500, 1.0, 10.0),
    ])
    con.execute("INSERT INTO fund_rating VALUES ('F1','20260911',5,4,3,5,2)")
    con.execute("INSERT INTO fund_purchase_status VALUES "
                "('F1','20260911','开放申购','开放赎回',10.0,100000.0)")
    # 行业（二期预留）: 同日两行业 → 取权重最大者 = 第一大配置行业, industry_n=2
    con.executemany("INSERT INTO fund_industry_alloc VALUES (?,?,?,?)", [
        ("F2", "20260630", "制造业", 25.0),
        ("F2", "20260630", "金融业", 30.0),
    ])
    con.commit()
    con.close()


def _make_fixture_repo(tmp_path):
    """搭一个最小 REPO 布局: data/public_fund.db + .venv/bin/python(指向当前解释器)。"""
    repo = tmp_path / "fixture-repo"
    (repo / "data").mkdir(parents=True)
    (repo / ".venv" / "bin").mkdir(parents=True)
    py = repo / ".venv" / "bin" / "python"
    if not py.exists():
        try:
            py.symlink_to(sys.executable)
        except OSError:  # 某些文件系统不支持 symlink → 退化为包装脚本
            py.write_text('#!/bin/sh\nexec "%s" "$@"\n' % sys.executable, encoding="utf-8")
            py.chmod(0o755)
    _build_fixture_db(str(repo / "data" / "public_fund.db"))
    return repo


def _run_dry_run(tmp_path, repo):
    """跑真实同步脚本 DRY_RUN; TMPDIR 指向 tmp_path 让生成目录随测试自动清理。"""
    gen_root = tmp_path / "gen"
    gen_root.mkdir()
    env = dict(os.environ)
    env.update({"REPO": str(repo), "GIT_REPO": str(repo), "DRY_RUN": "1",
                "TMPDIR": str(gen_root)})
    r = subprocess.run(["bash", str(SYNC_SH)], capture_output=True, text=True, env=env,
                       timeout=180)
    assert r.returncode == 0, "同步脚本 DRY_RUN 失败:\n" + r.stdout + r.stderr
    assert "wrangler" not in r.stdout, "DRY_RUN 不该触云（输出含 wrangler）:\n" + r.stdout
    dirs = [p for p in gen_root.iterdir() if p.name.startswith("fund-screener-d1.")]
    assert len(dirs) == 1, "生成目录不是唯一: " + str(dirs)
    return dirs[0], r.stdout


def _load_generated(gen_dir, db_path):
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    for f in sorted(gen_dir.glob("*.sql")):
        con.executescript(f.read_text(encoding="utf-8"))
    return con


def _table_hash(con):
    h = hashlib.md5()
    for row in con.execute("SELECT * FROM fund_screener ORDER BY fund_code"):
        h.update(("\x1f".join("" if v is None else str(v) for v in row)).encode())
    return h.hexdigest()


# ============================ ① 前后端参数名对齐 ============================
def _extract_fe_spec():
    src = APP_JS.read_text(encoding="utf-8")

    def block(name):
        m = re.search(r"const %s = \[([\s\S]*?)\];" % name, src)
        assert m, "app.js 里找不到 %s 清单" % name
        return m.group(1)

    nums = re.findall(r'\bk:\s*"([A-Za-z0-9_]+)"', block("FUND_SCREENER_NUM_FIELDS"))
    multi = re.findall(r'\bp:\s*"([A-Za-z0-9_]+)"', block("FUND_SCREENER_MULTI_FIELDS"))
    exact = re.findall(r'\bp:\s*"([A-Za-z0-9_]+)"', block("FUND_SCREENER_EXACT_FIELDS"))
    sortm = re.search(r"const FUND_SCORE_API_SORT_KEYS = \[(.*?)\];", src, re.S)
    assert sortm, "app.js 里找不到 FUND_SCORE_API_SORT_KEYS"
    sorts = re.findall(r'"([A-Za-z0-9_]+)"', sortm.group(1))
    return nums, multi, exact, sorts


def _worker_spec():
    js = (
        "import('./worker/fund_screener.js').then(m=>console.log(JSON.stringify({"
        "range:m.RANGE_FIELDS.map(f=>f.name),multi:m.MULTI_FIELDS.map(f=>f.param),"
        "exact:m.EXACT_FIELDS.map(f=>f.param),sortable:[...m.SORTABLE]})));"
    )
    r = subprocess.run(["node", "--input-type=module", "-e", js], cwd=str(ROOT),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "读 worker 导出失败:\n" + r.stderr
    tail = [ln for ln in r.stdout.strip().splitlines() if ln.startswith("{")]
    assert tail, "worker 导出无 JSON: " + r.stdout
    return json.loads(tail[-1])


def test_worker_and_frontend_param_names_align():
    nums, multi, exact, sorts = _extract_fe_spec()
    wk = _worker_spec()
    fe_nums = set(nums)
    wk_range = set(wk["range"])
    # FE 数值条件 = worker 区间字段 ∪ {rating_any}（「任一机构评级」不在区间表内, 由 worker 单列实现）;
    # 前端出现 worker 不认的名字 = 参数名写错（线上条件静默失效）→ 必须为 0。
    assert fe_nums - (wk_range | {"rating_any"}) == set(), \
        "前端条件名 worker 不认（参数名拼写漂移）: " + str(sorted(fe_nums - wk_range - {"rating_any"}))
    # worker 支持但面板未暴露的（API 超集, 属设计选择）—— 显式登记, 增删都要求同步本常量。
    NOT_IN_UI = {"rating_shanghai", "rating_cms", "rating_jajx"}
    assert wk_range - fe_nums == NOT_IN_UI, \
        "worker 有而面板无的条件变了（应在 NOT_IN_UI 显式登记）: " + str(sorted(wk_range - fe_nums))
    assert set(multi) == set(wk["multi"]), "多选条件参数名不一致"
    assert set(exact) == set(wk["exact"]), "精确匹配条件参数名不一致"
    # 工具栏排序下拉的每个键都必须在筛选器排序白名单里（否则切到筛选器模式排序静默失效）
    missing = [k for k in sorts if k not in set(wk["sortable"])]
    assert missing == [], "工具栏排序键不在筛选器白名单: " + str(missing)


# ============================ ② worker 过滤行为 ============================
def test_buildfilter_behavior_and_injection():
    r = subprocess.run(["node", str(NODE_CHECK)], capture_output=True, text=True,
                       cwd=str(ROOT), timeout=60)
    assert r.returncode == 0, "buildFilter 机检失败:\n" + r.stdout + r.stderr
    assert "ALLPASS" in r.stdout, r.stdout


# ============================ ③ 同步脚本端到端口径 ============================
def test_sync_script_dry_run_per_fund_latest_and_idempotent(tmp_path):
    repo = _make_fixture_repo(tmp_path)
    gen_dir, out = _run_dry_run(tmp_path, repo)
    con = _load_generated(gen_dir, tmp_path / "screener.db")
    rows = {r["fund_code"]: r for r in con.execute("SELECT * FROM fund_screener")}

    # 宇宙 = fund_basic 全市场（1 行/只, 不因某字段缺失而少行）
    assert sorted(rows) == ["F1", "F2", "F3"], sorted(rows)
    assert "rows=3" in out, out

    # 核心: 每只基金取**各自**最近可用评分分区（不是全局最新分区）
    for code, exp in EXPECT.items():
        for k, v in exp.items():
            assert rows[code][k] == v, "%s.%s 期望 %r 实得 %r" % (code, k, v, rows[code][k])
    assert rows["F1"]["score_date"] == "20260913" and rows["F2"]["score_date"] == "20260912", \
        "「每只基金最近可用评分」失效（F2 应取 20260912 而非全局最新）"

    # 风险: 同日不同 period 各取各的; 一期口径外的 period 不污染
    assert rows["F1"]["volatility_1y"] == 15.0 and rows["F1"]["volatility_3y"] == 18.0
    # 派生年限列随运行日变 → 只断言非空（L51 时敏, 不写死数值）
    assert rows["F1"]["setup_years"] is not None and rows["F1"]["tenure_years"] is not None

    # 幂等: 把同一批 SQL 再灌一遍到同一个库（DELETE+INSERT 全量替换）→ 行数与内容 hash 不变
    h1 = _table_hash(con)
    n1 = len(rows)
    con2 = _load_generated(gen_dir, tmp_path / "screener.db")
    assert len(list(con2.execute("SELECT fund_code FROM fund_screener"))) == n1, "重灌后行数变了"
    assert _table_hash(con2) == h1, "重灌后内容不一致（全量替换非幂等）"

    # 覆盖率 meta 与实表逐位一致
    meta = dict(con.execute("SELECT key, value FROM screener_meta"))
    coverage = json.loads(meta["coverage"])
    assert json.loads(meta["fund_total"]) == 3
    for col, v in coverage.items():
        real = con.execute("SELECT COUNT(*) FROM fund_screener WHERE %s IS NOT NULL" % col).fetchone()[0]
        assert real == v, "覆盖率不一致 %s: meta=%s 实表=%s" % (col, v, real)
    con.close()


# ============================ ④ 表列 ⊇ worker 引用列 ============================
def test_generated_table_covers_every_worker_referenced_column(tmp_path):
    """参数/排序列写错一个字母 = 线上 500; 这里把 worker 引用的**每一列**回查建表产物。"""
    repo = _make_fixture_repo(tmp_path)
    gen_dir, _ = _run_dry_run(tmp_path, repo)
    con = _load_generated(gen_dir, tmp_path / "cols.db")
    cols = {r[1] for r in con.execute("PRAGMA table_info('fund_screener')")}
    wk = _worker_spec()
    need = set(wk["range"]) | set(wk["sortable"]) | {
        # handler 直接引用的固定列
        "fund_code", "fund_name", "fund_company", "fund_type", "purchase_status", "composite_score",
    }
    missing = sorted(need - cols)
    assert missing == [], "worker 引用了建表产物里没有的列: " + str(missing)
    # 反向: 表里列名不得与 worker 白名单以外的东西冲突（仅提示性, 不断言全部列）
    assert len(cols) >= 70, "列数过少(%d), 前端详情弹窗/行渲染会缺字段" % len(cols)
    con.close()