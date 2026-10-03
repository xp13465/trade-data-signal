# acc_nav 补数执行独立复核报告(2026-10-03)

> reviewer 独立产出,针对执行分支 feat/accnav-backfill-exec-20261003 @ 973a57bda 的执行报告
> docs/ops/accnav-backfill-execution-20261003.md + UPDATE 脚本 docs/ops/accnav_backfill_update.py。
> 复核方式:全部核心数字独立重算(云上只读 SQL/md5 + 本机中间表比对 + R2 独立抽样 + 接口重拉 306 只),
> 未照抄报告任何数字。审查面:C 级数据改动(生产主库 252,562 行),命中 §15 必审。

## 0. 结论

**补数本体正确、可验证、可回滚,审查通过;发现 1 个执行链小瑕疵 + 1 个报告时效性事实更新(非补数缺陷)。**

- 逐项 PASS:三库行数/11 天逐日行数、只改 acc_nav 列(全表 rowid 对比零增删零他列差异)、
  备份可恢复(bak + wal-.bak 双备份均能打开且为补前基线)、12 只 fail 定性(全部=接口侧本就没有,非"该有没补")、
  NaN 拦截正确(009303/009386 主库保持 NULL 无污染)、R2 线上 5 桶独立抽样逐位一致、
  连续性锚点(被 clobber 日的补回值=clobber 前原始值)、云上实跑 UPDATE 脚本=commit 版逐字一致(md5)、
  stage0-nav UPSERT 根治云上在位(下次 10-09 01:43 不会二次踩踏)。
- 2 个低分/信息项:①报告 §3「三库 md5 逐位一致」以验收时点成立,复核时主库被 16:01 定时评分管线追加
  2000 行 fund_score(score_date=20261003)→ 现主库 md5=c20a0bd0 ≠ 另两库 37aaa79c;属正常管线写主库、
  deploy 才同步另两库的**既有架构事实**,非补数缺陷,但报告快照已过时,故本报告按复核实况记录。
  ②报告 §4「9-15/16/18/22 未穷举单只对账」诚实标注成立(抽样 5 只已对账,本复核另补 5 只全对)。

## 1. 三库 md5 独立复算(复核实况)

| 库 | md5(我复算) | 执行报告声称 | 核 |
|---|---|---|---|
| REPO 主库 /home/ubuntu/code/trade-data/data/public_fund.db | **c20a0bd0a72f39ef0f5435cf346a3bec** | 37aaa79c... | ✗ 见下 |
| signal 副本 | 37aaa79ce7df48d59deee3f42727c936 | 37aaa79c... | ✓ |
| staticdata 副本 | 37aaa79ce7df48d59deee3f42727c936 | 37aaa79c... | ✓ |

- 差异根因(已溯源):16:01-16:08 定时管线 **pf-score-daily**(日志 data/logs/pf-score-daily.log 16:08 收尾)向主库 fund_score
  追加 score_date=20261003 共 2000 行(main 356929 vs signal 354929,其余 20 张表行数全部一致)。
  **acc_nav 补数数据在三库完全一致(11 天逐日行数三库相同,3 只基金抽样值 signal=main 逐位一致),不受影响。**
  - 结论:报告验收时刻(15:58-16:0x)三库确为逐位一致;复核时刻(16:20+)主库已被正常定时管线写新数据。
    三库同步机制=deploy rsync(主→signal)+ staticdata_backup_async(主→staticdata),两次 deploy 之间主库被
    评分管线追写属既有架构设计(用户侧数据经 export 产物展示,不直接读这三份 DB 拷贝)。
  - 此为**报告时效性事实更新**,不是补数缺陷;提示:任何"三库 md5 一致"结论都有时间窗,复核应以"数据值一致"为准。

## 2. 11 天逐日行数独立 SQL(三库全跑,逐位一致)

SELECT date, SUM(acc_nav IS NOT NULL) ... WHERE date BETWEEN 20260915 AND 20260930 GROUP BY date

