# #88 订阅推送调研:现有能力 vs 原始设想差距盘查(2026-08-22)

> 调研 agent 只读不改;任务源=pending-features-index.md #88「订阅推送(410行,待实施),用户确认保留(手中活清完后评估启动)」。
> **核心结论先行:#88 原始设想(P2-新-K 三层)已于 2026-07-24 由 A12 全量实施上线,是「已完成未销号」条目,不需要开发;唯一真增量是往现有订阅里加自选标的(零代码操作)与 TG 配置激活(填 token,零代码)。**

---

## 一、现有订阅/通知能力全盘点(读代码为准)

### 1.1 两套订阅体系并存(设想外新增了一套)

**体系一:信号订阅(A12 = P2-新-K 本体,2026-07-24 上线)**
| 层 | 实现 | 证据 |
|---|---|---|
| 存储 | CF Workers KV 单 key `subscriptions:v1`,整存整取 `{subscriptions:[...]}`;密码认证(X-Sub-Pwd 对比 secret SUBSCRIBE_PASSWORD);CORS 全开 | worker/subscribe.js L11/L26-37/L39-53 |
| 线上 CRUD | GET/POST/DELETE `/api/subscribe`(列表脱敏/新建更新/删除)+ GET `/api/subscribe/export` 回流 | worker/subscribe.js L112-173 |
| 本地回流 | check_signals.py 跑前 subprocess 调 sync_subscriptions_from_cf.py 拉 KV → config/subscriptions.json(best-effort 失败兜底旧文件) | scripts/check_signals.py L276-296 |
| 过滤推送 | load_subscriptions(L309)→ filter_signals_for_subscription(L333,targets 精确匹配 index_id + signals 类型双维过滤)→ push_subscriptions(L379):复用 build_email 构建专属邮件,主题加 `[订阅:name]` 前缀,email+TG 双通道,notify.send_to 多收件人;每订阅独立去重 data/subscriptions_notified.json(7天清理);#61 增强=订阅邮件带「回测宇宙+AI过滤+AI建议」标记 | scripts/check_signals.py L379-430/L1920-1922 |
| 前端 UI | 指数卡片 h3 🔔 按钮(hasPrivilege('subscribe') gating)→ 订阅管理 modal:密码/名称/邮箱/TG chat_id/标的(index_id 逗号分隔文本框)/信号类型复选框 + 已订阅列表增删改查 | static-site/app.js L5033-5140+ |
| 运行状态 | **链路活**:launchd update_all/intraday 链每天多次触发,日志每天可见「A12 订阅推送:2 个有效订阅」;CF KV 回流每天同步成功 | trade-data/data/logs/check_signals_*.log |

**体系二:AI 每日速递付费订阅(UUMit 商品化线,2026-08-17 上线,P2-新-K 设想外)**
| 层 | 实现 | 证据 |
|---|---|---|
| 存储端点 | CF Workers KV `sub:<key>`(email 或 webhook_url,status active/revoked);管理员 api_key(SHA-256 hash 入 KV)注册/拉取列表,订阅者 sub_key 自助注销/查状态 | worker/subscription_service.js L1-28/L101-208 |
| 推送端 | brief_push.py 每天 20:45(launchd com.trade.brief-push):daily_brief.json 生成后推 email 订阅者(SMTP)+ webhook 订阅者(POST)+ 飞书报告群播报;同日防重 data/brief_push_state.json;非交易日不推;计费 hook 预留 | scripts/brief_push.py L1-45;plist StartCalendarInterval 20:45 |
| 商业化状态 | UUMit 三形态已 API 上架:查询API+订阅=capability pending_review(审核中),数据包=知识商店 published;**当前 recipients=0(尚无外部付费订阅者)** | commit 1ed2a203f;brief_push_state.json 8/17-8/21 连续 5 天 recipients:0 |

