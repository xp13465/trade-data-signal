# 全球品种实时跑马灯 · 免费行情源调研报告

- 日期:2026-08-17(周日 19:5x,实测于贵金属/外汇 24h 盘活跃时段,周末新浪/东财均返回实时数据)
- 目的:首页「今日要闻」/「明日关键事件」下方加实时跑马灯(8 全球品种:现货黄金/现货白银/WTI原油/布伦特油/富时A50/美元指数/离岸人民币/美元日元),浏览器侧高频刷新(5-30s 轮询)。本报告只调研,不做实施。
- 结论一句话:**8 品种全部有免费实时源,且每品种双异源(新浪 hq.sinajs.cn + 东财 push2delay);前端可直连东财(CORS *),新浪无 CORS 走后端代理兜底**。
- ⚠️ **最终拍板(2026-08-17 用户定,覆盖原推荐):只做纯客户浏览器端直连东财 push2delay 单源,砍掉新浪后端代理兜底**——用户原话「我要的是纯客户浏览器端的 别给服务器增加压力了。10s压力后段转法不行」,即:服务器零压力优先,任何后端定时采集/接口代理都不做。**接受单源风险**(东财崩→跑马灯暂时无数据+标注,不自动切新浪,因新浪需后端代理)。实施方案一律按此单源执行,下文"默认推荐/异源兜底"段已被本拍板覆盖。

---

## 一、8 品种 × 可用源 × URL × 字段位置对照表

### 实测数据快照(2026-08-17 19:58,北京时间)
| 品种 | 新浪最新 | 东财最新 | 双源一致性 |
|---|---|---|---|
| 现货黄金 XAU | 4396.94 (hf_XAU) | 4397.11 (122.XAU) | 差 0.17 ✓ |
| 现货白银 XAG | 65.66 (hf_XAG) | 65.68 (122.XAG) | 差 0.02 ✓ |
| WTI原油 | 81.731 (hf_CL) | 82.54 (102.CL00Y) | 差 0.81(合约口径差异,见风险节) |
| 布伦特油 | 88.731 (hf_OIL) | 88.98 (112.B00Y) | 差 0.25 ✓ |
| 富时A50 | 15144.2 (hf_CHA50CFD) | 15144.0 (104.CN00Y 期指) | 一致 ✓(100.XIN9=15214 是现货指数点位,有基差,勿用) |
| 美元指数 | 99.4630 (DINIW) | 99.46 (100.UDI) | 一致 ✓ |
| 离岸人民币 | 6.7463 (fx_susdcny) | 6.7409 (133.USDCNH) | 差 0.005 ✓ |
| 美元日元 | 159.30 (fx_susdjpy) | 159.2510 (119.USDJPY) | 差 0.05 ✓ |

### 新浪 hq.sinajs.cn(GBK 编码,需 Header Referer: https://finance.sina.com.cn)
批量 URL:`https://hq.sinajs.cn/list=code1,code2,...`(一次拉全部,实测 8 品种 + 沪金/沪银共 10 码一次请求成功)
返回格式:`var hq_str_<code>="字段逗号分隔";`

| 品种 | 新浪代码 | 最新价位置 | 昨收位置 | 涨跌幅 | 时间 | 名称位置 |
|---|---|---|---|---|---|---|
| 现货黄金 | `hf_XAU` | [0] | [1] | 自算=(价-昨收)/昨收 | [5](HH:MM:SS) | [13] 伦敦金（现货黄金） |
| 现货白银 | `hf_XAG` | [0] | [1] | 自算 | [5] | [13] 伦敦银（现货白银） |
| WTI原油 | `hf_CL` | [0] | [2] | 自算 | [6] | [13] 纽约原油 |
| 布伦特油 | `hf_OIL` | [0] | [2] | 自算 | [6] | [13] 布伦特原油 |
| 富时A50 | `hf_CHA50CFD` | [0] | [2] | 自算 | [6] | [13] 富时中国A50期货 |
| 美元指数 | `DINIW`(无前缀!) | [1] | [3] | 自算(实测-0.177%,与东财-0.18%吻合) | [0] | [9] 美元指数 |
| 离岸人民币 | `fx_susdcny` | [3] | [8] | [11](直接给出) | [0] | [9](显示"在岸人民币"实为离岸,新浪命名混乱) |
| 美元日元 | `fx_susdjpy` | [3] | [8] | [11](直接给出) | [0] | [9] 美元兑日元即期汇率 |

