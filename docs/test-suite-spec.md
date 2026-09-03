# 网站测试用例全集与验证规范(test-suite-spec)

> **创建**:2026-09-03,ZCode 代班秘书出具(资深黑盒+白盒测试视角)。
> **定位**:全站测试的唯一入口文档——三层用例(代码/算法/页面)+ 验证规范 + 多执行者交接规范。
> **与既有资产关系(不重复建设,分层引用)**:`docs/smoke-checklist.md`=数据产物层 P0 速查表(保留,本文 TC-DATA 系列引用它);`scripts/check_*.py|mjs` 22 个机检=自动化层(本文 TC-CODE 引用);`docs/kelly/analysis/scripts/*.cjs`=playwright 专项(本文 TC-UI 引用)。本文补齐的是:**用例分层组织、每条的可执行验证方法、结果记录规范、跨执行者交接**。
> **维护**:活文档。新功能上线/事故复盘/季度 review 时增改;变更走 git commit(尾注标执行者),新用例按 ID 规则追加(§7)。

---

## 0. 使用说明(执行者必读)

**适用执行者与读法**:
| 执行者 | 读法 |
|---|---|
| ZCode / Claude / opencode 等 agent | 全部用例可执行;命令类直接 Bash;页面类优先 Playwright,无浏览器时降级为「curl 数据层+min 字符串」双层验证并在报告标注降级 |
| 人工测试 | 页面层用例直接按步骤操作;命令类可复制执行 |

**用例格式**(每条固定字段):
`ID | 名称 | 优先级 | 前置 | 步骤 | 预期 | 证据要求`

- **优先级对齐项目分级**:P0=资金正确性/主功能不可用/数据损坏;P1=常用功能异常/明显回归;P2=边界/体验/性能;P3=锦上添花。
- **证据要求**:每条执行必须留证(命令输出/JSON 字段值/截图路径/console 摘录),**无证据=未执行**(对齐项目「验收铁律:不信自报」)。

---

## 1. 测试环境与前置

### 1.1 环境矩阵
| 环境 | 地址 | 用途 | 注意 |
|---|---|---|---|
| 本地后端 | http://localhost:8000 | 后端/数据层调试 | `--reload` 常驻,**不要杀进程**;无鉴权仅本机 |
| 生产主站 | https://ss.fx8.store | 主要验证对象 | curl 必须带浏览器 UA(`-A "Mozilla/5.0"`),裸 curl 被 307(memory live-index-curl-307) |
| 生产备站 | https://sss.sugas.site / s.sugas.site | 一致性验证 | 备站核心数据必须在位(§24④) |
| R2 | https://ssd.fx8.store/data/ | 大 JSON 分发 | 404 时走备站 ./data 兜底 |

### 1.2 开测前置检查(每轮必做,约 2 分钟)
1. **基准锚点确认**:读 memory `test-baseline-v112-anchor`(或 TASKS 当前状态段)拿当前测试基准版本。⚠️ 派算法层测试前必做——基准过时=全部结论作废(L31 教训)。非基准口径必须在报告显式声明。
2. **版本串现状**:`curl -s -A "Mozilla/5.0" "https://ss.fx8.store/?_=$(date +%s)" | grep -o 'app.min.js?v=[^"]*'` 记录本轮测试基线版本串。
3. **告警检查**:`tail -20 data/alerts/latest.md`,有未处理 severe 先上报再测(L46:事件驱动,latest.md 沉默≠无告警)。
4. **数据快照日期**:`python3 -c "import json;d=json.load(open('static-site/data/overview.json'));print(d.get('date'),d.get('collected_at'))"` 记录数据日期(测试结论绑定数据日)。
5. **多主控防撞**(agent 执行时):核实另一主控(Claude/ZCode)会话是否活跃;涉及改代码的测试必须走 feat 分支,严禁直接改 main 工作区。

