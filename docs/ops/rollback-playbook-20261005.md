# 发布回滚预案(rollback-playbook-20261005)

> 任务 #165,承接 `docs/ops/cloud-healthcheck-20261003/D5-deploy-chain-audit.md` P1-2:
> 此前代码回滚约 30-40min 且流程只散落在 agent 规范里,全 docs 无集中回滚文档,真出 P0 靠现场拼。
> 本预案 = 三步回滚(代码 / 数据 / 版本串·缓存),每步给「具体命令 + 预计耗时 + 风险点 + 验证方法」。
> 适用对象:主控 / 值班操作者。日期:2026-10-05。

**先记住这个分层事实(再动手):**

| 层 | 载体 | 上线路径 | 回滚手段 |
|---|---|---|---|
| 代码 | git(main) | `main-merge.sh` → push main → GH Actions(wrangler deploy CF Worker 主站 + GH Pages 备站)+ 毛子云自动 pull | `git revert` 前进式 + 重走 main-merge.sh |
| 数据 | R2 `signal-data` 公开桶(**唯一线上数据源**,三站同源) | 云上 `deploy.sh` 定时链(export → R2 上传 → purge → 推 min) | 从恢复源 PUT 回 R2 + purge CF |
| 版本串/缓存 | `index.html` 引用 `?v=` + `sw.js CACHE_VERSION` | 随代码链自动 bump(机制 C) | **只能前进式 bump 新串,禁止倒退** |

## 0. 结论速览

| 层 | 端到端耗时 | 能否"秒切上一版" | 主要瓶颈 |
|---|---|---|---|
| 代码 | ≈25~40 min | **不能**(前进式) | 完整校验链+console 哨兵 ~5-10min;CDN/SW 用户侧传播上界 ≤20min |
| 数据 | 单文件 2~5 min;批量 30~60 min(10-02 实测 562 key ≈34min) | 能(恢复源=上一版快照) | 对账+PUT 批量;跨境带宽(建议云上跑) |
| 版本串/缓存 | 链内 0~1 min;purge ≤1 min;用户侧 ≤20 min | **不能,且不允许倒退** | max-age=1200(20min) |

### 三条铁律(先于一切操作)
1. **前进式回滚**:版本串只前进不后退(`check_version_progress.py` A 闸拦倒退);**禁止 force push main、禁止 reset main 后强推**(CLAUDE.md §8;零 force 手法见 memory `force-push-avoid-new-ref`)。
2. **唯一入口**:agent 只推 feat 分支;merge+push main 一律走 `scripts/main-merge.sh`(§8 机制 D),**P0 也不破例**。数据回滚不走 git,直接从 R2 层做。
3. **先定层再动手**:同事故可能横跨多层(如算法+坏数据),按「止血优先 → 拆层回滚 → 对账验证」顺序;动手前做 §25 可逆性检查(恢复源存在 + 可复核 + 写明恢复路径)。

### 现象 → 层 决策表
| 现象 | 层 | 走向 | 预计 |
|---|---|---|---|
| 页面 JS 报错/白屏/功能坏(数据正常) | 代码 | 第一步 | 25~40 min |
| 点「更新新版」白屏 / 三站版本混乱 / 缓存滞留 | §24 撕裂 | 第一步(前进式修)+ 第三步核验 | 25~40 min |
| 数据数值错误 / 停更 / 被旧版覆盖 | 数据 | 第二步 | 2~60 min |
| 三站(ss/sss/s)数据不一致 | 数据(R2 单源) | 第二步核验/补传 | 视批量 |
| 版本串倒退 / 孤儿快照 | §24 | 阻断上线 + 前进式修复 | 同代码层 |

---

## 1. 第一步:代码回滚(git 层)

### 1.0 前置检查(2 min,全只读)
```bash
cd /Users/linhuichen/code/trade
git fetch origin main
git log origin/main --oneline -5             # 现场基线:坏版本是哪个 commit
git status --porcelain                        # 必须干净(revert 前置;禁 reset --soft,memory bump-sw-version-with-appjs)
git worktree list | grep -F '<feat>' || true  # 目标分支是否被残留 worktree 占死(memory resume-same-task-reuse-branch)
```
**时点检查**:对照 §14 盘后时点(15:35/16:00/17:50/20:35/22:00 ±5min)——`main-merge.sh` L57-123 会 exit 3 硬拒且**无逃生门**;等到窗口外(最多等约 5~10 min,或直接等 23:00 后安全窗口)再跑。

