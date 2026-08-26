/*
 * tdsignal Service Worker - A6 PWA
 *
 * 缓存策略(任务约束):
 *  1. App Shell (HTML/CSS/JS/vendor/图标/manifest): CacheFirst
 *     - 关键静态资源预缓存,离线可用
 *     - 改 CACHE_VERSION 清旧缓存,skipWaiting+clients.claim 立即接管,提示用户刷新拿新版
 *  2. 数据 JSON (除 intraday_snapshot): network-first (正确性优先, 失败回退缓存)
 *     - 2026-08-02 改: 原走 SWR 先返旧缓存后台拉新版, 低频数据(季频 public_fund_* /etf_score_list)更新后用户仍拿旧缓存
 *     - 改 network-first 每次走网络拿最新, 离线/失败回退缓存(牺牲毫秒延迟换正确性)
 *  3. intraday_snapshot.json + notifications.json: NetworkFirst (盘中实时性优先,离线回退缓存)
 *  4. 第三方 (hm.baidu/zz.bdstatic/echarts CDN 等): 跨域不拦截,直接走网络,不缓存
 *
 * 版本号破缓存: 改 CACHE_VERSION 即可让所有客户端清旧缓存 + 提示刷新
 */

const CACHE_VERSION = 'v6-20260826-a429';  // a324->a325 = lite-svg perColor 渐变 id 全文档冲突根治(2026-08-17, 纯前端app.js, B级, §23.2/§23.3/§22): _lwGradSeq 原为 _lwSVG 内块级 let, 每图从0起 → 每张图第一个 perColor 渐变都叫 lwGrad-1; SVG url(#lwGrad-N) 引用是全文档解析到第一个匹配 id → 恐贪(渲染最早)用自己渐变正确, 情绪分/跨市场/过拟合全解析到恐贪渐变错误(跨市场灰7.3%应44.9%/浅蓝0应60, 与用户"缺灰/错位"吻合). 修=_lwGradSeq 提到模块级(照 _lwZClipSeq 示范), 渐变 id 全文档唯一 lwGrad-1/2/3..., 每图 url(#lwGrad-N) 唯一解析到自身渐变. §23.2同类覆盖: 首页恐贪/情绪分/跨市场 + 过拟合风险分图(L1777 绿黄红同污染) + KPI弹窗/信号弹窗 perColor 同分支, 一处改全部好. 自验=headless Chrome 组合页逐图: 4图 id lwGrad-1..4 唯一, 每图 path stroke first-match=自身渐变, 过拟合@v45黄/跨市场@v75浅蓝/红绿黄恢复; 旧bug仿真: 跨市场@v20灰被渲染成蓝(缺灰)/overfit@v45黄变灰. 根因+证据落档 docs/lite-svg-grad-id-collision.md. 同commit重建min+bump;  // a321->a322 = 首页三张分段色图(SVG轻量版)变色分界点校准(2026-08-17, 纯前端app.js, B级, §23.2/§23.3/§22): 恐贪/情绪分/跨市场三张0-100温度计图值域原走数据自适应(_lwValueExtent nice extent, 恐贪[20,90]/跨市场[30,100])致渐变拉伸, 用户读图切点偏离0-100直觉(黄红分界~75/蓝灰贴底~10); 修=_lwLineCard liteCfg ys + echarts fallback yAxis 固定 min:0 max:100, 渐变/曲线同_py映射, 颜色切点精确落 20/40/60/80(恐贪25/40/60/75), 与既有过拟合风险分/准确率图(已固定0-100)一致; §23.3同类: KPI详情弹窗9张sentiment情绪分(_kpiLiteCfg+echarts)同样自适应漏固定, result.yRange=[0,100]一并固定; 信号弹窗/分时/家数/涨跌比非温度计不改. 自验=线上overview三图渐变stop像素==曲线同值像素(差0.000px)+切点值偏差0.12(采样粒度), 对照表docs/lite-svg-grad-calibration.md. 同commit重建min+bump;  // a319->a320 = 首页走势图「T日提示」今日锚bug修复(2026-08-17, 纯前端app.js, B级, §23.2/§23.3/§22): overview.date盘中过时(814)但signals_today含817→_todayDateB2原锚overview.date=814致817才有信号的指数(sw_801130等)漏判"T日有信号"误报数据截止; 修=_todayDateB2改signals_today最新日期(max只前进不后退,同_renderSignalGrid L2480-2487锚法), _hasTodaySigB2/_lagHint随锚自动对齐; 自测线上overview模拟: 旧锚sw_801130漏判false→新锚true正确. §23.3同类扫描: L6414 KPI预估overview.date=T+1源设计(814有值817无值补814正确)标注不改; L7038/L7040角标=数据新鲜度语义非今日判定不改; L3053/L11254_renderSignalGrid今日高亮/排首已max修复覆盖; L2573信号卡排首基于items最新日期已覆盖. 同commit重建min+bump; // a311->a313 = 恒指分时+5%虚高根治(2026-08-17, 纯前端app.js, B级, §23.2/§23.3/§22): 同花顺港股源(hsi/hscei)停更错位(日K最新2026-04-21, 自带昨收实为停更前收盘), 前端拿错曲线+对不上后端快照正确昨收→恒指分时幅度虚高+5%. 根治=港股指数(hsi/hscei/hstech)一律不走同花顺, 统一走东财push2delay(100.HSI/100.HSCEI/124.HSTECH)+腾讯(hkHSI/hkHSCEI/hkHSTECH)双源(与后端快照一致, 实测HSI +1.46%/HSCEI +1.42%/HSTECH +1.64% vs 后端+1.37%/+1.33%/+1.57%); 同花顺批量只服务A股. §23.2同类排查: _INDEX_TO_THS_CODE 仅含A股+hsi/hscei, 无其他全球指数(ftse100/kospi/dax/us_*都不在); §23.3消费点: 分时图tooltip/badge/spark-foot/banner均读_fetchDynamicPcts单源结果, 单点修源全修(横幅chips仅A股不受影响); 后端快照采集不动. 同commit重建min+bump; // a310->a311 = 修两处展示数据不正确(2026-08-17, 纯前端lab.js, B级, §23.2/§23.3): ①样本外榜「低过拟合」min-max归一化被full_in全仓复利极端离群值(519.63)压平→overfit归一化前95%分位截断抗极端(p95≈61.85),替补🔵full_in行≥0.95从88.3%→57.1%区分度恢复,主候选⭐️Top12逐位不变(主候选overfit全≤1.56≪61.85);②成本对比顶部文案口径标错(loDecay/hiDecay实为总收益相对降幅却写"年化约降"夸大)→措辞改「总收益约降+折算年化0.4~5.4pp,见下表年化列」(数字核实源lab_cost_compare.json)。legend同步更新(补95%截断+局限改"已截断但全仓复利与定额两尺度仍同池,跨模式比较需谨慎")。落档 docs/lab-out-of-sample-normalization-bias.md + docs/scripts/analyze_oos_normalization_bias.py。同commit重建min+bump; // a309->a310 = 全站复杂说明补「1:1 直白举例」第四批 #15-#20(2026-08-17, 纯展示文案, §23.9三档互证教学法, B级): #15 lab.js 交易表表头 补 上证BB下轨反抽×MACD死叉 固定1万·近5年 首两笔 连环算例(账户/累计盈亏/累计收益率/较上次); #16 lab.js 成本对比 补 上证Donchian20×MACD死叉 全仓进出 毛年化20.4%→含费低档18.9%→高档17.5%; #17 lab.js G/H/I仓位管理 补 G模式 关(旧FIFO峰值136万不可操作)vs 开(13万P≤3d b0 155.8%) 开关前后; #18 lab.js 推荐规则 补 可操作性→收益率→佐证 决策链例子; #19 lab.js 组合降亏预设宏 4预设tip各补1:1(年末季节并集6.50/稳健核心5.95+30.8万6年全正/最大化降亏A/F+19-26pt/1月调整-56万); #20 lab.js 配对排行质量指标 补 上证BB下轨反抽×BB中轨突破 胜率55.3%+盈亏比1.59+期望+2.38% 三数怎么读。纯展示文案不改算法/数值语义, 1:1数字均从数据产物逐位核实(lab_sim_sh_full/stats.json、lab_cost_compare.json、kelly-g-mode-recheck.md、kelly-combo-round3-verify.md), 同commit重建min+bump; // a307->a308 = 全站复杂说明补「1:1 直白举例」第二批 #7-#10(2026-08-17, 纯展示文案, §23.9三档互证教学法, B级): #7 purpose-notes lab.sigkelly 补 高评级信号G模式全周期85笔/61.2%胜率/2.95盈亏比/半凯利24%(保守) 1:1算例; #8 lab.js 全信号表按年窗口增长 补 2021年G模式 过程回撤-8.7% vs 年末净结果-3.8% 的两把尺子 1:1(2026-08-16数据实时重算); #9 common.js K档评级 补 K1=单笔1万(86.6%) vs K3=3笔各3333元(66.2%) 的每日资金池拆分 1:1; #10 lab.js 三玩法披露 补 G模式可操作口径P≤3d 峰值持仓13万→最小本金6500元(13万÷20) 1:1。纯展示文案不改算法/数值语义, 1:1数字均从数据产物逐位核实(评级象限/按年聚合重算/K快照/G档参考), 同commit重建min+bump; // a305->a307 = lite-svg perColor 分段色变点两缺陷根治(2026-08-17, 纯前端app.js, B级, §23.2/§23.3): ①转折尖角 — _lwLineDIdxCtx 段首(k===kStart, 即跨色段共享端点)借前一色段最后点做中心差分, 使下段「离开」切线与上段「到达」切线共线(折角→0°, 色变点真平滑; 仅非首段且相邻 idx 差=1 不跨 null 时借, 否则取自身); ②颜色切换滞后 — connectNulls+perColor 段循环绘制起点与颜色判定起点分离(首段画[0,re0]; 后续段绘制起点=上一段 re 共享端点保线连续、颜色判定起点=rs2 新色), kEnd 由桥接 _nxt(=re+1) 改 re(画到旧色最后点止), 色变点 re→re+1 之间改由下一段新色绘制 → 颜色在色变数据点精确切换不再滞后。自测: 恐贪/情绪分/跨市场三图 色变点折角 111.0°/36.1°/90.0°→0.0°(复现脚本+忠实新代码验证), 共享端点平滑 0.0°, 颜色去向色对齐, 线连续, 首点/末点/跨null/单点色段 6 边界用例无崩不尖。同根因 5 消费者(恐贪L11099/情绪分L11170/跨市场L11472/过拟合风险分L1777/信号弹窗L4670)走同一分支自动生效, _lwLineDIdx(单色)/_lwLineD(常规)/非connectNulls perColor分支(L12598-12628 无消费者)不动。同commit重建min+bump; // a292->a294 = 首页技术分析参考点空态横条文案改具体日期(2026-08-16, 用户已确认, 纯前端app.js, B级, §23.2): 原写死「今日无 AI 建议买入信号,仅风险/持有状态」, 但横条是对每个日期组判定(非仅在今日), 非今日历史日期触发时"今日"指错日期; 改 `${dateLabel} 当日无 AI 建议买入信号,仅风险/持有状态`(dateLabel=fmtDate(dt)如"08-14")带具体日期, data-tip 同步补 `(${dateLabel})` 并与"该日"措辞自洽; 触发逻辑 `_pcOn && !_dateHasInUniverseBuy[dt]`/日期格式/其它均不动(§23.2同类排查: `.sig-empty-universe` 文案全站仅 L2820 一处, 无重复); // a284->a285 = 用户产品决策重构: 移除 AI预测弹窗顶部新闻区块 + 首页新闻外露两行(2026-08-16, 纯前端app.js+style.css, B级, §23.2/§23.3/§23.7): 用户认为弹窗顶部独立放新闻不合适(弹窗是看AI预测不是看新闻), ①移除弹窗 newsBlockHtml 区块(含 a282一次性渲染 + a283/a284 弹窗日期标注一并取消, 该区块整个不要了) ②首页 AI预测卡下方「📣今日要闻」外露速览行(重要优先≤3, 时间+标题压缩, 标日期 8月16日, 复用 db-nextday-row 样式, guard=无数据整行隐藏) + 「📅明日关键事件」行标日期(8月17日, a284), 一上一下相邻(summmary-news-row 内两 db-nextday-row, 第二行 margin-top:6px) ③历史收盘分析「当日大事」事件对照保留按日期匹配(符合新方向) ④新增 _dbHomeTodayNewsRowHtml + 保留 _dbTodayNews/_dbNewsDateCn/_dbTomorrowDateCn/_dbUpcomingEvents/_dbHistoryNewsHtml, 删除 _dbNewsBlockHtml 及弹窗专用死CSS(.db-news-modal/block/sec/sec-t; 保留 .db-news-ul/time/title 给历史对照) ⑤新闻完整入口仍指向后续独立「📰新闻」, 首页只做外露速览; 同commit重建min+bump; // a283->a284 = 明日关键事件日期标注追加(2026-08-16, 用户同批需求并入, 纯前端app.js, §23.3举一反三): 首页「明日关键事件」行 + 弹窗「明日关键事件」区 标题统一补明日日期——新增 _dbTomorrowDateCn(由 news_digest.date 推断次日「8月17日」, UTC 边界月末/跨年正确; upcoming 无结构化日期字段, 标题区统一标「明日（X月X日）」宁缺毋滥, 不逐条臆造; 无 date 降级「明日关键事件（预告）」不报错); 首页 _dbNextDayRowHtml 签名 +date 参数(调用点传 nd); 弹窗 upLabel 同逻辑; 与 a283 三处今日要闻/当日大事日期标注共同构成三展示位日期全覆盖; // a282->a283 = AI预测弹窗「今日要闻」区块一次性渲染bug修复(2026-08-16, 纯前端app.js, B级, §23.2三铁律): ①删 newsBlockRendered 一次性guard——原每次会话仅首开弹窗渲染news区块、之后恒空串消失; 改每次打开都执行 _loadNewsDigest+_dbNewsBlockHtml 渲染(_newsDigestCache 缓存防重复请求, 渲染幂等, 无数据空态不阻塞); ②「📣今日要闻」标题补日期(_dbNewsDateCn 归一化 2026-08-16/20260816 → "8月16日", 有date显示「今日要闻（8月16日）」, 无date退化"今日要闻"不报错); ③§23.3举一反三: 历史收盘分析「当日大事」标题同步带日期(_dbHistoryNewsHtml nuth 有 date 字段); 首页「明日关键事件」行入参仅事件数组无 date 且为紧凑单行, 不强带(说明); ④同类排查§23.2③: 全站 _dailyBriefState.*Rendered 仅 todayFetched(取数防重复,合理未删)+newsBlockRendered(本次删), newsBlock 仅弹窗一处, 无其他"HTML渲染混用一次性guard"; 同commit重建min+bump; // a279->a280 = 死CSS清理(P2, 2026-08-16, 纯CSS冗余非逻辑, §24): lab.css 删21个全零引用死class(lab-title/lab-detail-key/lab-sim-controls|mode-toggle|desc/lab-signal-tabs|tab/lab-fusion-pair-filter|legend|section|mode|table+lab-fp-win|n/lab-fusion-core-divider|detail/lab-sigkelly-fee-apply|posrate-k/wm-top1|out|mix), lab.min.css 93472->89648B(-4.1%) rebuild; README 6宽基已核对正确不动; overfit K按钮无title/data-tip祖先+无自有hoverpop=不被term-pop捕获, 无需data-no-pop; // a278->a279 = 信号固化提示条文案「跟版本走」修法①(用户已确认, 2026-08-16, 前端app.js+后端queries.py, B级, §21公示+§22+§24): ①后端 _finalized_note 拆 full/evening 两分支(full=进行式"A股15:03已定稿、港股/欧股/国债17:50起补齐,21:00指数补采后最终定稿"; evening=已定稿态"当日信号已定稿:A股15:03、港股/欧股/国债17:50已补齐;晚发指数补采(21:00)可能再补") ②前端 _signalFinalizeBannerHtml barTxt 直接消费 meta.finalized_note(单一事实源),不再硬编码full/evening时间文案,保留三态前缀+a-share-close可操作后缀 ③purpose-notes.js 信号固化时点段按full/evening拆分同步公示 ④§22一致性:后端4分支文案grep确认+前端无硬编码残留(from a277 rebase+fix版本冲突改a279); // a267->a271 = 分析参考点AI监控卡改造+AI降亏过滤(feat/overfit-monitor-ai-filter, 2026-08-15, B+C级, §21公示+§23.6+README+§24): ①后端 overfit_monitor.py 抽 _compute_bank 并行生成 未过滤/已过滤(filtered) 两套 accuracy+overfit bank, 过滤判定=AI宏9规则(8键+未入样本, 与 queries._ai_macro_hit_filters+_bt_in_universe 同源 v1.1.0), 复用 queries 逻辑; version v1->v2 ②前端 app.js 卡改名「分析参考点AI监控」+❓弹窗bug修复(signalHelpTip->termTip, 不再误弹技术信号modal)+「特买」->「追买」术语统一+加「AI降亏过滤」开关(默认关, localStorage tds_overfit_fade, 切读 data.filtered Bank 不自算) ③style.css 加开关样式; // a260->a261 = v1.1.0: K2C5 港股追涨加入默认AI降亏过滤(2026-08-15 21:5x 用户拍板, lab.js, B级, §21公示+§24+bump+README §23.1): ①_kellyDefaultFilters k2c5HkChase false->true(默认开; K3 维持默认关不动) ②K2C5 toggle tip 补默认开+诚实标注(全信号除G外双升 A/F/H多年稳定/I微负-1,365; G因强平兑现口径 b0(保守-2,256)/b1(乐观+11,755)方向依赖口径, 真实强平收益在区间不把b1当承诺) ③数据支撑 docs/kelly/analysis/kelly-k2c5-return-quadrant-check.md ④CLAUDE.md §5.4 基准 v1.0.0->v1.1.0 + memory test-baseline-v110-anchor.md;  //  a259->a260 = 首页调教监控卡完整改造(2026-08-15, B+C级, feat/overfit-dim-20260815, §21公示+README+README §23.1): ①数据层 scripts/overfit_monitor.py——回测准确率样本去重((mode,signal_date,index_id,signal), n 90048→22794 去 ~4x 跨象限重复, 全史等权胜率 55.70→55.71 与现状一致, 修正 n 虚高11.85x); 新增 accuracy.rolling.by_signal/by_grade 维度(裁剪365天) + overfit.daily_by_win(30/60/90三套) + daily_by_dim(评级/类型, 60日) ②前端 app.js——三组按钮(窗口/评级/类型)两图联动(syncOverfitCharts), 维度曲线读取, 风险分 visualMap 绿黄红按值变色(30/60参考线对齐), 卖出类回测仅买入单曲线, 近窗n<20空态提示(不画误导曲线) ③style.css overfit-win-row 允许换行 ④README 补维度切换+去重+诚实标注 ⑤同commit重建min+bump; a257->a258 = 修 reviewer FAIL(free/free-multisource-fallback, 2026-08-15, app.js QVIX 公示诚实化 §21 + README 致敬/截断句 §23.1 + docs 对账): QVIX 6处公示「主源宕机时以上交所官方IV自算兜底(同口径)」改为如实声明「主源(optbbs)宕机时QVIX降级为本地RV(已实现波动率,非隐含波动率)近似;上交所官方IV自算仅用于当日补采档(T+1,同口径)」; README 补 nkuguanrui/ivx 致敬 + HKEX datacdn 截断句修; docs/qvix-data-sources.md 对账(实现用 SSE 510050 而非新浪 mo 链原因); 同commit重建min+bump;  // a256->a257 = 修 reviewer P2 公示诚实性+小清理(2026-08-15, pure前端 app.js/lab.js/purpose-notes.js, B级, §21/§5.1/§23.7): P2-1 overfit G口径诚实标注(signalHelpTip+README: G=信号驱动卖出全量不含P≤3d, 峰持仓136万不可操作) P2-2 K2C5/K3笔数改实算(948/4440->独立信号728/3775, unique完整身份去重口径, 溯源无出处) P2-3 删 purpose-notes.js 孤儿键 overfit_monitor(无渲染点, 卡内用signalHelpTip防双份漂移) P2-4 排序ratio归一helper(字符串"待实测"->-1置底, 消NaN) P2-5 app.js删markArea空块+_overfitCardChartsPush占位行; 同commit重建min+bump;  // a234->a235 = K档位历史对比行高修复(2026-08-15, 纯CSS lab.css, B级, §23.2): 「投资习惯/建议/真实回测数据」3列表格规则原选择器 .lab-sigkelly-advice-body > 过宽, 误命中同class的「K档位历史对比」6列表(L9009, poscap-history 内 advice-body 直子→后3列table-layout:fixed压0宽+white-space:normal+疯狂换行→行高164vs正常28); 加 .lab-sigkelly-advice-outer 前缀=只命中 advice-outer 内 advice-body 直子(3列表本意目标 L9593), K档表在 poscap-history 内不再命中恢复默认nowrap行高28px; 举一反三全站扫: 无其他"为3列表设计但选择器过宽"规则, afg/yearly 专属选择器隔离, poscap-history 专属 line-height 规则不受影响; 同commit重建lab.min.css+ref版本串;  // a232->a233 = 凯利降亏区交互修复(2026-08-15, 纯前端lab.js, B级): ①问题1 AI降亏过滤详情 展开态持久化到 state.labSigKellyAiDetailOpen(参照 labSigKellyMoreOpen 模式, 点小标签/组合按钮重渲染后保持展开, 不回落默认收起; 按钮textContent+body初始style均读该state); ②问题2 更多开关折叠区去重(滤掉顶部默认推荐7键的 rec flags, 只渲染非默认24个, 组标题count用过滤后长度, 空组跳过——消除与顶部推荐区重复); ③举一反三: 4大分类组 手工收/展态持久化到 state.labSigKellyCatCollapsed(重渲染后保持用户手工收展, 默认仍全展开不破坏原设计); 核查 G/H/I 对比表(_gihCompareOpen 模块级变量重渲染保持)与组合建议外层(state.labSigKellyAdviceOpen 已持久化)均无需改;   // a230->a231 = P0 "$ is not a function" 修复(2026-08-15, build_min.py terser mangle 加 reserved=['$']): terser 把局部函数(如 _isSellSig)重命名为最短名 `$`, 但 app.js/lab.js/common.js 全文件 37+ 处已把 `$` 用作普通局部变量(字符串/数组/布尔, 不同作用域) → 作用域遮蔽冲突 → 首页信号渲染 AI警示分支 "$ is not a function"。reserved 让 `$` 永不被 mangle 复用, 根除所有 min 文件 `$` 复用冲突(全局统一 min 内容变更, 需清缓存重拉 app/lab/common.min.js); // a229->a230 = 公示补「+1」  // a229->a230 = 公示补「+1」(2026-08-14, 纯公示文案 purpose-notes.js+app.js+lab.js+common.js, 不动算法/过滤行为, §21/§23.3, B级): AI宏7键升级公开为「AI宏4+3+1」——4=基础4+3=核心3为保留入样、可被AI建议推荐的降亏键, +1=回测/凯利模型层剔除的一整类信号(波动相关信号+未入样本信号, 债类cgb_*/情绪s.*/全球商品利率g.*/港股行业hk_*/空数组, _bt_in_universe=false), 语义=这类信号虽同属全信号, 但按宇宙规则被回测剔除故 AI建议 一律不推荐; 同步修 reviewer S1: 上版注释中「任一开启=进入AI过滤视图」的过时变量名引用已清(该变量在代码中不存在), 正确表述为「两开关正交各管一层: AI降亏=删除线层, AI仓位=badge层」; // a228->a229 = 首页「AI过滤视图」改造(2026-08-14, 纯前端app.js+style.css, §23.6/§21): 用户新视图口径「只显AI推荐, 其余直接过滤置灰标原因」——两开关正交各管一层(下述各产各的badge/标注, 不互相触发): AI降亏过滤(_fadeOn/tds_home_fade, 删除线层)+AI仓位建议K档(_pcOn/tds_poscap.on, badge层), 新增两态: ①入宇宙卖出(sell/sell_stop_loss/波段减仓)=亮色+「AI警示」badge(sig-poscap-warn, 醒目警示橙, 卖出=离场保护非过滤不置灰, 无K约束不判K); ②未入宇宙(债类cgb_*/情绪s.*/全球商品利率g.*/港股行业hk_*/空数组, 即回测剔除+1类)=置灰+「未入样本」badge(sig-poscap-notuni, 比当日已满更灰更弱化); 全关=回现状「全量视图」所有信号正常亮显不标注; band_hold持有中性保持不标; 空态横条文案改「今日无 AI 建议买入信号,仅风险/持有状态」并按过滤视图门控; 迟到的入宇宙卖出(8/14中证银行sell)AI警示+盘后补齐角标共存; AI降亏命中的信号仍走删除线AI降亏(不强加AI警示, 防双重矛盾); 历史日期复盘视图同 cellHtml 一处渲染(§23.3 举一反三全站只有本处); // a227->a228 = 首页8/14信号三修复(2026-08-14, app.js+style.css+purpose-notes+app/queries.py): P1-1 当日无入样宇宙买入信号空态灰条(sig-empty-universe); P1-2 「当日已满」补 _bt_in_universe 判(未入样买入类不再误标, 修 8/10 csi_931892/gz_399440 & 8/12 thsc_306380); P0-2 迟到信号「盘后补齐」角标(sig-late-badge, 字段 _bt_late 待 P0-1 后端注入) + 定稿文案对齐21:00补采(purpose-notes/app.js/queries.py finalized_note "20:36后定稿"→"21:00指数补采后定稿"); // a226->a227 = 修 SW 更新接管裸白(HIGH, 2026-08-14, 纯前端sw.js+index.html, §23.2三铁律):根因=点「更新新版」→新SW install个别核心失败被catch吞+无条件skipWaiting→activate删光全部旧缓存+clients.claim接管→reload时新壳缺app.min.js(从边缘失败/未拉)+旧缓存已删+CF抖动→净加载不全→全白空壳. 修=①install核心shell(app.min.js/common.min.js/index.html)必须全部预缓存成功才skipWaiting, 任一核心失败=install reject→SW redundant不激活, 旧SW留守继续服务; 非核心资源个别失败不阻塞(容错保留) ②activate接管前用cache.match二确认核心shell已就绪(未就绪不claim不删任何旧缓存, 让旧SW继续=network-first逐资源升级, 杜绝"清旧+新缺"裸崩) ③cacheFirst: App Shell缓存命中但响应损坏(非ok/200)回退网络拉新, 不拿坏缓存当数据; 网络也失败才回退缓存/error ④index.html「刷新」按钮: 点击前探活app.min.js可达, 新SW未就绪则提示"正在准备新版", 待核心壳确认可命中caches再reload, 已就绪才reload(不再无条件reload踩裸崩). 不加新告警/新机制, 保持现有SW策略(overview networkOnly返占位+前端守卫等)不变; app.js渲染守卫不动(那些是对的). // a225->a226 = P0回归紧急修复(首页全Failed to fetch, 2026-08-14, 纯前端sw.js): a225把overview失败从HTTP200占位改Response.error()(reject) -> fetchJSON走R2兜底, 而R2兜底URL( /data/overview.json )同命中overview分支再reject -> 首页依overview模块全Failed; 修=overview分支catch回滚返HTTP200 {error:offline}占位(不reject不Failed), 穿透防护由app.js `if(!r||!r.today)`守卫承担(仍保留, 空态+重试不裸崩); 尊重networkOnly不回退缓存防返昨日a_amount; // a224->a225 = P0首页崩溃修复「Cannot read properties of undefined (reading 'scores')」(2026-08-14, 前端app.js+sw.js, §23.2): 根因=overview 请求失败时 SW 返 HTTP200 的 {"error":"offline"} 占位, fetchJSON 只查 r.ok 穿透当正常数据, r 无 today 推进到 renderOverview r.today.scores 裸崩; 修=①renderOverview 开头加 `if(!r||!r.today)` 守卫(缺失则清缓存+渲染失败态+重试按钮+兜底轮询自愈,参照_refreshKpiMainValues L6461同模式) ②无 today 不写 _setCachedOverview(防 _overviewTTL 5min 缓存反复崩) ③SW offline 占位全改 Response.error()(不再返 HTTP200 error 占位, fetch 走 reject/R2兜底; overview/intraday-notifications/networkFirstJson 3处) ④L9651 r.today.scores / L9687 r.today.metrics 双保险 (r.today&&...)(§23.3同类全量扫描所有 .today. 访问点均已有外保护); // a223->a224 = 凯利回测页 2 个 UI 布局修复(2026-08-14, 纯前端lab.js+lab.css): ①全信号表「按年窗口增长」表格限高——不超强关联ETF(etf_strong)卡片高度, 超出内部滚动(_applySigKellyYearlyMaxHeight 测量强关联卡高度设按年表滚动容器 max-height, CSS 兜底440px); ②「AI仓位建议 · 历史回测数据」展开面板布局修正——max-width 860px(不撑满全屏)+max-height 80vh内部滚动+summary换行+行高收窄(仅 .lab-sigkelly-poscap-history, 不动 advice-outer 面板); // a222->a223 = 修复 etf_since_return 回归(F1, 后端queries.py) + 完整版信号文案放宽(W1, 前端app.js+后端queries.py): F1=_etf_close_cache 恢复 accum_nav IS NOT NULL 独立查询(原误用 close IS NOT NULL 致有close无accum_nav行进入->_today_close=None->etf_since_return整体None, 拆两条独立查询: accum_nav->_etf_close_cache, close->_etf_price_cache(etf_close), 非空率94.6%->96.9% PASS); W1=17:50-18:42 update_all 信号重算完成前数据仍A股版但_hm>=1750已判full, 文案放宽"17:50起陆续补齐(港股/欧股/国债),20:36后最终定稿"(不硬编码18:45阈值, 与docs/signal-finalize-time.md对齐), 后端finalized_note+前端banner同步(§22); // a221->a222 = 卖类信号行跳过「当日已满」badge(#30, 2026-08-14, 纯前端app.js): 卖类/持有中性信号(sell/sell_stop_loss/波段减仓 band_sell/波段持有 band_hold)不涉及"当日已满不能买"语义且不入AI建议, 原渲染误落else分支显示「当日已满」+被 sig-poscap-excluded 灰化, 修复为整块跳过分支(§23.3: 全站「当日已满」badge 渲染点仅 app.js cellHtml 一处); + §23.6 入样宇宙规则三处公示(#33, 2026-08-14, 前端app.js+lab.js+purpose-notes): 入样白名单 buy/buy_aux/buy_special/buy_backup, 入样依赖=board_etf_map key+track_score(_bt_in_universe), 排除类别=债类cgb_*/情绪s.*/全球商品利率g.*/港股行业hk_*/空数组ftse100·kospi, 自我ETF唯一例外=cgb_10y_etf, 首页AI建议1:1遵从回测入样判定(权威=config/universe_rules.yaml, §21公示同步); // a220->a221 = 首页信号「两段式固化」三态提示+当日实操说明(2026-08-14, 后端app/queries.py+前端app.js+style.css+purpose-notes): overview() 注入 signals_meta(version a-share-close/full/evening + finalized + coverage + generated_at + finalized_note + operable_window, 基于服务端真实时点判定, 不新增采集/launchd) + 每条信号补 close/etfs[]补 etf_close(复用 index_daily/etf_daily 已有价格); 前端首页信号区三态提示条(_signalFinalizeBannerHtml: 盘中预估⚠/A股已固化✅/完整版定稿✅, 由 signals_meta 驱动)+AI建议区「⏰已固化·可操作(盘后窗口)」标签(A股已固化时); 参考说明弹窗+hoverpop 补「⏰当日实操建议」段(15:03 A股定稿不再消失/15:05-15:30盘后固定价格窗口可按收盘价操作/当日可执行=AI建议1/2/3); §21公示同步(purpose-notes lab.sigkelly 补信号固化时点说明); §22 同消费 overview 展示位一致; // a219->a220 = 首页AI建议与凯利回测入样宇宙1:1对齐(#25, 2026-08-14, 后端app/queries.py+前端app.js+lab.js+purpose-notes): overview() 每条信号注入 _bt_in_universe(有跟踪ETF且带track_score=入样), 前端AI建议仅在此宇宙内选择+排除卖类信号(sell/sell_stop_loss)——首页AI建议选择口径与回测 _build_best_etf 入样判定100%一致; §21公示同步(purpose-notes+app.js tooltip+lab.js); a219->a220 = compliance版 band_hold 名词统一(2026-08-14, 纯前端i18n.js): band_hold 字典"持有"→"波段持有"(detail/legend 同步), _TS_COMPLIANCE_MAP 删["波段持有","持有"]映射(trade_sim 文本保留原词"波段持有"); band_sell 保持"波段调整"(减仓是完整版🛡️off专属, compliance 禁用); §22 全展示位(信号表格/详情弹窗/图例/trade_sim文本)一次改齐; // a218->a219 = 首页「推荐方法&参考说明」按钮 hoverpop 与父级原生 title 打架修复(2026-08-14, 纯前端app.js): help 按钮(.sig-kbtn-help-wrap)嵌在父容器 .sig-switch-poscap(长原生title)内, hover 时浏览器原生 title 冒泡 + 独立 hoverpop 重叠打架 → 给 help wrap/button 加 title=""(空 title 阻止祖先 title 冒泡, HTML 规范); 举一反三(§23.3): K 按钮评级 hoverpop(.lab-sigkelly-posrate)同嵌 title 容器、同型冲突 → 新增 _bindPoscapTitleSuppress 在 K 评级 pop 显示期(mouseenter)临时置空父容器 title、离开(mouseleave)恢复(K 原生 title 属性仍保留, 悬停标签文本仍显示); AI降亏开关(.sig-switch-ai)内 ⓘ tip 因 data-no-pop 已被 term-pop 抑制、无竞争弹层不冲突; 不动 lab.js/lab.css(凯利区刚合并上线); // a217->a218 = 信号凯利回测「降亏组合使用建议」面板重构为「全信号操作建议指南」(2026-08-14, 纯前端lab.js+lab.css+purpose-notes+README, 合并自 feat/kelly-advice-guide): ①标题两处统一改「全信号操作建议指南」; ②去序号+去「②分投资习惯」收起展开, 内部分节平铺(分投资习惯/总建议两节, .lab-sigkelly-advice-section-title); ③G行数据改可操作口径(P≤3d「先卖年轻」当前档, 峰持仓≤20倍本金, 不再披露原始329笔/146万无操作性数字; GIH on读真实__gihb1, off用报告参考b0, §22与ai长线对比表/卡片一致); ④格式错位修复: 投资习惯3列表格 table-layout:fixed+列宽+单元格换行(仅advice-body直子, 不影响G/H/I对比表); ⑤§21公示同步(purpose-notes)+README同步; // a217->a218 = 信号凯利回测首列 SPAN 独立换行(#firstcol, 2026-08-14, 纯CSS lab.css+style.css, 合并自 feat/kelly-firstcol-linebreak): 用户要求首列「AI长线·开 满仓不买@15万」「淘汰·无仓位限制·无法实操」等 SPAN 独立换行不再挤一行 —— .lab-sigkelly-modelbl display:inline→block / .lab-sigkelly-exec-badge 加 display:block+margin-top / .lab-sigkelly-gih-badge display:inline-block→block; 首列全部4展示位(三玩法披露表/主信号表/无数据行/G/H/I对比表)共用此三类 CSS 自动覆盖(§23.3), 纯样式不动 lab.js 渲染结构(§9); // a216->a217 = 首页信号「参考说明」按钮独立化(2026-08-14, 纯前端app.js+style.css): 按钮移出 K 评级 trigger 不再复用 .sig-kbtn 与 off 同款样式, 独立样式 .sig-kbtn-help(主色系描边+浅底), 文字改「推荐方法&参考说明」; 独立 hoverpop(_sigHelpPopHtml+_bindSigHelpPop, 不复用 K 评级表 _aiPoscapRatingPopHtml), 悬浮讲清短线A/F(固定10天/持有15天快进快出)+中长线G(指数卖出信号触发离场、无信号持有, 总建议主选)+引导点击弹完整说明弹窗跳转「信号凯利回测」, 内容口径与 rule-modal 弹窗一致(§22); // a215->a216 = 线上P0紧急修复 staleTxt is not defined(2026-08-14, 纯前端app.js): 上版a215的 staleTxt 在 if(ntStale) 块内 const 声明但块外 ntCard.innerHTML termTip 引用 → 块级作用域 ReferenceError 首页汪汪队卡片崩溃; 提升到函数作用域(let staleTxt="") + 块外 (staleTxt?"日") 兜底, 逻辑不变; // a214->a215 = 汪汪队「最新信号日期卡7/31」bug修复(2026-08-14, 前端app.js+style.css+后端app/collector/etf_national_team.py+gen_daily_brief.py, §23.2三铁律+§23.3举一反三): etf_signal 仅在信号触发时写行, 无触发MAX卡在7/31, 首页卡片"最近信号"误示旧日 → latest_signals_overview 加 data_date(MAX etf_daily, 每日健康)+signal_stale+signal_stale_td, 前端卡片标"⚠近N个交易日无信号触发(数据更新至MM-DD)"灰色stale样式, stale时不把旧信号日当"今日"高亮; AI预测gen_daily_brief.py 加新鲜度守卫(stale时注明确注明信号日vs数据日, 防把旧信号当今日呈现); §22一致性(卡片/专区按日期列表/通知去重/AI预测全同语义); // a213->a214 = AI预测命中容忍带口径 0.1%->0.5%(2026-08-14, 纯前端app.js公示文案+后端gen_daily_brief.py HIT_THRESHOLD, 历史命中按新口径重刷 0/3->2/3, §21公示+README同步); // a212->a213 = 信号凯利回测 lab.js 显示层优化(2026-08-14, 纯前端lab.js+lab.css+purpose-notes, 不动计算口径): ①「最大持仓/持仓中」金额<1万分支加 Math.round 修 3333.3333/6666.6666 显示bug(§23.3 举一反三: 交易记录弹窗 amount 列同步 Math.round, 消除 3,333.333 小数); ②按年窗口增长表新增第7列「峰值资金回撤」(_aggYearlyMap 每year加 peak_drawdown_pct=该年最大回撤金额÷峰值持仓×100, 与hoverpop/AI仓位K评级同口径只是按年, 参考A2011 etf_def=14.01%自测); ③峰值资金收益率/回撤列title+表下白话说明(小白可读: 回撤是过程最深一次从高点跌下的幅度, 收益率是最终净结果, 两把不同尺子勿直接比), 全周期回撤见AI仓位建议K按钮评级; §21公示同步(purpose-notes 按年表描述补峰值资金回撤列+白话口径); // a211->a212 = 信号凯利回测 3处UI优化(2026-08-14, 纯前端lab.js+lab.css+purpose-notes+README): ①费率默认档改ETF主流(etf_main, 万0.5最低0.1, 原ETF默认万3最低5为历史默认), 页面加载/重置/加载失败回退全按ETF主流口径渲染, 渲染数据随费率档联动重算(§22); ②按年窗口增长表上方新增「当前[模式]+[k档]+[降亏N标志]+[费率口径](+[G档])」来源条件归纳提示(_kellyYearlySourceHint 动态读当前勾选/费率/K/G档实时拼, 不写死; G模式额外补G三档13W/15W/20W); ③表格首列模式字母+描述合并为一行(.lab-sigkelly-modelbl display:inline, 消除描述独立一行拉高行高, AI长线/淘汰角标仍同格); §21公示同步(purpose-notes lab.sigkelly 费率默认改ETF主流+etf_def→etf_main)+README同步; // a210->a211 = 首页信号「参考说明」按钮+弹窗(2026-08-14, 纯前端app.js): AI仓位建议开关行「关off」后新增「参考说明」按钮(data-k=help), 点击弹 rule-modal 说明弹窗——短线A/F玩法(固定10天/持有15天)+中长线G玩法(指数卖出信号触发离场、无信号持有)+引导跳转「信号凯利回测」(lab #lab?sub=sigkelly 定位A/F/G模式数据); 文案口径与 lab.js _sigKellyAfgRealtimeHtml/purpose-notes lab.sigkelly 一致(§21/§22); 复用既有 rule-modal 弹窗机制不新造; // a209->a210 = AI建议编号与列表展示同人口修复(2026-08-14, 纯前端app.js): kept集改用 popItems(档位筛选后人口)+排除band_hold, 消除"可见列表只1条却标AI建议N跳号"(原用windowedItems全量算kept, 被默认档位藏掉的tier5信号仍占AI建议位→可见项编号跳号, 如20260804 K4 rank3被藏致10年国债ETF标AI建议4); 修复后kept⊆可见, 编号与展示一一对应不跳号; // a208->a209 = 按年窗口增长 A-G 模式下拉切换(2026-08-14, 纯前端lab.js+lab.css): ①按年窗口增长表支持下拉选择 A-G 任一模式独立查看各自的按年窗口增长(allYearlyByMode, 各模式独立聚合非混算), 默认G保持现网口径; ②allYearly 仍取G模式(总建议语义, 兼容); ③§21公示同步(desc文案改"各模式各自独立按年增长"); a207->a208 = G/H/I 三模式独立仓位策略 v2(2026-08-14, 纯前端lab.js+lab.css+style.css+purpose-notes+README): ①G/H/I 不再统一 FIFO 20万——G=P≤3d「先卖年轻仓」(手段P)+13/15/20三档自选(开关行内嵌档位切换 tds_gih_g_tier 默认13万, 切换全消费点联动), H=满仓不买@7万/I=满仓不买@15万(手段A, 无强平 b0=b1); ②新增内核 _kellyAihlineP3dCap(先卖≤3天年轻仓无年轻才FIFO)+_kellyAihlineHoldCap(满仓停买), _kellyAihlineApply 按 strategy.method 分发(B/P/A); ③对比表/tooltip/卡片角标/水印/三玩法/弹窗全按各模式当前策略动态化+策略short标签; ④§21公示同步+purpose-notes 更新; a206->a207 = 凯利降亏组合使用建议面板重构(2026-08-14, 纯前端lab.js+lab.css+purpose-notes+README): ①删除「4组合全开」折叠区(old fixed每笔1万口径过时)→标题去「4组合全开=可选」; ②总建议行G数字fixed错标改每日池口径(AI仓位建议K1主推 47.22%/+642,184, 按年2021 -23,500/2023 +60,645/2024 +225,894/2025 +151,405, 出处dailypool rerun §6) + 配套行「同口径可直接对比」矛盾句改口径差异说明; ③面板整体可收缩默认折叠(标题一行概览, open状态持久化state.labSigKellyAdviceOpen); ④G玩法三档标b0保守口径+口径说明去4组合全开残留; 布局复用现有advice/gmethod class样式美化; // a205->a206 = BC包 + 按年窗口口径归正(2026-08-14, 纯前端common.js+lab.js+app.js+purpose-notes+lab.css+README): ①B包 K评级佣金口径重算——静态快照 _AI_POSCAP_RATING 由比例法改费率重算扣最低佣金5元(每日池A模式 K1 86.60%/K2 67.61%/K3 66.24%/K4 63.17%, 消除12.67pt佣金低估§22, 与动态 _kellyApplyFeeRecompute 逐位一致); ②C包 默认K 3→1主推(_kellyDefaultFilters/_kellySharedPosCap/app.js _posCapK/重置/初始载入全链路, K按钮1342置顶+★主推高亮, tooltip/评级/对比/全信号/建议面板全同步); ③按年窗口口径归正: allYearly 仅累加 G 模式(原全9模式累加量级虚高, 对齐"总建议=遵守G模式卖出"语义, 表头标签标注G模式), 4组合全开静态按年表加口径标注; ④§21公示同步(purpose-notes.js)+README 同步; a204->a205 = 总建议板块融合 G 玩法完整交易方法(2026-08-14, 纯前端lab.js+lab.css): ②分投资习惯怎么用?总建议"②总建议"分节内新增 .lab-sigkelly-gmethod 教学区 G玩法三层流程: ①P≤3d"先卖年轻仓"最优仓位管理(白话说+12万持仓举例, 保老仓21-100天利润引擎砍新仓)②三档自选13万155.78%(净+202,508)/15万147.34%(净+221,016)/20万131.25%(净+262,509, 全部≤20倍本金可操作)③可信度=15起始年全超FIFO(均值98.9vs62.0)+随机30点0/30负+b0/b1区间窄(4-24pp)可信; with G分层流程; 与A/F维持默认7键并列清晰; lab.css加靛青左边框教学callout; a203->a204 = 凯利降亏过滤使用建议重写(2026-08-14, 纯前端lab.js+lab.css+purpose-notes): ①_fadeFlagGroups 31键 tip 改每日池口径白话+剔除fixed旧数字、"净增收+XX万"主口径清除, 加 advice(白话1句+ratio可见文本)/tip(ⓘ弹层完整detail)结构; ②4组合宏tip瘦身(去重复"可叠加OR幂等无害"+过期数字); ③_comboAdviceHtml 面板6.33pp改"与默认差异0.3-0.7pt"+加G模式分裂建议(A/F维持/A-F去g15等); ④布局重写=顶部"怎么用"三行汇总+默认推荐7键高亮独立块+非默认收"更多开关"折叠区, 星标+advice色块联动warn(绿推荐/黄监控/红慎用); ⑤purpose-notes 降亏段同步每日池口径+剔除过时口径; a202->a203 = 凯利AI报告区移页面尾部作历史留存(2026-08-14, 纯前端lab.js+lab.css): 用户定"AI报告版本已过时移页尾作历史留存"——整个 lab-sigkelly-ai-wrap(切换条+3AI新版[3ai-comparison+comprehensive+deepseek+claude-v4]+双AI历史[comparison+comprehensive+deepseek] 全部report块)从 wrapper 中部移到 host 之后页面最底, 加归档标注 .lab-sigkelly-ai-archive-title"📦历史AI报告存档(结论已过时·仅供回溯)"+灰虚边框弱化; 保留 3AI/双AI 切换/localStorage 记忆(lab_sigkelly_ai_mode)/KELLY_REVIEW_NOTES 内容原样; 全部版本无一遗漏俱移尾部; // a201->a202 = #25 bug修复(2026-08-14, 纯前端lab.js+lab.css+style.css): "ai长线开+淘汰文字看不清字"样式修复——①淘汰删除线行文字 var(--text-4)最淡灰改 var(--text-2)深灰可读+整行 opacity 0.55→0.85(不被压淡, 含红角标保持亮色); ②删 .lab-sigkelly-exec-badge 幽灵变量 var(--gih-el,未定义)用深红 #c62828+白字11px加粗+内白描边(原10px红底白字对比不足); ③水印 .lab-sigkelly-wm-cmp-noop 不再 opacity:0.5 整行压淡(会吞掉角标), 改只灰化文字色 var(--text-3), noop-badge 9px→10px 深红加粗; ④"AI长线·开" .lab-sigkelly-gih-badge 去 .lab-sigkelly-modelbl(display:block 致独占一行挤位), 独立 inline-block 11px加粗+紫底白字+白描边, dark/redgold 提亮紫#8b3ff0; ⑤GIH on cap 后记录不误标淘汰(已自测:GIH on G/H/I 行仅 AI长线·开 无删除线, GIH off 才标淘汰·无操作性) ; a200->a201 = #25 A包(2026-08-14, 纯前端lab.js+purpose-notes+lab.css): ①TOP1推荐算法修正——先可操作性(峰持仓≤20万)过滤再按收益率(return_pct_max_holding)排序, 不再按净盈亏(去F大净利压Abug, 新默认top1=A), GIH on读__gihb1; ②需求②GIH off不可操作(G/H/I未套20万硬控原始峰持仓>20倍)记录标"淘汰·无操作性"(删除线+角标+hoverpop+弹窗理由); ③需求D K档OFF(无仓位限制每笔1万全买峰持仓疯长)记录标"淘汰·无仓位限制·无法实操"; 统一_kellyOpElimination判据(峰持仓≤20万), 卡片行/全信号表/三玩法表/水印/弹窗同步(§23.3), purpose-notes §21公示同步, README同步; a199->a200 = docs路径整理(2026-08-14): docs/kelly-* 移入 docs/kelly/{mining,combo,position,backtest-ai,toggle,analysis}/, kelly-review-notes/lab/purpose-notes 内嵌文档链接路径同步, 仅注释/字符串变更无功能改动; a199 = #49 issue49 修复2用户反馈  // a198->a199 = #49 issue49 修复2用户反馈(2026-08-14, 纯前端lab.js): F1交互-对比表展开/收起独立于开关(_gihCompareOpen用户态, 开关change不再强制收起, 重渲染保开合); F2核心-开关无效修复(顶层缓存签名cacheKey拼入gih开关态, 7829, 否则短路径命中旧result无__gihb1→卡片恒显原始值); a198 = #49 ai长线仓位管理reviewer审查修复(2026-08-14, 纯前端): F1 _kellyMaxConcurrentCapital/_kellyMaxConcurrent 改【先减后加】(与仿真内核/后端_peak_capital同序, cap后峰值精确回20万/200.46%对齐报告§7.2, A-F基线从高估错误值收敛到后端口径如G 137万→136万, §22+§21); F2 水印/卡间对比过滤 mode+"__gihb0/b1/peak"伪模式键(防封面均值稀释排序错乱); F3 弹窗+三玩法表GIH ON加"未套硬控原始口径"诚实标注+CSS(gih-modal-note); a196->a197 = #49 ai长线模式(G/H/I)仓位管理(2026-08-14): 凯利回测区新增开关(长线族群总入口, 模式→策略映射 G/H/I v1 统一 fifo20w), G/H/I 套持仓≤20万+FIFO强制平最久持仓硬控, ON后卡片套乐观b1口径值+AI长线·开角标, 新增G/H/I对比表(关/开b0/开b1, 报告§7.2 K1参考口径), 前端FIFO仿真内核与报告逐位对齐§21, purpose-notes/README同步, style.css加角标徽标类; a195->a196 = #48 每日池口径重算页面(2026-08-14): _kellyFadeFlagGroups 31键 ratio 换每日池 ALL9 K1 + 组内重排 + tips 注明口径; _pcRating/_AI_POSCAP_RATING/首页 tooltip/purpose-notes/README A模式 K1-4 改每日池(86.60/74.93/78.91/79.96); common.js 回退+口径描述同步每日池; a194->a195 = 凯利回测金额口径恢复"每日资金池等分+top-K"(2026-08-13): 当日保留前K基笔每笔=10000/当日保留数, K档最大持仓恒定(~11万), 撤销fixed口径下K=3 33万异常; a193->a194 = AI降亏过滤详情默认收起(31个单标志toggle默认收起, 点按钮才展开); a192->a193 = 凯利降亏过滤 toggle 名称精简+去版本标识(#V4/A45/A5/J1/J2/R7/mid评级统一为白话名) + fix: _renderSigKellyCard 误删 periods 声明回归(#1); a191->a192 = 信号凯利回测页UI增强: 卡片置顶(全信号+16子域卡 localstorage 持久化, 已置顶区集中显示) + 默认推荐框内文字醒目(灰改金字加粗) + 默认推荐badge文案精简为"推荐"; a190->a191 = 首页实操验证与凯利回测 1:1 对齐(#60 方案A): 首页信号链路接入 #58 ETF 冻结表(queries.py 命中冻结标 _bk_top), 前端 _topEtfByScore 改纯 track_score 降序(去 stable_top1 滞回 + track_n>=90 启发), 首页 AI建议/标的 = 回测标的; a189->a190 = #54 hoverpop动态化(bug1总开关联动扩7键+badge降级+重置为AI默认推荐按钮) + 前端动态重算管线; a188->a189 = 凯利回测区AI仓位建议布局调整(删除第一行纯文字标题"AI仓位建议"去重 + AI降亏过滤总开关/详情按钮并入第一行跟在关OFF按钮后); a187->a188 = K档补文案(首页AI仓位建议K档 title 档位语义诚实标注, 默认K=3稳健档非收益率最优) + AI建议编号修复(序号改质量序=当日跟踪分降序第N, 不随K档跳变) 两分支合并(#48#49); a186->a187=AI建议编号改质量序; a185->a186=凯利AI降亏过滤区融合(#39/#45)+§22 K档口径同步; a184->a185=皮肤弹窗样式修复; 基底=a177