> 格式备注:hf_XAU/hf_XAG(伦敦现货)比 hf_CL/hf_OIL/hf_CHA50CFD(外盘期货)多 1 字段偏移;fx_ 外汇 18 字段,DINIW 是 11 字段(无涨跌字段,自算)。**项目 intraday_snapshot.py L439 `_parse_sina_commodity` + L521 `_parse_sina_fx` 已有解析实现可复用,需新增 hf_XAG/DINIW 两个 code 分支**(详见第五节)。
> 实测:新浪代码大小写敏感,`hf_UDI`/`hf_DINIW`/`hf_CHA50` 等变体全空;`DINIW` 无前缀才有美元指数。

### 东财 push2delay(CORS *,JSON,UTF-8,实测 8 品种全有数据)
批量 URL:`https://push2delay.eastmoney.com/api/qt/ulist.np/get?secids=<secid1>,<secid2>,...&fields=f43,f58,f60,f86,f170`(ulist 支持批量;单只用 stock/get)
返回 JSON:data[f43]=最新价、[f60]=昨收、[f170]=涨跌幅%、[f86]=Unix 时间戳、[f58]=名称

| 品种 | 东财 secid | 最新价缩放 | 备注 |
|---|---|---|---|
| 现货黄金 | `122.XAU` | f43×100(439711→4397.11) | 名称 黄金/美元 |
| 现货白银 | `122.XAG` | f43×100(6568→65.68) | 名称 白银/美元 |
| WTI原油 | `102.CL00Y` | f43×100(8254→82.54) | NYMEX原油 |
| 布伦特油 | `112.B00Y` | f43×100(8898→88.98) | 布伦特原油当月连续 |
| 富时A50 | `104.CN00Y`(期指,推荐) / `100.XIN9`(现货指数) | f43×100(151440→15144.0) | CN00Y 与新浪 CHA50CFD 数值一致;XIN9 有基差 |
| 美元指数 | `100.UDI` | f43×100(9946→99.46) | 名称 美元指数 |
| 离岸人民币 | `133.USDCNH` | f43×10000(67409→6.7409) | 外汇市场 ×10000 |
| 美元日元 | `119.USDJPY` | f43×10000(1592510→159.2510) | 外汇市场 ×10000 |

> f170 涨跌幅统一 ×100(如 47→0.47%、154→1.54%、-18→-0.18%);f86 实测为本地时间戳(贵金属/外汇/美元指数 1 分钟内实时)。**东财 push2 主 host(push2.eastmoney.com)实测全空(被风控/间歇不稳定,项目 memory 已知),必须用 push2delay**(分时图同款)。
> 东财 secid 来源:searchapi.eastmoney.com/api/suggest/get 实测检索(UDI/XIN9/CN00Y/USDCNH/USDJPY/GC00Y/CL00Y/SI00Y/B00Y/XAU/XAG)。

---

## 二、CORS 实测结论(直连 vs 代理)

### 实测响应头(2026-08-17,curl -D - 抓头)
| 源 | Access-Control-Allow-Origin | Content-Type | 前端直连? |
|---|---|---|---|
| 新浪 hq.sinajs.cn | **无此头** | application/javascript; charset=GB18030 | ✗ 不可直连 |
| 腾讯 qt.gtimg.cn | `*` | text/html; charset=GBK | ✓ 但仅覆盖 A股/港股,不含目标 8 品种(usDINIW/hkFCHA50CFD 等实测全空) |
| 东财 push2delay | `*`(且 allow-credentials:true) | application/json; UTF-8 | ✓ **唯一 CORS 覆盖全部 8 品种的源** |

### 路线对比
- **前端直连东财 push2delay(推荐主路)**:CORS * 实测通过,JSON 解析友好,ulist 批量一次拉 8 品种(1 请求),与项目分时图"前端直连 CORS * + setTimeout 递归"同模式。符合用户"像分时图一样浏览器侧刷新"的要求,零新增后端任务。**代价**:东财对 A 股是延时行情(push2delay),但对贵金属/外汇/美元指数实测实时(1 分钟内);原油实测停在最新成交时间(19:48,周日原油盘清淡,属正常)。
- **后端代理新浪(推荐兜底路)**:新浪无 CORS 前端直连不了,但项目**已有现成机制**——`intraday_snapshot.py fetch_commodity_realtime()/fetch_fx_realtime()` 已在盘中每 10 分钟采新浪 6 商品+离岸人民币(源码 L568/L589),可扩展 code 列表(hf_XAG/DINIW/hf_CHA50CFD)落一个高频小 JSON 或接口供前端兜底。**代价**:后端定时任务 + 落盘/接口 + 前端双请求。仅作为东财崩了时的兜底。
- **新浪 script 标签 hack(不推荐)**:`<script src="https://hq.sinajs.cn/list=...">` 加载后读全局 `window.hq_str_xxx`,无 CORS 限制。但无法感知加载失败/超时、防抖差、污染全局,与项目工程化风格不符。