### 1.2 推送内容清单(现有全量,按触发时点)
| 推送物 | 触发时点 | 通道 | 受众 |
|---|---|---|---|
| 买卖点信号邮件(check_signals 全局版) | 盘中 intraday 链(约每 10min 一轮,带【盘中实时】标注)+ 收盘 17:50 update_all 终版 | 邮件(Resend)+飞书 report 群(+TG 未启用);去重 signal_notified.json | 用户本人(email.json to=234058394@qq.com) |
| A12 订阅推送(`[订阅:name]` 专属邮件) | 同 check_signals 每轮 | 订阅者各自 email+TG | 订阅者(现 2 条,均用户自己) |
| fade 高位背离告警 | 盘中,仅 red 档,fade_notified.json 去重 | 邮件等 | 用户本人 | 
| D10 收盘情绪速递(daily_summary_email.py --mode main) | 17:50 update_all.sh L259 链内 | 邮件 | 用户本人 |
| AI 每日速递(gen_daily_brief 20:40 生成) | 20:45 brief_push | 飞书报告群播报 + 付费订阅者 email/webhook(recipients=0) | 用户本人+外部订阅者 |
| 运维/采集告警(notify.py severe) | schedule_monitor 等异常时 | 邮件+飞书告警群(TG 占位未启用) | 用户本人 |
| 浏览器通知(前端轮询 notifications.json,30s 节流) | 盘中实时 | SW showNotification(Safari 兜底 new Notification);三层去重(后端 signal_notified.json+前端当日 localStorage+时间窗) | 登录浏览器;6 类=买入/卖出信号、ETF 进场/离场/放量、盘中异动(severe)、高位/低位预警、恐贪极值 | static-site/app.js L11074-11180 |

### 1.3 三通道现状
- **邮件:通,活跃**。已切 Resend(smtp.resend.com:465,user=resend,发件 hi@fx8.store;config/email.json 实测值),notify.py _send_email L758-811 兼容 163/QQ/Resend。
- **Telegram:代码通,配置空壳从未启用**。notify.send_telegram L291 在,check_signals/告警都留了 TG 出口;但 config/telegram.json bot_token='YOUR_B***'(占位符),chat_id 占位——A8(fc27f631)实施后用户一直没填 token, TG 通道实际零流量。
- **浏览器通知:通,活跃**(Chrome 主力,Safari 有兼容修复 a73)。注意架构是「前端轮询+本地弹通知」非 VAPID 真 web push(memory notify-email-vs-push 已记录),页面不开收不到。

## 二、原始设想还原(P2-新-K)
出处:NOTES.md 小节AZ2(L2051)+ docs/archive/TASKS-history-archive-20260820.md L464:
> 「P2-新-K 订阅个性化推送(~410行,完全空白分阶段):scripts/ 和 app.js grep subscribe/订阅/favorite 全空。3层新建(存储config/subscribe.json + check_signals过滤 + 前端订阅UI)」

设想范围=个性化信号订阅推送:用户挑标的+信号类型 → 有信号时推给用户。**没有涉及**:每日速递订阅、webhook、付费化、浏览器通道(当时 W 浏览器通知是另一条并行方向)。