const CACHE_NAME = 'tdsignal-' + CACHE_VERSION;
// 分两类:
//   CORE_SHELL_URLS   —— 页面能渲染的"绝对必要"核心壳(缺其一 reload 即全白空壳)。这些必须全部预缓存成功才能激活接管。
//   PRECACHE_URLS     —— 含 CORE + 非关键资源(图标/字体/统计 JS 等)。非关键失败不阻塞预缓存,但 CORE 失败绝不允许激活。
const CORE_SHELL_URLS = [
  './',                 // 导航请求回退目标
  './index.html',       // HTML 壳
  './app.min.js',       // 首屏渲染 JS(缺=全白)
  './common.min.js'     // app 依赖的公共 JS(缺=渲染异常)
];

// 核心 shell 的 pathname 归一形态('./' → '/', './x' → '/x'), 供 fetch 路由判定核心资源
const CORE_SHELL_PATHNAMES = CORE_SHELL_URLS.map((u) =>
  u === './' ? '/' : '/' + u.replace(/^\.\//, '')
);

const PRECACHE_URLS = CORE_SHELL_URLS.concat([
  './style.min.css',
  './purpose-notes.min.js',
  './kelly-review-notes.min.js',
  './qr.js',
  './manifest.json',
  './favicon.svg',
  './favicon.ico',
  './icon-192.png',
  './icon-512.png',
  './apple-touch-icon.png'
]);

// App Shell 静态资源的文件扩展名(CacheFirst 适用)
const APP_SHELL_ASSET_PATTERN = /\.(?:css|js|svg|png|ico|woff2?|ttf|woff)$/i;

// ============== install: 预缓存 App Shell + 核心就绪才 skipWaiting ==============
// P0(2026-08-14 a227): 修复「点更新新版→切换 SW→reload→全白」裸崩。
// 旧缺陷: Promise.all 内 cache.add().catch() 吞掉个别失败(app.min.js 拉失败不阻塞),
//          无论是否就绪都立即 skipWaiting 激活;activate 又无条件删光旧缓存+claim,
//          reload 瞬间新壳缺 app.min.js+旧缓存已删+网络抖动 → 净加载不全 → 全白空壳。
// 修复: ①CORE_SHELL_URLS(app.min.js/common.min.js/index.html)必须全部预缓存成功才推进
//          install 完成(self.skipWaiting only in ready case);任一核心失败 = install 以
//          reject 结束 → SW 进入 redundant 不激活,浏览器保留旧 SW 继续服务。
//        ②非关键资源(图标等)个别失败不阻塞整体预缓存(容错保留)。
self.addEventListener('install', (event) => {
  // 核心壳是否全部预缓存成功(供 activate 二次确认兜底)
  let _coreShellReady = false;
  self.__coreShellReady = false;

  const coreReady = caches.open(CACHE_NAME).then((cache) =>
    // 核心 shell: 严格全成功,任一失败 → reject → install 不激活
    Promise.all(CORE_SHELL_URLS.map((url) => cache.add(url))).then(() => true)
      .catch((err) => {
        console.error('[sw] CORE shell precache FAILED, 不激活(保留旧SW兜底):', err && err.message);
        return false;
      })
  );

  event.waitUntil(
    coreReady.then((ok) => {
      self.__coreShellReady = !!ok;
      if (!ok) {
        // 核心未就绪 → 不 skipWaiting;但尽量预缓存非核心(失败忽略,redundant 后清理)
        return caches.open(CACHE_NAME).then((cache) =>
          Promise.all(
            PRECACHE_URLS.filter((u) => CORE_SHELL_URLS.indexOf(u) === -1).map((url) =>
              cache.add(url).catch((err) => console.warn('[sw] precache non-core miss:', url, err.message))
            )
          )
        ).then(() => Promise.reject(new Error('core shell not ready')));
      }
      // 核心就绪 → 预缓存其余非关键资源(失败不阻塞)
      return caches.open(CACHE_NAME).then((cache) =>
        Promise.all(
          PRECACHE_URLS.filter((u) => CORE_SHELL_URLS.indexOf(u) === -1).map((url) =>
            cache.add(url).catch((err) => console.warn('[sw] precache non-core miss:', url, err.message))
          )
        )
      ).then(() => self.skipWaiting());
    })
  );
});

// ============== activate: 核心壳就绪才接管,未就绪不 claim 不删旧缓存 ==============
// P0(2026-08-14 a227): 修复「点更新新版→切换 SW→reload→全白」裸崩(bug 根因之二)。
// 旧缺陷: activate 无条件删光 k!==CACHE_NAME 全部旧缓存 + clients.claim 立即接管当前页,
//         此时 install 的新壳缓存可能缺 app.min.js(拉取失败被吞) → reload 后旧缓存已删、
//         新缓存不全、网络抖动 → 净加载不全 → 全白空壳。
// 修复: ①接管前用 caches.match 二次确认当前 CACHE_NAME 缓存里核心 shell 文件已就绪
//        (install 的 __coreShellReady 兜底 + activate 实况复验)。
//        ②核心未就绪 → 不 claim(不接管当前页)、不清任何旧缓存 → 旧 SW 继续服务,
//          网络/缓存仍可逐资源加载页面(network-first 逐资源升级),绝不"清旧+新缺"裸崩。
//        ③仅当核心就绪才清理旧版缓存(只清旧版本 cache,不清新版本)并 claim 接管。
self.addEventListener('activate', (event) => {
  const isCoreShellReady = () => {
    if (self.__coreShellReady) return Promise.resolve(true);
    // 兜底复验: 逐个确认核心文件已在新版缓存可命中
    return caches.open(CACHE_NAME).then((cache) =>
      Promise.all(CORE_SHELL_URLS.map((u) => cache.match(u).then((r) => !!r && r.ok)))
        .then((results) => results.every(Boolean))
    ).catch(() => false);
  };

  event.waitUntil(
    isCoreShellReady().then((ready) => {
      if (!ready) {
        console.warn('[sw] activate: 核心 shell 未就绪,不接管不删旧缓存,旧 SW 继续服务');
        return Promise.resolve();
      }
      // 核心就绪 → 清旧版本缓存(仅非当前版本)+ claim 接管 + 通知客户端刷新
      return caches.keys().then((keys) =>
        Promise.all(
          keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
        )
      ).then(() => self.clients.claim())
        .then(() => self.clients.matchAll({ type: 'window', includeUncontrolled: true }))
        .then((clients) => {
          clients.forEach((client) => {
            client.postMessage({ type: 'SW_UPDATED', version: CACHE_VERSION });
          });
        });
    })
  );
});

// ============== fetch: 按资源类型路由 ==============
self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // 4) 跨域请求不拦截 (百度统计 hm.baidu / 百度站长 zz.bdstatic / echarts CDN 等)
  //    直接走浏览器默认网络栈,不缓存
  if (url.origin !== self.location.origin) return;

  // 3) overview.json: networkOnly (盘中实时数据强制网络优先,不让SW缓存兜底)
  //    根因③修复: 旧版SW缓存兜底致用户看到昨日overview(a_amount=昨日全天值)而非今日实时值。
  //    改 networkOnly: 网络成功返最新overview,失败返 offline 占位(不回退缓存,避免盘中网络
  //    抖动时返旧缓存致误判)。fetchJSON 已加 ?_=Date.now() cache-busting + no-store。
  //    仍写入缓存(cache.put)供离线页重载兜底,但 fetch 时不读取(网络优先无回退)。
  if (url.pathname.endsWith('/overview.json')) {
    event.respondWith(
      fetch(req, { cache: 'no-store' })
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, copy)).catch(() => {});
          return res;
        })
        // P0(2026-08-14 a225) 回归修复(a225): a225 把失败从 HTTP200 {"error":"offline"} 占位
        // 改为 Response.error()(fetch reject)。后果: fetchJSON catch 走 R2 兜底, 而 R2 兜底 URL
        // (主站 ss.fx8.store/data/overview.json) 同样以 /overview.json 结尾 -> 命中本 overview 分支
        // 再次 Response.error() reject -> 首页所有依赖 overview 的模块「全是 Failed to fetch」。
        // 修复: 回滚为返 HTTP200 的 {"error":"offline"} 占位(fetch 不 reject, 不走 R2 兜底死亡链路,
        // 不 Failed)。穿透防护由 app.js renderOverview 的 `if(!r||!r.today)` 守卫(仍保留)承担:
        // 识别 200 占位(无 today) -> 清缓存+渲染失败空态+重试按钮+兜底轮询自愈, 不裸崩不 Failed。
        // 尊重 overview networkOnly 原始设计(不回退缓存, 防返昨日 a_amount 误判)。
        .catch(() => new Response('{"error":"offline"}', { headers: { 'Content-Type': 'application/json' } }))
    );
    return;
  }
  //    intraday_snapshot.json + notifications.json: NetworkFirst (盘中实时性优先,离线回退缓存)
  //    notifications.json 走 NetworkFirst（根因③修复）：原走 SWR 3min 缓存致前端读旧 notifications.json，
  //    真实信号触发后即使后端更新了前端也拿旧缓存不弹通知。改 NetworkFirst 每次走网络拿最新。
  //    overview.json 已拆出走 networkOnly（上方），此处仅处理 intraday_snapshot + notifications。
  //    fetch 加 cache:'no-store'（根因①修复）：避免命中浏览器 HTTP/CF 缓存拉旧数据。
  if (url.pathname.endsWith('/intraday_snapshot.json') || url.pathname.endsWith('/notifications.json')) {
    event.respondWith(
      fetch(req, { cache: 'no-store' })
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(req).then((cached) => cached || Response.error()))
    );
    return;
  }

  // 2) 其他数据 JSON (非 intraday): network-first (正确性优先, 失败回退缓存)
  //    2026-08-02 修复: 原走 SWR 3min 先返旧缓存后台拉新版, 低频数据(季频 public_fund_*/etf_score_list)
  //    更新后用户仍可能拿到旧缓存(SWR 后台 fetch 也可能命中 CF edge 旧版)。改 network-first 每次走网络拿最新,
  //    离线/网络失败才回退缓存。牺牲毫秒级延迟换数据正确性(数据更新第一时间反映)。
  if (url.pathname.startsWith('/data/') || url.pathname.endsWith('.json')) {
    event.respondWith(networkFirstJson(req));
    return;
  }

  // 1) App Shell 静态资源 (CSS/JS/vendor/图标): CacheFirst
  //    导航请求 (HTML) 也归入 CacheFirst (App Shell 模型);新版靠 CACHE_VERSION bump + 提示刷新
  if (req.mode === 'navigate' || APP_SHELL_ASSET_PATTERN.test(url.pathname)) {
    event.respondWith(cacheFirst(req));
    return;
  }

  // 其他同源 GET 请求: 默认走网络,失败回退缓存(兜底)
  event.respondWith(
    fetch(req, { cache: 'no-store' }).catch(() => caches.match(req).then((cached) => cached || Response.error()))
  );
});

