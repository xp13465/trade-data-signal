# #212 实施:R2 上传通道接 `on_fail` 告警(A 类 13 条 + data_files)

- 日期: 2026-10-07 | 任务: #212 实施(批 1 = A 类 13 通道 + 批 2 = data_files)
- 分支: `feat/212-upload-onfail-20261007` | base: `origin/main` @ `18f758e6c`(开工时;rebased 到 `0967fe413`,仅 docs 增文件、与本批零重叠)
- 依据: 调研报告 `docs/ops/212-channel-failure-matrix-20261007.md`(已合 main `18f758e6c`)
- 性质: 只接「失败 loud 化」告警,不动上传语义/口径/数据产物;**未跑任何真实上传、未触发任何真实通知**

## 1. 交付物

| 文件 | 改动 |
|---|---|
| `scripts/upload_r2.py` | 新增工厂 `_channel_on_fail`(L1775);13 个 A 类 cmd 接 `on_fail`;`cmd_upload_data_files` 失败分支命令级单点接 `_notify_channel_upload_fail`(label=`data-files`);14 处 docstring `#212` 注 |
| `scripts/tests/test_212_upload_onfail_loud_pytest.py` | 自验(CI 门禁 ⑧ 收集路径),43 用例 |

唯一挂点(未误判,报告 §关键证据点 1):`_incremental_upload` 的 `on_fail` **只在 `ok != total` 分支触发**(L1476→L1484 前),其后再 `sys.exit(1)` L1489。

## 2. §23.2 修完整:同类错误面清单(全量穷举)