主库独立输出(与 signal/staticdata 相同):
```

20260915 25281 / 20260916 25276 / 20260917 25278 / 20260918 26110 / 20260921 25284 /
20260922 25306 / 20260923 25308 / 20260924 26114 / 20260928 25327 / 20260929 24347 / 20260930 24311
```
与报告 §2 逐个数一致 ✓;全表 22478032 行(UPDATE 前后不变)✓。

## 3. 「只改 acc_nav 列」独立验证(最强项,全表 rowid 对比)

把 22,478,032 行主库与备份库(bak,补前字节级副本)按 rowid 逐行、逐列对比(字段:
date/fund_code/fund_name/unit_nav/acc_nav/prev_unit_nav/nav_change_pct):

- rows in main not in bak:**0**(零 INSERT);rows in bak not in main:**0**(零 DELETE)
- fund_code/date/fund_name/unit_nav/prev_unit_nav/nav_change_pct 差异:**全 0**
- **仅 acc_nav 列差异:277,819 行**(= 报告 10 天全量 252,562 + 9-17 单日 25,252 + 5 行语法验证 = 报告行数的精确相加)
- 差异行仅落在 11 个目标日期内(逐日分组核对,无一日溢出)
- 损坏残留原样保留:9-17=21 / 9-21=23 / 9-23=25 / 9-24=54,与 bak 值逐位相等(UPDATE 的 acc_nav IS NULL 条件确实没覆盖已有值)
- unit_nav 11 天非空数与报告 §6 声称基线逐位一致(25267/25262/25278/26087/25292/25299/25320/26164/25313/24355/24353)

**结论:UPDATE 只写了 acc_nav 的 IS NULL 位,其它列/其它日期/行集零变动——报告 §2/§6 自证我复算全对。**

## 3.1 fix 表 ↔ 主库全量对账(拦截正确性)

将主库 11 天全量 286,839 行拉回本机与中间表 /tmp/accnav_fix.db(fix 277,949 行)逐 (date, fund_code) 比对:

- **MISS = 0**:fix 有非空值但主库仍 NULL 的行数 = 0(三层防护无误拦)
- **MISMATCH = 0**:主库非空 acc_nav 与 fix 值不符 = 0(写入值=拉取值,逐位一致)
- main 非空但 fix 无对应 = 17 行,全在 9-24 = 54 行损坏残留中接口无值者(fix 表本来就没有这些值,合法)
- unit_nav 也顺带比对:主库 11 天 unit_nav 与报告基线一致(见 §3)

## 4. NaN 拦截正确性(009303/009386)

fix 表中 (20260921, 009303)/(20260921, 009386) 两行 acc_nav = NULL(接口 NaN → Python float(nan) → sqlite 落 NULL);
主库这两行 9-21 保持 acc_nav = NULL(全表对比中既不在 MISS 也不在 MISMATCH),证:UPDATE 的 EXISTS(acc_nav IS NOT NULL)
条件正确拦截了 NaN,主库该行确实无污染;同时 9-15 两行主库 NULL + fix 无行(接口当日也无值),无漏写。

## 5. 备份可恢复性

- `public_fund.db.bak-20261003_104704`(2.67GB):md5=53df2a5d7face1d83c348deebc090cc8(与报告 STEP2 一致,=补前原库),
  可打开,行数 22478032,11 天 acc 非空=补前基线(0/0/21/0/23/0/25/54/0/0/0)✓
- `public_fund.db.wal-20261003_104704.bak`(2.67GB):文件头="SQLite format 3"(虽名 .wal-,实为**完整 DB 快照**),
  可打开,**PRAGMA quick_check = ok**,行数 22478032,11 天 acc=补前基线 ✓(与 cp 备份内容一致)
- 报告 §5 回滚命令 `cp "$DB.bak-20261003_104704" "$DB"` 实际可执行(备份已验证可打开可读,回滚后再跑 deploy 同步三库);
  R2 回退路径 /tmp/nav_bucket_bak_20261003_150704 在位(256 桶),未删。
- 仅验证+干跑,未执行任何写入。

## 6. 12 只 fail 的独立定性(重点)

