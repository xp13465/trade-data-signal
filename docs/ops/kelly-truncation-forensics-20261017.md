> **落档说明**(2026-10-18,收口批):本文为 kelly 两件产物截断事故的**独立取证报告原文**(原在 `/tmp/forensics-kelly-truncation.md`)。
> 生成者:researcher 子 agent(只读);生成时间:2026-10-17(星期六);关联上下文:R2 断供期间本地数据事故取证 / 同目录复原执行报告 `kelly-restore-report-20261017.md`。
> 正文以下**逐字原样保留**(历史记录不追改,CLAUDE.md §6④)。

# kelly 两件产物截断事故·独立取证报告(researcher,只读)

- 取证日期:2026-10-17(星期六)。全部数字=实测(附命令),未采信 P2 自述,自述项逐条独立复测。
- 全程只读零写:未做任何恢复动作;未动仓库/数据/云上/桶(云上仅 ssh 读;备份桶仅 --list)。
- 残留后台任务(交卷时仍在跑,均只读 git 扫描,主控可 TaskStop):
  - `bdqj3omvd`:staticdata 备份仓全历史 blob 顺序遍历(慢,见 §2.3 原因)。
  - `b9m5luu78`:同仓批处理版+收尾项;进度写 `/tmp/j-blobsizes.txt`(截稿 71/380,0 命中 86254426)。

## 结论速览(明确判定)
1. **现状**:两件均处于 P2 申报的恢复态,与自述数字一致——features 逐位复原;trades=本机 trade-data 镜像版 86,222,094/BED268677(非原件)。
2. **「逐位副本全无」不成立**:trade 树内 `signal_kelly_trades.json.gz`(9-22 11:27:51)gzip ISIZE=**86,254,426**、解压头 generated_at=**"2026-09-22 11:20"**、解压流 md5 `8ace9b51e5f712a856c5a7142df1572b`,与被截断原件同尺寸同世代(另有两处事前独立记录佐证)=唯一可及的原件级副本(高置信推断,无原件 md5 直接比对,见 §2.2 诚实标注)。
3. **线上/云端/数据层未被污染(否)**:本机自 10-06 起无 deploy/export/上传运行;本机公共 R2 写入有硬闸(upload_r2.py exit 2,2026-10-03 起);deploy 上传源=trade-data(未受损);云上今晚 21:06 deploy 中止于完整性检查(4 个 R2 404 失败,与 kelly 两件无关),未触发上传;R2 主桶 403 为独立既有故障。
4. **云上副本比原件更新**(且更大):云 trade-data=88,160,130B/10-17 21:09;云 signal±staticdata=87,614,810B/10-15;备份桶=87,614,810 世代(manifest 10-15)。均非原件副本,可作「刷新到最新」源。
5. **恢复**三条路径见 §5.1(未执行,由主控拍板);危险夹具 `/tmp/valtest` 已删(复测 ENOENT);同类 symlink 风险面 3-4 处(§5.3)。**注意:trade 树 gz 是唯一原件级副本且同样 gitignored 无备份,建议先固化一份。**

