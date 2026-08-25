# S06 · 大盘领先切换(首个动态降亏模式)实施报告

- **任务**: codex-task-20260825-001(B 级,用户已拍板),实施 agent 于隔离 worktree `agent-afb3ea18c2e3ff411` feat 分支完成
- **日期**: 2026-08-25
- **§5.4⑥ 判定**: **纯新增可选档,不改默认组合/算法 → 不动测试基准 v1.1.6**。默认档仍为 NEW14(`new14`),S06 仅在用户于四消费点手动选中时生效;不动基准定义、不发版本号。
- **一句话**: 新增「AI降亏·模式」第 9 个可选档 `s06`——唯一动态档,按大盘风格逐日自动切换基座(T 日收盘算中证1000−沪深300 近20日涨幅差,≤ −3.524% 次日切 A 进攻王,否则次日回 NEW14+1·15键),由生成器单源产出快照 JSON,前端只读不重算。

---

## 一、实现清单(文件与职责)

| 文件 | 动作 | 职责 |
|---|---|---|
| `scripts/gen_kelly_mode_s06_state.py` | 新增 | **唯一事实源**:冻结参数常量(THRESHOLD=-3.524224785046781 / CONFIRM_DAYS=15 / MIN_HOLD_DAYS=10 / LOOKBACK=20 / ON_BASE="a9" / OFF_BASE="new15")+ sticky_array 状态机 + 快照生成。头部 docstring 含目的/输入/输出/复现命令 |
| `static-site/data/kelly_mode_s06_state.json` | 新增(产物) | 快照:coverage 20141114~20260824 共 2863 行 daily(effective_mode/decision_date/size_spread),meta 带冻结参数与 `_provenance`(generator+inputs);current={date:20260824, mode:a9, since:20260609} |
| `static-site/common.js` | 修改 | ①`_KELLY_FADE_MODE_PRESETS` 追加 s06(dynamic:true,无静态 keys,排 new15 之后);②快照层 API:`_tdsS06StateEnsure()`(单例 promise,成功 dispatch `tds-s06-state-ready`/失败 dispatch `tds-s06-state-error`)、`_tdsS06BaseForDate(d)`(返回 {ok,base,decisionDate,sizeSpread} 或 {ok:false,reason∈not_loaded/load_err/out_of_range/no_row/bad_mode})、`_tdsS06FiltersForDate(d)`(per-date filters,直接套 a9/new15 键集)、`_tdsS06Status()`;③模式下拉 tooltip 补 S06 三档说明文案 |
| `static-site/app.js` | 修改 | 三消费点接入:首页信号 AI 降亏过滤(per-date 分支+fail-open 计数+slot 四态警示)、模拟回测弹窗(sim 下拉经 common 单源自动含 s06+警示条移出 wrap)、AI 监控卡(syncOverfitCharts s06 组集分支+守卫);另修 ready 重绘竞态 |
| `static-site/lab.js` | 修改(最小 diff) | 凯利区消费点:选 s06 时 per-date passesFade 走快照、口径区标「🧪 实验可选档·动态切换(非默认)」、fail-open 超覆盖期笔数红字警示。**最小 diff 说明**:并行 agent 正改 renderSigKellyLab 移动端卡片化,本任务对 renderSigKellyLab 主体零触碰,仅在其调用的 per-date 过滤路径(_labS06/_s6OpenCnt 变量区+matched 特派 L9600 区)加分支,冲突面最小化 |
| `static-site/purpose-notes.js` | 修改 | §21 公示:模式下拉说明补 S06 三档互证段(白话+场景+1:1 真实日期数字) |
| `scripts/check_s06_state.py` | 新增 | 机检四断言 A1-A4(见 §三),可挂 deploy 同链,FAIL 阻断签名(exit 非 0) |
| `README.md` | 修改 | §23.1② 功能亮点段补 S06 完整描述(L101 条目末尾) |

## 二、状态机口径(sticky_array,1:1 直白举例)

规则(全部只在生成器定义,前端零硬编码):
1. **T 日收盘判定,T+1 生效**:size_spread = csi1000_ret20 − hs300_ret20(%),防前视(只用 t 及以前数据)。
2. **off(new15) → on(a9)**:T 日收盘 spread ≤ −3.524%(小盘显著跑输,A 进攻基座前提成立)→ 次日切 A。
3. **on(a9) → off(new15)**:A 基座前提**连续破坏 15 个交易日**(spread > 阈值连计 15 日,broken 锁存直到切换)**且最短持有 ≥10 个交易日**,两条件都满足后的首个可用日次日切回防守兜底。
4. 首日恒 off;重跑生成器对历史段逐位幂等(输入不变则输出不变)。

**1:1 真实举例**(数字从快照 `daily` 逐位核实):
- **2026-06-08(一)收盘**:size_spread = **−4.05%** ≤ −3.524%(注意 6-04/6-05 的 −3.46%/−3.45% 都还没破)→ **2026-06-09 生效 A 进攻王**,保持至今(current=20260824 仍 a9,since=20260609)。
- **2026-04-27 收盘**:spread=−0.02%,此前 a9 段(2025-10-23 起)持有约 120 交易日,末段 spread 连续 > 阈值满 15 日且 held≫10 → **2026-04-28 生效 NEW14+1·15键 防守**。
- 全史共 **56 段**切换(20141114~20260824),首段 20141117 即入 a9(decision=20141114 spread −5.45%)。

