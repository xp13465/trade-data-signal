# R2 备份桶容量查证报告(2026-10-07)——老桶为何还是 8G · 新桶为何开始增长

> **派单**:用户报案「新 R2 备份桶(backup2,独立账号)开始容量增长了;老 R2 备份桶还是 8G,没缩到预期的 6G,什么情况?」——本报告为只读查证(**R2 仅 LIST/HEAD,零写零外发零删除;不 commit**),回答 6 问。
> **实测时点**:2026-10-07 21:07~21:22 CST(老桶 21:07 完成 / 新桶 ~21:12 / 主桶 ~21:22)。

## 0. 一句话结论

**三件事全部对得上,无故障、无泄漏**:① 老桶 8.16 GB(十进制,实测 7.595 GiB)没缩 = 「预期 6G」是 #186 的 **lifecycle 自然回收时间线**(首批存量到龄 10-10~12),10-07 尚未到点——lifecycle 实测在跑(两天自动回收 313.2 MB);② 新桶 2.001 GiB 增长 = **10-05 13:29 写入路径切新桶后的正常表现**(一次性回填/归档 ≈1.6 GiB + 日常 ≈110 MiB/天);③ 老桶已**冻结**(全前缀最后写入 10-05T04:55:32Z=12:55 CST,在切点 13:29 之前),不再增长,只会被 lifecycle 逐日回收。

## 1. Q1 两桶实测容量(凭据自 .env 读入,只读 LIST;命令见 §7)

### 1.1 老桶 `signal-backup`(老账号 `9be954e8…`)= **38,327 objs / 8,155,372,290 B = 7.595 GiB = 8.16 GB(十进制,= CF 面板显示)**

| 前缀 | 对象数 | 字节 | GiB | mtime(UTC) |
|---|---|---|---|---|
| pre-upload/ | 6,585 | 3,453,993,283 | 3.217 | 2026-10-03 ~ 10-05T04:55:32 |
| mac-backups/ | 1 | 2,278,230,346 | 2.122 | 2026-10-04T00:44 |
| backup/ | 24 | 1,319,114,393 | 1.228 | 2026-09-23T13:01 ~ 10-04T13:08 |
| large-json/ | 31,673 | 454,483,790 | 0.423 | 2026-09-30 ~ 10-05T04:31:13 |
| weekly/ | 6 | 312,556,531 | 0.291 | 2026-09-14 ~ 09-28 |
| monthly/ | 8 | 303,160,886 | 0.282 | 2026-07-21 ~ 10-01 |
| claude-backup/ | 28 | 22,852,892 | 0.021 | 2026-09-07 ~ 10-04 |
| decommissioned/ | 2 | 10,980,169 | 0.010 | 2026-09-03 |

