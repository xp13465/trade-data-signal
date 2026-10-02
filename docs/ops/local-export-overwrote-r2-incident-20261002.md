# 本机 export.py 未设 EXPORT_SKIP_R2 覆盖 R2 事故(2026-10-02)

## 0. 结论速览
- **被覆盖**:本机 trade-data 树 16:37-16:42 跑 `static-site/export.py`(未设 EXPORT_SKIP_R2),自动上传 R2 的 **10 条通道共 966 个 key**(全部"首次/无状态全量"),用本机旧数据树(DB 数据停 20260917,overfit_monitor generated_at=2026-09-16 23:01)覆盖 R2 上云上正确版。
- **叠加**:云上 5 次 deploy(0205/0500/1640/1750/2105)均因 fund_nav DB↔产物不一致在校验阶段 exit 1 终止,云上 9-30/10-01 新版从未经 deploy 上传。
- **已自动修复一部分**:云上 fund_nav 22:10 修复(DB=产物=R2 均 20260930);云上 23:13 手动完整 deploy(校验 PASS,退出码 0)+ verify-r2 平日对账自动补传 92 个 → **已修复 383/966**。
- **最终剩余需恢复 562 个**(deploy 完成后 00:05 复测,R2 仍=本机旧版),构成:trade_sim 482、lab 44、industry-all-indices 28、index 3、global-extras-all 1、overfit_monitor_ext 1、industry-3y-meta 1、industry-5y-meta 1、signal_kelly_snapshots/20260918.json 1。**overfit_monitor.json / accum_nav_map.json 已被 verify-r2 自动修复,不再需恢复。**
- **止血 = 对账后从云上树 PUT 回 R2 这 562 个**(模板 `/tmp/restore_r2_v2.py` + 清单 `/tmp/restore_list_v3.txt`,已备,只写不执行),不碰 git/systemd。

## 1. 根因链(证据)
1. `static-site/export.py` L1420:`if os.environ.get("EXPORT_SKIP_R2") != "1":` → **默认=自动上传**;L1422-1426 循环调 10 条 upload_r2.py 通道,`env={**os.environ, "REPO": str(ROOT)}` **强制注入 REPO**。
2. `scripts/upload_r2.py` L78 `guard_repo_default`:REPO 显式设置→放行;该保护被 export.py 注入 REPO 绕过(事故当时云上树/本机树都能传)。
3. 本机 trade-data/data 的 `.r2_*_state.json` 缺失/损坏 → `_incremental_upload` 判定"首次/无状态全量"(证据:10 个状态文件 updated_at=2026-10-02T16:37~16:42, mode=首次/无状态全量)→ 全量上传本机旧树 966 key。
4. 云上 5 次 deploy 因 fund_nav DB 领先产物(DB=20260930 但产物停更)在校验阶段 exit 1,从未走到 R2 上传段 → 线上继续用 9-30/10-01 前的版本,叠加 16:41 覆盖后用户看到旧数据。

## 2. 时间线(2026-10-02)
| 时间(北京) | 事件 | 证据 |
|---|---|---|
| 16:37-16:42 | 本机 export.py 10 通道全量上传 R2,966 key | 10 个 `.r2_*_state.json` updated_at 同段,mode=首次/无状态全量 |
| 16:41 | R2 data/overfit_monitor.json、boot.json 被本机旧版覆盖 | R2 last_modified=16:41,etag=本机 md5 |
| 18:10 | 云上 fapi-daily 上传 7 文件(a-stock-3m/1y/6m/3y/5y/all + overview) | fapi_daily_launchd.log: `[fapi-bj-width-export] ... done (上传 7 文件到 R2 data/)` |
| 21:05 | 云上树重算出正确新版(手动/定时?),deploy 仍校验失败未上传 | deploy_20261002_2105.log 尾部 ✗ 数据产物校验失败(退出码 1) |
| 22:10 | fund_nav 异步上传完成 256/256(DB=产物=R2=20260930) | 云上日志 `[fund-nav] ✓ 上传完成 256/256, 耗时 1487.3s` |
| 23:13-23:44 | 云上手动完整 deploy,校验 PASS,退出码 0;verify-r2 平日对账自动补传 92 个(含 overfit_monitor/accum_nav_map/global-3y/5y/all 等) | deploy_manual_20261002.log `=== deploy.sh 结束 ... 退出码=0 ===`、`[verify-r2] ✓ 对账完成, 自动补传 92 个`;00:05 复测 overfit_monitor R2=5948d1f(云上版) |
| 23:43 | 本调研第二次全量 R2 探测(966 key),得出最终剩余恢复清单 | /tmp/r2_probe_result.json |
| 23:44+ | deploy 收尾触发 staticdata 备份 upload-large-json 异步进程 | ssh ps: upload_r2.py upload-large-json(23:44 启动) |

