# 首页「分析参考点AI监控」卡两走势图渲染慢·根因调研与提速方案

- 日期:2026-08-24 | 角色:researcher | 只读调研,未改任何代码
- 用户原话:「首页的这个分析参考点ai监控 里面的准确率和过拟合风险分走势图渲染每次都好慢。查一下什么原因 可以优化提速么」
- 关键词锚点:`static-site/app.js` `_renderOverfitAcc`(L1701)/`_renderOverfitRisk`(L1788)/`_appendOverfitCard`(L2096)/`_fetchOverfitMonitor`(L2081);`worker/headers.js` `dataCacheTtl`(L158);`scripts/overfit_monitor.py` json.dump(L1669/L1703)

## 一、结论(TL;DR)

**慢的不是"渲染",是"每次都全量下载 27.8MB 的 overfit_monitor.json"。** 渲染层(SVG 重绘)实测仅 ~7ms,CPU 段合计 <300ms;瓶颈 90% 以上在网络段——线上该文件被 worker 归入 NO_CACHE(ttl=0)→ 响应头 `cache-control: no-store, max-age=0`,浏览器和 CF 边缘都不缓存,**每次刷新页面都重新下载整个 27.8MB**(CF br 压缩后传输 1.52MB,实测总耗时 2.8~11.4s)。叠加文件本身有 64% 的纯格式化浪费(`indent=2`)与 77% 的默认渲染不消费数据(by_k/filtered_by_k)。

## 二、证据链(逐条可复核)

### 2.1 UI 渲染层定位(对准用户看到的位置)
| 点 | 位置 | 说明 |
|---|---|---|
| 卡片构建 | `app.js:2096 _appendOverfitCard(colA2,r,snap)` | renderOverview 主链路 L14149 **fire-and-forget 调用(无 await)**,不阻塞整页首屏 |
| 准确率图 | `app.js:1701 _renderOverfitAcc` | 已是首页轻量 SVG 引擎 `_lwSetup`(L16143),非 echarts;echarts 只是 fallback |
| 风险分图 | `app.js:1788 _renderOverfitRisk` | 同上,lite SVG + 绿黄红 itemColor 分段 |
| 数据源 | `app.js:2083 fetchJSON(dataUrl("overfit_monitor.json"))` | 单一 promise 共享(L2080 `_overfitMonitorPromise`),监控卡主图 + 首页枯竭 chip(L2792)**无双拉** |
| 触发时机 | L2344-2353 | `await loadEcharts()` → `await _fetchOverfitMonitor()` → `syncOverfitCharts()`,卡片挂载后异步执行一次 |

### 2.2 网络段实测(线上 ss.fx8.store,curl 实测)
| 测量 | 命令要点 | 结果 |
|---|---|---|
| 无压缩视角 | `curl -s -o /dev/null -w` | `http=200 size=27,843,084B(27.8MB) TTFB=0.78s total=5.38s` |
| 浏览器视角(br) | 加 `-H "Accept-Encoding: gzip, deflate, br"` | `size=1,520,547B(1.52MB) TTFB=0.97s total=2.98s` |
| 响应头 | `curl -D -` | `content-length: 27843084`、**`cache-control: no-store, max-age=0`**、`etag: "6fed..."` |
| 条件请求 304? | 带 `If-None-Match: <etag>` 再请求 | **仍 `200` 全量 27.8MB,total=11.38s**(no-store 下协商缓存完全失效) |
| 备站 sss/s.sugas.site | 同测 | 均 404(备站本地无此文件,前端 fetchJSON 自动重写主站 `/data/`,同吃 27.8MB) |

