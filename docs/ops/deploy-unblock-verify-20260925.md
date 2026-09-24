# deploy 解封 + 卡片数据层上线验收(2026-09-25)

## 一句话结论
- **断言解封:确认**——00:25 deploy(merge 274d5dcf4 后首轮)check_universe_alignment assertion1/2/3/4 全 PASS,不再「终止部署」。
- **R2 主链已完整恢复**——overview.json(00:45 落盘,含 index_tiers 聚合卡数据源)+ board_etf_map.json/summary.json/intraday_snapshot.json 等 data/ 小文件(00:55 落盘),线上均为 00:25 轮产物,逐位一致。
- 前端展示层:ss/s 两站新版,sss 站旧内容。

## 验证实测
### 第 1 步 · 等待 merge 后 deploy
- 云上 HEAD=274d5dcf4(含修复 b891a29c5),00:17 前无新日志。
- 00:25 出现新日志 deploy_20260925_0025.log,为 merge 后首轮;export 完成 00:33,R2 段持续至 00:54 才停。

### 第 2 步 · 断言解封
- deploy_20260925_0025.log:L617/620/623/626 `[PASS] assertion1/2/3/4`,L629「✓ 入样宇宙规则全部对齐(§23.6 对称校验 PASS)」。
- 无「✗ 入样宇宙规则校验失败/终止部署」;跑到 L756 R2 上传段,L760/762/763 purge 完成(110/1591/102 keys)。

### 第 3 步 · R2 主链恢复(§0②)
- `https://ssd.fx8.store/data/overview.json`:last-modified 9-25 00:45(北京),字节 1489865=本地产物,含 `index_tiers`(hs300=熊市·主跌/20260924)。✅
- `https://ssd.fx8.store/data/board_etf_map.json`:last-modified **9-25 00:55**(北京),ETag 8ecb1ee0 == GET 内容 md5 == 云上本地产物 md5(逐位一致)。sw_801200/sw_801950=[](本次产物,assertion4 修复生效)。✅
- summary.json(00:55:24)/ intraday_snapshot.json(00:55:16)均落盘,字节与 00:25 轮产物一致。✅
- market_tier_history.json:ETag e48bc557 == 本地 md5(内容一致,增量引擎见内容未变未重传,时间戳旧属正常)。✅

### 第 4 步 · hs300 展示位一致(§22)
- overview 顶层无 market_tier/market_state 字段(实测 None)。
- index_tiers.hs300.tier=熊市·主跌(20260924)vs market_tier_history.json 最新(20260924)=熊市·主跌 → 一致 ✅

### 第 5 步 · 前端展示层(§0③)
- ss.fx8.store app.min.js:1047809B,含「各指数四档」+「tier-card」✅
- s.sugas.site:同 ✅
- sss.sugas.site:279597B,无两字符串 ❌(旧/异常,按 §8 任一域名到新版即算 OK,记录不阻断)
- 三站 index 版本串均 v=20260924-a616

## 原观察(保留可反查,2026-09-25 00:46-00:52 采样)
> 当时 curl board_etf_map/summary/intraday_snapshot 的 last-modified 仍为 9-22/9-24 23:10,曾判「upload-all-data 未完成、R2 data 小文件未更新」。**该判断为采样时点过早的假结论,见下方后续核实。**

## 后续核实(2026-09-25 01:00,主控实测 + 本测试复跑确认)
1. `curl -s -A "Mozilla/5.0" https://ssd.fx8.store/data/board_etf_map.json` → HTTP 200,`last-modified: Thu, 24 Sep 2026 16:55:15 GMT`(= 北京 9-25 00:55:15);检查时看到的 9-22 21:04 是上传尚未落盘的中间态。
2. md5 逐位对账:R2 侧 = `8ecb1ee0624a27063f5422caef11ca06`;云上 `/home/ubuntu/code/trade-data/static-site/data/board_etf_map.json` = `8ecb1ee0624a27063f5422caef11ca06`。完全一致。
3. 云上小文件 mtime:summary.json 09-25 00:28、intraday_snapshot.json 00:29、board_etf_map.json 00:28 —— 全部是 00:25 那轮 deploy 生成的当轮产物。
4. 「00:45 进程消失、日志无 all-data 收尾行」与上传在 00:55 落盘不矛盾——上传段在日志尾部、purge 之后,采样时点早于其完成。

**修正后结论:断言解封 + R2 主链恢复两项均成立;原「upload-all-data 未完成」为采样过早的假结论,撤回。**

## 遗留记录(非阻断)
- [低] sss.sugas.site 前端未到新版(279KB 无新字符串;按 §8 任一域名到新版即算 OK)。
- [信息] overview 无 market_tier/market_state 字段,hs300 档位展示源在 index_tiers + market_tier_history(两者一致)。
