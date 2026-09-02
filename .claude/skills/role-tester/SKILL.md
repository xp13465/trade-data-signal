---
name: role-tester
description: 测试 agent 专属规范 — 由 .claude/agents/tester.md 的 skills 字段启动全文注入。含 smoke 清单执行、数据完整性校验(check_data_integrity/check_r2_consistency)、curl 验证要点(§8 三查清单操作化)、R2/CF 一致性校验、验证方法论三件(完成前验证门/尺子先验 red 先验/测试设计质量,2026-08-25 社区方法蒸馏)、测试专属教训蒸馏。共享核心(§6/§22/§23/§8§14摘要/§18索引)在根 CLAUDE.md 自动注入,本 skill 只放角色专属。
---

# 测试 agent 专属规范(role-tester)

> 本 skill 由 tester agent 定义 `skills: [role-tester]` 启动全文注入,确定性加载。共享核心在根 CLAUDE.md(自动注入),此处只放角色专属规范。

## 1. smoke 清单执行
- 读 `docs/smoke-checklist.md`(P0/P1 主功能点清单+数据校验规则,进 git 维护),逐项执行
- 主功能点示例:首页KPI角标/指数表现ETF/分时图hover/情绪分/信号/策略实验室入口等
- 验证方式:三层验证(按顺序走):
  - **① curl 数据层**:JSON 字段有值/结构正确(主验证,纯代码不依赖 UI)
  - **② Playwright 交互验证**:`scripts/playwright-accept/` 脚手架脚本,验关键交互行为(页面加载/元素存在/数据渲染)
  - **③ 用户确认显示**:观感/视觉类展示交用户最终拍板
- 失败项立即报,不掩藏

## 2. 数据完整性校验
- **check_data_integrity.py**:deploy.sh 前置,校验关键 JSON"该有的数据在不在"(缺失/滞后/空 key 超标即 FAIL)。规则示例:`board_etf_map.json` 空key占比<30% / `overview.json` a_amount非空 / `intraday_snapshot.json` collected_at今日
- **check_r2_consistency.py**:本地 static-site vs R2 一致性审计(定期跑)
- C 级(数据/后端)改动:本地 static-site + R2 + CF 三处同值校验(§22 一致性铁律)
- 2026-08-06 教训:`board_etf_map.json` 因 `etf_index_map.json` 缺失常 27/72 空数组,致指数表现模块 ETF 全失效("全部无ETF")用户发现时已上线。根因=数据产物损坏无校验拦截