**✅ 已拍板方案(2026-08-17 用户定,替代下述原推荐):纯前端直连东财 push2delay 单源,浏览器侧 10s 轮询,零后端任务/零服务器压力。**新浪后端代理兜底路线因"给服务器增加压力"被用户否决,不再采用(新浪无 CORS,前端直连不可行,故新浪源整体弃用;东财单源崩时跑马灯显示占位/降级文案,不自动切换)。
~~原推荐(已作废):前端直连东财 push2delay 为主源(浏览器侧 10s 轮询),新浪走后端代理作异源兜底(满足 memory source-reliability "任一源必须有异源兜底,fallback 不走同源")。若为省后端任务接受单源风险,可只做东财直连,但不符合项目数据源铁律,不建议。~~

---

## 三、现有源复用盘点(项目已覆盖 vs 需新增)

### 项目现状(源码实测,2026-08-17)
| 机制 | 文件 | 覆盖 | 频率 |
|---|---|---|---|
| 分时图 | static-site/app.js L7631-8474,INTRADAY_REFRESH_MS=60s,setTimeout 递归 | 12 指数(9A股+3港股)前端直连腾讯/同花顺/东财,CORS * | 盘中每 1 分钟浏览器侧刷新 |
| 盘中快照 | trade-data/app/collector/intraday_snapshot.py | 新浪 hq.sinajs.cn 采 **6 商品(hf_XAU伦敦金/hf_CL WTI/hf_SI COMEX银/hf_OIL布伦特/nf_AU0沪金/nf_SC0上海油)+ 离岸人民币 fx_susdcny** + 腾讯 17 指数 + 同花顺行业 | 后端每 10 分钟(27 次/天) |
| 夜盘补采 | trade-data/app/collector/gold_night.py | 沪金/上海油夜盘收盘价写 daily_metric | 02:40 |
| 指数日线 | app/collector/fetchers.collect_index | 新浪 stock_zh_index_daily 主 + baostock/腾讯兜底,10 核心 A 股指数 | 日频(T+1) |

### 8 目标品种覆盖判定
| 品种 | 项目已有机源(盘中) | 需新增? |
|---|---|---|
| 现货黄金 | ✓ 新浪 hf_XAU 已有(项目 COMMODITY_CODES L106) | 否(仅展示位新增) |
| 现货白银 | ✗ 项目只有 COMEX 银期货 hf_SI(纽约白银),无现货 hf_XAG | **是**(加 hf_XAG) |
| WTI原油 | ✓ 新浪 hf_CL 已有 | 否 |
| 布伦特油 | ✓ 新浪 hf_OIL 已有 | 否 |
| 富时A50 | ✗ 项目未覆盖(分时图只有 A 股/港股指数,无新加坡 A50) | **是**(hf_CHA50CFD 或东财) |
| 美元指数 | ✗ 项目未覆盖 | **是**(新浪 DINIW 或东财 100.UDI) |
| 离岸人民币 | ✓ 新浪 fx_susdcny 已有(项目 FX_CODE L124) | 否 |
| 美元日元 | ✗ 项目未覆盖 | **是**(fx_susdjpy 或东财 119.USDJPY) |

**结论:8 品种里 4 个已有机源可复用(黄金/WTI/布伦特/离岸人民币,走新浪 hf_/fx_ 实时源,盘中已采),4 个需新增代码(现货白银 hf_XAG/A50 hf_CHA50CFD/美元指数 DINIW/美元日元 fx_susdjpy)——但**全部只需在现有新浪批量 list 里加 code,或前端直连东财 secid 即可,不需要新增数据源供应商**。项目分时图/日图对富时A50/美元指数/USDJPY 从无覆盖(现有覆盖全是 A 股/港股指数),这 3 个是全新品种。**

---

## 四、轮询频率建议

### 参考基准
- 项目分时图 = 前端直连 + 1 分钟轮询(INTRADAY_REFRESH_MS=60s,setTimeout 递归防 tab 隐藏堆积,收盘后收起)
- 项目数据源压测边界(memory source-reliability-needs-stress-test):同花顺 30 次/min、东财 push2delay 60 次/min 峰值、腾讯 40 次/min 零 501

