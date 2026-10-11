# B3 fund_nav 清理返修 复审报告 — #111(2026-10-11,reviewer 二轮独立复审)

> 残留后台任务:**无**(本次全程无 `moved to the background (ID:`;所有命令均在生效 timeout 内前台完成)。
>
> 审查对象:分支 `feat/b3-fundnav-cleanup`,tip **`5bae7c68e`**(=merge origin/main 6f635df65 后);返修 commit `344a53237`(父 `02081eb64`,FF 推送成立)。
> 复审依据:前审 `next-steps-b3-review-20261011.md` **§2 复核放行标准**(修正项 1-2 必须 / 3-4 建议)+ 实施返修说明。
> 审查方式:静态读码 + 只读实测(本地 `ls/find/gzip/shasum`、云上只读 `ssh ls/grep`、线上只读 `curl`、**R2 备份桶真实 LIST + 实测取回**);**零写零删、未执行任何写路径脚本(restore 仅写 /tmp --target)**;curl 无 -v/-i。
> **一句话:前审 §2 点名的 4 项修正全部闭合(1-2 必须项逐条实物核过);merge 无 B6/B7 回退;既有工具未被触碰。判定:PASS。**

## 0. 总判定:PASS(0 must-fix)

| # | 复审点(前审 §2 口径) | 独立复核 | 判定 |
|---|---|---|---|
| 1 | 修正① 计数口径闭合(表 7 行 = 1 R2+6 磁盘树,自洽) | exec §2 表 7 行 + 合计行 + §0/§3-a/§3-f 同步 + 勘误保留原表述 | **闭合** |
| 2 | 修正② 残树处置闭合(双线:删除实物 + 备份链前提 + §25 证据) | mac 残树 GONE / 备份链结论读码成立(含 mac 历史实跑实证)/ 清单 MISSING=0 独立重放 + 备份现物 5/5 件重放 + sha256 复现 | **闭合** |
| 3 | 修正③ verify 报告勘误注 | +3 行勘误注(off-by-one + 「漏 3 处」不自洽一并勘误),原表述保留 | **闭合** |
| 4 | 修正④ 审计归档 | README sha256 6/6 + 计数 5/5 全对账;gzip -t 4/4 过;/tmp/b3 GONE | **闭合** |
| 5 | merge 无回退扫描(关键) | diff vs main = 11 文件全 B3 相关 / 524 insertions / **0 deletions**;B6/B7 与 main 逐位一致(0 diff);工具 0 diff | **PASS** |
| 6 | exec §7 自核与实际一致 + 返修 diff 范围一致 | §7 两行 PASS + 终态复验 4 项全独立核过;344a53237 9 files 与返修说明吻合 | **PASS** |

**放行结论:按前审 §2 标准全部闭合,建议主控走 `scripts/main-merge.sh` 合入。**

## 1. 修正①(计数口径)闭合 — 逐字核

- exec §2 表 = **7 行**:①R2 前缀 + ②云上 REPO + ③云上 GIT_REPO + ④云上 staticdata + ⑤mac REPO + ⑥mac GIT_REPO + **⑦mac staticdata(二轮返修补删,10:49)**;L67 合计 = 「**6 磁盘树 + 1 R2 前缀 = 7 处**」⇒ 1 R2 + 6 磁盘树,与表 7 行**自洽**。
- §0(L36)「7 处删除 | 全删完(6 磁盘树 GONE + R2 前缀 0;轮一 5 树 + 轮二 ⑦ mac staticdata)」✓;§3-a(L93)逐处枚举「②③④云上 3 树、⑤⑥ mac 2 树、⑦ mac staticdata」= 6 树 ✓;§3-f(L98)「6 磁盘树全 GONE(含二轮⑦)」✓。
- 勘误履历:L11 顶部勘误块 + L69 表下勘误注**均保留原表述**(「原文本行写『7 处删除完成』,但 §2 表列仅 6 行…off-by-one」「原表仅 ①~⑥ 六行…现 7 行 = 1 R2 + 6 磁盘树」)⇒ 可反查 ✓。返修说明勘误 1 同款保留 ✓。

## 2. 修正②(残树处置)闭合 — 双线独立复核

### 2a. 残树删除核实物(实测)
- `ls -d /Users/linhuichen/code/trade-data-signal-staticdata/data/fund_nav` → **No such file or directory(GONE)** ✓。
- 回退保险 `…-old-20260926/data/fund_nav` **仍在**(26,370 文件)✓(与 memory `staticdata-old-mirror-keep-decision` 保留至 2026-10-30 一致,勿动)。
- mac 全盘残树复查(4 根,maxdepth 9,`find -name fund_nav -type d`)= **仅剩 …-old-20260926 一处**(与 exec §5 声称一致)✓。
- 现役镜像其余部分抽核未动:mac staticdata `data/overview.json`、`data/intraday_snapshot.json` 在位;mac trade-data `static-site/data/` 288 项在位。