独立重拉 306 只候选(progress 有记录但 fix 无行的代码)重新分类:

**12 只 = 11 只接口空返回(EMPTY)+ 1 只解析异常(EXC)**,重拉结果与拉取时同源一致,无一能在重拉时取到数据:

| 代码 | 定性 | 线上展示位状态(R2 nav_bucket 桶内) |
|---|---|---|
| 005471/005792/006922/019738/019739/021487/021834 | 接口 EMPTY | 桶内 nav=0 行;主库全史 43 行 unit/acc 双 NULL(占位行,从不展示) |
| 010813(华安添益一年持有混合A,持有期债基) | 接口 JS 解析异常(返回面页无累计净值走势数组) | 桶内 1221 行止于 2026-07-14,acc 恒 None;主库 11 天无行 |
| 180303/508059/508066/508097 | 接口 EMPTY | 桶内行止于 2025-06/2026-07,acc 恒 None;主库 11 天无行 |

**结论:12 只 = 「本来就没有的数据」,不是「该有却没补上」。**
- 接口(天天基金累计净值走势,补数唯一数据源)对这 12 只 11 天无任何可取值(重拉验证),主库自然无行可补;
- 其中 7 只主库有占位行但 unit/acc 双 NULL,前端本来就渲染不出净值,不存在"展示位缺 acc"的情形;
- 与 9-21 的 2 只(009303/009386)NaN 拦截**非同类**:后者是接口有响应但值=NaN 被防护拦截,前者是接口无数据;
  §23.15「上线必须完整版」口径:完整版覆盖=「所有 interface 可补者已补」,12 只不属"可补未补",不构成残缺版。
- 报告 §0「fail12=0.045%」数字与我重算一致(12/26458=0.0454%)。

## 7. 线上独立验证(R2,避开被审方/调研方全部抽过的代码)

另选 5 只(000003/000004/000005/000006/000008,5 个不同桶 a4/11/7e/eb/c5,均未被任何此前报告抽过):

- R2 `https://ss.fx8.store/r2/nav_bucket/{b}.json` 桶内 11 天 acc 值 vs 主库本地 dump 286,839 行比对:**55/55 逐位一致(0 mismatch)**
- 连续性锚点:老快照 R2 `fund_nav/000008.json`(clobber 前留存)9-17=2.3278/9-21=2.3834 与新桶**逐位一致**,
  000003 9-17=1.196/9-21=1.199 亦逐位一致 → **补回的值就是 clobber 前的原始值**,非编造;9-15/16 老快照 acc=None
  (clobber 前就没有),补数后由接口补齐——与报告 §2 补前基线(9-15/16=0)口径吻合。
- CF 边缘缓存:5 桶全部返回新数据,无滞留旧快照(§22 缓存一致性对本次抽样通过)
- 前端展示路径核实:static-site/app.js 读 `nav_bucket/{b}.json` 桶内 payload[date, unit_nav, acc_nav],acc 允许 null;
  FNV-1a 桶算法前后端同构(§5.4⑦ 防第二份实现漂移,前端注释明示"必须与 export_fund_nav._fund_bucket 同构")

## 8. §5.4⑦ 复现脚本同源检查

- 云上实跑脚本 /tmp/accnav_update.py md5 = 8d52901cd176ec7c95534ecbefd9658c = commit 版 accnav_backfill_update.py md5 **逐字一致**(不存在"跑的不是审的")
- UPDATE 脚本与拉取脚本(repro_backfill_accnav.py)职责分离:拉取写 fix 中间表 /tmp/accnav_fix.db(幂等 INSERT OR IGNORE),
  UPDATE 只按 fix 写主库空位;两者无重复实现同一逻辑,无静默漂移面。
- export_fund_nav.py(云上)= 读主库直出桶(无前端重算逻辑),前端桶算法与后端 _fund_bucket 同构已核(见 §7)。

## 9. stage0-nav 复发风险(前瞻)