### 1.3 硬约束(违者中断测试)
- **盘中(09:30-15:30)不跑全量 export/deploy**;盘后时点(15:35/16:00/17:50/20:35/22:00)不推 main 不写 public_fund.db(§14)。
- 只读测试(curl/grep/浏览器看)任意时点可跑。
- min 文件验证一律用**字符串/class 名**,不用变量名(memory verify-minjs-use-string-not-varname)。
- 测试产生的临时文件放 /tmp,禁止 git add -A。

---

## 2. 代码层用例(白盒)

### TC-CODE-001 全前端语法门禁 | P0
- 前置:仓库根目录。
- 步骤:`for f in static-site/app.js static-site/lab.js static-site/common.js static-site/sw.js static-site/purpose-notes.js; do node --check $f || echo "FAIL $f"; done`
- 预期:全部通过无输出(FAIL 行为 0)。
- 证据:命令完整输出。

### TC-CODE-002 既有单元测试全绿 | P0
- 步骤:`python3 -m pytest scripts/test_*.py -q`(或逐个 `python3 -m unittest`)
- 预期:10 个全过(notify/feishu/watcher/model_dispatch 等)。
- 证据:pytest 汇总行。
- ⚠️ 已知缺口:算法层无 pytest(评审报告 P0-1,见 §7 挂账)。

### TC-CODE-003 机检脚本分批执行 | P0
- 快机检(每次回归):`check_version_progress.py`、`check_data_integrity.py`、`check_fade_keys_alignment.py`、`check_universe_alignment.py`、`check_r2_consistency.py`
- 慢机检(发版前):`check_loss_rules_vs_mining.py`、`check_fade_predicate_parity.mjs`、`check_overfit_recent_parity.mjs`、`check_s06_freshness.py`、`check_s06_state.py`
- 预期:全 PASS;FAIL 任何一条=阻断,记录输出。
- 证据:各脚本退出码+关键输出行。

### TC-CODE-004 淘汰原因链路静态走查 | P1
- 背景:feat/kelly-elim-reason(8b741acb5)引入 `_elimReason` 链。
- 步骤:grep 验证四个不变量——①`_elimReasons` 与 `eliminated` 同源 filter 同序(lab.js 搜 `const _elimReasons = eliminated.map`);②挂载在 `_recompute`(t.slice 丢属性)之后(搜 `eliminated.forEach(function (t, i)`);③GIH 补集按 `_src` 引用对回(搜 `_gihKeptSrc`);④排序守卫 `if (!key) return`。
- 预期:四点俱在且顺序正确。
- 证据:各 grep 行号+行内容。
- 自动化替代:`node docs/kelly/analysis/scripts/kelly-elim-align-test.js` 全 PASS 即覆盖本条。

### TC-CODE-005 build 链完整性 | P0(发版前)
- 步骤:改任一前端源码后走 `bash scripts/main-merge.sh <feat>`;观察输出。
- 预期:统一 build_min(从 git HEAD 读源)+ bump 版本串 + check_version_progress 任务 A/B PASS + push main 成功。
- 证据:脚本输出含「✓ 版本串倒退/净回退校验通过」与「push main 成功」。

### TC-CODE-006 SW 壳芯配套 | P0
- 步骤:①`grep -n "CACHE_VERSION" static-site/sw.js` 取当前值;②与 index 引用版本串比对(`grep -o 'app.min.js?v=[^"]*'` curl 结果)。
- 预期:sw.js CACHE_VERSION 与 index ?v= 同步(部署后哈希==引用,§24⑤)。
- 证据:两个值并排。

### TC-CODE-007 敏感信息不泄漏 | P0
- 步骤:`git log -p --all -S "SENSENOVA_KEY" -- scripts/ | head -5`;`grep -rn "sk-\|Bearer [A-Za-z0-9]" scripts/*.py | grep -v "os.environ\|getenv\|\*\*\*" | head`。
- 预期:key 只在 trade-data/.env(仓外);代码/日志中 key 掩码(***);无明文 secret 进 git。
- 证据:grep 结果(应为空或仅 env 读取)。