⚠ 语义澄清(防误读):`decision_date` 行内的 `size_spread` 是该判定日当天的值,**不代表当天刚发生破位**——a9→new15 的切换由此前连续 15 日破坏序列驱动(broken 锁存),decision_date 只是 stay 条件最后满足的判定日。

## 三、数据验收(handoff §五逐条证据)

| 验收项 | 结果 | 证据 |
|---|---|---|
| 快照 effective_mode 与独立复算一致 | PASS | check_s06_state.py **A1**:check 内置第二套独立状态机实现(independent_state_machine),覆盖期/日历一致(2863 行)逐位相等,mismatch=0 |
| decision_date=上一交易日 | PASS | **A2**:2863 行时序无穿越(T_close_signal_T_plus_1_execution) |
| a9/new15 键集与预设逐位一致 | PASS | **A3**:两基座预设均在 `_KELLY_FADE_MODE_PRESETS`,s06 为 dynamic 且**无静态 keys**;`_KELLY_FADE_ALL_KEYS` 覆盖两基座全部键(防 per-date filters 缺键恒 false) |
| 阈值等参数单源 | PASS | **A4**:json 六参数 == 生成器常量逐位相等(threshold=-3.524);公示截断串(common.js tooltip + purpose-notes 各 3 处数值)在位 |
| 与 codex 同引擎对照误差 <0.5% | PASS | 早前会话已完成同引擎对照:验证段 2021 起 S06 净利 +93,813 vs 静态 NEW14+1 +83,718(+12.1%),回撤 -3,811 vs -3,550(略深,诚实标注);引擎逐位核对通过 |
| 功能锚点 | PASS | ①2026-06-09 生效 a9(decision=20260608 spread −4.05 破位)②2026-04-28 生效 new15 ③current=20260824 a9 since 20260609——浏览器层 `_tdsS06BaseForDate` 实测三点全中(smoke 断言 1-3) |

机检复现命令:
```bash
python3 scripts/check_s06_state.py            # 全 PASS 输出 4 项断言明细, exit 0
```

## 四、四消费点浏览器级 smoke(Playwright)

环境:`/tmp/s06_smoke_setup.sh` 搭 webroot(worktree js/html/css + trade-data 数据镜像 + vendor),8907 改动版 / 8908 HEAD 基线对照,no-sw 页面(route abort 断供测试需要,SW 会接管 fetch 使 route 失效)。

**主 smoke `/tmp/s06_smoke.js`:23/23 PASS**;**补充 smoke `/tmp/s06_smoke2.js`:5/5 PASS**;监控卡专项 `/tmp/s06_ovcheck.js`:PASS。

| # | 消费点 | 验证内容 | 结果 |
|---|---|---|---|
| 1 | 首页信号 AI 降亏过滤 | 选 s06 后 slot 四态文案(加载中/N 笔超覆盖期 fail-open/生效中/不可用);per-date filters 生效(f609.bull=true=filters 对象非 null,f0428.tierNone=true=new15 键集特征) | PASS |
| 2 | 凯利区(lab) | 两级导航进 sigkelly→选 s06→口径区「🧪 实验可选档·动态切换(非默认)」;手动勾任一键→变「⚙️ 自定义(手动勾选生成)」不再显 S06;超覆盖期 7370 笔 fail-open 红字可见(数据核实=覆盖期前早期段,预期行为非 bug) | PASS |
| 3 | 模拟回测弹窗(sim) | 下拉含 s06(经 common 单源);窗口 2026-01-26~2026-08-24 下 **new14=29 笔 vs s06=49 笔**(per-date 动态生效的直接数字证据) | PASS |
| 4 | AI 监控卡 | overfit-fade-mode-sel 在 DOM 且含 s06 选项;选 s06 后无 JS error(组集分支守卫在位) | PASS |
| 附 | TTL 到期回落 | localStorage 写 19h 前(>18h TTL)→ select.value 回落 new14,mem=null | PASS |
| 附 | 断供降级契约 | route abort 断 kelly_mode_s06_state.json → 该笔 fail-open 不拦截 + 红字警示可见,**绝不静默退回其他模式** | PASS |
| 附 | JS error 基线对照 | 改动版 vs HEAD 版 @8908 双跑,均仅既有噪音(`Unexpected token '.'`),无新增错误 | PASS |

## 五、smoke 揪出的 4 个真 bug(§23.2 三铁律自验记录)

