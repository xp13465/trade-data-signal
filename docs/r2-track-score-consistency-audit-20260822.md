# R2 审计 P1 调研报告:track_score 跨文件不一致 + 百分位基线动态变化(pending-index #29)

- **生成时间**: 2026-08-22(调研执行 2026-08-21 深夜)
- **调研人**: researcher agent(只读调研,未改任何业务代码/数据)
- **触发**: pending-features-index #29(出处 docs/r2-migration-implementation-report.md §2.1问题4/§3.2/§6.2)
- **数据截止**: 2026-08-21 盘后产物(export manifest written_at=2026-08-21 21:58:47,本地 static-site/data/ 与线上 R2 已验证一致)

## 一、结论摘要(3 句)

1. **#29 描述的现象仍在,但形态已变**:8/9 报告时点的"board_etf_map=30.2 / index_detail=30.2 / overview=30.9 + match_method 不同",当前(8/21 盘后)已演化为"board_etf_map=25.1 vs index_detail=25.0(match_method 三处一致)";overview 经 P0 修复(必更白名单)后已不再落后,当前落后的展示位是 index/{id}-all.json(滞后 1-2 天的 map 快照)。
2. **根因一句话**:track_score 只在 build_board_etf_map.py 一处计算,三产物都是它的快照;export.py 增量门控的 index/{id}-all.json 依赖表清单不含 board_etf_map,导致 map 更新后 index 详情被"源数据未变化"误判跳过,停留旧版快照(58.5% pair 数值不一致)。
3. **百分位基线是每次运行动态收集的**(全体候选 pair 排序),候选集变化/ETF 跨 n=30、60 阈值/每日窗口滚动都会让全群体分数重排——这是设计内行为(相对排名口径),但叠加时序不同步后,用户会在两个页面看到同一 ETF 差 1~20 分。

## 二、全景量化(2026-08-21 盘后,本地=线上 R2)

### 2.1 产物规模

| 产物 | 规模 | track_score 来源 |
|---|---|---|
| board_etf_map.json | 147 指数 / 1412 pair | 唯一计算源(build_board_etf_map.py) |
| index/{id}-all.json(167 文件) | 1412 pair | map 快照(queries.etf_for 读 data/board_etf_map.json) |
| overview.json | 376 pair(signals_today[].etfs[]) | map 快照(同上) |

board_etf_map 内 match_method 分布:track_index 1145 / holdings_overlap 100 / sum_pct 95 / overlap 35 / kw_global 24 / kw 13。
track_tier 分布:strong 187 / related 318 / approx 181 / none 314 / None(灰灭)412。

### 2.2 三方逐 pair 对比

| 对比组 | 交集 | 双方有分 | 一致 | 不一致 | 不一致分差分布 |
|---|---|---|---|---|---|
| map vs index detail | 1412 | 1319 | 586(44.4%) | **733(55.6%)** | (0,0.5] 605 /(0.5,1.5] 98 /(1.5,3] 25 / >3 共 5 |
| overview vs map | 376 | 350 | 350(100%) | 0 | —(26 对双方同 None) |
| overview vs index detail | 376 | 350 | 158 | 192 | 同构于上(index 落后) |

- match_method:当前版本三处 **0 不一致**(8/9 报告时点的 match_method 不同是当时版本现象)。
- 双方同 None 93 对(一致地灰灭,非漂移)。
- track_n 差(map−index):**差 1 天 1281 对 / 差 2 天 11 对 / 差 0 天 120 对** → index 详情整体停留在 1-2 天前的 map 版本。

### 2.3 分差 >3 极端例(5 个)

| 指数/ETF | map(新版) | index detail(旧版) | 备注 |
|---|---|---|---|
| thsc_302035 / 588510 科创创业人工智能ETF华夏 | 21.5(n=60) | 1.4(n=59) | **n 跨 60 阈值**:降权分(sqrt(n/60) 折扣)→全 5 项百分位,跳变 20.1 分 |
| csi_931752 / 561030 工程机械ETF华泰柏瑞 | 62.5 | 70.8 | 基线滚动,旧版反而高 8.3 分 |
| sw_801880 / 516840 汽车ETF南方 | 25.8 | 33.0 | 差 7.2 分 |
| sw_801770 / 159511 通信ETF南方 | 41.1 | 37.8 | 差 3.3 分 |
| sw_801150 / 562600 医疗器械ETF华夏 | 48.4 | 45.2 | 差 3.2 分 |

### 2.4 159335 单例复核

