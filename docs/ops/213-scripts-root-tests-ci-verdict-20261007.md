# #213 —— `scripts/` 根 `test_*.py` 逐个「能否入 CI」判定(2026-10-07)

> 本报告由 researcher 只读调研产出(#213);因 role agent 无 Write 工具,报告全文由主控落档。

## 0. 口径与硬约束(诚实标注)
- **全程未真跑任何 notify/feishu/upload_r2 脚本**(import 也没做):判定 = 读源码 + AST 静态解析 + `grep` + 两个**合成探针**(pytest 收集行为探针、dash 探针)+ 一个 **CI 环境模拟导入探针**(只 import `app.queries`,不涉及 notify)。
- 任务书写「11 个」,实物 **13 个**(`ls scripts/test_*.py`):多出 `test_193_r2_channel_coverage.py`(#201 已包装)与 `test_204_etfscore_loud.py`(无包装,漏在清单外)。已一并判定。
- 「本地过/不过」未实测(禁止真跑),判定基于代码结构 + CI 环境差异机制,**改 CI 前必须由 implementer 在 CI 首跑实测确认**(#201 做法:collect-only + 零外发自证)。

## 1. CI 挂载面与范式(锚点)
- CI pytest 命令:`/Users/linhuichen/code/trade/.github/workflows/ci.yml:112` → `python3 -m pytest -q scripts/tests/`(Job1 `quality-gate-static`,FAIL 阻断)。
- **memory `gate-mount-decision-ci-only` 判法**:命令路径 `scripts/tests/` 与 `scripts/test_*.py` **零相交** ⇒「只把文件搬进 `scripts/tests/` / 或加薄包装」即被收集,**不需要改 ci.yml**;反之若想让根目录 11 个被收集,必须改 ci.yml:112 且会连带收集非 pytest 形态文件(危险)。
- 现有 `.env` 垫片:`scripts/tests/conftest.py:96-104`(`GIT_REPO` → 临时 .env,4 个 dummy R2 键);bare pandas/akshare/requests/pyarrow stub:`conftest.py:54-79`;`REPO` 注入:`conftest.py:51`。
- #201 范式(推荐复用):`scripts/tests/test_193_r2_channel_coverage_pytest.py` —— 薄包装 import 原模块 + 调 `main()` + 接 `SystemExit` + 断 `PASS/FAIL` 计数(有 `_MIN_ASSERTIONS` 防 0 断言假绿)+ finally 会话卫生回滚;**零断言重复实现**。

## 2. 判定表(13 行)

| 脚本 | 顶层 import 生产模块/副作用? | 需 .env 垫片? | 真实外发链路(邮件/飞书/告警/R2 写)? | 若外发:打桩是否已证? | 判定 | 理由(锚点) |
|---|---|---|---|---|---|---|
| test_132_notify_tier_dedup.py | `import notify` L43;路径全指 tempdir L54-66 | 否 | **有外发面**,但用例走 `notify.main(--tier warning)` → `defer_warning` 入 buffer 不外发(`notify.py:2158-2164` 在 config 读取之前路由;tier 分支 L2164 → `defer_warning`) | 已打桩(dry_run 三态断言 + buffer/state 零写 L129-131/139) | **入 CI** | 需薄包装(模块级无 `main()`;`unittest.main` L297);用例是 `TierDedupTests`(非 Test 前缀) |
| test_188_s06_sync_blindspot.py | 顶层仅 stdlib L24-31;函数内 `import upload_r2` | **是**(自带 `_bootstrap_env_for_selftest` L46-64,CI 下靠 conftest 的 GIT_REPO shim 兜住,否则 `sys.exit`) | [C] 段**真跑生产 shell 脚本** `subprocess.Popen(["sh", scripts/s06_snapshot.sh])` L277 | 外发面已打桩(s3_head/_upload_glob/notify Fake L163-165/243);**但 exec 业务脚本本身违反 L50 精神** | **先重构再入** | ① `sh` 显式调用 → Ubuntu `/bin/sh`=dash,`${BASH_SOURCE[0]}` 直接 `Bad substitution`(合成探针: `/bin/dash /tmp/dashprobe/probe.sh` → exit 2),断言 `rc==1` 必挂;② 模块级 `test_*` 带必填参数(`test_verify_r2(td)` L124 等)→ pytest 收集/执行报 fixture 错;③ 不还原 `os.environ` REPO/GIT_REPO/MATCH(L78/331) |
| test_193_r2_channel_coverage.py | `import upload_r2` L39 | 是(conftest §④ 已覆盖) | 有(stubbed) | 已打桩+陷阱自证 L80-88/302 | **已入 CI**(2026-10-06 经 `scripts/tests/test_193_..._pytest.py`) | #201 已落,无需动作 |
| test_204_etfscore_loud.py(清单外) | `import upload_r2` L37(任一 cwd 可跑 L23) | 是(conftest §④ 已覆盖) | 有(stubbed) | 已打桩+陷阱自证 L54-84/215-219 | **可入 CI(照 #201 加薄包装)** | `main()`+`sys.exit`+PASS/FAIL 计数(L39-40/233);STATIC_DIR/ROOT 重定向 L127/153 |
| test_agent_inbox_watcher.py | `import agent_inbox_watcher` L24;**该模块 import 期 `raise SystemExit("OR_API_KEY required")`(agent_inbox_watcher.py:37-38)** | 否 | 无外发;唯一真 git 动作 `cleanup_ref` 的 `git update-ref` 被 mock 且 cwd=tempdir(L198-205) | 已打桩(`patch.object(w.subprocess,"run")` L144/161/177/198/293) | **入 CI** | 测试 L21 已先设 `OR_API_KEY`(必须在 import 前,否则 SystemExit=收集期崩);类名 `*Test/*Tests` 混用但 pytest 收集 unittest.TestCase 不看前缀(见 §3 探针);LockTest 依赖 CI 非 root(PID1 判定,非 root→PermissionError→判死,与断言一致) |
| test_ai_macro_hit_filters.py | `import app.queries` L36/38 | 否 | **无**(纯谓词+pkill`_ai_macro_feat_at` 置 None L30/58) | 不适用 | **先重构再入** | **CI 现环境必炸**(下节 §3 实测):conftest 的 bare pandas stub → `app/compute/normalize.py:13 -> pd.Series` 注解 AttributeError ⇒ 收集错误;另 `app.queries` 闭包含 akshare/pandas/requests/yaml(前 3 有 stub、yaml 已装) |
| test_feishu_post.py | `import notify` L18 + `import check_signals` L19 | 否 | **有外发面**(`notify.send_feishu` 全链) | 部分打桩:`_feishu_http_post_json`/`_get_tenant_access_token` L63/80/114,**3 个用例未 patch `load_feishu_config`** | **先重构再入** | CI 无 `config/feishu.json`(.gitignore:70,`git ls-files`=0;本地存在且 enabled=true/mode=app)→ `load_feishu_config()=None` → `send_feishu` 直接 `return False`(notify.py:806-812,`.env` 无凭证只 print 跳过)→ `assertTrue(ok)` 必挂 |
| test_feishu_ws_listener.py | `import feishu_ws_listener` L33(import 期闭包零第三方,静态核实) | 否 | 有外发面(飞书 API/notify),**但全部 patch** L90/111/130/236/268;不调 `run_listener`(不建长连接);TASKS_PATH 指 tempdir L155/170/… | 已打桩(FakeNotify L68 + 各 patch) | **入 CI** | 无 mac/云路径依赖;`lark_oapi` 是函数内懒加载且测试不触达 |
| test_notify_dedup.py | `import notify` L44 | 否 | 有(三渠道 send),**setUp 全 mock** L79-85;**spawn 子进程内重打桩** L435 | 已打桩(mock;无 trap 自证) | **入 CI** | 路径全指 tempdir L59-66 |
| test_notify_feishu_retry.py | `import notify` L22 | 否 | 有(飞书 API/notify_agent_done),patch token/post L31/86 + patch `notify.send`/`update_dedup` L107-129 + `DEDUP_FILE` → tempfile L101 | 已打桩 | **入 CI** | — |
| test_notify_flush_race.py | `import notify` L32 | 否 | 有(`flush_warning_batch` → `send()`),多渠道 mock L154-156 + spawn 子进程内重打桩 L105/…;路径 tempdir L160-170 | 已打桩(mock + 共享 sent 流水) | **入 CI** | 唯一风险:T1 三进程×5 轮、10s 栅栏(L86/98),CI 负载下可能 flaky → 首跑观察再定轮数 |
| test_notify_reply.py | `import notify` L14 | 否 | 有,全 patch token L20/post L32/config L56 | 已打桩 | **入 CI** | 最干净的一个 |
| test_queries_regression.py | `import app.queries/app.db/fetchers.load_config` L23-25 | 否 | 无 | 不适用 | **不入 CI** | ① `app.queries` 同 §3 必炸;② 依赖**生产 DB(`data/sentiment.db` untracked)+ `static-site/data/*.json`(git ls-files=0)**;JSON 缺失时 SKIP 且 `all_pass` 保持 True(L131-134)= **0 断言假绿**(违反 §18 L49 精神)⇒ 只适合人工/带生产快照形态 |

## 3. 决定性证据(可复核)

1. **`import app.queries` 在 CI 现配置下必败**(CI 模拟探针,stub 与 conftest 同款、block 掉 numpy/bs4 等):
   `AttributeError: module 'pandas' has no attribute 'Series'` at `app/compute/normalize.py:13` —— 注解在 def 时求值(无 `from __future__ import annotations`)。同类注解见 `app/compute/signal_stats.py:67`、`futures_position.py:39/67`、`rotation.py:20`、`signals.py:83…`。⇒ `test_ai_macro_hit_filters` / `test_queries_regression` 入 CI 的**先决条件**:CI `pip install` 加 numpy+pandas,或把 conftest stub 扩到 `Series/DataFrame`(二者择一,需拍板)。
2. **dash 探针**(合成 3 行脚本,非业务脚本):`/bin/dash probe.sh` → `Bad substitution`+`source: not found`,exit 2 ⇒ test_188 [C] 在 Ubuntu 必挂机制确认。
3. **pytest 收集行为探针**(本地 pytest 9.1.1):`NotifyReplyTest`/`TierDedupTests` 这类**非 Test 前缀的 unittest.TestCase 被正常收集**(`2 tests collected`)⇒ notify 家族「搬进 scripts/tests/」可直接被 pytest 收,不强依赖包装;但搬动会改 `Path(__file__).parent` 语义(靠 conftest sys.path 兜 import),**推荐仍用 #201 薄包装**(单一实现、原文件零改动)。包装 unittest 模块的写法:`importlib.import_module("test_xxx")` + `unittest.defaultTestLoader.loadTestsFromModule(mod)` + 断 `testsRun>=N and wasSuccessful()`。
4. **notify/check_signals/upload_r2 的 CI 可导入性已被现网证明**:`scripts/tests/test_196_*`/`test_alertchain_*`/`test_notify_r4_*` 已 `import notify`、`test_219` 已 `import upload_r2`;CI main `92fa551ad` 结论 **success**(GitHub API 实拉)。`notify` import 期第三方仅 certifi(try/except,notify.py:42-45)。
5. **`send()` 无 config 门控、门控在渠道函数内部**(notify.py:1017-1020)→ 直接 patch 渠道函数的用例在 CI(无 config)也成立 ⇒ flush_race/dedup 的 `sent_batch` 断言不受无 config 影响;**test_feishu_post 例外**(只 patch HTTP 层,不 patch config)。

## 4. 汇总 + 分批派单建议
- **入 CI:7 个**(132_tier_dedup / feishu_ws_listener / notify_dedup / notify_feishu_retry / notify_flush_race / notify_reply / agent_inbox_watcher)+ **已入 1 个**(test_193)+ **可入 1 个**(test_204,**清单外**)≈ 9 个动作项。
- **先重构再入:3 个**(test_188、test_ai_macro_hit_filters、test_feishu_post)。
- **不入:1 个**(test_queries_regression)。
- **批 1(低风险、直接薄包装)**:notify_reply / notify_feishu_retry / notify_dedup / notify_flush_race / 132_tier_dedup / feishu_ws_listener / agent_inbox_watcher + test_204 → 8 个包装文件,零改 ci.yml,每个带 `_MIN_ASSERTIONS` 下限。
- **批 2(需先决决策/改造)**:test_ai_macro_hit_filters(先拍板 pandas 方案)、test_feishu_post(加 `load_feishu_config` 打桩/fixture)、test_188(改 bash 显式调用、[C] 段换打桩、函数改名/包装、环境还原)。
- **批 3**:test_queries_regression → 维持人工跑(若要入 Job2 需生产 DB 快照,当前 DB untracked 不可得)。
- **每批验收口径**:CI 上 `pytest --collect-only` 先证收集 + 首跑实测绿 + 零外发自证(复用 L48 trap 模式;test_132/dedup/flush_race/feishu_* 目前是 mock 无 trap,建议包装里补「真实 notify.send 挂陷阱计数 0」断言)。