### 1.1 场景 A(最常见):坏改动已 merge 进 main → revert 前进式

```bash
# ① 建 revert 分支(基于最新 origin/main,不基于旧 base)
git checkout -b revert-<名> origin/main

# ② 生成回退 commit
git revert --no-edit <bad_sha>                 # 单 commit
#   · 回退 merge commit:  git revert -m 1 --no-edit <merge_sha>
#   · 回退连续一串:      git revert --no-edit <最老_sha>^..<最新_sha>
#   · 3 方冲突 → 停下人工解决(§23.11 绝不静默),解决后 git revert --continue

# ③ 核对回退面(只应含目标改动,防夹带)
git diff origin/main..HEAD --stat

# ④ 走统一入口(自动:merge → build_min+bump 新版本串 → 全校验链 → console 哨兵 → push main → 云上 pull)
bash scripts/main-merge.sh revert-<名>
```

**与 main-merge.sh / deploy.sh 的关系(必读):**
- `main-merge.sh` 是代码上线唯一入口:自动完成 merge(L192-206)→ 9 源 build_min + `bump_asset_version.py` 版本串**新值**(L217-241,机制 C)→ `check_version_progress` A/B(L310-357)→ push main(L445-493,non-ff 走 fetch+rebase 重试,绝不 force)→ ssh 云上 `git pull` 同步(L496-538)。**revert 分支不需要手动 bump**(改了前端源码它自动统一 bump)。
- push main 触发 `.github/workflows/deploy-cf.yml`(wrangler deploy Worker 主站)+ `deploy-pages.yml`(GH Pages 备站);毛子云备站自动拉 git main(deploy.sh L911 注释)。**代码回滚不需要跑 `deploy.sh`**——deploy.sh 是数据上线链,与代码回滚无直接关系(仅场景 C 联动时才用)。
- 若 revert 分支触碰前端 9 源,main-merge 会自动 bump;若**没碰**,版本串不动——此时若要靠版本串破缓存,需确认改动是否真落到源上。