### 2b. 备份链核查结论独立复核(读码 + 历史实证)— 结论成立
1. **排列顺序**:`staticdata_backup_async.sh` **段1(锁外,L115-220)** = rsync 全量 JSON(L158)→ step3.5a(.gitignore)→ **step3.5b upload-large-json(L182-210)**;**写权限守卫 `staticdata_write_guard.py --check-write-auth` 在段2(git 段)最前** L251,注释 L242-243 自证「调用点 = git 段最前(rsync 段已跑完…)」。⇒ **R2 上传在守卫之前,守卫不拦 R2** 成立 ✓。
2. **mac 可执行面无阻断**:`upload-large-json` ∈ `_PRIVATE_ONLY_CMDS`(upload_r2.py L92)⇒ `_is_public_bucket_write()`=False ⇒ 本机 export-guard L2(只拦公共桶写)不适用;且 ∈ `_A_CLASS`(L65)⇒ `guard_repo_default` A 类白名单放行。默认桶 = `BACKUP_BUCKET = os.environ.get("R2_BACKUP_BUCKET", BACKUP2_BUCKET)`,BACKUP2=**signal-backup2**(L288/L301)✓。
3. **mac 历史实跑实证(强于推演)**:`trade-data/data/logs/staticdata_backup_async_2026092*.log` 4 个在位,其中 **09-25 22:42 / 09-26 13:25 / 09-26 14:51 三次日志含「[step3.5b large-json R2 上传] ✓」= 在 mac 上真实执行过 R2 上传**(09-26 18:00 一次为 SKIP 钩子跳过)⇒ 「mac 跑会真写 signal-backup2」非纯理论。
4. **覆盖机理**:上传 key = `large-json/<rel>.gz` 固定前缀(唯一副本);幂等 = HEAD ETag 比对(L3093-3095),**内容没变跳过、内容变即 PUT 覆盖同 key** ⇒ mac 09-11 旧代际 vs 云上 09-22 正本内容不同 ⇒ ETag 不命中 ⇒ PUT 覆盖正本,**结论成立**。
- ⇒ 该残树确在 mac staticdata 备份源面内(第 3 步触发源 + 第 4 步覆盖),前审「删该树消风险」的正当性前提**复核成立**;exec §6.7 已如实上报「机制本身仍在(建议给 step3.5b 加非生产机 R2 上传守卫)」= 正确处置。

### 2c. §25 备份验证证据复核
- **清单比对 MISSING=0(独立重放)**:归档 `mac_staticdata_names.txt.gz`(26,370 名,+.gz 归一化)∖ 备份 26,458 key = **0**;备份 ∖ mac = **88**(方向与 verify §1.2 一致)✓;主桶删前 26,458 名称集 = 备份集(双向差集 0)✓。
- **抽样 5 件「共有 unit_nav 逐位一致」可信度**:备份现物**逐件实测取回重放,5/5 数字逐位吻合** exec §3.1 表「备份条数/备份末日期」两列 — 000001:1269/20260921;**009774:1269/20260921;017525:899/20260921;024767:263/20260921;970205:938/20260921**。sha256 复现 4 件全等于 verify §4 表:000001=`953ac5a3…294af27c`、017577=`4904d616…26db957`、970205=`7a33654c…7c71f3a1b`、027213=`2d686a53…e1b5028c`。
  - **限制诚实标注**:mac 侧数字(1263/893/257/932…)与 mac↔备份的「逐位比对」过程本身**不可重放**(mac 源树已删);可信度由「备份现物全量可重放 + 清单 MISSING=0 + 5/5 数字吻合」三重支撑,判定**可信**。
- **诚实标注(口径)**核查:exec §3.1 表下注「mac 树 = 09-11 旧代际,备份 = 09-22 新代际(严格超集)⇒ **非逐位同一份**(逐文件 md5 不同:000001 mac 30,353B vs 备份取回 30,497B)」— 备份侧 30,497B 实测吻合 ✓,标注如实(未拿「快照≠更新超集」冒充逐位相同)✓。
- **恢复路径(§25④)写明且可执行**:`signal-backup2` 桶 `large-json/fund_nav/<code>.json.gz` + `bash scripts/restore-large-json.sh fund_nav/<code>.json --target <树>/static-site/data`(exec §4 六树 `--target` 全列出);**本次实测执行取回 6 件,6/6 成功**,000001 取回 sha256 = 归档样本 = verify 表(逐位一致)✓。
- **备份现物真实存在**:独立直连 LIST `signal-backup2 large-json/fund_nav/` = **26,458 objs / 2,643,222B JSON**;且与归档 `r2_backup_post.json.gz`(10:00)逐条比对(key+size+mtime)**only_now=0 / only_arch=0 / value_diff=0** ⇒ 备份桶自 10:00 至 11:04 **零漂移**(「备份未动」从「数目相等」升格为逐条全等)✓。

