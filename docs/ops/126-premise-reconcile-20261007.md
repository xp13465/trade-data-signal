# #126 前提对账:「large-json 唯一副本在 git」是否已被 #185① 回填证伪(2026-10-07 只读复验)

> ⚠️ **残留后台任务声明(§0.2)**:本机 harness 任务 `bdguq3fll`(16:36 启动的"远程 nohup 启动 sweep"ssh 包装命令,输出文件 0 字节)至交报告时仍显示 running;远程实测 sweep 进程 16:48 已结束、`ps` 复查=0(疑为 ssh 通道未正常闭合的悬挂包装进程:本地 zsh PID 34151 + ssh PID 34161)。role agent 无 TaskStop 能力,请主控 TaskStop。(补记:主控已 TaskStop 予以清除,本条已闭环。)
>
> 任务:只读调研,对账 #126 调研(09-30)所立前提「9 目录 31239 文件全球只有 git 一份完整副本」在 #185①(10-05 新桶全量回填 31673)之后是否已证伪;要求**集合级**(非数字级)对账。
> 环境:云上 `ssh -i ~/tdsignal.pem ubuntu@122.51.111.173`;staticdata 仓 `/home/ubuntu/code/trade-data-signal-staticdata`;解释器 = 生产 venv `/home/ubuntu/code/trade-data/.venv/bin/python`(3.11.15)。
> 只读声明:全程未改任何仓文件、未 PUT/DELETE/COPY 任何 R2 对象、未 commit、未启停 unit;R2 侧只走 `_list_keys`(分页 list)与 `s3_head`(HEAD);探针均 static-only(未 source/exec 业务脚本主体)。唯一写入 = 本报告文件 + 云上 /tmp 只读对账 scratch + 进度文件 `/tmp/agent-progress-126-premise.md`。

## 0. 判决(一句话)

**前提已证伪,且整个 #126 早已被"执行超越":迁移 10-01 已发生、登记 10-02 已闭环、10-05 换桶后由 #185 复核、今日(10-07)全量复验通过 —— 它是"已完成事项",不是"待设计事项"。**
- 集合级:R2(新桶 signal-backup2/large-json)**==** .gitignore 受管区块 **==** 云上磁盘(9 目录 31666 + data 根 7 大文件 = 31673),逐位相等、**双向差集全 0**;git HEAD@5242b7459 的 9 目录 31235 个文件 **全部**在 R2 中(A0 − R2 = 0)。
- 差集判定(回答任务 Q3):**不是双向差** —— R2 相对 git 是**单向扩张**(31673 ⊋ 31235/31239 口径),扩张 434 项已 100% 归因(§1.3),无孤儿、无缺失。
- 内容级:今日全量 31,673/31,673 对象实测通过(HEAD etag == 磁盘重算 gz md5 == state md5),**0 失败 0 异常**。

## 1. 集合级对账表(命名 / 映射 / 差集)

### 1.1 四层命名与映射链(单一权威源)

