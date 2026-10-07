# #213 批 2 先决决策权威评估:CI 依赖 vs stub 扩写(2026-10-07)

> 本报告由 researcher 只读调研产出(#213 批 2 先决拍板项);因 role agent 无 Write 工具,报告全文由主控代落档(与 #181/#213 先例一致)。
> 执行环境:全程只读;未改任何文件;未 import/真跑任何 notify/feishu/upload_r2;探针内 `socket.getaddrinfo` + `subprocess.run` 双重阻断(零外发,含 `_resolve_sws_ip` 的 dig 路径)。

## 0. 口径与硬约束(诚实标注)

- 全程只读,未改任何文件;未 import/真跑任何 notify/feishu/upload_r2;探针内 `socket.getaddrinfo` + `subprocess.run` 双重阻断(零外发)。
- 唯一被执行的业务代码 = `scripts/test_ai_macro_hit_filters.py`(纯谓词,无外发面)在探针沙箱内 runpy 执行,用于证明「import 通 ⇒ 用例真绿」;不使用 `pytest`(避免收集他文件)。
- 未实跑 CI、未做 pip 安装(耗时项标注预估);本机无 `timeout`/`gtimeout`,命令一律用工具级 timeout。

## 1. Q1 依赖闭包(答案:装真库到「纯数值/数据层」为止)

`app.queries` / `app.db` 静态 AST 闭包(16 个项目模块):`app.queries → {app.calendar, app.collector.fetchers, app.compute.{signal_stats, market_summary, futures_position, rotation, signals, normalize}, app.db}`;`fetchers → {base, multisource, fapi_fallback, fapi_daily}`;`signal_stats → normalize`。

模块级(import 期必需)第三方顶层模块:

| 库 | 性质层级 | 引入点(文件:行) | 处置 |
|---|---|---|---|
| pandas | 纯数值/数据层 | `app/compute/normalize.py:4`、`signal_stats.py`、`futures_position.py:20`、`rotation.py:13`、`signals.py:76`、`collector/fetchers.py:11`、`fapi_fallback.py:23` | **装真库** |
| (numpy) | 纯数值层 | `signals.py` 函数内懒加载(pandas 依赖会连带装) | **装真库** |
| pyarrow | 纯数据 I/O 层 | `collector/fapi_daily.py:54`(`import pyarrow.parquet as pq`,仅函数内 L268 使用) | **装真库**(理由见 Q2) |
| yaml | 配置解析 | `collector/fetchers.py:12`(`load_config` L98-100) | 已装(`pip install pytest pyyaml`) |
| akshare | **网络采集层** | `collector/fetchers.py:10` | 保持 stub |
| requests | **网络采集层** | `collector/base.py:8`(L124 `EM_SESSION = requests.Session()`) | 保持 stub |

边界判据(可复用):①库语义=外发网络/第三方服务 ⇒ stub(保留"运行时调用响亮失败")②库语义=纯数值/数据 I/O 且 CI 测试可能真断言 ⇒ 装真库 ③硬机检:生产/开发 venv(`/Users/linhuichen/code/trade/.venv`、`trade-data/.venv`)里**有**它 ⇒ CI 应同构装真。两 venv 实查:均 pandas 3.0.3 / numpy 2.4.6 / pyarrow 25.0.1 / akshare 1.18.64。

## 2. Q2 方案 A 可行性(结论:可行,但"只装 numpy+pandas"不足)

- 安装位置:`ci.yml:109-112`(Job1 ⑧,FAIL 阻断)内 **L111 `pip install pytest pyyaml`** 一行;Job2(`quality-gate-data`,L115-151)两脚本 = `check_loss_rules_vs_mining.py`(stdlib+`loss_rules`)+ `check_fade_predicate_parity.mjs`(Node)⇒ **Job2 不需要**。
- **链式风险实证(决定性)**:PyPI 实拉(2026-10-07)pandas 3.0.6 requires_dist 核心仅 `numpy>=1.26.0`/`python-dateutil`,**pyarrow 只在 extras**(`extra == "pyarrow"/"parquet"/"all"`)⇒ CI `pip install numpy pandas` 不会装 pyarrow ⇒ conftest 裸 pyarrow stub 生效 ⇒ 探针 plan_a 实测:`AttributeError: module 'pyarrow' has no attribute '__version__'` at `pandas/compat/pyarrow.py:14`(该处 `try: import pyarrow as pa` 只捕 ImportError,AttributeError 直接外逸)。**即"装真 pandas"必须先解决 pyarrow 关系**。
- 补 `__version__` 的省钱变体验收失败:`pd.Series([1.0,2.0,3.0])` → `pandas/core/arrays/string_.py:781 → lib.is_pyarrow_array → pyarrow.Array` AttributeError(探针实测)⇒ 假 pyarrow 需按真 pandas 内部实现逐个补面 = 无底洞。
- **A2(真 numpy+pandas+pyarrow)通过态**:探针用项目 venv 真库 + stub akshare/requests:`import app.queries` OK;`pd.Series.mean()/groupby` OK;`app.compute.signals._rsi(真 Series)=53.0496`;`test_ai_macro_hit_filters` **13/13,exit 0**。faithfulness 收益 = 测试对着真库断言 + 解锁 `app/compute/*` 类算法函数可测(现 CI 只能测纯 JSON 算法)。
- 耗时量级(预估,未实测):pin 三件 cp311 manylinux wheel 已核 —— pandas 3.0.3 = 11.3MB、numpy 2.4.6 = 16.9MB、pyarrow 25.0.1 = 50.1MB,合计 ~78MB;wheel 免编译,预估 +20~40s/次(可选 `setup-python cache: pip` 摊薄);运行时 import 增量实测 ≈0.2s(numpy 0.03s + pandas 0.15s)。
- 版本 pin 依据:两 venv 同款(dev==trade-data/生产树);三者 `requires_python` 均兼容 3.11(`pandas>=3.11`/`numpy>=3.11`/`pyarrow>=3.10`),cp311 轮子存在。

## 3. Q3 方案 B(继续扩 conftest stub)上限判定:不能根治

- 做到什么程度够导入:实测**只要 `pd.Series` + `pd.DataFrame`** 两个属性(`conftest.py:56` 的 bare pandas 补这两项)即可 `import app.queries` OK,用例 13/13 —— 因注解站点就这两类(`normalize.py:13`、`signal_stats.py:67`、`futures_position.py:39/67`、`rotation.py:20`、`signals.py:83` 等)。
- 万能兜底 stub(模块级 `__getattr__` 返回假类)也能 import + 13/13,但风险最大(把"假对象"扩散到任意属性,静默吞掉 import 期真实调用面)。
- **上限**:任何真 pandas 语义都不能测(实测 `_rsi` 类调用 → AttributeError)⇒ B 永久锁死"导入级",与 ⑧「算法核心 pytest」的意图背离。
- **无底洞实证**:假库里"够不够"由**真库内部实现**决定 —— 假 pyarrow 撞真 pandas(Q2 两处),补 `__version__` 后又在运行期撞 `pyarrow.Array`;每引入一个新真库,就要给它配套的假依赖再打补丁,补丁面不可穷举、随版本漂移。
- §18 L49 同类风险(诚实标注边界):本用例恰好不触 pandas 语义,故 B 下"CI 绿"今天不算假绿;但把"核心数值库用假对象"固化进 conftest 作长期范式 = 断言输入/运行环境与生产脱钩的温床。

## 4. Q4 业界实践(诚实标注:无强权威先例可引)

- 官方文档域名 `docs.pytest.org` / `pytest.org` / `docs.python.org` 三次 WebFetch 均被网络策略拦(domain verification failed);WebSearch 返回内容以中文转载、JVM 生态文章为主,质量不足以引证。
- 仅得到方向性二手共识:"不要 mock 你不拥有的类型"(Mockito wiki 链条)与"打桩应打在系统边界(网络/DB/时钟),而非核心库"。**按任务口径记为「无权威先例」,不硬编**;本报告的结论按工程判据+本地实测给出。

## 5. Q5 唯一推荐 + 反方案否决 + 最小落地

**推荐:方案 A2** —— Job1 ⑧ 装真 `numpy==2.4.6 pandas==3.0.3 pyarrow==25.0.1`(与 venv 同款),akshare/requests 保持 stub。

- 最小落地(精确):`ci.yml` **L111** `pip install pytest pyyaml` → `pip install pytest pyyaml numpy==2.4.6 pandas==3.0.3 pyarrow==25.0.1`(**conftest.py 零改动**:真库装上后 `conftest.py:60` 的 `find_spec` 命中即跳过 stub,pyarrow 冲突自然消失)。
- 首跑实测项(实施后必做,验收锚点):①CI `pytest --collect-only scripts/tests/` 收集通过 ②首绿(含现有 8 个算法用例不回退)③把 `scripts/test_ai_macro_hit_filters.py` 按 #201 薄包装入 `scripts/tests/`(本批2 交付物)④记录本次 CI 实际增量耗时(替换本报告预估)。
- 可选优化(非必需):`setup-python@v5` 加 `cache: pip`(+`cache-dependency-path` 指向新增的 CI 依赖小文件)可把 ~78MB 下载摊薄到首次。
- **反方案否决理由**:
  - B 扩 stub:上限只有"导入级"+无底洞+固化假对象范式(见 Q3);
  - A1''(只装 numpy+pandas,pyarrow stub 改成"拟真缺席":属性访问抛 ImportError):实测**也能全绿**(pandas 视角 `PYARROW_INSTALLED=False`,用例 13/13),但省下的 50MB 换来"模块存在却对 pandas 不存在"的两副面孔魔法,维护者极易踩坑 ⇒ 不值,不推荐(§5 一步到位准则);
  - 只给假 pyarrow 补 `__version__`:已实测运行期仍崩(Q2),直接排除;
  - (顺带评估)给 `app/compute/*` 补 `from __future__ import annotations` 使裸 stub 也够 import:不采纳 —— 改生产冻结模块(§23.7 需用户确认)且仍不能测算法,A2 下不需要(注解可正常求值)。

## 6. Q6 批2 另两项最小修法判定(不实施)

- **test_feishu_post(挂点=配置门控)**:CI 无 `config/feishu.json`(`.gitignore:70`)⇒ `load_feishu_config()=None` ⇒ `send_feishu` 在 `notify.py:799-809` 直接 `return False`;4 个发送用例中仅 `test_post_webhook_mode`(L134)自带 config patch,其余 3 个必挂。**最小修**:`SendFeishuPostTest.setUp`(L62-65)除现有 `_get_tenant_access_token` patch 外,增 `mock.patch("notify.load_feishu_config", return_value={"enabled": True, "mode": "app", "chat_ids": {"report": "oc_test", "alert": "oc_test", "agent_done": "oc_test"}})`(无需 app_id/app_secret:token/get 两处已被 patch,`_send_feishu_api:608-624` 全走桩 ⇒ 零外发);L134 的内层 patch 优先级更高,不受影响。
- **test_188(四类问题,最小修法)**:①`L273 ["sh", target, "force"]` → Ubuntu `/bin/sh`=dash,`BASH_SOURCE` 类语法直接崩(判定报告 §3.2 合成探针,exit 2),改 `["bash", target, "force"]`(CI 自带 bash 5.x;trap 语义/143 与 mac bash 3.2 的差异列入首跑实测);②`L128/180/213 test_verify_r2(td)/test_dead_key_filter(td)/test_ledger_gap_alert(td)` 带必填参数 → pytest 收集即 fixture 错:最小修 = 改名(如 `run_verify_r2`)+ 单一入口(把 `__main__` 块(含 L328-337 的 MATCH 顺序语义)抽成 `main()`)+ #201 薄包装;③**会话级污染(本文件今天不需要、入 CI 必炸他文件)**:`L243 sys.modules["notify"]=N`(假 notify 顶替真模块)、`L240-241 u.s3_head/_upload_glob`、`L78 os.environ["REPO"]=td`、`L331 MATCH=1` 全未还原 ⇒ 最小修 = finally 还原(或该文件走子进程隔离);④`[C]` 段 exec 生产脚本 `s06_snapshot.sh` 违反 §18 L50 精神(虽已 env 钉死 + PY=fakepy 拦截):最小合规 = 抽 `lib` 只 `source`(L50 同款手法)或保持 exec 但补"正面白名单"断言(exec 目标 == 显式声明的单一文件 + cwd/env 全在 tempdir)。

## 7. 已验证方法/数据源 + 诚实缺口

- 已验证手段:AST 静态闭包(自写脚本,零 import);6 组导入探针(ci_now / plan_a / plan_a_fix / plan_b / plan_b_magic / A1'' / A2,网络双阻断);venv 真库端到端模拟(A2);PyPI 官方 JSON 元数据(版本/requires_dist/wheel 尺寸,curl 实拉);`git ls-files`/`grep` 定点核查。
- 诚实缺口:①CI 实际增量耗时未实测(禁 pip 安装)②云上生产 venv 版本未核(本机两 venv 已知一致;implementer 可在云上跑 `python3 -c "import pandas,numpy,pyarrow;print(...)"` 核对)③pandas 3.0.3(venv)vs 3.0.6(CI 若不 pin 装最新)行为差异未验 ⇒ 故推荐 pin ④未实跑 CI ⑤业界实践无权威引证(渠道受限)。