### 实测压测(2026-08-17,本报告)
- 新浪 hq.sinajs.cn **15 次连打(≈5s 间隔模拟 12 次/min),15/15 全返回 6 品种,零失败零风控**
- 东财 push2delay **15 次连打,15/15 全成功(美元指数),零失败**

### 建议(全球 24h 品种,区分时段)
| 时段 | 建议轮询 | 次数/min | 相对边界余量 |
|---|---|---|---|
| 全球活跃盘(如欧股/美股/贵金属活跃时段) | 10s | 6 | 东财边界 60,余量 10x |
| 盘后/周末(全球清淡,如周日白天) | 30-60s | 1-2 | 极安全 |
| 用户点名区间 5-30s | 5s 上限已实测 15/15 稳定 | 12 | 余量 5x |

**默认建议:10s 轮询(6 次/min,余量 10x),周末/深夜自动降频到 30s;setTimeout 递归(复用分时图模式),tab 隐藏时暂停或降频防堆积。8 品种东财 ulist 批量 1 请求即可,无需逐品种请求。**

---

## 五、风险与合规

1. **免费源稳定性/反爬**:东财 push2 主 host 已被风控(实测全空,项目 memory 已知"东财 push2 间歇 0/10 不稳定"),**必须用 push2delay 且控制频率在边界内**(60 次/min 以下,建议 6-12 次/min);新浪无 CORS 且需 Referer,频率过高会被 403/封 IP(实测 15 次连打安全)。
2. **数据延时口径**:东财 push2delay 对 A 股是延时行情,但对贵金属/外汇/美元指数实测实时(f86 时间戳 1 分钟内);原油 CL00Y 实测停在新成交时间 19:48(周日原油盘清淡,价格无新成交时数据停更属正常,非故障)。
3. **品种口径差异**:WTI 新浪 hf_CL(81.73)vs 东财 102.CL00Y(82.54)差 0.81,疑主力月/连续加权合约口径不同——**跑马灯同一品种固定用单一源,不混用**(双源仅作故障兜底切换,不并存展示)。
4. **富时A50 交易时段**:新加坡 A50 期货周五收盘后周六凌晨有交易,周日白天基本停(实测周日 XIN9 停在 15:00),跑马灯需容忍"该品种当前无新数据"(显示最后价格 + 时间,不报错)。
5. **合规**:免费行情源仅个人展示用;页面须标注"全球行情数据来源网络公开接口,实时刷新,仅供参考,不构成投资建议";延时标注(东财 A 股延时,全球品种实时)。
6. **异源兜底(项目铁律,本跑马灯已豁免)**:原铁律=主东财直连/兜底新浪后端代理(两源不同 host,符合"fallback 不走同源")。**但 2026-08-17 用户拍板"纯客户端零服务器压力"已豁免本项**:新浪后端代理不做,跑马灯为单源东财,接受"东财崩→暂时无数据"的风险,降级显示不自动切源。腾讯 qt 对目标品种无覆盖,不作兜底。
7. **金十/英为专有接口**:金十数据(rtd.jin10.com 实测空)、英为财情(investing.com)均为不公开/反爬重,不采用——**不用去强求,新浪+东财已够 8 品种双源**。

---

## 六、实施落点建议(供后续实施,本次不实施)

- **展示位**:首页 AI 预测卡「📣 今日要闻」行(L10260)+「📅 明日关键事件」行(L21994)下方加跑马灯条;数据走东财 ulist 批量接口。
- **可复用代码**:前端 fetchJSON/分时轮询模式(L7631-8474);后端新浪代理复用 intraday_snapshot.py `fetch_commodity_realtime()`(L568,加 hf_XAG/DINIW/hf_CHA50CFD code)+ `_parse_sina_commodity`(L439,加 DINIW 11 字段分支)。
- **8 品种统一结构**:{name, code, price, pct_change, timestamp},前端按来源统一缩放(新浪无缩放直接解析;东财 f43×100 或 ×10000 按品种, f170×100 涨跌幅)。

---

## 复现

