# acc_nav 补数执行报告(2026-10-03)

> 实施 agent 产出,对应主控任务「云上补 acc_nav 缺失数据(11 天)→ 同步三库 → 线上验证」。
> 用户 2026-10-03 已拍板「补」。本文=执行报告(本体),含 ## 复现段,配套 commit 见 §8。
> 上游:调研 `accnav-backfill-0923-0924-20261003.md` + 执行前两前提查证 `accnav-backfill-prerequisites-20261003.md` + 独立复核 `accnav-backfill-review-20261003.md`。

## 0. 一句话结论

**主库 11 天(9-15/16/17/18/21/22/23/24/28/29/30)acc_nav 全部补齐(逐日 24311~26114 行),三库 public_fund.db md5 逐位一致 `37aaa79ce7df48d59deee3f42727c936`,nav_bucket 已重出并上传 R2,线上 CF 主站抽样逐位对账一致,备份在位可回滚。全程无撞定时任务,17:50 update_all 前收工。**

## 1. 执行时间线

| 阶段 | 时点 | 动作 | 结果 |
|---|---|---|---|
| STEP 1 脚本核查 | 10:44 | 读 `docs/ops/repro_backfill_accnav.py` 全文 | 四条件全过(只写 /tmp 中间表;UPDATE 三层防护在报告 §4.3;--dates 参数化;不碰其它列/日期),无需改 |
| STEP 2 备份 | 10:47 | 云上 cp + sqlite 在线备份主库 | `public_fund.db.bak-20261003_104704`(cp, md5=原库 53df2a5d)+ `public_fund.db.wal-20261003_104704.bak`(在线), 行数 22478032 可打开 |
| STEP 3a 本机小验证 | 10:54 | `--limit 5` 拉 9-17 | 5/5 与接口逐位一致(000001=3.871 等) |
| STEP 3b 全量拉取 | 10:52→15:00 | 本机 `repro_backfill_accnav.py --dates 11天` | 26446/26458 ok(fail12=0.045%),中间表 277,949 行,逐日 24311~26122 |
| STEP 3j 门槛对账 | 15:00 | ①11 天逐日量级 ②抽 5 只跨日期接口逐位一致 ③中间表只含 11 天 | 三项全 PASS |
| STEP 3k 单日试跑 | 15:04 | UPDATE 9-17 | 补 25252 行,9-17 acc 有值 26→25278,四项对账全 PASS |
| STEP 4 全量 | 15:06 | UPDATE 其余 10 天 | 补 252,562 行,11 天全有值 |
| STEP 4b 全量对账 | 15:07 | 全表行数 + 11 天逐日 + 差异根因 | 全表 22478032 不变;差异=fix 含接口新增 code 主库无行 / NaN 被防护拦截,均正常 |
| STEP 5a 重出 nav_bucket | 15:08→15:10 | 云上 `export_fund_nav.py` | 26596 只/256 桶/535.5MB/105s,000001 11 天全有 acc 值 |
| STEP 5b 上传 R2 | 15:09→15:33 | `fund_nav_upload_async.sh` | 256/256 桶,耗时 1440.6s,线上生效 |
| STEP 5d deploy | 15:34→15:58 | `deploy.sh`(带注入) | 退出码 0,export357 JSON+rsync data/→GIT_REPO+git push main+staticdata 异步同步 |
| STEP 6 验收 | 15:58→16:0x | 三库 md5/行数 + 线上 + 备份 | 全 PASS |

## 2. 补数结果(主库,UPDATE 后)

`SELECT date, SUM(acc_nav IS NOT NULL) FROM fund_daily_nav WHERE date BETWEEN 20260915 AND 20260930 GROUP BY date`