**`on_fail` 扩展点定义处 / 调用点(全文件,共 3 类)**
1. 定义: `_incremental_upload(..., on_fail=None)` 形参 L1206 + doc L1231-1235;
2. 触发点: 引擎 L1484-1488(`if ok != total` 内,`sys.exit(1)` 前);
3. 工厂/回调: `_channel_on_fail`(#212,本批) + `_etf_score_on_fail`(#204 既有,未动)。

**`_incremental_upload` 全部调用点(15 处)——逐条是否挂 max**
| 调用点 | 通道 | 本批处置 |
|---|---|---|
| L778 | lab | ✅ 挂 |
| L1524 | trade-sim | ✅ 挂 |
| L1552 | trade-sim-json | ✅ 挂 |
| L1577 | index | ✅ 挂 |
| L1607 | etf-hist | ✅ 挂 |
| L1648 | fund-nav | ❌ 不挂(报告判定:唯一调用方已 severe,已有等价;未动) |
| L1677 | accum-nav | ✅ 挂 |
| L1712 | industry | ✅ 挂 |
| L1730 | public-fund | ✅ 挂 |
| L1863 | etf-score | 已由 #204 挂(`_etf_score_on_fail`,本批未动) |
| L1883 | kelly-parts | ✅ 挂 |
| L1904 | kelly-parts-sdc | ✅ 挂 |
| L1929 | kelly-snapshots | ✅ 挂 |
| L2008 | data-large | ✅ 挂 |
| L2188 | all-data | ✅ 挂 |

**`_upload_glob` 全部调用点(用于判「非引擎通道」)**
| 调用点 | 通道/用途 | 处置 |
|---|---|---|
| L1805 | offshore-fund | #193 已挂(未动) |
| L1827 | fund-score | #193 已挂(未动) |
| L2232 | intraday | ❌ 不挂(报告判定:两调用链均 severe) |
| L2377 | data_files | ✅ 挂(#212,批 2) |
| L3646 | cmd_verify_r2 内部对账 | 非上传通道(对账路径),不接 |

**`sys.exit(1)` 全量(19 处)分流** —— 与上传失败告警相关的仅 6 处(引擎 L1489 / offshore-fund L1812 / fund-score L1834 / intraday L2237 / data-files L2389 = 已挂或判定不挂;`large_json` L3309 自研上传器,报告判「机制不适用+已有 severe」);其余为 export-guard L1379、`verify-r2` L3528、`cmd_upload_db` L2646(私有桶备份)、dispatch/main L3809+ 等,**非「R2 上传失败」语义,未误接**。

**三类触达不到 on_fail 的退出路径(接线时防误判,均未挂)**:① export-guard L3/L5(L1379)② `total == 0`(L1472-1473)③ cmd 级前置「无 xxx json」(如 lab L774)。报告 §0.2 三类全部核实未误接。

## 3. §23.3 举一反三:复核三档判定 + 报告外发现

- **复核结论:报告三档(挂 14 / 不挂 3)成立,未改判**。14 条 = A 类 13 + data_files;B 类 `fund_nav`/`intraday`/`large_json` 三条不挂——`fund_nav`(唯一调用方 severe)、`intraday`(两调用链均 severe,含失败文件列表)、`large_json`(不走引擎/glob 的独立通道 + 私有桶非用户可见 + 唯一调用方 severe+heartbeat)。本批**未触碰**这三条。
- **报告外的真静默候选(列报主控,未擅自扩改)**:
  - `cmd_upload(local, key)`(L752,`upload <本地> <r2key>` 单文件点对点):失败仅 `print ✗`、**不 exit 非零、无 notify**。但它是**人工即时命令**(无任何定时/systemd 调用方;全仓 grep 仅用法示例,无 .sh 调用),失败当场肉眼可见 ⇒ 判定**范围外**(非「自动链静默面」),建议**不纳入** #212。若主控要「全站单点统一」可另单。
  - `cmd_upload_db` / `cmd_upload_decommissioned` / `cmd_upload_claude_backup` / `cmd_upload_large_json`:私有桶(signal-backup / signal-backup2)+ 管理用途,**前端零展示**,不在「用户读旧数据」判别面内 ⇒ 范围外。
- **预留位置遵循(§23.4)**:本批正是复用 #204 预留的 `on_fail` 扩展点(报告 §0.2),未新造机制;scan `docs/pending-features-index.md` 同模块项(#193/#204/#212/#218/#223/#228)无与本次改动文件重叠的在跑任务;`#212` 行(=待拍板)状态列未改(状态权威归主控)。

## 4. 自测结果(§18 L48 打桩,零真实外发)

命令:`/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_212_upload_onfail_loud_pytest.py`
结果:**43 passed**(逐通道参数化)。

负控逐条(验收口径全覆盖):
- ①「真失败 → 仍告警 + 仍补传」:`test_a_failure_alerts`(13 通道各 1 例)—— 打桩 `_upload_glob` 返回 `ok!=total` → cmd `exit 1` **且**恰发 1 条 severe(标题含通道+计数 / 「含义」= 本通道 note / 去重键 `r2_channel_upload_fail_{label}` / 窗口 21600),且 `put_calls` 非空=引擎真跑到上传步骤(打桩零真实 PUT)。`test_b_data_files_failure_alerts` 同口径(1 例)。
- ②「正常 → 不误报」:`test_c_success_no_alert`(13 通道,`ok==total`)→ 不 exit、零告警。
- ③「改前能复现静默 / 改后能告警」(病灶存在性对照):
  - `test_d_pre_change_engine_silent`(13 通道):同一场景**不传 `on_fail`** 调引擎 = 改前该通道行为 → `exit 1` **且零告警**;
  - `test_b2_data_files_pre_change_counterfactual`:屏蔽新增 notify 调用 → `exit 1` + 零外发(= 改前形态);
  - `test_e_pre_change_source_static`(仅未提交态可得,CI 自动 skip):HEAD 版源码 `_channel_on_fail` 计数 **0**、`data_files` 失败分支无 notify,且 `on_fail=_etf_score_on_fail` 恰 1(#204)⇒ **13 通道 + data_files 改前确实静默**的静态证据;本机已实跑通过(未 skip)。
- ④**零真实外发证据**:每用例收尾断言 `not trap`(真实 `notify.send` 挂陷阱全程 **0 触达**);`_upload_glob` / `_backup_overwritten_keys` / `purge_cache` 全打桩;`ur.STATIC_DIR`/`ur.ROOT` 重定向临时树。**本次自测未产生任何真实邮件/飞书/告警,未跑任何真实上传/R2 写**。

**回归面(逐位不变)**:
- 成功路径:13 通道 `ok==total` 行为 = 上传 + purge,**逐位不变**(无新增副作用;`on_fail` 分支不进入);
- `on_fail=None` 默认态与改前等价:`test_d2_default_none_and_scope_locked` 断言 `_incremental_upload.on_fail` 默认仍 `None`;未接通道(fund-nav 等)零行为变化;
- 既有自验未破:`scripts/test_204_etfscore_loud.py` **21 PASS/0 FAIL**;`scripts/test_193_r2_channel_coverage.py` **40 PASS/0 FAIL**;全量 `python -m pytest -q scripts/tests/` **338 passed,1 skipped**。

**挂点数量锁定**:`test_d2` 机检 `on_fail=_channel_on_fail(` 计数 == 13、`data-files` 实参对 == 1(不多不少,改范围须同步测试表)。

## 5. 硬约束遵守

- ✅ 未真发任何通知(邮件/飞书/告警):`not trap` 逐用例断言;**自测未产生真实外发**(§18 L48)。
- ✅ 未真跑生产上传/R2 写:`_upload_glob` 全打桩,零真实 PUT/COPY/purge。
- ✅ `isolation="worktree"`;只 commit + push **feat 分支**,未 push main。
- ✅ 无顶层 `import` 副作用:测试仅 `import upload_r2`(conftest §④ 的 `.env` 垫片已覆盖 CI 收集期,#219 教训不复发);未新增第三方依赖。

## 6. 其他规范判定

- **§21 算法公示**:N/A —— 未改任何算法/评分/权重/阈值/匹配逻辑,仅新增失败告警回调。
- **§22 数据一致性**:N/A —— 未改任何数据产物/字段/口径;无 N 文件/N 缓存同步面。
- **§23.1 README**:N/A —— 未引用外部开源项目/库,非站点重大功能发布(纯后端运维告警接线)。
- **§24 前端防撕裂**:N/A —— 未改 app.js/lab.js/common.js/style.css/index.html,无版本串/bump 面。
- **§23.7 冻结契约**:未改任何已上线功能的默认行为/口径/数字;`_etf_score_on_fail`(#204)与既有 #193 调用点文案**逐字未动**;新增回调仅在失败分支额外发声。

## 7. 双告警形态(既有形态,非 bug)

`data_files` 挂后,对**已有 severe 的 9 个调用方**(nextday_plan / nextday_gap_check / update_lab / s06 / push_schedule_stats / gold_night / kelly_intraday_rerun 等)形成**双告警**:通道级即时(on_fail/命令级)+ 收尾聚合,二者**键不同、去重窗口不同**(通道键 `r2_channel_upload_fail_data-files` 21600s),属 #204 审认可的既有形态(#193 fund-score/offshore-fund 同理)。`data_files` 的增益面 = 补齐 2 条**明确静默**调用方(`fapi_bj_width_export.py` print-only、`intraday_snapshot.sh` 的 `signal_kelly_trades_intraday` echo-only)。

## 8. 诚实标注 / 限制

- 本批结论来自静态读码 + 打桩自测,**未在云上实跑真实上传**(纯自测约束)。
- 「改前静默」的证据:引擎路径是**同构对照**(唯一差异 = 传入的 `on_fail` kwarg,忠实等价改前);`data_files` 为**反事实对照**(屏蔽新增调用即复现零外发)+ 静态 HEAD 版对照;非「跑改前版进程」级实证,但三类证据互证。
- `data-files` 告警「处置」行给的是 `bash scripts/upload_r2.py upload-data-files`(该子命令需带文件名,提示为通用形态;body 已列出失败文件明细)。
- 每通道 `impact_note`(报告「失败后果」栏文案,已回填代码):
  lab=策略实验室参数/回测/权重表;trade-sim=模拟回测详情页;trade-sim-json=弹窗走势/统计卡;index=指数K线/情绪曲线叠图;etf-hist=ETF/标的弹窗长历史K线;accum-nav=全站净值走势(G/H/I 真实净值);industry=行业卡/行业详情;public-fund=公募筛选器/持仓分布;kelly-parts=弹窗凯利分片;kelly-parts-sdc=「当日收盘」口径分片;kelly-snapshots=lab 凯利演进曲线 + 首页 K 档评级;data-large=走势图/过拟合监控/模拟回测主档;all-data=AI 建议/每日前瞻/信号统计/新闻看板;data-files=随调用方而异(schedule_stats/北交所宽度/盘中凯利/lab_*/s06/nextday/feed.xml)。

## 9. 复现

```bash
cd <worktree>
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_212_upload_onfail_loud_pytest.py
/Users/linhuichen/code/trade/.venv/bin/python scripts/test_204_etfscore_loud.py
/Users/linhuichen/code/trade/.venv/bin/python scripts/test_193_r2_channel_coverage.py
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/
```