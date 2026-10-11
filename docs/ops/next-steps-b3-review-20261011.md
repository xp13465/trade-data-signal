# B3 fund_nav 遗留清理 独立审查报告 — #111(2026-10-11,reviewer)

> 残留后台任务:**无**(本次审查全程无 `moved to the background (ID:`)。
>
> 审查对象:分支 `feat/b3-fundnav-cleanup`,tip `a88094c97a49508d3a2ce6f25569ac859c238528`。diff vs main = **+2 文件 / 295 行**(新增 `scripts/r2_delete_prefix.py` + 新增 `docs/ops/next-steps-b3-exec-20261011.md`),无其它文件改动。
> 审查方式:静态读码 + 只读实测(mac 本地 `ls/find`、云上只读 `ssh ls/find`、线上只读 `curl`、`/tmp/b3` 审计产物回读、grep 行号核)。**零写零删、未执行任何业务脚本(含该工具 dry-run)、curl 无 -v/-i。**
> 一句话:**删除执行本体与新增工具均无问题(独立复核通过);但执行报告的两个核心数字口径与实物不符("7 处 / 6 磁盘树"vs 表列 6 行),且 mac staticdata 检出树上同类 fund_nav 残余(26,370 文件/574M)未列未删未声明 → 总判定:不通过(修正量小,修正后可快速复审放行)。**

## 0. 总判定:不通过

| # | 修正项 | 性质 |
|---|---|---|
| 1 | 执行报告计数/表述修正:"7 处 = 6 磁盘树 + 1 R2"与表列 6 行(1 R2 + 5 磁盘树)不自洽;"全删/全空"表述需按实物改准(见 §2) | **必须**(merge 前) |
| 2 | mac staticdata 残余面(`/Users/linhuichen/code/trade-data-signal-staticdata/data/fund_nav`,26,370/574M)如实声明 + 上报拍板 删/留;若删按 §25 补证据(备份已覆盖,判定可删) | **必须**(merge 前) |
| 3 | verify 报告(main 上)同款计数勘误(「6 磁盘树+1 R2=7」「漏 3 处」vs 其 §1.1 表 6 行) | 建议(可随文档批) |
| 4 | 删除 run 分批日志与 26,458 审计清单目前仅存 /tmp/b3/(易失);建议归档入报告链 | 建议(非阻断) |

**不需要回滚任何已执行删除;新增工具无需修改即可留用。** 不通过仅针对报告准确性(must 1)与一处未声明残余面的处置(must 2)。

## 1. 新增工具安全审查(`scripts/r2_delete_prefix.py`,纯读代码,未执行)

| 项 | 实物核 | 判定 |
|---|---|---|
| dry-run 默认 | `--yes` 为 store_true;缺省走 L135-137 打印 DRY-RUN 后 return,零写 | ✓ |
| `--yes` 门控 | L135 `if not args.yes` | ✓ |
| 桶/前缀白名单硬校验 | `ALLOWED={("signal-data","fund_nav/")}`(L48-50);L116-120 exact tuple 不在名单即 `exit 2`,且该检查在**任何 R2 动作(含 LIST)之前** | ✓ |
| 绕过面排查 | `--bucket/--prefix` 均 required、**无默认值**;全脚本无环境变量参与桶/前缀路由;无参数注入面(纯字符串 exact 比较);非白名单组合(wildcard/无尾斜杠/空串/异桶)一律 abort | ✓ 无绕过路径 |
| `--expect N` 计数闸门 | L131-133 实际 LIST 数≠期望即 exit 2(可选参数,文档已写明"给定期望数时") | ✓ |
| 分页逻辑 | list-type=2 + continuation-token 循环(L54-79);批次 BATCH=1000(L146-152) | ✓ |
| 删除实现 | POST `/?delete` + Content-MD5 + XML body(L87-104);非 200 → 该批计错 `(0, len(keys))` 继续累计 | ✓ |
| err>0 处理 | 最终 `remain or total_err` → **exit 3**(非静默;比报告措辞略强:err>0 即使 remain=0 也 exit 3) | ✓ |
| 与报告声称对照 | 报告 §2 五条安全设计逐条属实,**无夸大**;两处小弱点(见 §6 低分项):XML 正则解析对 niche 特殊字符 key 脆性(本前缀 key 形态 `fund_nav/NNNNNN.json` 无影响)、`--expect` 非强制 | ✓ |

**结论:工具安全设计成立,PASS。**

## 2. 「7 处 vs 6 行」对账(重点查实 —— 结论:计数口径错误 + 一处未声明残余面,非"清单内漏删")

