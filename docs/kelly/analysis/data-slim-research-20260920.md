# signal_kelly_trades 数据瘦身方案调研(L42 / codex 外审结论2)

日期:2026-09-20 | 角色:researcher | 状态:只读调研(未改码未碰线上)
目标:预聚合摘要 + 明细按需/范围 API,把 ~100MB 满载解码压到 ~1/10,不砍「分片失败回退全量」兜底语义、数值口径零改动。
测试基准:current baseline v1.1.7(权威见 memory test-baseline-v112-anchor);本调研不涉及重算口径,只做数据形态分析与瘦身设计。

## 一、数据形态现状(全部实测,9-13 05:10 产物)

| 产物 | 体积 | 作用 |
|---|---|---|
| signal_kelly_trades.json | 75 MB | 全量兜底(首页 sim 弹窗 _simLoadFull) |
| signal_kelly_trades.json.gz | 12 MB | 全量压缩版(R2 传输) |
| signal_kelly_trades_sdc.json(+.gz) | 75 MB + 12 MB | 当日收盘对比档(口径切换候选,结构与主档同构) |
| signal_kelly_trades_parts/ | 177 MB / 382 files | 分片目录 |
| ├ t2011..t2026.json(17 含 recent) | 81 MB | 年片+recent,**主消费路径**(app.js sim 弹窗 + lab.js 凯利页) |
| ├ lab_*_p{N}.json(364 files) | 78.5 MB | 未被 lab.js/app.js 引用,little 疑似冗余待确认 |
| signal_kelly_trades_sdc_parts/ | 159.7 MB / 381 files | 同上(口径双套) |

两套(主档+sdc)合计 ≈ 500 MB 本地静态存储;传输侧最坏路径=提交全史时拉满 17 片 81 MB(解码后 ~100MB)。

### 数据结构(核心事实)
- 顶层:{generated_at, buy_amount(10000), period_cutoffs, fields, quadrants}
- fields = 27 列名 list;quadrants = 16 子域(qk)× 10 模式(A~J),每条记录 = 27 值平行数组
- 16 qk = rating_high/mid/low(3)+ etf_strong/related/approx/has_track(4)+ sig_main/aux/special/backup(4)+ mkt_a/hk/global/industry/concept(5)
- **304,320 条记录(16qk×10mode×~1902)**,按前端基笔键去重后每模式 **7,608 基笔** → **副本膨胀 40 倍**
- 每条基笔恒出现在 **恰好 4 个 qk**(rating/etf/sig/mkt 各 1,16qk=3/4/4/5 选 1)→ 前端 _simBuildModePool 据此聚合 _mktD/_etfD/_ratD 维度

### 基笔去重键(前端 _simBaseKey,app.js L3573)
`signal_date|index_id|signal|buy_date|etf_code`(含 signal;跨 qk 45 条 signal 差异笔因 key 含 signal 天然拆分为不同基笔,与前端口径一致,零冲突)

## 二、字段全集与分级(27 列)

