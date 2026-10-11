# B3 fund_nav 遗留清理执行报告 — #111(2026-10-11)

> 残留后台任务:**无**(全程无 `moved to the background (ID:`;所有命令均在生效 timeout 内前台完成)。
>
> 任务:next-steps-plan §1 B3 执行(先 tester 验证 → implementer 清理)。方案 v2.1 / #111,2026-10-11 用户拍板开工。
> 执行:implementer(role-implementer);分支 `feat/b3-fundnav-cleanup`(从 origin/main 切)。
> 依据:清理前验证报告 `docs/ops/next-steps-b3-verify-20261011.md`(判定 **可清理 PASS**,§25 备份核验通过)。
> 时间窗:轮一 09:57~10:00 CST + **轮二(返修)2026-10-11 10:40~10:50 CST**,均**早于 16:00 目标**;避 22:30 update_all rsync 时点,避 22:00-01:30 R2 写窗。
> **总体判定(二轮返修后):7 处删除完成(1 R2 前缀 + 6 磁盘树),自验 a-f 全过。**
>
> ⚠️ **勘误(2026-10-11 二轮,依据独立审查 §2)**:原文本行写「7 处删除完成」,但 §2 表列**仅 6 行(1 R2 + 5 磁盘树)**——**off-by-one**(verify 源头、exec 继承);真相 = mac 存在**第 3 棵同类残树**未列未删。二轮返修补删该树(§2 行⑦),表列补齐为 7 行后计数自洽。详见下「返修说明」段。

## 返修说明(2026-10-11 二轮,依据独立审查 `next-steps-b3-review-20261011.md` §2)

> 审查总判定「不通过」,点名两处**必须**改:①计数口径与表列不自洽 ②mac staticdata 同类残树未列未删未声明。本段为返修结论 + 修正履历(原表述保留可反查)。

### 勘误 1(计数口径,必须项)
- **原表述**:「7 处 = 6 磁盘树 + 1 R2」;§2 表列仅 6 行(①R2 + ②③④⑤⑥ = 1 R2 + **5 磁盘树**)⇒ 文字「6 磁盘树」在表中**无第 6 项**,off-by-one。
- **根因**:mac 存在**第 3 棵**同类残树 `/Users/linhuichen/code/trade-data-signal-staticdata/data/fund_nav`(26,370 文件/574M/09-11 代际)——与云上④同类(staticdata 仓 `data/fund_nav`),审查前未被发现,故表漏一行、「6 磁盘树」口径缺第 6 项。
- **处置**:二轮返修补删该树(见勘误 2),§2 表补齐**行⑦**;现表列 **7 行 = ①R2 + ②③④⑤⑥⑦ 6 磁盘树**,与「7 处 = 6 磁盘树 + 1 R2」计数**一致**。

### 勘误 2(mac staticdata 同类残树,必须项)
- **发现**:`/Users/linhuichen/code/trade-data-signal-staticdata/data/fund_nav`,**26,370 文件 / 574M / 09-11 代际**(与已删 ⑤⑥ 同代同族),审查指出**未列、未删、未声明**。
- **备份链核查(item 2a,结论=链路风险真实存在)**:该树**确在 mac staticdata 备份源面内** → step3.5b `upload-large-json` 从 `STATICDATA_REPO/data/`(=`large_json_excludes.py` DIR_EXCLUDES 含 `data/fund_nav`)gzip 上传 `signal-backup2/large-json/fund_nav/`;`upload-large-json` 属 `upload_r2.py:_PRIVATE_ONLY_CMDS`(本机允许跑,只写私有桶 signal-backup2);写权限守卫 `staticdata_write_guard.py` 在**段2(git 段,在 R2 上传之后)**⇒ **不拦 R2 上传**;且 mac 历史确跑过该脚本(`trade-data/data/logs/staticdata_backup_async_2026092[56]_*.log`,09-25/09-26 四次)⇒ **若 mac 再跑该脚本,会把 09-11 旧代际 PUT 覆盖 signal-backup2 的 09-22 正本**(结构风险成立)。**删该树即一并消除此风险**。
- **备份覆盖复核(item 2b)**:见 §3.1(清单比对 MISSING=0 + 抽样内容子集覆盖,结论 PASS)。
- **处置**:备份验证通过 → **二轮返修补删**(限 16:00 前,实测 10:49 完成);§2 表补行⑦、§4 补恢复路径、§5 补复现命令、§6 同步。

