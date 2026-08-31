---
name: role-implementer
description: 实施 agent 专属规范 — 由 .claude/agents/implementer.md 的 skills 字段启动全文注入。含单版前端铁律(原 §9 全文)、算法公示同步(原 §21 全文)、上线操作细节(原 §8 操作层)、生产稳定时点(原 §14 操作层)、修 bug 三铁律操作化、实施专属教训蒸馏。共享核心(§6/§22/§5/§23/§8§14摘要/§18索引)在根 CLAUDE.md 自动注入,本 skill 只放角色专属。
---

# 实施 agent 专属规范(role-implementer)

> 本 skill 由 implementer agent 定义 `skills: [role-implementer]` 启动全文注入,确定性加载不依赖主动读。共享核心在根 CLAUDE.md(自动注入),此处只放角色专属规范 + 操作细节。

## 关联规范源(§23.8 skill 维护同步,2026-08-19)
- §3 push main 统一入口(agent 只推 feat)/版本串统一 bump/完成报告带 base commit → 根 CLAUDE.md §8「改完必须推送」+ §23.11(git 冲突绝不静默)+ 机制 C/D(防再犯,docs/conflict-overwrite-rootcause-2026-08-18.md)
- §3 开工强制 rebase + base 新鲜校验 → 防再犯缺口①(docs/conflict-overwrite-triggers-2026-08-18.md)
- §1 单版前端铁律(build_min/bump sw.js/export 路径同步) → 根 CLAUDE.md §24 前端部署缓存防撕裂
- §2 算法公示 → 根 CLAUDE.md §21
- §4 生产稳定时点 → 根 CLAUDE.md §14
- §5 修 bug 三铁律 / §6 举一反三 → 根 CLAUDE.md §23.2/§23.3
- §8 团队协作 → 根 CLAUDE.md §23.4
> 改了对应源头(§8/§14/§21/§24/§23.x/CLAUDE.md),顺着本节反向查同步本 skill。

## 0. quickstart 约定遵循检查清单(关思考补偿,2026-08-15 优化 P0-2 加)
> 执行 agent 常被配置 flash+关思考以省 token(省 97-99% output token),但关思考后对 B 级跨文件/约定遵循任务有降质风险(benvanik 数据:thinking 降 67-75% 时约定遵循违规 0→173 次),被 reviewer 打回=返工更费 token。本清单把实施 agent 最容易违反的规范浓缩成 8 条硬勾选,**开工前读一遍、完工自验逐条勾**,靠 prompt 不看 thinking 也守住核心约定。逐条对应的规范全文见下方对应节,参考实现见 `docs/agent-quickstart.md`。
- [ ] **§21 算法公示**:改算法逻辑/数值(评分/权重/匹配/分段),必 grep 前端公示文案 purpose-notes.js + app.js/lab.js(算法/跟踪分/TE/R²/IR/权重/百分位/match_method)同步改,不只 tooltip 实施点
- [ ] **§22 数据一致性**:改数据产物,必重跑 + 同步 static-site/ + R2(三步),N 展示位一致,不进根 data/ 目录
- [ ] **§23.2 修 bug 三铁律**:修完整(先列同类错误面清单)+ 自测完成(全覆盖)+ 排查同类(根因修,不逐文件补丁)
- [ ] **§23.3 举一反三**:做 A 主动覆盖同模式/同数据源/同组件所有消费点+相关展示位,不只用户点名处(自验列清单)
- [ ] **§24 改前端源码** app.js/lab.js/common.js/index.html:改完 commit+push feat,**不自行 bump 版本串**(机制 C:主控 merge 走 main-merge.sh 统一 build_min+bump,防多 agent bump 撞号);完成报告必带 base commit + 版本串前后值
- [ ] **§8 上线链路**:改完必 commit+push **feat**(commit message 加 Co-Authored-By 行);**禁止 agent 直接 push main**,merge+push main 由主控统一走 scripts/main-merge.sh(机制 D)
- [ ] **§23.5 新产物落档**:新增报告/脚本/数据当场落最合适目录+建/跟索引+git 已跟踪,不靠定期整理
- [ ] **§5.1⑥ 防前视铁律**(2026-08-23):实现择时/状态/信号类功能(前端重放或后端预计算同规)时,信号判定在 t 时点只能用 t 之前数据(t 收盘出信号次日生效);分位数阈值禁用全期分位(用 expanding/滚动窗口);复用特征库先核查固化口径。全文见 researcher skill §3.1
- [ ] **data/ 隔离**:不 add/提交根目录 data/(sentiment.db/etf_national_team.db/signal_stats.json 等留本地);static-site/data/ 走 deploy.sh 正常上线