### 2.3 no-store 的来源(为什么"每次都慢")
- `worker/headers.js:168`:正则把 `overfit_monitor.json` 与 overview/intraday_snapshot 等并列 **NO_CACHE(ttl=0)**;L191 `cc = 'no-store, max-age=0'`。
- 注释自述(L165-167):2026-08-16 补入,理由=「重跑后立即看」+「MED 600s 会被 CF 拉长成 4h edge 残留」。**当时该文件 <1MB**(upload_r2.py L817 注释「<1MB 但需走 R2」),no-store 代价可接受;T3-2(v1.1.5,commit 1562165cb/44d383620)给它加了 `by_k`×4 + `filtered_by_k`×4 八个 bank 后膨胀到 27.8MB,no-store 代价变成每次全量 27.8MB。
- 该文件实际更新频率:**盘后 21:40 每日打点一次**(卡内空态文案与 help 弹窗均自述「盘后 21:40 打点生成」),不是盘中高频文件,与 overview(盘中实时)性质不同。

### 2.4 文件体积解剖(27.8MB 都是什么)
对线上文件做 JSON 结构级体积分解(compact 序列化口径):
| 块 | 体积 | 默认首屏渲染是否消费 |
|---|---|---|
| `by_k`(K1-K4 四 bank) | 4.1MB(38%) | 否,仅切 K 档按钮才读(app.js:2201) |
| `filtered_by_k`(K1-K4) | 4.2MB(38%) | 否,降亏开+切 K 档才读(app.js:2199) |
| `filtered` | 1.3MB(12%) | 降亏开+无K档时读(app.js:2204,默认路径用它) |
| `accuracy.rolling` | 0.9MB(8%) | **是**(准确率图) |
| `overfit.daily_by_win/daily_by_dim` | 0.4MB(3%) | **是**(风险分图) |
| 其他(config/alerts/daily 等) | ~0 | 否 |
- **格式化浪费**:文件由 `scripts/overfit_monitor.py:1669/1703` 以 `json.dump(..., ensure_ascii=False, indent=2)` 落盘;同数据 compact 化实测 **26.6MB→9.7MB(-64%)**,compact+gzip 仅 1.14MB。即 27.8MB 里约 17MB 是缩进空格。
- 注意:T3-2 后端已加 `recent` 明细块(RECENT_DAYS=340 天逐信号行,`scripts/overfit_monitor.py:450,627`),**线上当前数据(2026-08-21 21:40,v2)尚无 recent 键**——recent 数据上线后文件还会再涨(估数 MB),当前慢度是下限不是上限。

### 2.5 CPU 段实测(playwright + node,排除渲染嫌疑)
本地 `python3 -m http.server` serve static-site + playwright-core(chrome-headless)打点:
| 段 | 实测 | 说明 |
|---|---|---|
| 本地全链路(goto→两图 SVG 出齐) | **596ms** | 其中 fetch 129ms(disk)、body read ~95ms、JSON.parse **104ms** |
| 卡内按钮切换重绘(聚合+SVG 重建) | click 同步段 **7.1ms** | SVG 节点数 acc 41~51 / risk 50,量级极小 |
| 组集聚合 `_ovAggregateRecent`(T3-2,recent 上线后每图重绘都会跑) | 合成 68,000 行实测 **~14ms**(JIT 热) | `_ovRolling` 双重循环 O(10pathKey×5窗口×340天×窗口宽),量级可忽略 |
- 结论:**echarts 重复 init 不 dispose、动画开销、SVG 绘制、组集聚合全部排除**——lite 引擎每次重建但只有几十个节点;`charts.push(inst)` fallback 路径在 charts.lightweight=true(默认)下不走。
- 对照同类图(恐贪/A股情绪分/KPI sparkline):同款 `_lwSetup` 引擎秒开,差异只在数据源——它们的数据在 boot.json(1.1MB)/overview.json(495KB)里随主请求带出,而 AI 监控卡独享一个 27.8MB 且 no-store 的大文件。

### 2.6 附带隐患(顺带发现)
- `fetchJSON(url)` 默认超时 **15s**(app.js:6977 附近,sim 弹窗 64MB 场景特意传 60000 先例);本次实测出现过单次 11.4s——弱网/无 br 压缩环境下 27.8MB 极易撞 15s 超时,届时卡片显示「监控数据加载失败」,用户感知为"又慢又失败"。

