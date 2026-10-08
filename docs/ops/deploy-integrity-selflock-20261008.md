# deploy 数据产物校验「自锁」查证报告(2026-10-08)

> 调研 agent 落档,2026-10-08 ~21:55;22:15 续核补 §11(含 22:00 档实证,见 §11.3)。全程只读:云上未启停/未改 unit、未跑任何业务脚本主体(探针 static-only)、零 R2 写、零外发;未切分支/未 commit。
> 背景:#232 观察报告 §4 提出「alert 自锁」疑点;#235 报告(02:06)预期「17:50 后自动归零」实测未兑现。本报告以代码阅读 + 云上日志 + R2 上传台账 + 线上实测四路证据钉死链条。
> 任务书要求:①自锁是否成立 ②卡住项三列 ③起点成因 ④解锁命令 ⑤根治 ⑥影响面 ⑦与 #235 关系。

## 0. 结论摘要

| 项 | 结论 |
|---|---|
| 自锁是否成立 | **成立**(锁点=唯一 1 项 `alert`) |
| 自锁对象 | `alert.json`;同族受害者 `alert_analyze_*.json`(58 个,无独立通道、R2 停 09-30,**非锁点**) |
| 02:06 原 6 项现状 | 5 项已自愈归零(notifications/ad_line/a_stock/accum_nav_map_fresh/s06_state),**只剩 alert 1 项 fail**(21:08 轮实证) |
| 10-08 deploy 结果 | 全天 ≥15 轮(确证:02:06/05:00/16:32/16:45/17:00/18:28/18:30/19:30/20:05/20:11/20:25/21:00/21:08/21:27/21:45)**全部被 check 拦截、零成功**;最近成功=10-07 21:05 档;22:00 档实测无 deploy 轮(§11.3) |
| 自动逃逸路径 | **无**(5 类通道逐一排除,见 §3) |
| 立即解锁 | 手动补传 alert 到 R2(命令见 §7.1,本次未执行) |

## 1. 自锁链(代码 + 台账 + 日志三证)

> 【2026-10-08 22:1x 续核】判据无损并再获两轮实证:21:27 轮(backfill_evening 触发)/21:45 轮(etf_national_team 触发)均 39 ok/2 warn/1 fail、唯一 fail=alert;22:00 档实测无 deploy(机制见 §11.3)。注意「deploy 零成功」≠「R2 零更新」,三类区分见 §11.1。

1. **生成**:`alert.json` 由 update_all 17:50 链的 `export_alert.py` 写本地两树(无 R2 上传;update_all.sh L174-178 注释原文「alert.json 本地更新,下次 pipeline deploy 推上线」)。10-08 源侧 mtime=19:29:45、md5=`65c60ad5378e4179a40bfacb69c08352`。
2. **上 R2 的唯一通道** = `upload-all-data`(r2_upload_async.sh L223),触发唯一 = `deploy.sh L582`(异步触发),而该步骤位于 check(L323-324)**之后**。
3. **闸门读 R2**:`check_data_integrity.check_alert`(check_data_integrity.py L410-436,`R2_DATA_BASE`=L110)读线上 `alert.json` → 读到 09-30 版 → `days=8 > STALE_DAYS_FAIL=7`(L57-58,L431)→ FAIL。
4. **拦截**:deploy.sh L326-331 FAIL → notify(--severe,dedup key `deploy_check_data_integrity_fail` window 21600)+ `exit 1` → L523/L543 rsync、L570+ R2 段、deploy 末尾 purge、L656 段2 git **全部未执行**。
5. **闭环**:R2 永停 09-30 → 下一轮 check 继续 FAIL → 永久锁死。

**旁证(数字化/内容级,四条独立)**:
- 云上 `data/logs/` **无 10-08 的 r2_upload_async 日志**(最新仍为 20261007_211623)→ 上传链 10-08 从未启动。
- R2 上传台账 `data/.r2_all_data_state.json` mtime **停在 10-07 21:27**(10-07 21:05 档成功 deploy 的 R2 段),10-08 零写入。其中 `alert.json` 条目 md5=`ee9dc60e69d8be05ea40dd546f4e539c` **≠ 源侧当前 md5 `65c60ad5…`** ⇒ 当前源版从未上传过。
- 线上直读(带 cache-busting `?v=timestamp` 与不带 query 双测):`alert.json` 均 `date=20260930, generated_at=2026-09-30 18:37:24`。#232 报告另以 R2 直连域名 `ssd.fx8.store` 独立测得同期 09-30。
- 环境对照(同一批次 curl):s06/notifications/ad_line/boot 均为 10-08 新版,**仅 alert(及 alert_analyze)停在 09-30** ⇒ 非「整体缓存/网络伪象」。

