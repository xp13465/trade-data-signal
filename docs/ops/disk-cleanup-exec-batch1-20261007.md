# 磁盘清理「批 1」执行报告(2026-10-07,role-implementer)

> 范围:甲2 `data/release/` + 甲3 `.bak` 三件 + 甲4 `.git/lost-found/` + 甲6 `/tmp/AweSun_*`。
> 输入:`docs/ops/disk-cleanup-verify-20261007.md`(只读核实)。进度文件:`/tmp/agent-progress-disk-clean-batch1.md`。
> 全程遵守 §25:先备份 → 实测可恢复 → 验过直接删。**零外发**(仅 GitHub API GET 读 + R2 GET 读);未写 R2、未发任何通知、未改任何 tracked 文件、未 commit/push。
> 删除方式:逐路径显式列出,无通配 `rm -rf`。

---

## 一、逐项结果

### 甲2 `data/release/`(657M)—— 闸门 PASS,已删

**闸门① 4 个 asset size 逐位比对(API vs 本地)—— PASS**

| asset | 本地 size | GitHub API size | 一致 |
|---|---|---|---|
| etf_national_team.db.tar.gz | 52,511,320 | 52,511,320 | ✓ |
| public_fund.db.tar.gz | 578,428,929 | 578,428,929 | ✓ |
| sentiment.db.tar.gz | 37,396,124 | 37,396,124 | ✓ |
| stock_daily.db.tar.gz | 19,547,655 | 19,547,655 | ✓ |

**闸门② 回读 md5 逐位一致 —— PASS(2/4 回读,≥1 达标)**

| asset | 回读(size 完整?) | 远端 md5 | 本地 md5 | 一致 |
|---|---|---|---|---|
| etf_national_team.db.tar.gz | 52,511,320 完整 | `07e26b3241f27ff0cd0cf8f4f3127a95` | `07e26b3241f27ff0cd0cf8f4f3127a95` | ✓ |
| stock_daily.db.tar.gz | 19,547,655 完整 | `946ece063b97d45488baa12e0779411e` | `946ece063b97d45488baa12e0779411e` | ✓ |
| sentiment.db.tar.gz | 未完成干净回读 | — | `3ea4863743054a34a7f5bf3d0a068db3` | 未回读 |
| public_fund.db.tar.gz | 未回读(578MB,带宽限制) | — | `12f64b245ab83107633d45d92c8b6f85` | 未回读 |

> 主控 21:33 提醒「抽样闸门已满足,别再下大包」后即停掉未完成下载。**回读 2 个(含 1 个最小 19.5MB + 1 个 52MB)已超「至少 1 个」要求**;sentiment/public_fund 仅 size 比对,未逐个回读 md5(受下载速率限制),恢复路径 = GitHub Release 下载。

**删除清单(逐路径显式)与 du**
```
删前 du -sh data/release = 657M
data/release/etf_national_team.db.tar.gz   52,511,320
data/release/public_fund.db.tar.gz        578,428,929
data/release/sentiment.db.tar.gz           37,396,124
data/release/stock_daily.db.tar.gz         19,547,655
→ 4 文件删除 + 空目录 rmdir;删后目录不存在
```
**恢复路径**:GitHub Release `db-archive-2026-08-10`(4 assets 直下)——
`https://github.com/xp13465/trade-data-signal-staticdata/releases/tag/db-archive-2026-08-10`(README.md:363 即该对外分发点)。

---

### 甲3 `etf_national_team.db.bak-backfill-*` + `alert_state.json.bak-*`×2(双树,共 74M)—— 闸门 PASS,已删

**闸门① R2 `decommissioned/` 两个 key 只读列举在位 —— PASS**
```
list signal-backup prefix=decommissioned/ status=200 KeyCount=2
  decommissioned/decommissioned-small-baks-20260903.tar.gz               11,259 B   ETag 6f905c9b077884d1b17df39228865948
  decommissioned/etf_national_team.db.bak-backfill-20260728-232308.gz  10,968,910 B  ETag 1b82c2dd650b883d0dccd0a8466da569
```
(与报告 §一.4 逐项一致)