**耗时**:①+②+③ ≈2 min;④ ≈3~8 min(console 哨兵约 1 min);GH Actions 1~3 min;用户侧传播上界 ≤20 min。**合计 ≈25~40 min**(与 D5 审计 §5.2 口径一致)。先例:`774e97ece` revert(codex,2 文件,2026-09-16)、`18cfa90e3` revert(#97 移动端,2026-08-25 最大批次)。

**风险点:**
1. **本地 ref 过期丢 commit**(memory `main-merge-stale-local-ref-drop-commits`):复用既有 feat 分支时,merge 前必核 `git rev-parse refs/heads/<feat>` vs `git rev-parse origin/<feat>`;不一致 → `git fetch origin && git branch -f <feat> origin/<feat>`(worktree 占死先 `git worktree remove --force <路径>`,先确认该 worktree 的 agent 已完工)。
2. **半完成态**(memory `main-merge-fail-leaves-half-merged-main`):merge 后任一校验 FAIL → 本地 main 已前进、远端未动。核状态:`git log --oneline -3 main` + `git rev-list --left-right --count origin/main...main`;修问题后**重跑 main-merge.sh 即可**,不许手搓 `git merge`/`git push` 绕过入口。
3. **绝不 force**(§8):non-ff 走 fetch+rebase 重试;确需改写已推 commit 用"推新 ref 名"零 force 手法(memory `force-push-avoid-new-ref`;判内容在不在用 `git rev-parse <ref>^{tree}` 逐位比)。
4. **deploy 段2 fail-open 认知**(D5 P1-3):`with_lock.py` 排队超时 exit 0,"rc=0 ≠ git 已推"。验证以 `git log origin/main`/`git ls-remote origin main` 实况为准,**不以退出码为准**。
5. revert 是**内容回滚不是版本回滚**:版本串会 bump 到更**新**号,用户会收到"更新新版"提示,属预期行为。

**验证方法(逐条给证据):**
```bash
# a. main 链含 revert + bump commit
git log origin/main --oneline -3
# b. 版本串前进且 ≥ 祖先天花板(A 闸门本地复跑)
.venv/bin/python scripts/check_version_progress.py --site-dir static-site --repo . --deploy-mode
# c. 版本一致性(index 引用 == sw 批次 == min 内容,§24⑤)
GIT_REPO=$PWD .venv/bin/python scripts/check_version_consistency.py --site-dir $PWD/static-site --deploy-mode
# d. 线上实况(版本串 + SW 批次)
curl -s https://ss.fx8.store/ | grep -oE "(app|common)\.min\.js\?v=[0-9]{8}-a[0-9]+" | head -2
curl -s https://ss.fx8.store/sw.js | grep -oE "CACHE_VERSION = '[^']+'"      # 批次应与 c 一致
```

### 1.2 场景 B:坏 feat 未 merge → 直接弃用(不产生 main 改动)
```bash
git worktree list | grep -F '<feat>'      # 有残留 worktree 先 remove --force(确认 agent 已完工)
git branch -D <feat>                       # 本地删
git push origin --delete <feat>            # 远端删(删 ref 非改历史,不涉 force)
```
**风险**:删远端分支前确认无其他 agent 在跑该分支(memory `user-takeover-stop-inflight-agent` 先 TaskStop);若该任务还要续跑,按 memory `resume-same-task-reuse-branch` 保留分支。
**验证**:`git branch -a | grep <feat>` 与 `git ls-remote origin | grep <feat>` 均无输出。

### 1.3 场景 C:坏改动 = 算法+数据联动(代码回滚后数据要重算)
代码按 1.1 回滚后,用旧算法重算数据 —— 云上跑一次数据上线链:
```bash
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  'cd /home/ubuntu/code/trade-data && REPO=/home/ubuntu/code/trade-data GIT_REPO=/home/ubuntu/code/trade-data-signal bash scripts/deploy.sh force'
```
`force` = 绕过盘中(09:30-15:30)全量闸(deploy.sh L142-156);deploy 内含全部数据闸门(校验 FAIL 即终止,线上不变);FAIL 先修再重跑。若坏数据已上线需**立即**回旧版:先走第二步(数据层快照恢复)止血,再等重算。

---

## 2. 第二步:数据回滚(R2 / CF / static-site 产物)

> **分层事实**:`static-site/data/` 已全量移出 git(除 feed.xml);线上数据唯一来源 = R2 `signal-data` 公开桶;三站(ss.fx8.store 主站 / sss.sugas.site / s.sugas.site 备站)最终读同一 R2——备站前端把 `./data/*` 重写为主站 `https://ss.fx8.store/data/`(app.js L9660 `_R2_FALLBACK_BASE` + L9664 fetchJSON 重写)。
> **所以数据回滚 = 把 R2 对象恢复成旧版 + purge CF 边缘缓存**,不需要改 git;§22 三站一致性由"单源 R2"天然保证,回滚后对 R2 做一次对账即可。

### 2.1 恢复源优先级(动手前先选源并留证据)
| 优先级 | 源 | 位置 | 覆盖面 | 时效 |
|---|---|---|---|---|
| ① | **pre-upload 备份**(export-guard L5) | R2 `signal-backup` 桶 `pre-upload/<YYYYMMDD>/<key>` | 每次上传将被覆盖的旧 key 自动 COPY(upload_r2.py L1007-1138,key 格式 L1090) | 保留 **7 天**(L1008) |
| ② | **云上树当前文件** | 云上 `/home/ubuntu/code/trade-data/static-site/data/` | 本机/异源误传类事故的正确版(10-02 先例) | 实时 |
| ③ | **large-json 版本化快照** | R2 `signal-backup` `large-json/<相对data路径>.gz`(固定前缀=唯一副本) | 7 个 >20MB 大 JSON | 永久(不滚动删) |
| ④ | **git 历史** | staticdata 仓库(`/Users/linhuichen/code/trade-data-signal-staticdata`)小 JSON 差异日志;trade git(仅 2026-08-10 前 static-site/data) | 历史任意版 | 全量历史 |
| ⑤ | **本机 mac-backups 归档** | `~/code/trade-data/data/mac-backups-20261001/`(86 文件/10.2GiB) | DB 层快照 | 按日归档 |

### 2.2 场景 A:少量文件被坏版本覆盖(最常见)→ pre-upload 精准恢复(2~5 min)
```bash
cd /Users/linhuichen/code/trade
.venv/bin/python - <<'PYEOF'
import sys; sys.path.insert(0, "scripts")
import upload_r2
DAY  = "20261004"                            # 覆盖发生日(备份目录),7 天内
KEYS = ["data/overfit_monitor.json"]         # 要回滚的 signal-data key(无前导斜杠)
for key in KEYS:
    st, data = upload_r2.s3_request("GET", f"pre-upload/{DAY}/{key}", bucket=upload_r2.BACKUP_BUCKET)
    assert st == 200, (key, st)              # 没备份=停,换②源,绝不硬编造
    st2, _ = upload_r2.s3_request("PUT", key, payload=data)   # 幂等写回 signal-data
    print("restore", key, st2)
upload_r2.purge_cache(KEYS)                  # 清 CF 边缘
# 注:purge 前缀按通道——data/ 前缀(default "/");lab/index/industry/etf_hist/accum_nav/
#    public_fund/offshore_fund/fund_score/etf_score/trade_sim_data 通道用 cache_prefix="/r2/"
#    (upload_r2.py 各 cmd 归属 L1480-1816);fund_nav 通道**不自动 purge**(F3),
#    恢复 fund_nav 后必须手动 purge("/")
PYEOF
```
**风险**:DAY 选错 → 取到更旧版本;先确认备份存在:`.venv/bin/python scripts/upload_r2.py list "pre-upload/20261004/" --bucket signal-backup`,再 PUT。
**验证**:PUT 后逐 key HEAD 对账(`s3_request("HEAD", key, with_headers=True)` 的 ETag == 源数据长度/md5)+ `curl -s https://ssd.fx8.store/data/<file>` 抽查 + `curl -s https://ss.fx8.store/data/<file>` 主站一致(purge 后)。

### 2.3 场景 B:批量被异源覆盖(10-02 类)→ 对账清单 + 批量 PUT(30~60 min)
1. **止血前置**:确认无 deploy/上传在跑(否则再次覆盖):
   `ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'systemctl list-timers --no-pager | grep trade; ps aux | grep -E "deploy|upload_r2" | grep -v grep'`
2. **生成对账清单**:逐 key `HEAD` 取 ETag vs 恢复源 md5,列「R2 ≠ 源」清单(命名空间统一:剥 R2 前缀对到源树相对路径;如 `data/x.json` → `static-site/data/x.json`)。
3. **逐 key PUT(PUT 前再 HEAD 对账,幂等)**——克隆 10-02 模板流程(含模板脚本形态/清单/验证):
   见 `docs/ops/local-export-overwrote-r2-incident-20261002.md` §6(恢复执行)+ §8(防再犯:export-guard L0-L5)。
4. **purge + 结果计数**(fixed/skipped/missing/failed 四项都看;missing≠0 要核源,不静默当成功)。

**先例**:10-02 事故 562 key 从云上树恢复,实测 **34 min**(04:21 清单 → 04:55 结果;fixed=541 / skipped=21 / missing=0 / failed=0)。
**风险**:①恢复期间云上 deploy 又跑 → 覆盖恢复结果(故第 1 步);②恢复源自身要先验正确性(别拿另一份坏版);③跨境带宽——批量**建议在云上跑**(源=云上树,免下载)。

### 2.4 场景 C:坏数据 = 坏生成器产出 → 修生成器 + 重跑
- 止血:先用 2.2/2.3 恢复到"坏版上线前"快照(pre-upload 正是该时点旧版),保线上可用;
- 根治:修生成器 → 云上 `deploy.sh force` 重跑(命令同 1.3;全闸门保护,校验 FAIL 不上线);
- 产物是独立脚本生成(gen_daily_brief/accum_nav 类)时:按 implementer skill §3.1 新类别上线 R2 上传 + purge,再跑一次 deploy 兜 staticdata。
**验证**:curl 线上 JSON 关键字段(`generated_at`/`date` 等)== 新生成版本;源树 md5 == R2 etag 对账。

### 2.5 场景 D:DB(数据源)本身坏 → 按 `docs/backup-restore.md` §五 六步
停 4 条 timer(trade-update-all / trade-intraday-snapshot / trade-etf-national-team / trade-lab-auto)→ mv 坏库留证 → 备份覆盖(`download-db` 拉最新或本地 `data/backups/` 热备)→ 删 `-wal/-shm` → `PRAGMA integrity_check` + 关键表行数 → 起 timer。**云上生产路径 = `/home/ubuntu/code/trade-data/data/*.db`**(本机开发库是另一份,别搞混)。
**耗时** ≈10~20 min(视库大小)。**风险**:恢复期必须停写库任务;恢复后必须删旧 WAL/SHM;恢复的 DB 绝不 `git add`(untracked 保护,防切分支污染重现)。

### 2.6 数据回滚通用验证(§22 三站一致)
```bash
# R2 直链 vs CF 主站(两路同源对账,恢复后必查;purge 后应一致)
curl -s https://ssd.fx8.store/data/overview.json | md5
curl -s https://ss.fx8.store/data/overview.json  | md5
# 三版本审计器(参考工具;注:未接线且本地树可能滞后会误报,以两路 curl 对账为准)
.venv/bin/python scripts/check_r2_consistency.py --quiet
# 备站:访问首页确认加载(备站引用主站数据源;"备站 /data/ 直链 404 是常态",裸 curl 307 须带浏览器 UA → memory live-index-curl-307-use-browser-ua)
```
**风险(诚实标注)**:`check_r2_consistency.py` 全仓无自动调度(D5 P0-1),主站 /data/ 与两备站 HTTP 层一致性**无自动校验**——本预案的对账命令是**手动**的,执行者必须自己跑到。

---

## 3. 第三步:版本串/缓存回滚(§24 防撕裂)

### 3.0 机制事实(决定"怎么回")
- 版本串 = `index.html` 资源引用 `?v=<YYYYMMDD>-a<N>` 与 `sw.js CACHE_VERSION` 同源;`bump_asset_version.py` 每次强制 +1(内容相同也换新),杜绝指纹断链(§24①)。
- `check_version_progress.py A` 拦"版本串 < 最近祖先天花板"(L190-224)→ **回滚只能前进式**:revert 后 bump **新**串,内容与引用匹配,不产生孤儿快照(D5 审计:无"秒切上一发布";08-14 白屏事故根因=指纹断链+孤儿快照,memory `deploy-cdn-stale-snapshot-blue-screen`)。
- SW 壳芯配套+失败回退(sw.js install L51-97 / activate L99-139):install 必须 `CORE_SHELL_URLS`(app.min.js/common.min.js/index.html)全部预缓存成功才 `skipWaiting`,任一失败 → SW 不激活(旧 SW 继续服务);activate 复核 `isCoreShellReady()` 后才清旧缓存 + claim。→ 回滚发版里用户"点更新"不会白屏;新壳拉不全直接保留旧版。

### 3.1 正确操作(0 额外步骤,随第一步链自动完成)
代码回滚走 `main-merge.sh` 时已自动:build_min + bump **新串** + `check_version_progress` + `check_version_consistency`(§24⑤ 内容哈希==引用)+ SW `CACHE_VERSION` 同步。**不需要也不允许**手动把版本串改回旧值。

### 3.2 用户侧仍滞留旧版/白屏 → 处置序
1. 先核线上引用自洽(防"孤儿快照"类):
```bash
curl -s https://ss.fx8.store/ | grep -oE "(app|lab|common)\.min\.js\?v=[^\"']+" | head -5
curl -s https://ss.fx8.store/sw.js | grep -oE "CACHE_VERSION = '[^']+'"
GIT_REPO=$PWD .venv/bin/python scripts/check_version_consistency.py --site-dir $PWD/static-site --deploy-mode
```
2. 引用/内容不一致(断链)→ 走第一步前进式修复(补一次完整 bump 链),**不手动动 sw**。
3. 一致但个别用户滞留 → 手动 purge CF 边缘(purge 接口只覆盖 `/data/` 与 `/r2/` 路由缓存;代码资源靠版本串换 URL 破缓存):
```bash
curl -s -X POST https://ss.fx8.store/api/purge-cache -H "Content-Type: application/json" \
  -d '{"secret":"<PURGE_SECRET>","keys":["/data/overview.json"]}'
```
4. 浏览器侧兜底:提示用户硬刷新;**不把"注销 SW"当常态手段**。

### 3.3 明确禁止(§24 反面清单)
- ❌ 把 `CACHE_VERSION` / `?v=` 改回旧值(撞 A 闸门;且旧串缓存可能已被清 → 真孤儿);
- ❌ `reset --soft` 对齐分支(留 M 脏文件被 build_min 读旧源,16:30 事故根因);
- ❌ 删 sw.js / 全局清 CF 缓存求"干净"(带宽风暴 + 无差别 purge);
- ❌ 为"快点"手动 push 源码到 main(绕过 bump/校验 = 制造断链事故)。

**验证**:§3.2 第 1 步三命令 PASS;抽查三站首页版本串批次一致。
**耗时**:链内 0~1 min;purge ≤1 min;用户侧传播上界 ≤20 min(max-age=1200,deploy.sh L911 注释)。

---

## 4. 时点纪律与执行注意
- §14 时点:15:35/16:00/17:50/20:35/22:00 ±5min **不 merge/push main**(main-merge.sh exit 3,无逃生门);23:00 后为安全窗口。
- 盘中(09:30-15:30):全量 deploy 默认拒(`force` 可绕);数据 R2 恢复不受 deploy 盘中闸限制,但注意 intraday 定时任务盘中每 30min 上传(index/intraday/overview)——恢复批量数据时先等其窗口或接受它下一轮覆盖(它只覆盖自己负责的 keys)。
- 并发纪律:恢复/回滚全程避开 `/tmp/trade_deploy.lock`(deploy 段2 + staticdata async)持锁进程;git 写由 main-merge 统一入口串行。
- **演练缺口(诚实标注)**:D5 审计点名「SW 缓存+版本串回滚组合从未演练」——本预案为首份集中文档化;建议择一次非交易日 dry-run(代码链:main-merge.sh 支持 `--dry-run`(L28-29,跳过实际 merge/push 其余校验照跑);数据链:`restore-large-json.sh --target /tmp` 类演练)。

## 复现
> 本节写明每条关键命令的取证/验证方式(执行者可逐条反查;行号=2026-10-05 版代码)。
1. **代码回滚链**:`scripts/main-merge.sh`(§14 闸 L57-123;统一 bump L217-241;校验 L310-357;push L445-493;云上 pull L496-538;--dry-run L28-29)。验证方式:跑 1.1 的 a~d 四条命令,全部输出与预期比对(a:含 revert/bump commit;b:exit 0;c:exit 0;d:线上版本串==本地批次)。
2. **数据链**:`scripts/deploy.sh`(盘中闸 L142-156;check_version_progress 调用 L641-642;段2 锁 L650-657;分支校验+push main:main L694-707;毛子云备注 L911)。验证方式:`grep -n "盘中" scripts/deploy.sh` 逐处核对。
3. **恢复源**:`scripts/upload_r2.py`(pre-upload L5 L1007-1138、保留 7 天 L1008、key 格式 L1090;purge_cache 定义 L1819、分批 30 keys/0.5s;各通道 purge 前缀 L1480-1816);`scripts/restore-large-json.sh`(--list/文件名/--date/--all/--target,原子写+bak+sha256 校验);`docs/backup-restore.md` §五(DB 六步,含云上路径 L101-133 与 4 条 timer 名单 L112-113)、§八(large-json 恢复)。
4. **版本串/缓存**:`static-site/sw.js`(install L51-97 / activate L99-139);`scripts/bump_asset_version.py`(读 sw.js CACHE_VERSION 批次+1);`scripts/check_version_progress.py`(A 天花板 L190-224 / B 净回退 L277-303;参数 --site-dir/--repo/--deploy-mode L326-328);`scripts/check_version_consistency.py`(--site-dir/--deploy-mode L232-233)。
5. **先例证据**:10-02 R2 恢复 34min/562key → `docs/ops/local-export-overwrote-r2-incident-20261002.md`(§6 执行/§8 防再犯);代码回滚先例 `774e97ece`(09-16)、`18cfa90e3`(08-25);D5 能力评估 → `docs/ops/cloud-healthcheck-20261003/D5-deploy-chain-audit.md` §5。
6. **验证命令取证方式**:所有 curl 命令均可现场重放对比;所有 `.venv/bin/python scripts/...` 校验器即主控/评审复跑入口;线上实况判定以 `git log origin/main` + `curl` 两路为准,不以退出码为准(段2 fail-open,见 1.1 风险 4)。