## 2. 卡住项三列表现状(以 21:08 最新轮为准)

| check 项 | R2 线上值 | 源侧值 | 阈值 | 分类 |
|---|---|---|---|---|
| **alert** | date=**20260930**(gen 09-30 18:37) | date=10-08(gen 19:29:45) | 7 自然日 | **自锁(唯一致命锁点)** |
| s06_state | 20:35 已上传成功(实测=10-08T20:35:01;21:00 轮单点读到旧版=CF edge 残留,21:08 轮已对账归位) | coverage_end=10-08 | 7 | 已自愈(独立通道 20:35) |
| notifications | date=10-08(gen 20:37:25) | 10-08 | 7 | 已自愈(独立通道) |
| ad_line | 末条=10-08 | 10-08 | 7 | 已自愈(独立通道) |
| a_stock | (check 读本地) | 本地=10-08 | 7 | 已自愈 |
| accum_nav_map_fresh | (check 读本地;但 **R2 副本实测停在 09-30**,见 §5) | 本地=10-08 | 7 | 已自愈(check 解)、R2 停更(非 check 项) |

各轮演进:02:06 6 fail(#235)→ 16:32 3 → 16:45 4 → 17:00 3 → 18:28 4 → 20:05 3 → 20:11 2 → 20:25 2(alert+s06)→ **21:00 1 fail(38 ok/3 warn)** → **21:08 1 fail(39 ok/2 warn;唯一 fail 行:`✗ alert: alert.json date=20260930 滞后 8 天 > 7 天`)**。21:08 尾部无 rsync/R2/git 行,止于 notify dedup(`suppress … age=16617s < window=21600s`)。

## 3. 通道穷举:`alert` 为何没有任何通道能救(自锁「无逃逸」论证)

| 通道 | 是否可救 alert | 证据 |
|---|---|---|
| deploy.sh L582 → r2_upload_async → upload-all-data | **否**(被自身闸门拦死) | §1 链条 |
| upload-data-files 独立链(各脚本调用方) | **否** | `.r2_standalone_keys.json` 全量 79 项**无 alert/alert_analyze**(登记=实际曾上传过的独立链产物全集) |
| verify-r2 周期对账(含独立链 stale 补传) | **否** | upload_r2.py L4043-4044 注释「deploy.sh 每日调用」——其触发也在 deploy 链内(r2_upload_async.sh L254),10-08 未跑;且补传对象=独立链登记清单,不含 alert |
| self_heal 自愈 | **否** | self_heal.sh L77-86 `HEAL_ACTIONS` 8 项无 R2 补传动作;`update_all force` 路径内部又走 deploy → 再被拦 |
| intraday 等其他 export/上传链 | **否** | 各清单(如 upload-intraday)不含 alert;update_all 仅 export 本地 |

⇒ **alert 的 R2 更新完全寄生在「被它自己阻塞」的 deploy 链上 = 结构性自锁,无自动逃逸。**

## 4. 自锁起点与成因

- **起点 = 10-08 02:06 档**(trade-backfill-evening 02:00 触发)。10-07 21:05 档时同一批项 days=7 **仅 WARN 不拦**(#235 报告 L50:34 ok/8 warn/0 fail);跨入第 8 自然日(10-08)首拦。
- **成因**:6 项判定用**自然日差**(check_data_integrity.py L156-162 `_days_ago` = `(now - d).days`,无交易日感知)+ **国庆长假**(09-30 为最后交易日,10-01~10-07 全非交易日)。10-08 凌晨自然日差=8 > 7,而交易日差=0。——即 #235 已定性的「长假后自然日假阳性」,**但它对 alert 从「误拦一轮」升级成了「永久锁死」**(其余 5 项有 deploy 之外的刷新/上传路径,alert 没有)。

## 5. 影响面(§22 用户可见性)

**真实用户可见停更(R2 层面,实测)**:
1. `alert_analyze_*.json`(58 个 iid):R2 停 09-30(实测 hs300;R2 etag=`39605fad…` == 台账登记 md5,证明对象=09-30 上传版)。消费方=app.js L10023-10160(首页 58 iid 预警卡 fetch+modal)、lab.js L6351(lab 预警快照)、lab.js L6902-6961(持仓自查 8+8 拆解)、lab.js L7078-7103(单标的分析 modal)——**全部直 fetch R2,用户看到的是 09-30 版拆解**。
2. `alert.json` 直连:09-30。首页 C6 预警条(app.js L15766)优先读 `_bootData.alert`(**R2 boot 内嵌 alert 实测=10-08 新版**,20:35 融合),仅 boot 不可用时 fallback fetch `./data/alert.json`;但 R2 公开对象/任何直读方仍是 09-30。**【22:1x 补核】alert.json 本体直读点全站仅 app.js L15766 一处降级路径(grep 核对:lab.js 全部消费点均为 alert_analyze)⇒ 对主路径用户可见度≈0,但 §22 裂口仍在(boot.alert=10-08 vs alert.json=09-30 两展示位)。**
3. `accum_nav_map.json`:R2 末条=20260930(净资产曲线/强平日真价展示位)。
4. `signal_kelly_backtest.json` / `signal_kelly_trades.json`:R2 generated_at=2026-10-07 21:11(10-08 版未上);R2 LM=10-07 21:27:36 / 21:26:53(§11.2)。
5. `board_etf_map.json`:**已判(§11.2)**:R2 LM=10-07 02:28:06 版(10-07 凌晨轮),本地 21:12 重写后 md5 `1cb6b8ae…` ≠ R2 etag `b4a420e3…` ⇒ **停更**(deploy-only 类,ttl=0 用户直读)。
- §22 一致性裂口:同一「风险预警」事实两展示位不一致(boot.alert=10-08 vs alert.json=09-30)。

**已自愈/不受影响(独立通道 10-08 在跑)**:notifications、overview、boot、ad_line、s06_state、etf_score_list、trade_sim_indices 等。

## 6. 与 #235 的关系

- **option A「17:50 后自动归零」:对 alert 证伪**(21:08 仍 fail;alert 结构上不会归零);其余 5 项确实归零。
- **option B(自然日→交易日口径)**:本轮**能解锁**(10-08 凌晨交易日差=0;盘后差≤1,均 ≤7 → 通过 → deploy 恢复 → R2 自动追平)。**但不能防「真停更型自锁」**:若 alert 未来因任何原因真实滞后 >7 交易日,「R2 旧→拦→不传→更旧」的正反馈仍原地复活。**∴ #235 方案须叠加「上传链解耦」(见 §7)才完整。**
- 建议 #235 条目(pending-features-index.md L362)补充:option A 预期证伪、自锁定性、解锁命令、根治改为「B + 解耦」。

## 7. 修复方案

### 7.1 立即解锁(本次未执行;均由人工在云上执行)
```bash
# 选项 A(最小解锁,推荐):补传 alert 到 R2 → 下一轮 deploy(22:00 档或明晨 02:00/05:00)即通过,
#   并通过 deploy 自身 R2 段自动追平其余产物(含 alert_analyze 四路客户端所需数据)
cd /home/ubuntu/code/trade-data
.venv/bin/python scripts/upload_r2.py upload-data-files alert.json $(cd static-site/data && ls alert_analyze_*.json)
# (仅 alert.json 一项即足以解锁;alert_analyze_*.json 是同族受害者,顺带一起补)
# 选项 B(直接全量追平 R2,等价 deploy 的 R2 段;有锁幂等,可与选项 A 二选一):
REPO=/home/ubuntu/code/trade-data GIT_REPO=/home/ubuntu/code/trade-data-signal bash /home/ubuntu/code/trade-data/scripts/r2_upload_async.sh
```
(命令形态与 s06_snapshot.sh L133 活例子一致:upload-data-files <相对名…>,运行于 REPO;上传后自动 purge+登记 standalone。)

### 7.2 根治
1. **上传链解耦(核心,消灭自锁结构)**:alert/alert_analyze 在 export 后直接走 `upload-data-files` 独立通道(同 s06_snapshot.sh L133 先例),R2 数据更新不再依赖 deploy 存活。
2. **口径修(#235 option B)**:6 项日期判定改交易日口径(改动点=check_data_integrity.py `_days_ago` 及 6 处 call site)。
3. **闸门分级(可选,与 #188 权衡)**:check_alert 对「R2 旧但本地新」给 WARN 非 FAIL——**先例即 s06 分支①(#188,check_data_integrity.py L2168-2187)注释原文「FAIL 会 abort deploy → R2 永不上传 → 死锁」**,即设计方已识别此死锁形态并对 s06 打了补丁,alert 未获同等待遇。
4. **自锁检测(可选)**:连续 N 轮同项 FAIL 且本地新鲜 → 告警文案区分「自锁」形态 + 附修复指引(现 dedup 6h 窗只抑制重复,不区分自锁)。

### 7.3 §23.7 冻结契约标注
- 7.2-1(新增上传链)= 新增为主,不改已上线判定行为,风险低(增量 R2 写 ~59 文件/日,量级可忽略)。
- 7.2-2/3(改 check 口径/分级)= **改已上线校验行为,触及 §23.7,需用户拍板**。
- 7.2-4 = 纯新增监控告警文案。

## 8. 未测/未核项(诚实标注)

1. ~~R2 `alert.json` 对象 etag 未直取~~ **已销项**:**R2 etag=`ee9dc60e…` 已直取(HEAD 实测,--max-time 20 -sI)==台账登记 md5 逐位一致**,见 §11.2。
2. ~~`board_etf_map.json` R2 版生成日期未判~~ **已判**:R2 LM=10-07 02:28:06(§11.2)。
3. ~~22:00 档及 10-09 各轮~~ **22:00 档已测:实测无 deploy 轮**(机制=public_fund_full 无新数据跳过分支,未到 deploy 步;见 §11.3);10-09 各轮未到观察时点。
4. s06 21:00 单点读旧版(与 20:35 上传成功、21:08 归位并存)的完全定因:判为 CF edge 缓存生效时序,未做更细因果实验。
5. alert.json 消费方穷举范围=static-site 前端(app.js/lab.js/guide/about)+ R2 公开层;邮件/飞书链读本地源,不受影响(未再向外穷举)。

## 9. 证据索引(可复核)

- 代码:`scripts/check_data_integrity.py`(L57-58/L110/L156-162/L410-436/L431/L439-464/L2114-2220/L2144/L2168-2187/L2190/L2213-2214);`scripts/deploy.sh`(L22/L323-331/L523/L543/L557-567/L582-604/L656);`scripts/r2_upload_async.sh`(L198-227/L223/L254);`scripts/upload_r2.py`(L2359-2394/L2408-2431/L4033-4039/L4043-4044);`scripts/update_all.sh`(L174-178);`scripts/s06_snapshot.sh`(L117/L126/L133);`scripts/self_heal.sh`(L64/L77-86);`static-site/app.js`(L15760/L15766/L10023-10160);`static-site/lab.js`(L6217/L6351/L6902-6961)。
- 云上日志:`data/logs/deploy_20261008_0206.log`(L557-580/L595-596/L597-602)、`deploy_20261008_2100.log`(38/3/1)、`deploy_20261008_2108.log`(39/2/1+尾部 dedup suppress);`data/logs/` 无 r2_upload_async_20261008*。
- 云上台账:`data/.r2_all_data_state.json`(mtime 10-07 21:27;alert 条目 md5=ee9dc60e…)、`data/.r2_standalone_keys.json`(79 项,无 alert)、`data/.r2_kelly_snapshots_state.json`(mtime 10-08 20:35)、`data/.r2_accum_nav_state.json`(mtime 10-07 21:16)。
- 线上实测(本机 curl --max-time 20 -sL + UA + cache-busting):`ss.fx8.store/data/alert.json`(09-30)、`alert_analyze_hs300.json`(09-30;etag=39605fad…)、`accum_nav_map.json`(tail 20260930)、`signal_kelly_backtest.json`/`signal_kelly_trades.json`(gen 10-07 21:11)、`notifications.json`(10-08 20:37)、`ad_line.json`(tail 10-08)、`kelly_mode_s06_state.json`(10-08T20:35:01)、`boot.json`(alert.date=20261008)、`overview.json`(10-08 20:35:54)。

---
*只读查证报告;未 commit(主控收口)。*

## 10. 附:逃脱路径核查(--skip/环境变量?)

**无。** check 拦截为硬终止(deploy.sh L326-331 `exit 1`);SKIP/FORCE 类开关仅作用于时段闸门、不作用于 check(#235 报告已 grep,本次复核代码一致)。唯一解锁路径 = 让 R2 的 alert 变新(§7.1)。

## 11. 续核订正(2026-10-08 21:30+,主控复核触发)

### 11.1 「deploy 零成功」与「overview 15:39 上 R2」的澄清(兼容,非矛盾)

- **overview 15:39:59 上传 = intraday_snapshot.sh 15:35 轮**(独立通道,与 deploy 无关)。证据:云上 `data/logs/intraday_snapshot_20261008_1535.log`(mtime 15:40)L201 `-> 同步 intraday 数据到 R2（upload-intraday）...`;15:30-15:45 find 窗口内仅该日志与 check_signals 在写;代码 `intraday_snapshot.sh` L169-170(`upload_r2.py upload-intraday`,清单含 overview/boot/notifications)。
- **当前 R2 overview 已是更晚版本**:ssd.fx8.store(直连)HEAD `last-modified: Thu, 08 Oct 2026 12:40:24 GMT(=20:40:24 BJ)`;GET(带/不带 query 双测)内容 `collected_at=20261008 20:35:54` ⇒ 被同一链 20:35 轮再刷。主控观测的 LM=15:39:59/内容 15:35:52 = 15:35 轮版本(事件窗口内当时态),二值各自吻合对应轮次,无矛盾。
- **订正表述**:「10-08 全天 deploy 零成功」判据无误(≥12 轮全被拦),但 **≠「R2 零更新」**——须区分三类:
  1. **独立通道文件(照常更新)**:overview/boot/notifications/ad_line/s06/etf_score/trade_sim…(15:35/20:35 intraday 轮 + 各自独立链);
  2. **deploy-only 文件(停更)**:alert(09-30 内容版)、alert_analyze 58 个(09-30 版)、board_etf_map(10-07 02:28 版)、backtest/trades(10-07 21:27 版);
  3. 本地读类(check 不拦,R2 副本另判):accum_nav_map(R2 09-30 版,停更)。

### 11.2 补测硬数据(R2 对象 LM/ETag vs 云上本地,2026-10-08 ~21:30)

| 文件 | R2 ETag | R2 LM(ssd, 北京) | 云上本地 md5(21:12 重写) | 判定 |
|---|---|---|---|---|
| alert | ee9dc60e…(**== 台账登记 md5,逐位一致**) | **10-07 02:27:47** | 65c60ad5…(10-08 19:29 生成) | **停更:最后 PUT=10-07 凌晨,10-08 版从未上传(自锁双证闭环)** |
| alert_analyze_hs300 | 39605fad…(== 台账 md5) | — | 3d495923… | 停更(09-30 内容版) |
| board_etf_map | b4a420e3… | 10-07 02:28:06 | 1cb6b8ae…(21:12) | **停更:R2=10-07 凌晨版;该文件 ttl=0 用户直读** |
| signal_kelly_backtest | d2f7292b… | 10-07 21:27:36 | 0cc7a667…(21:12) | **停更:R2=10-07 21:11 生成版** |
| signal_kelly_trades | 28684cd5… | 10-07 21:26:53 | 76690c9f…(21:12) | **停更:同上** |
| overview | f10a0cd5… | 20:40:24 | bc41c1c1…(21:12) | 正常(独立链 20:35 轮已上当日定稿版;与本地差=轮次差异,非 T 日级停更) |
| (对照) notifications / boot / s06 / ad_line | — | — | — | 正常(独立链) |

- ss.fx8.store(worker)与 ssd.fx8.store(直连)ETag 全对齐(无缓存残留);worker 不透传 LM(仅直连可见)。
- **alert R2 对象 LM=10-07 02:27:47 BJ**(=10-06 18:27:47 GMT)= 最后 PUT 时刻(10-07 凌晨轮 deploy);10-08 全天真零 PUT。ETag 与台账 md5 逐位一致 ⇒「R2 alert=最后上传版、10-08 版从未上传」双证闭环(此前「etag 未取」未测项就此销项)。
- 补充意义:deploy 段2 被跳过 → GIT_REPO 树同为 10-07 版;云上本地 static-site/data 每轮 export 照常重写(21:12),「本地新 vs R2 旧」差距全天累积(但不等≠必然停更——须按上表 LM 判旧)。

### 11.3 21:27 / 21:45 轮实测 + 22:00 档追踪(2026-10-08 21:30-22:1x)

- **21:27 轮**(触发者=**backfill_evening** 链:云上 `backfill_evening_launchd.log` 含 `=== deploy.sh 段1(锁外 export+R2+rsync)开始 2026-10-08 21:27:34 ===`):**39 ok / 2 warn / 1 fail**,唯一 fail=`✗ alert: alert.json date=20260930 滞后 8 天 > 7 天`;mtime 21:35 停(卡 check→exit 1)。非 self-heal 触发(21:22 self-heal LIMIT 已满)。
- **21:45 轮**(触发者=**etf_national_team** 链:`etf_national_team_launchd.log` 含 `... 开始 2026-10-08 21:45:10 ===`):同形态 **39 ok / 2 warn / 1 fail,唯一 fail 仍=alert**;尾部 `[notify][dedup] suppress key=deploy_check_data_integrity_fail last_alerted=2026-10-08 16:39:14 age=18766s < window=21600s`;mtime 21:52 停。两轮 log md5 不同(内容细节有差),但大小同 39464B、汇总形态一致。
- **deploy 触发者模式**:deploy 非单一 cron,而是**多条业务链(backfill_evening / etf_national_team / public-fund 等)尾部的统一调用**;「16:39 起持续 FAIL」= 各链每跑到 check 全被 alert 拦(每轮各自 export 照跑、全被截停)。
- **dedup 到期=22:39:14**(16:39:14+21600s)⇒ 22:39 后首个 FAIL 轮将**真发 severe 告警**(此前所有轮持续 suppressed)。
- **22:00 档追踪=实测无 deploy 轮(机制钉死,非「未测」)**:
  - timer 实锤:`/etc/systemd/system/trade-public-fund-full.timer` `OnCalendar=*-*-* 22:00:00`(service ExecStart=public_fund_full.sh;脚本头注释「launchd 02:00」为 mac 时代遗留,已过时)。
  - 该链 22:00:00 起跑 → **22:00:01 走数据新鲜度闸门跳过分支**:`[fresh] should_run=False 无新数据 report_date=20260630 已采全 holding=5202 asset_alloc=8919/9000, 跳过` → `⏭ 无新数据, 跳过本次全量采集(check-fresh exit=1)` → `=== public_fund_full.sh 结束(无新数据)2026-10-08 22:00:01 ===` ⇒ **未到 L88-89 的 deploy 调用**;22:00:02-22:00:05 仅跑跳过分支尾部 gen_schedule_stats+push_schedule_stats(独立通道 ✓ R2 上传完成,证明 R2 通道与锁均健康)。
  - 22:00-22:14 全窗口无 `deploy_20261008_22*.log`、`ps` 无业务进程。**结论:22:00 档设计上是 deploy 潜在触发者之一(链尾 L89),今日因季报无新数据跳过、未产生 deploy 轮**;若某日有新季报数据,该链将真跑 ~5.25h 后于深夜/凌晨调 deploy。
  - 22:00 后其余 timer:22:30 nextday-plan / 22:35 check-data-gap / 23:20 r2-consistency 均不含 deploy;下一轮 deploy 预计=今夜 02:00 档 backfill 系链(待观察,超本任务窗口)。
- **21:45 轮 check 的 2 warn 明细**(deploy log L565/L570;21:27 轮同):`⚠ fapi_mutex: 两源最新日不一致 mootdx=20261008 fapi=20260930(观察期正常时序)`、`⚠ etf_since_return: 非 null 占比 93.2% (2706/2903) < 95%`——均 WARN 不阻塞(非锁点)。
- **self-heal 实况固证**:今日额度 3/3 全给 etf_national_team(20:22/20:37/20:52),21:22 起 LIMIT 空转;且 HEAL_ACTIONS 8 项本无 R2 补传 ⇒ **自锁无自动逃逸路径**。
- **顺带观察(超本任务边界,未深查)**:①check 输出 `✓ nextday_plan: 计划条目=1 date=20260930` 判 ok,而 self_heal 侧 `SKIP_STALE nextday_plan(last_run 09-30)` ⇒ nextday_plan 产物自 09-30 起未更新且 check 无新鲜度门;②今日 etf_national_team heal×3 全败(20:22/20:37/20:52)。均登记待后续独立排查。