### TC-CODE-008 代理健壮性 | P1(动代理后必测)
- 步骤:①`curl -s http://127.0.0.1:8899/healthz`(若无该端点=评审 P0-3 挂账确认);②观察 `/Users/linhuichen/code/trade-data/data/logs/sensenova-rotate-req.log` 尾部有无连续 429/400;③带 thinking 参数的合成请求打 `/v1/messages`(无 beta query)验证不 400。
- 预期:代理存活、无持续错误流、双客户端路径(Claude 带 beta/ZCode 不带)均 200。
- 证据:curl 状态码+日志尾部 10 行。

---

## 3. 算法层用例(白盒+数据)

> **总前置**:TC-ALGO 全系列先完成 §1.2 第 1 步(基准锚点),报告首行写「基准=vX.Y.Z」。所有回测数字结论必须绑定:基准版本+数据日期+口径(费率/卖出模式/K 档)。

### TC-ALGO-001 前后端回测对齐 parity | P0
- 步骤:`node scripts/check_fade_predicate_parity.mjs`
- 预期:全键 diff=0(历史基线 115 键)。
- 证据:输出汇总行(键数+diff 数)。

### TC-ALGO-002 loss_rules 单源三层一致 | P0
- 步骤:`python3 scripts/check_loss_rules_vs_mining.py`
- 预期:三层(规格↔挖掘↔前端标签)全 PASS。
- 证据:三层各自的 PASS 行。

### TC-ALGO-003 S06 状态机快照新鲜度与覆盖 | P0
- 步骤:`python3 scripts/check_s06_freshness.py && python3 scripts/check_s06_state.py`
- 预期:快照覆盖至今日、状态参数与冻结参数一致(threshold/confirm/minhold/lookback)。
- 证据:两脚本输出。⚠️ L45 教训:快照过期=动态功能死数据,必 fail。

### TC-ALGO-004 防前视(时点穿越)抽验 | P0(任何择时类改动后)
- 步骤:取一个历史切换点(如 2026-06-08 spread=-4.05% 破阈→06-09 生效 A),核对判定只用 t 前数据;分位阈值来源为 expanding/滚动(非全期分位)。
- 方法:读 `scripts/gen_kelly_mode_s06_state.py` 判定段+快照该行数据手算一遍。
- 预期:逐位一致;t 日信号次日生效。
- 证据:手算过程+快照对应行。

### TC-ALGO-005 universe 入样对称校验 | P0
- 步骤:`python3 scripts/check_universe_alignment.py`
- 预期:六断言全过(overview 标记⟺map 重算/候选⊆白名单/trades 无排除类/yaml⟺实际缺 key)。
- 证据:六断言输出。

### TC-ALGO-006 GIH 仿真三态 | P1
- 步骤:lab 打开 G/H/I 任一模式+开启 ai长线仓位管理,抽弹窗:①正常单(自然卖出)②强平单(sell_reason=强平)③缺价行(nav_missing 显「— 缺价」红字不进统计)。
- 预期:三态渲染正确;卡面 G/H/I 行 holding_count 与弹窗逐位一致(§22)。
- 证据:三行数据并排(卡面 vs 弹窗)。

### TC-ALGO-007 positionCap K 档口径 | P1
- 步骤:K=1 时抽一日:当日保留基笔数=1、每笔金额=资金池/1;s06p1 观察档(K=1 剔高评级)开/关注对比。
- 预期:每日池等分口径一致(与卡片/评级同口径)。
- 证据:抽样日的 kept 数与金额。

### TC-ALGO-008 费率预设语义 | P1
- 步骤:核对 sim 默认档=etf_def(万3/最低5/印花万5)与 lab 凯利 KELLY_FEE_PRESETS etf_main(免印花)差异展示正确。
- 预期:两处费率标签/数值各自正确,不串档。
- 证据:两处 UI 数值+代码常量行。

