# B3 清理前验证报告 — #111 fund_nav(2026-10-11,只读)

> 任务:next-steps-plan-20261011 §1 B3 清理前验证(先 tester 验证 → implementer 清理)。
> 执行:tester(role-tester);时间:2026-10-11 09:35~10:10。
> **只读声明**:全程零写 R2(仅 LIST/GET)、零删本地、零写生产目录/生产数据;唯一写入=本报告 + /tmp 验证取样(4 个还原样本);0 commit / 0 push / 0 切分支。
> **总体判定:可清理(PASS)** —— §25 备份核验**通过**(计数 26,458/26,458 + 抽样 sha256 4/4 逐位一致)。
> ⚠️ **执行须按本报告 §1 的「7 处对象清单」**(方案基准「4 处」口径经实测修正:漏 3 处;另 88 差集方向修正见 §1.3)。

## 0. 结论速览

| 项 | 判定 | 一句话 |
|---|---|---|
| 1 四处对象现状 | PASS(修正为 7 处) | R2 26,458/531.0MiB;云上 3 树各 26,458;mac 2 树各 26,370(旧代际) |
| 2 生成者核查 | PASS | 现役生成链只写 nav_bucket/;fund_nav/ 无任何现行生成者,无机制性重生 |
| 3 上传管道健康 | PASS(附 10-08 单失败已修复) | 最新完整跑 10-09 实传 7/7 + ETag 对账无不一致;10-08 曾 255/256 已告警并次日补齐 |
| 4 large-json 备份核验 | **PASS** | 26,458/26,458 计数 + 抽样 4/4 sha256 逐位一致(含 manifest 记录) |
| 5 恢复路径 | PASS(附 2 注) | 脚本在、用法实测通;x 位 0644;R2 前缀无一键重推命令(记录为缺口) |
| 6 删后影响面 | PASS | _R2_CHANNELS 无 fund_nav + check_r2_consistency 不扫 + 无告警/定时器依赖 |

## 1. 四处对象现状实测(实为 7 处)

### 1.1 7 处对象清单(执行删除面以此为准)

| # | 对象 | 路径 | 计数 | 体积 | 证据 |
|---|---|---|---|---|---|
| ① | R2 主桶 signal-data `fund_nav/` 前缀 | — | **26,458 obj** | **556,807,260 B = 531.0 MiB** | r2_list_prefix.py LIST(27 页分页完整);mtime 冻结 2026-09-20T11:14:27Z ~ 2026-09-22T12:17:49Z |
| ② | 云上 REPO 侧 static-site 树 | `/home/ubuntu/code/trade-data/static-site/data/fund_nav` | 26,458 | 578M(du 块口径) | ls \| wc -l + du |
| ③ | 云上 GIT_REPO 侧 static-site 树 | `/home/ubuntu/code/trade-data-signal/static-site/data/fund_nav` | 26,458 | 578M | 同上;**方案「云上 static-site 树」实为 2 处**(②+③) |
| ④ | 云上 staticdata 灾备树 | `/home/ubuntu/code/trade-data-signal-staticdata/data/fund_nav` | 26,458 | 578M | 同上 |
| ⑤ | mac REPO 侧树 | `/Users/linhuichen/code/trade-data/static-site/data/fund_nav` | 26,370 | 574M | 同上 |
| ⑥ | mac GIT_REPO 侧树 | `/Users/linhuichen/code/trade/static-site/data/fund_nav` | 26,370 | 574M(du);trade 树精确 553,049,297 B = 527.4 MiB(trade-data 树 du 同值,抽样 md5 一致) | 同上;**方案「本机 mac 树」实为 2 处**(⑤+⑥) |
| — | 合计 | **6 磁盘树 + 1 R2 前缀 = 7 处** | | | |