// ============== CacheFirst: 缓存优先,损坏回退网络;无缓存才走网络 ==============
// P0(2026-08-14 a227): App Shell 资源缓存命中但响应损坏(非 ok / 错误占位)时,
//   不能把坏缓存当数据返给页面(会致 app.min.js 等未执行 → 全白)。回退网络拉新的;
//   网络也失败则回退缓存(有总比没强)或 error。
function cacheFirst(req) {
  return caches.match(req).then((cached) => {
    if (cached && cached.ok && cached.status === 200) {
      return cached;
    }
    // 缓存命中但损坏 / 无缓存 → 走网络拉新
    const url = new URL(req.url);
    const isCore = CORE_SHELL_PATHNAMES.indexOf(url.pathname) !== -1;
    return fetch(req, { cache: 'no-store' }).then((res) => {
      if (res && res.status === 200) {
        const copy = res.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(req, copy)).catch(() => {});
        return res;
      }
      // 网络也非 200 → 若核心 shell 则有损坏缓存也兜底返回(避免直接裸崩;前端守卫二次容错)
      if (isCore && cached) return cached;
      return res || Response.error();
    }).catch(() => {
      return cached || Response.error();
    });
  });
}

// ============== networkFirstJson: 优先网络拿最新, 失败回退缓存(离线兜底) ==============
// 用于 /data/ JSON: 低频数据(季频/日频)正确性优先, 不返回旧缓存。
// fetch 加 cache:'no-store' 避免命中浏览器 HTTP/CF 缓存拉旧数据(与 intraday/overview 同模式)。
// 成功写入缓存供离线兜底; 失败回退缓存, 缓存也无则返 offline 占位。
function networkFirstJson(req) {
  return fetch(req, { cache: 'no-store' })
    .then((res) => {
      if (res && res.status === 200) {
        const copy = res.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(req, copy)).catch(() => {});
      }
      return res;
    })
    .catch(() => caches.match(req).then((cached) => cached || Response.error()));
}