## 3. Q1/Q2 被覆盖清单 + 污染面
**污染面 = 966 个 R2 key 全在 10-02 被改写**(962 个本机 16:37-16:42 全量上传 + 4 个云上 fapi 18:10 恢复 a-stock-3y/5y/all + overview)。
**被覆盖范围按通道**(10 状态文件,全部"首次/无状态全量"):
| 通道 | R2 前缀 | 本机状态文件 | key 数 | 最终状态 |
|---|---|---|---|---|
| lab | lab/ | .r2_lab_state.json 16:37 | 65 | 44 需恢复 / 21 已恢复 |
| trade_sim_json | trade_sim_data/ | .r2_trade_sim_json_state.json 16:39 | 504 | 482 需恢复 / 22 已恢复 |
| index | index/ | .r2_index_state.json 16:40 | 173 | 3 需恢复 / 170 已恢复 |
| industry | industry/ | .r2_industry_state.json 16:40 | 134 | 30 需恢复(28 detail+2 meta)/ 104 已恢复 |
| public_fund | public_fund/ | .r2_public_fund_state.json 16:40 | 13 | 0 需恢复 / 13 已恢复 |
| etf_score | data/etf_score_list_* | .r2_etf_score_state.json 16:40 | 3 | 0 需恢复 / 3 已恢复 |
| data_large | data/ | .r2_data_large_state.json 16:41 | 24 | 1 需恢复(overfit_monitor_ext)/ 23 已恢复(overfit_monitor/accum_nav_map/global-3y/5y/all 等已被 verify-r2 补传) |
| kelly_parts | data/signal_kelly_trades_parts/ | .r2_kelly_parts_state.json 16:41 | 17 | 0 需恢复 / 17 已恢复 |
| kelly_sdc | data/signal_kelly_trades_sdc_parts/ | .r2_kelly_sdc_state.json 16:42 | 17 | 0 需恢复 / 17 已恢复 |
| kelly_snapshots | data/signal_kelly_snapshots/ | .r2_kelly_snapshots_state.json 16:42 | 16 | 1 需恢复(20260918.json)/ 15 已恢复 |
| 合计 | | | **966** | **562 需恢复 / 388 已恢复 / 16 云上无文件** |

注:.r2_etf_hist_state.json / .r2_fund_nav_state.json 为 9-13 旧状态(今天 export.py 未跑这两通道,不受影响)。

## 4. Q3 逐位对账(最新探测 23:43 + 云上树 md5 23:45 + 本机 md5)
分类口径:R2 etag(单 PUT=内容 md5)vs 云上树文件 md5 vs 本机文件 md5,统一 rel 命名空间(剥 R2 前缀)。
- **R2=本机(被覆盖,需恢复):562**(R2 etag == 本机 md5 ≠ 云上 md5)。完整清单见 `/tmp/restore_list_v3.txt`(562 行),映射 R2 key 校验 0 失配。**(00:05 复测,deploy/verify-r2 完成后的稳定态;较 23:43 中间态的 567 减少 5 个 = verify-r2 收尾补传)**
- **R2=云上(一致/已恢复):388**(R2 etag == 云上树 md5)。含 boot/overview/sentiment-*/hk-*/etf_national_team-*/a-stock-3y/5y/all/kelly_loss_features/signal_kelly_trades/signal_kelly_trades_sdc/lab_backtest、overfit_monitor、accum_nav_map、global-3y/5y/all 等。
- **云上无此文件(R2 保留现状):16**(index/g.brent-all、g.cn10y-all、g.comex_silver-all、g.gold-all、g.oil-all、g.usdcnh-all、g.wti_oil-all、s.cross_market-all、s.nasdaq_small-all、s.ryan_all2-all、s.ryan_all-all、s.sp500-weekly-all、s.spot_gold-all、s.tencent_cash-all、s.us10y-all、s.usd_cny_ef-all、industry-3y.json)。index/g.* 与 index/s.* 15 个 + industry-3y.json 云上树无文件,唯一来源=本机(其数据为 9-7 版),保留现状不恢复(无更优版本可传)。
- **R2≠本机≠云上(第三方):0;R2 404:0。**