### 2.1 数字对账(逐字)
- verify §1.1「执行删除面以此为准」表 = **6 行**:①R2 前缀(26,458/556,807,260B)②云上 REPO ③云上 GIT_REPO ④云上 staticdata ⑤mac trade-data ⑥mac trade(②③④各 26,458;⑤⑥各 26,370)。
- exec §2 表与 verify §1.1 **逐行同构**;两报告合计行均写「**6 磁盘树 + 1 R2 前缀 = 7 处**」——但表列只有 **5 磁盘树**。exec §3-a 自证式枚举:「6 树…(**②③④云上 3 树、⑤⑥ mac 2 树**)」= 枚举 5 树却称 6 树。
- ⇒ **口径错误成立**:"7 处"与"6 磁盘树"只能二选一(把行①R2 双重计入"6 磁盘树",或文字层面漏列第 6 树),与其自身 6 行清单不自洽。verify 头「漏 3 处」与其 §7.1 只列 2 项(云上 GIT_REPO、mac 拆两处)同样不自洽。

### 2.2 实物对账(mac 全盘扫)
- **mac 上存在第 3 棵同类树(第 6 棵磁盘树)**:`/Users/linhuichen/code/trade-data-signal-staticdata/data/fund_nav` — 实测 **26,370 文件 / 574M / 09-11 代际**(与⑤⑥同代,内容同族),**未列入任何清单、未删、未声明**。
  - 它与云上④同类:同为 staticdata 仓 `data/fund_nav`(④被删,它被漏)。按本任务已执行口径,本应同列同处。
  - 影响面(机制推演,静态读码):mac staticdata 是 `staticdata_backup_async.sh` 的备份源面(L158 全量 rsync + step3.5b `upload-large-json`);该脚本明示「本地无 systemd(mac)→ nohup fallback」可 mac 侧跑 → mac 侧一跑会把 26,370 个 **09-11 旧代际** gz 传向 signal-backup2 `large-json/`(覆盖 09-22 正本)。此为推演非实跑,但处置该残余可一并消掉。
- 另一棵 `trade-data-signal-staticdata-old-20260926/data/fund_nav`(26,370)为**已拍板保留的回退保险**(至 2026-10-30,memory `staticdata-old-mirror-keep-decision`),**勿动**。
- 云上全盘扫:3 树全 GONE + `find /home/ubuntu/code -maxdepth 6 -name fund_nav -type d` = **0 残留**;mac 全盘扫(trade*/wt/worktrees/-depth 9)= 仅上述 2 处。**⑤⑥/②③④/R2 清单内 6 处全灭属实**(独立复核见 §3)。

### 2.3 归因
**计数口径错误(主,verify 源头、exec 继承)+ 一处未声明残余面(mac staticdata)**。不是"清单内漏删"——清单内 6 处的执行干净利落;问题是"清单本身与总数不自洽 + 残一树未声明","7 处全删/6 磁盘树 GONE"(exec L9/L15/L45/L122)与实物不符。

## 3. 自验 a-f 独立复核(我做的独立动作 / 限制)

| 项 | 我的独立复核 | 判定 |
|---|---|---|
| **a** R2 归零 | `/tmp/b3/r2_fundnav_post.json`(10:00)=`[]`;我另 curl `ssd.fx8.store/fund_nav/{000001,970205,027213}.json` 全 **404** + CF 路径 `ss.fx8.store/r2/fund_nav/000001.json` **404** | ✓ |
| 6 树 GONE | 云上②③④:ssh 只读 `ls -d` 全 GONE + 云上全盘 find 0 残留;mac⑤⑥:本地 `ls -d` GONE | ✓("7 处全空/6 树 GONE"表述例外见 §2 — 旧镜像+mac staticdata 仍在) |
| **b** 备份未动 | `/tmp/b3` pre/post 审计件(09:56/10:00)回读:均 **26,458 / 110,870,643 B**(与 verify §4 记录一致);抽样 sha256 重算 `/tmp/b3/restore_test/fund_nav/000001.json` = `953ac5a3…294af27c`(与记录**逐位一致**);机制侧:工具白名单仅 signal-data 桶,结构上触不到 backup 桶 | ✓(限制:未直接对私桶 signal-backup2 重 LIST——按派单只允许 curl 只读口径;以审计件+白名单+verify 前验三重支撑) |
| **c** 线上 404 | 见 a(独立 curl,含 exec 声称的 ssd 直连 + 我补的 CF /r2/ 回退路径) | ✓ |
| **d** nav_bucket=256 | 审计件 pre/post 均 **256**;我另 curl `nav_bucket/{ca,0c,5c}.json` × {ssd 直连, ss/r2 CF} **6 连 200**;云上 staticdata/data/nav_bucket 实测 256 | ✓ |
| **e** deploy 闸门 | 实核 `scripts/check_data_integrity.py`:L1202 `def check_fund_nav`、**L1220** `nav_dir = data_dir / "nav_bucket"`、L1927 注册点 —— 与旧 `fund_nav/` 目录无关 ✓(exec 报 L1220 准确;verify 报 L1219 差 1 行,无关紧要)。旁证:check_data_gap_alerts 读 DB(注释 L777 明示)✓;alert_denoise_rules 仅 key 分类 ✓;upload_r2 L3477-3478 fund-nav 通道 `r2_prefix="nav_bucket"`,无 fund_nav 前缀通道 ✓;check_r2_consistency 全文件 **0 处 fund 字样**(verify §6 称"仅 1 处注释 L308"未复现——方向安全:该文件确不扫 fund_nav,细节diff建议顺手勘误) | ✓ |
| **f** 删后复查 | 同 a 表述注意点;清单内逐树复测全 0/GONE | ✓ |
| item⑥ 未动反证 | `main...HEAD` = 仅 2 文件(新增);`git show --stat` tip = 同 2 文件;无前端/无其它改动(不需要 bump,§24 未触);无冲突/倒退(§23.11) | ✓ |