## 三、慢度归因排序(数据说话)
| 排名 | 环节 | 耗时贡献(线上实测推算) | 占比 |
|---|---|---|---|
| 1 | 网络:27.8MB no-store 每次全量拉(TTFB~1s + br 传输 ~2s+) | ~3s(实测 2.8~11.4s 波动) | **>85%** |
| 2 | CPU:V8 JSON.parse 27.8MB | ~100-200ms | ~5% |
| 3 | CPU:组集聚合(recent 上线后)+SVG 渲染 | ~20ms | <1% |
| — | 渲染引擎本身(lite SVG) | ~7ms | 忽略 |

## 四、优化方案(§5 默认准则:一步到位终极合集,按收益排序)

### A. 数据瘦身:去 indent=2 改 compact【1 行改动,立收 -64%】
- 改 `scripts/overfit_monitor.py:1669/1703`:`json.dump(out, f, ensure_ascii=False, separators=(',',':'))`。
- 收益:27.8→9.7MB;br 传输 1.52→约 1.1MB;parse 字节数同步 -64%(parse ~104ms→~35ms)。
- 影响面:纯序列化格式,字段/数值零变化,前端零改动。动数据产物 → §22 三步(重跑 overfit_monitor → static-site/data → R2 上传)。
- §23.7:不触功能语义。

### B. 数据拆分:核心曲线与扩展 bank 分家【根治,首屏 -95%】
- 现状 77% 体积(by_k/filtered_by_k 8.3MB)只有用户**点了 K 档按钮**才会读;`filtered` 仅降亏开无 K 档时读;T3-2 的 `recent` 只有非 p8 模式组集用。
- 拆法:①`overfit_monitor.json` 只留 `generated_at/version/config/accuracy/overfit`(≈1.3MB,br 后约 300KB)——默认首屏(NEW14 默认模式下走组集或 raw bank 的 total 曲线)够用;②`by_k/filtered_by_k/filtered/recent` 拆到 `overfit_monitor_ext.json`(或 recent 单拆),前端在用户首次切 K 档/切模式时**按需再拉**(复用 `_fetchOverfitMonitor` 单 promise 模式加第二把 promise)。
- 收益:首屏 fetch 体积 27.8MB→1.3MB(**-95%**),叠加 A 后 br 传输约 300KB,TTFB+传输预计 <800ms;二次交互(切 K)多一次 ~1MB 拉取,用户无感。
- 影响面:前端 app.js `_ovBank` 取 bank 处需异步补拉(改动集中在 L2183-2205 + L2346 一处);后端 overfit_monitor.py 输出两个文件。动数据产物结构 → §22 三步 + 校验脚本(check_overfit_recent_parity.mjs 输入路径要跟着改)+ R2 上传清单(upload_r2.py 补 ext 文件的 _OVERFIT_FORCE 式强制上传)。
- §23.6/§23.7:读 bank 不自算的边界不变,曲线数字逐位不变,纯加载方式变化。

### C. 缓存分层纠偏:no-store → MED/LOW 层 + 上传后主动 purge【消掉"每次都拉"】
- 现状根因见 §2.3。改 `worker/headers.js:168` 正则把 `overfit_monitor` 从 NO_CACHE 移出(建议落 MED_FREQ 600s 或单独 3600s 档),配合 upload_r2.py 上传后调 `/api/purge-cache`(worker L241/L275 端点已在,purge 联动机制已有先例 L521-522)。
- 「重跑立即看」如何保:purge 在上传完成后自动调,边缘立即失效,不存在旧版残留窗口;比 no-store 每次回源更稳(当年 4h 残留事故的真正根因是 purge 缺失,现 purge 链路已补齐)。
- 收益:刷新页面时浏览器 HTTP 缓存(max-age 内)直接命中零下载;max-age 过期后走 CF edge 命中(~50ms),不再每次回源+全量传输。
- 影响面:worker 一处正则+upload_r2 purge 调用;需回归验证「重跑→上传→purge→刷新立即见新数据」链路(memory edge-cache-ttl-stretch-no-cache 的场景)。