// ============== message: 接收客户端消息 ==============
self.addEventListener('message', (event) => {
  // 客户端主动触发 skipWaiting (用户点击"立即刷新"按钮)
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
  // SHOW_NOTIFICATION: 客户端委托 SW 弹通知（Mac Chrome 下 SW showNotification 点击比页面 new Notification 可靠：
  // 页面失焦时 new Notification().onclick 链路丢失 -> 点击无响应；SW registration.showNotification + notificationclick 稳定）
  if (event.data && event.data.type === 'SHOW_NOTIFICATION') {
    const { title, body, tag, data, failClearKeys } = event.data.payload || {};
    console.log('[sw] 收到SHOW_NOTIFICATION', title, '| tag=', tag);
    event.waitUntil(
      self.registration.showNotification(title || '', {
        body: body || '', tag: tag || undefined,
        icon: '/favicon.svg', badge: '/favicon.svg',
        requireInteraction: false, data: data || {},
      }).then(() => {
        console.log('[sw] showNotification 成功', title);
      }).catch((err) => {
        console.warn('[sw] showNotification 失败', err?.message || err, '| title=', title);
        // 回传 NOTIFY_FAILED 到所有 client: 清除已弹标记+时间窗,下次轮询重试(防死锁漏通知)
        const keys = Array.isArray(failClearKeys) ? failClearKeys : [];
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
          clientList.forEach(c => c.postMessage({ type: 'NOTIFY_FAILED', tag, failClearKeys: keys }));
        });
      })
    );
  }
});

// ============== notificationclick: 通知点击 -> 聚焦已有 tab + postMessage 触发页面 UI 反馈 ==============
self.addEventListener('notificationclick', (event) => {
  console.log('[sw] notificationclick 触发', '| data=', JSON.stringify(event.notification.data));
  event.notification.close();
  const notifData = event.notification.data || {};
  const msgType = notifData.msgType || 'NOTIFY_CLICK';
  const payload = notifData.payload || {};
  const hash = notifData.hash || '';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      console.log('[sw] matchAll 找到', clientList.length, '个client');
      let target = null;
      for (const c of clientList) {
        if (c.url.startsWith(self.location.origin)) {
          target = c;
          if (hash && c.url.includes(hash)) break;
        }
      }
      if (target) {
        console.log('[sw] focus+postMessage target', target.url);
        return target.focus().then(() => target.postMessage({ type: msgType, payload, hash }));
      }
      console.log('[sw] 无匹配client，openWindow', hash || '/');
      const openUrl = hash ? self.location.origin + '/' + hash : self.location.origin + '/';
      return self.clients.openWindow(openUrl);
    })
  );
});