### 勘误 3(「全删/全空」表述,必须项附带)
- **原表述**:「7 处全空」/「6 树 GONE」(§0/§3-a)。
- **改准**:截至二轮返修,清单内 **7 处全灭**(①R2 前缀 0 + 6 磁盘树 GONE)属实;**唯一「仍在」的 fund_nav 树 = `trade-data-signal-staticdata-old-20260926/data/fund_nav`(26,370)**——已拍板保留的**回退保险**(至 2026-10-30,memory `staticdata-old-mirror-keep-decision`),**故意不动**,非遗漏。

## 0. 结论速览

| 项 | 结果 |
|---|---|
| 7 处删除 | **全删完**(6 磁盘树 GONE + R2 前缀 0;轮一 5 树 + **轮二 ⑦ mac staticdata**) |
| 删后自验 a-f | **全 PASS**(见 §3;二轮补 §3.1 备份验证) |
| large-json 备份 | **未动**(26,458 obj,抽样 sha256 逐位一致) |
| nav_bucket 现役链 | **未动**(256 obj) |
| 线上变化 | `ssd.fx8.store/fund_nav/000001.json` → **404**(预期,D2 前端缓动观察面) |
| 新增工具 | `scripts/r2_delete_prefix.py`(dry-run + --yes 门控 + 白名单硬校验) |

## 1. §25 四件之一:备份验证(引用清理前报告,不重复)

本任务删除前的前置条件 = §25「备份验证通过」,由验证报告承担,此处**引用**(原文 `docs/ops/next-steps-b3-verify-20261011.md` §4):

- R2 `signal-backup2` `large-json/fund_nav/` = **26,458 obj / 110,870,643 B**,与 fund_nav/ 名称集合**差集 0**。
- 抽样取回 sha256 **4/4 逐位一致**(首/中/尾/最小边界),含 manifest 记录比对。
- manifest:staticdata 仓 `docs/large-json-backup-manifest.md`(2026-10-11 05:31 刷新,fund_nav 行 26,458 行,「永久(唯一副本)」档位)。
- 上传侧:2026-10-11 05:31 `staticdata_backup_async` → `large-json 上传 31675/31675 -> signal-backup2/large-json/`(全过,0 失败)。

⇒ 既有备份完整覆盖 26,458/26,458,删除前§25 条件满足。

## 2. §25 四件之二:删除清单(逐处计数 + 命令)

**删除前逐处复核(与验证报告数字逐位比对,全部吻合)**:

| # | 对象 | 删前计数 | 删后 | 手段 |
|---|---|---|---|---|
| ① | R2 主桶 `signal-data` `fund_nav/` 前缀 | **26,458 obj / 556,807,260 B** | **0 obj** | `r2_delete_prefix.py`(27 批 DeleteObjects) |
| ② | 云上 REPO 树 `/home/ubuntu/code/trade-data/static-site/data/fund_nav` | 26,458 | **GONE** | ssh `rm -rf` |
| ③ | 云上 GIT_REPO 树 `/home/ubuntu/code/trade-data-signal/static-site/data/fund_nav` | 26,458 | **GONE** | ssh `rm -rf` |
| ④ | 云上 staticdata 灾备树 `/home/ubuntu/code/trade-data-signal-staticdata/data/fund_nav` | 26,458 | **GONE** | ssh `rm -rf` |
| ⑤ | mac REPO 树 `/Users/linhuichen/code/trade-data/static-site/data/fund_nav` | 26,370 | **GONE** | 本地 `rm -rf` |
| ⑥ | mac GIT_REPO 树 `/Users/linhuichen/code/trade/static-site/data/fund_nav` | 26,370 | **GONE** | 本地 `rm -rf` |
| ⑦ | mac staticdata 灾备树 `/Users/linhuichen/code/trade-data-signal-staticdata/data/fund_nav` | 26,370 | **GONE** | 本地 `rm -rf`(**二轮返修补删**,2026-10-11 10:49) |
| — | 合计 | **6 磁盘树 + 1 R2 前缀 = 7 处** | 全删 | |

> **勘误(表)**:原表仅 ①~⑥ 六行(1 R2 + 5 磁盘树),与合计「6 磁盘树 + 1 R2」不自洽;二轮返修补入行⑦(mac staticdata),现 **7 行 = 1 R2 + 6 磁盘树**,与「7 处」自洽。

**未动对象(反证)**:

| 对象 | 删前 | 删后 |
|---|---|---|
| R2 `signal-backup2` `large-json/fund_nav/`(备份) | 26,458 | **26,458**(未动) |
| R2 `signal-data` `nav_bucket/`(现役) | 256 | **256**(未动) |

**删除顺序**:源侧→下游(⑤ mac REPO → ⑥ mac GIT_REPO → ② 云上 REPO → ③ 云上 GIT_REPO → ④ 云上 staticdata),R2 前缀 ① 随后。删前逐处 `ls | wc -l` / LIST 复核,与报告一致才删;**一致性不符即停**的要求满足(全程逐位吻合,未触停)。
**二轮返修删除顺序(⑦)**:单独一类(mac staticdata 灾备树),删前完成 §25 备份验证(§3.1)后 `rm -rf`,与轮一各树无先后依赖。

**为什么 6 树全删**:`deploy.sh` L529 与 `staticdata_sync.sh` L94 两处通用全量 rsync(**无 --delete、无 exclude fund_nav**)→ 只删下游会被源侧残留携带回填;6 树全删后 rsync 无源可带、不重生(验证报告 §2)。**未改 deploy.sh / staticdata_sync.sh / update_all / nav_bucket / 前端**(红线遵守)。

**R2 前缀删除实现**:新增 `scripts/r2_delete_prefix.py`(全 repo 原无删除能力)。
- 安全设计:①默认 dry-run(零写)②`--yes` 门控 ③**桶/前缀白名单硬校验**(ALLOWED 只含 `("signal-data","fund_nav/")`,其余 abort exit 2)④`--expect N` 计数闸门(不符 abort)⑤删后重 LIST 计数须 0(否则 exit 3)。
- 实现:SigV4 复用 `scripts/upload_r2.py:s3_request`(全项目同一签名/路由),POST `/?delete` 批量删(1000 key/批 + Content-MD5 + XML body)。
- 实跑:dry-run 先验 26,458 → 真删 27 批(前 26 批各 1,000 + 末批 458),**deleted=26,458 err=0**,删后 LIST=0。
- 将删对象清单落盘:`/tmp/b3/r2_fund_nav_pre.json`(26,458 条 key/size/mtime);**二轮已归档** `docs/ops/b3-fundnav-audit-20261011/r2_fund_nav_pre.json.gz`,/tmp 原物已清(修正项 4)。

## 3. §25 四件之三:删后验证证据(a-f)

| 项 | 检查 | 结果 |
|---|---|---|
| **a** | 7 处全灭 | R2 `fund_nav/`=**0**;**6 磁盘树逐处 GONE**(②③④云上 3 树、⑤⑥ mac 2 树、**⑦ mac staticdata(二轮)**);①R2=0 ✓。余一树 = `…-old-20260926/data/fund_nav`(**故意保留**的回退保险,见勘误 3)|
| **b** | large-json 备份未动 | LIST=`**26,458**`;抽样取回 `fund_nav/000001.json` sha256=`953ac5a3b43352bc…294af27c` = 报告记录值(**逐位一致**)✓ |
| **c** | 线上变化 | `https://ssd.fx8.store/fund_nav/000001.json` → **http_code=404**(预期,R2 直连前缀已删)✓ |
| **d** | nav_bucket 现役链未动 | R2 `nav_bucket/` LIST = **256 obj**(未动)✓ |
| **e** | deploy 闸门不坏 | 静态核 `scripts/check_data_integrity.py` `check_fund_nav` 查 `data_dir/"nav_bucket"`(L1220),与旧 `fund_nav/` 目录无关;其余引用(check_data_gap_alerts)读 DB 不读目录(引用验证报告 §6)✓ |
| **f** | 删后复查全 0 | 逐处复查:6 磁盘树全 GONE(含二轮⑦) + R2 前缀 0(**防删不全**)✓ |

## 3.1 二轮返修:mac staticdata 残树 备份验证证据(§25,item 2b)

> 对象:`/Users/linhuichen/code/trade-data-signal-staticdata/data/fund_nav`(26,370 文件 / 574M / 09-11 代际)。删除前逐项完成 §25「备份验证」:

**① 清单全量比对(MISSING=0)**:该树 26,370 文件名 vs 备份 `signal-backup2/large-json/fund_nav/` 26,458 key(名称集合比对):
- **mac 树 ∖ 备份 = 0(MISSING=0)**;备份 ∖ mac = 88(≥09-11 后新入基金,方向正确,与 verify §1.2 一致)。
- 清单源件落档 `docs/ops/b3-fundnav-audit-20261011/mac_staticdata_names.txt.gz`(26,370 行,sha256 `f9dff777…d443bc55`)。

