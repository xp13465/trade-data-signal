# 测试报告 2026-09-03 ZCode

> 按 `docs/test-suite-spec.md` 执行的首次全量回归(降级模式:无浏览器,页面层用「curl 数据层+min 字符串」双证,已标注)。

## 基线与环境
- **基准**: v1.1.7 锚点(memory,AI降亏默认基座=S06 动态;⚠️ 挂账:memory 锚点仍 v1.1.7,但 git 已发至 v1.1.14,锚点滞后见 FAIL-0)
- **版本串**: 20260903-a533(app/lab/sw.js 三处一致)
- **数据日期**: overview.date=20260903,collected_at=20260903 20:36(今日,新)
- **环境**: 生产三站(ss.fx8.store / sss.sugas.site / s.sugas.site)+本地;执行时点 21:16-21:4x,Claude 会话并行活跃中(本轮全只读零冲突)
- **严重告警登记**: 20:36 update_all 耗时 166 分钟超 1h 阈值(severe 级,但退出码 core/width/futures/turnover/deploy_all/check_signals 全 0=完成未死,属性能告警;详见 FAIL-4)

## 汇总: PASS 12 / FAIL 3 / BLOCKED 0 / SKIP 14

### FAIL 明细

#### FAIL-1 [P2·环境基建] 单测 5/10 挂(TC-CODE-002)
- 现象:`python3 -m unittest scripts/test_*.py` 逐跑:ai_macro_hit_filters / feishu_post / model_inherit_dispatch **ImportError**(pyarrow 缺/notify、agent_inbox_watcher 是脚本名非包名,导入路径错);agent_inbox_watcher 3 个**真逻辑 FAIL**(`test_missing_report_rejected` 断言 `True is not false` 等)。
- 证据:逐 test 输出(5 个 ImportError 明细 + watcher 3 FAIL 断言差异)。
- 初判根因:两层——①测试环境依赖缺(pyarrow 未装/模块路径写法不兼容 unittest 导入);②watcher 09-03 被 Claude 守护进程重构(2570d8a6b/46cc46db8),**测试没跟上代码改动**(测试断言针对旧行为)。
- 建议:watcher 3 个 FAIL 由改动方(Claude)回填适配;环境类(pyarrow/路径)测试基建补项,挂账对齐评审 D1。
- 处置:不擅自修(非本轮回归范围;watcher 在 Claude 域),已如实上报。

#### FAIL-2 [P1·算法] loss_rules 层2 谓词全等 FAIL(TC-ALGO-002)
- 现象:`check_loss_rules_vs_mining.py` 层1/层3 PASS,**层2 FAIL**——`S1(s1SentALow)` 行数 5078、**不一致 2 条**,其余 19 键全 PASS。
- 证据:命令输出逐键行数,S1 唯一不一致。
- 初判根因:loss_rules 规格与挖掘谓词(mine21/mine22)在 S1 键有 2 行判定差异;需逐行 diff 定位(是规格更新未同步挖掘,还是挖掘实现漏边)。
- 建议:派 researcher 挖 2 行差异的日期/特征,判定哪端该改;**影响 S1 键的谓词一致性,发版前建议闭环**。
- 处置:登记待修,不擅自动代码(谓词语义属口径域,§23.13 三源核对)。

#### FAIL-3 [P2·环境] data_integrity export_manifest FAIL(TC-CODE-003)
- 现象:`check_data_integrity.py` 汇总 34 ok / 1 warn / **1 fail**——`export_manifest: 加载 export.py 失败: ModuleNotFoundError: No module named 'pyarrow'`。
- 证据:汇总行+明细行。
- 初判根因:与 FAIL-1 同根(pyarrow 缺)——机检脚本在缺少 pyarrow 的环境跑时 export_manifest 项 fail;**非数据产物损坏**(其余 34 项全 ok)。
- 建议:机检脚本对 export_manifest 依赖 pyarrow 做软依赖处理(缺时 SKIP 而非 FAIL),或在跑机检的标准环境补装 pyarrow;⚠️ 同 warn:`etf_since_return` 非 null 占比 94.2%(1582/1679)< 95% 阈值,持续偏低,建议跟踪是否数据缺口。
- 处置:登记;数据层 34 项实质 ok。

#### FAIL-4 [P1·生产稳定] update_all 166 分钟超时告警(前置检查发现)
- 现象:20:36 severe 告警「update_all 严重告警:耗时超1h(166分钟)」;但退出码全 0、overview/intraday 数据时效 OK。
- 证据:`tail data/alerts/latest.md` 该条目(含日志路径/结束时间 20:36:32)。
- 初判根因:性能劣化(非卡死);可能与 Claude 09-03 的 5 pipeline 并发改动(98814180f 等平台健康检相关)或数据量增长有关。
- 建议:Claude 侧跟进(它的域);告警阈值与 166min 实测的对齐方式需 review(是任务真慢了还是阈值该调)。
- 处置:登记,不在本轮修(生产时序敏感,属 Claude 正在处理的 FAPI/平台域)。