### TC-ALGO-009 过拟合监控 recent 口径 | P2
- 步骤:`python3 scripts/check_overfit_recent_parity.mjs`;抽一个 15 日窗口手算命中率对比卡片显示。
- 预期:banker's rounding 一致;维度切换数字对。
- 证据:手算 vs 显示。

### TC-ALGO-010 可操作性判定 | P1
- 步骤:GIH 关+任一 G/H/I 模式:弹窗顶部应显「⚠️ 本模式已淘汰·无法实操」note;峰持仓>20 万的行带删除线+角标。
- 预期:_kellyOpElimination 判据(峰值持仓≤20倍单次本金)展示一致。
- 证据:note 文本+角标行。

---

## 4. 页面层用例(黑盒)

> 执行方式:优先 Playwright(既有脚本见 `docs/kelly/analysis/scripts/*.cjs`);人工按步骤;agent 无浏览器时降级「curl 数据层+min 字符串」并标注。

### 4.1 首页

### TC-UI-001 首屏加载与 KPI | P0
- 步骤:打开 https://ss.fx8.store,等 3s。
- 预期:KPI 卡片全渲染、情绪分/信号数/AI 建议非空、console 无 error。
- 降级验证:`curl -s static-site/data/overview.json` 查 today.scores 9 key 非空+date=交易日。
- 证据:截图或 JSON 字段。

### TC-UI-002 AI 过滤视图(置灰+原因) | P0
- 步骤:开「仅显示可用信号」+AI 过滤,观察被淘汰信号行。
- 预期:被滤信号置灰**带原因标注**(非静默消失);开关关闭恢复。
- 证据:开关前后对比截图;kept 计数与列表基线分离正确(按钮计数宽松基线,列表完整链)。

### TC-UI-003 首页模拟回测弹窗 | P1
- 步骤:首页→模拟回测→弹窗展开交易记录表;点 ETF 代码列。
- 预期:表格 14 列不横向溢出(压缩后 min-width 1270);ETF 代码点击弹走势(复用 _etfTrendLite)。
- 证据:截图;min 串 `app.min.js` 含 `_etfTrendLite` 调用点。

### TC-UI-004 新闻看板自动刷新 | P2
- 步骤:停留首页>30min 观察新闻区;或改轮询时钟。
- 预期:自动刷新不叠加 DOM、无内存泄漏。
- 证据:console+DOM 节点数稳定。

### 4.2 策略实验室·信号凯利回测(核心区)

### TC-UI-010 lab tab 懒加载 | P0
- 步骤:切到信号凯利回测 tab,首次进。
- 预期:首屏 recent.json 快速出数(骨架屏),全量按年分片后台加载;无 69MB 单请求(Network 面板)。
- 证据:Network 截图(请求清单+体积);加载耗时。

### TC-UI-011 信号卡片→交易模式弹窗(主表) | P0
- 步骤:点任一信号卡片「交易模式」。
- 预期:弹窗出;顶部统计行(共N笔/胜率/总盈亏/费率消耗);主表 13 列;排序点击有效;ETF 筛选/盈亏筛选有效且**主表与淘汰区联动同筛选**。
- 证据:截图+一次排序前后行序。

### TC-UI-012 淘汰区+淘汰原因列(本套核心) | P0
- 步骤:同弹窗滚到下半部。
- 预期:①淘汰区 14 列,尾列「淘汰原因」三值之一(AI降亏/AI仓位/AI长线·满仓不买),行删除线但**原因列文字可读**(豁免 line-through);②统计行与标题动态在场标签(不在场不列);③原因筛选下拉只列在场原因,筛选生效;④淘汰区独立分页;⑤淘汰单不计入统计(总数=主表笔数)。
- 证据:截图;筛选前后行数;统计行文本。
- ⚠️ 回归锚点:feat/kelly-elim-reason(8b741acb5)+Claude 后续 af40be9f4(筛选下拉+该类盈亏统计)。

