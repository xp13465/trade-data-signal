# 独立复核报告:deploy 数据产物校验失败(2026-10-08 02:06)—— reviewer agent

- 复核对象:`docs/ops/deploy-integrity-fail-20261008-0206.md`(researcher 产物,131 行)
- 复核方式:独立只读复算(自读代码行号 / 整读云上日志 / 实测交易日历 / curl 线上 + md5 对账 / 扫描 268 个历史 deploy 日志)
- **总判定:原定性成立 —— P2 假阳性、拦在线上写之前、线上未污染;6 项承重结论全部 PASS,未发现任何可推翻的致命反例。** 另发现 2 处「措辞不严」级偏差(不影响结论,见 §7)。

## 1. 闸门顺序(项1)—— PASS(附行号自核 + 一处口径澄清)

自读 `scripts/deploy.sh`(非转述):
| 位置 | 行号 | 内容 |
|---|---|---|
| check 调用 | **L323-324** | `echo "-> 运行 check_data_integrity.py ...` / `"$PY" "$REPO/scripts/check_data_integrity.py" --deploy-mode --data-dir "$REPO/static-site/data"` |
| 失败分支 | **L326-331** | `exit "$CHECK_RC"`(其前 L329 notify --severe --dedup-window 21600) |
| 首个线上通道写1 | **L527-529** | `rsync -a --checksum "$REPO/static-site/data/" "$GIT_REPO/static-site/data/"`(1.6) |
| 线上通道写2 | **L542-557** | rsync `$REPO/data/` → `$GIT_REPO/data/`(1.7) |
| 线上通道写3 | **L582-586+** | 触发 R2 上传(唯一 R2 数据通道,`r2_upload_async.sh`) |
| 线上通道写4 | **L656+** | exec 段2(锁内 git add/commit/push) |

- **口径澄清(最重要)**:「check 在一切写之前」字面不成立——check 之前有大量**本地写**:L216-236 build/cp board_etf_map(写 `$REPO/data/` + L251 cp 到 staging + L268 cp 到 `$GIT_REPO/data/`)、L288 `export.py --incremental`(写 staging,357 JSON/408.5MB)、L303-317 accum_nav 生成+cp。**但所有这些都不是线上通道**;线上三通道(rsync/R2/git push)全部在 check 之后,**确认成立**——原报告 §4 的措辞本来就是「拦在写线上/写仓步骤之前」,与其结论一致。check 之后 L332-522 区间自核无任何线上写命令(全为只读机检:task_state/universe/key-set/overfit/critical-css/version/placeholder/intraday;其间 L500-507 gen_rss、L509-521 build_min 也是本地写)。

## 2. 日志截断点(项2)—— PASS

- **0206 日志整读**(自拉全文 602 行):末尾 L595 `=== 汇总: 34 ok / 2 warn / 6 fail ===` → L596 终止 → L597-602 notify(邮件 L597 / telegram 跳过 / 飞书 L599 / severe-mirror L600 / 汇总 L601)+ dedup L602;**最后一条实质动作 = L602 `[notify][dedup] 更新 key=deploy_check_data_integrity_fail last_alerted=now`**。
- 机械核:`rsync`=1 处(**仅 header 文字**「段1(锁外 export+R2+rsync)开始」)、`upload`=0、`git push`=0、`commit`=0、`git add`=0、`段2/exec/git-phase`=0;**无「rsync 完成」、无「触发 R2 上传」**。
- 唯一 R2 实质行:`-> 跳过自动上传 R2(默认跳过; 显式 EXPORT_FORCE_R2=1 开启)`(export.py 自动 R2 段被跳过;机制=deploy.sh L22 `export EXPORT_SKIP_R2=1` + export.py L1424-1426 门 + 2026-10-03 起默认即跳过,双保险)。
- **05:00 日志**(595 行)同样:同 6 项 fail(L555-556/559-560/566/578)、L593 同汇总 → L594 终止 → **L595 止于 dedup suppress**(`suppress ... last_alerted=2026-10-08 02:16:02 age=10253s < window=21600s`;算术自洽:抑制判定时刻≈05:06:55);rsync=1(header)、upload/git push/commit=0。日志头=`2026-10-08 05:00:17` 起跑(与报告一致)。
- 对照 10-07 21:05(成功链,767 行):L595 `34 ok / 8 warn / 0 fail`、同 6 项=**滞后 7 天(warn,不拦)**、含「rsync 完成」+ L753 R2 触发;其段2 日志 `deploy_20261007_2116.log` 头="段2(锁内 git add/commit/push)开始 21:16:24"、尾="结束 21:16:44 退出码=0" ⇒ 10-07 那次完整成功,线上最后一次成功 deploy 链闭环。

## 3. 阈值与口径(项3)—— PASS

- `scripts/check_data_integrity.py` 逐字:`STALE_DAYS_WARN = 3` / `STALE_DAYS_FAIL = 7`(**L57-58**);`_days_ago()` **L156-162** = `(datetime.now() - d).days` = **纯自然日,无交易日感知**。
- 独立验算(云上 `data/trade_dates.txt` 实测,8796 行):`grep 2026(0929|0930|1001..1008)` 仅命中 **L8735=20260929 / L8736=20260930 / L8737=20261008**;10-01~10-07 全部不在表 ⇒ **自然日差 8(FAIL>7),交易日差 0** ✓。阈值边界对照:10-07 时自然日差=7 → warn(实测日志证实),10-08 跨到 8 → FAIL,纯边界效应。

## 4. 线上状态(项4)—— PASS(更强口径:md5 逐位对账)