**闸门② 只读取回 + md5 逐位一致 —— PASS**

> 说明:`restore-r2-backup.sh` 会**写 `data/<key>`(覆盖本地源)**,非只读;为不覆盖线上、保住比对锚点,改用脚本同款读取路径(`upload_r2.s3_request("GET",...,bucket="signal-backup")`)落到 `/tmp` 再比对。

| 对象 | R2 取回 | md5(R2) | md5(本地) | 一致 |
|---|---|---|---|---|
| backfill db(.gz 解压后 38,793,216 B) | 10,968,910 B(net) | `46f5dab90d82d763e6a80311922f9baf` | `46f5dab90d82d763e6a80311922f9baf` | ✓ |
| alert_state.json.bak-68c51a59-20260804-234731 | tar member 2,222 B | `f41b40af941399093e28a1848e302a90` | `f41b40af941399093e28a1848e302a90` | ✓ |
| alert_state.json.bak-fix-20260814-191445 | tar member 13,331 B | `b1dc8a658b3f02d300e46031c359e7de` | `b1dc8a658b3f02d300e46031c359e7de` | ✓ |

**删除清单(逐路径显式)与 du**
```
删前 du -ch(6 文件)= 74M
trade 侧:      data/etf_national_team.db.bak-backfill-20260728-232308   38,793,216
               data/alert_state.json.bak-68c51a59-20260804-234731            2,222
               data/alert_state.json.bak-fix-20260814-191445              13,331
trade-data 侧: 同名三文件(与 trade 侧 md5 完全相同)                       38,808,769
→ 6 文件全删,删后 glob 零命中
```
**⚠️ 范围标注**:报告 §二表 甲3 行明写「双树各一份 backfill ⇒ 两棵都删」,故按**双树都删**(实测 74M,超派单字面 37M);已如实记录。