### D. 防超时兜底【1 行】
- `_appendOverfitCard` 内 `await _fetchOverfitMonitor()` 链路的 fetchJSON 传 `timeoutMs=60000`(对齐 sim 弹窗 64MB 先例),防弱网 15s abort 报"加载失败"。若做了 B,此项可选。

### E.(可选,小收益)lite 模式下不必 await loadEcharts
- `app.js:2344` `await loadEcharts()` 与 fetch 串行;charts.lightweight=true(默认)时不依赖 echarts,可改为并行触发(fetch 不等 echarts)。冷缓存省 echarts.min.js(615KB)的串行等待。收益视网络几百 ms,优先级低。

### 推荐组合
**A+B+C(+D 兜底)一步到位**:A 是一行白捡;B 是根治(首屏只传渲染消费的 1.3MB);C 消掉"每次都全量拉"的机制性浪费并保住重跑即时可见;D 防弱网报错。预期效果:**AI 监控卡两图从"每次打开等 3~11 秒"变为"刷新秒开(<1s),max-age 内零网络请求"**;CPU 段(parse+聚合+渲染)合计 <150ms,不再是感知项。
- 若求最小改动先止血:只做 A+C(不动前端),27.8→9.7MB+缓存命中,也能从"每次 3s+"降到"首次 ~1.5s、后续近乎 0";但 B 不做的话,文件仍会随 recent 上线继续膨胀,治标不治本。

## 五、§22/规范联动提示(实施时)
- 动 overfit_monitor.json 产物(A/B)→ §22 三步:重跑脚本 → static-site/data → upload_r2(R2)+ 主站 curl 验新字段/新体积;
- B 改产物结构 → 同步 check_overfit_recent_parity.mjs、upload_r2 强制上传清单、§21 公示如有涉及加载方式的描述需核对(曲线口径不变);
- C 动 worker 缓存策略 → 回归「重跑→上传→purge→立即见新」+ 备站跨域 ACAO 头(memory:旧缓存缺 ACAO 备站挂);

## 六、复现
```bash
# 1) 线上体积与缓存头(no-store 证据)
curl -s -D - -o /dev/null https://ss.fx8.store/data/overfit_monitor.json --max-time 30 | grep -iE "content-length|cache-control|etag"
# 2) 浏览器视角(br 压缩)耗时
curl -s -o /dev/null -H "Accept-Encoding: gzip, deflate, br" -w "size=%{size_download} total=%{time_total}s\n" https://ss.fx8.store/data/overfit_monitor.json
# 3) 条件请求仍全量(negociation 失效证据)
ETAG=$(curl -s -D - -o /dev/null https://ss.fx8.store/data/overfit_monitor.json | grep -i ^etag | tr -d '\r' | cut -d' ' -f2)
curl -s -o /dev/null -H "If-None-Match: $ETAG" -w "http=%{http_code} size=%{size_download}\n" https://ss.fx8.store/data/overfit_monitor.json
# 4) 体积解剖(indent 膨胀证据)
python3 -c "import json;d=json.load(open('static-site/data/overfit_monitor.json'));print(len(json.dumps(d,ensure_ascii=False,indent=2).encode())/1048576,len(json.dumps(d,ensure_ascii=False,separators=(',',':')).encode())/1048576)"
# 5) 本地渲染全程打点(playwright):cd static-site && python3 -m http.server 8765 &
#    脚本:/tmp/aimon-test/test.js(playwright-core + chrome for testing,输出 fetch/parse/SVG 出齐各段 ms)
# 6) 组集聚合 CPU:/tmp/aimon-test/agg.js(node 直跑,合成 68000 行 recent)
# 数据版本:线上 generated_at=2026-08-21 21:40 version=v2(尚无 recent 键);关键口径:准确率/风险分曲线数据=后端预聚合 rolling/daily bank,前端只读 bank(recent 组集为 T3-2 新增路径,与 bank 曲线 parity 校验)
```