| # | 字段 | 分级 | 用途证据(前端消费点) |
|---|---|---|---|
| 0 | signal_date | 列表必须 | 基笔 key、K 分组(app.js L4439)、日期切片 L4497、按年聚合、s06 per-date 过滤 L4398 |
| 1 | index_id | 列表必须 | 基笔 key(去重身份) |
| 2 | signal | 列表必须 | 基笔 key、K 排序 L4452、过滤谓词(_simPassesFade L3451 等)、展示 _simSigTypeLabel |
| 3 | buy_date | 列表必须 | 基笔 key、K 排序 L4454、月/星期过滤、观察期倒计时 |
| 4 | sell_date | 详情/重算必须 | 卖出侧随 mode 变、观察期倒计时 _simBuildTradeCal、表格展示 |
| 5 | etf_code | 列表必须 | 基笔 key、G/H/I nav 目标集 _simCollectNavCodes L4477 |
| 6 | etf_name | 列表必须 | 表格展示(中文名) |
| 7 | track_tier | 过滤必须 | etf-light 档位展示(L4592)、X1 新键判定 _ctx20.track_tier |
| 8 | track_score | 过滤必须 | K 排序主键 DESC L4448、etf-light tooltip、新键上下文 ts |
| 9 | match_method | 列表必须 | etf-light 来源展示 _simEtfSrcLabel |
| 10 | track_low_confidence | 列表必须 | etf-light 低置信标注 |
| 11 | buy_price | 重算必须 | 费后重算(买入成本)、买价分桶过滤 _simBuypriceBin L3560 |
| 12 | sell_price | 重算必须 | 费后重算(卖出价)、表格展示 |
| 13 | shares | 重算必须 | 费后盈亏份数 |
| 14 | profit | 重算必须 | 表格展示(费后重算覆盖其值) |
| 15 | return_pct | 重算必须 | 表格展示 |
| 16 | hold_days | 详情必须 | 观察期倒计时(计划卖出=买入后第 hold_days 交易日) |
| 17 | sell_reason | 列表必须 | 卖出原因展示/统计 |
| 18 | current_price | 重算必须 | 未卖笔现价计浮盈亏(持仓) |
| 19 | real_buy_price | 重算必须 | 费后重算真实买入价(#90 口径) |
| 20 | real_buy_date | 重算必须 | 真实买入日期(买点标签) |
| 21 | real_current_price | 重算必须 | G/H/I 真实净值路径 |
| 22 | market_state | 过滤必须 | marketTiming 键(L3453)、legacyMa60Special |
| 23 | market_tier | 过滤必须 | bullAuxBackupStop、excludeSpecialBear、新键 tier 上下文 |
| 24 | market_tier_all | 过滤必须 | declinePhaseSpecial |
| 25 | market_tier_cyb | 过滤必须 | excludeSpecialBearCyb |
| 26 | rating | 列表必须 | 过滤 excludeRatingLow、K 排序、s06p1 剔 high、展示 |
| - | _mktD/_etfD/_ratD | 过滤必须(前端聚合) | 20 新键 + v3/v4/r3/jan/k2 谓词依赖;构建期可由 qk 归属直接落字段,前端不再现扫 |

**结论:27 字段全部保留逐笔,无一列可仅靠预聚合替代**——过滤(13+ 键)、费后重算(5 参费率用户可调)、K 档、s06 动态全部在前端逐笔执行,任何字段缺失即断粮。

## 三、瘦身核心方案:基笔唯一化(消除 40 倍膨胀)

### 数据实锤
- 每模式基笔集 A~J **完全相同**(交集 7599/7599,零独有,按前端 key=7608)
- 同一基笔跨 qk 副本:30432 记录中 22788 重复条**逐字段全同**,45 条 signal 差异 → 前端 key 天然拆分,不影响口径
- **跨 mode 差异字段(实测 A vs G)**:sell_date/sell_price/profit/return_pct/hold_days/sell_reason + 部分 current_price/real_current_price——**卖出侧 8 字段随 mode 变,买入侧 19 字段跨 mode 完全共享**

### 新结构(三表)
1. **基笔主表**:7608 行 × 19 共享字段(买入侧+标识)+ 每行 4 个 qk 归属(枚举码或 4×2 字节)
2. **mode 卖出变体表**:7608 × 10 = 76,080 行 × 8 卖出侧字段
3. (可选)卖方按年分片 = 主表按 signal 年切 + 对应变体行

### 体积估算(实证)
- 现状:单套 75 MB(全量)/ 81 MB(年片全史);膨胀后 304,320 行 × ~260B/行
- 唯一化后:76,080 行(含 mode 变体)× ~200B/行 ≈ **15 MB 原始 JSON**;.gz 预计 ~3-4MB
- 若再列式 + 字典编码(etf_code~50 值/signal 8 值/rating 3 值/track_tier 5 值,数值列 float32):≈ **3-5 MB 原始**
- 结论:**~1/20 ~ 1/25 传输量(比估的 1/10 更好),兜底也从 75MB 降为 ~3-4MB**

### 兜底新形态(d)
- 现状:年片失败 → _simLoadFull() 拉 75MB(L3767/L8771)
- 新形态:基笔唯一化后「全量」仅 ~4MB(= 现在 recent 热区量级),**兜底语义保留**:分片失败 → 拉唯一化全量;不再存在 75MB 长拉
- 全量能摘:能,摘成「唯一化全量」;不能摘干净(白屏事故 §24 教训),必须留一个低成本全量兜底

## 四、预聚合摘要设计(c)

### 已有基础(不新造,§3.2b 建模四问②复用)
- signal_kelly_backtest.json(501KB)已含按年×象限×mode 统计(n/win_rate/pl_ratio/kelly_f/half_kelly/total_profit/total_return_pct/avg_hold_days 等,实测 periods.all.G 结构)——凯利页概览已在用
- **但该统计是无过滤、无费后口径**,与弹窗「当前过滤+费率+模式」实时概览口径不同 → 弹窗概览**不能**直接复用

### 结论:预聚合只做「固定默认参数路径」
- 可变参数组合(13+ 过滤键× 费率 6+ 档 × K 档 × 10 模式)全预聚合 = 组合爆炸,不做(建模四问①不必要)
- 弹窗概览(总数/盈亏/收益率/胜率)在基笔唯一化后(~4MB)仍由前端逐笔重算,口径逐位不变(§22/§5.4)
- 可选的增量:构建期预聚合「每模式×每年」未过滤基线统计(与 backtest.json 同公式扩展)——仅用于概览区间参考,不作主展示;实现时与前端重算逐位对账(§5.4⑦ 同构对账铁律)

## 五、范围 API / 分片形态(d)

- 现状已按年切(tYYYY)+ recent 热区,主链路 OK
- 唯一化后年片 shrunk ~4 倍(17.7MB → ~4.4MB 原始 / ~1MB gz),recent 2.7MB → ~0.7MB;热区秒开、年片增量更小
- lab_ 前缀 364 files/套(78.5MB)未被 lab.js/app.js 消费 → 确认无消费方后可删(省 157MB×? 需再查全站引用)
- 业界按需/范围机制佐证:HTTP Range Requests(MDN),ClickHouse 物化视图(预聚合模式),ClickHouse TTL(数据分层)
  - https://developer.mozilla.org/en-US/docs/Web/HTTP/Range_requests(已验证可达)
  - https://clickhouse.com/docs/en/materialized-view(已验证可达)
  - https://clickhouse.com/docs/en/guides/developer/ttl(已验证可达)

## 六、分步实施建议

| 步 | 内容 | 可独立上线 | 前端改动 |
|---|---|---|---|
| 1 | 生成端新增「主表+变体+qk归属」三表产物(signal_kelly_backtest.py L1397 _classify_buy_rows / L1493 _build_outputs / L1722 分片处),旧产物并存 | 是(纯新增,不动消费方) | 无 |
| 2 | 前端读取新结构(_simParseTrades 适配:`quadrants[qk][mode]` 由主表+变体+归属现组装;或改 _simBuildModePool 直接吃三表)——删除前端跨 qk 去重(40 倍扫描) | 否(需回归) | app.js _simParseTrades/_simBuildModePool + lab.js 等价点 |
| 3 | 兜底切换:失败回退改拉唯一化全量(~4MB),删 75MB 全量 + .gz 双套 | 否(与 2 一起) | _simLoadFull/_labKellyLoadFull 的 URL |
| 4 | 确认 lab_ 364 files 无消费方后删除 | 是 | 无 |
| 5 | (可选)预聚合摘要层扩展 backtest.json 统计 | 是 | 概览展示位切换 |

## 七、风险点

1. **首见 qk 顺序**:前端 _simBuildModePool 遍历 qk 按 JSON 插入序,首见写入 rec。唯一化主表若在构建期直接落字段,须保证 4 个 qk 归属不依赖顺序——实测每基笔 4 qk 分属 mkt/etf/sig/rating 各一,聚合维度值唯一,**顺序无关**(已验证)
2. **45 条 signal 差异笔**:key 含 signal 天然分离,主表保留 signal 即保真(已验证前端处理口径)
3. **双套产物(sdc)**:口径切换 _simTradesBaseName() 依赖两套并存,瘦身须同构覆盖两套
4. **s06 动态过滤**:per-date 基座依赖 signal_date 字段,保留
5. **G/H/I 管位**:依赖 etf_code → nav 映射,保留
6. **预聚合漂移**:预聚合仅默认参数路径;任何预聚合数字发布前与前端逐笔重算逐一断言(§5.4⑦)
7. **费用口径**:费后重算字段(real_buy_price/real_sell_price/shares)必须原样保存,不可预聚合/压缩精度
8. **基准锚定**:实施重算口径时以 current baseline v1.1.7 为准,测试基准=current baseline(§5.4③)

## 八、业界佐证(e,§5.1 要求上网调研)

- 预聚合+明细分层(聚合表/明细表):ClickHouse 物化视图文档(已验证可达)
- 按需范围读取:HTTP Range Requests 规范(MDN,已验证可达)
- 数据分层(热区/冷区):ClickHouse TTL 指南(已验证可达)
- 列式+字典编码:Apache Parquet file format(未在本机验证,建议实施前再取权威链接)

## 九、待验证项(不阻塞方案)

- lab_ 364 files 全站引用面再确认(本次只查了 app.js/lab.js)
- 唯一化后各列实际压缩率用生成端实测数据跑一版(实施 agent 做)
- 字典编码/列式化样本体积的实验(实施 agent 做,user 愿等 §5.1)