云上 app/collector/public_fund.py L1131-1140:stage0-nav 已改 UPSERT,
`ON CONFLICT(date, fund_code) DO UPDATE SET unit_nav=excluded.unit_nav, nav_change_pct=COALESCE(...)`——**冲突更新不写 acc_nav**,
10-09 01:43 下次定时运行不会二次踩踏补上的 acc_nav。根治在位 ✓。

## 10. 时点安全

10-03 周日休市;deploy 15:34-15:58 与 15:35/16:00/17:50/20:35/22:00 盘后时点无重叠 ✓。
注:16:01 pf-score-daily 写主库 fund_score 属常规管线(见 §1),非本次动作引发,且不写 acc_nav。

## 11. 被审方报告如实性总评

报告 §0/§2/§3/§4/§5/§6 的数字与复算一致;§8 诚实标注(12 只 fail/未穷举单只对账/中间表与参考值差异/备份被 rsync 带进副本)
全部属实。唯一需更新:§3「三库 md5 逐位一致」为验收时点事实,复核时主库已被 16:01 评分管线追写(§1)。

## 复现段(命令 + 预期)

```bash
# 1) 三库 md5(复核实况:主库 c20a0bd0...,另两库 37aaa79c...)——预期需以复核实况为准,已过时的 37aaa79c 三库一致不再成立
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 "md5sum /home/ubuntu/code/trade-data/data/public_fund.db /home/ubuntu/code/trade-data-signal/data/public_fund.db /home/ubuntu/code/trade-data-signal-staticdata/db/public_fund.db"

# 2) 11 天 acc_nav 非空行数(三库相同;预期:25281/25276/25278/26110/25284/25306/25308/26114/25327/24347/24311,全表 22478032)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 "python3 -c \"import sqlite3;c=sqlite3.connect(\\\"/home/ubuntu/code/trade-data/data/public_fund.db\\\");
[print(r) for r in c.execute(\\\"SELECT date, SUM(acc_nav IS NOT NULL) FROM fund_daily_nav WHERE date BETWEEN 20260915 AND 20260930 GROUP BY date ORDER BY date\\\")]\""

# 3) 只改 acc_nav 独立验证(rowid 全表对比;bak=补前字节级副本;预期:仅 acc_nav 列 277819 行差异,其余列/行集 0)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 "python3 -c \"import sqlite3;c=sqlite3.connect(\\\"/home/ubuntu/code/trade-data/data/public_fund.db\\\");
c.execute(\\\"ATTACH DATABASE ['/home/ubuntu/code/trade-data/data/public_fund.db.bak-20261003_104704'] AS bak\\\");
[print(r) for r in c.execute(\\\"SELECT SUM(CASE WHEN m.acc_nav IS NOT b.acc_nav OR (m.acc_nav IS NULL)!=(b.acc_nav IS NULL) THEN 1 ELSE 0 END) FROM fund_daily_nav m JOIN bak.fund_daily_nav b ON m.rowid=b.rowid\\\")]\""
# (上面仅示意简版;完整 7 列对比见报告 §3,本机脚本 /tmp/reviewer-accnav/)

# 4) 备份可恢复性(预期:两备份数均=22478032,quick_check=ok,11 天 acc=补前基线 0/0/21/0/23/0/25/54/0/0/0)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 "python3 -c \"import sqlite3;b=sqlite3.connect(\\\"file:/home/ubuntu/code/trade-data/data/public_fund.db.bak-20261003_104704?mode=ro\\\",uri=True);
print(b.execute(\\\"SELECT COUNT(*) FROM fund_daily_nav\\\").fetchone());print(b.execute(\\\"PRAGMA quick_check\\\").fetchone())\""

# 5) R2 线上抽样(浏览器 UA 必需;预期:桶内 11 天 acc 与主库逐位一致)
curl -s -A "Mozilla/5.0" https://ss.fx8.store/r2/nav_bucket/a4.json | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['000003']['nav'][-5:])"

# 6) 云端实跑脚本=commit 版(预期:两 md5 相同)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 "md5sum /tmp/accnav_update.py"  # 8d52901cd176ec7c95534ecbefd9658c

```