## 4. 恢复路径可用性(§25④)

- `scripts/restore-large-json.sh` 在位(26,110B),支持 `--target`(任意位置,含 `--target=`)/`--all`/`--list`/`--date`(参数解析 L278-320);默认目标 = trade-data/data(docstring);**无 x 位 0644**(报告注1 属实)。
- 报告逐树 `--target` **5 行齐**(对应被删 5 树)✓;注2(R2 前缀无一键重推;`upload-fund-nav` 现役只传 nav_bucket —— 我核实 upload_r2 L1704/L3477 属实;**缺口如实声明**=服务面缺口非数据缺口)✓;注3(mac 旧代际 26,370 ⊂ 26,458、无独有文件/独有日期——引用 verify §1.2,成立)✓。
- 未见隐瞒项;唯一"未声明"= mac staticdata 残树本身(见 §2,无证据表明实施方知情,属漏知非隐瞒)。

## 5. 报告质量(§25 四件 + 复现)

- ①备份验证(引用 verify §4,verify 已在 main)✓ ②逐处计数+手段+删除顺序+复现命令 ✓(数字口径缺陷见 §2)③恢复路径(§4)✓ ④删后验证 a-f ✓(证据链我复核成立;仅"全空/全删"表述失实)。**四件齐。**
- §21 公示:N/A(无算法改动)。§22:未产生新的多展示位不一致(nav_bucket 为唯一 serving 源;前端 fund_nav 回退退役属已拍板 D2 缓动——app.js L27840 实物行号核实属实)。§15 回归面:受影响老功能=基金弹窗净值走势回退路径(404→降级提示不崩溃,verify §6 结构核),无其它老功能受影响。

## 6. 低分项(<80)已滤 3 个

工具 XML 正则解析对特殊字符 key 的脆性(约 50,本前缀无影响)/ `--expect` 非强制(约 25,文档已写明)/ 审计清单与 run 日志仅存 /tmp 易失(约 50,已列修正项 4)。

## 7. 复现命令(本次审查用,全只读)

```bash
# mac 本地
ls -d /Users/linhuichen/code/trade-data/static-site/data/fund_nav /Users/linhuichen/code/trade/static-site/data/fund_nav   # 全 GONE
ls /Users/linhuichen/code/trade-data-signal-staticdata/data/fund_nav | wc -l   # 26370(未声明残树)
find /Users/linhuichen/code/trade* -maxdepth 9 -name fund_nav -type d           # 仅 staticdata + old-20260926 两处
# 云上(只读)
ssh -i ~/tdsignal.pem -4 ubuntu@122.51.111.173 'ls -d /home/ubuntu/code/trade-data/static-site/data/fund_nav /home/ubuntu/code/trade-data-signal/static-site/data/fund_nav /home/ubuntu/code/trade-data-signal-staticdata/data/fund_nav; find /home/ubuntu/code -maxdepth 6 -name fund_nav -type d'   # 全 GONE + 0 残留
# 线上(只读)
curl -s -o /dev/null -w '%{http_code}\n' --max-time 15 "https://ssd.fx8.store/fund_nav/000001.json"        # 404
curl -s -o /dev/null -w '%{http_code}\n' --max-time 15 "https://ss.fx8.store/r2/fund_nav/000001.json"      # 404
curl -s -o /dev/null -w '%{http_code}\n' --max-time 15 "https://ss.fx8.store/r2/nav_bucket/ca.json"        # 200
# 审计产物回读(/tmp/b3,一手 LIST 输出)
python3 -c "import json;print(len(json.load(open('/tmp/b3/r2_fund_nav_pre.json'))))"      # 26458
python3 -c "import json;print(json.load(open('/tmp/b3/r2_fundnav_post.json')))"            # []
python3 -c "import json;d=json.load(open('/tmp/b3/r2_backup_post.json'));print(len(d))"    # 26458
shasum -a 256 /tmp/b3/restore_test/fund_nav/000001.json                                     # 953ac5a3…294af27c
# 闸门/通道行号
grep -n 'nav_dir\|def check_fund_nav' scripts/check_data_integrity.py   # L1202/L1220/L1927
```

---
> 报告人:reviewer(独立于实施 agent;结论均基于本次只读实测与逐字读码,未采信自述)。
> 交接:修正项 1-2 完成后请主控派人按本报告复核 §2 两处后放行;D2 缓动观察点(10-13/10-14)与 #111 状态列更新属主控链,不在本审查范围。
