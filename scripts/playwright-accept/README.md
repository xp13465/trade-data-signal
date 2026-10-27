# scripts/playwright-accept/ — Playwright 前端验收脚手架

把「看图验收」变成「程序化断言」的通用工具。主控看不了图片,这里把所有验收证据
(console 报错、网络请求、DOM 断言、accessibility snapshot)变成文本,主控/ reviewer/
tester 可直接读。

纯工具,不碰 static-site/ 任何业务文件、不碰后端、不碰 app.js/lab.js。

## 目录索引(§23.5 塞入即归类)

| 文件 | 作用 |
|---|---|
| `accept.js` | 主入口:console 抓取 + 网络断言 + DOM 断言,输出 PASS/FAIL |
| `snapshot.js` | 辅助:输出页面 accessibility snapshot 文本结构 |
| `ticker-check.js` | 首页「全球盘面跑马灯」验收模板(占位断言,待上线回填) |
| `mem_probe.mjs` | 内存泄漏量化探针:三场景 JS heap 采样+CDP 强制 GC,GC 后仍单调涨=泄漏实锤(2026-08-23 P0③) |
| `news-debug-fetch.mjs` | 新闻看板线上 fetch 调试探针(marker/date 场景模拟) |
| `news-epoch-facts.mjs` | 新闻纪元硬化实证:本地新 app.min.js route 注入线上页,验首现/切 tab 往返/轮询更新/fetch 失败不消失(#12) |
| `news-lifecycle-facts.mjs` | 新闻看板复发症状实证(线上旧版):精确驱动轮询体与重建竞争做事实层断言 |
| `probe_heap_cdp.mjs` | CDP 精确 heap 曲线:Performance.getMetrics 每秒采 JSHeapUsedSize/DOM/监听器(new14 修复前后对比) |
| `probe_heap_explosion.mjs` | 内存暴涨曲线探针:修复前版本复现 R1,500ms 采样拿暴涨速率与构成证据 |
| `probe_sim_ls_dump.mjs` | sim 弹窗切 NEW14 后 dump 全部 localStorage,验证 sim 选择是否污染 lab 启动态 |
| `repro_fade_bugs.mjs` | fade 双 bug 复现探针 v2:Bug A 渲染风暴(longtask 计量)+ Bug B/C/D 跨弹窗模式读值 |
| `sim_modal_baseline_probe.js` | sim 弹窗默认态 A/B 探针:feat vs main 构建输出逐项 diff 一致=只动布局不动行为(§23.7,2026-08-24) |
| `t32-fade-mode-smoke.js` | T3-2「AI降亏·模式」下拉三处接入真实浏览器冒烟(UI 落点/联动/记忆) |
| `ticker-dead-closure-probe.js` | 死闭包轮询守卫根治自证:切 tab 重建≥2 次后旧闭包不再作用于已脱离 DOM 的 wrap |
| `ticker-rebuild-check.js` | 跑马灯「切 tab 重建后是否消失」实测坐实根因 |
| `verify_fade_mode_ttl.mjs` | 模式记忆 TTL 验收:18 小时滑动过期+四区域独立记忆体(T1-T4) |
| `verify_fade_mode_ui.mjs` | 模式下拉 UI 交互+性能专项验收(T3-1 修复批四件修复+硬指标) |
| `verify_sim_modal_fade_cb.js` | sim 弹窗「AI降亏过滤」总开关行为自验:feat vs main 默认态逐位一致+开关联动(2026-08-24 第4轮) |
| `verify_sim_modal_layout.js` | sim 弹窗顶部筛选条单行排布自验(四控件组合 1 行横排) |
| `kelly-layout-check.js` | 凯利参数区排版验收(2026-08-26 feat/kelly-longmode-layout):PC1280/平板768/手机375 三视口布局断言 + G档/开关/对比表/费率交互回归 |
| `kelly-overflow-probe.js` | 辅助:375px 全页横向溢出元素定位探针(基线对照用,定位超宽元素路径) |
| `lab_review_table_scroll_check.js` | lab 手机横溢出修复验收(feat/lab-review-table-scroll):三视口+参数区展开 docScrollWidth 断言 + AI 表格横滑/折叠交互/PC hover 气泡弹收;⚠️ kelly-overflow-probe 的 offender 榜会把关闭 details 子树 stale rect(如 table w=1616)排前、挤掉真凶(真凶=参数栏 [data-tip]::after visibility:hidden absolute 气泡),页面级溢出以 docScrollWidth 为准、元凶用二分隐藏法定位 |
| `xcount-consensus-smoke.js` | AI信号认可度计数口径(X/Y/W)渲染层冒烟(2026-08-27 feat/x-count-full-alignment):线上页 route 注入本地新 min,验 data-consensus 三段式格式/winner hover 显「{x}票·当日主推」/0 票显「0·非主推」/CONS_TIP 新文案;⚠️ 信号 cell 子元素带 data-no-pop,须对 cell 本身 dispatchEvent mouseover(onboarding 弹窗需先点 .onboarding-skip) |
| `sim-toggle-accept.js` | 首页模拟回测弹窗「价格口径」双档验收(2026-09-06 #91,feat/sim-price-toggle):双档按钮默认次日开盘/切当日→买卖价与汇总/峰值/曲线联动/计划买入时间列上下换行(上=信号日期下=实际买入)/首列「信号日期」/表头15=行15/独立键与 lab 键互不触碰/无 console 报错。⚠️ 对账样例 560210 需取消 AI降亏过滤+K=关(raw 全量人口);onboarding overlay 拦截点击须 evaluate+click |
| `verify_nav_lazy_consistency.mjs` | accum_nav_map 按 ETF 懒加载「前端同构对账机检(§5.4⑦ 强制)」(2026-09-17 feat/nav-lazy-loading):三场景——A block 全量放行 per-ETF(纯懒加载)/B block per-ETF 放行全量(全量 fallback)逐 cell 逐位一致;D 单 code 缺失注入(block 某 code 拆分文件→failed→`__gih_missing_px_`>0 且渲「— 缺价」,证三态门控「未载被吞」bug 未发生)。首页 sim/演进表复用同一 common 内核由 lab 路径覆盖 |
| `verify_bj50_intraday_degrade.mjs` | 北证50分时双加固验收(2026-09-30 feat 盘中注入minute_series+东财熔断+腾讯day/query备用腿):A EM mock 合法成功路径零变化/A2 腾讯腿/B 实时源全失败+快照带minute_series→画曲线非文字降级/C1 熔断短路(前触发+day兜底取数/C2 偶发失败不误熔断;⚠️ 需本地起 http.server serve worktree static-site 且 data 目录可访问,route 拦截外部源 |
| `cal_render_regression.mjs` | 情绪日历「旧版 vs 新版」渲染逐位一致回归 + 点日期弹当天明细(2026-09-30 feat 情绪日历加维度说明):双视口(1280/375)断言 D3 日期集合+格子文本+sig+idx+val 逐位一致证明「只增不改」、D5/D6 点日期弹明细、M 系列移动端点击目标/字号;⚠️ 前置依赖=需同时起 8133(新版)/ 8134(旧版)两个本地服务器,单跑必失败 |
| `accept_console_clean.mjs` | console 洁净度哨兵(#133 复发防线,2026-10-03 加严并挂 main-merge.sh 7.7 发版验收):判 0 CSP 违规 + 0 pageerror;退出码 0=PASS/1=FAIL(违规,发版阻断)/2=UNREACHABLE(路由加载失败未能校验,放行+醒目提示)以与「检测到违规」区分;⚠️ 打线上真实 URL,约 1 分钟;`SKIP_CONSOLE_CLEAN=1` 只在 main-merge 逃生,本脚本本身无逃生钩;2026-10-27 起默认用真实 Chrome UA 访问:Playwright 默认 UA 含 HeadlessChrome 字样会被 Cloudflare 判为机器人 → 踢到挑战页 → 挑战页自身 fetch('data:,') 触发它自己的 CSP 违规 ⇒ 哨兵误报 FAIL(实测默认 UA 4 条违规/13 次挑战,真实 UA 0 条/3 次)。可用 `SENTINEL_UA` 环境变量覆盖;把它改回 HeadlessChrome UA 可复现原误报,用于验证「检测没被弄瞎」。**2026-10-27 可归因化**:每条 CSP 消息记来源 location + 完整文本,按 location 分组计数。**2026-10-27 第 3 轮改成按「策略归属」判**:拿 `page.goto` 主文档响应头的 `content-security-policy` + `content-security-policy-report-only` 原文,把消息里引用的 directive 与我们的策略逐 token 比——等于我们的策略 ⇒ FAIL(`our-policy-violated`);外来注入策略(如 CF jsd 的 `connect-src 'none'`)⇒ `INFO noise` 不阻断(仍打印可见);拿不到我们的策略 ⇒ fail-closed 判 FAIL(`our-policy-unverifiable`)。**不能按 location 归因**:实测外部脚本发起的违规 location 报的是脚本 URL(如 `/app.min.js`,正是我们自己的 bundle),按 location 判会把真违规当噪音=闸门变瞎。另有:第三方 origin / `about:srcdoc` / `data:` / 挑战侧同源 document / 4xx 页不论策略文本一律 INFO;加挑战页识别(`cf-mitigated` 头 / 挑战标题)→ UNREACHABLE,并记录+断言 `page.goto` 的 HTTP 状态码;导航落地 URL 不是我们的 document(跨 origin / 同源异路径)也判 UNREACHABLE(2026-10-27 堵「跳转到别处仍静默 exit 0」)。归类规则见 `console_attribution.mjs`(纯函数,单测 `console_attribution.test.mjs`)。2026-10-27 #319 补:文档策略**全文打印不截断**(带字数,旧版截 400 字把 `connect-src` 白名单截掉);补 Chrome 141 的**内联脚本(单引号无冒号)/ eval(冒号后名字)**两种真实报文方言,不再落 unknown |
| `console_attribution.mjs` | 哨兵归因纯函数模块(2026-10-27,零依赖不 import playwright):location 归类 / 挑战页识别 / 路由结果判定 / CSP 与 pageerror 归因 / **策略归属比对(`extractViolatedDirective` + `parsePolicyDirectives` + `compareDirectiveToOurPolicy` 三态 ours·foreign·unknown)** / 按 location 分组计数 / 退出码决策。独立成模块是为了能离线单测 + 变异判别力验证 |
| `console_attribution.test.mjs` | 上者的自动化测试(node 内置 test runner):`node --test scripts/playwright-accept/console_attribution.test.mjs`,覆盖「我们的 document→FAIL / 第三方·srcdoc→INFO / 挑战页→UNREACHABLE / 4xx→加载失败 / 退出码优先级 / 导航落地跨 origin·同源异路径→UNREACHABLE / **E7–E10 策略归属(我们策略⇒FAIL·含 app.min.js 脚本 URL / 外来策略⇒INFO / 拿不到策略⇒fail-closed / 第三方恒 INFO)** / **E2–E3 Chrome 141 内联脚本·eval 方言(真实原文取自 /tmp/probe-csp2/out.log)**」+ 归一化与边界 |

> 新增脚本在此索引追加一行。(2026-08-26 补登历史 16 个一次性/专项探针;small-items-batch 六件验收为内联临时断言未落脚本文件,无新增行)

## 安装

```bash
cd /Users/linhuichen/code/trade/scripts/playwright-accept
npm init -y
npm i playwright
npx playwright install chromium   # 下载 Chromium(首次)
```

> 若项目其他目录已有 node_modules/playwright 可复用,不必重复下载。首次 `npx playwright
> install chromium` 需联网下载浏览器;网络被墙时设 `PLAYWRIGHT_DOWNLOAD_HOST` 镜像
> (如 `https://npmmirror.com/mirrors/playwright/`)重试。

## 用法

### accept.js(主入口)

```bash
# 本地静态站(先起服)
python3 -m http.server 8000 -d /Users/linhuichen/code/trade/static-site

node accept.js http://localhost:8000 \
  --expect-request news_digest.json \
  --assert '#app|exists'

# 线上三站任选
node accept.js https://ss.fx8.store \
  --expect-request news_digest.json \
  --block-on-error
```

选项:
- `--expect-request <子串>` 断言某请求发出且 HTTP 200(可多次)
- `--expect-request-missing <子串>` 断言某请求未发出(验证降级后旧源已停)
- `--block <子串>` 屏蔽匹配请求,模拟源故障,验证降级(可多次)
- `--assert <选择器|期望>` DOM 断言,期望值:`text=xxx` / `exists` / `attr=key=value` / `count=N`
- `--assert-file <路径>` 从文件读断言列表(每行一条)
- `--block-on-error` 有 error 级 console 或 pageerror 时 exit 1
- `--wait <ms>` 加载后额外等待毫秒(给前端渲染/网络留时间)

退出码:0=全 PASS;1=有 FAIL / error 级 console(开启 --block-on-error)/ 参数错误。

### snapshot.js(辅助)

```bash
node snapshot.js http://localhost:8000 --wait 2000
# 输出页面 accessibility 树文本(role/name 层级),主控直接读页面结构
```

### ticker-check.js(跑马灯模板)

```bash
# 正常跑(断言 8 品种 + 布局滚动 + 主源发出)
node ticker-check.js http://localhost:8000

# 屏蔽东财主源验证降级
node ticker-check.js http://localhost:8000 --block push2delay.eastmoney.com
```

> 选择器已按 2026-08-17 实测回填:.global-ticker 容器 / .gt-scroll 滚动条(一行超宽即滚动)/
> .gt-name 品种(无缝滚动复制2份 → 16 节点,唯一品种 8)/ 主源 push2delay.eastmoney.com。
> 降级模式当前预期 FAIL = 跑马灯备源兜底尚未就位(block 东财后 8 品种无备源请求 + 页面
> error),为真实验收发现,待跑马灯实施 agent 回填备源子串后转 PASS。

### kelly-layout-check.js(凯利参数区排版验收,2026-08-26)

```bash
# 先起本地静态站(worktree 或主树, 需 data/ 数据软链在位)
python3 -m http.server 8803 -d /Users/linhuichen/code/trade/static-site
# 三视口(PC1280/平板768/手机375)布局断言 + 交互回归(G档持久化/gih开关/对比表开合/费率预设/AI降亏总开关)
node kelly-layout-check.js http://localhost:8803
```

> 断言口径:DOM 顺序 fee→gih→过滤区 / topgrid 两列结构 / PC 同行+过滤区独占行 / 窄屏堆叠 /
> 参数区无横向溢出(全页 scrollWidth 溢出=AI 报告折叠区表格存量问题, 基线探针对照见下)。
> 截图存同目录 `kelly-layout-*.png`。退出码非 0 = 有 FAIL。

### kelly-overflow-probe.js(横向溢出元素定位探针)

```bash
node kelly-overflow-probe.js http://localhost:8803   # 可换任意端口/基线 URL 对照
# 输出: innerWidth/docScrollWidth + 前 14 个超宽元素(path/width/right/text)
```

> 用途:验证「溢出是否本次引入」——新分支与 main 基线各跑一遍比对 offender 清单是否一致。

### accept_console_clean.mjs(console 洁净度哨兵,可归因版 2026-10-27)

```bash
# 线上(与 main-merge.sh 7.7 同一条命令; worktree 里没有 node_modules 时用 NODE_PATH 指到主树)
NODE_PATH=/Users/linhuichen/code/trade/scripts/playwright-accept/node_modules \
  BASE_URL=https://ss.fx8.store node scripts/playwright-accept/accept_console_clean.mjs

# 归因规则的自动化测试(不需要浏览器/网络)
node --test scripts/playwright-accept/console_attribution.test.mjs
```

退出码契约(与 2026-10-03 版**逐字不变**,main-merge.sh 7.7 依赖它):
`0` 洁净 / `1` 有真违规(阻断) / `2` 不可达或命中挑战页(放行+醒目提示),违规优先于不可达。
「不可达」含三种原因:路由加载失败(`goto-error`/`http-status`)、命中挑战页(`challenge`)、
**导航落地不是我们的 document**(`origin-mismatch` 跨 origin / `path-mismatch` 同源异路径,
2026-10-27 补:旧版这种情况会静默判 OK ⇒ 三个路由全"通过" ⇒ exit 0,等于没校验却报洁净)。

输出怎么读:
- `路由 #xxx: HTTP <状态码> OK|UNREACHABLE 原因=<reason>  我们策略=<N>条|无(fail-closed)` —— hash 同文档跳转没有新响应,显 `(same-document)` 并沿用上一个路由的策略;挑战页显 `原因=challenge` 并带 `cf-mitigated` 头值。
- `我们文档策略(<N> 字): <原文>` —— 本次从主文档响应头抓到的 CSP 策略(enforce + report-only,排障时先看这行:它决定了「算我们」还是「算外来」)。**全文打印、不截断**(2026-10-27 #319:线上策略 907 字,旧版截到 400 字正好把 `connect-src` 白名单截掉,排障最需要的那段看不见);前面的「N 字」便于对账「是否全打」。
- `归因分组(按 location):` —— 每条 CSP/pageerror 按「来源 location + 判定 + 原因」分组计数:`count`=累计条数(浏览器每报一次记 1),`唯一文本`=同一完整文本去重后的条数;每组最多 3 条全量样例(不截断)。原因 `our-policy-violated`=我们自己的策略被违反;`foreign-policy(注入/挑战侧)`=外来策略;`our-policy-unverifiable`=拿不到我们的策略,按 fail-closed 判 FAIL。
- `INFO noise: <url> × N` —— 降级为噪音的记录(第三方 origin / `about:srcdoc` / `data:` / 挑战侧同源 document / 4xx 页 / 外来策略)。**噪音只是不计 FAIL,不会吞掉**,照旧打印。
- 空/无法解析 location 的浏览器自产消息:若当时正在校验的路由加载正常 ⇒ 仍算我们的 FAIL(避免把真违规弄瞎);挑战/失败路由 ⇒ INFO。

已知取舍(诚实标注):`about:srcdoc` / `about:blank` / `data:` / `blob:` 这类**继承父 document 策略**的 frame,Playwright 的 `ConsoleMessage` 不暴露所属 Frame ⇒ 拿不到父 document,一律保守降级 INFO。代价:万一我们自己页面的 srcdoc iframe 触发 CSP 违规会被当噪音;目前站点无 srcdoc 用法(`grep -rn srcdoc static-site/ --include=*.js --include=*.html` 零命中),风险可接受。若将来引入 srcdoc,需要改成按 frame 追踪。
另一条已知取舍(诚实标注,2026-10-27 第 3 轮改写):**按「被违反的策略文本是不是我们文档自己的」判归属**,不再按 location 路径判(实测外部脚本发起的违规 location 报的是脚本 URL,`/app.min.js` 这类正是我们自己的 bundle,按路径判必把真违规当噪音)。残余代价两条:①**text 撞车**:若 CF 注入的策略里某条 directive 的文本与我们的**完全相同**(例如两边都是 `default-src 'self'`),单看消息文本分辨不出来 ⇒ 判 `ours`(FAIL)。方向是「宁可假红不假绿」,可接受;②**同名 directive 缺失即判 foreign**:我们策略里没有某个 directive 时,引用该 directive 的消息判外来(理论依据:Chromium 引用的就是策略原文,我们没写这条就不可能是我们的原文;缺 `connect-src` 由 `default-src` 兜底时,Chromium 引的是 `default-src`,仍能命中)。
**`enforce` 与 `report-only` 都算违规源**(两条头都收、都参与比对):report-only 的越权同样说明「页面确实在请求策略不允许的东西」,只是浏览器没硬拦;对我们自己声明的策略来说,report-only 越权是**该修的真问题**,所以不降级。2026-10-27 13:35 那批 `connect-src 'none'` 噪音之所以判 INFO,靠的是「值不等于我们声明的策略」,不是靠 report-only 标志。
- **CF 注入策略的识别有边界（2026-10-27 复验补）**：我们靠「消息里引用的规则原文 vs 我们自己策略头的同名规则」比对来判归属。如果 Cloudflare 把自己注入的策略塞进**我们同一个策略头**（一个头里写两条规则），我们就分不清哪条是外来的，会把它当成自己的违规拦下来 —— 属于**多报（误拦）**，不会漏报。相对第 3 轮（按策略文本判）这一处不变；相对更早「按消息来源页面路径判」的版本，这类误拦是那时被降噪放掉的、本批又恢复为拦截。注入头的真实形态未经证实。

## 派单模板句(给 reviewer/tester 派单 prompt 复制)

> 用 Playwright 验收脚手架跑前端验收:`node /Users/linhuichen/code/trade/scripts/playwright-accept/accept.js <URL> --expect-request <关键请求子串> --block-on-error`。要点:①URL 本地静态站(先 `python3 -m http.server 8000 -d /Users/linhuichen/code/trade/static-site`)或线上三站(ss.fx8.store / sss.sugas.site / s.sugas.site);②`--expect-request` 断言数据请求发出且 200;③`--block <主源子串>` 屏蔽主源验降级到备源;④`--assert '选择器|期望'` 断言 DOM;⑤`--block-on-error` 使 error 级 console 直接 FAIL;⑥看页面结构用 `node .../snapshot.js <URL>`。

## 参考与致敬

- 基于开源库 [Playwright](https://playwright.dev)(Node.js API,headless Chromium 驱动
  浏览器执行 console 抓取/网络拦截/DOM 断言/accessibility snapshot)。MIT 协议。