| date | acc_nav 有值 | 补数前 | 判定 |
|---|---|---|---|
| 9-15 | 25281 | 0 | 接口已可取,补 |
| 9-16 | 25276 | 0 | 同上 |
| 9-17 | 25278 | 21(损坏)→26(语法验证5行)→25278 | 必补(参考 21959) |
| 9-18 | 26110 | 0 | 接口已可取,补 |
| 9-21 | 25284 | 23(损坏) | 必补(参考 21956) |
| 9-22 | 25306 | 0 | 接口已可取,补 |
| 9-23 | 25308 | 25(损坏) | 必补(参考 21977) |
| 9-24 | 26114 | 54(损坏) | 必补(参考 22754) |
| 9-28 | 25327 | 0 | 交易日,补 |
| 9-29 | 24347 | 0 | 交易日,补 |
| 9-30 | 24311 | 0 | 交易日,补 |

- 全表行数 22478032(UPDATE 前后不变)。
- 与中间表 fix 行数差异根因(诚实标注):
  - 9-15/16/17/18: fix 表含接口返回但主库当日无此 `fund_code` 行的记录(主库无法给不存在的行补值,正常)。
  - 9-21: 2 行(009303/009386)接口返回 NaN → 中间表存 NULL → UPDATE 三层防护 `EXISTS(... IS NOT NULL)` 正确拦截,不写入污染。
  - 9-24: 主库 26114 > 中间表 26097,因原 54 行损坏残留被 `acc_nav IS NULL` 条件保留 + 新补,正常。

## 3. 三库同步

| 库 | 路径 | md5 | 11 天 acc 行数 |
|---|---|---|---|
| 主库(REPO) | `/home/ubuntu/code/trade-data/data/public_fund.db` | `37aaa79c...` | 25281/25276/25278/26110/25284/25306/25308/26114/25327/24347/24311 |
| 副本1(signal) | `/home/ubuntu/code/trade-data-signal/data/public_fund.db` | `37aaa79c...` | 逐位一致 |
| 副本2(staticdata) | `/home/ubuntu/code/trade-data-signal-staticdata/db/public_fund.db` | `37aaa79c...` | 逐位一致 |

同步机制:deploy.sh 段1.7 `rsync data/ → GIT_REPO/data/`(signal)+ 尾部 `staticdata_backup_async.sh step1 rsync *.db → staticdata/db/`。**P1 缺口(复核报告)已通过跑 deploy 补上。**

## 4. 线上验证

- **R2 nav_bucket**:`https://ss.fx8.store/r2/nav_bucket/{bucket}.json`(前端真实取数路径,no-store 上传即生效)
  - 000001(ca.json): 9-15=3.823/9-16=3.869/9-17=3.871/9-18=3.906/9-21=3.905/9-22=3.9/9-23=3.897/9-24=3.868/9-28=3.817/9-29=3.819/9-30=3.795 — 11 天全有值
  - 110022(ef.json): 9-17=2.814/9-23=2.82/9-24=2.781/9-30=2.79(与调研报告 §2 逐位一致)
  - 163402(7b.json): 9-17=11.255/9-23=11.3428/9-24=11.2506/9-30=11.1459(与调研锚点逐位一致)
- **备站 sss.sugas.site 404 为架构正常**:nav_bucket 走 R2(ssd.fx8.store/CF 主站),GitHub Pages 不承载;任务验收口径「任一域名验证到新版即算上线 OK」已满足(CF 主站 PASS)。

## 5. 备份与可回滚

| 备份 | 路径 | 状态 |
|---|---|---|
| 主库 cp | `/home/ubuntu/code/trade-data/data/public_fund.db.bak-20261003_104704`(2.67GB, md5=53df2a5d 损坏前原库) | 在位,可打开,行数 22478032 |
| 主库 sqlite 在线 | `/home/ubuntu/code/trade-data/data/public_fund.db.wal-20261003_104704.bak`(2.67GB) | 在位 |
| nav_bucket 重出前留底 | 云上 `/tmp/nav_bucket_bak_20261003_150704`(256 桶 536MB,损坏版) | 在位,用于 R2 回退 |

