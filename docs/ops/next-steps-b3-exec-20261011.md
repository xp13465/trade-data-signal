# B3 fund_nav 遗留清理执行报告 — #111(2026-10-11)

> 残留后台任务:**无**(全程无 `moved to the background (ID:`;所有命令均在生效 timeout 内前台完成)。
>
> 任务:next-steps-plan §1 B3 执行(先 tester 验证 → implementer 清理)。方案 v2.1 / #111,2026-10-11 用户拍板开工。
> 执行:implementer(role-implementer);分支 `feat/b3-fundnav-cleanup`(从 origin/main 切)。
> 依据:清理前验证报告 `docs/ops/next-steps-b3-verify-20261011.md`(判定 **可清理 PASS**,§25 备份核验通过)。
> 时间窗:09:57~10:00 CST 完成全部写动作(**早于 16:00 目标**;避 22:30 update_all rsync 时点,避 22:00-01:30 R2 写窗)。
> **总体判定:7 处删除完成,自验 a-f 全过。**

## 0. 结论速览

| 项 | 结果 |
|---|---|
| 7 处删除 | **全删完**(6 磁盘树 GONE + R2 前缀 0) |
| 删后自验 a-f | **全 PASS**(见 §3) |
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
| — | 合计 | **6 磁盘树 + 1 R2 前缀** | 全删 | |

**未动对象(反证)**:

| 对象 | 删前 | 删后 |
|---|---|---|
| R2 `signal-backup2` `large-json/fund_nav/`(备份) | 26,458 | **26,458**(未动) |
| R2 `signal-data` `nav_bucket/`(现役) | 256 | **256**(未动) |

**删除顺序**:源侧→下游(⑤ mac REPO → ⑥ mac GIT_REPO → ② 云上 REPO → ③ 云上 GIT_REPO → ④ 云上 staticdata),R2 前缀 ① 随后。删前逐处 `ls | wc -l` / LIST 复核,与报告一致才删;**一致性不符即停**的要求满足(全程逐位吻合,未触停)。

**为什么 6 树全删**:`deploy.sh` L529 与 `staticdata_sync.sh` L94 两处通用全量 rsync(**无 --delete、无 exclude fund_nav**)→ 只删下游会被源侧残留携带回填;6 树全删后 rsync 无源可带、不重生(验证报告 §2)。**未改 deploy.sh / staticdata_sync.sh / update_all / nav_bucket / 前端**(红线遵守)。

**R2 前缀删除实现**:新增 `scripts/r2_delete_prefix.py`(全 repo 原无删除能力)。
- 安全设计:①默认 dry-run(零写)②`--yes` 门控 ③**桶/前缀白名单硬校验**(ALLOWED 只含 `("signal-data","fund_nav/")`,其余 abort exit 2)④`--expect N` 计数闸门(不符 abort)⑤删后重 LIST 计数须 0(否则 exit 3)。
- 实现:SigV4 复用 `scripts/upload_r2.py:s3_request`(全项目同一签名/路由),POST `/?delete` 批量删(1000 key/批 + Content-MD5 + XML body)。
- 实跑:dry-run 先验 26,458 → 真删 27 批(前 26 批各 1,000 + 末批 458),**deleted=26,458 err=0**,删后 LIST=0。
- 将删对象清单落盘:`/tmp/b3/r2_fund_nav_pre.json`(26,458 条 key/size/mtime,审计用)。

## 3. §25 四件之三:删后验证证据(a-f)

| 项 | 检查 | 结果 |
|---|---|---|
| **a** | 7 处全空 | R2 `fund_nav/`=**0**;6 树逐处 **GONE**(②③④云上 3 树、⑤⑥ mac 2 树);①R2=0 ✓ |
| **b** | large-json 备份未动 | LIST=`**26,458**`;抽样取回 `fund_nav/000001.json` sha256=`953ac5a3b43352bc…294af27c` = 报告记录值(**逐位一致**)✓ |
| **c** | 线上变化 | `https://ssd.fx8.store/fund_nav/000001.json` → **http_code=404**(预期,R2 直连前缀已删)✓ |
| **d** | nav_bucket 现役链未动 | R2 `nav_bucket/` LIST = **256 obj**(未动)✓ |
| **e** | deploy 闸门不坏 | 静态核 `scripts/check_data_integrity.py` `check_fund_nav` 查 `data_dir/"nav_bucket"`(L1220),与旧 `fund_nav/` 目录无关;其余引用(check_data_gap_alerts)读 DB 不读目录(引用验证报告 §6)✓ |
| **f** | 删后 6 树复查全 0 | 逐处复查:6 树全 GONE + R2 前缀 0(**防删不全**)✓ |

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

- 本地实测(本次):`bash scripts/restore-large-json.sh fund_nav/000001.json --target /tmp/b3/restore_test` → 成功 1 / 失败 0,sha256 逐位一致。
- ⚠️ **注1(脚本无 x 位)**:`restore-large-json.sh` 权限 0644,须 `bash scripts/...` 调用(`./` 直跑需 chmod +x)。
- ⚠️ **注2(R2 前缀恢复 = 缺口,如实记)**:**不存在**把 per-code 重新 PUT 回 R2 `fund_nav/` 旧前缀的现成命令(`upload-fund-nav` 现役已改传 `nav_bucket/`)。若未来要恢复 R2 `fund_nav/` 前缀服务面,需临时脚本 GET(large-json)→解压→循环 PUT(无现成通道)。此为「服务面恢复」缺口,**非「数据丢失」缺口**——数据本体已完整备份。
- ⚠️ **注3(mac 旧代际)**:mac 2 树为 09-11 旧代际(26,370 ⊂ 26,458,无独有文件/独有日期,抽样核实);若需恢复,`--all` 会还原为 09-22 新代际(26,458),不还原旧代际差异——差异价值近零,验证报告 §7.3 已记,不建议单独立项。

## 5. 复现命令

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

## 6. 遗留 / 注意(交主控)

1. **7 处已全删**,方案「4 处」口径经实测修正为 7 处(验证报告 §1.1),勿再按 4 处复核。
2. **#237 pre-upload 404** 与本次清理无因果(验证报告 §3 附注),10-12 为首发观察日,按 plan §4 走。
3. **D2 前端缓动观察面**:`app.js` L27840 回退 `fetchJSON('https://ss.fx8.store/r2/fund_nav/${code}.json')` 删除后转 404 = 预期降级(不崩溃);plan D2 定「数据先清、前端缓 1-2 日再发版下线」,**本任务不碰前端**。
4. 云上 `/home/ubuntu/` 顶层 2 个 0 字节异常名文件(验证报告 §7.6),疑历史脚本残留,**建议另案核查**(本任务只读发现,未动)。
5. **R2 前缀无一键重推命令**(§4 注2),服务面恢复缺口如实记录。

---
> 报告人:implementer;结论依据均为本次实跑输出(逐处计数→删除→删后复查/对账)。
> §25 四件齐:①备份验证引用 ②删除清单逐处计数/命令 ③恢复路径 ④删后验证证据;复现命令见 §5。