- **脚本/命令**:见下(纯 curl 实测,无脚本文件)
- **输入依赖**:无(公共免费接口,无需 key/登录)
- **数据截止**:2026-08-17 19:5x(北京时间,周末贵金属/外汇 24h 盘活跃时段)
- **关键口径一句话**:新浪 hq.sinajs.cn(GBK,需 Referer finance.sina.com.cn,无 CORS)用 hf_XAU/hf_XAG/hf_CL/hf_OIL/hf_CHA50CFD/DINIW/fx_susdcny/fx_susdjpy 8 码一次批量;东财 push2delay(CORS *,JSON)用 122.XAU/122.XAG/102.CL00Y/112.B00Y/104.CN00Y/100.UDI/133.USDCNH/119.USDJPY 8 secid 一次 ulist 批量,最新价按品种缩放(外汇×10000 其余×100)、涨跌幅 f170 统一×100

```bash
# 新浪 8 品种批量(含美元指数 DINIW 无前缀、现货银 hf_XAG)
curl -s -H "Referer: https://finance.sina.com.cn" -H "User-Agent: Mozilla/5.0" \
  "https://hq.sinajs.cn/list=hf_XAU,hf_XAG,hf_CL,hf_OIL,hf_CHA50CFD,DINIW,fx_susdcny,fx_susdjpy" | iconv -f gbk -t utf-8

# 东财 8 品种批量(push2delay!push2 主 host 实测全空不可用)
curl -s -H "User-Agent: Mozilla/5.0" \
  "https://push2delay.eastmoney.com/api/qt/ulist.np/get?secids=122.XAU,122.XAG,102.CL00Y,112.B00Y,104.CN00Y,100.UDI,133.USDCNH,119.USDJPY&fields=f43,f58,f60,f86,f170"
```

---

# 2026-08-17 二轮:1主2备 纯客户端备源深化(追加,commit 后验)

- 日期:2026-08-17 20:0x-20:12(周末贵金属/外汇 24h 盘活跃时段实测)
- 目的:上一轮用户拍板「纯客户端直连东财单源、零服务器压力」后,再加码「1主2备」最佳状态——除东财主源外,再找 **2 个纯客户端可用备源**(全部前端直连,不允许任何后端)。本轮逐项实测出证据。
- 结论一句话:**备源1 = 腾讯 qt.gtimg.cn(原报告误判,本次推翻——漏测 hf_/wh_ 前缀,实为 CORS * + 6/8 品种实时);备源2 = api.gold-api.com(黄金/白银现货)+ open.er-api.com(外汇日更)组合;新浪 script hack 实测 Referer 防盗链不可行;诚实标注缺口=富时A50 与美元指数除东财外无任何 CORS 备源。**

## 2.1 任务1:腾讯 qt.gtimg.cn 重测结论(原报告误判,本次推翻)

**原报告(620f7f20a)「腾讯 CORS * 但目标品种代码实测全空(usDINIW/hkFCHA50CFD 等)」——本次实测发现原报告只试了 us_/hk_ 前缀变体,漏测 hf_(外盘期货)/wh_(外汇)前缀,导致误判。**

实测(2026-08-17 20:06-20:12,`curl https://qt.gtimg.cn/q=...` + iconv gbk):

| 腾讯代码 | 名称 | 现价 | 昨收 | 时间 | 实时? | 对应品种/口径 |
|---|---|---|---|---|---|---|
| `hf_GC` | 纽约黄金 | 4451.58 | 4437.30 | 20:12:01 | ✓ | 黄金(**COMEX 期货**,现货 4393.84,基差 +56) |
| `hf_SI` | 纽约白银 | 65.85 | 65.11 | 20:11:22 | ✓ | 白银(**COMEX 期货**,现货 65.63,差 +0.22) |
| `hf_CL` | 纽约原油 | 81.70 | 81.47 | 20:12:00 | ✓ | WTI(与新浪 81.73 一致) |
| `hf_OIL` | 布伦特原油 | 88.67 | 88.52 | 20:12:00 | ✓ | 布伦特(与新浪 88.73 一致) |
| `whUSDJPY` | 美元日元 | 159.21 | 159.31 | 20:12:00 | ✓ | 美元日元 |
| `whUSDCNY` | 美元人民币 | 6.7391 | 6.7421 | 20:11:55 | ✓ | 人民币(**在岸 CNY**,品种要求离岸 CNH) |
| `whDINIW` | 美元指数 | 99.64 | 99.60 | **20260810160649=8/10 16:06** | ✗ **旧数据** | 美元指数(两次复验均停在 8/10,不实时) |
| `whUSDCNH`/`whCNH`/`whCNY` | — | — | — | — | ✗ 全空 | 离岸人民币(腾讯无离岸代码) |
| `hf_CHA50CFD`/`hf_A50`/`hkCHA50CFD`/`rt_hf_CHA50CFD`/`whCHA50CFD`/`sgA50`/`hf_CN00` | — | — | — | — | ✗ 全空 | 富时A50(腾讯无 A50) |