- 带浏览器 UA curl `ss.fx8.store`(2026-10-08 07:54,无 -v/-i):
  - `alert.json`:date=**20260930**、generated_at=2026-09-30 18:37:24,结构 keys=[date,generated_at,high,history,low] 完整。
  - `ad_line.json`:250 条完整,尾条=**{date:20260930, up_count:2337, down_count:2719, ratio:0.4622, ad_line:-141161, ma5/ma20 齐}**。
- **md5 对账(新增证据)**:线上三文件 md5 == 云上 `trade-data-signal/static-site/data/` 同名文件(alert `ee9dc60e…` / ad_line `dc5f7352…` / overview `5403b70f…`)⇒ 线上内容 = 10-07 21:05 成功 deploy 的产物(**非半成品**);GIT_REPO 侧文件 mtime 全部 ≤ 2026-10-07 21:11(alert 09-30 18:37 / ad_line 21:11:50 / overview 21:11:35)⇒ 10-08 两次失败 deploy **未写入** GIT_REPO staging。
- 独立 R2 物证:云上 `r2_upload_async_*.log` 最新 = `r2_upload_async_20261007_211623.log`(**10-08 全天无 r2 上传日志**)⇒ 两次失败 deploy 均未触发 R2 上传 ✓。

## 5. 首犯判定(项5)—— PASS(L49 非空集已验)

- 扫描范围实测:269 个 deploy 日志(最老 `deploy_20260913_0850.log`,报告写「9-16 起」略保守,覆盖更长)。
- `grep -lE '> 7 天' deploy_*.log` ⇒ **仅 `deploy_20261008_0206.log` + `deploy_20261008_0500.log`** 两个。
- 非空集验证(防"空集当没命中"):滞后分布实测 `0天×717 / 1×382 / 2×133 / 3×100 / 4×71 / 5×37 / 6×35 / 7×28 / 8×12` ⇒ 格式确实在日志中存在且满布;历史最高=7 天(7 个日志有),**8 天=12 条=6 项×2 日志(恰为本案)** ⇒ 「滞后>7 天类首犯」成立。
- 闸门整体:`数据产物校验失败(退出码` 命中 44 个日志(与报告一致);`邮件已发送.*数据产物校验失败` 仅 0206 一个(首次实发 ✓)。

## 6. 反例搜寻(项6,最关键)—— 未发现致命反例;已穷举的写路径如下

| 排查面 | 结论 | 证据 |
|---|---|---|
| check 之前有写盘吗? | **有,但全部本地**(staging + 本地库/data + `$GIT_REPO/data/`):board_etf_map 重建+3 处 cp(L216-268)、export 357 JSON/408.5MB 写 staging(L288)、accum_nav(L303-317) | 0206 日志全文;export.py 自动 R2 被 L22+默认双保险跳过并实印「跳过自动上传 R2」 |
| `$GIT_REPO/data/board_etf_map.json` 写会否弄脏 git/挡未来 pull? | **不会**:该路径被忽略 | 云上实测 `git check-ignore -v` → `data/.gitignore:1:*  data/board_etf_map.json`(rc=0);`git status --porcelain` 0 行 |
| 02:06 是否 update_all 里 deploy 之外的步骤已执行? | 02:06 不是 update_all;链=`backfill_metrics.sh L29` → `index_backfill.main()` 内部 **L1121-1124 先 compute.runner(本地库)** → **L1137-1139 subprocess deploy.sh**。deploy 非第一步,但前序只写本地 DB,且 deploy 在 L324 被拦后 **exit**,后续全未跑 | 本地代码逐行 + 0206 日志"段1 开始 02:06:14"为日志首行 |
| export.py 自动 R2 会不会绕过? | 不会(双保险 + 日志实印跳过) | deploy.sh L22;export.py L1418-1456;日志行 |
| 半成品上线? | 无(md5 逐位=10-07 版本;R2 无 10-08 上传;日志止于 notify) | §4 |
| 其它:当前是否有 deploy 在跑/新写? | 无:10-08 仅 0206/0500 两个 deploy 日志;`ps` 无 deploy/update_all/backfill 进程 | 云上实测 |

## 7. 措辞级偏差与观察(不影响总判定,供主报告知悉)

1. 「日志无任何 rsync/R2/git 行」字面不严:日志含 `git fetch` 输出(3 行)与 header 中 "rsync" 字样 1 处、R2 字样若干(均为文本/注释);实质(无 rsync 执行/R2 上传/git 写)成立。
2. 「线上是 09-30 版本」精确口径=就 6 个被拦项(alert/notifications/ad_line/a_stock/accum_nav/s06)。线上 `overview.json` 的 date=20261001、fund_score=20261007 属既有日期语义,10-07 21:05 **成功**版本即如此(该次 check 亦通过/仅 warn),与本案无关。
3. 报告 §5 称日志范围「9-16 起」,实测最老为 9-13(结论方向不变且更强)。
4. 未归因小观察:`/tmp/trade_deploy.lock` mtime=10-08 07:45(schedule-monitor 07:45:01 同窗),但无 07:45 deploy 日志、无 deploy 进程、git 工作区干净、live md5 未变 ⇒ 不影响任何结论,建议勿追。

## 8. 未测项(诚实标注)

- 触发链 journalctl 证据(02:00:01→02:16:47)沿用原报告,未独立复跑 journal(可复跑,预期一致)。
- 未直读 R2 对象时间戳(避免动 R2 凭据),以「r2 日志无 10-08 记录 + GIT_REPO mtime + live md5」三路间接证"R2 未污染"。

—— reviewer agent,/Users/linhuichen/code/trade(只读复核,未切分支、未 commit)
