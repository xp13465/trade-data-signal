# 独立审报告:restore-r2-backup.sh 默认桶失效修复(feat/restore-bucket-route-20261008)

> 审查者:reviewer agent(独立上下文,只读不改)。日期 2026-10-08。
> 审查对象:分支 `feat/restore-bucket-route-20261008` tip **`e4fecce2c`**(远端 ref 已核 == e4fecce2cb95ee57e2521290cf9c143775f9a8c8);
> base = origin/main `d86527912`。改动面:`scripts/restore-r2-backup.sh`(M,+117/-22)、`docs/decommissioned-backups.md`(M)、
> `docs/ops/restore-bucket-route-20261008.md`(A,实施报告)。
> **结论:代码内容 merge 资格成立(必查 9/9 PASS);但有 1 项 merge 前必须先做的行动项(P1:squash 见下),否则 main-merge 会在第 5 步直接 abort。**
> 分级:B 级(DR 恢复脚本=可逆性保障链)→ 完整影响面审 + 只读实跑验证。
> **零副作用声明**:本次审查只发 R2 **GET/list**(无 PUT/DELETE、无邮件/飞书/告警);所有脚本实跑均落在 `/tmp/restore-review-20261008*` 临时目录;
> 真实 `data/` 实测零改动(`find data -maxdepth 1 -type f` 全量 71 文件 `名称|大小|mtime` 前后 `diff` 零差异,`git status --porcelain` 无新增)。

---

## 一、审查方法(为什么可采信)

独立构造临时镜像 `/tmp/restore-review-20261008/{scripts/restore-r2-backup.sh,scripts/upload_r2.py}`(脚本取 `git show feat/...:`,sha256 `de79deab…` == 分支 blob;upload_r2.py 取工作树,sha256 `ba428fda…` == 分支 blob 逐位一致 ⇒ 未改)。**不在主工作树 checkout 分支**(§memory `non-isolated-agent-switches-main-branch`),主工作树始终停在 main。

---

## 二、必查 9 项逐项判定