pre-upload 按日:10-03 277 个/0.705 GiB;10-04 2,697/1.322 GiB;10-05 3,611/1.190 GiB。large-json 全为 flat(legacy 按天目录 0 个——已由 #186 C 档清完,见 §2④)。

### 1.2 新桶 `signal-backup2`(新账号 `2455352499…`)= **31,692 objs / 2,148,344,504 B = 2.001 GiB**

| 前缀 | 对象数 | 字节 | 说明 |
|---|---|---|---|
| large-json/ | 31,673 | 454,498,988(433.4 MiB) | 10-05 回填 31,635 + 10-06 增 36 + 10-07 增 2;mtime 10-05T08:55:49Z 起 |
| decommissioned/ | 6 | 1,140,898,597(1088.0 MiB) | pfdb 备份 2×~558MB @10-05 + 10-07 清理归档 |
| backup/ | 6 | 330,618,259(315.3 MiB) | 10-05~10-07 每天 2 个 ≈105 MiB/天(21:00 CST 链路) |
| weekly/ | 2 | 110,197,083(105.1 MiB) | @10-05 快照 |
| monthly/ | 2 | 110,197,083(105.1 MiB) | @10-05 快照 |
| claude-backup/ | 2 | 1,891,667 | 10-05/10-06 各 1 |
| git-branch-bundles/ | 1 | 42,827 | 10-05T06:13 |

**pre-upload/ = 空(0 个)**——原因见 §3。**新桶最早对象 = git-branch-bundles @10-05T06:13:19Z(14:13 CST)> 切点 13:29:55 CST**。

### 1.3 主桶 `signal-data`(老账号)= **31,463 objs / 2,857,478,024 B = 2.661 GiB**

前缀大头:fund_nav 531 MiB / nav_bucket 535.5 / data 517.6 / trade_sim_data 367.9 / trade_sim 195.3 / index 65.7 / industry 122.9 / lab 94.5 / etf 111.7 等。对象数与 10-07 清理 exec 后(31,463)一致;字节 +4,862 B vs exec 参考值(live 对象并发重写,同 exec 报告 +1,590 B 性质)。

**老账号合计 = 8,155,372,290 + 2,857,478,024 = 11,012,850,314 B = 11.01 GB 十进制(10.26 GiB)**,超 10 GB 免费线约 1.0 GB(超线部分按 $0.015/GB-month 量级 ≈ 月 ¥0.1 级;10-12 起自然回落 <10,见 §5)。新账号 2.148 GB,远低于 10 GB。

## 2. Q2 老桶为什么还是 8G(逐条排除)

### ① 压缩方案(2.122 GiB 整包)——**已执行,但它本来就不清桶**
- 证据:`docs/ops/r2-archive-upload-20261004.md`——`signal-backup/mac-backups/archive/mac-backups-2026-10-01.tar.zst` 2,278,230,346 B(SHA256 f36dd009e27f…),10-04 上传 + 回读 86/86 对账 PASS;本次实测 mac-backups/ 恰 1 个对象 2,278,230,346 B 逐位一致。
- 性质:**「把本机 mac-backups 压缩归档上传到 R2」= 新增一个 2.122 GiB 对象**,不是「压缩桶内现有对象」;本机原件按用户拍板未删。⇒ 老桶 8G 与它无关,不存在「压缩完就该变小」。

### ② 老桶各前缀占用与 mtime 分布(见 §1.1)——**可回收存量 ≈ 4.77 GiB、永久地板 ≈ 2.85 GiB**
- 可自然回收:pre-upload 3.217 + backup 1.228 + weekly 0.291 + claude 0.021 ≈ **4.77 GiB**(全部等 lifecycle 到龄)。
- 地板(不回收):mac-backups 2.122 + large-json flat 0.423 + monthly 0.282 + decomm 0.010 ≈ **2.84 GiB**。

### ③ 「14 天 lifecycle 只覆盖 backup/」**不成立**(两层更正)
- **不是只有一条**:#179 定案(2026-10-05 用户 dashboard 实测)——**新老两桶均已配 5 条规则**:pre-upload 7 / weekly 28 / monthly 365 / claude-backup 30 / backup 14;不配的仅 decommissioned/、mac-backups/(刻意)与 large-json/(prefix 无通配会命中 flat 唯一副本)。代码注释同载 `scripts/upload_r2.py:288-293`(含纠偏句「勿信旧报告『其余前缀全无 lifecycle』的配置前快照」)。
- **实测在跑**:10-05→10-07 两天 lifecycle 自动回收 **313.2 MB**(backup -4 对象 / weekly -2 / claude-backup -2),与规则推算一致(`docs/ops/r2-cleanup-audit-20261007.md` §2.1);本次实测 backup/ 最老 mtime 09-23 ≈ 10-07−14 天,且对象数 24 ≈ 2 个/天×12 天 ⇒ **老桶 backup/ 的实际生效保留期 = 14 天**(由 mtime 分布推断,非 dashboard 直读;可解 #169「30 天」记录打架)。
- **不缩的真原因 = 存量到龄时间未到**:pre-upload 存量写于 10-03~10-05,7 天期首批 **10-10~12** 才删;backup 14 天期 10-19;weekly 28 天期 10-26。10-07 的「还是 8G」就是 #186 时间线内的正常状态。

### ④ #186 已清 430.05 MiB **已反映在实测**(对得上)
- `docs/ops/r2-cleanup-exec-20261007.md`:A 档(主桶 21 对象 171,894,762 B)+ C 档(老桶 27,673 对象 279,046,499 B)= 430.05 MiB;删后老桶 **38,327 / 8,155,372,290 B 与本次实测逐位一致**;老桶 large-json legacy 已归零(本次实测 legacy=0)。
- ⇒ 用户看到的 8.16 GB **已含**这次清理(清理前 8.43 GB 十进制);离「6G」的剩余差 = 等 lifecycle(10-10~12 起)。

## 3. Q3 新桶为什么开始增长

- **写入方 = 切桶后的全部备份通道**:`upload_r2.py:286` `BACKUP2_BUCKET` 默认 `signal-backup2` + `_route_bucket`(:402-412)按目标桶路由双账号端点/凭据(#178,已合 main `5e014d9e3`)。云上日志明证(只读 grep):
  - 10-05 16:52 轮 `staticdata_backup_async_20261005_165200.log`:**trigger=backfill** 全量回填 `-> signal-backup2/large-json/…`(4798s);21:16 轮增量 36/36 入新桶(#185 销账记录)。
  - 10-06 18:00 轮:`[large-json] 模式=增量 全集 31673 / 跳过 31637 / 待传 36 -> signal-backup2`。
  - 10-07 18:00 轮:`待传 2 -> signal-backup2`(signal_kelly_trades 82MB→13MB gz、sdc 84MB→14MB gz;manifest 31673 行重写)。
- **首现**:全桶最早对象 10-05T06:13:19Z(14:13 CST);large-json 回填首写 10-05T08:55:49Z(16:55 CST)——均在切点 13:29:55 CST 之后。
- **增长构成(2.001 GiB)**:一次性大额 ≈ large-json 回填 433.4 MiB + decommissioned 1,088 MiB + weekly/monthly 各 105.1 MiB ≈ **1.6 GiB**;日常节奏 = backup/ 105 MiB/天(2 obj/天)+ claude-backup ~0.9 MiB/天 + large-json 增量(10-06 36 个分片 / 10-07 2 个大文件 ≈27 MB gz)。**假期基线 ≈ 110~135 MiB/天**。
- **pre-upload 为空的原因**:10-05~10-07 云上**全部**日志 grep「`pre-upload|将被覆盖`」= **0 命中**(假期无数据变更 ⇒ 主桶通道全部「内容未变化,无需上传」⇒ 无覆盖 ⇒ 无备份)。正常,非跳过 bug。
- **是否正常**:是——设计即「新写落新桶」;不是泄漏,不是重复写。

## 4. Q4 因果判断:**是**(「写路径已切新桶 + 老桶存量搬迁/压缩未做」完整成立)

| 时点(CST) | 事件 | 证据 |
|---|---|---|
| 10-05 13:29:55 | 切桶:云上代码含 #178 双端点路由(commit `a8086deba`,merge `5e014d9e3`) | `git show -s a8086deba`;云上 .env 含 `R2_BACKUP2_*` 四键 |
| 10-05 12:55:32 | **老桶最后写入**(全前缀 max mtime 10-05T04:55:32Z < 切点) | 本次 LIST |
| 10-05 14:13 / 16:55 | **新桶首写**(bundle / large-json 回填) | 本次 LIST + 云上日志 |

老桶存量:用户已拍板「**存量不搬**,靠 lifecycle 自然回收」(memory `r2-backup-bucket-second-account`);压缩(2.122 GiB)是归档上传非清桶(§2①)。⇒ 老桶 8G 不动 = 设计内状态,变量只剩「lifecycle 到龄时钟」。

## 5. Q5 风险与下一步(§25)

- **老桶会不会持续涨**:不会(已冻结;唯一动态是 lifecycle 只减不增)。**持续占费点** = 老账号合计 11.01 GB 超 10 GB 线 ~1.0 GB(量级 ~¥0.1/月),且 **10-10~12 pre-upload 清空后自然回落至 ~7.6 GB <10**。
- **「缩到 6G」步骤(每步一行)**:
  1. **等 lifecycle 自然到龄(推荐:零动作、零风险)**:10-10~12 pre-upload −3.454 GB → **~7.56 GB**;10-18/19 backup 排空(旧桶无新写入,存量到期即走)→ ~6.24 GB;10-26 weekly → **~5.93 GB(十进制)< 6 GB 达标**(claude 11-03 补 -0.02);与 #186「~5.0 GiB」估算同向(本次为实测口径复算)。
  2. 若要**提前**:手动删老桶 pre-upload/ 存量 3.217 GiB——**删除类,§25 前置**:先备份(可备到本机/新桶)+ 实测可恢复(清单比对+抽样逐位)+ 写明恢复路径,验过才删、验不过停。
  3. 手动删老桶 backup//weekly//claude 存量——同上 §25;注意这些前缀**本也会自然清**(10-19/10-26/11-03),捷径收益小、风险不值得。
  4. **mac-backups 2.122 GiB 不可动**(唯一副本异地容灾,#198 补正);要动须先备份验证。
  5. **large-json flat 0.423 GiB 老桶副本**:唯一副本属性 + #186 D 档判定「不可动」;且该前缀不配 lifecycle(prefix 无通配,配了会误中 flat)。
  6. monthly/decomm 地板留存(合计 ~0.29 GiB,占费忽略级)。
- **复市后新桶预警(需观察)**:pre-upload 将开始在新桶累积(旧桶交易日历史速率 ~0.7~1.35 GiB/天);按 7 天保留外推稳态最坏 ≈ 5~8 GiB,叠加其它前缀 ≈ **逼近 10 GB 新账号免费线**——建议复市后实测一轮新桶 pre-upload 日增(假期零样本,外推仅参考)。
- **风险点(未验证,重点)**:pre-upload 备份链路现为**跨账号 server-side COPY**(源 `signal-data`@老账号 → 目标 `signal-backup2`@新账号;`scripts/upload_r2.py:1171-1179` `x-amz-copy-source`)——自切桶以来**未被现实触发**(覆盖=0);复市后首轮即验。且该函数**失败只记日志不阻断**(:1180-1181)⇒ 若 403 会静默少备份(覆盖前备份是防丢数据护栏),复市后须人工 grep「`⚠ 备份 …失败`」核查。

## 6. 诚实标注

- **实测**(可复核):三桶 LIST 数字与 mtime(本次);云上日志 grep(hits=0、回填/增量行);10-07 audit 的 313.2 MB 回收与删后逐位对账;`git show` 切点。
- **推断**:老桶「冻结」(依据=写入路径已切 + mtime 分布);老桶 backup/ 有效保留期=14 天(自 mtime/对象数推断);复市后新桶 pre-upload 增速(历史外推)。
- **拿不到**:① 我方 key 调 `GetBucketLifecycleConfiguration` 返回 403 ⇒ 桶规则只能以用户 dashboard 为准(#179 已核:两桶 5 条);② 跨账号 COPY 是否 403 未实测(待复市);③ 精确超线月费未查账单(按 $0.015/GB-month 量级)。
- **更正留痕**:memory `r2-backup-bucket-second-account`「老桶只有 backup/ 一条规则」= 10-05 配置前快照,同日 #179 已定案 5 条齐(代码注释 :288-293 亦注明)。
- **未做**:零写(无 PUT/DELETE/COPY/lifecycle 变更)、零外发、未 commit。

## 7. 复现命令(脚本 + 指认)

```bash
# ① 三桶实测(只读 LIST;凭据自 repo/.env 读入,不打印密钥)
cd /Users/linhuichen/code/trade
/Users/linhuichen/code/trade/.venv/bin/python /tmp/r2cap_measure.py signal-backup  /tmp/r2cap_out/old.json   # -> 38327 / 8155372290 B
/Users/linhuichen/code/trade/.venv/bin/python /tmp/r2cap_measure.py signal-backup2 /tmp/r2cap_out/new.json   # -> 31692 / 2148344504 B
/Users/linhuichen/code/trade/.venv/bin/python /tmp/r2cap_measure.py signal-data    /tmp/r2cap_out/main.json  # -> 31463 / 2857478024 B
#   脚本核心:upload_r2.s3_request("GET","",query="list-type=2&max-keys=1000&continuation-token=…",bucket=<桶>)
#   分页列举 + 前缀聚合(路由由 _route_bucket 自动按目标桶选账号端点);全文本次会话 /tmp/r2cap_measure.py
# ② 云上日志(只读 ssh):
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  'cd /home/ubuntu/code/trade-data/data/logs; grep -c "pre-upload\|将被覆盖" *202610[567]*.log'          # -> total_hits=0
# ③ 复市后必做(验证跨账号 COPY 护栏):
#   grep -h "⚠ 备份\|已备份\|export-guard" /home/ubuntu/code/trade-data/data/logs/r2_upload_async_*.log | tail
```

## 8. 参考
- `docs/ops/r2-cleanup-audit-20261007.md`(lifecycle 回收 313.2 MB / 前缀表)· `docs/ops/r2-cleanup-exec-20261007.md`(430.05 MiB 删后逐位对账)
- `docs/ops/r2-archive-upload-20261004.md`(2.122 GiB 归档已执行)· `docs/ops/r2-backup-prefix-lifecycle-audit-20261005.md`(前缀普查)
- `docs/pending-features-index.md` #178/#179/#185/#186 · memory `r2-backup-bucket-second-account`
- `scripts/upload_r2.py`(:286 默认桶 / :402-412 路由 / :1120-1201 pre-upload 备份+减量)