### TC-UI-013 GIH 开启态弹窗 | P0
- 步骤:开「ai长线(G/H/I)仓位管理」+选 H 模式,开弹窗。
- 预期:顶部「✅ ai长线仓位管理已套用」note;满仓不买被跳过的单出现在淘汰区且原因=AI长线·满仓不买(原先静默消失);强平单卖出原因=强平。
- 证据:note 文本+淘汰区含长线原因行截图。

### TC-UI-014 模式下拉 7 种与记忆隔离 | P1
- 步骤:lab 切 7 种模式各一次;刷新;再去首页/监控卡切。
- 预期:lab 记忆存 `tds_kelly_fade_mode`(18h 滑动过期,超时回默认 S06);与 sim 弹窗/首页/监控卡互不干预(四 key 独立)。
- 证据:localStorage 值并排(console `localStorage.getItem('tds_kelly_fade_mode')`)。

### TC-UI-015 ETF 走势 pin 弹窗 | P1
- 步骤:交易弹窗点行→走势弹窗;切「正式区/淘汰区」;点 pin;缩放拖拽。
- 预期:区切换重渲染、pin 高亮对应配对、缩放不飘移(dot 居中曲线点)、强平/淘汰事件标记正确。
- 既有脚本:`node docs/kelly/analysis/scripts/pin-zoom-smoke.cjs`(及 pin-ui-fix-render/pin-xn-aggregate)。
- 证据:脚本 PASS 输出或截图。

### TC-UI-016 三玩法表与水印 | P2
- 步骤:看三玩法表 G/H/I 行(A/F 行 K-OFF 态)+水印 hover。
- 预期:GIH off 时 G/H/I 行标「淘汰·无法实操」角标+hoverpop 理由;水印 TOP1/淘汰/分化与可操作层判定一致。
- 证据:角标截图。

### 4.3 跨站一致性与更新

### TC-UI-020 三域名版本一致 | P0
- 步骤:三域名各 curl index 取 ?v= 串。
- 预期:三站同版本串;核心数据文件(overview/board_etf_map)三站在位同内容(§22)。
- 证据:三串并排+两文件 md5。

### TC-UI-021 SW 更新无白屏 | P0(发版后)
- 步骤:发版后旧页面点更新/刷新。
- 预期:新版加载无白屏、无孤儿快照 JS error(Cannot read 'scores' 类为历史事故特征)。
- 证据:console 干净截图。

### TC-UI-022 移动端 | P2
- 步骤:iPhone 14(390px)/iPad viewport 开弹窗。
- 预期:可横向滚动使用;已知挂账:min-width 横滚边界待真机验证(外审 rev-20260831-002 P2)。
- 证据:截图。

### TC-UI-023 性能基线 | P2
- 步骤:lab 首屏 Performance 录制;快速切模式 10 次。
- 预期:无 >200ms 长任务(历史修复:988ms→0);快切 frozen 不出现。
- 证据:Performance 面板截图或 Lighthouse 数。

---

## 5. 验证规范(结果获取与记录)

### 5.1 结果三态
每条用例结论只能是:`PASS` / `FAIL` / `BLOCKED`(环境不可用/数据未就绪)/ `SKIP`(挂账或依赖未就绪,须注明原因)。

### 5.2 测试报告模板(每轮一份)
落档 `docs/test-runs/test-report-<YYYYMMDD>-<执行者>.md`:
```
# 测试报告 <日期> <执行者>
基准: vX.Y.Z(tag/memory 锚点) | 版本串: aXXX | 数据日期: YYYY-MM-DD | 环境: 生产三站+本地
## 汇总: PASS x / FAIL y / BLOCKED z / SKIP w
## FAIL 明细(每条: 用例ID+现象+证据+初判根因+建议)
## 证据索引(截图路径/命令输出)
## 挂账确认(本轮 SKIP 的挂账项)
```