> **勘误(2026-10-11 二轮,依独立审查 `next-steps-b3-review-20261011.md` §2)**:本表原列 **①~⑥ 六行(1 R2 + 5 磁盘树)**,但合计行写「**6 磁盘树** + 1 R2 = 7 处」——**off-by-one**(表中无第 6 棵磁盘树)。真相 = mac 存在**第 3 棵同类残树** `/Users/linhuichen/code/trade-data-signal-staticdata/data/fund_nav`(26,370 文件/574M/09-11 代际,与云上④同类 staticdata 仓 `data/fund_nav`)**未被发现**,故表漏一行。该树经二轮返修复核+补删(见 exec 报告 §3.1 / 勘误 2),补为第 7 项后 **7 行 = 1 R2 + 6 磁盘树** 与合计自洽。原表述保留可反查。
> 另:本报告头(下 §1 标题下注)「漏 3 处」与 §7.1 只列 2 项(云上 GIT_REPO 侧树、mac 拆两处)亦不自洽,一并勘误(以 §1.1 表 + 上述补项为准)。

- 独立性核验:云上 3 处 inode 互不相同(1222218/1076213/1104837);mac 2 处 inode 互不相同(253202469/253229137)→ **均为物理独立副本,不是 symlink/hardlink**;mac 两树抽样 md5 一致(同内容)。
- 集合并集核验:R2 `fund_nav/` 名称集 = 云上树名称集(**差集 0**);云上树 vs mac 树 = 仅云上 88 / **仅 mac 0**。

### 1.2 88 差集原因(已抽样核)

- 差集成员抽样:027213.json =「易方达中证全指食品ETF联接A」(count=1,首条 20260917);023020.json =「南方臻利3个月定开债券发起E」(count=1,20260921)→ **均为 09-11 之后新入 fund_daily_nav 表的基金**(新成立/新收录,单条净值)。
- 段分布:02 段 80 个 + 15 段 4 个 + 50/51/56/58 各 1 个。
- ⚠️ **方向修正**:plan §1 B3 原文「mac 26,370 比 R2 26,458 多 88 个」方向写反——实为 **mac 少 88 个**(26,370 + 88 = 26,458)。
- 代际结论:**mac 2 树 = 09-11 旧代际;R2 + 云上 3 树 = 09-22 新代际**。抽样内容对比(000001:mac count=1,263→0910 vs R2 count=1,269→0921;017577:901 vs 907),**mac 全部日期 ⊂ R2 日期(mac 独有日期 0 个)**;共同日期 unit_nav 逐位一致,唯一差异 = 末条 acc_nav 注记(mac 20260910 acc=3.835,与当前 DB fund_daily_nav 值一致;R2 版同日 None、另有 0911~0921 共 6 天更新)→ **mac 树无备份外独有文件/独有日期,删除不丢独有数据**。

### 1.3 删除前线上可达性现状(记录)

- `https://ssd.fx8.store/fund_nav/000001.json` 当前 HTTP 200 / 30,497B / sha256=953ac5a3…(= 云上 = large-json 备份)→ **R2 旧前缀仍在线上服务**;删除后该 URL 转 404(预期,属 D2 前端缓动观察面)。

## 2. 生成者核查(防删后重生)PASS