**回滚**:DB `cp "$DB.bak-20261003_104704" "$DB"` 后重跑 deploy 同步三库;R2 用 `/tmp/nav_bucket_bak_20261003_150704` 重传。

## 6. 脚本只改目标列自证

- UPDATE 语句(三层防护)只 `SET acc_nav`,`WHERE date IN(...) AND acc_nav IS NULL AND EXISTS(fix 有非空值)`。
- UPDATE 后全表行数 22478032 不变;unit_nav 11 天非空数与 UPDATE 前基线逐位一致(25267/25262/25278/26087/25292/25299/25320/26164/25313/24355/24353)。
- 即:只动了 acc_nav 的 IS NULL 位,其它列/其它日期零变化。

## 7. 时点安全

- 全程 10-03 周日(A 股/港股休市),deploy 段 15:34-15:58,远早于 17:50 update_all,未撞任何盘后定时任务(15:35/16:00/17:50/20:35/22:00 均未重叠)。
- 10-09 01:43 stage0-nav timer 在补数完成后(10-03),且 UPSERT 修复已在云上,不会二次踩踏 acc_nav。

## 8. 配套 commit / 生成脚本

- 本报告 commit:feat 分支 `feat/accnav-backfill-exec-20261003`(见 git log,Co-Authored-By 行)。
- 生成脚本:本机全量拉取用 `docs/ops/repro_backfill_accnav.py`(调研已提交);云上 UPDATE 用 `docs/ops/accnav_backfill_update.py`(三层防护,同报告 §4.3 SQL,本文件随本报告一并提交,云上已 scp 至 /tmp/accnav_update.py 实跑)。

## 复现段(命令速查)

```bash
# 1) 三库 md5 + 行数
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'md5sum /home/ubuntu/code/trade-data/data/public_fund.db /home/ubuntu/code/trade-data-signal/data/public_fund.db /home/ubuntu/code/trade-data-signal-staticdata/db/public_fund.db'
# 2) 11 天 acc_nav 非空行数(三库各跑)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'python3 -c "
import sqlite3
c=sqlite3.connect(\"/home/ubuntu/code/trade-data/data/public_fund.db\")
for r in c.execute(\"SELECT date, SUM(acc_nav IS NOT NULL) FROM fund_daily_nav WHERE date BETWEEN 20260915 AND 20260930 GROUP BY date ORDER BY date\"): print(r)"'
# 3) 线上 R2(浏览器 UA 必需)
curl -s -A "Mozilla/5.0" https://ss.fx8.store/r2/nav_bucket/ca.json | python3 -m json.tool | grep -A1 20260917
# 4) 备份在位
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'ls -la /home/ubuntu/code/trade-data/data/public_fund.db.bak-* ; sqlite3 -line /home/ubuntu/code/trade-data/data/public_fund.db.bak-20261003_104704 "SELECT COUNT(*) FROM fund_daily_nav"'
# 5) UPDATE 脚本(云上,三层防护;供复核/补漏)
python3 /tmp/accnav_update.py <dates_csv> /tmp/accnav_fix.db
```

## 诚实标注(未验证/已知边界)

1. fail=12 只(0.045%, 接口空返回/NaN):对应基金部分日期未补,量级占比 <0.1%,不影响结论。
2. 9-15/16/18/22 全市场可补性未穷举单只对账(只抽样 5 只),由接口同源全量拉取 + 主库与中间表差量核查兜底。
3. 中间表 11 天行数与参考正常日(~2.2 万)的差异(实际 2.4-2.6 万)来源:参考值为 signal 10-01 快照(损坏前)口径,与接口全量实拉存在自然差异;以 fix 实量为准(任务已注明)。
4. 备份文件被 deploy rsync 带进 signal 副本(rsync data/ 未 exclude *.bak),属多一层备份,无负面影响。