**恢复路径**:`bash scripts/restore-r2-backup.sh etf_national_team.db.bak-backfill-20260728-232308.gz`(及 `decommissioned-small-baks-20260903.tar.gz` 解包取 alert_state ×2)。
**⚠️ 该恢复路径默认失效(本轮实测)**:脚本用 `upload_r2.BACKUP_BUCKET`,而 `.env` 未设 `R2_BACKUP_BUCKET` ⇒ 默认 = `signal-backup2`(#178 迁移后新桶),decommissioned/ 却在**老桶 `signal-backup`** ⇒ 直接跑会 **404**。**实测**:`GET signal-backup2/decommissioned/etf…gz → 404`;`GET signal-backup/…gz → 200`。**可用恢复命令**:
```
R2_BACKUP_BUCKET=signal-backup bash scripts/restore-r2-backup.sh etf_national_team.db.bak-backfill-20260728-232308.gz
```
> 未改脚本/文档(遵守「不碰 tracked 文件」),建议主控收口时修正 `restore-r2-backup.sh` 默认桶或 `docs/decommissioned-backups.md:85`(该行仍写「默认 signal-backup」,已过时)。

---

### 甲4 `.git/lost-found/`(17M)—— 已归档并实测可恢复,已删

- 归档:`tar czf /Users/linhuichen/r2-archive-20261007/git-lost-found-20261007.tar.gz -C /Users/linhuichen/code/trade/.git lost-found`
  - 产物 11,190,130 B,md5 `9091a58fccfb6ccdf0cecc46bcd716a5`;688 文件 → 691 条目(含 3 目录)
- 实测可恢复:解包到 `/tmp/lf_verify` → 688 文件,**文件名/内容 md5 集合与原目录逐位相同**(`diff` 零差异)
- 删除:`rm -rf /Users/linhuichen/code/trade/.git/lost-found`(逐路径显式);删前 du 17M,删后不存在;`.git` 其它项(objects/refs/worktrees)未动,未跑 gc
- **恢复路径**:`tar xzf /Users/linhuichen/r2-archive-20261007/git-lost-found-20261007.tar.gz -C <target>`(或重跑 `git fsck --lost-found`)

---

### 甲6 `/tmp/AweSun_*.dmg` + `.pkg`(198M)—— 已删

- `ls -l` + `file` 核对确为 AweSun 安装包(非项目文件):
```
/tmp/AweSun_v16.5.0.30905_arm64.dmg  103,916,877 B  (zlib compressed data / macOS dmg)
/tmp/AweSun_v16.5.0.30905_arm64.pkg  103,768,353 B  (xar archive / macOS pkg)
```
- 删除:`rm -f` 两文件(逐路径显式);删前 du 99M+99M,删后 glob 零命中
- **恢复路径**:从 AweSun(Aweray)官网重新下载对应版本(非项目资产)

---

## 二、净释放实测

| 项 | du 删前 | 说明 |
|---|---|---|
| 甲2 data/release | 657M | 4 tar.gz |
| 甲3 .bak 双树 | 74M | 6 文件(双树) |
| 甲4 .git/lost-found | 17M | + 归档 11MB 落在 ~/r2-archive-20261007/ |
| 甲6 AweSun | 198M | 2 文件 |
| **合计** | **946M** | |

> 派单估 ≈1.29G,实测 **946M**(差异:甲3 实测含双树 74M;余为 du 口径)。另清理了本 agent 自建临时目录 `/tmp/release_verify`(回读用的下载副本,归零)。
> 磁盘:`df` = 460Gi 容量 / 134Gi 可用(删除后快照;删前未单独记 df,采用逐项 du 记账)。

## 三、诚实缺口 / 未做

1. **甲2 仅 2/4 回读 md5**:etf + stock_daily 回读完整且逐位一致;sentiment、public_fund **只核 size 未回读 md5**(受下载速率限制,主控叫停大包)。
2. **甲2 下载通道异常(已绕过)**:本轮实测 **`github.com:443` 被墙/超时**(`http=000`),`curl` 直连 release 下载 URL 卡死,`-4` 无效;改用 **`api.github.com/.../releases/assets/<id>` + `Accept: application/octet-stream`** 才通(重定向到 `objects.githubusercontent.com`,~47KB/s/连接,并行 3 连接聚合 ~77KB/s)。**不影响闸门结论**(回读 md5 已证内容一致)。
3. **甲3 恢复脚本默认桶失效**(见上):建议主控修脚本/文档;本任务未改。
4. **甲3 双树都删**(74M > 派单字面 37M):依据报告「两棵都删」;已标注。
5. **甲4 归档是本地归档**(`~/r2-archive-20261007/`),**未上传 R2**——报告 §二理解为「本地归档即可」;如需异地副本请主控补充。
6. 硬排除项全程未动(`/tmp/restore_test/`、`staticdata-old-20260926`、根 `data/` 保护项、双树活跃数据、当前会话)。执行时 **`.claude/worktrees/agent-abef716d45a426513` 已不在位**(非本 agent 所为,本 agent 全程未引用该路径)。

## 四、复现命令(关键)
```bash
# 甲2
curl -s --max-time 20 "https://api.github.com/repos/xp13465/trade-data-signal-staticdata/releases?per_page=10" \
  | python3 -c "import sys,json;[print(a['name'],a['size']) for r in json.load(sys.stdin) for a in r['assets']]"
# 回读(通道:api assets 端点,Accept: application/octet-stream)
# 甲3
python3 scripts/upload_r2.py list decommissioned/ signal-backup
# 甲4
tar tzf /Users/linhuichen/r2-archive-20261007/git-lost-found-20261007.tar.gz | wc -l
```
> 报告落档:本文件(worktree 内 `docs/ops/disk-cleanup-exec-batch1-20261007.md`;**未 commit/push**,待主控统一收口)。