## 一、现状核实(Q1)
### 1.1 树关系(命令+结果)
```
ls -ld static-site/data /Users/linhuichen/code/trade-data/static-site/data → 两处均为真实目录(非链接)
readlink /Users/linhuichen/code/trade-data/scripts → /Users/linhuichen/code/trade/scripts(代码目录 symlink;data 目录为实体)
```
### 1.2 两件现状(`stat -f` + `md5 -q` 实测)
| 位置 | size | md5 | mtime | ctime | birth/inode |
|---|---|---|---|---|---|
| trade 树 features | 1,121,943 | 9dc05b42dcb4189b83e653443979933e | 2026-08-24 17:07:27 | **10-17 21:40:46**(恢复写) | birth 08-23 14:17:49 / ino …913 |
| trade 树 trades | 86,222,094 | bed268677bcdf8cf78eb3b4613ba5492 | 10-06 17:56:37(mtime 保留) | **10-17 21:41:35**(恢复写) | birth 2026-09-13 05:10:14 / ino …941 |
| trade-data 镜像两件 | 同 md5 | 同 | 同 | ctime 未变(08-24 / 10-06) | — |
trades 的 birth/ino 保留 ⇒ 恢复为**原地覆写**(非删建/非 os.replace);mtime=镜像值(cp -p 语义)。
### 1.3 与 P2 自述交叉核对
- 一致:features md5 9dc05b42;trades 86,222,094/bed268677;原 86,254,426、Δ=32,332(=86254426−86222094 逐位吻合);R2 403。
- **推翻**:「逐位副本全无」→ §2.2 找到原件级候选。
### 1.4 git 状态
`git check-ignore -v` → `.gitignore:208:static-site/data/*`(两件均 ignored);`git log --all -- <两件>` 为空 ⇒ 上线树**全史未跟踪**(不是"曾跟踪后删")。
### 1.5 可达副本全清单(实测,含 ~/code 两树 + 全 ~/code depth4 + /tmp depth10 扫描)
| # | 副本 | size | md5(或世代) | 判定 |
|---|---|---|---|---|
| 1 | trade/static-site/data/signal_kelly_trades.json(当前) | 86,222,094 | bed268677 | 恢复态(10-06 世代) |
| 2 | **trade/static-site/data/signal_kelly_trades.json.gz** | 14,099,991→解压 86,254,426 | 流 8ace9b51 | **唯一原件级候选(9-22 11:20 世代)** |
| 3 | trade-data 镜像 .json | 86,222,094 | bed268677 | 10-06 世代 |
| 4 | trade-data gz | 14,097,282→86,222,094 | bed268677 | 10-06 配对 |
| 5 | trade-data-signal-staticdata/data/.json | 86,222,094 | 041b3411 | 9-22 22:47:35 另世代 |
| 6 | 同上 old-20260926 快照 | 86,222,094 | 041b3411 | 同上 |
| 7 | trade/data(旧数据仓) | 32,307,771 | bc0e0f95 | 8-09 老物 |
| 8 | trade-data/data 同款 | 32,307,771 | bc0e0f95 | 同上 |
| 9 | /private/tmp 2 组(10 文件) | — | 见下 | 全非原件 |
| 10 | 云上 4 树 | — | §2.1 | 更新世代 |
| 11 | 备份桶 | 14.1MB gz | §2.1(manifest) | 10-15 世代 |
| 12 | staticdata 备份仓 git 历史 | — | §2.3 | 无 86,254,426 世代 |
/private/tmp 明细:#9 = valtest2(21:52,两件=恢复态真副本 bed268677/9dc05b42);p2val-p2rev(backup/=真副本×2 + static-site/data=真副本 + caseC 夹具 1,080,000B/7788f838);261-harness/ws(两件 **0 字节**,00:06:59,空体夹具);rev262-probe(features=9dc05b42,00:32);reviewer_t2/six(features=9dc05b42,10-14)。**全组无 86,254,426 件;无硬链接(inode 各异)**。