关键文件逐位证据(示例):
| 文件 | R2 etag(23:43) | 本机 md5 | 云上树 md5 | 结论 |
|---|---|---|---|---|
| data/overfit_monitor.json | 5948d1f751db572c23e7675773381464(00:05) | 52523f...4711 | 5948d1f751db572c23e7675773381464 | **已恢复**(verify-r2 23:43 补传;用户见停 9-09 的原因已消除) |
| data/accum_nav_map.json | fba0949e6427529970ffa650532c9544(00:05) | 5adc1dfacd9c9faff3d4bcd653756f81 | fba0949e6427529970ffa650532c9544 | **已恢复**(verify-r2 补传) |
| data/global-3y.json | ae4843afd9b688de252151bdd75ab1c3(00:05) | ff3e2bae...2e6f | ae4843afd9b688de252151bdd75ab1c3 | **已恢复**;global-extras-all.json 仍本机版需恢复 |
| data/index/csi_000813-all.json | 3b8d28d3968f8df9faa34957aada597e | 3b8d28d...a597e | 78484075a6caffeaf7d0ddb32ca34154 | R2=本机,需恢复 |
| data/trade_sim_data/trade_sim_hs300_stats.json | 849a478ceda3832e61ea757a9df6230b | 849a478c...230b | ce03e4ba58401b5204c9155607266664 | R2=本机,需恢复(482 个 trade_sim 之一) |
| data/lab/lab_sim_sh_full.json | eb4b11c50f2913d37ab19947be558b2f | eb4b11c5...2b2f | 292f89d1e060b210116af0a5b0e44854 | R2=本机,需恢复(44 个 lab 之一) |
| data/signal_kelly_snapshots/20260918.json | 28bc8e60845372e5bba75c9692336aac | 28bc8e60...36aac | 35a9fe9dff9d3ae91df0e6ddb78462b1 | R2=本机,需恢复 |
| data/industry-all-indices/sw_801010-detail.json | 26f0c6021484a99bb5e92b2952dbfe7a | 26f0c602...fe7a | 3a80666ae1c95243353455684dce9b27 | R2=本机,需恢复(28 个之一) |
| data/boot.json | f75c244bb913bc433e829e79664e9de6 | d6d395637bfe77adfd466add2150a186 | f75c244bb913bc433e829e79664e9de6 | R2=云上,已恢复(23:13 deploy) |
| data/overview.json | 6967ff7b42f19424e9ec14cf2db36fa1 | d3fb7d7a955d87eebf0cd94f2232c18b | 6967ff7b42f19424e9ec14cf2db36fa1 | R2=云上,已恢复(23:13 deploy) |

## 5. Q4 云上版本数据日期(可恢复确认)
| 文件 | 云上树(恢复源) | R2 现状(=本机) | 用户可见影响 |
|---|---|---|---|
| overfit_monitor.json | generated_at=2026-09-30 21:40,accuracy 到 20260929 | generated_at=2026-09-16 23:01,accuracy 到 20260910 | 「AI监控走势图」本机版停 9-09/9-10 |
| overview.json | date=20261002 | 本机 date=20260916 | 首页 overview 已恢复(23:13 deploy) |
| boot.json | overview.date=20261002 | 本机 20260916 | 首页卡片已恢复 |
| accum_nav_map.json | 云上树 code→date→nav(21:05 重算),全部 code 最大日期=20260930(实测 158000 末 3 天 09-28/29/30) | 本机停 09-16 段 | 需恢复 |
| trade_sim_hs300_stats.json | generated_at=2026-09-30 19:02 | 本机 09-16 版 | trade_sim 482 个需恢复 |
| signal_kelly_trades.json | 已恢复(0cd85bdf) | — | 已恢复 |

