# todolist(pending-features-index)全量治理盘查报告(2026-08-22 周末清账)

> 调研 agent 只读产出,**未改 pending-features-index.md 本体**。逐条核实=文档自述 + git commit 在 main + 数据产物/前端代码/线上 API 实测三重交叉。
> 用户核心诉求:"堆积太多都快忘记了"。本文供用户勾选拍板,后续由 implementer 执行。
> 盘点范围:pending-features-index.md 全部条目(含墓碑划线行),对照 tasks-done-list.md + docs/archive/TASKS-done.md + TASKS-history-archive-20260820.md 防漏。

## 一、总览统计

| 分类 | 条数 | 编号 |
|---|---|---|
| ✅ 可关闭(实际已完成未标注/已被覆盖) | **9** | #15/#91、#29、#42、#75、#79、#80(P2-15 子项)、#82(大部)、#83(大部)、#22 |
| 🔄 状态刷新(内容有效但描述过时) | **2** | #10、#83 剩余部分 |
| 🗑️ 建议废弃 | **2~3** | #88、#87(#85 二选一交用户拍板) |
| ⏸️ 保留远期 | **10** | #11、#12、#13、#14、#17(+21)、#19、#20、#86、#80 P2-10长期/P2-11 |
| 🧹 墓碑行格式清理(非功能) | ~18 行 | 划线条目统一移出表格留指针 |

**最大异常:2026-08-21/22 两天的会话把至少 7 条 pending 待办做完了,但一条都没回写状态**(详见第四节)。

## 二、✅ 可关闭清单(9 条,建议移入 done-list)