## 二、恢复缺口核实(Q2)
### 2.1 各源盘点(为什么都不是原件)
- **云 trade-data**(ssh read):trades 88,160,130 / mtime **2026-10-17 21:09:44** / md5 f7163538…(比原件**新**且大 1.9MB);features 1,121,943/9dc05b42(与本地一致)。
- **云 trade-data-signal / -staticdata**:trades 87,614,810 / 10-15 17:07 / af3bbacd…。
- **备份桶 signal-backup2**:`restore-large-json.sh --list` → 31,685 对象全部在「当前固定前缀」区(0 个日期目录);本件单条 14.1MB;manifest(`.../docs/large-json-backup-manifest.md` L3975)= 87,614,810 / sha256 ee68f68d… / 日期 2026-10-15。**=10-15 云版快照,非原件**。(逐字节复核未做:恢复脚本写目标=仓库树,取证纪律禁写;以 manifest sha256 为准)
- **R2 主桶**:实测 `http=403`(CF HTML 17,729B,60s 内复测两次同)→ **取不到**(R2 断供既有故障)。
- **上线树 git**:全史未跟踪 ⇒ 空。**trade-data 本地非 git 工作树**(已验)。
- 本机其它:§1.5 #3-9 全非 86,254,426。
### 2.2 关键发现:trade 树 gz = 原件级候选(证据链)
```
stat  → size=14,099,991 mtime=2026-09-22 11:27:51
gzip -l → ISIZE 86,254,426(= P2 申报原件大小,逐字节吻合)
gzip -dc | md5 → 8ace9b51e5f712a856c5a7142df1572b
gzip -dc | head -c 130 → {"generated_at":"2026-09-22 11:20","buy_amount":10000,"period_cutoffs":{"y1":"20250922",…(截断口径与 9-22 当日一致)
```
独立旁证(均早于事故):
- `/tmp/wt-251r3/docs/ops/r2fix-review-report-20261005.md`(10-05):「本地实测最大单文件 signal_kelly_trades.json=86,254,426B」
- `/tmp/wms-install/pkg/docs/ops/next-steps-w3b-222-exec-20261011.md`(10-11):「真实产物 /Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json(86,254,426 B)…generated_at=2026-09-22 11:20」
**诚实标注**:全链无原件 md5 留存(gitignored+无 manifest),「gz=原件」= 尺寸逐位吻合 + 世代戳吻合 + 两处事前独立记录 的高置信推断,**非**直接 md5 等同。
### 2.3 备份仓(staticdata)git 历史深查
- 该仓为 **promisor 部分克隆**(`remote.origin.promisor=true`,.git 仅 139MB)⇒ 历史大 blob 不在本地,取数=逐个网络拉取(两个后台任务慢的根因)。
- 跟踪史:曾跟踪 data/signal_kelly_trades.json,至 **c4db266(9-26 13:45)** 移出跟踪(`|1 -` 删除行 + .gitignore 增行,与 #126 大文件移出设计一致)。
- 定向取数:9-22 21:12 blob=86,567,298;9-22 23:22=86,569,358;9-23 02:24=86,569,374;抽样 9-24~26 七个=86,586,298,**全部 ≠ 86,254,426**。⇒ 该 git 链未见原件世代(唯一未扫窗口=9-18~9-21,低概率;后台任务收敛可终局)。
### 2.4 结论
「逐位副本全无」**不成立**(gz 为高置信原件级副本);云上副本比原件**更新**(88.1MB/10-17 与 87.6MB/10-15)。

## 三、影响面判定(Q3)
### 3.1 谁生成(file:line)
- trades:`scripts/signal_kelly_backtest.py`(默认路径 L2719;主写 L2780 `atomic_write_text`;注释 L2771-2774=tmp+fsync+os.replace 全有或全无;parts L2788)
- features:`scripts/gen_kelly_loss_features.py`(OUT=L39)
- 上线链:deploy 段1 经 `static-site/export.py` subprocess 生成(export.py L1206-1213 `--output DATA_DIR/signal_kelly_backtest.json`);两件在 EXPORT_MANIFEST 具名,**分级 WARN「设计内可缺」**(export.py L726-730)。
### 3.2 谁消费
- 前端:`static-site/app.js` L3416、L3423(parts→全量回退)、L3456、L3527;`static-site/lab.js` L7626/7637、L8592-8601、L10307。
- CI:`.github/workflows/ci.yml` L31-32 注释、L161-165(从 ssd.fx8.store 下载两件)、L184/191 TRADES_JSON。**今夜 22:36 已 merge #261:CI 新增「下载后产物完整性校验」(JSON 可解析+大小下限),挡空体/截断、不挡旧版。**
- 部署:`scripts/deploy.sh` L323-324 `check_data_integrity.py --deploy-mode --data-dir "$REPO/static-site/data"`;features 有专项校验(check_data_integrity.py L1836+ rules 键集);trades 无专项深度校验(仅 export_manifest 存在性+非空,WARN 级);上传触发在 L608+ 段。
### 3.3 能否推上线?(关键=否,三重防护)
1. **上传源不是本树**:deploy.sh L247/L549-553「采集在 trade-data,git 上线在 trade;trade-data 跑时 rsync trade-data→trade」;R2 上传源=$REPO(trade-data,L246/L302)。即使 deploy 真跑,rsync 也先用 trade-data 完好版覆盖 trade,被截断文件到不了上传层。
2. **macOS 硬闸**:`scripts/upload_r2.py` L88-103(_PRIVATE_ONLY_CMDS 仅 4 条本机放行;所有 upload-* 数据通道=公共桶写)+ L114-128(darwin/非 /home 拒写公共 R2,**sys.exit(2) L128**,2026-10-03 export-guard L2);REPO 缺省另 exit(3) L145。
3. **本机零运行**:21:00 后数据面无 deploy/export/upload 活动(§4)。
4. 补充:完整性检查失败阻断(L323-356);但**无「版本新旧/新鲜度」闸**挡旧版——保护靠架构(源树+mac 闸),非 freshness 检查。
### 3.4 结论
本地这份**不可能**经现有链路推上线;未见可污染通道。

## 四、时间线(Q4)
| 时刻 | 事件 | 证据 |
|---|---|---|
| 9-22 11:20 / 11:27:51 | 原件生成 / trade 树 gz 落盘 | gz ISIZE+头+mtime |
| 10-05、10-11 | 两处独立文档记录 86,254,426 | 两文档原文 |
| 10-17 21:37 | p2-val.sh(夹具驱动) | mtime |
| 21:38 | 用例 b/c/d 运行(mtime 21:38)⇒ 期间经 symlink 重定向截断真件(trades→0B;features→8B) | logs + 受损态 |
| 21:39:01 | p2-val-g.log:两件 8B/0B(发现) | 内容+mtime |
| 21:40:46 / 21:41:35 | features / trades 恢复写入 | ctime |
| 21:51-52 | valtest2 真副本 | mtime |
| 22:24 | p2val-p2rev 修复后夹具(backup/=真副本,新范式) | 文件 mtime |
| 云 21:06:03→21:12 | deploy 段1:export 重生成云 trades(21:09:44,88,160,130);完整性检查 4 FAIL(全为 R2 404:alert/notifications/nextday_plan/signal_kelly_day_snapshot)→**终止,未上传** | 云 data/logs/deploy_20261017_2106.log L560/561/584/585/606 |
| 本机 21:00 后 | 数据面仅两件恢复写 + public_fund.db-shm 等零星;**无 deploy/export/上传** | find -newerct 扫描 |
| 本地 git 21:37~22:36 | 4 次 merge(统一入口),纯代码 | reflog |
**判定:线上(R2/CF)、云端、CI 数据层当前均未被该旧副本影响(否+上述证据)。** R2 403 与本次无关(既有断供)。原件 mtime 不可考(被截断+恢复两次覆写;最后已知内容世代=9-22 11:20)。

## 五、恢复与防再犯(Q5)
### 5.1 恢复选项(本报告未执行任何恢复动作;由主控拍板派单)
- **A 恢复事故前原状(唯一原件级)**:`gzip -dc /Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json.gz > /tmp/sk_restore.json`;校验 `stat -f %z`=86254426 + `md5 -q`=8ace9b51e5f712a856c5a7142df1572b + head 世代戳"2026-09-22 11:20";再原子落位(mv)或 cp -p;落位后复核 md5 + `python3 -c json.load` 可解析。
- **B 刷新到最新权威**:`scp -i ~/tdsignal.pem ubuntu@122.51.111.173:/home/ubuntu/code/trade-data/static-site/data/signal_kelly_trades.json <目标树>/static-site/data/`;校验 size=88,160,130 + md5 f7163538(云上会滚动,以当次实测为准)。是否同步 trade-data 树由主控定。
- **C 本地重生**:`python3 scripts/signal_kelly_backtest.py --output static-site/data/signal_kelly_backtest.json`(同目录默认写 trades;原子写;产出=当天口径,非 9-22 复原;同时写 backtest.json/parts/unique,**属多产物改动**,仅派单后执行)。
- features 无需动(已逐位复原)。执行时按 §14 核时点。
- **前置建议**:先把 trade 树 gz 复制固化一份(唯一原件级副本,同样 gitignored 无任何备份,被清理即彻底丢)。
### 5.2 危险夹具已删(复核)
`ls -ld /tmp/valtest` → **No such file or directory**(ENOENT,实测);同级 valtest2/p2val-p2rev 等为**真副本**(非链接),无风险。附带:261-harness/ws 残留两个同名 **0 字节**夹具,建议随清理。
### 5.3 同类风险面(扫描+建议)
- `scripts/playwright-accept/t32-fade-mode-smoke.js:18`、`verify_sim_modal_layout.js:18`:指引式 `ln -sfn <真树>/static-site/data static-site/data`(标"只读",任何写/重定向即打穿真树——本次事故同型)。
- `scripts/tests/repro_fundnav_selfheal_20261013.sh:53-56`:symlink 真仓 scripts/app/.venv/config。
- `scripts/tests/test_resolve_repo.sh:55/79/144`:temp 内 symlink(低风险)。
- 建议:①夹具写目标禁 symlink(脚本内加 `[ ! -L "$target" ]` 断言);②统一真副本(参考 p2val-p2rev 的 backup/ 范式);③"数据产物只读引用"写进测试规范;④ gz 固化(§5.1 前置)。

## 附:取不到项 / 未收敛项(诚实标注)
- R2 主桶内容取不到(403 实测,原因=既有断供);备份桶内容逐字节未复核(脚本写目标=仓库树,纪律禁写;以 manifest sha256 为准)。
- 备份仓 git 全量 380 blob 未扫完(截稿 71/380、0 命中;promisor 网络取数极慢);定向 3 取数+抽样 7 个已足以判定"9-22 起无 86254426 世代";后台任务 bdqj3omvd/b9m5luu78 收敛后可终局(/tmp/j-blobsizes.txt)。
- 原件 mtime 不可考(两次覆写;最后已知世代=9-22 11:20)。

---
补记(2026-10-17 23:0x,交卷后):两个后台扫描任务已由主控 TaskStop(bdqj3omvd、b9m5luu78);b9m5luu78 最终扫描态=95/380、0 命中 86254426(/tmp/j-blobsizes.txt)。全量 380 blob 未扫完(余量含 9-18~9-21 窗口,属低概率区间)——「备份仓 git 链无 86254426 世代」的判定依据=§2.3 定向取数 3 个+抽样 7 个,未因任务停止而改变。