## 3. 修正③(verify 报告勘误注)闭合

- `git diff 344a53237^..344a53237 -- docs/ops/next-steps-b3-verify-20261011.md` = **+3 行**(L34-35 勘误注 + 空行),位于 §1.1 表后:
  - L34:off-by-one 勘误(原列 ①~⑥ 六行 = 1 R2+5 磁盘树 vs 合计「6 磁盘树」)+「真相 = mac 第 3 棵残树未被发现、补为第 7 项后 7 行 = 1 R2+6 磁盘树与合计自洽」;
  - L35:「头『漏 3 处』与 §7.1 只列 2 项亦不自洽,一并勘误」✓。
- 原表述(表 6 行 + 头注 + 合计行)**原文保留**,勘误注叠加 ⇒ 可反查 ✓。

## 4. 修正④(审计归档)闭合 — 逐件对账

`docs/ops/b3-fundnav-audit-20261011/` 7 文件;README 声称**独立重算全部对上**(未压缩源件口径,`gzip -dc | shasum`):

| 文件 | README 声称 sha256 | 重算 | 计数核 |
|---|---|---|---|
| r2_fund_nav_pre.json.gz | dee44986… | **逐位一致** | 26,458 ✓ |
| r2_backup_post.json.gz | fb31cdcf… | **逐位一致** | 26,458 ✓ |
| r2_fundnav_post.json | 4f53cda1… | **逐位一致** | 内容 `[]` ✓ |
| r2_navbucket_post.json.gz | 6e36d17f… | **逐位一致** | 256 ✓ |
| restore_test_fund_nav_000001.json | 953ac5a3… | **逐位一致** | 30,497B ✓ |
| mac_staticdata_names.txt.gz | f9dff777…d443bc55 | **逐位一致** | 26,370 行 ✓ |

- `gzip -t` 4 件全过 ✓;清单文件行数 vs README 计数 5/5 对账 ✓;**/tmp/b3 已 GONE** ✓。

## 5. merge 无回退扫描(关键)— 逐项

- `git diff 6f635df65..5bae7c68e --stat` = **11 文件 / 524 insertions / 0 deletions**,全部 B3 相关:B3 工具 1(scripts/r2_delete_prefix.py)+ B3 报告 3(exec/review/verify)+ 审计归档 7。**无任何其他文件被减/回退**。
- **B6 修复逐位一致**:`git diff 6f635df65:scripts/upload_r2.py 5bae7c68e:scripts/upload_r2.py` = 0 行 ✓;**B7 修复逐位一致**:同法 `scripts/tests/test_245_l2_budget_digest_20261010.py` = 0 行 ✓。
- **B3 工具未被触碰**:`r2_delete_prefix.py` 在返修 commit 344a53237 中 0 改动;与轮一 `a88094c97` 版逐位一致(0 diff)⇒ 前审「工具安全设计 PASS」结论继续有效,无需重审。
- 分支独有 commit 链(相对 main)= `a88094c97`(轮一实施)→ `02081eb64`(前审报告落档)→ `344a53237`(返修)→ `5bae7c68e`(merge)⇒ 与任务书「02081eb64..5bae7c68e FF 推送」一致 ✓。

## 6. exec §7 自核一致性 + 返修 diff 范围

- §7 自核表两行(§2.1/§2.2)声称「PASS 闭合」= 本次复核实测之结论一致 ✓。
- §7 终态复验 4 项全部独立核过:R2 `fund_nav/` 线上 404(`ssd`×2 + `ss` CF /r2/ 全 404)✓;`signal-backup2` LIST = 26,458 ✓;`nav_bucket/ca.json` = 200 ✓;mac find 仅余保险树 ✓。
- 返修 commit `344a53237` = 9 files(docs 归档 7 + exec +108/-10 + verify +3),与「返修说明」描述(计数勘误+补删+归档+勘误注)吻合 ✓。
- 附带独立复核:exec §1/verify §4 声称的 manifest(云上 staticdata `docs/large-json-backup-manifest.md`,2026-10-11 05:31,6,055,904B)已 ssh 只读实测:`grep -c fund_nav` = **26,458 行** ✓ 属实;云上 3 树(②③④)独立 ssh `ls -d` 全 GONE ✓。