| 产物 | track_score | match_method | track_n | similarity | 说明 |
|---|---|---|---|---|---|
| data/board_etf_map.json(后端源,mtime 8/21 21:58) | 25.1 | sum_pct | 188 | 0.842 | 与 static-site/data/ 双份逐字节一致 |
| static-site/data/index/thsc_300830-all.json(mtime 8/21 16:41) | 25.0 | sum_pct | 187 | 0.8483 | 停在当天 16:41 时点的 map 快照 |
| overview.json(8/21) | —(无) | — | — | — | thsc_300830 当日无信号,不在 signals_today |
| 线上 R2(data/board_etf_map + /r2/index/thsc_300830-all.json) | 25.1 / 25.0 | 同本地 | 同 | 同 | 本地=线上,无缓存不一致 |

#29 原文数字(30.2/30.9)是 8/9-8/10 报告写作时点的旧版数值,单例结构性结论不变:**同一 ETF 在 map 与 index 详情两个展示位分数不同**。

## 三、根因定位(file:line 证据)

### 3.1 生成链(唯一计算源 + 两路快照)

```
build_board_etf_map.py(唯一计算 track_score 处)
  └─写→ data/board_etf_map.json
deploy.sh 每次部署:
  L106  跑 build_board_etf_map.py 刷新 data/board_etf_map.json(新版)
  L121  cp data/board_etf_map.json static-site/data/(前端 R2 上传源,2026-08-18 项6 已同步)
  L131  export.py --incremental:
          overview.json → 必更白名单强制全量重算(export.py L989-990),读 data/ 新版 map
          index/{id}-all.json → 增量门控(export.py L1185-1199)
```

### 3.2 不一致直接根因:index 增量门控依赖表不含 board_etf_map

- `static-site/export.py L1187`: `idx_deps = ("index_daily", "score_daily", "signal_daily", "daily_metric")` — **不含 board_etf_map**。
- `static-site/export.py L1188-1193`: 4 表 MAX(date) 与上次 manifest 相同 → 跳过重导,复用旧 index/{id}-all.json(etfs 停留旧 map 快照)。
- `app/queries.py L218-222`: `_etf_map()` 带 `@lru_cache(maxsize=1)`,单次 export 进程内读一次 map 全程快照(单次运行内自洽;跨次运行漂移)。
- `app/queries.py L225-239`: `etf_for()` 读 map 透传 track_score(裁剪 4 项原始指标),overview 与 index detail 的 etfs 同源于此。

