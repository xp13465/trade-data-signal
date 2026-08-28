# 优化批次 B+C 精确实施蓝图(ab-#37 + ab-#38 + O2)

> 产出:role-researcher 只读调研(2026-08-18)| 前置:已 4 次直接派 implementer 探索阶段异常退出,改「蓝图→按图实施」两段式
> 依据:docs/ab-refactor-bug-reflection.md L31/L32 + docs/optimization-closeout-list.md §1.3/§3 + 代码层/日志层证据(见「## 复现」)
> 测试基准无关(纯采集/脚本提速,不动回测组合口径)。

---

## 0. 调研背景速览(所有蓝图的前提)

| 项 | 现状(证据) |
|---|---|
| baostock 并发 | 固定 n_workers=4(app/collector/runner.py L316/L477 两个调用点;baostock_parallel.py L109 签名默认 4) |
| baostock 熔断 | 已有 **worker 级** 熔断(baostock_worker.py L104 circuit_open + L142-183 检测 10001011 → exit 3 L202-206),但**无跨 worker 共享熔断、无 relay 到 runner** |
| core 采集瓶颈 | metrics 单步实测 13.5min(collect_log 铁证:17:50:28→18:03:57),其中 a_qvix_300≈3.9min、a_qvix_1000≈3.9min、cn10y≈2.8min、a_fund_north≈2.4min,其余 39 个指标合计≈1min |
| indices 规模 | config/indicators.yaml indices 共 158 个(sw 31 / ths 27 / sina 35 / csindex 24 / tencent 19 / hk 11 / us 4 / global 5 / etf 1 / futures 1),**串行**逐源拉取 |
| O2 etf_score | export_etf_score_list.py L580 `n_workers = min(6, len(_worker_args))`;空返 ETF 会被重复拉取(初始拉取 + _compute_volatility 内再拉);mootdx fallback 每只 ETF 重新 tdx_client(bestip 测速) |
| 当前 deploy | 后台 deploy 正在跑(8/18 09:08 启动)。**本蓝图调研的文件全部是代码/config 层,deploy 不写这些文件**,无冲突;实施时 `export_etf_score_list.py` 输出(etf_score_list_*.json)会被 deploy 覆盖,实施后需重跑该脚本 |

---

## 1. ab-#37 降并发 + A 熔断(共享化)

### 1.1 涉及文件 + 行号
- `app/collector/runner.py` L316、L477(run_update_parallel 两个调用点)
- `app/collector/baostock_parallel.py` L109(签名默认值)、L200(日志正则)、L218(CLI 默认值)
- `app/collector/baostock_worker.py` L104(circuit_open)、L143-183(4 处熔断触发点)、L201(done 行打印)、L202-206(exit 3)

### 1.2 改动内容
**改动 A1 — 并发可配 + 默认 4→3(降并发 25% 触发概率,时间约 +33%)**
- runner.py L316/L477:`n_workers=4` → `n_workers=int(os.environ.get("BAOSTOCK_WORKERS", "3"))`
- baostock_parallel.py L109 签名默认 `n_workers=4` → `n_workers=3`;L218 CLI 默认 `n_workers = 4` → `3`
- 为什么:8-14 事故=4 并发中 2 连接被 10001011 黑名单(ab-refactor L42-44);8-17 实测 4 并发正常(6.3min,5199 ok/1 fail)。降并发降低触发概率,env 覆盖保留临时调高速率。

**改动 A2 — 跨 worker 共享熔断(核心)**
- 新增共享 flag 文件:`DATA_DIR / "baostock_blacklist.flag"`(DATA_DIR 已在 baostock_parallel.py L17 定义 = repo/data)
- Writer(baostock_worker.py 4 处熔断触发点 L145/L153/L171/L179 的 `circuit_open = True` 后追加):
  ```python
  _BLACKLIST_FLAG = Path(__file__).absolute().parent.parent.parent / "data" / "baostock_blacklist.flag"
  def _set_blacklist_flag():
      try: _BLACKLIST_FLAG.write_text(dt.datetime.now().isoformat(), encoding="utf-8")
      except Exception: pass
  ```
- Reader(baostock_worker.py 主循环 L105 前、每个 code 处理顶部追加):其他 worker 撞 10001011 后本 worker 下一 code 立即停,不必等自己也撞:
  ```python
  if not circuit_open and _BLACKLIST_FLAG.exists():
      circuit_open = True
      print(f"  [{os.getpid()}] 检测到共享黑名单 flag(其他 worker 已熔断),短路后续 code", flush=True)
  ```
- Cleaner(baostock_parallel.py run_update_parallel L159 启动时 + L193 汇总前):`flag.unlink(missing_ok=True)`(启动清旧状态,结束清残留)
- 为什么:account/IP 级封禁对所有并发连接同效;1 个 worker 撞上时其余 3 个还在盲试(每个在撞上前会烧若干 code),共享 flag 让 4 个 worker 近似同时停,封禁场景总耗时从「4×盲试」降为「1×盲试」。

**改动 A3 — 熔断事件 relay 到 runner + 告警**
- baostock_parallel.py run_update_parallel 汇总段(L196-213)追加:
  ```python
  blacklisted = any(p.returncode == 3 for p, _, _ in procs) or _BLACKLIST_FLAG.exists()
  ...
  return {..., "blacklisted": blacklisted, "blacklist_workers": sum(1 for p,_,_ in procs if p.returncode==3)}
  ```
- runner.py turnover step(L477-507)在 `res.get("blacklisted")` 时复用现有 `_notify`(L29-44,dedup_key="baostock_blacklist",window=86400)告警「baostock 封禁熔断」,并记 fail;runner.py baostock step(L316)同理。
- ⚠️ **不改 L201 的 `done: ok=.. fail=.. rows=..` 打印格式**——run_update_parallel L200 正则依赖它聚合统计;若要改格式必须两处同步(ab-refactor L31 明确的同坑)。

### 1.3 共享状态读写双方 grep 清单
| 角色 | 位置 |
|---|---|
| Writer | baostock_worker.py L145、L153、L171、L179(4 处 circuit_open=True 后写 flag) |
| Reader | baostock_worker.py 主循环 code 处理顶部(新增检查 flag.exists) |
| Cleaner | baostock_parallel.py run_update_parallel 启动(L159 附近)/结束(L193 附近) |
| Consumer | baostock_parallel.py 汇总段(L196-213)+ runner.py L316/L477 调用点 |
> 防再犯:改共享状态必须 grep 读写双方(ab-refactor L31 风险点);本清单即实现期校验锚点。

### 1.4 单脚本自测命令
```bash
cd /Users/linhuichen/code/trade-data
.venv/bin/python -m py_compile app/collector/baostock_worker.py app/collector/baostock_parallel.py app/collector/runner.py
# 真实并行链路(最小):走 turnover 的 baostock 子步
RUN_BAOSTOCK=1 .venv/bin/python -m app.collector.runner --steps turnover
# 校验:worker 日志末尾 done: ok=.. fail=.. rows=.. 行仍在(正则匹配);flag 启动后清理、结束时清理
# 熔断短路单测(不碰真实网络):mock fetch_one 返 10001011 消息 → 断言写 flag + 循环短路 + exit 3
```

### 1.5 风险/挂起项
- 无挂起项(纯采集稳定性/风控,不动数据口径,不触碰 §23.7 已发布功能行为)。
- 风险:并发默认 3 会让 baostock 增量(8-17 实测 6.3min)约 +33%;可用 env 临时调回 4。

---

## 2. ab-#38 core 采集提速

### 2.1 瓶颈定位(数据说话,collect_log 实测)
**metrics 单步 = 13.5min 是 core 采集最大单点**,四个慢指标占 ~13min:
| 指标 | 耗时(8-17 17:50 run) | 慢因 | 提速手段 |
|---|---|---|---|
| a_qvix_300 (index_option_300etf_qvix) | 17:53:11→17:57:02 ≈3.9min | SSE 官方 IV 方差互换自算长序列(multisource.sse_qvix_series,fetchers.py L181/L317) | 并发重叠 |
| a_qvix_1000 (index_option_50etf_qvix) | 17:57:02→18:00:53 ≈3.9min | 同上 | 并发重叠 |
| cn10y (bond_china_yield) | 18:01:06→18:03:49 ≈2.8min | 3650 天 lookback 按 350 天窗口分块拉取拼接(fetchers.py L154-176 分块函数,L258-276/L396-400 两个入口) | 并发重叠 |
| a_fund_north (direct:north_fund_total) | 17:50:32→17:52:56 ≈2.4min | HKEX 官方源 | 并发重叠 |
| 其余 39 个指标 | 合计 ≈1min | — | — |
**indices 158 个串行**(sw 31 走 swsresearch index_hist_sw 慢源 full-history,fetchers.py L677-680)→ 估算 3-5min。
**industry_extras 换手率 31 个东财 kline 串行 + 每只 time.sleep(0.5)**(industry_extras.py L469)→ 估算 1-2min,东财封 IP 时连 3 失败提前结束。

### 2.2 改动内容(按收益排序)
**改动 B1 — metrics 循环并行化(最大收益,低风险)**
- 位置:runner.py L148-209(metrics 循环体)
- 把循环体抽成独立函数(如 `_collect_one_metric(m, date)`),内部保持现有 collect+upsert+log 逻辑不变,返回 (mid, st, msg);主循环改:
  ```python
  from concurrent.futures import ThreadPoolExecutor, as_completed
  _m_workers = int(os.environ.get("METRICS_WORKERS", "4"))
  with ThreadPoolExecutor(max_workers=_m_workers) as _ex:
      _futs = {_ex.submit(_collect_one_metric, m, date): m["id"] for m in _m_list}
      for _fut in as_completed(_futs):
          ...  # 汇总 ok/fail/details(顺序无关)
  ```
- 为什么安全:metrics 全部 request-based 或 direct:直爬,无 V8 isolate 依赖(V8 只 fund_etf_hist_sina,metrics 段没有);upsert_metric/upsert_metrics_many 各自开独立 conn(get_conn+commit+close,runner.py L83-110),线程安全;base.py `_THROTTLE_LOCK` 已线程安全(L72-83)。单个慢指标内部不变(不降 lookback,保数据质量)。
- 收益:13.5min → ~4-5min(≈max(慢指标))= **省 ~9min**,core 采集总时长腰斩。

**改动 B2 — indices 循环并行化(中收益,保守并发)**
- 位置:runner.py L214-228(indices 循环体)
- 同上 ThreadPool,`max_workers=int(os.environ.get("INDICES_WORKERS", "4"))`,抽 `_collect_one_index(idx, start, date)` 返回 (iid, st, msg)。
- 风险管控:akshare sina/csindex/ths 并发有限流风险;swsresearch(index_hist_sw)反爬敏感。建议**首版只对非 sw 源并行、sw 源保持串行**(按 func 分组:sw/ths 串行,sina/csindex/tencent/hk/us/global 并行),观察一轮再放开。
- 收益:indices ~3-5min → 1-2min。

**改动 B3 — industry_extras 换手率并发(低风险小收益,可选)**
- 位置:industry_extras.py L462-490(换手率循环 + time.sleep(0.5))。可并 2-3 线程;但东财封 IP 已有连 3 失败提前结束保护(ABORT_THRESHOLD L456),并发会放大封禁触发面 → **建议本轮不动,列为可选挂起**。

**改动 B4 — 删 sw 指数 = 挂起项(需用户确认,本蓝图不实施,见 2.3)**

### 2.3 sw 指数删除波及面清单(grep 全站,实施前必读)
> 依据 §23.7(版本功能冻结)+ §22(数据一致性)+ §23.6(宇宙规则)。删 config/indicators.yaml L164-206 的 31 个 sw_801xxx 属「动已发布功能默认行为」,必须用户确认后才实施。

| # | 波及位置 | 影响 | 风险 |
|---|---|---|---|
| 1 | config/indicators.yaml L164-206(31 个 sw_801xxx 定义) | 删源点 | — |
| 2 | app/collector/fetchers.py L655-666/L677-680(index_hist_sw 分支) | 采集不再拉 sw | 低(代码保留,cfg 删即不触发) |
| 3 | app/collector/index_backfill.py([校验] 31 申万行业今日齐全 + 补采) | 校验逻辑随 cfg 少 31 项 | 低 |
| 4 | app/collector/industry_extras.py L22-41(SW_EM_MAP 31 东财 BK 映射)+ L415-494(collect_industry_extras) | ind_flow_*/ind_turn_* 入 daily_metric,若指标段保留而指数段删,需解耦(这两者不依赖 indices 段,可单独保留) | 中(需确认资金流/换手率是否保留) |
| 5 | scripts/build_board_etf_map.py L33-52(sw_801xxx → ETF 关键词 30 个映射) | board_etf_map 的 30 个 sw key 全消 → ETF 联动 tag 丢失;check_universe_alignment 断言4(yaml 排除类别 ⟺ map 缺失)需同步 | **高** |
| 6 | scripts/signal_kelly_backtest.py L93(A_STOCK_MARKETS 含 "industry")、L110-114(五象限含 mkt_industry 31 申万)、L233-243(读 indicators.yaml → index→market 映射)、L1044(行业大盘择时) | 31 个行业从凯利回测宇宙消失,§23.6 宇宙规则变更,需重跑回测 + 对称校验 + 公示 | **高** |
| 7 | app/queries.py L428-430(industry_heatmap 遍历 market=industry)+ L1338/L1465/L1652 | 首页「申万一级行业涨跌幅热力图」空 | **高(用户可见)**,app.js L12269/L24774 渲染空态 |
| 8 | static-site/export.py L909-961(industry-3y-indices 拆分,31 行业文件)+ L650/L1181(public_fund_sw_industry_alloc.json 依赖 sw_components) | 行业指数 JSON 拆分文件消失 + 公募基金行业配置图数据源断 | **高** |
| 9 | static-site/app.js(20 处 sw_801)/common.js(16 处) | 前端行业网格/渲染引用 | 中(随数据空态显示) |
| 10 | docs/data-dictionary.md L250-272/393-406(行业结构文档) | 文档过时需同步 | 低 |

**结论:删 sw 指数 = 高风险,触碰 首页行业热力图 + ETF 联动 tag + 凯利宇宙 + 公募基金行业配置 4 大已发布功能。列入挂起项,需用户拍板;若确认删,必须按 §23.6 八步联动(改 cfg → 重跑 build_board_etf_map → 重跑凯利回测 → 重跑 export → §22 三步同步 → 三处公示 → check_universe_alignment → 前端空态)。本蓝图只列方案,不实际删任何指数。**

### 2.4 自测命令
```bash
cd /Users/linhuichen/code/trade-data
.venv/bin/python -m app.collector.runner --steps metrics      # 验证并行后 metrics 全 ok(对照 collect_log 耗时)
.venv/bin/python -m app.collector.runner --steps indices      # 验证并行后 indices 全 ok + index_daily 行数不减
.venv/bin/python -m py_compile app/collector/runner.py
# 回归:跑完看 collect_log 今日 metrics 是否全覆盖(43 个 enabled 无缺),index_daily 各指数最新日期=交易日
```

### 2.5 风险/挂起项
- 挂起:B4(删 sw 指数)= 需用户确认;B3(industry_extras 并发)= 可选。
- 风险:B2 indices 并发可能触发 akshare 源限流 → 首版 sw/ths 保持串行;任何并发改动后必须跑 `--steps metrics/indices` 全量验证覆盖率(§23.2 修完整)。

---

## 3. O2 etf_score 提速

### 3.1 涉及文件 + 行号
- `scripts/export_etf_score_list.py` L88-91(import)、L259-272(_fetch_and_upsert_ohlc)、L464-469(worker 内采集调用)、L482(_compute_volatility 调用)、L580(n_workers)
- `app/collector/etf_national_team.py` L64-71(_get_worker_tdx 进程级缓存)、L532-608(fetch_etf_ohlc,client 参数已存在 L532/L537)、L337-431(_compute_volatility,内置补采 L363-390)

### 3.2 改动内容
**改动 C1 — workers 6→8**
- L580:`n_workers = min(6, len(_worker_args))` → `n_workers = min(8, len(_worker_args))`
- 说明:ProcessPool 8 并发,采集(sina 0.3s/只)与算分并行提速;10 需要先观测 sina 限流(可后续 `min(10, ...)`,本轮保守 8)。**ProcessPool 必须保留(不能改 ThreadPool)**——akshare fund_etf_hist_sina 内部 V8 isolate 非线程安全(B4 教训,etf_national_team.py L56-60)。

**改动 C2 — mootdx 服务器复用(每进程只选一次服务器)**
- export_etf_score_list.py L88-91 import 追加 `_get_worker_tdx`
- L259 `def _fetch_and_upsert_ohlc(code: str, name: str, conn, client=None)`;L265 `fetch_etf_ohlc(code, start_yyyymmdd=start_yyyymmdd, client=client)`
- L468 worker 内:`n = _fetch_and_upsert_ohlc(code, name, conn, client=_get_worker_tdx())`
- 效果:ProcessPool worker 进程内 tdx_client 只创建一次(etf_national_team.py L64-71 已实现缓存),避免每只 ETF fallback 时重新 bestip 测速(~1-2s/只,mootdx_daily.tdx_client L98-132)。

**改动 C3 — 空返降重试(空返 ETF 不重复拉取)**
- 现状:`_fetch_and_upsert_ohlc` 返 0(空返)后,_process_one_etf_worker L482 仍调 `_compute_volatility(code, conn)`,而后者在 rows<20 时**再次** fetch_etf_ohlc(etf_national_team.py L363-390)→ 空返 ETF 每 run 重复拉取 2 次(含 mootdx paged)。
- 改法:
  - etf_national_team.py `_compute_volatility(code, conn, lookback_days=30, skip_refetch=False)`;L363 补采分支加 `if not skip_refetch:` 守卫
  - export_etf_score_list.py worker 内:
    ```python
    fetch_ok = False
    if not no_fetch:
        if _has_recent_data(conn, code):
            res["skip_count"] = 1
        else:
            fetch_ok = _fetch_and_upsert_ohlc(code, name, conn, client=_get_worker_tdx()) > 0
    ...
    vol = _compute_volatility(code, conn, skip_refetch=not fetch_ok)
    ```
- 效果:空返/无数据 ETF(如 QDII/停牌)只拉 1 次,不再进 mootdx 二次拉取;对全市场 ~1371 只中少数空返标的省时,叠加 C1/C2 整体降 2-3min(optimization-closeout 估算)。

### 3.3 自测命令
```bash
cd /Users/linhuichen/code/trade-data
# 小批量真跑(验证 workers/mootdx 复用/空返逻辑,~1min)
.venv/bin/python scripts/export_etf_score_list.py --limit 30 --buy-top 10 --sell-top 10
# 快速算分路径(不采集)
.venv/bin/python scripts/export_etf_score_list.py --no-fetch --buy-top 10 --sell-top 10
# 完整回归(全市场 ~1371 只,约 20min,避盘中/盘后定时任务时点;注意会覆盖 deploy 已生成的 etf_score_list_*.json,跑完须 §22 三步同步)
.venv/bin/python scripts/export_etf_score_list.py --full-market
```

### 3.4 风险/挂起项
- 无挂起项(独立脚本,不改采集口径,不动已发布默认行为)。
- 风险:sina 8 并发限流 → 观测 `--limit 30` 全 ok 后再全市场;C2 的 `_get_worker_tdx` 依赖 etf_national_team 已 import 的模块链,实施后先 py_compile。

---

## 复现
- **metrics 耗时铁证**:`sqlite3 "file:/Users/linhuichen/code/trade-data/data/sentiment.db?mode=ro" "SELECT metric_id,run_at FROM collect_log WHERE run_date='20260817' AND run_at>='2026-08-17T17:50' AND run_at<'2026-08-17T18:10' ORDER BY run_at"`(a_qvix_300 17:53:11→17:57:02、a_qvix_1000 →18:00:53、cn10y →18:03:49)
- **baostock 现状**:`grep -n "n_workers" app/collector/runner.py app/collector/baostock_parallel.py`(L316/L477/L109/L218);`grep -n "10001011\|circuit_open" app/collector/baostock_worker.py`(L38/L104/L143-183/L202-206)
- **并发基线**:8-17 update_all 日志 `parallel update done: ok=5199 fail=1 rows=6024 (5200 codes, 6.3min)`(data/logs/update_all_20260817_1750.log L77)
- **O2 现状**:`sed -n '578,586p' scripts/export_etf_score_list.py`(n_workers);`sed -n '64,71p;363,390p' app/collector/etf_national_team.py`(tdx 缓存 / volatility 补采)
- **sw 波及**:`grep -rn "sw_801" --include="*.py" --include="*.js" app/ scripts/ static-site/ config/ | grep -v worktrees`(见 2.3 表)
- 数据截止:2026-08-18(仅读,未改任何业务代码)