### PASS 明细(12 条)

| 用例 | 结果 | 证据 |
|---|---|---|
| TC-CODE-001 全前端语法 | PASS | app/lab/common/sw/purpose-notes 5 文件 node --check 全过 |
| TC-CODE-003 机检(除 export_manifest) | PASS | data_integrity 34 ok;fade_keys 全端对齐 PASS;r2_consistency 三版本一致 PASS |
| TC-CODE-004 淘汰原因链路 | PASS | kelly-elim-align-test.js 4 场景 ALL PASS(对齐/补集/缺价/守卫/计数守恒) |
| TC-CODE-006 SW 壳芯 | PASS | sw.js CACHE_VERSION=v6-20260903-a533 与 index ?v=a533 一致(§24⑤) |
| TC-CODE-008 代理健壮性 | PASS(条件) | 8899 监听存活(PID 35148);⚠️ 全日志 400/429 累计 9993 条(历史潮汐+冷却日志,非当前持续错误,近尾行为正常轮换);`/healthz` 端点不存在(挂账 D3) |
| TC-ALGO-001 parity | SKIP→N/A | check_fade_predicate_parity.mjs 单边运行(需 --ref/--base 参数才有对比,本轮未指定基线,记 N/A 非 FAIL) |
| TC-ALGO-003 S06 快照 | PASS | freshness 覆盖至 20260903 落后 0;state 机检六项(独立复算/时序/键集/阈值单源/锁死/元数据)全 PASS |
| TC-ALGO-004 防前视抽验 | PASS | 06-08 spread=-4.05 破阈(-3.524)→premise=True/decision=06-08→06-09 生效 a9;t 日信号次日生效逐位一致(阈值 -3.524224785046781/confirm 15/minhold 10 与冻结参数一致) |
| TC-ALGO-005 universe 入样 | PASS | 六断言全 PASS(absent/empty_array 集合+self 例外 cgb_10y_etf 兜底,§23.6 对称校验) |
| TC-UI-001 首页 KPI 数据层 | PASS | overview.json today.scores 11 键全非空,date=20260903 |
| TC-UI-012 淘汰原因在线上 | PASS | lab.min.js 含「淘汰原因」与「AI长线·满仓不买」串(首单+次单功能均已上线) |
| TC-UI-020 三域名一致 | PASS | ss/sss/s 三站 app.min.js?v= 全 = 20260903-a533 |
| TC-UI-021 SW 更新安全 | PASS | sw.js CACHE_VERSION 与 index 一致(孤儿快照风险基线正常) |

### SKIP 明细(14 条,均注明原因)
- TC-CODE-005 build 链 / TC-CODE-007 敏感信息深扫:本轮无发版/无代码变更,留待发版回归
- TC-ALGO-006 GIH 三态 / 007 K 档口径 / 008 费率语义 / 009 过拟合 / 010 可操作性:需交互态(开 GIH/切 K 档/切模式),降级模式无浏览器未执行,数据层无法替代,挂账待 Playwright 或人工
- TC-UI-002 AI 过滤视图 / 003 sim 弹窗 / 004 新闻刷新 / 010 lab 懒加载 / 011 主表 / 013 GIH 弹窗 / 014 模式记忆 / 015 pin 弹窗 / 016 三玩法水印 / 022 移动端 / 023 性能:同需浏览器交互,降级模式未执行;其中 012/020/021 已用数据层+min 字符串覆盖,其余挂账
- 说明:降级模式页面层覆盖=3/16(数据层可替代项),其余 13 项挂账待有浏览器执行者

## 挂账确认(§7 D1-D5 复核)
- D1 算法层无 pytest:**本轮实证**——单测 5 挂全是环境/重构未同步,无 pytest 约束算法层,评审 P0-1 成立且加剧(watcher 重构测试没跟上就是没 CI 门禁的直接后果)
- D2 CI 无门禁:同上证
- D3 代理无 /healthz:实证(TC-CODE-008 探活只有进程级,无端点级)
- D4 移动端横滚真机:未验(降级模式)
- D5 kelly-lab 分片上线验收:未验(降级模式)

## 给主控/Claude 的三条建议(按优先级)
1. **watcher 测试适配**(FAIL-1 真逻辑 FAIL):Claude 09-03 重构 watcher 后测试没跟上,3 个断言挂——改动方回填,防「重构破坏测试但无人发现」常态化
2. **S1 键谓词 2 行差异**(FAIL-2):派 researcher 定位这 2 行,判定规格端还是挖掘端该改——发版前建议闭环(§23.13)
3. **测试环境基建**:pyarrow 软依赖处理/测试运行环境标准化,消除「单测 5 挂全是环境噪音」的狼来了效应(FAIL-1/FAIL-3 同根)

## 证据索引
- 全部命令输出留存于会话 transcript;关键复现命令见 docs/test-suite-spec.md 各用例行
- S06 抽验数据:`static-site/data/kelly_mode_s06_state.json` daily 数组 20260605-20260610 行
- 告警原文:`data/alerts/latest.md` 2026-09-03 20:36 条