| # | 标题 | 现状核实证据 | 建议 | 理由一句话 |
|---|---|---|---|---|
| 15+91 | 凯利回测「次日开盘」口径(重复登记互指) | commit 371434fdc「回测默认买入口径切次日开盘(**v1.1.4**)」在 main;git tag v1.1.4 已打;lab.js L9846 前端已公示「v1.1.4 起默认=信号次日开盘」;907b76777 README 已补 | 关闭 | 待用户拍板的"是否切默认"已切完(v1.1.4),SOP 按钮②也早已上线(L9736),整项闭环 |
| 29 | R2 审计 P1 track_score 跨文件不一致 | commit 6e0f70eb6「增量门控纳入 board_etf_map + 全量一致性校验(**#29**)」在 main;check_data_integrity.py L44 注释「#29, 2026-08-22 全量两两对比」;基线漂移子问题已随 #26 废弃时定性"漂移极小" | 关闭 | 不一致已修+一致性门挂 deploy 链常态化;基线漂移已有定性结论 |
| 42 | 上下文优化 3 项(OPT-1/2/3) | OPT-3:CLAUDE.md 已含「Compact Instructions」段(grep 命中);OPT-2:2026-08-12 已做一轮(§5.3 记录 20.6KB→9.6KB,现 MEMORY.md 22.9KB 又回填);OPT-1:被 E17 hooks 0 token 抄送(2d1b9206e)+token-cache-stats 每日收尾(92c303963)+§5.5 行为层吸收 | 关闭(OPT-2 要重做另开新项) | 三件事要么落地、要么做过一轮、要么被更好机制替代,原条目已无指向性 |
| 75 | upload_r2.py REPO 读路径强校验 | commit a956cbe5a「REPO 缺省分级闸 **#75**, 防手动裸跑旧库盖线上」在 main;upload_r2.py L36-54 分级闸代码在(显式态放行/缺省拦截) | 关闭 | reviewer 当年"方案1 无兜底须再上"的诉求已实现 |
| 79 | 场外基金方案C 全量化 step1-8 | commit 28314d030「feat(**#79 方案C**) D1 服务端分页+详情弹窗 5 区块」在 main;step1 export_fund_score.py L59 九字段;step2 pf_score_weekly.sh L39 top_n=None;step3 wrangler.jsonc L37 FUND_SCORE_DB binding+sync_fund_score_to_d1.sh;step4 worker/fund_score.js;step5 app.js L22707 /api/fund_score 分页 fetch;step6 openFundScoreDetailModal(L23003);step7 统一 bump(1985b733f);step8 weekly L47 挂 sync+线上 curl /api/fund_score 返回 401 登录特权鉴权正常 | 关闭 | 八步全链路落地且已上线生产 |
| 80 | 全站性能 P2 中 **P2-15** 子项 | commit 4289d50a7「chore(**P2-15**): 停用 offshore_fund JSON 定时生成链(用户已确认)」在 main | P2-15 关闭;P2-10 长期/P2-11 保留远期 | offshore_fund dead weight 已按用户确认停链;P2-10 短期 requestIdleCallback 已上线(app.js 2 处)、P2-11 未实施(feat/p2-11-dapan-lazy 分支预开无新提交,renderAStock 无图表懒渲染) |
| 82 | 留言箱完整方案剩余 | 管理端审核页 static-site/admin/feedback.html 存在;4b384b473「留言箱管理端审核页+防滥用四层」+ f3f4cd838「管理员账号+头像菜单管理端入口」均在 main;防滥用四层代码 worker/auth.js L731-796(频控/honeypot/内容约束/审核闸门)实锤 | 关闭或补尾(用户拍板) | 四层防滥用+管理端全做了;仅剩 MailChannels 邮件通知(worker 无 mailchannels)+留言墙上墙公示(app.js 无留言墙)两个小子项——要么顺手补完,要么明确不要 |
| 83 | 公募基金筛选器实战版 | 前置阻塞已解除:export_fund_score.py L8-10 注释「**#83** 公募筛选器字段前置」fund_company/manager/scale 等 9 字段已补;指标体系(sharpe/drawdown/stability/manager_score/star_rating)+筛选(type)/排序/搜索已被 #79 的 worker+弹窗实现 | 关闭(被 #79 覆盖大半)或刷新为小增量 | "实战级筛选器"核心=字段+指标+筛选排序搜索+详情弹窗,#79 一次全给了;剩余仅"多条件区间组合筛选"这类增强 |
| 22 | 凯利过滤层 walk-forward | #16(commit 299db6167)已建完整 walk-forward 方法论+kelly_walkforward.py 脚本(docs/kelly/analysis/kelly-walkforward-validate/),结论"推荐组合样本外有效,选段最优才过拟合" | 关闭(方法论已沉淀) | 该待办的诉求="未来调参用 walk-forward 防过拟合",方法论+脚本已沉淀可复用,独立挂待办无增量 |

## 三、🗑️ 建议废弃(单独成节,供重点勾选)

| # | 标题 | 废弃理由 | 证据 |
|---|---|---|---|
| 88 | 订阅推送(410 行大方案) | 订阅→推送的核心链路**现网三通道已覆盖**:①邮件/Telegram 信号订阅 worker/subscribe.js(C 方案,check_signals 推送)②浏览器通知(第一批已上线)③飞书抄送。410 行方案的增量场景不明,再做=重复建设 | worker/subscribe.js L1-15;TASKS-history-archive L464「K 订阅推送(410行) 待」 |
| 87 | PWA 体验增强(150 行) | App Shell CacheFirst+CACHE_VERSION 破缓存+SW 更新壳芯配套安全网均已就绪(sw.js v6-20260822-a382,§24 体系);150 行增益项属锦上添花,与"稳定系统不画蛇添足"(2026-08-21 废弃批次同精神)一致 | sw.js L14-17;archive L145 三件套已上线 |
| 85(二选一) | 板块轮动 | 前提多年未变且比记录更弱:board_concept.db **空库无任何表**(sqlite_master 查询为空),板块行情采集链路从未建成,"等历史攒够"无从攒起;若仍想要需先建采集(新工程),不想要即废 | sqlite3 board_concept.db ".tables" 空;static-site/data 仅 industry-*-concepts.json 概念映射非历史行情 |

> #85 属方向性需求,给用户二选一:A 废弃 B 明确"要做"后重新立项(先建板块数据采集,老前提描述作废)。

## 四、⚠️ 异常发现(治理过程揪出的问题)

1. **【最重】2026-08-21/22 会话批量完成 7+ 条 pending 但零回写**:#15/#91(v1.1.4 口径切换)、#29(track_score 一致性)、#75(REPO 分级闸)、#79(场外基金八步)、#80-P215(offshore 停链)、#82 大部(留言箱管理端+四层)、#83 前置(fund_basic 字段)——全部有 commit 在 main 甚至已上线,索引里却还挂"待排期/未派"。**这正是"堆积太多都忘记了"的成因:做完不销账**。建议 implementer 本次一并刷新,并考虑在 main-merge.sh 收尾加"若 commit message 含 #NN 则提醒更新 pending/done-list"的软提示。
2. **pending #82 引用的 commit hash b53a312e7 是悬空对象**(git cat-file 可读但无任何分支包含),实际承载 commit 为 eb288f443/4b384b473/f3f4cd838。引用失效,刷状态时一并修正。
3. **#94 方案文档大小口径误差**:docs/claude-md-slim-a1-5point4-plan.md 称"总39K→约34.5K(-12%)",实测字节:瘦身前 75217B → 瘦身后 71802B(-3415B≈-4.5%),"39K"疑为字符数误当 KB。#94 完成定性不变(A1+§5.4 内容确实删除,commit 3d9d9cdab/cd8ea5d8e 在 main),仅口径标注失真;另 CLAUDE.md 现又回到 71.8KB,若在意体积需新一轮瘦身(新增 §23.x/§24 规范所致),是否立项由用户定。
4. **重复登记复查结论**:既有互指(#15↔#91、#92↔#80、#90↔#34、#21→#17)无双重实施风险;done-list 与 pending 无编号重叠;#11(净值走势)与 #79(评分详情弹窗)是不同内容不算重复。无新增重复登记。
5. **"文档说做了实际没做"类**:未发现反向案例(done-list 里抽查的 commit 全部 `git merge-base --is-ancestor` 通过,18/18 在 main;#93/#51/#56/#62/#65-67/#70-72/#94/#96/#97 抽查均实锤)。

## 五、🔄 状态刷新(2 条)

| # | 过时表述 | 建议修正文案 |
|---|---|---|
| 10 | "数据源待调研(阻塞项)" | 阻塞已解除:chart-p2p3-data-source-research.md L9 结论「数据源已存在且全史——etf_daily 表 1520 只 ETF 2005 至今 21 年,不需新数据源调研」,缺口仅导出产物 etf/{code}-all.json(复刻 index/{iid}-all.json 模式,~29KB/只走 R2)。可直接派实施 |
| 83 | "fund_basic 仅 6 字段,须扩规模/经理/业绩(前置阻塞)" | 前置已解除(见第二节 #83 行);剩余范围收窄为"实战级多条件区间组合筛选"增强,大部分主体已被 #79 实现 |

## 六、⏸️ 保留远期(10 条,维持不动)

#11 场外净值走势(fund_nav 产物未建,static-site/data/fund_nav 不存在;与 #79 弹窗内容不同,独立有效)/ #12 canvas 统一组件(site.yaml charts 配置 P0 在,P1 组件化未做,方案待用户确认)/ #13 SVG fidelity 小项(hideOverlap 低优先)/ #14 lab_sim 费率客调(lab.js 只有静态成本块 L2091,无控件;trade_sim 版 _SIM_FEE_PRESETS 已上线不混淆)/ #17 凯利 v5 四方法(+ #21 并入)/ #19 港股全球 MA60 / #20 交叉分组二级筛选 / #86 真pin 复盘(archive L464 锚点仍在) / #80 P2-10 长期 code-splitting + P2-11 大盘 tab 懒渲染(分支 feat/p2-11-dapan-lazy 已预开)

## 七、🧹 墓碑行格式清理建议

pending 表内 ~18 行划线墓碑(#3-6/8-9/26-28/31/34/84/89/90/92/93/95)建议统一移出表格,各模块表尾留一行指针:「已完成见 docs/tasks-done-list.md,已废弃见 docs/abandoned-features.md」。§5.3 核心保留=编号+去向可反查,索引瘦身不丢信息。

## 八、复现

```bash
cd /Users/linhuichen/code/trade
# 1. 已完成类 commit 在 main(18/18 通过)
for h in dba8d2091 eee3d9387 b59c08838 b0c87c183 571c18ef7 7ab3dc3fa b317d85c3 e4fdcead4 b74368b5a 2cbec0452 8b63a7b9c 3d9d9cdab cd8ea5d8e d18b2fcb1 768a896cd d92df2b58 f27768c85 299db6167 371434fdc 28314d030 6e0f70eb6 a956cbe5a 4289d50a7 4b384b473 f3f4cd838; do git merge-base --is-ancestor $h origin/main && echo "$h IN_MAIN"; done
# 2. v1.1.4 口径切换
git log --oneline --all --grep="v1.1.4"; git tag -l; grep -n "v1.1.4 起默认" static-site/lab.js
# 3. #79 八步:worker/wrangler/前端/调度/线上
head -8 worker/fund_score.js; grep -n FUND_SCORE_DB wrangler.jsonc; grep -n "api/fund_score" static-site/app.js | head -3; sed -n '39p;47p' scripts/pf_score_weekly.sh; curl -s https://ss.fx8.store/api/fund_score?page=1\&size=1
# 4. #75 分级闸 / #29 校验门 / #82 防滥用
sed -n '36,54p' scripts/upload_r2.py; sed -n '44p' scripts/check_data_integrity.py; sed -n '731,733p' worker/auth.js; ls static-site/admin/feedback.html
# 5. #10 阻塞解除 / #85 空库 / #14 lab 无费率控件
sed -n '9p' docs/chart-p2p3-data-source-research.md; sqlite3 ~/code/trade-data/data/board_concept.db ".tables"; grep -n "labFeeConfig" static-site/lab.js
# 6. #94 减量口径
git show 3d9d9cdab^:CLAUDE.md | wc -c; git show 3d9d9cdab:CLAUDE.md | wc -c; wc -c CLAUDE.md
```

数据截止:2026-08-22(origin/main@4289d50a7);关键口径:完成判定=commit 在 origin/main 且产物/前端/数据层至少一重实证。

## 执行结果(implementer 回写,2026-08-22)

> 执行分支 feat/todolist-cleanup-exec(base=origin/main@436f6d6bf);本报告随治理 commit 入库,commit hash 待主控 merge 入 main 后以 merge 链为准。改动范围仅 4 份文档(pending-features-index.md / tasks-done-list.md / archive/TASKS-done.md / 本报告),零代码/脚本/前端改动。

| 处置分类 | 拍板数 | 实际执行 | 编号 | 去向 |
|---|---|---|---|---|
| 关闭移入 done-list | 8 | 8 | #15+#91 / #29 / #42 / #75 / #79 / #80-P2-15 / #83 / #22 | docs/tasks-done-list.md「2026-08-22 todolist 治理移入」(每条带 commit 实锤) |
| 整条关闭 | 1 | 1 | #82 留言箱(邮件通知上线+留言墙砍除;悬空 b53a312e7 随行清除) | 同上 |
| 废弃留档 | 2 | 2 | #85 板块轮动 / #87 PWA 增强 | docs/archive/TASKS-done.md「四、…治理关闭记录(2026-08-22)」(注明废弃+重启条件) |
| 状态刷新 | 1 | 1 | #10 ETF 弹窗长历史(阻塞解除,可直派) | pending 模块二行内更新(依赖列同步改无阻塞) |
| 保留 | 1 | 1 | #88 订阅推送(用户确认保留) | pending 模块十六行内更新 |
| #80 子项重组 | 1 | 1 | P2-15 关闭 / P2-11 标实施中(feat/p2-11-dapan-lazy 预开) / P2-10 长期保留 | pending 模块十六行内重写 |
| 墓碑行清理 | 17 | 17 | #3/4/5/6/8/9(模块一)+ #95(模块三)+ #26/27/28/31/34(模块五)+ #34(模块六)+ #84/89/90/92/93(模块十六) | 表格行删除,各模块注释留编号+去向指针(§5.3 可反查) |

墓碑清理前后:pending 表格行(`grep -c '^| '`)69 → 41 行,-28 与 git diff 实测一致(删 32 增 4)。-28 构成:墓碑划线行 -18(#3/4/5/6/8/9 + #95 + #26/27/28/31 + #34 两处[模块五/模块六] + #84/89/90/92/93)+ 拍板关闭/废弃整行移出 -10(#15/#22/#29/#42/#79/#82/#83/#91 关闭 8 + #85/#87 废弃 2);#75 行换「本模块已无远期项」占位行净 0;#80/#86/#88 为行内重写(diff 计删+增各 1,不影响净数)。头部「最近更新」已补 2026-08-22 治理记录(报告路径已带)。

⚠️ 主控 merge 提示:主仓库工作区原有一份本报告的 untracked 旧版(无「执行结果」段),merge 本分支前需先移除/覆盖该 untracked 文件,否则 merge 会被 untracked 冲突挡住;以本 worktree 版(含执行结果)为准。
