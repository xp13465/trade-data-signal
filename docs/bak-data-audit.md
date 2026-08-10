## START 2026-08-11 bak-audit
started
=== STEP: git log check ===
static-site/data fully moved out of git (catch-all L188-191), only feed.xml tracked. GH Pages backup has NO data JSON.
## PROGRESS 01:38 (was slow due to large curl loops)
已完成:
1. quickstart 两文档通读: R2 迁移后 static-site/data/ 全 gitignore(L188-191), R2 唯一数据源, GH Pages 备站无 data JSON(设计如此)
2. git: 862e3a86d (A+B fix) 只在 feat/iframe-theme-follow 分支, 未合 origin/main; 但 3 站已部署 fallback (app.min.js 含 ss.fx8.store/data)
3. fetchJSON 逻辑: ./data/* 失败 → fallback https://ss.fx8.store/data/ (worker /data/ rewrite, 有 ACAO:*); 外链 r2/ 不走 fallback 靠 CORS
4. CORS 验证: /data/ ✓ACAO /r2/data/ ✓ACAO /r2/lab|industry|public_fund ✓ACAO; **/r2/index/hs300-all.json 缺 ACAO(cf-cache-status HIT age=2820 旧边缘缓存, 部署前缓存, 自愈≤1h)**
5. R2 完整性: 165 index/-all.json 全在 R2; 65 lab/*.json 全在 R2; 12 public_fund 全在 R2; 顶层小 JSON 全在 R2 (除 industry/offshore 独立前缀)
6. signal_kelly_backtest.json: R2 200 (463KB) + 主站 /data/ 200 → fetchJSON fallback 可恢复; **但 signal_kelly_trades.json 用 ssd.fx8.store 直链(无 ACAO) → 备站 CORS 阻断 → 凯利交易重算/交易记录弹窗备站必挂**
7. §9 cwd 陷阱: trade/static-site/data/ 缺 public_fund* 全部 + signal_kelly_backtest.json (只在 trade-data/), 但 launchd REPO=trade-data 上传, R2 有全量 → 生成侧 OK
8. 公募基金 renderPublicFund: summary metrics 有数据(96.17 仓位) → 主站 OK; 备站"暂无数据"=CORS 阻断旧因(已由 ACAO 修)
继续: s.sugas.site(MaoziYun) 全量探测 / signal_kelly_backtest 内容 / trade_sim_indices / 剩余外链 URL(etf_score/industry detail) / 备站 app.min 版本核对
## PROGRESS 01:46 - 验证收尾,写报告
- /r2/index/hs300-all.json + /r2/trade_sim_data/trade_sim_sh_stats.json: cf-cache-status HIT age~3560(00:46 缓存,早于 01:03 ACAO 部署) 无 ACAO → 01:46 max-age 3600 到期自愈(现在)
- alert_analyze 58/58 全在 R2; fund_score_top 在 fund_score/ 前缀 200 + ACAO; industry 走拆分文件(industry-all.json 404 无关紧要,前端不读)
- 结论: 4 症状根因=CORS(预修复缺 ACAO)+./data 无兜底(预修复); 现 A+B 已上线基本恢复; 残留真 bug=signal_kelly_trades ssd 直链无 ACAO
# 备站功能模块数据加载失败 — 完整调研报告 (2026-08-11 只读)

## 一、架构根因(一切问题的总根源)
R2 迁移(2026-08-08, .gitignore L188-191 `static-site/data/*` catch-all + `!feed.xml`)后,**static-site/data/ 全量移出 git**。
=> GitHub Pages 备站 sss.sugas.site / MaoziYun 备站 s.sugas.site **磁盘上一份 data JSON 都没有**(curl 全 404)。
所有数据只能靠前端两条通道: ①`./data/*.json` 404 后 fallback 主站 `https://ss.fx8.store/data/` rewrite(862e3a86d A+B 新增) ②外链 `https://ss.fx8.store/r2/*` 直读主站 Worker R2 代理(靠 CORS ACAO 放行)。
**备站可用性 = R2 数据完整性 × CORS 头 × fetchJSON fallback 覆盖度**。任一缺失=该模块备站挂。

## 二、用户报 4 症状逐一定位(现态)

| 模块 | 读的文件(代码位置) | 本地trade | R2/主站 | 备站现状 | 根因 |
|---|---|---|---|---|---|
| 1 公募基金"暂无数据" | 12 个 https://ss.fx8.store/r2/public_fund/*.json (app.js L12028-12035) | 0(trade 无 public_fund*) | 12/12 在R2(200)+ACAO✓ | **已恢复** | 预修复: r2ProxyHandler 无 ACAO→跨域 CORS 阻断→Promise.all 全 null→summary null→L12042 暂无数据。862e3a86d 加 ACAO 后已好 |
| 2 指数表现"加载失败" | https://ss.fx8.store/r2/index/{id}-all.json (app.js L11508/11736) + dataUrl 大range | 165/165 | 165/165 在R2(200) | **CORS 瞬态** | /r2/index/ 响应 cf-cache-status HIT age~3560(00:46 缓存,早于 01:03 ACAO 部署)**缺 ACAO**→备站跨域阻断,~1h 内刷新也没用;01:46 max-age 到期自愈。非代码 bug,部署后未 purge 所致 |
| 3 凯利信号回测 signal_kelly_backtest.json (lab.js L7793-7797) | ./data/signal_kelly_backtest.json(16 quadrants 有值) | **trade 无此文件(只在 trade-data/)** | R2 200(463KB)+主站/data/ 200 | **已恢复** | 预修复: 备站 ./data/ 404 无兜底→报"Failed to fetch...不存在"。A+B fallback 后走主站/data/ 200 恢复 |
| 4 信号实验配对排行 (lab.js L1636 lab_sim_{i}_stats.json) | https://ss.fx8.store/r2/lab/lab_sim_*_stats.json | 65/65 | 65/65 在R2(200)+ACAO✓ | **已恢复** | 预修复 CORS(同1)。A+B ACAO 后恢复 |

## 三、残留真 bug(未覆盖/仍会挂)
1. **[确认挂] signal_kelly_trades.json 直链 ssd 无 ACAO** (lab.js L7496-7505 费率重算 + L8600-8608 交易记录弹窗):
   代码硬编码 `r2Url="https://ssd.fx8.store/data/signal_kelly_trades.json"`(R2 公开桶,curl 实测**无 access-control-allow-origin**),失败后兜底 `./data/`(备站 404)。
   => 备站: ssd CORS 阻断→catch→./data 404→双失败。**凯利"交易记录弹窗/费率重算"在备站必挂**。A+B 只改了 fetchJSON 没改这个直链。
   (主站 OK: ./data/ 经 /data/ rewrite→R2 200,51MB)
2. **[瞬态已自愈] /r2/ 旧边缘缓存缺 ACAO**: /r2/index/* + /r2/trade_sim_data/* 在 01:03 ACAO 部署前被缓存(age 3560),部署后 1h 内返回旧无-ACAO 响应→备站 指数表现/策略实验回测 CORS 挂。01:46 max-age 到期后自愈。**根因**: r2ProxyHandler `if(cached) return cached`(L118)直接返回缓存不重加 ACAO 头。
3. **[合并风险] 862e3a86d(A+B)未合 origin/main**: `git branch --contains 862e3a86d` 仅 feat/iframe-theme-follow;origin/main 顶端 cb5da14c4。3 站已部署(a117,curl app.min.js 含 fallback+sw a117)但 main 无此修复→**下次从 main 的 deploy/重构建会把 A+B 修掉**。
4. **[潜在回归] §9 cwd 陷阱**: signal_kelly_backtest.json + public_fund* 全部 + alert_analyze 70 个 **只在 trade-data/static-site/data/**,trade/static-site/data/ 为 0。R2 现齐全靠 launchd `REPO=trade-data`。**任何从 trade/ 手动跑 deploy.sh/upload_r2(无 REPO)会漏传这些文件→线上回归**。signal_kelly 为独立脚本无 launchd,重跑后必须 cp 两路径+上传。

## 四、全量数据依赖清单验证(不只 4 个)
A. `./data/*` fallback 链(33 字面引用 + 动态): 全在 R2 data/ 前缀(200)。含 overview/boot/summary/signal_stats/intraday_snapshot/alert/notifications/ma_alignment/position/ad_line/volume_ratio/new_high_low/futures*/rotation/etf_national_team*/trade_sim_indices/a-stock|hk|global|sentiment 小range/lab_cost_compare/lab_ablation/lab_short_symmetry/lab_param_scan。**唯一 404: fund_score_top.json——正确,它走 r2/fund_score/ 外链**
B. 外链 r2/*: public_fund 12✓ / index 165✓ / lab 65✓ / industry(range+meta+indices+detail+concepts)✓ / data 大range+etf_score_list✓ / trade_sim_data✓ / fund_score✓ / offshore_fund✓ —— **全部在 R2 且(除旧缓存瞬态)有 ACAO**
C. alert_analyze 58 白名单 iid: 58/58 在 R2(200)
D. 绕过 fetchJSON 的直链: signal_kelly_trades(ssd, 见残留1)+ intraday 分钟图(eastmoney/腾讯外网, 非备份数据范畴)

## 五、统一修复方案(按 §22 N文件+N缓存同步)
1. **signal_kelly_trades 修 CORS**(B级, 改 lab.js): L7496/L8600 `r2Url` 从 `ssd.fx8.store/data/` 改 `https://ss.fx8.store/data/signal_kelly_trades.json`(主站 /data/ rewrite,ACAO✓+边缘HIT~50ms, 与 A+B 对齐); 或 R2 公开桶配 CORS(需 R2 侧配置)。改后 §21 无算法公示影响; 派 agent+reviewer
2. **r2ProxyHandler 缓存响应补 ACAO**(B级, worker/headers.js L118): `if(cached)` 分支 clone 后 `headers.set('Access-Control-Allow-Origin','*')` 再 return——根治"部署改头 1h 内旧缓存缺头"瞬态, 不必每次 purge
3. **合 862e3a86d 到 origin/main**(主控动作): 防 main 部署丢失 A+B; 合后 curl 3 站确认 a117 仍在
4. **§9 上传链路加固**(C级): deploy.sh/upload_r2 统一 `REPO=trade-data`(或 upload 前 rsync trade-data→trade); signal_kelly 重跑文档化"run in trade-data→cp trade→upload-data-files signal_kelly_backtest+trades→purge"三步; 落 docs/data-deploy-quickstart.md
5. **部署后 purge /r2/*** : 每次 worker 头变更部署后 `POST /api/purge-cache`(分批30)清 /r2/ 旧缓存, 免 1h CORS 盲窗

## 六、修复后自测计划
- 信号灯: ①`curl -sI https://ss.fx8.store/data/signal_kelly_trades.json` 看 200+ACAO; ②备站模拟: `curl -s https://sss.sugas.site/data/signal_kelly_trades.json` 404 + 确认 fallback URL 200
- 公募基金: `curl -s https://ss.fx8.store/r2/public_fund/public_fund_summary.json | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['metrics'][0]['metric_value'])"` 出 96.17 非空; 备站浏览器开 fund tab 看 4 信号灯+仓位曲线
- 指数表现: `curl -sI https://ss.fx8.store/r2/index/hs300-all.json` 确认 cf-cache-status MISS/DYNAMIC + ACAO:*; 备站 A股 tab 全卡片有 K 线
- 凯利: `curl -s https://ss.fx8.store/data/signal_kelly_backtest.json | python3 -c "import json,sys;print(len(json.load(sys.stdin)['quadrants']))"` 出 16; 备站凯利 tab 打开+点交易记录弹窗
- 配对排行: `curl -s https://ss.fx8.store/r2/lab/lab_sim_hs300_stats.json | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('summary') or list(d.keys()))"` 非空; 备站策略实验配对排行有行

## DONE 备站调研完成: 4症状根因=CORS+./data无兜底(预修复),A+B(862e3a86d)已上线基本恢复;残留3问题:①signal_kelly_trades ssd直链无ACAO备站必挂 ②/r2/旧边缘缓存缺ACAO瞬态(已自愈) ③A+B未合origin/main;潜在1:§9 cwd陷阱signal_kelly_backtest/public_fund/alert_analyze只在trade-data需REPO=trade-data上传。完整报告见上。
