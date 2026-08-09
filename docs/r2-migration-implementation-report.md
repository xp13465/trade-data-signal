# R2 迁移合并版实施/回归报告

> **文档定位**: R2 数据层迁移的完整实施记录 + 一致性问题修复 + 端到端审计结论 + 方案A上线 + 回归检查 + 后续待办合并版。供后续校对排查用(§7 落档铁律)。
>
> **生成时间**: 2026-08-09
> **信息来源**: NOTES.md §48 小节BA/BB + TASKS.md 会话状态 + 8个agent进度文件 + git log + memory(r2-migration-complete/backup-architecture-4-layers)

---

## 1. R2 迁移架构

### 1.1 五阶段完成(2026-08-08 全部上线 main)

| 阶段 | commit | 内容 | reviewer |
|------|--------|------|----------|
| 1a/1b | `df6597245` | R2双写: deploy.sh 末尾跑 upload-all-data(全量JSON); intraday_snapshot.sh 加 upload-intraday(每10min盘中快照) | PASS(2非阻断建议: upload-intraday失败告警/boot.json冗余) |
| 2 | `8a36b4b82` (含 `3b56bcb04`) | Worker /data/*.json -> R2 rewrite(dataRewriteHandler) + /api/purge-cache + 分层TTL(60s/600s/3600s) + upload_r2.py purge_cache + PURGE_SECRET wrangler secret | PASS(1个P1: overview/intraday no-store回退60s设计意图变化可接受; 1个P2: max-age=14400 CF edge header误导) |
| 3 | `508eabb44` | 定时任务去 git push 数据改 R2 上传 + purge_cache + notify告警。deploy.sh DATA_FILES只留 minJS/CSS+feed.xml; intraday_snapshot.sh 去 git push 改 upload-intraday | PASS(4个P2: update_lab无notify/gold_night缺--dedup-key/deploy.sh checkout死代码/intraday schedule_stats无notify) |
| 4a | `3f721f2d8` | static-site/data/ 移出 git(.gitignore catch-all `static-site/data/*` + `!feed.xml`, git rm --cached 266文件保留feed.xml)。R2唯一数据来源 | PASS(3个P2: 死代码/daily_metric 404/checkout静默失败) |
| 5 | `8bfc55e8d` | staticdata git 差异化日志备份(best-effort rsync DB到本地db/不进git + 配置 + 小JSON + commit+push staticdata) | PASS |

**核心成果**: git代码/R2数据解耦完成。static-site/data/ 移出git走R2唯一数据来源,定时任务去git push改R2上传+purge_cache,staticdata git记录差异。

### 1.2 灾备4层分工架构

| 层 | 存储 | 用途 | 内容 |
|----|------|------|------|
| ① trade git | `git@github.com:xp13465/trade-data-signal.git` | 代码 | app/scripts/static-site源码,不含data/ |
| ② staticdata git | `git@github.com:xp13465/trade-data-signal-staticdata.git` | 差异日志 | DB原件(3个不压缩)+配置(.env.example/wrangler/launchd plist不含密钥)+小JSON(脚本生成小文件git diff追踪)。每次deploy后commit+push |
| ③ R2 signal-backup(私有桶) | R2 | 备份快照(全量恢复) | DB等重要文件gz,分层 backup/30 + weekly/28 + monthly/365。upload_r2.py upload-db 推 |
| ④ R2 signal-data(公开桶) | `ssd.fx8.store` | 线上静态资源分发 | 前端fetch的所有线上静态资源(小JSON+大文件index/industry/lab/trade_sim) |

**脚本生成文件去向规则**: 小文件 -> staticdata git(差异日志) + R2公开桶(分发)两处; 大文件 -> 只R2公开桶(不进staticdata,体量大git不适合)。

**互补不重复**: staticdata看变化历史(git diff),signal-backup恢复全量(解压快照),R2公开桶线上分发。

### 1.3 数据类别走R2 vs CF Workers Static Assets

按数据类别(非按单文件大小)判断(§8.1):

**走R2的类别(满足任一)**:
- 全量品种多(100+ index / 31 industry / 100+ trade_sim / 1000+ public_fund)
- 有大range历史序列(`-all/-5y/-3y` 单文件 >1MB)
- 类别整体大(index 48M / industry 54M / trade_sim 268M / lab 109M)

**走CF Workers Static Assets的小文件**: 单文件 <100KB 且类别总量 <5MB 的状态/监控小文件(alert.json / daily_metric.json / schedule_stats.json / alert_analyze_*.json 等)。

**upload_r2.py 命令清单(10个)**:
upload-lab / upload-trade-sim / upload-trade-sim-json / upload-index / upload-industry / upload-public-fund / upload-offshore-fund / upload-etf-score / upload-data-large(>=1MB兜底) / upload-all-data / upload-intraday / upload-data-files

**前端 dataUrl R2 fallback**: 大range历史序列 `-(all|5y|3y).json$` 走R2 `data/` 前缀; 其他R2类别(industry/index/trade_sim/public_fund)用硬编码 `https://ssd.fx8.store/{prefix}/` URL。

---

## 2. R2 一致性5问题 + P0根治

### 2.1 五大系统性问题(R2迁移2天数据口径不一致根因)

调研agent进度文件: `/tmp/agent-progress-r2-consistency.md`

**问题1(核心,致43/36.4旧版残留): PURGE_SECRET手动部署丢失 + CF edge cache不清**
- 11:10 deploy(agent手动跑): PURGE_SECRET 未设,7次 purge_cache 全跳过
- 05:00 deploy(launchd): PURGE_SECRET 有,purge 成功(purged:13)
- R2上传新数据但CF edge cache没清,前端读旧版(max-age=14400旧缓存,4h)
- 根因: 手动跑deploy.sh时 .env 加载路径与 launchd 不同,PURGE_SECRET 丢失

**问题2: dataRewriteHandler 的 no-store 失效 + edge cache 旧版 max-age 残留**
- R2迁移前 overview 走 CF Static Assets,CACHE_RULES 设 no-store(禁缓存)
- R2迁移后 overview 走 dataRewriteHandler(R2 rewrite),不走 CACHE_RULES,改设 max-age=60
- 但 edge cache 里残留旧版 response(max-age=14400),purge 不跑则4h旧版
- dataRewriteHandler 设的 max-age=60 只在新缓存生效,旧缓存不受影响

**问题3: R2上传与 edge cache purge 不同步(R2新版+edge旧版)**
- upload_r2.py 上传R2后调 purge_cache,但 purge 失败(PURGE_SECRET未设)则 edge 旧版
- dataRewriteHandler 先查 edge cache(HIT返旧版),不回源R2
- 即使R2有新版,前端读 edge 旧版

**问题4: overview vs board_etf_map 时序不同步 + track_score百分位基线动态**
- board_etf_map.json 独立刷新,overview 读旧版快照
- track_score 百分位基线全局动态(每次跑基线随候选ETF集合变化)
- `d36126194`(09:41) 加159335进量子科技,基线变,516000 从36.x降到32.1
- 非交易日 intraday 不跑,overview 不重算

**问题5: R2上传失败不阻断 + R2 200不回退ASSETS**
- deploy.sh R2失败只 warning 不阻断
- dataRewriteHandler R2 200不回退ASSETS(R2旧版残留时读旧版)
- 11:10 deploy 的 upload-data-large(overview) R2上传输出缺失,R2直链 overview 仍8/8 21:08旧版

### 2.2 根治方案(5层)

| 优先级 | 方案 | 内容 | 状态 |
|--------|------|------|------|
| **P0** | 方案2(worker) | dataRewriteHandler 高频文件(overview/intraday_snapshot/board_etf_map) ttl=0,跳过 cache.match+cache.put,设 no-store。即使 PURGE_SECRET 丢失/purge失败也不留旧版edge cache。代价:R2回源~50ms | ✅已实施上线 |
| **P0** | 方案1(PURGE_SECRET) | trade/.env += PURGE_SECRET(gitignored安全) + deploy.sh set -a source .env + 23个launchd plist加EnvironmentVariables PURGE_SECRET + upload_r2.py空时notify告警(不静默跳过) | ✅已实施上线 |
| P1 | 方案4 | board_etf_map 与 overview 同步: build_board_etf_map.py 刷新后自动触发 export_overview 重算; track_score百分位基线固定化(工作量大可选) | 待办 |
| P2 | 方案3 | R2上传失败阻断 + 版本校验: deploy.sh 关键文件R2上传失败则阻断push; dataRewriteHandler对关键文件加last-modified校验 | 待办 |
| P2 | 方案5 | edge cache purge 兜底: deploy.sh末尾统一调一次 purge_cache; 或Worker加定时清理; 或HIGH_FREQ文件edge cache TTL=5s | 待办 |

### 2.3 P0实施详情(commit `b6c019eaf`,push main `0339ee963`)

实施agent进度文件: `/tmp/agent-progress-r2-consistency-p0.md`
reviewer进度文件: `/tmp/agent-progress-r2-consistency-p0-reviewer.md`

#### 方案2: worker/headers.js 改动
- **dataCacheTtl**: 新增 NO_CACHE(ttl=0)档 = overview/intraday_snapshot/board_etf_map(从原60s拆出)
- **dataRewriteHandler**: 重构,ttl=0时 noEdgeCache=true -> 跳过 `caches.default.match`(不读旧版) + 跳过 `caches.default.put`(不写) + `Cache-Control: no-store,max-age=0`; 每次回源R2
- 即使 PURGE_SECRET 丢失/purge失败,HIGH_FREQ文件也不留旧版edge cache(根治4h旧版残留)
- grep验证: worker L148 `return 0`(overview/intraday_snapshot/board_etf_map); L166 `noEdgeCache=ttl===0`; L170 `if(!noEdgeCache)`跳match; L202 `if(response.status===200 && !noEdgeCache)`跳put; L167 `noEdgeCache?'no-store,max-age=0'`

#### 方案1: PURGE_SECRET 持久化
- **trade/.env** += PURGE_SECRET(gitignored安全; upload_r2 load_env L62硬编码读此作fallback,覆盖所有调用路径)
- **scripts/deploy.sh**: `set -a source $GIT_REPO/.env + $REPO/.env` 加载PURGE_SECRET到环境(手动跑不丢)
- **scripts/upload_r2.py**: purge_cache PURGE_SECRET空时调 notify.send 告警(进程内只告警一次防轰炸,不静默跳过)
- **23个 ~/Library/LaunchAgents/com.trade.*.plist** += EnvironmentVariables PURGE_SECRET(本地非git; plutil -lint全OK)
- 三处值一致(hash 657b77b6...)

### 2.4 P0上线状态

- commit `b6c019eaf` push feat -> reviewer PASS -> push main(含在 `0339ee963` 链中)
- **reviewer结论**: PASS(代码逻辑正确,无阻塞性问题,2个minor建议: CACHE_RULES rule 2.5死代码/cacheKey noEdgeCache时未使用)
- **线上验证**: worker no-store生效(board_etf_map/overview no-store); daily_metric.json仍走cache(低频文件,合理)
- check_data_integrity: 23 ok / 1 warn / 0 fail
- P0 smoke: live site 数据层正常

---

## 3. R2 端到端审计结论

审计agent进度文件: `/tmp/agent-progress-r2-audit.md`

审计5维度: ①数据产物生成链路完整性 ②前端fetch链路 ③多文件一致性 ④R2缓存策略 ⑤完整性校验覆盖

### 3.1 P0×2 已解决

| P0 | 问题 | 解决状态 |
|----|------|----------|
| P0-1 | index detail etfs级别缺 etf_since_return(index_detail不调 _enrich_etfs_since_return) | ✅ 已解决: commit `567be9b24` 走势卡ETF至今盈亏Layer2+3根治(后端注入etf_since_return+前端优先etfs读)。线上验证 etf_since_return=11.55 |
| P0-2 | trade_sim_indices.json 停在8/8 02:09(simulate_trade.py JSON模式无自动调度,update_lab.sh只跑--html模式) | ✅ 已解决: 方案A实施时重跑10个top1变化品种的 simulate_trade,trade_sim_indices 03:41新鲜 |

### 3.2 P1×3(待办)

1. **159335 track_score 跨文件不一致**: board_etf_map=30.2 / index_detail=30.2 / overview signal=30.9(不同match_method: sum_pct vs holdings_overlap)。非bug但需关注一致性
2. **simulate_trade.py JSON模式无自动调度**: update_lab.sh 只跑 --html 模式,trade_sim JSON需手动触发。建议加 launchd 定时或 deploy.sh pipeline
3. **track_score百分位基线全局动态变化**: 基线随候选ETF集合变化(如加159335进量子科技后516000从36.x降到32.1)。可选预计算基线集固定化(工作量大)

### 3.3 P2×4(待办)

1. **purge_cache失败无监控/告警**: upload_r2.py purge_cache 失败只 warning,无 notify 告警(P0方案1已加告警,但 deploy.sh 末尾统一purge未加)
2. **check_data_integrity.py 校验覆盖不足**: 不校验 track_score三版本一致性 / etf_since_return存在性 / R2产物一致性 / trade_sim_indices时效性
3. **_headers不生效**: `run_worker_first=true`,Worker接管所有请求,_headers的CSP/HSTS等由Worker代码设
4. **upload_r2.py不设R2对象Cache-Control metadata**: 由Worker代码设Cache-Control,upload_r2只传数据

### 3.4 审计关键发现(数据流链路)

- **board_etf_map.json 不走R2/CF**: 只在 data/ 后端读,export.py 读它生成 overview.json + index/{id}-all.json 的 track_score
- **track_score 冗余存储**: board_etf_map.json(data/后端读) -> export.py 读它生成 overview.json + index/{id}-all.json
- **Worker路由**: /r2/* -> r2ProxyHandler(R2直读+1h缓存); /data/*.json -> dataRewriteHandler(R2直读+分层TTL)
- **R2直链**: index/industry/public_fund/lab/trade_sim_data/ + data/(大range)
- **purge映射**: upload-all-data purge cache_prefix="/" 清/data/; upload-index/industry等 purge cache_prefix="/r2/" 清/r2/

---

## 4. 方案A上线(track_score IR权重按match_method分层)

### 4.1 算法改动

**文件**: `scripts/build_board_etf_map.py`

**改动内容**:
- 新增 `TRACK_WEIGHTS_INDIRECT`(L940) = `{te:0.36, r2:0.34, avg_dev:0.15, roll_std:0.15, ir:0.0}`
- n>=60 composite 按 match_method 分层(L1165-1166): `w = TRACK_WEIGHTS if match_method=="track_index" else TRACK_WEIGHTS_INDIRECT`
- **直接匹配(track_index)**: IR权重15%原样(TE30%/R²25%/IR15%/avg_dev15%/roll_std15%)
- **间接匹配(overlap/kw/holdings_overlap/sum_pct/kw_global/manual_fallback)**: IR权重0%,R²从25%升到34%,TE从30%升到36%(TE36%/R²34%/IR0%/avg_dev15%/roll_std15%)

**设计理由**: 间接匹配(持仓重叠/关键词/概念暴露度)的IR(信息比率)统计意义弱于直接跟踪指数的ETF,降IR权重到0%避免间接匹配ETF因IR偶然高值排名虚高。

### 4.2 §21 公示同步(commit `a21c28406`)

**文件**: `static-site/app.js` L2216-2222 + `static-site/app.min.js` + `static-site/index.html` + `static-site/sw.js`

- `_etfLightHelpHTML` b2块权重改双套说明: 直接(TE30%/R²25%/IR15%) vs 间接(TE36%/R²34%/IR0%)
- 归一化段加 match_method 分层原因说明("权重按匹配方式分层"/"间接匹配...IR权重0%")
- app.min.js 含全部关键字符串(直接30%/间接36%/权重按匹配方式分层/直接15%/间接0%) -- 用字符串验证非变量名(§9 min版JS验证规范)
- sw.js CACHE_VERSION a66 -> a67; index.html ?v= 版本号 bumped

### 4.3 board_etf_map data/ -> static-site/data/ 复制遗漏修复(§18教训)

**根因**: `build_board_etf_map.py` 写入 `ROOT/data/board_etf_map.json`(.absolute()非.resolve(),ROOT=trade-data),非 static-site/data/。export.py 不复制 board_etf_map.json 到 static-site/data/(grep无board_etf_map引用),data/->static-site/data/同步是独立步骤。

**问题**: 方案A agent 重跑 build_board_etf_map.py 生成新版(159586 top1),但未同步到 static-site/data/(两处static-site仍10:13旧版516630)。

**修复**: boardmap-rerun agent 手动 cp 到两处 static-site + upload-data-files(含自动purge)。

**验证(三处均=159586 计算机ETF南方 score=35.1 method=holdings_overlap)**:
1. local trade/static-site/data/board_etf_map.json -> top1=159586 ✓
2. R2 ssd.fx8.store/data/board_etf_map.json -> top1=159586 ✓
3. CF ss.fx8.store/data/board_etf_map.json -> top1=159586 ✓(purge后HIT age=9=新版缓存)

**§18教训落档**: 数据产物复制遗漏(data/->static-site/data/)+reviewer验数据需真读上线文件非源文件+agent自验+主控§0验三版本一致。

### 4.4 三版本一致性验证

实施agent进度文件: `/tmp/agent-progress-plana-implement.md`

- **thsc_300830(量子科技)**: 27只ETFs,top1=159586(35.1,holdings_overlap),516000=#3(31.5,非42.6旧版),159335 ret=2.33
- **三版本一致**: local board_etf_map = R2 index detail = R2 overview = 159586/35.1 ✓
- curl R2验证: ssd.fx8.store/index/thsc_300830-all.json 159586第一 ✓; ssd.fx8.store/data/overview.json 159586第一 ✓

### 4.5 全局影响: 10/138 概念 top1 变化

| 序号 | 指数 | 旧top1 | 新top1 |
|------|------|--------|--------|
| 1 | bj50(北证50) | None | 159543 |
| 2 | sw_801160 | 159301 | 560620 |
| 3 | thsc_309049(CPO) | 515050 | 510770 |
| 4 | thsc_307940(存储芯片) | 516350 | 589990 |
| 5 | thsc_300830(量子科技) | 516630 | 159586 |
| 6 | thsc_308300(MCU芯片) | 516350 | 562380 |
| 7 | thsc_308491(氢能源) | 159368 | 588830 |
| 8 | csi_000510(中证A500) | 563220 | 563360 |
| 9 | us_ndx(纳斯达克100) | 513390 | 159513 |
| 10 | us_ixic(纳指) | 159660 | 159501 |

### 4.6 上线commit链

| commit | 内容 |
|--------|------|
| `4ea283685` | feat: 方案A track_score IR权重按match_method分层(build_board_etf_map.py) |
| `a21c28406` | feat: §21 track_score公示文案同步方案A IR权重分层(app.js+app.min.js+sw.js+index.html) |
| `83a63fcca` | docs: CLAUDE.md §11 方向纠正(通知机制) |
| `b6c019eaf` | fix(r2): 高频文件不写edge cache + PURGE_SECRET持久化(R2一致性P0) |
| `0b8226604` | docs: §18 追加方案A board_etf_map数据产物遗漏+reviewer误报教训 |
| `0339ee963` | docs: §18 修正board_etf_map根因-data/->static-site/data/复制遗漏 |

以上全部在 origin/main 上(已验证)。

---

## 5. 回归检查

### 5.1 方案A reviewer(6维度 PASS)

reviewer进度文件: `/tmp/agent-progress-plana-reviewer.md`

| 维度 | 检查内容 | 结果 |
|------|----------|------|
| §21公示同步 | app.js双套权重公示(直接TE30%/R²25%/IR15% vs 间接TE36%/R²34%/IR0%); 值与TRACK_WEIGHTS_INDIRECT一致; app.min.js含关键字符串; sw.js a67; index.html ?v= bumped | PASS |
| 算法逻辑 | TRACK_WEIGHTS_INDIRECT L940 = {te:0.36,r2:0.34,avg_dev:0.15,roll_std:0.15,ir:0.0}; L1166 w分层; 直接=IR15%原样,间接=IR0%+R²34%+TE36% | PASS(MINOR: n<60分支用TRACK_WEIGHTS不分层,4概念0只ETF走n<60影响极低) |
| 数据校验 | check_data_integrity 23 ok/1 warn/0 fail; 三版本一致(local=R2 index detail=R2 overview=159586/35.1); CF=旧版(expected,未push main) | PASS |
| 全局影响 | 3概念抽查(thsc_309049/thsc_308300/us_ndx)合理; 无负收益异常排第一 | PASS |
| P0 smoke | P0-08 指数表现ETF: 5指数etfs全非空 | PASS |
| 回归 | _etfLightHelpHTML仅L2316调用(display-only); build_board_etf_map.py被deploy.sh L97调用,TRACK_WEIGHTS_INDIRECT无其他调用方 | PASS |

**reviewer结论**: PASS(可push main)。1个MINOR(n<60分支不分层,影响极低不阻断)。

### 5.2 R2一致性P0 reviewer(PASS)

reviewer进度文件: `/tmp/agent-progress-r2-consistency-p0-reviewer.md`

| 检查项 | 结果 |
|--------|------|
| 方案2 worker/headers.js: ttl=0 overview/intraday_snapshot/board_etf_map; ttl===0跳match+put设no-store; 低频ttl>0正常cache; R2回源不变; ASSETS fallback也用cc; SW networkFirstJson不缓存旧数据 | PASS |
| 方案1 PURGE_SECRET: trade/.env有(len=64); deploy.sh source .env(set -a L39-42在upload_r2调用前); upload_r2.py空时notify告警(try/except+_warned去重); 23 plist全有(hash一致); load_env setdefault不覆盖已设; 三处值一致 | PASS |
| 不影响其他功能: worker只影响/data/*.json路由; deploy.sh .env只加载PURGE_SECRET+DEEPSEEK_*; upload_r2告警只在空时触发 | PASS |
| check_data_integrity: 23 ok / 1 warn / 0 fail | PASS |
| P0 smoke: live site数据层正常 | PASS |
| Regression: headers.js是wrangler main entry, dataRewriteHandler只被/data/*.json调用 | PASS |

**reviewer结论**: PASS。2个minor建议(CACHE_RULES rule 2.5死代码/cacheKey noEdgeCache时未使用,非阻塞)。

### 5.3 §18 教训记录(本次新增)

落档于 CLAUDE.md §18(commit `0b8226604` + `0339ee963`):

1. **board_etf_map data/->static-site/data/ 复制遗漏**: build_board_etf_map.py写ROOT/data/(.absolute()),export.py不复制到static-site/data/。防:数据产物生成后必须手动cp或确认rsync同步到static-site/data/(§9 cwd=trade-data衍生陷阱,memory export-output-path-sync)
2. **reviewer验数据需真读上线文件非源文件**: reviewer报"三版本一致"但实际CF=旧版(未push main时expected),需明确区分"源文件一致"和"线上文件一致"
3. **agent自验+主控§0验三版本一致**: agent自验local+R2,主控§0补验CF线上(三处全验才算上线)

### 5.4 主动通知调研结论

调研agent进度文件: `/tmp/agent-progress-notify-stable.md`

**根因结论**:
1. **SendMessage丢失根因(两假设都确认)**: ①~7% agent没调SendMessage(16/236) ②调了但没送达(231 enqueue仅~154送达)
2. **task-notification机制**: agent stop_reason=end_turn时触发(707 completed);被interrupt(429/killed/stuck)不触发
3. **主控消息队列是瓶颈**: 680 enqueue仅313 dequeue = 54%丢失率。队列溢出时旧消息被remove不处理
4. **task-notification含result字段**: 包含agent最终文本输出(结论),主控收到即可读结论
5. **queue里cron轮询消息(181条)与通知竞争队列空间**,加剧丢失

**推荐方案(优先级排序)**:
1. **[最优] agent调notify.py + 终止end_turn**: notify.py邮件/Telegram直达用户(绕过主控队列),end_turn触发task-notification带result(备份)
2. **[增强] launchd WatchPaths监听进度文件**: 文件变化触发脚本调notify.py,不依赖agent主动调
3. **[保留] cron轮询进度文件**: 兜底,用户已说成本高不及时,但作为最后保险保留

**不可行方案**: StructuredOutput(Agent工具不支持schema参数) / claude CLI发消息到运行中session(--resume创建新进程非发消息) / .output文件作完成信号(是jsonl symlink全程存在非结果文件)

**落档**: commit `fc14495cf` docs: §11 主动通知调研结论-推荐notify.py+end_turn

---

## 6. 后续待办

### 6.1 R2一致性P1/P2(待办)

| 优先级 | 方案 | 内容 |
|--------|------|------|
| P1 | 方案4 | board_etf_map与overview同步: build_board_etf_map.py刷新后自动触发export_overview重算; track_score百分位基线固定化(预计算基线集,工作量大可选) |
| P2 | 方案3 | R2上传失败阻断+版本校验: deploy.sh关键文件(overview/board_etf_map)R2上传失败则阻断push; dataRewriteHandler对关键文件加last-modified校验; upload_r2.py上传后验证R2对象last-modified更新 |
| P2 | 方案5 | edge cache purge兜底: deploy.sh末尾统一调一次purge_cache(所有上传文件); 或Worker加定时清理(每小时清HIGH_FREQ文件edge cache); 或dataRewriteHandler对HIGH_FREQ文件edge cache TTL=5s(近实时) |

### 6.2 R2审计P1×3/P2×4(待办)

**P1(3项)**:
1. 159335 track_score跨文件不一致(overview signal=30.9 vs board_etf_map=30.2,不同match_method)
2. simulate_trade.py JSON模式无自动调度(update_lab.sh只跑--html模式)
3. track_score百分位基线全局动态变化(随候选ETF集合变化)

**P2(4项)**:
1. purge_cache失败无监控/告警(deploy.sh末尾统一purge未加notify)
2. check_data_integrity.py校验覆盖不足(不校验track_score三版本一致性/etf_since_return存在性/R2产物一致性/trade_sim_indices时效性)
3. _headers不生效(run_worker_first=true,Worker接管)
4. upload_r2.py不设R2对象Cache-Control metadata(由Worker代码设)

### 6.3 主动通知方案实施(待办)

- 实施 notify.py 调用方案: agent完成时调notify.py(邮件/Telegram直达用户)+end_turn触发task-notification带result
- launchd WatchPaths监听进度文件方案(增强)
- agent prompt规范更新: 完成时调notify.py(不只SendMessage)
- 当前cron轮询作兜底保留(§11标准方案=主控主动查进度文件,非靠通知)

### 6.4 R2报告72h监控

- R2迁移后72h监控(阶段3-5完成后启动): 维度①日志scan_log_anomaly ②告警邮件 ③执行耗时 ④周末定时任务 ⑤工作日开盘采集上传 ⑥R2数据时效(盘中intraday<15min,CF cache purge生效)
- 已有监控commit: `3ffea9396`(加维度⑥R2直连时效+维度③dur阈值检查) + `acfe50d55`(R2 72h reviewer FAIL修复C1+M1+L1+L2)
- 72h时间线: 周六阶段3-5完成+周末任务+R2+周日任务+R2+周一开盘intraday双写+采集+时效

### 6.5 R2迁移reviewer P2清理(已完成)

commit `9ead2aa33`: R2迁移reviewer P2清理(阶段3 4告警不一致 + 4a 3死代码)

---

## 附录A: 关键文件路径

| 文件 | 用途 |
|------|------|
| `worker/headers.js` | CF Workers主入口: dataRewriteHandler(/data/*.json->R2+分层TTL) + r2ProxyHandler(/r2/*->R2+1h缓存) + purgeCacheHandler(/api/purge-cache) |
| `scripts/upload_r2.py` | R2上传工具(10+命令) + purge_cache(PURGE_SECRET空时notify告警) |
| `scripts/deploy.sh` | 全量deploy pipeline: gen_etf_index_map -> build_board_etf_map -> export.py -> check_data_integrity -> gen_rss -> build_min -> rsync -> R2上传(10命令) -> staticdata备份 |
| `scripts/build_board_etf_map.py` | board_etf_map.json生成: track_score评分(直接/间接权重分层) + 5维度相似度 + 4层ETF匹配 |
| `static-site/export.py` | 全量JSON导出: overview/index/{id}-all/industry拆分/signal_kelly等30+JSON + 末尾自动R2上传7命令 |
| `scripts/check_data_integrity.py` | 数据完整性校验(13项): board_etf_map空数组/overview date/boot一致/intraday amount_forecast等。deploy.sh前置 |
| `docs/r2-deployment.md` | R2部署文档(8章节): 架构/R2 binding/Worker路由/upload_r2命令/定时任务双写/staticdata备份/重建步骤/排障 |
| `docs/site-deployment.md` | 站点部署文档(12章+2附录): 完整重建指南 |

## 附录B: 关键进度文件索引

| 进度文件 | 内容 |
|----------|------|
| `/tmp/agent-progress-r2-consistency.md` | R2一致性5问题5方案调研 |
| `/tmp/agent-progress-r2-audit.md` | R2端到端审计5维度(P0×2+P1×3+P2×4) |
| `/tmp/agent-progress-r2-consistency-p0.md` | R2一致性P0实施(方案2 worker + 方案1 PURGE_SECRET) |
| `/tmp/agent-progress-r2-consistency-p0-reviewer.md` | R2一致性P0 reviewer(PASS) |
| `/tmp/agent-progress-plana-implement.md` | 方案A实施(IR权重分层+board_etf_map重跑+export+R2上传+公示同步) |
| `/tmp/agent-progress-plana-reviewer.md` | 方案A reviewer(6维度PASS) |
| `/tmp/agent-progress-boardmap-rerun.md` | board_etf_map重跑+R2上传+CF purge(三处159586验证) |
| `/tmp/agent-progress-notify-stable.md` | 主动通知调研(主控队列54%丢失+推荐notify.py+end_turn) |

## 附录C: commit链(按时间顺序)

```
df6597245  feat: intraday_snapshot.sh 加 R2 双写 upload-intraday(阶段1b)
3b56bcb04  feat: R2迁移阶段2 - Worker /data/->R2 rewrite + purge-cache + 分层TTL
8a36b4b82  docs: 新建完整站点部署文档 docs/site-deployment.md(含阶段2)
508eabb44  feat: R2迁移阶段3 - 定时任务去git push数据改R2上传
3f721f2d8  feat: R2迁移阶段4a - static-site/data/移出git(R2唯一数据来源)
8bfc55e8d  feat: deploy.sh末尾加staticdata备份块(阶段5)
c24286e0f  docs: R2部署文档(r2-deployment.md 8章节) + site-deployment.md R2部分补完整
3ffea9396  feat(monitor): R2迁移72h监控-加维度⑥R2直连时效+维度③dur阈值检查
acfe50d55  fix(monitor): R2 72h reviewer FAIL 修复 C1+M1+L1+L2
9ead2aa33  fix: R2迁移reviewer P2清理(阶段3 4告警不一致+4a 3死代码)
710e43c70  fix(upload_r2): 5命令加 purge_cache 清 /r2/ 路由 CF edge 缓存
bf8be5527  fix(upload_r2): cmd_upload_index + cmd_upload_data_large 加 purge_cache
f958ef6cd  fix(upload_r2): _upload_glob 空匹配早返回补 4-tuple
d36126194  feat: 第5层来源 e(sum_pct概念暴露度)让159335进量子科技thsc_300830
567be9b24  fix: 走势卡ETF至今盈亏Layer2+3根治(后端注入etf_since_return)
4ea283685  feat: 方案A track_score IR权重按match_method分层
a21c28406  feat: §21 track_score公示文案同步方案A IR权重分层
b6c019eaf  fix(r2): 高频文件不写edge cache + PURGE_SECRET持久化 (R2一致性P0)
0339ee963  docs: §18 修正board_etf_map根因-data/->static-site/data/复制遗漏
fc14495cf  docs: §11 主动通知调研结论-推荐notify.py+end_turn
```