## 1. 单版前端铁律(原 §9 全文,2026-07-15 web/ 弃用)
- 前端源码统一在 static-site/(web/ 已删,不再双写);app/main.py 挂载 static-site/ 到根 /,/api/* 读 DB 不变
- **worktree agent 不自行 bump 版本串**(机制 C,与 §3 同口径):改前端源码后,本地验证产物可用 `scripts/build_min.py` 确认,但**不 commit bump_asset_version 改动**——版本串统一由主控 merge 走 `scripts/main-merge.sh` 跑 build_min+bump(版本串唯一权威入口)。产物共 **8 对**(非 2 对):common/purpose-notes/kelly-review-notes/kelly-reports-content/app/lab 的 .min.js + style.min.css + lab.min.css;版本串格式为 `YYYYMMDD-a<N>`(非 md5 前 8 位),每次 bump 强制换新串
- 本地开发:`cd /Users/linhuichen/code/trade-data && /Users/linhuichen/code/trade/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000`(看页面+调API)或 `python -m http.server -d static-site`
- ⚠️ **uvicorn cwd 必须是 trade-data/**(2026-07-20 方案B,根治线上读滞后镜像):app/db.py 用 `.absolute()` 读最新主库 `trade-data/data/sentiment.db`(launchd 写 trade-data/data/),从 trade/ 跑读滞后镜像(仅 deploy.sh rsync 同步)致 export 漏数据;resolve 修复 f0f6df78 需 cwd 切 trade-data 才生效。trade-data/app 是 symlink 指向 trade/app
- ⚠️ **sw.js CACHE_VERSION 与版本串同源, 由 main-merge.sh 统一 bump**(2026-08-07 补 + 2026-08-19 机制 C 改造):否则旧 Service Worker CacheFirst 缓存旧 app.min.js 致用户拿不到新代码(硬刷后退回旧数据)。`bump_asset_version.py` 已内置把 sw.js CACHE_VERSION 同步为同一 `YYYYMMDD-a<N>`(与 index 同源,不再手工维护);**agent 不自行 bump**,由主控 merge 走 main-merge.sh 统一 build_min+bump(含 sw.js)
- ⚠️ **min 版 JS 验证用字符串非变量名**(2026-08-07 补):terser mangle 重命名 let 局部变量(_compBarsHtml 等),grep 验 min 版上线用 class 名/中文字符串(kst-comp-fill/分项构成/优秀)非变量名
- ⚠️ **export 输出路径同步**(2026-08-07 补,§9 cwd trade-data 衍生陷阱):export.py cwd trade-data 写 JSON 落 trade-data/static-site/data/,但 deploy.sh 从 trade/static-site/data/ 推 git,两路径不同步推旧版。export 后必须 cp 或确认 rsync 同步

## 2. 算法改动同步公示(原 §21 全文,2026-08-08 定,防算法公示与实施不同步)
- **核心一句话:改算法逻辑必须同步改前端算法公示文案**。算法公示是用户理解算法的依据,算法改了公示不改=用户看老规则误导,修复成本高(发现+返工)
- **触发**:任何改 track_score/评分/权重/分段函数/匹配规则等算法逻辑的改动(build_board_etf_map.py/queries.py/simulate_trade.py 等后端算法),必须 grep 前端算法公示文案同步更新
- **算法公示文案位置**:app.js/lab.js 中 track_score/跟踪分/算法/TE/R²/IR/权重/百分位/match_method 等相关说明文字(弹窗/tooltip/策略实验室公式展示)。实施 agent 须 grep 这些关键词找全所有公示点(调研 agent 产出位置清单落档 docs/ 供查)
- **验收口径**:算法改动 agent 自验须含「grep 确认公示文案已更新为新规则」,reviewer 须查公示同步。算法改了公示没改=验收不通过
- ⚠️ **已复发 2 次强化款(2026-08-10 教训 L18 / 2026-08-11 教训 L25;遵 §19 历史对照优化:复发不新开条,强化原条款)**:条款存在但 fresh context agent 仍不主动读(同会话降亏4toggle agent c818fddd3 做对了、费率 agent 963ba3881 没做——不能因"别的 agent 做过"假定本 agent 会主动做)。**防重犯:主控 prompt 每次都要显式列 grep 动作+文件名**(purpose-notes.js + app.js/lab.js 所有算法说明),不只引用"见§21";修一个数值要 grep 全站同一数值所有出现处同步改(同 §22 数据一致性铁律),不只 tooltip 实施点;漏=验收不过
- **历史教训**:曾算法改了公示没改用户看老规则,修复需重新定位所有公示点+更新+重新上线,成本高

## 3. 上线操作细节(原 §8 操作层,摘要见根共享核心)
- ⚠️ **push main 统一入口(防再犯机制 D,2026-08-19)**:agent 只 push **feat 分支**,**禁止 agent 直接 push main**。merge+push main 一律由主控走 `scripts/main-merge.sh <feat>` 统一入口(内含 base 新鲜校验 + merge + 统一 build_min/bump + §24⑤/check_version_progress + push main)。push main 不归 agent。
- ⚠️ **worktree agent 改前端源码不自行 bump 版本串**(防再犯机制 C,2026-08-19):改 app.js/lab.js/common.js/style.css 的 worktree agent **不自行跑 bump_asset_version.py**(多 agent 各自 bump 会撞号/stale bump,08-18 根因 §三.2),由主控 merge 时 main-merge.sh 统一跑 build_min+bump(版本串唯一权威入口,回归 08-13「merge 收尾统一 bump」模式)。
- ⚠️ **完成报告必带「base commit + 版本串前后值」**(防再犯机制 D,2026-08-19):agent 完成报告必须写明 base commit(开工时基于的 origin/main 或 merge-base)+ 改动前后版本串值(若改前端源码,记录改动前版本串,由主控 merge 统一 bump 成新值)。
- **开工强制 rebase origin/main + base 新鲜校验(防再犯缺口①,2026-08-19)**:worktree 或分支开工前先 `git fetch origin && git rebase origin/main`;提交前用 `git merge-base --is-ancestor origin/main HEAD && echo base-fresh || echo base-stale` 校验 base 新鲜(base 落后则先 rebase 再提交,防基于旧 base 提交静默覆盖最近改动)。
- 每次改完 commit + push feat + merge main + push main(不推=白干,别人无法验收);commit message 末尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`(注:merge main + push main 改由主控走 main-merge.sh,agent 只 commit + push feat)
- 不 add **根目录 data/** 下任何文件(sentiment.db/etf_national_team.db/signal_stats.json 保持本地 M / untracked 不推);**`static-site/data/` 是正常上线渠道**(deploy.sh 的 git add 只加 static-site/data/ + min JS,不碰根 data/)。后端新增 JSON 字段/新品种后**必须跑 `bash scripts/deploy.sh` 推数据上线**,否则前端读旧数据
- 线上 curl 验证/测试:任一域名(ss.fx8.store CF 主站优先 / sss.sugas.site GitHub Pages / s.sugas.site MaoziYun)验证到新版即算上线 OK,不卡单域名 404;`_headers`+br 压缩仅 CF 主站生效
- ⚠️ **force-with-lease / force push 是最后手段,不是首选**:non-fast-forward 优先 `git fetch + rebase origin/main + 重试 push`(deploy.sh L141-160 内置),rebase 失败 abort 等人工。**不得擅自强推,尤其 main**;确需强推须主控确认
- ⚠️ **deploy.sh `git add static-site/data/` 通配会带入工作区残留旧文件**(2026-07-20 事故根因):跑 deploy.sh 前确认工作区无旧版实时数据文件(尤其 intraday_snapshot.json);export.py 不生成 intraday_snapshot.json,工作区里的旧版会被通配带入 commit 覆盖线上新版
- ⚠️ **agent 推理"X 文件在 Y commit 里"前先核对**:用 `git show --stat <commit>` 或 `git log -- <file>` 确认文件实际是否在 commit 里、是哪个时点版本,不靠"Y commit 是 Z 时点跑的所以含 Z 时点数据"推理
- ⚠️ **"功能 done"三查清单(唯一权威,2026-08-11 AI 预测前端漏上线教训补)**:验收"已上线/done"必须三查齐:①main 链含 commit(git log origin/main 含 hash)②数据层生效(curl 线上 JSON 字段有值/无旧字段残留)③**前端展示层上线(curl 线上 app.min.js/lab.js 含新功能 class/中文字符串)**。只验①②不验③=前端代码写了但从未 commit main+上线,用户看不到。**reviewer 验本地 min ≠ 前端上线**,reviewer PASS 后主控 §0 必须补验③
- ⚠️ 交易日盘中(09:30-15:30)不跑全量 export + deploy(全量 export+deploy 限定交易日 15:35 后;周末/节假日休市例外可随时跑)。盘中 intraday-snapshot 走 R2 不推 main

### 3.1 R2 存储架构准则(原 §8.1,按数据类别不按大小)
- **R2 是存储架构的结构决策,不按单文件大小临时判断**。新数据类别从第一天就走 R2 架构(upload_r2 清单+前端 dataUrl R2 fallback),不等变大才补
- **走 R2 的类别(满足任一)**:①全量品种多(100+ index/31 industry/100+ trade_sim/1000+ public_fund) ②有大 range 历史序列(`-all/-5y/-3y` 单文件 >1MB) ③类别整体大(index 48M/industry 54M/trade_sim 268M/lab 109M)
- **走 CF Workers Static Assets 的小文件**:单文件 <100KB 且类别总量 <5MB 的状态/监控小文件(alert.json/daily_metric.json/schedule_stats.json/alert_analyze_*.json 等)
- **upload_r2.py 5 个按前缀命令**(upload-lab/upload-index/upload-industry/upload-trade-sim[-json]/upload-public-fund)+ **1 个大小阈值兜底**(upload-data-large >=1MB,exclude industry-/public_fund)。**新数据类别优先按前缀建独立命令**,不依赖大小阈值
- **前端 dataUrl R2 fallback**:大 range 历史序列 `-(all|5y|3y).json$` 走 R2 `data/` 前缀;其他 R2 类别用硬编码 `https://ssd.fx8.store/{prefix}/` URL
- **本地留引用**:upload_r2 上传后不删本地 `static-site/data/`;大文件可 `.gitignore` 移出 git
- **上线流程**:export.py 生成 JSON -> 末尾自动跑 R2 上传(EXPORT_SKIP_R2=1 跳过,deploy.sh 自己跑)-> git push 触发 CF deploy -> 前端 fetch
- **新数据类别上线 checklist(2026-08-11 定,同 §22 三步同步)**:写 `static-site/data/` 的生成器必须同时接 ①R2 上传(upload_r2 清单或 export 自动) ②staticdata 同步(**scripts/staticdata_sync.sh** 或跑 deploy.sh 覆盖)。尤其「只写 static-site/data + 调 upload_r2 不跑 deploy.sh」的独立生成器(如 gen_daily_brief.py),缺 staticdata 留旧版直到下次 deploy
- **判断 checklist(扫描 agent 用)**:①该类别是否有 upload-{prefix} 命令? ②前端 fetch 是否用 R2 URL 或 dataUrl 走 R2? ③upload-data-large exclude 是否含该前缀(防双副本)? 三条齐全=架构合规
- ⚠️**[2026-08-19 事故]盘中手动 upload/export 必须显式 REPO**:任何 agent 盘中手动跑 `upload_r2.py upload-intraday` / export 相关脚本覆盖 R2,**必须带 `REPO=/Users/linhuichen/code/trade-data` 前缀**(正确:`REPO=/Users/linhuichen/code/trade-data python scripts/upload_r2.py upload-intraday`)。
  - **为什么**:upload_r2.py `STATIC_DIR` 缺省回退 `ROOT`(=trade),带 REPO 才读到 trade-data 实时库。手动命令若忘带 REPO,STATIC_DIR 落到 trade/static-site,抓走 trade 侧旧库整体覆盖 R2 → 线上退回旧数据(事故 2026-08-19:8-18 旧库覆盖线上)。
  - **哨兵兜底**(upload_r2.py `cmd_upload_intraday` 开头 `_guard_upload_intraday`):「STATIC_DIR 在 trade 侧 + 交易日盘中(09:30-15:30 北京)」双条件同时成立 → abort(exit 2)拒传,打印正确手动跑法。定时链路(intraday_snapshot.sh)显式 REPO,STATIC_DIR 落 trade-data 侧,不触发。**方案4一致性兜底已废弃**(STATIC_DIR 由 REPO 一次性派生、源根恒一致,exit3 结构性死閪不可达),实际拦截只有方案2单一承担。
  - **关联规范源**:`scripts/upload_r2.py:33 STATIC_DIR 缺省回退 trade`(哨兵注释) + `scripts/intraday_snapshot.sh` 显式 `REPO=...; export REPO`(定时链路默认 REPO=trade-data)。改了 REPO 默认/STATIC_DIR 逻辑/交易日时段口径,同步此条款。

## 4. 生产稳定时点(原 §14 操作层,核心摘要见根共享核心)
- **任务冲突检查不应由用户提醒才做**:每次派任务/设 cron/推 main 前**必须主动查 launchd 定时任务清单**(`launchctl list | grep trade` + 查 plist `StartCalendarInterval`),列当日盘后任务时点确认不撞,并主动给用户时点建议
- **核心冲突类型**:①推 main(intraday-snapshot 15:35/20:35 + update-all 17:50 + deploy)vs 另一推 main = 互相覆盖事故 ②写 DB(评分/采集)vs 同 DB 任务 = DB锁/progress撞 ③采集脚本并发 = 限流空转
- **盘后定时任务时点(15:35/16:00/17:50/20:35/22:00)不推 main 不写 public_fund.db**;安全窗口 23:00 后无推 main/评分/采集任务
- **agent 只 push feat 分支,不碰 main**(机制 D):agent 不 push main,盘后时点(15:35/16:00/17:50/20:35/22:00 ±5min 缓冲)与 cron 任务撞车由主控 `scripts/main-merge.sh` 统一检查拦截,agent 无需也不得自行判断 main 时点(避撞=主控 merge 入口职责)
- ⚠️[2026-08-10 R2迁移阶段3 更新]盘中 push 代码 main 不避 intraday(intraday-snapshot 走 R2 上传不推 main);**仍避盘后 17:50 update_all deploy.sh 推 main non-ff 竞争**(deploy.sh 有 rebase 重试,non-ff 自动 rebase);盘中全量 export+deploy 仍禁(防覆盖 R2 实时数据)

## 5. 修 bug 三铁律操作化(原 §23.2,用户 2026-08-11 定)
- ①**修完整**:修一个 bug 前先全面调研同类错误面(用户报 1 个,先 grep 前端全量数据依赖+curl 多处状态码列全同类异常,不只听用户报的),根因修复不只表面症状
- ②**自测完成**:修复后必须自己全面测试(用户报的模块+同根因其他模块+跨展示位 §22 一致性),自验列测试清单,不"草率说修好了"
- ③**排查同类**:修完自查"是否还有其他同类错误"(同文件类型/同 fallback 链路/同上传通道的其他文件,如 signal_kelly 未传 R2,要查所有新数据类别是否都传 R2)
- **验收口径**:自验须含「同类错误面清单(与用户报的同根因的所有模块)+逐项自测结果」,reviewer 查同类覆盖,漏=验收不过
- 防重犯:①修 bug 前必列异常面清单,不直接上手修用户报的那几个 ②修复后自测清单全覆盖 ③根因层面修,不逐文件打补丁

## 6. 举一反三(原 §23.3,需求理解/做方案也要举一反三)
- **需求理解/设计/实施方案时主动举一反三**:用户点名做 A,方案要主动覆盖 A 的相关场景/相关位置/相关展示位(同类功能在哪也用同一模式、同一数据源/同一组件还被谁用、N 个展示位 §22 一致性),不只做用户点名的那一处
- **验收口径**:自验须含「同模式/同数据源/同组件还被谁用+相关展示位清单+逐项覆盖结果」,不只做用户点名处;reviewer 查举一反三覆盖,漏=验收不过
- 防重犯:①需求理解/方案阶段先列"同类消费点/相关展示位"清单,不全员覆盖不实施 ②只做用户点名处=违反本规范 ③与修 bug 三铁律③同源,一为正(修bug排查已坏同类)一为前(做方案覆盖未做同类)

## 7. 实施 agent 专属教训蒸馏(2026-08-12 用户定 §18 按归属拆分:21 条 = 过错 11 + 经验 10)
> 每条一行(锚点|一句话防重犯|归档行号),防重犯原文(含根因+场景+防重犯全文)在 `docs/archive/CLAUDE-errors-2026-08.md` 反追。**命中场景读本清单 → grep 锚点 → 归档原文**。零丢失校验:实施归属 = L03/L06/L07/L08/L10/L11/L16/L18/L25/L19/L27(11 过错)+ E01/E02/E04/E06/E08/E09/E11/E17/E20/E21(10 经验)= 21 条。通用/主控/调研/测试归属教训见各自文件,不经本 skill 注入。

### 实施专属过错(11 条)
- **L03 exclude偏离全量**:用户说"全量/全部"不擅自 exclude/清理,先确认 | archive:L15
- **L06 cherry-pick撞冲突**:切分支前 CronList+查后台 agent | archive:L18
- **L07 hoverpop方案试错**:方案先充分调研再实施,不边试边改 | archive:L19
- **L08 ETF拆档null归属**:归属/分类前复述口径确认,不靠语义猜测 | archive:L22
- **L10 lowconf过时规则**:改灯/样式体系遍历所有 return/分支,grep 所有 `return {cls:` 确认无过时拦截 | archive:L24
- **L11 需求加未要求改动**:理解需求不擅自加未要求的改动,不确定时复述需求确认 | archive:L25
- **L16 数据没上线R2**:新类别上线链路三步(①export.py upload_r2 清单 ②launchd 覆盖/deploy.sh ③backfill 补跑)→§22 | archive:L51
- **L18/L25 §21公示gap(已复发2次)**:改算法/数值必显式 grep purpose-notes.js + app.js/lab.js 所有公示点同步改 | archive:L60/L82
- **L19 前端重算对齐后端**:replay/recompute 自验取一个 signal JSON 逐字段对比后端(open_positions/rounds/equity_curve/summary),列对比表,不只对比 summary 总计 | archive:L61
- **L27 hooks子agent输入也抄送**:hooks 区分主会话 vs 子 agent,子 agent 输入不抄送 | archive:L84

### 实施专属经验(10 条)
- **E01 R2 purge分批**:R2 purge 每批 30 keys+批间 sleep,不一次全量 | archive:L55
- **E02 持有天数用交易日**:持仓 hold_days 改交易日口径 | archive:L56
- **E04 多卡全局互比水印**:UI 多卡比较用全局互比+双标识(蓝★+紫◆) | archive:L58
- **E06 em dash 用 sed**:Edit 含 em dash 行失败用 sed 行号替换 | archive:L62
- **E08 盘中 push 不避 intraday**:R2 迁移后盘中 push 代码不避 intraday | archive:L62
- **E09 分时轮询自愈**:分时 1min 轮询自愈机制(S1-S5+S9) | archive:L62
- **E11 兜底槽差异化**:多 launchd 槽位用 BACKFILL_SLOT env 通道差异化 | archive:L70
- **E17 0token hooks抄送**:hooks 0 token 抄送方案(2d1b9206e) | archive:L87
- **E20 飞书 listener 落盘**:外部消息→主控在 listener 层落盘+回执(02bd47f8f) | archive:L90
- **E21 全信号表双视图**:多因子系统拆分调试+结果双视图 | archive:L91

### 新增教训(非 archive 锚点)
- **动态/状态类功能·数据供给链路四件自检(2026-08-26 S06 快照教训,L45,依据 CLAUDE.md §18+§5)**:做动态切换/状态机/择时信号/任何"随时间变化的数据驱动"功能,交付自检必含**数据供给四件**:生成脚本→定时挂载(launchd/cron)→机检校验→过期告警,缺一=功能未完成不算 done;实现若取静态快照/手动生成等降级形态,**必须作为方向性分叉上报主控转用户拍板**(§5),拿不准算不算方向分叉=算,报。关联规范源:CLAUDE.md §18 锚点 L45/memory s06-static-snapshot-missing-daily-regen
- **涉档位/分类/阈值语义任务·开工三源逐字对照(2026-08-24 has_track 口径 P0,依据 CLAUDE.md §23.13)**:开工第一件事=逐字对照派单 prompt 附的 UI 文案+产品文档原文 vs 代码现状,对不上=停下上报主控,不照单全收;上游(挖掘报告/调研结论)的语义声明一律视为待验证假设而非事实(本案:X1 规格书把「整剔 none」当事实,实际设计口径=「剔 none+null」,照单落地致口径三版本事故)| 来源:memory has-track-caliber-p0-reflection

## 8. 团队协作:开发任务先查"已落档未开发功能"+ 同模块冲突预防(原 §23.4/23.5,2026-08-12 用户定,实施层核心)
用户原话"开发一个任务时是否会考虑到已经落档的其他调研报告出了但是没开发完成的功能?这应该也是一个要求。毕竟多个子agent应该是一个团队。你不能只顾管自己的开发工作。别人干的活和你懂的模块有关。就要提前考虑进去" + "现在主要靠主会话调度 分派任务。但是子agent其实也要有同模块功能的考量。更好的写作或预留好位置等" + "如果互相都考量到了。真碰到开发时。冲突问题应该也可以进一步得到缓解。否则2个任务对同一个模块对态度存在对立时。大概率是后者覆盖前者了。但这其实也不太对。然后反而还要碰到问题后找我确认。其实这一开始就应该暴露问题出来 又起现在有很多待办都是堆积的时候。等真开干了 很可能和实际项目存在脱节了。实施起来还要重新讨论。但开发人员因为知道有这么件事。提前留好了改造空间。就会和谐很多"
- **核心一句话**:多个子 agent 是一个团队,不能只顾自己的活。**开工前先查 `docs/pending-features-index.md`(已落档未开发功能索引,团队共享地图)**,凡"方案已出但未开发"的功能与本任务同模块/同数据源/同组件/同展示位的,必须提前考虑进去
- **预留位置(用户强调)**:实施时主动 scan 索引同模块项,写代码时**预留好位置**(接口/数据结构/配置位/展示位/常量表),或在与待开发功能相关的点留 TODO/注释说明"待某功能接入",不自顾自封死;发现与索引项相关但无法预留的,在报告里显式提出
- **同模块冲突预防(后覆盖前禁止)**:两个任务改同一模块(同文件/同数据源/同组件),不得各自闷头改后让"后完成者覆盖先完成者"。正确流程:①开工前查同模块占用(此模块是否另有任务在改→冲突第一时间上报主控协调=排队/约定共用约定/分区域) ②不默默并行,不闷头做到碰壁才找用户确认 ③独立 commit+分区,merge 前 §0/reviewer 核对无覆盖
- **待办-现状对账(防脱节)**:开做某待办前,先核对当前代码/数据现状与方案假设是否一致(pending-features-index 待办项依赖现状,项目变则项失效),不一致先更新方案(§5 调研)再实施,不硬套旧方案
- **验收口径**:自验须含「scan 了 pending-features-index.md 本模块项 + 已预留位置清单(或说明为何不相关)+ 同模块占用检查(冲突已上报协调)+ 待办对账(方案假设 vs 当前代码现状一致才动手)」;reviewer 查预留覆盖+冲突预防,漏=验收不过
- 防重犯:①开工前必查索引同模块项+同模块占用 ②只做点名需求、不查团队其他未开发方案=违反本规范 ③同模块后覆盖前=违反本规范 ④拿过时方案硬套=违反本规范;与 §6 举一反三互补:§6 查"现有已上线功能"的同类位,本节查"已落档未开发功能"的衔接位+冲突预防+待办对账

## 9. token 优化行为层(实施专属,2026-08-15 社区调研落档 §5.5 实施侧)
> 与共享核心 §5.5 互补:本节约实施专属子集(①不贴回已写文件 ②命令静默化 ④@文件引用);通用 6 条全量+来源收益见根 CLAUDE.md §5.5。每条带"收益"便于理解。
- **① 不贴回已写文件**:改完文件报结论时**不贴回文件全文/大段代码**,只给关键 diff 点/发生变化的行+最终状态。收益:省输出 30~60%。
- **② 命令静默化**:**git status --porcelain、git log --oneline、测试带 -q、日志 tail/截断、大 JSON 输出落盘不内联**(写 `/tmp` 或 `static-site/data/` 再 grep 而非整段打印)。收益:工具输出占上下文 ~60%,大幅压缩。curl 验上线仍按 §3 三查清单执行,只是输出裁剪不裁剪校验动作。
- **④ @文件直接引用代替 Read**:定位/回报用 `@文件路径:函数/变量/行号` 直接引用,能定位到行就不整文件 Read;查大文件(app.js 1.3MB)按 §16 subagent 耗时规范"定点 grep 看片段"评估,不无脑全量读。收益:省 Read+搜索,防无限探索。

## 10. 相关文件指针
- docs/pending-features-index.md(已落档未开发功能索引,开工先查本模块项)
- docs/agent-quickstart.md(按任务类型 A-F 的操作步骤速查,接任务先读对应类型)
- docs/data-deploy-quickstart.md(数据上线类速查)
- docs/main-governance.md(主控专属,实施 agent 一般不读,除非主控要求)
