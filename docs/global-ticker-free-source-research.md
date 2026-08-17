# 全球品种实时跑马灯 · 免费行情源调研报告

- 日期:2026-08-17(周日 19:5x,实测于贵金属/外汇 24h 盘活跃时段,周末新浪/东财均返回实时数据)
- 目的:首页「今日要闻」/「明日关键事件」下方加实时跑马灯(8 全球品种:现货黄金/现货白银/WTI原油/布伦特油/富时A50/美元指数/离岸人民币/美元日元),浏览器侧高频刷新(5-30s 轮询)。本报告只调研,不做实施。
- 结论一句话:**8 品种全部有免费实时源,且每品种双异源(新浪 hq.sinajs.cn + 东财 push2delay);前端可直连东财(CORS *),新浪无 CORS 走后端代理兜底**。

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

**默认推荐:前端直连东财 push2delay 为主源(浏览器侧 10s 轮询),新浪走后端代理作异源兜底**(满足 memory source-reliability "任一源必须有异源兜底,fallback 不走同源")。若为省后端任务接受单源风险,可只做东财直连,但不符合项目数据源铁律,不建议。

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
6. **异源兜底(项目铁律)**:主=东财 push2delay(前端直连),兜底=新浪(后端代理,复用 fetch_commodity_realtime)。两源不同 host/不同供应商,符合"fallback 不走同源"。腾讯 qt 对目标品种无覆盖,不作兜底。
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