| # | 现象 | 根因 | 修复+同类排查 |
|---|---|---|---|
| 1 | 首页 s06 态首次渲染整块崩:`Cannot access '_homeS06FailOpen' before initialization` | **TDZ**:_homeS06FailOpen 的 let 声明位于 popItems 统计循环(调 _isAiFadeHit)之后,function 声明提升但体内引用后置 let 在声明行执行前是 TDZ | 声明前置到 _aiOnS06 处+TDZ 注释;同类排查:grep 其余 s06 相关变量(_aiOnS06/_homeIsS06 等)声明序,确认无同类 |
| 2 | s06 态 open=2042 全 fail-open、快照永远 not_loaded | 首页只用同步判定函数 `_tdsS06BaseForDate`,它按契约不触发 fetch,无人发起 ensure → 静默全量降级 | 渲染尾部(kind==="signal")幂等发起 `window._tdsS06StateEnsure()`,ready/error 事件接管后续重渲;同类排查:四消费点逐一确认各自发起或共享同一 ensure 单例 |
| 3 | ready 事件后 mount 文案填进旧 slot、新 slot 恒空 | `_rerenderSigCardContent` 是 async,settle 前 remount 被旧 DOM 吞掉(竞态) | promise 化统一 sync/async,settle 后统一 remount + 1200ms 兜底;手动 dispatch ready 复验能填上 |
| 4 | sim 弹窗警示条消失 | `_tdsFadeModeSelectMount` 用 innerHTML **覆写整个挂载点**,放 wrap 内的 note span(含既有 sim-feat-note)被静默冲掉 | 两个 span 移到 wrap 外+注释;举一反三:grep 所有 fade-mode-wrap 消费点的兄弟提示元素,确认无同类受害 |

## 六、上线与待办(主控侧动作清单)

- **本 agent 只 commit + push feat 分支,不 push main、不自行 bump 版本串、不跑 deploy**(机制 C/D:merge 由主控走 `scripts/main-merge.sh <feat>` 统一 build_min+bump_asset_version+bump sw.js CACHE_VERSION+push main)。
- **R2 待办(§22 三步)**:`kelly_mode_s06_state.json` 是新数据类别,merge 上 main 后须随 `bash scripts/deploy.sh` 走 static-site/data 正常渠道推上线并上传 R2(ssd.fx8.store),前端 fetch 路径与现有 data 同源无需额外配置。
- **邮件链路显式声明:S06 暂不启用**。`check_signals.py` 不动(邮件白名单维持 v1.1.6 口径),S06 仅前端四消费点可选;若未来要上邮件链路,属动默认行为,须用户另行拍板(§23.7)。
- **并行 agent 提示**:凯利移动端 B 方案 agent 正 rebase origin/main 改 renderSigKellyLab 区域;merge 本 feat 时如遇 lab.js 冲突,以「renderSigKellyLab 主体归移动端改造、per-date s06 分支归本 feat」为界,冲突勿静默(§23.11)。

## 七、已知边界(诚实标注)

- 快照 coverage 自 20141114(csi1000 可得性)起,凯利全史交易自 20110119 起 → 覆盖期前约 **3,960 笔** fail-open 属预期可见降级(红字警示列明笔数),不是数据缺失事故。
- S06 对照优势(+10,095)来自验证段 2021 起,最大回撤比静态 NEW14+1 略深(-3,811 vs -3,550),公示已如实标注;未做全维度穷举回测(§5.1⑤),作为实验可选档供实测,不作默认推荐依据。

## 复现

```bash
# 1) 重新生成快照(幂等,历史段逐位不变)
cd /Users/linhuichen/code/trade/.claude/worktrees/agent-afb3ea18c2e3ff411
python3 scripts/gen_kelly_mode_s06_state.py \
  --repo "$(pwd)" --git-repo /Users/linhuichen/code/trade-data \
  --out static-site/data/kelly_mode_s06_state.json
#    输入依赖: trade-data/static-site/data/index/csi1000-all.json + hs300-all.json(收盘序列)
#    关键口径: size_spread=csi1000_ret20-hs300_ret20(%); ≤-3.524224785046781(2016-2020 选段 q30 冻结)次日切 a9;
#              a9 侧连续 15 日破坏+持有≥10 日才切回 new15; T 收盘判定 T+1 生效

# 2) 机检四断言(独立第二实现复算/时序/键集/阈值单源+公示数值)
python3 scripts/check_s06_state.py --repo "$(pwd)" --data-repo /Users/linhuichen/code/trade-data
#    全 PASS exit 0; 任一 FAIL exit 1(deploy 同链签名)

# 3) 浏览器级 smoke(playwright, 需先搭 webroot+起服务)
bash /tmp/s06_smoke_setup.sh && bash /tmp/s06_serve2.sh &   # 8907 改动版 / 8908 HEAD 基线
node /tmp/s06_smoke.js      # 主 smoke 23 断言(锚点/四消费点/断供/TTL)
node /tmp/s06_smoke2.js     # 补充 5 断言(TTL 回落数字/sim per-date 29 vs 49 笔)
node /tmp/s06_ovcheck.js    # 监控卡专项
```

- 数据截止:指数收盘至 20260824(coverage_end),generated_at=2026-08-25T07:16:27
- 版本基准:v1.1.6(has_track 补 null 卡1982/X1剔none+null/tag@91303132b),本 feat 基于 worktree base commit(见配套 commit message),纯新增不改默认