**8/21 当天实证(两次 export 时序)**:
- 16:41 export:index_daily 等 4 表当日已入库 → index/*.json 全量重导,读当时 map(V1:159335 n=187/score=25.0/sim=0.8483)。
- 21:58 deploy:build_board_etf_map 重跑(map 升 V2:n=188/25.1/sim=0.842)+ cp 同步;export --incremental 判 manifest 4 表 MAX(date) 仍=20260821(16:41 已就位)→ **index/*.json 全跳过停留 V1;overview 必更白名单强制重算用 V2**。
- 证据:`static-site/data/export_manifest.json` written_at=2026-08-21 21:58:47、tables 四表均 20260821;文件 mtime:index/thsc_300830-all.json=16:41:03,overview.json=21:58:27,data/board_etf_map.json=21:58:25。

### 3.3 历史现象("overview=30.9 vs map=30.2")的旧根因

r2-migration 报告 §2.1 问题4 记载:当时 board_etf_map 独立刷新、overview 读旧版快照(时序倒挂)。该方向已被 P0 方案修复(overview 进必更白名单 export.py L730-739 `MUST_RECOMPUTE`),**当前漂移方向反转:overview/map 新,index detail 旧**。

### 3.4 match_method 差异(8/9 时点)的解释

候选生成是"a+b+c+d+e 六来源合并去重"(board_etf_map.json _meta.match_method 字段自述;build_board_etf_map.py L1360-1365),match_method 标记该 ETF 对的入选来源。两次 build 之间来源层算法/候选变化(如 d36126194 加 e 层让 159335 以 sum_pct 入选量子科技)会改 match_method;且 IR 权重按 match_method 分层(build_board_etf_map.py L1166:track_index 用 TRACK_WEIGHTS IR15%,间接匹配用 TRACK_WEIGHTS_INDIRECT IR0%,权重定义 L934/L940)→ match_method 变化连带换权重表,放大分数跳变。当前版本三处 match_method 已一致(0 差异),此项已自然收敛。

## 四、影响面(§22 视角:用户在哪看到两个分数)

| 展示位 | 数据源 | 前端位置 |
|---|---|---|
| 首页信号卡 hover "跟踪分X" / AI 建议 top1 排序 | overview.json(signals_today[].etfs[],=当日 map) | app.js L2148(hover 文案)、L2225-2234 `_topEtfByScore`(纯 max(track_score),决定 AI 建议 top1)、L3351-3352(信号排序) |
| 指数走势图/详情弹窗 ETF 候选列表(跟踪分/信号灯) | `https://ss.fx8.store/r2/index/{id}-all.json`(滞后 1-2 天) | app.js L1399、L6999;lab.js L2544、L3503、L4966 |
| lab 凯利/交易模拟 K 档排序与 ETF 关系列 | 同上 index detail | lab.js L7360、L7591-7593(K 档 track_score DESC 排序)、L10781/L10855-10859(表格列) |

**典型用户场景**:首页某指数信号 hover 显示"跟踪分 25.1"(当日 map)→ 点进同指数走势图弹窗看到同一 ETF"跟踪分 25.0/旧分差更大"(滞后快照)→ 同屏两数。极端例(588510)两处差 20 分且信号灯档位可跨档(灰灭↔橙)。

排除项:etf_score_list_*.json、trade_sim(simulate_trade.py 只取 map 首位 code/name,不带 track_score)不含 track_score,无此问题。R2/CF 缓存层已验证本地=线上一致(本次不一致是产物生成层,非缓存层)。

## 五、百分位基线漂移(任务 4)

### 5.1 基线定义(动态,每次 build 重算)

`scripts/build_board_etf_map.py L1065-1081`:每次运行第一轮对**本次全部候选 pair**收集指标排序作基线——te/roll_std 只收 n>=60 的 pair;avg_dev/r2 收 n>=30 的 pair(L1065-1070 注释明示);`_pct_score` 在该排序里做百分位 rank(L1072-1081)。
当前基线样本量(8/21 map 实测):te/roll_std 基线=1271 对;avg_dev/r2 基线=1319 对;n<30=93 对。

### 5.2 什么条件下变(三个触发器)

1. **候选集变化**:新增/剔除任一 ETF 对 → 基线分布变 → 全群体分数重排。实测:d36126194(2026-08-09 09:41,"第5层来源 e(sum_pct)让159335进量子科技")后,516000 从 36.x 降到 32.1(降约 4 分,r2-migration 报告 §2.1 问题4 实测记录,非推演)。
2. **n 跨 30/60 阈值**:n>=60 才进 te/roll_std 基线且用全 5 项;30<=n<60 走降权分(composite×sqrt(n/60))。588510 实测:n=59→60 分数 1.4→21.5(跳 20.1 分,8/21 map vs 前日 index 详情对比)。
3. **每日窗口滚动**:track_n 每天+1,全部指标值(TE/R²/avg_dev/roll_std)随窗口重算 → 即使候选集不变,基线与全部分数每天自然微调(设计内:相对排名口径)。

### 5.3 漂移幅度量级

- 日常滚动:多数 pair 日间差 <=0.5 分(605/733),属噪声级;
- 候选集变化:个位数分数(实测约 4 分);
- 跨阈值/权重表切换(match_method 变):可达 20 分级(588510 实测)。
- 注:8/9 时点 match_method 变化叠加 IR 权重表切换(L1166),会进一步放大;当前三处 match_method 已一致,该放大器暂未触发。

## 六、修复选项对比(≥2 个,含推荐排序)

### 选项 A(推荐①,根治时序):index 增量门控纳入 board_etf_map 依赖

- **改动点**:export.py L1185-1199——manifest 增记 board_etf_map.json 的 md5(或 mtime),`_incremental_skip` 对 index 块加"map 变了就强制重导"判定;`_save_manifest`(L801-810)同步写。
- **影响面**:map 变化日 167 个 index 文件全量重导(本来交易日就重导,仅多覆盖"map 单独变"的场景);线上 index 详情分数同步到最新(与首页一致)。
- **成本**:小(单文件改动,半小时级+回归)。
- **风险**:低。不改任何算法口径,纯消除"同源不同步"。
- **§23.7 标注**:会让线上 index 页展示数字从旧值跳到最新值(方向=与首页对齐),属修复不一致而非改口径,**建议报备用户后实施**;严格论"动线上展示数字"需用户点头。
- **配套**:D(校验兜底)一起上。

### 选项 B(可选增强,需用户拍板+发版本):百分位基线固定化

- **改动点**:build_board_etf_map.py L1065-1081——基线分布快照固化到 data/track_score_baseline.json(定期如每月刷新),build 读快照而非当次收集;r2-migration 报告 P1 方案4 原文"工作量大可选"。
- **影响面**:新增 ETF 不再扰动全群体分数,分数日间稳定性大增(消除触发器 1/3 的重排;跨阈值跳变仍存在但可同步修);切换当天全站 track_score 一次性重排。
- **成本**:中(基线产物+刷新节奏+回滚口径设计)。
- **风险**:中。track_score 是 AI 建议 top-K 排序依据(app.js `_topEtfByScore`)→ 属"动 AI 推荐/过滤核心功能的数据层口径",**§23.7/§5.4⑥ 必须用户确认 + 发中间版本 + 同步 §21 公示(app.js L4043 算法说明同步改)**。
- **§23.7 标注**:**明确动线上数字,必须用户拍板**。

### 选项 C(纯标注,零数字变化):前端标注数据时点 + 说明基线口径

- **改动点**:app.js 指数详情弹窗 ETF 列表 hover 补"跟踪分截至 {ohlc 末日期}";app.js L4034 算法说明 modal 补一句"分数为全候选池相对百分位,每日随基线微调"。
- **影响面/风险**:零数字变化,纯文案;§21 公示同步顺手。
- **§23.7 标注**:不动数字,纯新增标注。

### 选项 D(推荐②,校验兜底):check_data_integrity 加三产物一致性抽样校验

- **改动点**:scripts/check_data_integrity.py 增校验项:抽 N 个 pair 比对 board_etf_map vs index detail 的 track_score/track_n,差超阈值(如 track_n 差>1 或分差>3)warn/fail(r2 报告 P2-2 已列此缺口)。
- **影响面/风险**:纯监控,不动数字;防选项 A 回归 + 防未来新增快照位再犯。

### 推荐排序

**A + D 打包先行**(根治时序+永久兜底,不动算法口径;A 的上线会让 index 页数字对齐首页,向用户报备即可)→ **C 顺手**(纯标注,提升可解释性)→ **B 单独决策**(动 track_score 口径=动 AI 排序依据,须用户拍板+发版本+公示;若用户在意"分数天天微变"的稳定性,B 是终极解,否则 A+D 已消除跨展示位不一致)。

## 七、已验证方法/数据源清单

- 本地产物:static-site/data/{board_etf_map,overview}.json、data/index/*-all.json(167 文件)、data/board_etf_map.json(后端源)、data/signal_kelly_etf_freeze.json(28120 条,无 159335)
- 线上:https://ss.fx8.store/data/board_etf_map.json、/data/overview.json、/r2/index/thsc_300830-all.json(本地=线上一致)
- 代码链:scripts/build_board_etf_map.py、scripts/deploy.sh、scripts/update_all.sh、static-site/export.py、app/queries.py、static-site/app.js、static-site/lab.js
- 历史:git d36126194(8/9 e 层上线 commit)、docs/r2-migration-implementation-report.md(8/9-8/10 审计原文)
- 未做(如实标注):未重跑 build_board_etf_map 验证基线重排幅度(只读约束,以 8/9 实测记录+8/21 双版本产物对比代替);未逐日回放历史基线漂移序列(数据产物已移出 git,历史版本仅 R2 当前版可查)。

## 复现

- **脚本**:本文对比逻辑为一次性只读统计(内联 python3,无独立脚本);核心对比代码段已在上文 2.2 表格量化,重跑命令如下。
- **输入依赖**:static-site/data/board_etf_map.json、static-site/data/overview.json、static-site/data/index/*-all.json、static-site/data/export_manifest.json、线上 R2 三文件。
- **重跑命令**(一行):
  ```bash
  python3 -c "
  import json,glob,os
  B='/Users/linhuichen/code/trade/static-site/data'
  bm=json.load(open(B+'/board_etf_map.json'))
  m={i:{e['code']:e for e in v} for i,v in bm.items() if i!='_meta' and isinstance(v,list)}
  ip={}
  for f in glob.glob(B+'/index/*-all.json'):
      d=json.load(open(f))
      for e in d.get('etfs',[]): ip[(os.path.basename(f)[:-9],e['code'])]=e
  diff=[(k,m[k[0]][k[1]]['track_score'],ip[k]['track_score']) for k in ip if k in m and m[k[0]][k[1]]['track_score'] is not None and ip[k]['track_score'] is not None]
  nd=[x for x in diff if abs(x[1]-x[2])>0.001]
  print('交集',len(diff),'不一致',len(nd),'最大差',max(abs(x[1]-x[2]) for x in diff))"
  ```
- **数据截止**:2026-08-21 盘后(export manifest written_at=2026-08-21 21:58:47;线上 R2 同版)。
- **关键口径一句话**:track_score=build_board_etf_map.py 每次运行对全体候选 pair 的 5 指标百分位加权(基线动态);三产物均为该 map 的快照,index/{id}-all.json 因增量门控依赖表不含 map 而滞后 1-2 天。