## 6. Q5 止血命令清单(只写不执行,主控授权后云上执行)
只重传数据,不推 main、不动 git、不改 systemd。
```bash
# 1) 把清单与模板传到云上
scp -i ~/tdsignal.pem /tmp/restore_list_v3.txt ubuntu@122.51.111.173:/home/ubuntu/code/trade-data/
scp -i ~/tdsignal.pem /tmp/restore_r2_v2.py ubuntu@122.51.111.173:/tmp/

# 2) 在云上 deploy 树执行(用云上 venv,REPO 默认=trade-data)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  scp -i ~/tdsignal.pem /tmp/restore_r2_v2.py ubuntu@122.51.111.173:/tmp/
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  '/home/ubuntu/code/trade-data/.venv/bin/python /tmp/restore_r2_v2.py /home/ubuntu/code/trade-data/restore_list_v3.txt'

# 3) 验证(应看到 fixed≈562 skipped=0;个别 skipped=已被 verify-r2 自动修复)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cat /tmp/restore_result_v2.json'
```
- **作用**:562 个 key 逐个 HEAD 对账,不一致才 PUT(幂等);成功后 purge CF 边缘缓存(`/` 与 `/r2/` 前缀),前端立即读到新版。
- **预期影响**:R2 562 个 key 从本机旧版(9-16)变为云上正确版(9-30/10-01);不涉及 main/systemd/DB。
- **验证方式**:①脚本输出 fixed=562(或更少=已有自动修复);②抽查 `curl -s https://ss.fx8.store/data/overfit_monitor.json | head` 看 generated_at=2026-09-30(现已是云上版);③R2 HEAD etag==云上树 md5 抽查 3 个 key。
- **注意**:①执行前先确认云上无 deploy/定时任务在跑(见下);②该脚本从云上树读源文件,若云上树又重算过,以最新为准(幂等)。③script 内已含 purge_cache,无需手动 purge。

**止血前置检查**(避免与云上任务撞车):
```bash
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'systemctl list-timers --no-pager | grep -E "trade|deploy|update" ; ps aux | grep -E "deploy|upload_r2" | grep -v grep'
# 若 upload-large-json(staticdata 备份)还在跑,等它结束再止血(它走 backup 桶/data 前缀,不冲突但避免带宽争抢)
```

## 7. Q6 §25 前置(备份可逆性)
- **结论:重传前无需额外备份 R2 现状。**理由:①R2 被覆盖的 562 个文件内容 = 本机 trade-data 树旧版,**本机树保留原样(只读不动),可从本机逐位复现**;②恢复动作本身幂等(PUT 前 HEAD 对账,R2 已==云上则跳过);③若恢复后发现异常,可把本机旧版再 PUT 回去(本机树就是副本)。可逆性成立,不违反 §25。
- 唯一注意:本机树本次调研后保持只读,任何"再跑一次 export.py"都必须在 EXPORT_SKIP_R2=1 下进行(见 Q7)。

## 8. Q7 防再犯建议(只提建议,不实施)
1. **EXPOT_SKIP_R2 语义反转或强制**:export.py 的自动上传默认改为 `EXPORT_SKIP_R2 != "1" 时仅打印"将上传 N key"且须再确认`;或本机树运行(ROOT 非生产树)时默认跳过上传。
2. **export.py 不再注入 REPO**:L1426 `"REPO": str(ROOT)` 去掉,让 guard_repo_default 真正生效(本机树非 _TRADE_FALLBACK_OK 通道 → exit 3 拒绝);生产上传只从 deploy.sh 显式传 REPO。
3. **本机 trade-data 树标记为 dev 树**:upload_r2.py 增加"REPO 路径含 trade-data 且非云上生产树"的明确拒绝/告警;或在 dev 树加只读标识文件,上传通道检测到即拒。
4. **状态文件缺失 = 干跑告警**:`_incremental_upload` 判定"首次/无状态全量"时,默认不直接全量上传,而是 dry-run 打印待传清单并告警(或要求显式 `--allow-full`);否则一次状态丢失就静默全量覆盖。
5. **上传前自动备份到 signal-backup**:upload_r2.py 上传前把将要覆盖的 key 先 COPY 到 backup 桶(`s3_copy` 到 `signal-backup/<date>/<key>`),使任何覆盖都可逆(与 §25 同精神)。
6. **deploy 校验失败 = 告警升级**:云上 5 次 deploy 校验失败仅记日志,应触发 --severe 告警(memory alert-denoise-keep-fault-discriminator),避免"停更 6 天无人知"。
7. **跨机树数据一致性机检**:deploy 前比对 R2 现状 vs 云上树 md5 差异清单,超过阈值(如>100 个)即告警"R2 可能被异源覆盖"。