**② 抽样取回(子集覆盖验证)**:抽样 5 只(首/¼/½/¾/尾),从备份 `restore-large-json.sh` 实测取回(成功 5/5),对比 mac 树:

| code | mac 条数 | 备份条数 | mac 末日期 | 备份末日期 | mac 日期⊆备份 | 共同日期 unit_nav 逐位 | mac 独有日期 |
|---|---|---|---|---|---|---|---|
| 000001 | 1263 | 1269 | 20260910 | 20260921 | ✓ | ✓ | 0 |
| 009774 | 1263 | 1269 | 20260910 | 20260921 | ✓ | ✓ | 0 |
| 017525 | 893 | 899 | 20260910 | 20260921 | ✓ | ✓ | 0 |
| 024767 | 257 | 263 | 20260910 | 20260921 | ✓ | ✓ | 0 |
| 970205 | 932 | 938 | 20260910 | 20260921 | ✓ | ✓ | 0 |

- **诚实标注(口径)**:mac 树 = **09-11 旧代际**,备份 = **09-22 新代际(严格超集)** ⇒ **非逐位同一份**(逐文件 md5 不同:如 000001 mac 30,353B vs 备份取回 30,497B)。故证据 = **清单覆盖 MISSING=0 + 内容子集覆盖(0 独有日期)**;**「无备份外独有内容」成立,删除不丢独有数据**(与 verify §1.2 同结论)。唯一内容差 = 末条 acc_nav 注记(值≈3.835 级,该日 DB 亦可再生,价值近零,verify §7.3 已记)。

**⇒ §25 判定:备份覆盖成立(数据可恢复)→ 验过直接删(§25③)。** 恢复路径见 §4。

**删前状态留痕**:`ls -ld` = dir 26,372 entry(26,370 文件)/ `du -sh` = 574M(587,984 KB)/ 最新 mtime 2026-09-11 18:34 / `find -type l` 无 symlink → 删后 `ls -d` = **No such file or directory**(GONE)。

## 4. §25 四件之四:恢复路径(怎么恢复)

数据内容已被 `signal-backup2` `large-json/fund_nav/` 完整覆盖(26,458/26,458,抽样逐位一致)。**逐树恢复命令**(工具 `scripts/restore-large-json.sh`,实测可调,报告 §5):

```
# 通用形式:$REPO 为 trade 仓,从任意目录跑
bash scripts/restore-large-json.sh fund_nav/<code>.json --target <目标树>/static-site/data
# 枚举/批量:
bash scripts/restore-large-json.sh --list         # 列可恢复项
bash scripts/restore-large-json.sh --all --target <目标树>   # 全量并集还原
```

| 目标树 | `--target` |
|---|---|
| ② 云上 REPO | `/home/ubuntu/code/trade-data/static-site/data` |
| ③ 云上 GIT_REPO | `/home/ubuntu/code/trade-data-signal/static-site/data` |
| ④ 云上 staticdata | `/home/ubuntu/code/trade-data-signal-staticdata/data` |
| ⑤ mac trade-data | `/Users/linhuichen/code/trade-data/static-site/data` |
| ⑥ mac trade | `/Users/linhuichen/code/trade/static-site/data` |
| ⑦ mac staticdata(二轮) | `/Users/linhuichen/code/trade-data-signal-staticdata/data` |

- 本地实测(本次):`bash scripts/restore-large-json.sh fund_nav/000001.json --target /tmp/b3/restore_test` → 成功 1 / 失败 0,sha256 逐位一致。
- ⚠️ **注1(脚本无 x 位)**:`restore-large-json.sh` 权限 0644,须 `bash scripts/...` 调用(`./` 直跑需 chmod +x)。
- ⚠️ **注2(R2 前缀恢复 = 缺口,如实记)**:**不存在**把 per-code 重新 PUT 回 R2 `fund_nav/` 旧前缀的现成命令(`upload-fund-nav` 现役已改传 `nav_bucket/`)。若未来要恢复 R2 `fund_nav/` 前缀服务面,需临时脚本 GET(large-json)→解压→循环 PUT(无现成通道)。此为「服务面恢复」缺口,**非「数据丢失」缺口**——数据本体已完整备份。
- ⚠️ **注3(mac 旧代际)**:mac 2 树为 09-11 旧代际(26,370 ⊂ 26,458,无独有文件/独有日期,抽样核实);若需恢复,`--all` 会还原为 09-22 新代际(26,458),不还原旧代际差异——差异价值近零,验证报告 §7.3 已记,不建议单独立项。