- CORS 头:`HTTP/2 200, access-control-allow-origin: *, content-type: text/html; charset=GBK`(抓头确认)
- 编码 GBK:fetch 需 `response.arrayBuffer() → new TextDecoder('gbk').decode()`(浏览器 TextDecoder 原生支持 gbk)
- 批量:`qt.gtimg.cn/q=code1,code2,...` 一次多码,6 品种 1 请求;`v_pv_none_match="1"` 表示代码无效
- 字段解析:`v_hf_GC="4451.58,0.32,4449.50,4449.90,4473.20,4422.30,20:12:01,4437.30,4440.00,0,3,2,2026-08-17,纽约黄金"` → `[0]`现价、`[1]`涨跌幅%、`[3]`开盘、`[4]`最高、`[5]`最低、`[6]`时间、`[7]`昨收、`[12]`日期、`[13]`名称;`v_whUSDJPY="310~美元日元~USDJPY~159.2100~0~20260817201200~..."` 按 `~` 分 `[1]`名称、`[2]`代码、`[3]`最新价、`[5]`时间戳(YYYYMMDDHHMMSS)、`[6]`昨收、`[12]`涨跌额、`[13]`涨跌幅%
- **期货口径实锤**:东财 COMEX 黄金 `101.GC00Y` f43=44507≈4450.7、COMEX 白银 `101.SI00Y`=65780≈65.78,与腾讯 hf_GC 4451.58/hf_SI 65.85 一致;而东财现货 `122.XAU`=4393.84、`122.XAG`=65.63。**腾讯 hf_GC/hf_SI=COMEX 期货非现货,基差黄金+56/白银+0.22,备源切换该品种价格跳变,UI 需标注「期货口径」或接受跳变。**
- **腾讯可作备源1:覆盖 6/8(WTI/布伦特/USDJPY 与现货一致,黄金/白银期货口径),缺 离岸人民币(无代码)/美元指数(8/10 旧数据)/富时A50(无)。**

## 2.2 任务2:新浪 script 标签 hack 可行性(Referer 三态实测:不可行)

**结论:新浪 hq.sinajs.cn 按 Referer 防盗链,script 标签从本站域加载必被拒,纯客户端 hack 不可行。**

Referer 三态实测(2026-08-17 20:06,其余请求头一致仅换 Referer):

| Referer | 返回 | 结论 |
|---|---|---|
| 无 | `Forbidden` | 拒绝 |
| `https://ss.fx8.store/`(模拟本站页面加载 script) | `Forbidden` | 拒绝 |
| `https://finance.sina.com.cn` | 正常返回 4 品种数据 | 仅新浪域通过 |

- 浏览器 `<script src>` 跨域加载带当前页 URL 作 Referer(Chrome 默认 strict-origin-when-cross-origin,跨域发 origin)= 本站域 → **必 Forbidden**;script 标签无法自定义/伪造 Referer。
- 附带验证:新浪 `hq2.sinajs.cn` 变体同样 Forbidden;新浪 JSONP 接口(stock.finance.sina.com.cn 与 stock2 的 /futures/api/jsonp.php/GlobalFuturesService)实测 `Service not found`(接口已下线,非防盗链问题,一并排除)。
- **新浪 script hack 不可作纯客户端备源。**(上一轮「新浪需 Referer/无 CORS」判断正确,本轮补实锤:script 标签 hack 同样被 Referer 拦死。)

## 2.3 任务3:第3源候选实测(当选:gold-api + open.er-api;失败源诚实清单)

**✅ 入选 2 个(均 CORS `*` 抓头确认、免费无需 key):**
| 源 | URL | CORS | 实测返回 | 覆盖 | 口径/时效 |
|---|---|---|---|---|---|
| **api.gold-api.com** | `https://api.gold-api.com/price/XAU` | `*` | `{"name":"Gold","price":4395.2,"symbol":"XAU","updatedAt":"2026-08-17T12:09:03Z"}` | XAU 黄金/XAG 白银(**现货**) | 实时("a few seconds ago");一次仅 1 symbol(不支持批量);无昨收→无涨跌幅 |
| **open.er-api.com** | `https://open.er-api.com/v6/latest/USD` | `*` | `{"result":"success","rates":{...},"time_next_update_utc":...}` | 161 货币(USDCNH/USDJPY) | **日更非实时**(time_next_update=次日);无涨跌幅 |