## 7. 低分项(<80)已滤 4 个

1. verify 报告「fund_nav/027213.json(最小 211B)」与实际不符(备份 gz=206B / 解压=204B)——约 50,pre-existing 非本次返修范围,sha256 逐位一致已锤内容;建议顺手勘误。
2. `/tmp/b3fix_post_backup.json`(二轮过程临时物)未被清——约 25,非修正④点名对象(/tmp/b3 已 GONE),建议主控顺手清。
3. verify §1.1 勘误注「补为第 7 项后 7 行」主语指 exec 表(本表未补行⑦),文本微歧义——约 50,勘误注已注「见 exec 报告」,可不改。
4. 本机无 manifest 文件(manifest 在云上),mac 侧 restore 会打印「跳过 sha256 比对」降级——约 25,环境差异非缺陷(脚本有提示、非静默;数据本体实测正确)。

## 8. 复现命令(本次复审用,全只读;restore 仅写 /tmp)

```bash
# 分支/merge 扫描
git log --oneline -5; git rev-list --parents -n 1 5bae7c68e
git diff 6f635df65..5bae7c68e --stat                        # 11 files / +524 / -0
git diff 6f635df65:scripts/upload_r2.py 5bae7c68e:scripts/upload_r2.py | wc -l   # 0(B6)
git diff 6f635df65:scripts/tests/test_245_l2_budget_digest_20261010.py 5bae7c68e:scripts/tests/test_245_l2_budget_digest_20261010.py | wc -l  # 0(B7)
# 残树/保险树
ls -d /Users/linhuichen/code/trade-data-signal-staticdata/data/fund_nav        # GONE
ls /Users/linhuichen/code/trade-data-signal-staticdata-old-20260926/data/fund_nav | wc -l   # 26370(勿动)
find /Users/linhuichen/code/trade /Users/linhuichen/code/trade-data /Users/linhuichen/code/trade-data-signal-staticdata /Users/linhuichen/code/trade-data-signal-staticdata-old-20260926 -maxdepth 9 -name fund_nav -type d   # 仅 old 保险树
# 备份现物(只读 LIST + 取回)
/Users/linhuichen/code/trade/.venv/bin/python scripts/r2_list_prefix.py signal-backup2 "large-json/fund_nav/" /tmp/b3fixreview_bk_list.json   # 26458
bash scripts/restore-large-json.sh fund_nav/000001.json --target /tmp/b3fixreview_restore   # 成功 1/0
shasum -a 256 /tmp/b3fixreview_restore/fund_nav/000001.json   # 953ac5a3…294af27c(=归档=verify §4 表)
# 归档对账(gzip 后未压缩口径)
gzip -dc docs/ops/b3-fundnav-audit-20261011/r2_backup_post.json.gz | shasum -a 256   # fb31cdcf…
gzip -dc docs/ops/b3-fundnav-audit-20261011/mac_staticdata_names.txt.gz | wc -l      # 26370
# 云上(只读)
ssh -i ~/tdsignal.pem -4 ubuntu@122.51.111.173 'ls -d /home/ubuntu/code/trade-data/static-site/data/fund_nav /home/ubuntu/code/trade-data-signal/static-site/data/fund_nav /home/ubuntu/code/trade-data-signal-staticdata/data/fund_nav'   # 全 GONE
ssh ... 'grep -c fund_nav /home/ubuntu/code/trade-data-signal-staticdata/docs/large-json-backup-manifest.md'   # 26458
# 线上(只读)
curl -s -o /dev/null -w '%{http_code}\n' --max-time 20 https://ssd.fx8.store/fund_nav/000001.json   # 404
curl -s -o /dev/null -w '%{http_code}\n' --max-time 20 https://ss.fx8.store/r2/fund_nav/000001.json  # 404
curl -s -o /dev/null -w '%{http_code}\n' --max-time 20 https://ssd.fx8.store/nav_bucket/ca.json      # 200
```

---
> 报告人:reviewer(独立于实施 agent;结论均基于本次只读实测与逐字读码,未采信自述)。§21 公示:N/A(无算法改动)。§22:nav_bucket 唯一现役 serving 源未动(256/R2 + 线上 200),无多展示位不一致。
> 交接:复审 PASS,建议主控 `scripts/main-merge.sh feat/b3-fundnav-cleanup` 合入;低分项 1-2 可由主控顺手处理(非阻断)。