### 1. 缺陷真被修 + 新桶默认首选未被破坏 —— PASS
- **缺陷复现(旧版 origin/main 脚本)**:`restore-r2-backup.sh decommissioned-small-baks-20260903.tar.gz` → `✗ 下载失败 … status=404 NoSuchKey`,**exit=1**,未落文件。旧版只查 `BACKUP_BUCKET`(=#178 后默认新桶 `signal-backup2`),实体在老桶 → 恢复直接失败。
- **新版默认探测**:`--out-dir /tmp/…/out-a <同一 key>` → `✓ 命中桶 signal-backup | 还原 11259B(网络) → …tar (47104B)`,**exit=0**。
- **新桶首选路径未破坏**:新桶对象 `r2-cleanup-a-head-20261007.json` 默认探测 → `✓ 命中桶 signal-backup2`(首选即命中,未回落),产物 md5 `a9711b9c660b122ccba32363904fe851` == 该对象 R2 ETag(逐位)。

### 2. 是结构解不是补丁 —— PASS(带 1 条边界说明)
- 实现是「候选桶列表按序 GET,404 继续、命中即停」(`candidates()` 函数),**无「新/老」两分支写死**;默认顺序 = `BACKUP_BUCKET` → `R2_LEGACY_BACKUP_BUCKET`(默认 `signal-backup`)→ `R2_RESTORE_BUCKET_FALLBACKS`(逗号分隔,去重保序)。
- 实测 env 旋钮**真生效**:`R2_LEGACY_BACKUP_BUCKET=bogus-bucket` → `探测结果: signal-backup2=404, bogus-bucket=404` exit=1;追加 `R2_RESTORE_BUCKET_FALLBACKS=signal-backup,…` → **命中 signal-backup** exit=0 ⇒ 第三桶经 env 追加即被探测,脚本侧零代码。
- **边界(告知,非缺陷)**:第三桶若落在「第三个 CF 账号」,`upload_r2._route_bucket`(L402-411)只认两套凭据(桶名 == `BACKUP2_BUCKET` → 新账号;其余 → 老账号)⇒ 届时须改 `upload_r2.py`(非本脚本)。落在已配账号内的第三桶则真零代码。实施报告 §6.1/§6.2 已自述「靠 env / 老账号凭据依赖」,未覆盖此账号路由细分,建议后续补一句。

### 3. 失败语义(404 回落 / 非 404 响亮失败不静默) —— PASS
| 场景 | 实测 | 结果 |
|---|---|---|
| 全候选 404(不存在 key) | `✗ 目标对象在所有候选桶均不存在(全部 404)` + 逐桶探测结果 | exit=1,out-dir 目录都未创建(零半成品) |
| 首选桶非 404(新账号凭据置坏 → HTTP 400 InvalidArgument) | `✗ 下载失败 signal-backup2/… status=400 …` **未回落老桶** | exit=1,零落文件 |
| 回落位非 404(老账号凭据置坏) | `✗ 下载失败 signal-backup/… status=400 …`(未被当成「不存在」) | exit=1,零落文件 |
| `--bucket` 钉错桶 | 只探测该桶,404 即失败,不回落(设计如此) | exit=1 |
| CLI 误用(`--bogus` / `--bucket` 缺参) | 打 usage | exit=2 |
对齐 §23.11:未把权限/凭据问题伪装成「对象不存在」,也未吞任何异常(diff 无 `except`,唯二退出路径都带完整信息)。

### 4. 同类错误面清单(§23.2①/§23.3) —— PASS(独立抽验 4 条,全部成立)
| # | 对象 | 实施判定 | 审查者独立验证 |
|---|---|---|---|
| 1 | 本脚本 | 同病,修 | ✅ 见第 1 项(B 复现 404 / A 修复) |
| 2 | `docs/scripts/restore_pfdb_bak_r2.py` | 不同病(对象实际在新桶) | ✅ **独立实测**:`list decommissioned/ signal-backup2` 见 2 个 .zst(`public_fund.db.bak-20261003_104704.zst` + wal)在老桶 list 中**完全不存在** ⇒ `BKT=BACKUP_BUCKET`(新桶)命中正确 |
| 3 | `scripts/restore-large-json.sh` | 不同病(自愈全量回填) | ✅ **独立实测 key 集合**:`_list_keys("large-json/")` 老桶 **31,673** / 新桶 **31,673**,`only_old=0 / only_new=0`(集合差为空)⇒ 默认桶能覆盖全部 key,判定成立(比实施者的状态文件论证更直接) |
| 4 | `scripts/verify_backup.sh` | 不同病,老桶名仅文案 | ✅ grep 命中 4 处(L6 注释 / L69,L77 echo / L89 告警正文),无桶参数;真桶走 `cmd_download_latest_db`(BACKUP_BUCKET) |
| 5 | `scripts/staticdata_backup_async.sh` | 不同病,老桶名仅文案 | ✅ grep 命中 3 处(L30/L32/L169 均注释) |
- `docs/decommissioned-backups.md`(文档侧同病)已同步修;`#205` 在册核实**为真**:`docs/pending-features-index.md` L331 正是「切桶后老桶名文案漂移残留:4 个 shell」,且该条**明确要求「修前逐脚本归因,restore-* 可能有 legacy 恢复语义,盲改会把恢复指错桶」** ⇒ 本次用「候选探测不绑死单桶」既不盲改也不漏修,与 #205 指引一致。其余 3 shell + 3 文档未动=留给 #205,未越界(§23.4)。

### 5. 自测证据真实性 —— PASS(逐位复算 + 负控复跑)
- **md5 vs ETag 逐位**:独立 GET 复算 —— `signal-backup/decommissioned/decommissioned-small-baks-20260903.tar.gz` md5 `6f905c9b077884d1b17df39228865948`(= list ETag = `docs/ops/disk-cleanup-exec-batch1-20261007.md` §闸门① 记录,三源一致);新桶小对象 md5 `a9711b9c…` == 其 ETag。
- **产物链路闭合**:独立 `gzip.decompress` 的 md5 = `bc3cc04496012907583d59b5eb4d0963` = **脚本落盘文件本地 md5**,47104 B;`tar -tvf` 4 个成员 2222/13331/4432/22822 B 与 manifest 逐位一致。
- **负控真失败**:不存在 key → exit=1 且零文件;钉错桶 → exit=1 且零文件;CLI 误用 → exit=2。
- **`--out-dir` 确未覆盖本地源**:**真实 `data/` 全量 71 文件 `名称|大小|mtime` 前后 diff 零差异**;`git status --porcelain` 仅剩 untracked 报告文件(见 P1)。
- 报告数字全部复算一致(11259 / 47104 / 10968910↔38793216 未跑大件,小件全量复算;md5 三源一致已足以证「对象实体在老桶」)。

### 6. 回归面(调用方/文档引用) —— PASS
- 全仓 `grep -rn "restore-r2-backup"`(排除 .git)= **仅文档 11 份 + 脚本自身**,`scripts/**` 与根级 shell 无任何调用方,**无定时任务/无 CI 链引用** ⇒ 「默认行为变化」不对任何自动化链路生效;CLI 向后兼容(选项全可选,`bash scripts/restore-r2-backup.sh <key>` 老用法原样可用)。
- smoke 清单(`docs/smoke-checklist.md`)Part 1/2 全部是站点数据产物(static-site/data JSON + R2 静态资源)校验:本次改动**不产出/不修改任何数据产物、不碰前端** ⇒ 站点 P0 smoke **N/A**(已核改动文件清单无 `static-site/**`、无 `data/**`);最贴近的回归面=本脚本自身,已用 9 次只读实跑覆盖。

### 7. 文档同步 —— PASS
- `docs/decommissioned-backups.md`:桶分布说明(2 个历史归档在老桶 / #178 后新写入落新桶)与**实测两桶 key 清单逐条相符**(老桶 2 keys、新桶 6 keys,含文档点名的 `public_fund.db.bak-20261003_104704.zst`);恢复节新增 `--bucket`/`--out-dir` 示例;输入依赖段写明 env 变量名 `R2_LEGACY_BACKUP_BUCKET` / `R2_RESTORE_BUCKET_FALLBACKS`(L96)与脚本头注释一致;legacy 默认桶名 `signal-backup` 一致。

### 8. git 卫生 —— PASS
- base-fresh:`origin/main` 是 feat 祖先(`merge-base --is-ancestor` PASS);**1 个 commit、0 个 merge commit**;远端 ref == e4fecce2c;
- 改动清单 `M docs/decommissioned-backups.md / A docs/ops/… / M scripts/…`:无 `data/**`、无 `static-site/**`、无 app/lab/common/sw/index/版本串(故 main-merge 的 bump 逻辑自然跳过);无 force 迹象(线性单 commit,远端与本地一致)。

### 9. §23.7 冻结契约边界 —— PASS
diff 逐行核:除「多桶探测 + 命中桶打印 + 新增可选 flag + 文案」外**无顺手改动**;老用法/老输出文件路径/退出码语义全保持(默认 `--out-dir=data`);实施报告 §6 有 5 条诚实缺口(含「双桶同名 key 取新桶」——实测当前 `decommissioned/` 两桶 **key 集不相交**,零当前影响)。

---

## 三、Findings

### P1(merge 前必须处理的行动项,非代码缺陷):主工作树存在**同路径未跟踪文件**,会直接 abort main-merge
- `trace`:`diff_range`=非 diff 引入(工作树状态 `/Users/linhuichen/code/trade/docs/ops/restore-bucket-route-20261008.md`);`linkage`=不满足(阻挡本分支 merge);`user_request`:N/A(`origin: reviewer_own`)。
- 证据:该未跟踪副本 sha256 `09f9e08c1141bd1d7fccf431178064f6e039b39dc2185125873cda79cbdac016` **与分支内同名 blob 逐字节相同**;`scripts/main-merge.sh` 在第 5 步于主工作树执行裸 `git merge "$FEAT" --no-edit`(L215,无 `-f`/无 stash/无 clean;前置的工作区检查 L171 只覆盖 tracked 文件且仅在需 rebase 分支才跑)。
- `verifier`:`command`=隔离复现 `/tmp/gitmerge-sim-20261008`(init→main 提交→feat 加同路径文件→main 工作树放**内容相同**的未跟踪副本→`git merge feat`)⇒ `observed`=`error: The following untracked working tree files would be overwritten by merge: docs/ops/r.md … Aborting`,`exit=1`,main 未动;`expected`(若安全)=merge 通过。
- **修法(一行)**:merge 前 `rm /Users/linhuichen/code/trade/docs/ops/restore-bucket-route-20261008.md`(内容与分支 blob 逐字节一致,零信息丢失;需要保留草稿可 `mv` 到 /tmp)。**不做=`main-merge.sh` 第 5 步 exit 4,响亮停下(不静默)但白跑一轮**。

### P3(非阻断,建议 merge 时一并):`#205` 状态列未随本次部分落地更新
- `trace`:`docs/pending-features-index.md` L331 状态仍「待办(未实施)」,而本分支已把其 4 个 shell 之一的**实质读桶 bug**修掉(§23.12-1 任务状态单一事实源)。
- `verifier`:`command`=`grep -nE "^\| *205 *\|" docs/pending-features-index.md`;`expected`=状态列反映部分落地;`observed`=仍写「待办(未实施),禁止一把梭改」。
- 建议:merge 时在 #205 备注「`restore-r2-backup.sh` 已修(候选探测);其余 3 shell + 3 文档仍待办」,不改变其待办性质。

### 已滤低分项(<80,共 3 条,列出防黑箱)
1. 脚本文件末尾缺尾换行(diff 里 `\ No newline at end of file`);`lint_scripts.sh` 三项检查(bash -n / `$VAR`+非 ASCII / py_compile)均不查此项,零功能影响 —— nitpick。
2. 默认探测对老桶 key 多一次 GET(老桶对象总是两次请求)—— 成本可忽略。
3. 新账号凭据失效期间,老桶恢复也会被「非 404 响亮失败」挡住,需 `--bucket signal-backup` 逃生 —— 与 §23.11 mandate 的取舍一致,实施报告 §6.2 已自述。

---

## 四、审查者复现命令(只读,可直接重跑)

```bash
D=/tmp/restore-review-20261008   # 临时镜像(分支 blob 逐位复制)
# A 正向(老桶 key):bash $D/scripts/restore-r2-backup.sh --out-dir $D/out-a decommissioned-small-baks-20260903.tar.gz
# B 缺陷复现(旧版):见 /tmp/restore-review-20261008-old(origin/main blob)
# G 新桶首选:bash $D/scripts/restore-r2-backup.sh --out-dir $D/out-g r2-cleanup-a-head-20261007.json
# 两桶实体:python3 scripts/upload_r2.py list decommissioned/ signal-backup[2]
# large-json key 集对账:upload_r2._list_keys("large-json/", bucket=…)
# data/ 零污染:find data -maxdepth 1 -type f -exec stat -f "%N|%z|%m" {} \; | sort  (前后 diff)
```

## 五、审查者自证(§9 三层验收第二层)

- 本次仅只读:实跑 9 次(2 正控 + 4 负控 + 2 env 旋钮 + 1 等号形式),全部 `R2 GET`/`list`;**零 R2 写、零邮件/飞书/告警**(脚本 code 无 notify 通道;`upload_r2` 的 notify 仅在其他命令的错误回调内,未触及)。
- 真实 `data/` 零改动;主工作树分支未切换(始终 main);未 commit 任何文件(本报告按要求不 commit)。