**❌ 失败/不可用源(诚实标注):**
| 源 | 实测 | 原因 |
|---|---|---|
| Yahoo finance(query1/query2 的 v7/v8) | HTTP 403 | 数据中心 IP 被反爬;浏览器家庭 IP 可能可用但 403 无法验证 CORS,不作确定备源 |
| stooq.com | 404 | 路径变更/不存在,无 CORS 头 |
| 和讯 quote.hexun.com | 301→404 | 接口已下线 |
| 同花顺 d.10jqka.com.cn | 404(fut_GC 路径) | CORS `*` 存在但外盘实时接口路径未找到,不作备源 |
| api.frankfurter.app / .dev | 301/无响应 | 域名迁移中/Cloudflare 拦 |
| data-asg.goldprice.org(金价官网) | 403 | 反爬无 CORS |
| 金十 rtd.jin10.com | (上轮已测空) | 不公开 |

## 2.4 任务4:1主2备 组合表 + 频率 + 降级顺序

| | 源 | host | CORS | 覆盖 | 口径/时效 | 编码 | 请求数 |
|---|---|---|---|---|---|---|---|
| **主** | 东财 push2delay(单只 stock/get) | push2delay.eastmoney.com | `*`(抓头) | 8/8 | 现货/实时 | UTF-8 JSON | 8(单只)或 1(ulist 批量,当前失效) |
| **备1** | 腾讯 qt.gtimg.cn | qt.gtimg.cn | `*`(抓头) | 6/8(黄金/白银期货) | 实时 | GBK | 1(6 码批量) |
| **备2** | gold-api + open.er-api | 异 host ×2 | `*` ×2 | 4/8 | gold-api 实时、er-api 日更 | UTF-8 JSON | 2+1 |

品种级覆盖矩阵:

| 品种 | 主:东财 | 备1:腾讯 | 备2:gold-api/er-api |
|---|---|---|---|
| 现货黄金 | `122.XAU` ✓ | `hf_GC` ✓(期货+56) | `XAU` ✓(现货) |
| 现货白银 | `122.XAG` ✓ | `hf_SI` ✓(期货+0.22) | `XAG` ✓(现货) |
| WTI | `102.CL00Y` ✓ | `hf_CL` ✓ | ✗ |
| 布伦特 | `112.B00Y` ✓ | `hf_OIL` ✓ | ✗ |
| 富时A50 | `104.CN00Y` ✓ | ✗ | ✗ |
| 美元指数 | `100.UDI` ✓ | `whDINIW` ✗(8/10 旧) | ✗ |
| 离岸人民币 | `133.USDCNH` ✓ | ✗(只有岸 CNY) | `er-api USDCNH` ✓(日更) |
| 美元日元 | `119.USDJPY` ✓ | `whUSDJPY` ✓ | `er-api USDJPY` ✓(日更) |

**诚实标注缺口:富时A50 与美元指数除东财主源外无任何 CORS 备源**(新浪有对应码但 Referer 防盗链;腾讯无/旧;gold-api/er-api 无)。备源模式下这 2 品种显示「暂无数据/最后价」。**1主2备 在品种层面无法 100% 达成,请主控向用户说明:6/8 品种双备、A50/美元指数仅东财单源。**

轮询频率建议(避免源被风控):

| 源 | 频率 | 请求/轮询 | 次/min | 边界余量 |
|---|---|---|---|---|
| 东财(单只 8 请求) | 30s | 8 | 16 | 东财边界 60,余量 3.7x |
| 东财(若 ulist 批量恢复) | 10s | 1 | 6 | 余量 10x |
| 腾讯(批量 1 请求) | 10-15s | 1 | 4-6 | 边界 40 零 501,余量 6x |
| gold-api(2 请求) | 15-30s | 2 | 4-8 | 未知边界,保守 |
| er-api(日更数据) | 30-60min | 1 | — | 数据本身日更,高频无意义 |

- 共用:setTimeout 递归(复用分时图模式)、tab 隐藏暂停/降频、单源连续失败 3 次→指数退避(30s/60s/120s)。

