# #222「全量 trades 撤出每轮必变元数据」独立审查报告

- 日期:2026-10-11 | 角色:reviewer(独立审查,只读;未改代码,未 push/merge,未碰云上/R2/生产)
- 对象:`feat/222-trades-meta-strip` @ `14b2ce050`(worktree `agent-a4bc195e24d6e6227`)
- 输入:实施报告 `docs/ops/next-steps-w3b-222-exec-20261011.md` + 定性报告 `docs/ops/next-steps-w3-datacred-20261011.md`
- 方法:8 项必查逐条代码级复核 + 真实产物实证 + 测试实跑 + 历史版本对照 bisect

## 结论

**PASS(无 must-fix)**。改动方向正确、实现完整、影响面已穷举:主档+sdc 一次覆盖(共用 `main()`)、全仓消费方零降级、md5 稳定性经真实产物与测试双重实证、上传/verify 两把尺子合流自洽、"不动 B2 代码靠 mtime 回退"的设计经代码级核实成立。

- must-fix:0
- should-fix:1(测试夹具未覆盖新常态;测试面,非生产缺陷)
- nit:2(文案引旧字段)
- pre-existing 上报:2(与 #222 无关,已独立 bisect 定界,按 §10.3/§23.7⑤ 上报,不列为本改动缺陷)

## 逐项(8 项必查)

### ① 生成端剥离 —— PASS
- diff 全量核对:`14b2ce050` 改动 4 文件(3 生产 + 1 新测试),逐 hunk 核过。
- `signal_kelly_backtest.py`:`_build_outputs` 的 `trades_output` 撤 `generated_at`+`period_cutoffs`(L1686-1696 区),撤后仅剩 `{buy_amount(BUY_AMOUNT 常量), fields(TRADE_FIELDS), quadrants(数据本体)}`;同批 backtest 档 `output` 保留 `generated_at`(L1663)与 `config.period_cutoffs`(L1669)——展示链依赖,未误撤。
- sdc 档同源覆盖:`export.py` 第二子进程(`KELLY_BUY_NEXTDAY=0 --output ..._sdc.json --trades-output ..._trades_sdc.json`)走**同一个** `main()`/`_build_outputs` ⇒ 一次改动同覆盖(偏离 D 验证见④)。
- `_build_unique_tables`(KELLY_UNIQUE_EXPORT,默认关,L85)同款撤两键(L1804-1807 区),防口径分叉。
- 残余写点穷举:全仓 grep `trades-output|trades_path.write` ⇒ **唯一全量写点 = signal_kelly_backtest.py**(L2457 `atomic_write_text(json.dumps(...))`);parts 分片链路(#219)早已撤同类字段,本次仅同步注释(L2206-2230);`_dump` 为 parts 写盘内嵌函数,无独立顶层写点。
- 外部发送面前置核查:该脚本仅外发行情 GET(qt.gtimg.cn L880 / hq.sinajs.cn L899),无 R2/邮件/飞书发送;相关测试只写 tmp_path/tempfile。

### ② md5 稳定性实证 —— PASS
- 真实产物 `static-site/data/signal_kelly_trades.json`(86,254,426B)顶层键实测含 `generated_at`+`period_cutoffs`(病灶实证;generated_at=2026-09-22 11:20);行级时间戳泄漏扫描 = 0。
- 独立复算:以该真实本体按撤键后格式序列化,两轮(不同生成时刻)md5 同值 `3b794bfe46801f614e36abf7c42a0747`,与实施报告 roundA/B 逐位一致 ⇒ 报告数字诚实。
- 测试实跑复现:`test_222_trades_meta_strip.py` 6 passed(0.12s);(219+kelly_stats+212+loss_rules_20keys+222)合并 119 passed/1 skipped(0.29s)⇒ 报告自验数字复现无误;跑后 worktree `status --porcelain` 干净。

### ③ 消费方全仓反查(含 static-site/worker/check_*/调度)—— PASS
- B2(`check_data_gap_alerts.py` L1318-1345):`ts_cands=[mtime]` + `if generated:` 才 append + `min()` ⇒ 撤键后自动 mtime 单源,**零代码改动生效**(该段代码一层未动,diff 实证);"冻结值会触发 48h 误报"的取舍正确采纳。
- 展示链:首页槽位 `latest_posrating.json` 的 `date` 字段自生成(`kelly_posrating.py:919`,YYYYMMDD),与 trades 无关;`kelly_posrating.py:922` 已改 `backtest_doc.get("generated_at")`,两个调用方(`kelly_posrating.py:962` CLI / `signal_kelly_snapshot.py:204`)均传非 None 的 backtest 档 ⇒ 无 None 风险;`latest_posrating.json` 键集不变(common.js:577/595 读 `s.src.date`,无感)。
- LAB 侧:`lab.js:9341/11398` 及各 `_renderSigKellyBar` 调用点均读 `state.labSigKellyData` = `signal_kelly_backtest[_sdc].json`(保留 generated_at)⇒ 零改动正确(偏离 A 验证见④)。
- trades 顶层键的解析方:`lab.js:8697 _labKellyParseTrades`、`app.js:3775 _simParseTrades`、`signal_kelly_snapshot.py:152 scan_trades` 只取 `fields/quadrants` ⇒ 撤键无感。
- overfit_monitor:`L416 data.get("generated_at","")` → `L1862 trades_generated_at`,下游 0 个 .js 消费者(全仓唯一命中=写入点)⇒ 变 "" 无影响。
- 补充穷举(本轮新覆盖):`check_loss_rules_vs_mining`(读 mode A 行)、`check_universe_alignment`(读 quadrants 行)、`check_kelly_unique_restore/_parts_restore`(CLI 路径+行数据,0 处 generated_at)、`check_data_integrity`(仅注释 L1770)、`large_json_excludes`(parts 目录路径)、`nextday_plan_generator`(仅注释)、`signal_kelly_backtest_bond`(不写生产)、`app/queries.py`(仅注释)、`app/collector/etf_national_team.py`(仅 intraday 档,不同产物)、`gen_schedule_stats`/`schedule_monitor.sh`/`check_r2_consistency.py`(0 引用)、`worker/dataQuery.js`(读 brief/status,非 trades)、`export.py:1030`(boot.json `_meta`,非 trades)。
- `generated_at` 全仓枚举(19 个 py + 5 个前端/worker 文件)逐文件分类完毕:trades 消费者仅 B2 / posrating / overfit 三处,全部已核 ⇒ "trades 两键消费方 = 3 处"穷举成立。

### ④ 偏离验证 —— PASS(5 项全对)
- A/B/C(lab.js 无需改 + 报告首页/lab 描述不准):`lab.js:9682` 赋值链 `_labKellySummaryName()`=backtest[_sdc],9341 数据源=backtest 档;报告原文误标为 trades 档 ⇒ 偏离判定正确,lab.js 零改动成立。
- D(L1799-1802 非 sdc):该位置实为 `_build_unique_tables`(函数内),非 sdc trades;实施者识别正确并同步撤键(超任务书范围的正确覆盖);sdc trades 走共享 `main()` 判断正确。
- E(死常量+文档订正):`KELLY_BACKTEST_FILE` 全仓零引用(scripts/static-site/worker 全检,唯一提及=test_222 守护断言);L73 虚构依赖行与实现不符(实现只查 trades 文件)确为虚假,删除正确;文档头 L52 更正与实现一致。

### ⑤ 测试质量 —— PASS(附 should-fix S1)
- test_222 六例断言真:撤键存在性(c0 双向:trades 无 / backtest 有)、md5 稳定(c1 `_FixedNow` 钉时刻,两轮同 md5)、负控×2(c2 旧格式两轮必不同=证必要性;c3 backtest 两轮仍不同=证未过度撤)、unique 同款(c4)、登记点守护(c5 以源码字符串断言 posrating 改源 + gap 死码清 + B2 mtime)。`_ser` 序列化与 `main()` 写盘同款(`ensure_ascii=False, separators=(",",":")`)核对一致;c1 结果与真实产物独立复算逐位一致(防第二份实现漂移,E30/§5.4⑦ 精神)。
- 凯利家族回归 119 passed/1 skipped 实跑复现。
- **should-fix S1**:gap `--self-test` 的 kelly 夹具(L1904-1905)仍写**旧格式**(带 generated_at)样本;本改动的核心行为变化(B2 生产走 mtime 单源)无对应用例(L49「假样本养绿」同族预防缺失)。建议补"无 generated_at + `os.utime` 钉旧 mtime → B2 SEVERE"用例(可仿 case C2 的 utime 手法)。非生产缺陷,不阻塞。

### ⑥ §21 公示 + §22 一致性 —— PASS(附 nit)
- `purpose-notes.js`:`generated_at` 0 处,无指向 trades 元数据的公示文案 ⇒ "无需同步"成立。
- §22:首页/Lab 两展示位日期继续有值且语义不变(同轮次生成时刻),无降级;无多文件/多缓存不一致面。
- nit N1:`lab.js:10307`「AI 降亏组成对比」脚注静态文案仍写「数据版本 signal_kelly_trades generated_at=2026-08-23 05:09」——撤键后该字段在新产物中不存在(数值权威=`mine24_compare.json` 不受影响);建议后续编辑顺带改词,不阻塞。

### ⑦ 上传 / verify 链自洽 —— PASS
- data-large 判据(`upload_r2.py:1375-1379`,`_file_md5` 整文件)与 verify-r2(HEAD ETag vs 本地整文件 md5,`3660-3725` 区;trades 82.3MiB < 100MB `_MULTIPART_THRESHOLD`,单 PUT 路由 ETag=md5)两把尺子同源 ⇒ 内容稳则上传跳过+平日 verify 0 补传,判别力(本体真变/丢失)不降。
- 其它机制核查:`_is_all_data_excluded` 排除 trades 防双通道;parts 通道(#219)不受影响;`.gz` 不参与 R2(上传 glob `*.json`);`_main_pre_date_hash`(L1956-1982)只哈希 quadrants 行 ⇒ 盘中增量对账基线不受撤键影响;`sync_dev_from_r2.sh` META_KEYS 本就忽略这两键;worker headers.js:192 为路径级 TTL,无字段依赖。
- 一次性成本提示:撤键后首轮 md5 必变 ⇒ 首发仍全传一次(≈175MB,预期内);之后工作日才省。
- nit N2:`check_data_gap_alerts.py:1340` 告警正文「generated_at/mtime 已 N 小时未刷新」——实际已 mtime 单源(机制通述,可顺带改词;文档头 L52 本次已正确更正)。不阻塞。

### ⑧ 自由发现 —— 见"发现分级"之 pre-existing

## 发现分级

### must-fix:无

### should-fix
- **S1(gap 自测夹具未覆盖新常态)**:见⑤。测试面,建议与 P1 一并修。

### nit
- **N1**:`lab.js:10307` 静态脚注引已撤字段(见⑥)。
- **N2**:`check_data_gap_alerts.py:1340` 告警文本措辞(见⑦)。

### pre-existing 上报(非本改动引入;§10.3 不计为本改动缺陷,§23.7⑤ 上报)
- **P1:`check_data_gap_alerts.py --self-test` case A4 恒 FAIL(实跑 RC=1)**:
  - 现象:`[self-test] FAIL: case A4 state 应登记 t1+基线内部键, 实得 ['_accum_nav_baseline']`,共 1 项失败。
  - 机制:A4 的 stub `notify.py`(L2104-2106)空输出 exit 0;10-09 起 `_notify` 改 `notify_sent()` 判据(fail-safe:空输出→False)→ `ok=False` → state 不登记 → 断言必败(stub 未随语义更新,未输出「已发出」哨兵)。
  - 定界(独立 bisect):`14b2ce050^`(base)同 FAIL 同项;`4c9b41efb^` 全 PASS(「PASS: two-way 全过」)→ 断点=**4c9b41efb(2026-10-09)**;该 commit 对文件仅 3 hunk(import/_load_json/_notify 区),未碰 A4。#222 对该文件亦仅 3 处注释/死常量 hunk ⇒ 与双方无关的独立测试债。
  - 放大器:该 self-test 无任何自动执行方(CI/脚本/pytest 包装 grep 全无)⇒ 静默红至今。
  - 生产面判定:无生产缺陷(`_notify` 判据本身正确,stub 场景只存在于测试);建议修复=stub 输出哨兵(或 A4 改用 spy)+ 补 S1 夹具,合一个测试修复 commit。
- **P2:`overfit_monitor.py` load_trades docstring 与返回值不符**(声明 `(trades_by_date, mode_label)`,实际 `(by_date, generated_at)`;预存在,与 #222 无关,撤键后语义依旧、只是值变 "")。仅登记,建议后续顺带订正。

### 依赖项声明
- §23.7 用户拍板(字段集变更):由派单上下文给出(2026-10-11 拍板);reviewer 无法独立核验拍板记录本体,属主控台账责任面,如实标注。
- 上线后验收建议(主控 §0):首个工作日观察 data-large 轮「内容未变化跳过」+ verify 0 补传;并确认线上两展示位日期照常(§8 三查③)。

### §10.6 删除清单维度
本次改动为删除型(撤 2 键、删死常量、删文档错误行):逐项核验删除对象均零引用/与实现不符,删除安全无残留引用(存活提及仅 test_222 守护断言)。

## 证据附录
1. diff:`git -C <wt> diff 14b2ce050^ 14b2ce050 -- scripts/check_data_gap_alerts.py` → 3 hunks(文档头 L52/删 L73/删常量);`git -C <wt> show 4c9b41efb -- scripts/check_data_gap_alerts.py` → 3 hunk 区(import 区/_load_json 区/_notify 区),均不涉 A4。
2. md5:真实产物 86,254,426B;撤键后两轮 md5 `3b794bfe46801f614e36abf7c42a0747`(= 实施报告一致);行级时间戳泄漏 0。
3. 测试实跑:`/Users/linhuichen/code/trade/.venv/bin/python -m pytest scripts/tests/test_222_trades_meta_strip.py -q` → 6 passed;(219+kelly_stats+212+loss_rules_20keys+222) → 119 passed/1 skipped;py_compile 4 文件 OK;跑后 worktree clean。
4. gap self-test 三版本对照:当前(14b2ce050)RC=1 FAIL A4;14b2ce050^ RC=1 FAIL A4(同项);4c9b41efb^ RC=0 PASS。三次全程 temp 隔离、通知全打桩(输出实录「notify 未真发出(rc=0)」×2 = stub 命中,零真实外发)。
5. 关键锚点:`kelly_posrating.py` L919/L922;`check_data_gap_alerts.py` L1318-1345(+L1904-1905 夹具 +L2104-2106 stub);`overfit_monitor.py` L416/L1862;`lab.js` 9682/9341/8697/11398/10307;`app.js` 3775;`signal_kelly_snapshot.py` L152/L204;`upload_r2.py` L1375-1379/3660-3725。