## 5. 复现命令

> 注:下列 `/tmp/b3/*` 路径 = **轮一实跑**的审计产物路径(命令可重跑);其清单产物**二轮已归档** `docs/ops/b3-fundnav-audit-20261011/`,/tmp 原物已清(修正项 4)。

```bash
# 清理前计数复核(与报告比对)
/Users/linhuichen/code/trade/.venv/bin/python scripts/r2_delete_prefix.py --bucket signal-data --prefix fund_nav/ --expect 26458 --out /tmp/b3/r2_fund_nav_pre.json   # dry-run
ssh -i ~/tdsignal.pem -4 ubuntu@122.51.111.173 'ls /home/ubuntu/code/trade-data/static-site/data/fund_nav | wc -l'   # 26458(× 3 树)
ls /Users/linhuichen/code/trade-data/static-site/data/fund_nav | wc -l   # 26370(mac × 2 树)

# 真删
/Users/linhuichen/code/trade/.venv/bin/python scripts/r2_delete_prefix.py --bucket signal-data --prefix fund_nav/ --expect 26458 --yes
rm -rf /Users/linhuichen/code/trade-data/static-site/data/fund_nav /Users/linhuichen/code/trade/static-site/data/fund_nav
ssh -i ~/tdsignal.pem -4 ubuntu@122.51.111.173 'rm -rf /home/ubuntu/code/trade-data/static-site/data/fund_nav /home/ubuntu/code/trade-data-signal/static-site/data/fund_nav /home/ubuntu/code/trade-data-signal-staticdata/data/fund_nav'

# 删后自验
/Users/linhuichen/code/trade/.venv/bin/python scripts/r2_list_prefix.py signal-data "fund_nav/" /tmp/b3/post.json        # 0 objs
/Users/linhuichen/code/trade/.venv/bin/python scripts/r2_list_prefix.py signal-backup2 "large-json/fund_nav/" /tmp/b3/bk.json   # 26458
/Users/linhuichen/code/trade/.venv/bin/python scripts/r2_list_prefix.py signal-data "nav_bucket/" /tmp/b3/nb.json        # 256
curl -s -o /dev/null -w '%{http_code}\n' --max-time 25 https://ssd.fx8.store/fund_nav/000001.json                        # 404
```

**二轮返修:mac staticdata 残树 备份验证 + 补删(§3.1)**

```bash
# ① 清单比对(MISSING=0):mac 树文件名 vs 备份 key
ls /Users/linhuichen/code/trade-data-signal-staticdata/data/fund_nav > /tmp/b3fix_mac_staticdata_names.txt   # 26370
# (与 /tmp/b3/r2_backup_fundnav.json 的 26458 key 名集合比对 → mac∖备份=0, 备份∖mac=88)
# ② 抽样取回(成功 5/5),对比 mac 树与备份
bash scripts/restore-large-json.sh fund_nav/000001.json --target /tmp/b3fix_restore
# (5 样本:mac 日期⊆备份、共同日期 unit_nav 逐位一致、mac 独有日期=0)
# ③ 删前留痕 + 补删 + 改为删后验证
ls -ld /Users/linhuichen/code/trade-data-signal-staticdata/data/fund_nav    # 26372 entry / 574M / mtime 09-11 18:34
rm -rf /Users/linhuichen/code/trade-data-signal-staticdata/data/fund_nav
ls -d /Users/linhuichen/code/trade-data-signal-staticdata/data/fund_nav     # No such file or directory
# ④ mac 全盘残树复查(仅剩下故意保留的回退保险)
find /Users/linhuichen/code/trade /Users/linhuichen/code/trade-data \
     /Users/linhuichen/code/trade-data-signal-staticdata \
     /Users/linhuichen/code/trade-data-signal-staticdata-old-20260926 -maxdepth 9 -name fund_nav -type d
# → 仅 …-old-20260926/data/fund_nav(保留至 2026-10-30,勿动)
```

## 6. 遗留 / 注意(交主控)