前端自动降级顺序:
1. 东财 8 只成功 → 展示东财(现货口径全 8)
2. 东财失败 → 切腾讯批量(1 请求);离岸/A50/美元指数显示「——」或最后缓存价;黄金/白银 UI 标注「期货口径」
3. 腾讯失败 → 切备源2(gold-api XAU/XAG + er-api USDCNH/USDJPY);其余品种「——」
4. 全挂 → 显示「行情源暂不可用」+ 指数退避重试
5. 同品种不混源(沿用上轮:固定单一源,降级整源切换不并存展示)
6. 单品种失败保留最后成功价,不整行消失

实施要点(最小实现):
- 腾讯 GBK:`fetch(url).then(r=>r.arrayBuffer()).then(buf=>new TextDecoder('gbk').decode(buf))` → 逐行 `v_xxx="...";` 解析;`v_pv_none_match="1"`=无效代码
- 东财/备源2 直接 `res.json()`;统一输出 `{name, price, pct, ts}`
- 东财 f43 按品种缩放(外汇 ×10000,其余 ×100)、f170×100;腾讯 price=[0]、pct=[1](hf_)/[13](wh_);gold-api 无 pct 显示「—」

## 2.5 任务5:东财 push2 主 host 确认 + ulist 批量增量发现

- **push2 主 host(push2.eastmoney.com):实测返回 JSON 结构但 f43/f58/f86/f170 全 0(单只+批量两次确认),确认不可用,必须 push2delay。** 若备源只用东财体系(push2delay+push2)=同东财体系,主挂备大概率同挂=伪兜底——**故备源必须是异体系(本轮已落实:备1 腾讯=异 host,备2 gold-api/er-api=异 host),不违反同源兜底原则。**
- **⚠️ 增量发现:push2delay 的 ulist.np/get 批量路径本轮多次复测全 0(8 码/3 码/单码均 0),而上轮 19:58 同路径有数据;同 host 的 stock/get 单只路径稳定有数据(8/8 逐一验证)。** 无法断定是间歇失效还是本轮连打触发 IP 风控,但结论明确:**实施主源必须用 stock/get 单只路径(8 请求/轮询),或 ulist 批量+失败自动降级单只(自愈)。**
- 主源单只路径逐一验证(2026-08-17 20:10):

| secid | f43 | 换算 | f58 名称 |
|---|---|---|---|
| 122.XAU | 439384 | 4393.84 | 黄金/美元 |
| 122.XAG | 6563 | 65.63 | 白银/美元 |
| 102.CL00Y | 8234 | 82.34 | NYMEX原油 |
| 112.B00Y | 8878 | 88.78 | 布伦特原油当月连续 |
| 104.CN00Y | 151400 | 15140.0 | A50期指当月连续 |
| 100.UDI | 9944 | 99.44 | 美元指数 |
| 133.USDCNH | 67408 | 6.7408 | 美元兑离岸人民币 |
| 119.USDJPY | 1592045 | 159.2045 | 美元兑日元 |

(与新浪对照:黄金 4393.84 vs 4394.86、白银 65.63 vs 65.66、美元指数 99.44 vs 99.44 一致 ✓)

## 二轮复现命令

```bash
# 腾讯 6 码批量(CORS *,GBK)
curl -s "https://qt.gtimg.cn/q=hf_GC,hf_SI,hf_CL,hf_OIL,whUSDJPY,whUSDCNY" | iconv -f gbk -t utf-8
# 新浪 Referer 三态(script hack 可行性证据)
curl -s "https://hq.sinajs.cn/list=hf_XAU" -H "Referer: https://ss.fx8.store/"        # Forbidden
curl -s "https://hq.sinajs.cn/list=hf_XAU" -H "Referer: https://finance.sina.com.cn" # 正常
# 第3源(均 CORS *)
curl -s "https://api.gold-api.com/price/XAU"      # 黄金现货
curl -s "https://open.er-api.com/v6/latest/USD"   # 外汇日更
# 东财主源单只(ulist 批量本轮全 0,勿用)
curl -s "https://push2delay.eastmoney.com/api/qt/stock/get?secid=122.XAU&fields=f43,f58,f60,f86,f170"
```

- 数据截止:2026-08-17 20:0x-20:12(北京时间,周末贵金属/外汇 24h 盘活跃时段)
- 关键口径一句话:主源=东财 push2delay 单只 stock/get(现货全 8,ulist 批量当前失效);备1=腾讯 qt.gtimg.cn 批量 hf_+wh_(6/8,黄金/白银期货口径);备2=gold-api(XAU/XAG 现货)+open.er-api(USDCNH/USDJPY 日更);新浪 script hack 被 Referer 防盗链拒绝不可行。