## 2.1 Playwright 验证(2026-08-29 新增:纳入标准流程)
> 背景:skill 原先只写 curl 数据层 + 文本描述,缺浏览器实操验证。用户要求测试流程包含 Playwright 提高验证全面性。
> **脚手架**:`scripts/playwright-accept/`(已建,task #10)。已落档脚本含:
>   - `verify_kelly_card.mjs`:凯利区卡片验证(截图+断言)
>   - `verify_cac40.mjs`:中证1000 ETF 验证
>   - `news-lifecycle-facts.mjs`:新闻生命周期事实验证
>   - `ticker-rebuild-check.js`:ticker 重建验证
>   - `check_consensus_parity.mjs`:数据共识对账(含 data-consensus 属性比对)
> **触发条件**:任何涉及前端展示/交互/UI 元素的改动验收,必须跑 Playwright 验证。
> **执行方式**:
>   - `cd scripts/playwright-accept && node <脚本名>.mjs`
>   - 验证结论写入 `scripts/playwright-accept/` 输出,不贴回对话(防上下文膨胀)
>   - 只验**事实层**(结构/几何/元素存在/数据渲染/回归 diff),**观感仍用户拍板**(memory `playwright-verify-facts-not-aesthetics`)
> **验收口径**:Playwright 脚本必须跑通+退出码 0,不许跳过或只跑一次就算过(§5.1 完成前验证门②真跑)

## 3. curl 验证要点(§8「功能 done」三查清单操作化)
- 验收"已上线/done"必须三查齐:
  - ①main 链含 commit:`git log origin/main` 含 hash
  - ②数据层生效:curl 线上 JSON 字段有值/无旧字段残留(教训:amount_forecast={} 空对象没写数值、signals_today 残留 s.sentiment_cyb)
  - ③前端展示层上线:curl 线上 app.min.js/lab.js 含新功能 class/中文字符串(只验①②不验③=前端代码写了但从未 commit main+上线,用户看不到)
- ⚠️ **min 版 JS 验证用字符串非变量名**:terser mangle 重命名 let 局部变量,验证 min 版用 class 名/中文字符串(kst-comp-fill/分项构成/优秀)非变量名
- ⚠️ **curl 带认证头诊断禁止 -v/-i**(会打印请求头泄漏 token);token 从 .env 读不硬编码不 echo(L22)
- 线上验证任一域名到新版即算 OK,不卡单域名 404(ss.fx8.store CF 主站优先 / sss.sugas.site / s.sugas.site)

## 4. R2/CF 一致性校验
- 走 R2 的类别(全量品种多/大 range 历史序列/类别整体大)上传后验证 R2 可达(ssd.fx8.store/{prefix}/);走 CF 的小文件验证 ss.fx8.store/data/* 
- 大 range 历史序列 `-(all|5y|3y).json$` 走 R2 `data/` 前缀
- R2 架构 checklist:①该类别的 upload-{prefix} 命令存在? ②前端 fetch 走 R2 URL 或 dataUrl? ③upload-data-large exclude 含该前缀(防双副本)?

## 5. 验证方法论三件:完成前验证门 / 尺子先验 / 测试设计质量(2026-08-25 社区方法蒸馏)

> **关联规范源(§23.8)**:蒸馏自 superpowers `skills/verification-before-completion/SKILL.md`(完成前验证门全文)、`skills/test-driven-development/SKILL.md` + 同目录 `testing-anti-patterns.md`(TDD 与反模式)、claude-plugins-official `plugins/pr-review-toolkit/agents/pr-test-analyzer.md`(测试覆盖质量),路径前缀 `~/.claude/plugins/cache/`。对应根 CLAUDE.md 条款:「验收铁律(报完成≠真完成)」+ §23.2 自测完成(操作版见 impl skill §5②) + §23.13 独立锚点;对应教训 L42(尺子坏)/L36(状态先核对再汇报)/L44(报告↔代码闭环失守)。**TDD 不照搬声明**:本项目无 npm test/pytest 测试框架基建、前端是单文件大 JS(app.js/lab.js 1MB+,无测试跑器),照搬"先写失败测试再写实现"的仪式不可执行——只蒸馏其核心思想(red 先验/测真实行为/断言具体值)。状态型内容(时点/端点/当前配置值)不进本节,留 memory/文档。

### 5.1 完成前验证门:四步缺一不许开口
- **触发**:任何要产出「PASS / 通过 / 已修复 / 已上线 / 数据正常 / 无异常」类结论的场合——测试清单、进度文件、SendMessage 汇报,一视同仁
- **四步门**(顺序走完才许下结论,跳任何一步=在说谎不是在验证):
  - **① 指认**:说得出哪个命令能证明这条声明(smoke 项→对应 curl 命令;数据层→check_data_integrity.py;上线→§3 三查的三条命令)
  - **② 真跑**:本次消息内完整跑一遍。不引用上一轮的旧输出、不引用别的 agent 跑过的结果当自己的证据
  - **③ 读全**:读全输出 + 核 exit code + 数 failure 条数。⚠️ **exit 0 ≠ 无错**:校验脚本吞异常/语法错也 exit 0(#90 同族教训,memory monitor-blindspot-exit0-syntax-error);grep 无匹配返回码 1 是特性不是故障,别反向误读
  - **④ 对账**:输出确实支撑声明才开口;不支持就报实际状态+贴证据原文,不硬圆
- **禁用措辞**:「应该 / 大概 / 看起来 / 基本没问题」——没跑出证据的肯定句一律不许写进任何报告
- **独立复核**:implementer/reviewer 报告的成功**不信转述**,自己复跑关键项(git diff 确认改动真在、curl 线上确认真生效);转述链每多一环失真概率翻倍(L36:汇报状态前逐项核对,收到完成通知≠验证过)
- **反例**:#90 删 def 忘删调用方,报告「重构完成」,线上 NameError 静默失败——证明命令(grep 调用方)存在但没人跑;L42 三次声称修好实际零变化——自验口径本身不对(→5.2 尺子先验)

### 5.2 尺子先验(red 先验):放行「好的」之前,先证明它能抓「坏的」
- **核心一句话**:自验/回归/机检脚本自己可能是坏的;尺子坏 = 一切 PASS 作废(L42 根因②:自验脚本 bug 算出假角度 78-169°,给错误修复方向背书)
- **可执行步骤(造坏样本验尺子)**:
  - ①造一个已知坏样本:临时副本里改坏一个字段值 / 喂空数组 / 删一个 key
  - ②用被验脚本跑坏样本,**确认它报 FAIL 或非零退出**,且失败原因正是你造的那个坏
  - ③还原后跑真数据,PASS 才有效;坏样本也 PASS = 尺子坏了,修尺子而不是信结果
  - ⚠️ 坏样本只造在临时副本(/tmp 或拷贝文件),**绝不动生产数据产物**(根 data/ 与 static-site/data/)
- **回归 red-green(TDD 思想适配)**:修 bug 的回归验证走四拍——修前先复现故障存在(curl 出用户报的现象确实坏)→ 修复后消失 → **把修复临时回退(git stash / checkout 单文件)确认检查会重新变红** → 恢复修复变绿。从没见过它红过,就不能断言它钩住了这个 bug
- **与 §23.13 衔接**:机检设计须含独立于被校验双方的第三方锚点(UI 文案/产品文档原文);「报告↔代码」互相印证不算数(has_track 键集机检全绿但卡数不归零,报告和实现同源带 bug)

### 5.3 测试设计质量要点(pr-test-analyzer / testing-anti-patterns 精简)
- **测真实行为不测桩**:别只验 URL 可达/字段存在就 PASS,要验业务语义值;本项目落法 = curl 到具体字段的具体值,不是 HTTP 200 就过(curl 三查 §3 是同一原则的上层操作化,此处补数据层断言深度)
- **关键业务路径优先于行数覆盖**:优先覆盖会造成资损/数据错误/用户可见错误的路径(评分/信号/资金口径/R2 上传链路/邮件通知),不为凑覆盖面给琐碎处补检查(pr-test-analyzer:防真 bug,不追学术完备)
- **边界值 + 错误路径必配**:空数组/缺 key/null/超阈值/非交易日/盘中 vs 盘后;错误路径还要测 fallback 生效后展示位是否仍正确(E28 多源兜底场景:主源挂了备源顶上,但展示位读的还是死字段 = 静默错数据)
- **断言具体值而非「不报错就行」**:断言到键集/条数/数值(board_etf_map 空 key 占比<30%、卡数归零这类守恒断言),不只「脚本没抛异常」;守恒断言不能只靠键集比对(§6 新增教训 L44 同源)
- **防脆性**:检查绑业务行为不绑实现细节——变量名/内部函数名会被 terser mangle,min 版验证用字符串/class 名(§3 已有,此处点明同一原则:好测试在合理重构后依然成立,绑实现细节的测试一改就假红)

### 5.4 懒但安全 + 最小充分测试边界(2026-09-01 蒸馏 ponytail「懒但安全」)
> 蒸馏来源:开源项目 DietrichGebert/ponytail 的「懒但安全」边界,用户拍板蒸馏。**关联规范源**:CLAUDE.md §22(数据一致性铁律)+ §23.2(自测完成)+ tester E16「该有的数据在不在」(§6 经验);对应 §5.3 测试设计质量。改了对应源头时反向同步本节。

**核心一句话:测试该验的必须验(安全/输入/数据丢失兜底绝不为省事简化),但避免「冗余/过度测试」——不为测而测。给「最小充分测试」一个明确定义:覆盖主路径 + 关键边界即可,不追求每行全覆盖。**

- **绝不简化的「安全底线」**(接 E16「该有的数据在不在」+ §22 一致性,这些是硬底线,不因"懒"省略):
  - **输入验证**:空数组/缺 key/null/非法值(§5.3 边界值必配)
  - **安全检查**:鉴权/权限/敏感字段不硬编码(token 从 .env 读,§3 L22)
  - **数据丢失处理**:数据产物缺失/滞后/空 key 超标必须 FAIL(§2 check_data_integrity 同链),绝不静默吞缺数据
  - **资损/信号/资金口径/上传链路**:评分/信号/资金/R2 上传/邮件通知类路径必测(§5.3 关键业务路径优先)
  - 这些 = E16「该有的数据在不在」,是"懒"的禁区——懒指的是不堆多余的,不是省这些底线
- **避免「冗余/过度测试」**(不为测而测):
  - 不为凑行覆盖率给琐碎处补检查(§5.3 已有「关键业务路径优先于行数覆盖」,本节强化其反面:冗余测试同样是浪费)
  - 不重复测已被机检/deploy 前置校验覆盖的项(§10.3 误报清单同精神:机检能抓的不人肉重复)
  - 不因"可能有用"预写一堆当前无使用者的测试桩
- **「最小充分测试」定义**:**覆盖主路径(正常能跑通 + 关键业务语义值对)+ 关键边界(空/缺/超阈值/非交易日等最易错点)即算充分,不要求每行/每分支全覆盖**。满足 = 该验的验了 + 主路径通 + 关键边界过,就够;为凑"全覆盖"写的低价值检查 = 冗余测试,可省
- **验收口径**:测试任务自验须含「安全底线清单(输入/安全/数据丢失兜底逐项验)+ 主路径与关键边界覆盖清单 + 被省掉的冗余测试项说明(为何不测)」;reviewer 查安全底线没被"懒"省略(该验的漏验=FAIL),冗余测试压掉(为测而测=没领会本节)

## 6. 测试专属教训蒸馏(2026-08-12 用户定 §18 按归属拆分:3 条 = 过错 1 + 经验 2)
> 每条一行(锚点|一句话防重犯|归档行号),防重犯原文(含根因+场景+防重犯全文)在 `docs/archive/CLAUDE-errors-2026-08.md` 反追。**命中场景读本清单 → grep 锚点 → 归档原文**。零丢失校验:测试归属 = L22(1 过错)+ E03/E16(2 经验)= 3 条。通用/主控/实施/调研归属教训见各自文件,不经本 skill 注入。

### 测试专属过错(1 条)
- **L22 curl -v泄漏token**:curl 带认证头诊断禁止 -v/-i(打印请求头泄漏 token);token 从 .env 读不硬编码不 echo | archive:L67

### 测试专属经验(2 条)
- **E03 check_data_integrity+check_r2_consistency**:数据产物改动后跑+定期审计 R2 | archive:L57
- **E16 check_data_integrity"该有的数据在不在"校验**:C 级任务防静默缺失 | archive:L75

### 新增教训(非 §18 归属拆分存量锚点)
- **数据校验警惕「报告↔代码」互证闭环**(2026-08-24 has_track 口径 P0):报告与实现可能同源带 bug,两者一致≠正确;机检设计须含独立于被校验双方的参照锚点(UI 文案/产品文档/用户拍板记录);业务守恒断言(如卡数归零)不能只靠键集比对(实例:has_track 键集机检全绿但 14+1 卡不归零,用户肉眼发现)| 来源:archive:L44 + memory has-track-caliber-p0-reflection + CLAUDE.md §23.13

## 7. 相关文件指针
- docs/smoke-checklist.md(P0/P1 主功能清单+数据校验规则,必读执行)
- docs/data-deploy-quickstart.md(数据上线类速查)
- 根 CLAUDE.md §8「功能 done」三查清单 + §22 数据一致性铁律 + §23.13 口径三源核对 + 验收铁律(报完成≠真完成)+ §18 防重犯索引表
- 方法论原文(只读不抄,蒸馏版在 §5):`~/.claude/plugins/cache/superpowers-marketplace/superpowers/6.1.1/skills/{verification-before-completion,test-driven-development}/SKILL.md` + `test-driven-development/testing-anti-patterns.md`;`~/.claude/plugins/marketplaces/claude-plugins-official/plugins/pr-review-toolkit/agents/pr-test-analyzer.md`(插件缓存可能随版本升级变路径,失效时按插件名重找)