1. **7 处全灭**(1 R2 + **6 磁盘树**,含二轮补删 ⑦ mac staticdata),方案「4 处」口径经实测修正为 7 处(验证报告 §1.1),勿再按 4 处复核。
2. **#237 pre-upload 404** 与本次清理无因果(验证报告 §3 附注),10-12 为首发观察日,按 plan §4 走。
3. **D2 前端缓动观察面**:`app.js` L27840 回退 `fetchJSON('https://ss.fx8.store/r2/fund_nav/${code}.json')` 删除后转 404 = 预期降级(不崩溃);plan D2 定「数据先清、前端缓 1-2 日再发版下线」,**本任务不碰前端**。
4. 云上 `/home/ubuntu/` 顶层 2 个 0 字节异常名文件(验证报告 §7.6),疑历史脚本残留,**建议另案核查**(本任务只读发现,未动)。
5. **R2 前缀无一键重推命令**(§4 注2),服务面恢复缺口如实记录。
6. **唯一保留的 fund_nav 树 = `…-old-20260926/data/fund_nav`**(26,370,回退保险至 2026-10-30),故意不动(勘误 3 / memory `staticdata-old-mirror-keep-decision`)。
7. **【二轮新发现·非本任务范围·建议另案】备份链结构暴露面**:`staticdata_backup_async.sh` step3.5b 的 `upload-large-json` **在写权限守卫(git 段)之前**跑,且属 `_PRIVATE_ONLY_CMDS`(本机允许)→ **mac 若跑该脚本,会把本机 staticdata 的 `data/fund_nav` 覆盖上传 signal-backup2 正本**(本任务删 ⑦ 恰好消掉此处的触发源,但机制本身仍在)。同理暴露面 = 任何 mac staticdata 下与云上正本代际不一致的 large-json 目录。**建议主控评估:给 step3.5b 加非生产机 R2 上传守卫**(与 git 段同款 `staticdata_write_guard.py` 前置)。

## 7. 自核(依审查报告 §2「复核放行标准」两处逐条)

| 审查 §2 复核点 | 修正前 | 修正后 | 自核 |
|---|---|---|---|
| **§2.1 数字对账**(表列行数 vs 「7 处=6 磁盘树+1 R2」口径自洽) | 表 6 行(1 R2+5 磁盘树),文字「6 磁盘树」⇒ off-by-one | §2 表补**行⑦** ⇒ **7 行 = 1 R2+6 磁盘树**,与「7 处」自洽;§0 / §3-a / §3-f 同步改准 | **PASS 闭合** |
| **§2.2 实物对账**(mac 同类残树 staticdata 处置) | 26,370/574M **未列未删未声明** | 备份验证(§3.1:MISSING=0 + 子集覆盖)→ **补删**(10:49)→ §2 行⑦ / §4 恢复路径 / §6 遗留 补全;mac 全盘残树复查仅剩故意保留的回退保险 | **PASS 闭合** |

**终态复验(二轮,只读)**:
- R2 `signal-data` `fund_nav/` 前缀:删初证 `/tmp/b3/r2_fundnav_post.json`=`[]`(已归档);本轮 curl `ssd.fx8.store/fund_nav/{000001,970205}.json` + `ss.fx8.store/r2/fund_nav/000001.json` 全 **404** ✓。(注:本轮 `r2_list_prefix.py signal-data …` 遇本机 TLS 自签证书拦截,该 endpoint LIST 未取到;以 curl 端态 + 归档 `[]` 为准。)
- R2 `signal-backup2` `large-json/fund_nav/`:`r2_list_prefix.py` LIST = **26,458**(备份未动)✓
- R2 `signal-data` `nav_bucket/`:`ssd.fx8.store/nav_bucket/ca.json` = **200**(现役未动)✓
- mac 全盘 `fund_nav` 残树:`find`(限定 4 根,maxdepth 9)仅 **`…-old-20260926/data/fund_nav`**(回退保险,故意保留)✓

---
> 报告人:implementer;结论依据均为本次实跑输出(逐处计数→删除→删后复查/对账)。
> §25 四件齐:①备份验证引用 ②删除清单逐处计数/命令 ③恢复路径 ④删后验证证据;复现命令见 §5。
> **二轮返修(2026-10-11)**:依独立审查 §2 修正 — 计数口径 off-by-one(勘误 1)、补删 mac staticdata 残树 ⑦ 并补 §25 证据(勘误 2/§3.1)、「全空」表述改准(勘误 3);审计清单归档 `docs/ops/b3-fundnav-audit-20261011/`(修正项 4)。