## 8b. 问③ 关键:verify-r2 为什么没覆盖 trade_sim/lab(deploy 不能替代恢复脚本)
- **verify-r2 覆盖范围**:`_R2_CHANNELS` 16 通道全部参与(upload_r2.py L2703-2745,含 lab/trade-sim-json);但**平日模式**(weekday!=6)每通道 to_check = 状态文件 changed 字段 ∪ 全池均匀抽样 20 个(fund-nav 100)(L2811-2834);逐 key HEAD 对账,不一致才补传(L2867-2870)。今天周四,非周日全量模式。
- **为什么 lab/trade_sim 没被覆盖**:增量引擎判定 changed 的依据 = 「本地源文件 vs 本地状态文件记录指纹」(L987 `force_full=(not old_files) or weekday==6 or marker_stale`),**完全不看 R2 现状**。23:13 deploy 后云上状态文件实测:`.r2_lab_state.json` changed=0、`.r2_trade_sim_json_state.json` changed=0(云上树 lab/trade_sim 与 9-30 记录一致)→ 两通道 0 增量不传;verify-r2 平日对这两通道只查抽样 20 个 → 兜不住 482/44 大批残留。同理 data-large changed=16 不含 overfit_monitor(云上树 overfit_monitor 仍是 9-30 21:40,未重算),overfit_monitor 靠 verify-r2 抽样+对账补传才修。
- **决定性结论**:普通增量 deploy(23:13 那种)+ verify-r2 平日对账**不能替代恢复脚本**——批量"本地文件没变但 R2 被外部覆盖"的场景只有周日(weekday==6)全量对账能兜,但下一次周日=2026-10-06,不能等。必须主动恢复 562。
## 9. Q8 诚实标注(实测/推断/未查到)
- **实测**:根因代码(export.py L1420/L1426,upload_r2.py L78)、10 个状态文件 mtime+mode、966 key 的三方 etag/md5(23:43 探测 + 云上树 md5 + 本机 md5)、云上版本数据日期(overfit_monitor 9-30 21:40、overview/boot 10-02)、云上 deploy 日志(5 次校验失败 + 23:13 成功)、verify-r2 补传 92、fapi 18:10 上传 7 文件。
- **推断(低风险)**:966 key 中"962 个本机 + 4 个 fapi"的划分基于状态文件与日志,个别 key 覆盖时刻可能有 fapi/deploy 交错(已在三次探测中校准,最终分类以 23:43 探测为准)。
- **未查到**:①21:05 云上树重算的触发者(手动/定时)未确认;②云上 23:13 deploy 的发起者(主控派单的 ac562449df83a621b 正在轮询,推断为该 agent 手动触发,未直接证实);③`upload-large-json`(staticdata 备份)进程是否会碰 966 keys 中任意一个(未核对清单,其前缀多为 etf_hist/fund_nav 大 JSON,低风险);④R2 `signal_kelly_snapshots/20260918.json` 本机版与云上版的差异内容(未逐一比对,仅 md5 不同)。
- **数据源与工具**:`/tmp/r2_probe_v3.py`(只读 SigV4 HEAD,00:05 探测 966)、`/tmp/r2_probe_result_v3.json`(最终探测)、`/tmp/cloud_md5_v3.txt`(云上 950 文件 md5,00:06)、`/tmp/local_md5.json`(本机 966)、`/tmp/threeway_cats_v3.json`(最终分类)、`/tmp/restore_list_v3.txt`(562 恢复清单)、`/tmp/restore_r2_v2.py`(止血模板,未执行)。

## 10. 复现方式
```bash
# 三方对账复现
python3 /tmp/r2_probe.py full   # 966 key HEAD 探测
ssh ... 'cd /home/ubuntu/code/trade-data && xargs -a cloud_paths.txt -P 8 -n 40 md5sum'  # 云上树 md5
python3 /tmp/threeway_audit.py  # 生成 /tmp/threeway_cats_v2.json
```
