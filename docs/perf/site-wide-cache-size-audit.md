# 全站「AI监控卡四件套」同类病灶扫描报告

日期:2026-08-24 | 角色:researcher(只读扫描)| 参照病例:`docs/perf/ai-monitor-chart-slow-research.md`
> 本报告由 researcher 产出、主控落档(2026-08-24)。数据版本:线上实测 2026-08-24(headers.js=HEAD 28314d030 无 diff;hold 线上 16396654B vs 本地镜像略旧;overfit_monitor 线上 generated_at=2026-08-21 v2 与病例一致)。

## 一、TL;DR

以三类病灶模式扫全站(worker/headers.js 缓存分层 × static-site/data+R2 体积普查 × scripts/*.py indent 全 grep × app.js 105 处/lab.js 24 处 fetch 点逐个对触发时机),**新确诊 6 个患者 + 病例本体 overfit_monitor 复核确认**。最大的新发现:①`industry-*-concepts.json` 32.2MB 拆分不彻底(indices 拆了、concepts 没拆,85% 是点开才用的历史序列);②`signal_kelly_trades.json` 64.5MB——全站最大文件且在 NO_CACHE 名单里 no-store;③`etf_score_list_hold.json` 16.4MB indent=2 白胖;④`etf_score_list.json` 主文件 18.4MB 是前端零消费的死产物仍每日生成+线上残留;⑤机制层实测证实 memory「edge TTL 被拉长到 14400」:worker 写 3600、线上实际返回 max-age=14400。

## 二、缓存分层全清单(worker/headers.js 实测核对)

| 层 | worker 写的 CC | 线上实测 | 覆盖文件 |
|---|---|---|---|
| NO_CACHE ttl=0 | no-store | ✅ 生效(no-store) | overview/intraday_snapshot/board_etf_map/daily_brief(+history)/signal_kelly_backtest/**signal_kelly_trades**/**overfit_monitor**/news_digest/signal_stats/signal_kelly_trades_parts/* (L168/L171) |
| HIGH 60s | max-age=60 | ⚠️ 实测命中 14400 旧头 | boot/notifications/summary/-1m~1y/futures/global-extras-all 等(L174-178) |
| MED 600s | max-age=600 | 同上风险 | signal_stats(已在 NO_CACHE)/futures_acc_*/fund_score_top/trade_sim_indices(L180) |
| 兜底 LOW 3600s | max-age=3600 | ⚠️ etf_score_list_hold 实测 **max-age=14400**(age=220,刚回源就是 14400) | 其余全部(L182) |
| /r2/ 代理 | max-age=3600(L143) | ⚠️ sh-all 实测 14400(cf HIT age=171) | lab/index/public_fund/trade_sim_data 直链 |

**14400 根因判定**:git 全史 headers.js 从无 `return 14400`(仅注释提及事故),worktree=HEAD 无 diff → 14400 非 worker 所写,是 CF 平台把 Cache API/edge 的 TTL 实际拉长到 4h 上限,与 memory `edge-cache-ttl-stretch-no-cache` 记载吻合。前端靠 `_NO_CACHE_URLS`(app.js:6924)给时效名单加 `?_=Date.now()` 绕浏览器缓存兜住;**不在名单的文件(etf_score_list_hold/buy/sell、industry-*-concepts、K线 -all、lab_*)浏览器侧最长 4h 强缓存**——对日更文件可接受,诚实标注。

## 三、病灶清单表(按 用户感知×收益 排序)

| # | 文件 | 线上体积 | 病灶类型 | 触发时机 | 预期收益 | 修复建议 | 优先级 |
|---|---|---|---|---|---|---|---|
| P1 | overfit_monitor.json | 27.8MB(no-store) | 1+2+3+D 三重(病例本体) | 首屏 fire-and-forget 自动拉,每次刷新 | 首屏 -95%(B),compact -63%(A),刷新秒开 | A+B+C+D(病例 §四) | ★★★★★ |
| P2 | industry-all-concepts.json(含 5y 15.6M/3y 10.0M) | **32.2MB**(all) | **3 全量拉·少量用** | 行业 tab 切 all/5y/3y 档即整包拉(app.js:22091 `_loadIndustryData`;默认 range=3m 不中招) | 切档首拉 32.2→约 2MB(-94%):85% 是 concepts[].data 历史序列(92概念×240KB),列表只用 name/stats;data 仅点开单概念画图用 | C:拆 concepts-meta + concepts/{id}-data 按 id 按需(照抄 industry-{range}-indices/ 已有拆分模式)+D timeoutMs | ★★★★☆ |
| P3 | etf_score_list_hold.json(buy 1.5M/sell 3.7M 同源) | **16.4MB** | **2 indent 白胖**+D | 点"持有"chip 懒加载(app.js:22865 _ensureHoldLoaded;lab.js:6403) | indent=2→compact 实测省 49%(15.6→7.9MB);传输 br 后再叠 parse/内存减半 | A:`export_etf_score_list.py:179` 去 indent(1行)+D timeoutMs=60000;二级候选:hold_list 详情字段(ohlc/dims/history_analogy)与列表字段分家 | ★★★★☆ |
| P4 | trade_sim_data/{index}_full.json | 最大 cgb_idx **20.2MB**(实测 7.4s) | D+3 边缘 | 点模拟交易弹窗切视图(app.js:26056,fetchJSON 裸调无 timeoutMs) | 弱网不炸;cgb_idx 可切片或降采样 | D:timeoutMs=60000;长期:>5MB full 分片 | ★★★☆☆ |
| P5 | signal_kelly_trades.json | **64.5MB**(no-store,全站最大) | 1(NO_CACHE 大文件)+D 联动 | 正常路径已走 parts 分片;**分片任一失败回退此文件后常驻**(_simFullFallback,app.js:3222) | 一旦进兜底=每次开弹窗全量 64.5MB 回源 | C:兜底改造为"逐年片补齐"替代全量回退;短期至少把全量文件从"每次 no-store 回源"改为可 edge 缓存+purge(点击触发场景 stale 风险低) | ★★★☆☆ |
| P6 | boot.json | 2.34MB(HIGH 60s+前端 ?_bust=每次刷新真拉) | 3 变体(盘中白拉) | 首屏必拉(app.js:7159 fetchBoot) | 盘中约半数体积作废:overview 占 41% 但 date 过期被设计性弃用(L7169-7174)→renderOverview 再单独拉 overview.json 双份;intraday_snapshot 10% 可能被覆盖 | B:export_boot 盘中不含过期 overview/intraday(或 boot 瘦身只留 config+signal_stats+summary) | ★★☆☆☆ |
| P7 | etf_score_list.json(主文件) | 线上 18.4MB 残留 | 附带:死产物 | **前端零消费者**(grep 全 js 仅注释;upload_r2.py:750 自述已拆 3 分件,glob 只传 `etf_score_list_*.json`) | 每日停写 18MB+删 R2 旧件(存储/上传时间) | export_etf_score_list.py 停写主文件+R2 清理(§22 对称校验确认无人引用后再删) | ★★☆☆☆ |
| P8 | lab_sim_{index}[_fusion]_full.json ×13 | 单个最大 8.1MB,共 ~80MB | D 轻 | lab 明细视图按需(lab.js:1682/1823 fetchJSONProgress 带 onProgress+abort,**无超时**) | 有进度条+手动 abort,弱网挂起可自救 | 低成本:补 timeout;不动结构 | ★★☆☆☆ |
| P9 | public_fund_industry_fund_map.json | 6.5MB | D 轻 | 点击行业弹窗才拉(app.js:19238 注释明确按需)✓懒加载合理 | 弱网防炸 | D:timeoutMs=60000(顺手) | ★☆☆☆☆ |
| P10(机制) | CF edge TTL 拉长 14400 | — | 机制层认知 | 所有非 NO_CACHE 文件 | 无码可改;认知同步+对时效敏感新增文件一律走 NO_CACHE 或 purge 链 | 落档即可(memory 已有,本次实测再次印证) | ★☆☆☆☆ |

## 四、「确认无病」名单(扫过没病+理由,防漏检质疑)

| 文件/组 | 体积 | 为什么没病 |
|---|---|---|
| overview.json/intraday_snapshot.json/board_etf_map.json | 507K/124K/589K | no-store 合理(§22 一致性核心),体积小回源代价低 |
| daily_brief(.json/_history)/news_digest/signal_stats | 8.6K/19.7K/431K | no-store 但小,"重跑立即看"语义正确;signal_stats 首屏走 boot 分发复用不双拉(app.js:12698-12703 设计确认) |
| signal_kelly_backtest.json | 462KB | 弹窗 cfg 每次开都拉(no-store),462KB 可接受;中低优化可选挪 MED+purge |
| signal_kelly_trades_parts/recent.json+tYYYY.json | 2.7K/14.7M | 开弹窗只拉 recent 秒开、提交才按需补年片+模块缓存(_simEnsureRange L3290)——**真按需,分片设计合格**;60000ms 超时已有(app.js:3209) |
| K线大range a-stock-all 7.1M/hk-all 4.8M/global-all 5.3M/sentiment-all 4.4M | 见左 | 周期切"全部"档/s.*信号弹窗才拉(dataUrl 动态拼,app.js:8417/17327/17474/17579),按需合理;cache mode no-cache 条件请求 ✓;弱网 15s 边缘但非默认链路 |
| index/{id}-all.json(lab 切指数) | ≤1.3MB | 在前端时效名单(?_bust)每次真拉但单文件小,edge HIT 快 |
| industry-{3m,6m,1y}.json 小 range | 2.5M/3.9M/6.6M | 默认档 3m 走 60s 层,行业 tab 默认路径 OK(1y 6.6MB 切档拉,同 P2 病灶家族但量级次之,P2 修复时一并覆盖) |
| global-extras-all.json | 1.35MB | KPI 弹窗按需(8598/8164) |
| export.py 系全部产物(K线/boot/concepts/index-all/parts/trades) | — | compact separators ✓(export.py:827,signal_kelly_backtest.py:1374/1281)——indent 病灶只在 overfit_monitor.py 与 export_etf_score_list.py 两处 |
| kelly_loss_features.json | 1.1MB | 已 compact(实测 0% 可省);点击触发+60000 超时 ✓(app.js:3049) |
| lab stats 类 | ≤338KB | 进 tab 才拉,小 |
| static-site/data/trade_sim/(371MB 本地 json) | 371MB 本地 | 上传链只传 static-site/trade_sim_*.html 到 trade_sim/ 前缀(upload_r2.py:477-491);R2 用的是 trade_sim_data/ 新前缀——本地 371MB 是磁盘堆积不上线,建议另行清理(不入本表病灶) |
| indent 其余 24 脚本 | 均 <100KB 或写本地 data/ 不上线(gen_daily_brief 用 indent=1 且产物 8.6KB) | 逐一核对过输出路径 |

## 五、推荐修复批次划分

- **批次 1(打包一个小批,纯序列化 1-2 行+超时常数,不动结构)**:P3-A(hold/buy/sell 去 indent)+P1-A(overfit 去 indent,若病例方案未单独派)+P4/P8/P9-D(timeoutMs=60000 批量补)。动数据产物→重跑+§22 三步(static-site/data→R2→curl 验)。
- **批次 2(独立任务,动数据产物结构+前端)**:P2-C(industry-concepts meta/data 拆分,照抄 -indices/ 拆分模式;顺带评估 1y 档);P1-B(overfit ext 拆分,病例方案 B)。各含 §21 公示核对+对称校验脚本输入路径联动。
- **批次 3(独立任务,行为层)**:P5(signal_kelly_trades 兜底改造:逐年片补齐替代 64.5MB 全量回退);P6(boot 盘中瘦身);P7(死产物停写+R2 清理,先跑引用核查再删)。
- **批次 4(零码)**:P10 认知落档——新增"重跑立即看"文件一律 NO_CACHE+purge,不做 MED 600 幻觉依赖。

## 六、复现

```bash
# 1) 缓存分层实测(主站带 UA)
UA="Mozilla/5.0 Chrome/126"
for f in overfit_monitor.json signal_kelly_trades.json etf_score_list_hold.json daily_brief.json; do
  curl -s -D - -o /dev/null -A "$UA" --max-time 30 "https://ss.fx8.store/data/$f" | grep -iE "^cache-control|^content-length"; echo "<- $f"; done
# 2) edge TTL 拉长证据(worker 写 3600,线上返回 14400)
curl -s -D - -o /dev/null -A "$UA" "https://ss.fx8.store/data/etf_score_list_hold.json" | grep -iE "cf-cache-status|age|cache-control"
# 3) R2 大类体积(concepts/full/cgb_idx)
for u in r2/industry/industry-all-concepts.json r2/lab/lab_sim_sz_fusion_full.json r2/trade_sim_data/trade_sim_cgb_idx_full.json; do
  curl -s -o /dev/null -A "$UA" --max-time 40 -w "%{http_code} %{size_download}B %{time_total}s $u\n" "https://ss.fx8.store/$u"; done
# 4) indent 白胖量化(compact 对比)
python3 -c "
import json,os
for p in ['static-site/data/etf_score_list_hold.json','static-site/data/overfit_monitor.json','static-site/data/industry-all-concepts.json']:
    raw=os.path.getsize(p); d=json.load(open(p))
    comp=len(json.dumps(d,ensure_ascii=False,separators=(',',':')).encode())
    print(p.split('/')[-1], f'raw={raw/1048576:.1f}MB compact={comp/1048576:.1f}MB 省={(raw-comp)*100//raw}%')"
# 5) concepts 体积构成(85%=data 序列)
python3 - <<'EOF'
import json
d=json.load(open('static-site/data/industry-all-concepts.json'))['concepts']
sz=lambda o: len(json.dumps(o,ensure_ascii=False).encode())
agg={}
for v in d.values():
    for k,vv in v.items(): agg[k]=agg.get(k,0)+sz(vv)
print({k:f'{v/1048576:.1f}MB' for k,v in sorted(agg.items(),key=lambda x:-x[1])})
EOF
# 6) 前端 fetch 点普查
grep -on 'fetchJSON("[^"]*"' static-site/app.js | sort | uniq -c | sort -rn | head -45
grep -n "_loadIndustryData\|_ensureHoldLoaded\|_simLoadFull\|_tradeSimFetchFull" static-site/app.js | head
```

关键口径:病灶类型 1=缓存策略与体积失配、2=indent 白胖、3=全量拉·少量用、D=15s 默认超时隐患;传输体积收益以 compact 化前的原始字节计(CF br 下传输收益缩水,parse/R2 存储/回源带宽收益全额成立,诚实标注)。