### 5.3 证据硬规则
- 命令类:贴完整命令+关键输出(不裁剪 PASS/FAIL 行)。
- 页面类:截图(人工/playwright `page.screenshot`);agent 降级时必须双证:数据层 JSON 字段值 + min 文件字符串命中。
- 数字类:与展示位并排(卡面 vs 弹窗 vs 邮件,§22 N 位一致)。
- **改代码修 FAIL 后必须复测原用例+受影响邻域用例**(§23.2 自测完整),复测结果追加同报告。

### 5.4 回归策略(改动分级→最小回归集)
| 改动级 | 触发 | 最小回归集 |
|---|---|---|
| A 纯显示 | 文案/CSS | TC-CODE-001 + 涉及 UI 用例 1 条 |
| B 前端逻辑 | lab/app 逻辑 | TC-CODE-001/003/004 + 对应 UI 用例 + TC-UI-020 |
| C 数据/后端 | 产物/SQL/定时 | TC-CODE-003 全量 + smoke-checklist Part1 全部 + TC-ALGO 相关 + TC-UI-020 |
| 发版 | 任何 merge | + TC-CODE-005/006 + TC-UI-021 |

### 5.5 FAIL 处置
FAIL 不静默:报告登记→初判根因→(agent 执行时)上报主控/用户拍板修复→修复后复测闭环。P0 FAIL 视同生产事故优先级。

---

## 6. 交接规范(多执行者协作)

### 6.1 执行者适配
- **ZCode**:子 agent 派单 prompt 模板=「先 Read docs/test-suite-spec.md §<目标节> + 按用例执行 + 证据落 /tmp/agent-progress-<名>.md + ## DONE 汇总」;通道异常时主会话直接执行+报告标注降级模式。
- **Claude**:同上;页面用例可派 tester 子 agent+playwright;结果落 docs/test-runs/。
- **opencode 等外部**:只读仓库+本文件即可执行;命令类全可跑;报告写 docs/test-runs/ 并注明执行者(外审性质,结论供参考)。
- **人工**:§4 页面用例直接操作;证据截图存 docs/test-runs/assets/。

### 6.2 进度与状态
- 进行中:进度文件 `/tmp/agent-progress-test-<名>.md` 每步 echo(防卡死盲区)。
- 完成即落档:test-runs 报告 commit(尾注标执行者,git 可追溯)。
- 用例状态变更(新增/修订/废弃):改本文件+commit,message 注明 `TC-XX-NNN <变更>`。

### 6.3 防撞车
测试与开发并行时:测试只读任意;涉及改代码的验证(如 TC-CODE-005)必须 feat 分支+确认另一主控静止(§23.11/ZC-002)。

---

## 7. 挂账与已知测试债(诚实登记)

| # | 项 | 来源 | 状态 |
|---|---|---|---|
| D1 | 算法层无 pytest(loss_rules/凯利/S06) | 评审报告 P0-1 | 挂账待立项 |
| D2 | CI 无测试门禁(机检未挂 workflow) | 评审报告 P0-2 | 挂账待立项 |
| D3 | 代理无 /healthz+心跳告警 | 评审报告 P0-3 | 部分修复(4e92cb3ef 修 400/429,健康监控未做) |
| D4 | 移动端 min-width 横滚真机验证 | 外审 rev-20260831-002 P2 | 挂账(TC-UI-022) |
| D5 | kelly-lab 69MB 全量分片上线验收 | TASKS P1 | 需确认 feat/kelly-lab-lazy-load 上线态(TC-UI-010 覆盖) |

## 复现
- 本文件即规范本体,无独立生成脚本;用例内嵌命令逐条可跑。
- 取证基线:2026-09-03(版本串 a527 后,main 94d508c13);行号类锚点为当日 lab.js 版本,lab.js 迭代后以符号 grep 为准(不用行号死记)。