- **现役生成链只写 nav_bucket/**(2026-09-23 桶化):`scripts/export_fund_nav.py` OUT_DIR=`STATIC_DIR/nav_bucket`(L82),输出日志 `✓ 完成 N 只 -> nav_bucket`;**不再写 fund_nav/**。
- `scripts/update_all.sh`(L107/L120):export_fund_nav 照跑 + **只 rsync nav_bucket/**(L120,无 fund_nav 项);上传走 `fund_nav_upload_async.sh` → `upload_r2.py upload-fund-nav` → R2 **nav_bucket/** 前缀(现役 R2 实测 256 obj)。
- 全 repo 引用面全清单(逐处定性):
  1) `export_fund_nav.py` 写 nav_bucket(现役);2) `upload_r2.py cmd_upload_fund_nav` 传 nav_bucket(现役);3) `fund_nav_upload_async.sh` 调 upload-fund-nav;4) `update_all.sh` 导出链;5) `check_data_integrity.check_fund_nav` **查 nav_bucket**(删旧目录不触 deploy 闸门);6) `check_data_gap_alerts`(fund_nav_accnav/allnull)**读 DB,不读目录**;7) `alert_denoise_rules` 告警 key 分类(不读目录);8) `check_repo_paths_ratchet` 文件路径棘轮(只查脚本存在性);9) `large_json_excludes.py` DIR_EXCLUDES 含 data/fund_nav(备份路由);10) `restore-large-json.sh` 恢复入口;11) 前端 `app.js` 双读回退(见 §6);12) `deploy.sh`/`staticdata_sync.sh` rsync(见下)。
- **重生风险评估**:无任何现行脚本会重新生成 fund_nav/;**唯一「携带链」= 两处通用全量 rsync(均无 exclude fund_nav、均无 --delete)**:
  - `deploy.sh` L529:`rsync -a --checksum "$REPO/static-site/data/" "$GIT_REPO/static-site/data/"`(REPO→GIT_REPO)
  - `staticdata_sync.sh` L94:`rsync -a "$REPO/static-site/data/" "$STATICDATA_REPO/data/"`(REPO→staticdata 灾备)
  ⇒ **凡 6 磁盘树全删干净,则 rsync 无源可带、不重生**(无 --delete 意味着"只删下游不删上游"不会自动清理下游残留——**必须逐树手动删全**);只删下游、源侧残留 → 下次 rsync 会把下游带回来。此即"7 处同删"的必要性。
- 补充:fund_nav 未进 git 跟踪(主仓 .gitignore `static-site/data/fund_nav/`;staticdata 仓走 large-json 排除区)→ 无 git 侧重生。

## 3. 上传管道健康判据 PASS(附注 10-08)

判据 = **上传成功 + 失败=0 + 对账过**(核最近几日云上日志):

| 日期 | 运行 | 结果 | 证据 |
|---|---|---|---|
| 10-08(周四,复市首日) | 全量 256 判定 | **255/256,1 失败**(2c.json ✗ 403 RequestTimeTooSkewed),rc=1 → **已告警**(邮件+飞书,severe-mirror latest.md) | fund_nav_upload_async_20261008_182838.log L330/L541-L545 |
| 10-09(周五) | 强制全量判定(上次中断 marker)→ checkpoint 命中 249 | **实传 7/7 全成**(33.3s,含 10-08 失败的 2c.json ✓);层2 ETag 对账**无不一致** | fund_nav_upload_async_20261009_181521.log |
| 10-10(周六,非交易日) | — | 无上传(非交易日);deploy 内检查段 ✓「fund_nav: 256 桶/26634 只全史净值,抽样 30 只结构+DB逐位一致,覆盖率 ≥95%」 | update_all_20261010_1750.log L124 |
| 10-11(周日,今日) | — | 无上传(非交易日);最近一次上传=10-09 | 日志 ls 实测 |

- 任务基准「现增量 7/7」= **10-09 记录核验一致**。旧判据「每日 PUT 256」已不适用(桶化后行为)。
- ⚠️ **附注(不阻断,如实报)**:10-09 日志中 **pre-upload 覆盖前备份 7/7 全 404 NoSuchBucket**(目标 signal-backup2)——= **已知问题 #237**(跨账号 CopyObject;根因报告 `docs/ops/preupload-copy-rootcause-20261008.md`,relay 已上线 `9ae8c50cc`,C 开关未开,10-12 为首个观察日)。与 nav_bucket 上传本体无关(本体 7/7 正常)。
- 现役 R2 `nav_bucket/` 前缀 LIST = **256 obj**(现役完好)。

## 4. large-json 备份核验(§25 关键)PASS

- 排除声明:`scripts/large_json_excludes.py` **DIR_EXCLUDES 第 9 项 = `data/fund_nav`**(L78 附近)→ 语义 = 该目录整体走 R2 私有桶 `signal-backup2` `large-json/` 每日备份,不进 staticdata git(与主仓 .gitignore 一一对应)。
- **R2 `large-json/fund_nav/` LIST = 26,458 obj / 110,870,643 B = 105.7 MiB**(gz);key 形态 100% = `large-json/fund_nav/<code>.json.gz`(0 个异常形态)。
- **计数比对 26,458/26,458(名称集合差集 0)**(R2 fund_nav/ vs large-json/fund_nav/ vs 云上树三方互相差集全 0)。
- **抽样取回 sha256 逐位比对 4/4 全等**(restore 实测取回 → /tmp 比对;样本覆盖 首/中/尾/最小边界):

| 样本 | R2 取回 sha256 | 云上树 sha256 | manifest 记录 | 结果 |
|---|---|---|---|---|
| fund_nav/000001.json | 953ac5a3…294af27c | 953ac5a3…294af27c | 953ac5a3…294af27c | ✓ |
| fund_nav/017577.json | 4904d616…26db957 | 4904d616…26db957 | 4904d616…26db957 | ✓ |
| fund_nav/970205.json | 7a33654c…7c71f3a1b | 7a33654c…7c71f3a1b | 7a33654c…7c71f3a1b | ✓ |
| fund_nav/027213.json(最小 211B) | 2d686a53…e1b5028c | 2d686a53…e1b5028c | 2d686a53…e1b5028c | ✓ |

- manifest:云上 staticdata 仓 `docs/large-json-backup-manifest.md`(**2026-10-11 05:31 刷新**,fund_nav 行 26,458 行,每行含完整 sha256 + 最新 R2 key +「永久(唯一副本)」档位)。
- 上传侧证据:2026-10-11 05:31 `staticdata_backup_async` 日志 → `large-json 上传 31675/31675 -> signal-backup2/large-json/(私有桶)`(**全过,0 失败**;含 fund_nav 全部)。
- 结论:**既有备份完整覆盖 26,458/26,458,抽样逐位一致 → §25「备份验证」通过**。(无需重新 PUT 578MB;plan 预判成立)

## 5. 恢复路径确认 PASS(附 2 注)

- `scripts/restore-large-json.sh` **存在**(26,110 B);本次实测调用 **4 次单文件恢复全部成功**(每次「成功 1 / 失败 0」)。
- 用法(示意,均已在本次实测验证):
  - 单文件:`bash scripts/restore-large-json.sh fund_nav/<code>.json [--target <树根>/.../data]`
  - 枚举:`bash scripts/restore-large-json.sh --list`;批量:`--all`(并集);旧日期档:`--date YYYY-MM-DD`
- 默认目标 = `${STATICDATA_REPO:-/Users/linhuichen/code/trade-data}/data`(**= trade-data/data,非 static-site/data**)⇒ **恢复到 6 磁盘树的示意命令**(--target 指向该树对应位置):
  - 云上 REPO 树:`--target /home/ubuntu/code/trade-data/static-site/data`
  - 云上 GIT_REPO 树:`--target /home/ubuntu/code/trade-data-signal/static-site/data`
  - 云上 staticdata 树:`--target /home/ubuntu/code/trade-data-signal-staticdata/data`(与默认语义一致)
  - mac 两树:`--target /Users/linhuichen/code/trade-data/static-site/data` / `--target /Users/linhuichen/code/trade/static-site/data`
- **注1(无 x 位)**:脚本权限为 0644(-rw-r--r--),无执行位;所有官方用法均 `bash scripts/...` 调用,不影响(实测 4 次成功);若要 `./` 直跑需 chmod +x。
- **注2(R2 前缀无一键重推命令,缺口记录)**:`upload-fund-nav` 现役已改传 `nav_bucket/`,**不存在把 per-code 重新 PUT 回 R2 `fund_nav/` 旧前缀的现成命令**;若未来要恢复 R2 前缀服务面,需从 large-json 备份 GET→解压→循环 PUT 临时脚本(无现成通道;数据内容本身已被备份完整覆盖,此为「服务面恢复」缺口,非「数据丢失」缺口)。

## 6. 删后影响面再核(复核既有结论)PASS

- **`_R2_CHANNELS` 无 fund_nav 通道** ✓:`upload_r2.py` L3466 清单 16 通道逐条读,`fund-nav` 通道 `r2_prefix="nav_bucket"`(现役);无任何通道 r2_prefix=`fund_nav`。
- **`check_r2_consistency` 不扫 fund_nav** ✓:其扫描对象 = 文件内硬编码 `FILES` 显式清单(overview/board_etf_map/concepts/overfit_monitor 等,逐项 URL 三腿);全文件 grep `fund_nav` **仅 1 处注释**(L308),无检查项。
- **删除不触 deploy 前置闸门** ✓:`check_data_integrity.check_fund_nav` 查 `data_dir/"nav_bucket"`(L1219),与旧目录无关。
- **告警/监控无依赖** ✓:`check_data_gap_alerts`(fund_nav_accnav/allnull)直接读 DB(其注释明示"独立于 DB↔产物比对");`alert_denoise_rules` 仅做告警 key 分类;云上 `systemctl list-timers` 无 fund_nav 目录相关任务(pf-stage0-nav → stage0_nav.sh 无 static-site 写入)。
- **前端(现状,属 D2 缓动观察面)**:`app.js` L27840 回退 `fetchJSON('https://ss.fx8.store/r2/fund_nav/${code}.json')`(走 CF `/r2/` rewrite → R2 主桶 fund_nav/ 前缀);L9648 `_NO_R2_CACHE_URLS` 含 fund_nav(no-store)。**删除后回退链 404 = 预期降级(不崩溃)**,即 plan D2「数据先清、前端缓 1-2 日再发版下线」设计的观察对象。

## 7. 遗留 / 注意(交执行者与主控)

1. **执行清单以 §1.1 的 7 处为准**(方案「4 处」口径漏:云上 GIT_REPO 侧树、mac 拆两处);6 磁盘树**全删**才无 rsync 携带回填。
2. 方向修正(§1.2):「mac 比 R2 多 88」实为 **mac 少 88**;88 = 09-11 后新入 DB 基金,mac 生成时尚未出现(合理性已抽样核实)。
3. mac 2 树为 **09-11 旧代际**(26,370 ⊂ 26,458 名称全覆盖):无独有文件/独有日期;唯一内容差 = 末条 acc_nav 注记(2 样本,值 3.835/1.139 级别)。如追求绝对保全,可在删除前对 mac 树尾条差异摘录一笔(价值近零,不建议单独立项)。
4. **pre-upload 404(#237)** 与本次清理无因果,10-12 首发观察日按 plan §4 走。
5. 删除后 `ssd.fx8.store/fund_nav/*.json`(R2 直连)与 `ss.fx8.store/r2/fund_nav/*.json`(CF /r2/)将转 404——预期行为;若有外部引用者会失效(内部唯一引用者 = app.js 回退,D2 已拍)。
6. 顺带记录(不属本任务,只读时发现):云上 `/home/ubuntu/` 顶层有 2 个 0 字节异常名文件(`,json.dumps(v,ensure_ascii=False))` 与 `, v)`,mtime 09-30/10-09)——疑似历史脚本事故残留,建议另案核查。
7. 时窗:plan 已定「今天 16:00 前完成写动作/避 22:00-01:30」,不属本验证范围,未复核。

## 8. 复现命令存档(只读)

```
# R2 主桶前缀(信号数据)
.venv/bin/python scripts/r2_list_prefix.py signal-data "fund_nav/" /tmp/b3verify/r2_fund_nav.json
# R2 备份前缀
.venv/bin/python scripts/r2_list_prefix.py signal-backup2 "large-json/fund_nav/" /tmp/b3verify/r2_largejson_fundnav.json
# 云上三树计数
ssh -i ~/tdsignal.pem -4 ubuntu@122.51.111.173 'ls /home/ubuntu/code/trade-data/static-site/data/fund_nav | wc -l'          # → 26458
ssh ... 'ls /home/ubuntu/code/trade-data-signal/static-site/data/fund_nav | wc -l'                                              # → 26458
ssh ... 'ls /home/ubuntu/code/trade-data-signal-staticdata/data/fund_nav | wc -l'                                               # → 26458
# 抽样取回+对账(实测 4 次)
bash scripts/restore-large-json.sh fund_nav/000001.json --target /tmp/b3verify/restore_test
sha256sum /tmp/b3verify/restore_test/fund_nav/000001.json
# 线上现状
curl -s --max-time 25 https://ssd.fx8.store/fund_nav/000001.json -o /tmp/x.json && shasum -a 256 /tmp/x.json
```

---
> 报告人:tester;结论依据均为本次实跑输出(§5.1 完成前验证门四步:指认命令→真跑→读全→对账);备份核验不过即判「不可清理」——本报告计数与抽样全过,判定 **可清理**。