## 三、差距矩阵(设想 vs 现有)
| # | 设想项 | 判定 | 证据 |
|---|---|---|---|
| 1 | 存储层(config/subscribe.json) | ✅ 已有且超设想(CF KV+密码认证+线上 CRUD+回流兜底) | subscribe.js 全文;wrangler.jsonc kv_namespaces SUBSCRIBE_KV(id 7d373c33) |
| 2 | check_signals 订阅过滤推送 | ✅ 已上线且增强(#61 AI 标记/独立去重/多收件人) | check_signals.py L275-430/L1922 |
| 3 | 前端订阅 UI | ✅ 已上线(🔔+modal+列表管理) | app.js L5033+ |
| 4 | 推送通道 email | ✅ 通(Resend) | config/email.json |
| 5 | 推送通道 Telegram | ⚠️ 代码在,config 占位符,**从未启用** | telegram.json bot_token='YOUR_B***' |
| 6 | (隐含)实际推送发生 | ❌ **上线至今零发出**:subscriptions_notified.json 从未生成;日志每日「A12 订阅推送完成:无订阅成功推送」 | trade-data/data/subscriptions_notified.json 不存在;check_signals_20260821_*.log |
| 7 | (设想外)UUMit 付费速递订阅 | 已建成上架 pending_review,recipients=0 | subscription_service.js;brief_push_state.json;commit d6b17e449/1ed2a203f |

**为什么挂了「待实施」:TASKS 归档总览行 L464 是 2026-07-23 落档的快照,次日(7-24)A12 就实施并在 NOTES AZ8 标✅(L2290「对应 TASKS P2-新-K ✅」,commit c703a584f 前端+3d29c05c4 后端),但归档总览行没回写;2026-08-20 补登记模块十六时按旧行判断成「待实施」。典型档案漂移,不是功能缺口。**

### 零发出的根因(诚实标注)
两条订阅 targets=['sz']/['sh'](裸上证/深证成指),创建于 7-28;而 signal_daily 里 sh/sz 最后一条信号=2026-07-21(MAX(date) 实测),即**订阅创建日起标的本身零新信号**→ 过滤永远空 → 零推送。这是数据事实非 bug:sh 月均信号仅 1-5 条(2026-04:4/05:3/06:1/07:5),宽基本来极低频。
- ⚠️ 待进一步验证项:A股全部宽基(csi500/cyb/hs300/kc50/sz50/csi1000)最后信号停在 7-15~7-27,8 月宽基零信号但 sw_ 行业/g. 全球/s. 分数类照常出信号——大概率是 8 月单边上行行情(RSI 不下 30/不破 20 日低)所致,但不排除宽基检测输入断链,建议后续顺手核一次宽基指标计算输入(不在本调研范围展开)。

## 四、价值与成本
| 候选项 | 工作量 | 用户视角真实价值 | 判定 |
|---|---|---|---|
| 销号:#88 标已完成(pending 索引改状态引 A12 commit) | ~10min 文档 | 防重复立项/重复调研(本次就是被「待实施」误导的第 2 次) | 必做 |
| 往现有订阅加自选标的(行业 sw_* / ETF / 海外指数) | 零代码(线上弹窗或编辑 subscriptions.json) | **真增量**:订阅链路全活,加标的即生效;比订 sh/sz(月均 1 条)有价值的是高活跃标的 | 建议(若要订阅价值) |
| TG 通道激活 | 零代码(用户 @BotFather 拿 token 填 telegram.json) | 低:邮件+飞书+浏览器三通道已在跑,TG 边际小;且 TG 国内需反代 | 仅用户点名才做 |
| 订阅弹窗 targets 文本框 → 标的搜索下拉 | ~100-150 行 app.js | 低:单用户场景,文本框够用 | 不建议现在做 |
| UUMit 付费订阅推广/计费对接 | 商业决策非开发 | 外部收入线,服务端已就绪等审核通过 | 独立线,不属于 #88 |

## 五、结论建议
**一句话:#88 不需要做开发——原设想已被 A12(commit c703a584f/3d29c05c4,2026-07-24)全量实施且链路每天在跑,应关闭销号;唯一有真实价值的动作是把自选标的加进现有订阅(零代码)或激活 TG(零代码,需用户拍板),其余(订阅 UI 美化/UUMit 计费)均属低价值或独立商业线。**
第一批实施范围提案(若用户拍板):
1. pending-features-index.md #88 改「已完成(A12 c703a584f+3d29c05c4)」移 done-list;
2. (可选)用户从首页指数卡 🔔 弹窗把想跟的标的(如高活跃行业/海外指数)加进订阅;
3. (可选)TG 激活:填 telegram.json 即全链路通(含订阅推送/告警出口);
4. 顺手项(另开小单):核一次 8 月 A股宽基 signal_daily 零信号的生成层输入是否正常(见三·待验证项)。

## 复现
```bash
# 1) KV 订阅接口存在与结构
sed -n '1,60p' worker/subscribe.js                      # C 方案注释/KV key/密码认证
cat wrangler.jsonc | grep -A4 kv_namespaces             # SUBSCRIBE_KV namespace id
# 2) 推送链路
grep -n "push_subscriptions\|load_subscriptions\|filter_signals_for_subscription" scripts/check_signals.py
sed -n '379,430p' scripts/check_signals.py              # 推送实现
# 3) 前端订阅 UI
grep -n "A12 订阅推送" static-site/app.js               # L5033 起
# 4) 运行证据(链路活但零发出)
grep -h "A12\|sync_subscriptions" /Users/linhuichen/code/trade-data/data/logs/check_signals_20260821_*.log
ls /Users/linhuichen/code/trade-data/data/subscriptions_notified.json   # 不存在=零发出
python3 -c "import json;print(json.load(open('config/subscriptions.json')))"          # 2 条订阅 targets=sz/sh
# 5) 零发出根因(标的无新信号)
sqlite3 /Users/linhuichen/code/trade-data/data/sentiment.db \
  "SELECT index_id, COUNT(*), MAX(date) FROM signal_daily WHERE index_id IN ('sh','sz') GROUP BY 1;"
sqlite3 /Users/linhuichen/code/trade-data/data/sentiment.db \
  "SELECT substr(date,1,6),COUNT(*) FROM signal_daily WHERE index_id='sh' GROUP BY 1 ORDER BY 1 DESC LIMIT 4;"
# 6) 三通道现状
python3 -c "import json;d=json.load(open('config/email.json'));print({k:(v[:10]+'***' if k=='password' else v) for k,v in d.items()})"   # Resend
python3 -c "import json;print(json.load(open('config/telegram.json'))['bot_token'])"     # YOUR_B***=占位未启用
plutil -p ~/Library/LaunchAgents/com.trade.brief-push.plist                              # 每日速递订阅推送 20:45
cat /Users/linhuichen/code/trade/data/brief_push_state.json                              # recipients=0
# 7) 原始设想与 A12 实施 commit
sed -n '2051p' NOTES.md                                                                  # P2-新-K 设想原文
git log --oneline -1 c703a584f; git log --oneline -1 3d29c05c4                           # A12 前后端 commit
```
数据截止:2026-08-22;口径:信号订阅=体系一(worker/subscribe.js+A12),付费速递订阅=体系二(subscription_service.js+brief_push.py),两套并存互不复用。

---

## 六、追加闭环(2026-08-22 主控追派):8 月 A股宽基 signal_daily 零信号 = 行情原因 + 卖点过滤器设计行为,**非生成层 bug**

### 6.0 口径澄清(先纠偏)
signal_daily 是**指数级**信号表(index_id=sh/sz/hs300/sw_*/g.*/s.* 等),**里面没有 ETF**——ETF 信号是另一张表(etf_national_team.db 的 etf_signal,汪汪队链路),该表 8 月出 6 条信号、最新 2026-08-19,**ETF 链路完全正常**。「A股全部宽基 ETF 零信号」的准确表述应为「A 股宽基**指数**(sh/sz/sz50/hs300/csi500/csi1000/cyb/kc50)8 月在 signal_daily 零信号」。

### 6.1 生成层三层验证(全活,排除断档)
| 层 | 验证 | 结果 |
|---|---|---|
| 输入层 | index_daily 宽基 9 标的 | MAX(date)=**20260821** 全部新鲜(sh 8709 行/hs300 5976/cyb 3941...) |
| 配置层 | trade/ 与 trade-data/ 两份 config/indicators.yaml 的 indices 段 | 宽基 8 标的全部 enabled=True,未被移除 |
| 调度层 | app/compute/runner.py L23 `signals.store(sigs)`(DELETE+INSERT 全量重算,signals.py L1444)+ 盘中 intraday_snapshot.py L1861 | 每天 4 次在跑(signal_daily 8 月仍新增 191 条,sw_/g./s. 类照常出) |

### 6.2 复算器对齐校验(证明复算口径=生产口径)
用 signals.py 同款公式(_rsi Wilder ewm α=1/14 / 布林 20 日 2σ ddof=0 / D1=hh20×0.95+MACD死叉+MA60 过滤 / ATR14×3.5 Chandelier 首次跌破)离线重算 7 月:8 标的生产信号 30 条,复算命中 **27/30**(漏 3 条均为 7 月初 sell,系复算器 rolling 窗口边界微差,方向不受影响)。脚本逻辑同 /tmp/resim_wide_base.py(见复现段)。

### 6.3 八月零触发逐类机制(硬数据)
| 信号类 | 触发条件(signals.py 行号) | 8 月实测 | 定性 |
|---|---|---|---|
| C1 主买 | RSI14 上穿 30(L969-974) | RSI 全月最低 35.0(kc50),其余 37.5~42.7,**从未 ≤30** | 单边偏强无超卖,行情 |
| B1 辅买 | 收盘从布林下轨下回上来(L981-983) | 8 标的收盘低于下轨天数**全为 0**,前提不成立 | 行情 |
| D1 卖 | 20日高回落 5% + MACD 死叉 + close>MA60(L997-1003) | 原始回落事件**存在 5 次**(sz 08-11/08-19,csi500/csi1000/cyb 08-19),但当日 MACD 全部未死叉=False 且 close 已在 MA60 下方 → 双过滤按设计拦截 | **过滤器设计行为**:深跌时已处 MA60 下=多头趋势已坏,不给多头发"止盈减仓"提示 |
| A1 追止损卖 | close 首次跌破 hh20.shift(1)-3.5×ATR14(L1052-1061) | sh/sz/csi500/csi1000/cyb/kc50 **7 月底已在线下方**(首次跌破已在 7 月触发过),事件化设计持续在下方不重复出;hs300/sz50 未破线 | 事件化设计行为 |
| B 特买 | Donchian20 上破 shift5+5日站稳(L1014-1016/L1062+) | Donchian 突破源头事件 sh 2 次/其余 1 次,但未通过站稳确认+h5/R2 峰值过滤 | 未达最终条件 |
| 备买 | Supertrend(10,3) 翻多+3日确认(L1034/L1080-1090) | 未触发 | 行情 |

### 6.4 一句话定性
**8 月宽基指数零信号 = 单边偏强行市(C1/B1 买点前提"超卖回归"整月不成立)+ 卖点双重过滤与首次跌破事件化的设计行为(D1/A1 的原始触发条件在 8 月其实出现过 5 次,均被 MACD/MA60 趋势过滤或去重机制按设计拦下),输入/配置/调度三层全部健康,不是 bug。订阅推送零发出根因维持原判(订的 sh/sz 自创建日起无新信号=低频宽基常态)。**
附带洞察(不改判定):D1 的 5 次被滤事件集中在 08-11 与 08-19,即宽基 8 月确有两波回调,只是都跌破了 MA60(趋势坏),按现有设计这类"趋势内止盈"信号宁可错过不误发——若未来想要"弱势也提示减仓",那是策略口径变更(动核心算法须走 §5.4⑥ 版本升级),不属于本调研建议范围。

### 复现(第六节追加)
```bash
# 三层验证
sqlite3 /Users/linhuicheng/code/trade-data/data/sentiment.db "SELECT index_id,MAX(date) FROM index_daily WHERE index_id IN ('sh','hs300','cyb') GROUP BY 1;"   # 输入层=20260821
python3 -c "import yaml;c=yaml.safe_load(open('/Users/linhuichen/code/trade-data/config/indicators.yaml'));print([(i['id'],i.get('enabled',True)) for i in c['indices'] if i['id'] in ('sh','sz','hs300','cyb')])"  # 配置层=True
grep -n "signals.store" /Users/linhuichen/code/trade/app/compute/runner.py   # L23 调度层
# 口径澄清:ETF 是另一张表且活着
sqlite3 /Users/linhuichen/code/trade-data/data/etf_national_team.db "SELECT COUNT(*),MAX(date) FROM etf_signal WHERE date>='20260801';"  # 6|20260819
# 复算脚本(公式对齐 signals.py):/tmp/resim_wide_base.py + 本文 6.3 补充段(python 内联,输出 8月D1原始事件/布林下轨天数/止损线状态)
# 生产对照
sqlite3 /Users/linhuichen/code/trade-data/data/sentiment.db "SELECT index_id,MAX(date) FROM signal_daily WHERE index_id IN ('sh','sz','sz50','hs300','csi500','csi1000','cyb','kc50') GROUP BY 1;"
```