| 层 | 形态 | 示例 | 权威来源 |
|---|---|---|---|
| ① 磁盘(staticdata 工作树) | `data/<rel>` | `data/fund_nav/023684.json` | 生产数据本体(云上) |
| ② .gitignore 受管区块 | `/data/<rel>`,L27~L31708 | `/data/fund_nav/023684.json` | `scripts/large_json_excludes.py` default_mode(单一源维护;先刷区块再上传) |
| ③ R2 对象 key(新桶 signal-backup2) | `large-json/<rel>.gz` | `large-json/fund_nav/023684.json.gz` | `upload_r2.py` `_mk_key`(:2975-2976);上传清单直接取 ②(`--print`,print_mode :291-306) |
| ④ 逃生门 key(旧设计) | `large-json/<YYYY-MM-DD>/<rel>.gz` | — | **今日实测 legacy 日期目录 = 0 个**(已消除) |
| 状态清单 | `{<rel>: {size, md5}}` | `data/.r2_large_json_state.json` | `upload_r2.py:3088`(#149e 增量通道) |
| manifest | `docs/large-json-backup-manifest.md` | — | `upload_r2.py:2833` |

映射恒等链:`磁盘 data/<rel>` ↔ `区块 /data/<rel>` ↔ `R2 large-json/<rel>.gz`(去 `data/` 前缀 + 加 `.gz`,一一对应,无二级结构)。

「31673 vs 31673 是巧合吗」——**不是巧合,是构造同源**:上传清单就是区块本身(`--print` 直出,不重新枚举);区块由 `large_json_excludes.py` 单一源每日重生成。本次另用两个独立锚点交叉验证:① git 对象集(§1.2,head_only=0,独立于上传器)② 内容级三方 md5 一致(§1.4)。

### 1.2 三方集合对照(逐目录;2026-10-07 实测)

基准列 = staticdata 仓 git HEAD@5242b7459(迁移前最后一笔数据 commit,2026-09-28 19:01);当日列 = 区块 = R2 = 磁盘。

| 目录 | git@5242b7459 | 当日(区块=R2=磁盘) | 区块−git | git−区块 |
|---|---|---|---|---|
| fund_nav | 26458 | 26458 | 0 | 0 |
| etf | 1710 | 1718 | +8 | 0 |
| accum_nav | 1710 | 1718 | +8 | 0 |
| nav_bucket | 256 | 256 | 0 | 0 |
| signal_kelly_trades_parts | 383 | 383 | 0 | 0 |
| signal_kelly_trades_sdc_parts | 391 | 391 | 0 | 0 |
| index | 173 | 173 | 0 | 0 |
| lab | 65 | 65 | 0 | 0 |
| trade_sim | 89 | 504 | +415 | 0 |
| **9 目录小计** | **31235** | **31666** | **+431** | **0** |
| data 根 >20MB 大文件(不在 9 目录) | 0 | 7 | +7 | 0 |
| **合计** | **31235** | **31673** | **+438** | **0** |

data 根 7 个大文件(>20MB 阈值命中):`accum_nav_map.json`、`offshore_fund_fee_detail.json`、`offshore_fund_performance.json`、`offshore_fund_purchase_status.json`、`offshore_fund_risk_indicator.json`、`signal_kelly_trades.json`、`signal_kelly_trades_sdc.json`。

### 1.3 「31239 口径」与差集 434 全分解

- 「31239」= HEAD 9 目录 31235 + 迁移时 4 个 staged-add(相对 HEAD 是 A,不计入 D):`accum_nav/158025.json`、`accum_nav/562450.json`、`etf/158025-all.json`、`etf/562450-all.json`(4 个今日逐项确认 ∈ 区块 ⊆ R2)。
- 31673 − 31239 = **434**,逐项分解、无剩余:
  - **+415 trade_sim**(磁盘 504 个仿真产物,git 从未跟踪过)
  - **+7** data 根大文件(上列)
  - **+6 etf**:`158039-all`、`158059-all`、`515540-all`、`561650-all`、`562200-all`、`589490-all`(158025/562450 两个已计入 31239 口径)
  - **+6 accum_nav**:同 6 个基金代码(无 `-all` 后缀)
- 等价口径:31673 − 31235 = 438 = 415 + 7 + 8(etf) + 8(accum_nav)。
- **缺失 = 0(双向)**:git−区块 = 0(9 目录逐目录 head_only=0);区块−R2 = 0;R2−区块 = 0。
- 历史口径差解释:09-30 precheck 时旧桶/区块 = **31663**,extra 424 = 415 + 7 + 1(`accum_nav/158039.json`)+ 1(`etf/158039-all.json`);此后 +10 = 5 个新基金代码 × 2 目录(`158059/515540/561650/562200/589490`),10-01 03:02 区块重生成后为 31673(`git log -- .gitignore` 最后变更 = `537317b4a` 10-01 03:02:16,该版本即 31673 条;工作树与 HEAD 零漂移,`git diff --quiet` exit 0)。

### 1.4 内容级 + 状态级(今日实测输出)

- **全量内容扫**(31673 个对象,12 线程,703s,2026-10-07):
  `DONE {'n': 31673, 'ok': 31673, 'bad': 0, 'exc': 0} elapsed_sec 703`;`/tmp/126sweep_ok.txt` = 31673 行,`/tmp/126sweep_bad.txt` = 0 行。
  逐对象断言:`HEAD 200` 且 `etag == md5(gzip(源文件, compresslevel=6, mtime=0) 磁盘重算) == state 记录 md5`(三方一致)。
- 集合级命令输出:`total= 31673 flat= 31673 legacy= 0`;`MISSING(block_not_R2)= 0  EXTRA(R2_not_block)= 0`;`disk_9dir= 31666  block_9dir= 31666  block_minus_disk= 0  disk_minus_block= 0`;`block_non9dir= 7`。
- 状态级:生产 state = `files=31673 bucket=signal-backup2 updated_at=2026-10-07T05:13:50 mode=增量`;manifest 重生成于 10-07 05:14(6,055,596B)⇒ 备份链**今日仍在自转**(10-07 05:13 增量轮)。
- 生产自转旁证:staticdata 仓 HEAD = `7ddc35f2a "data backup [news-fetch] 2026-10-07_16:45 - 3 files"`(迁移后小步提交模式健康);tracked 总数 338,9 目录 tracked = 0。
- 旧桶(signal-backup,legacy):抽样 HEAD `large-json/fund_nav/001305.json.gz` → **200**(存量 flat 键仍活、无 lifecycle,属 #185③ 收尾范围)。

### 1.5 极简时间线(前提的诞生 → 证伪 → 超越)

| 时点 | 事件 | 证据 |
|---|---|---|
| 09-26~09-30 | 旧通道按 `large-json/<日期>/` 滚动,全桶 12142,9 目录从未完整(日期目录 8/8/8/11875/243) | #126 调研(前提诞生:「唯一完整副本在 git」) |
| 09-30 夜 | 固定前缀回填旧桶 31663;tester 独立复核 MISSING=0 vs git 31239、5/5 GET md5 ⇒ **前提此刻已不成立** | `docs/ops/126-git-resume-precheck-verification.md` |
| 10-01 01:17:48 | 迁移执行:commit `ee4a582c4`(31235 D)push origin;安全前提 = 旧桶 31663 + 云上磁盘 | `docs/ops/126-migrate-cutover-result-20260930.md` |
| 10-01 03:02 | 区块重生成入 git(`537317b4a`,31673 条),此后恒不变 | 本报告 §1.3 |
| 10-02 | 闭环验证:备份提交恢复、status=0、9 目录 tracked=0 | `docs/pending-features-index.md` L221(#126 行) |
| 10-05 | 换桶 signal-backup2(#178);16:52-18:12 自动全量回填 31673/31673;#185 复核 PASS(MISSING=0/EXTRA=0,7/7 逐位) | `docs/ops/185-backfill-verify-20261005.md` |
| 10-07(今日) | 全量复验:集合等价 + 31673/31673 内容一致 + state/manifest 新鲜 | 本报告 §1.4 |

## 2. 前提真伪判决

**判决:已证伪。**「9 目录 31239 文件全球只有 git 一份完整副本」在 09-30 当刻之后就错了两次:① 09-30 夜旧桶固定前缀已补齐完整(31663,MISSING=0);② 10-01 迁移把 git 的这份副本**主动移除**,副本承载转交 R2(新桶)+ 云上磁盘。今日完整副本至少两处(新桶 R2 全量 31673 逐位验证 + 云上磁盘实测 31666/31673 对齐),另有旧桶 legacy 冻结存量第三份。

## 3. #126 下一步范围建议

**建议:不保留原「备份链设计」任务,按已完成闭环处理;无剩余设计/实施工作。**

理由:
1. 收口设计三件套(固定前缀 flat key + `--print` 单一源 + `_prune_large_json` 不动固定前缀)已全部落地(实现 commit 链含 `dc0c62263`),迁移 10-01 已执行,10-02 已闭环验证,索引 L221 已明确「#126 闭环成立,可正式画句号」。
2. 所谓「坍缩为给 upload-large-json 加一个固定前缀参数」也已过时——该参数早已实现并生效、且迁移已在其上执行完毕;无「待坍缩」的剩余体量。
3. 今日复验证明该闭环**稳健**:双向差集 0、内容 31673/31673、state/manifest 每日新鲜、增量链自转(10-07 05:13 + 16:45)。

优缺点:
- 优点:零剩余风险敞口;不重复投入;持续保障已由既有机制承接(#149e 状态增量、#178 桶路由 + bucket-mismatch 自动全量回填、每日备份契约、#136 fail-loud)。
- 缺点/残余(如实标注,均有归属、不属 #126):① 结论依赖「区块↔R2 同源」构造,须靠内容级对账补独立佐证 —— 本次已做全量(31673/31673),后续巡检点 = #185④(10-08 后只读复核);② 老桶 legacy 存量(31663 + 切桶前增量,冻结)未清理 = #185③(随 #186 A+C,10-07 窗口后);③ 列表增量与新目录纳入的长期正确性依赖 DIR_EXCLUDES/阈值维护,已有 #136 fail-loud + #150(「侵蚀风险」核查不成立)背书。

## 4. 诚实标注与未核项(边界)

- 内容级 = HEAD etag + 磁盘重算 md5 + state md5 **三方内容哈希等价比对**,非全量 GET 字节流逐位(强度等价;与 #185 的 7/7 GET + sha256 抽样互补);md5 碰撞未另行排除。
- 旧桶仅抽样 HEAD(本次 1 键 + 前期 3 键),未全量列举(全量台账属 #185③ 范围)。
- 本地两份镜像(本地 staticdata 09-26 部分克隆 / 旧镜像 8.3G)未参与对账(均停在 09-26,过时);云上仓为权威。
- state `updated_at` 为云上本地时间(CST)。
- 云上 `/tmp` 留存本次只读对账 scratch:`recon126d2.py`、`126sweep.out`、`126sweep_ok.txt`(31673 行通过凭据,**建议保留**至 #185④ 复核后)、`126sweep_bad.txt`(0 行)、`block_126.txt`;本地 `/tmp/126recon/` 源码存根。清理属删除类动作,须走 §25(备份后删)。
- 复现踩坑备忘:云上 `import upload_r2` **必须显式 `REPO=/home/ubuntu/code/trade-data`**(`_find_env` 候选 = ROOT/.env(该路径不存在)+ `$GIT_REPO/.env` + `$REPO/.env` + mac 路径;**cwd 的 .env 不在候选**),否则 `sys.exit: 无 .env: 尝试过 ['/home/ubuntu/code/trade-data-signal/.env', '.env']`。

## 5. 复现段(关键命令)

全部只读;云上入口 `ssh -i ~/tdsignal.pem ubuntu@122.51.111.173`。

```bash
# A) 逐目录 git@5242b7459 vs 区块(.gitignore 受管区块) —— §1.2 来源
cd /home/ubuntu/code/trade-data-signal-staticdata
python3 - <<'PY'
import subprocess
out=subprocess.run(["git","ls-tree","-r","--name-only","-z","5242b7459","--","data/"],capture_output=True,text=True).stdout
hs=set(p[5:] for p in out.split("\0") if p)
block=set(l.strip()[6:] for l in open(".gitignore") if l.startswith("/data/"))
# 逐目录:len(hd)/len(bd)/len(bd-hd)(block_only)/len(hd-bd)(head_only);另打印 etf/accum_nav block_only 名单与 root 7
PY

# B) R2 集合级(signal-backup2) —— §1.4 来源
cd /home/ubuntu/code/trade-data && REPO=/home/ubuntu/code/trade-data /home/ubuntu/code/trade-data/.venv/bin/python - <<'PY'
import sys,re
sys.path.insert(0,"/home/ubuntu/code/trade-data-signal/scripts")
import upload_r2 as u
ks=u._list_keys("large-json/", bucket=u.BACKUP_BUCKET)           # 分页全量 list(只读)
flat=[k for k in ks if not re.match(r"large-json/\d{4}-\d{2}-\d{2}/",k)]
block=set(l.strip()[6:] for l in open("/home/ubuntu/code/trade-data-signal-staticdata/.gitignore") if l.startswith("/data/"))
exp={"large-json/"+p+".gz" for p in block}
print(len(ks), len(flat), len(exp-set(flat)), len(set(flat)-exp))  # 31673 31673 0 0
# 旧桶抽样:u.s3_head("large-json/fund_nav/001305.json.gz", bucket="signal-backup") → 200
PY

# C) 磁盘集合(vs 区块,双向) —— §1.4
#    os.walk 9 目录 → disk_9dir=31666;block_minus_disk=0;disk_minus_block=0;block_non9dir=7

# D) 全量内容扫(31673):见 /tmp/recon126d2.py —— 每个 rel 三断言:
#    HEAD 200 / etag == md5(gzip.compress(open(src).read(),6,mtime=0)) / etag == state md5;12 线程;ok/bad 落文件

# E) 状态/清单:json 读 count/bucket/updated_at;manifest `ls -l`(10-07 05:14)

# F) 区块历史:git log --format="%h %ci %s" -- .gitignore;git show 537317b4a:.gitignore | grep -c '^/data/'  # 31673
#    git diff --quiet -- .gitignore;echo $?   # 0(工作树=HEAD)
```

## 6. 维度完备性自检(§5.1⑤ 全局核心问题报告维度)

①基线复现(git@5242b7459 逐目录)✓ ②逐目录分解(含 trade_sim/root/etf/accum_nav 全归因)✓ ③集合双向差集(0/0)✓ ④内容级全量(31673/31673)✓ ⑤状态级(state/manifest 新鲜)✓ ⑥双桶口径(新桶 flat/legacy=0;旧桶抽样 200)✓ ⑦历史时间线(前提诞生→证伪→超越;含 31663→31673 差 +10 的逐项解释)✓ ⑧登记状态(#126 闭环;残余映射 #185③④)✓ ⑨前端展示位 = N/A(无用户可见展示位,§22 不适用,已标注)✓ ⑩诚实标注(方法边界/未核项/残留后台任务)✓
