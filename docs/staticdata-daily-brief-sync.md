# staticdata 数据仓库同步机制 + daily_brief 缺口调研与加方案

> 2026-08-11 调研落档。背景:用户反馈 AI 预测数据(daily_brief.json/daily_brief_history.json)只传了 R2,没进 staticdata 数据仓库,用户/同事看数据仓库提交记录查不到。
> 用户原则(2026-08-11 定):"我理解的数据仓库。除了大小首先无法进入。只要是数据产物。在 static-site/data 目录下。理论上都要进入 staticdata 数据仓库"。

## 一、staticdata 同步机制全景(现状)

### 同步脚本与触发
- **同步逻辑**: `scripts/deploy.sh` L507-558 的「staticdata 备份(best-effort)」段。每次 deploy.sh 运行后执行。
- **触发源**(deploy.sh 的调用方):
  - `scripts/update_all.sh` L58(17:50 盘后 pipeline,launchd `com.trade.update-all.plist`)
  - `scripts/public_fund_daily.sh` L80 / `public_fund_full.sh` L85 / `public_fund_quarterly.sh` L88(持 `/tmp/trade_deploy.lock` 调 deploy.sh)
  - backfill 等(经 index_backfill 内部触发)
- **同步内容**(deploy.sh L507-558 四步):
  1. rsync `$REPO/data/*.db` → staticdata/db/(本地备份,不进 git,`db/*.db` gitignore)
  2. cp wrangler.jsonc + launchd plist(脱敏)→ staticdata/config/
  3. **rsync 全量 `$REPO/static-site/data/` → staticdata/data/**(全量镜像,无白名单)
  4. `git -C staticdata add -A` + commit + push origin main(best-effort,失败不阻塞 deploy)
- **REPO 取值**: deploy.sh L24 `REPO=${REPO:-/Users/linhuichen/code/trade-data}`(与 gen_daily_brief 写盘目录同源,无 export-output-path-sync 陷阱)。

### 同步清单/排除规则(staticdata/.gitignore)
**无白名单,是全量 rsync**。gitignore 排除的都是「大小无法进入 git」的类别(§8.1 R2 架构):
- `index-*` / `industry-*` / `lab-*` / `trade_sim_*[0-9]*`(全量品种/大 range 历史,走 R2 公开桶)
- `*.gz`(git 无法 diff 二进制 gz)
- `feed.xml`、`db/*.db`
- 注:这些大文件**仍 rsync 到 staticdata 磁盘**(同事本地可见),只是不进 git 提交历史,由 R2 公开桶分发。

### manifest.json
- 由 staticdata 仓库根目录 `gen_data_manifest.py` 扫描 `data/` 全量 `*.json` 生成(含 daily_brief,已确认 manifest.json 里有 daily_brief.json / daily_brief_history.json)。
- **手动运行,无自动化 hook**(deploy.sh / update_all.sh 都不调它)。git log 里 manifest 最后一次更新是「开源门面」commit(80ca2d9/7f594a0)。

### 定时
无独立 staticdata 定时任务,跟随 deploy.sh(update_all 17:50 / public_fund ~02:34 / backfill ~02:15 等,以 staticdata git log 提交时间印证)。

## 二、daily_brief 为什么"没进"staticdata(真因)

**结论:不是被排除,是同步时机缺口。**

1. **daily_brief 从未被排除**:manifest.json 有它、staticdata git 有它(git ls-files 确认被追踪,提交记录 7bd4a7e「data backup [futures]」、b1e1802「data backup [etf-national-team]」均含)。
2. **真因 A(同一 pipeline 内时序)**: update_all.sh 17:50 里 deploy.sh(L58)**先**跑,run_daily_brief.sh(L254)**后**跑 → 当天的 daily_brief 生成于该 pipeline 的 staticdata 同步**之后**,不会被那次同步收录。
3. **真因 B(手动跑在计划任务后)**: `config/daily_brief.yaml` `schedule_enabled` 默认 false,daily_brief 多为手动 CLI 跑(如 8/11 02:41 真实版),跑在所有计划 deploy 之后 → staticdata 里一直是旧版,直到**下次**任何 deploy.sh 运行才顺带更新。
4. **真因 C(生成器只接 R2)**: `gen_daily_brief.py` 只做两件事——写 static-site/data/ + R2 上传(`upload_to_r2` L778-799 → `upload_r2.py upload-data-files` L786,仅 R2 + purge CF 缓存),**不触发 staticdata 同步**。R2 与 staticdata 是两套独立机制。
5. **实证**: staticdata/data/daily_brief.json 是 8/10 20:48 MOCK 精简版(927B,direction=up 只 1 个 watch),当前 static-site/data/daily_brief.json 是 8/11 02:41 真实完整版(2318B,direction=flat,5 个 watch)。

## 三、全量盘点:static-site/data 下还有哪些产物没进 staticdata

按用户新原则全量核对(2026-08-11):

- **磁盘层:0 缺口**。static-site/data 251 个文件全部已 rsync 到 staticdata/data 磁盘(名称逐一对比,0 个缺名)。全量 rsync 机制本身完整。
- **git 追踪层:0 真缺口**。staticdata 磁盘 490 个未 git 追踪文件全部有合法 gitignore 规则(`*.gz` / `index-*` / `industry-*` / `lab-*` / `trade_sim_*[0-9]*`),即「除大小无法进入」的类别,无一个被误排除。
- **唯一真实缺口 = 时间戳**:
  - daily_brief(见 §二):deploy 外生成,staticdata 留旧版。
  - 其他同类「只写 static-site/data + R2、不跑 deploy.sh」的生成器,理论上都有同样风险(schedule_stats.json 由 push_schedule_stats.sh 独立推 main,alert 类随 deploy;需在实施时统一排查,见 §四-4)。
  - manifest.json 不自动刷新(手动跑 gen_data_manifest.py)。

## 四、加方案

### 原则
凡 static-site/data 下数据产物,除超大文件外都应进 staticdata。daily_brief 是每日 2KB 级小文件,进 staticdata 完全合理,且与 R2 双份不冲突(§8.1:小文件走 CF/staticdata 差异日志,R2 是公开分发,两不冲突)。

### 1. 核心改动:gen_daily_brief.py 生成后追加 staticdata 同步(推荐)
在 `scripts/gen_daily_brief.py`:
- **改动点**: 在 `upload_to_r2(repo, args.no_upload)`(L927)之后,追加 `staticdata_sync(repo, args.no_upload)` 调用。
- **新函数**(仿 upload_to_r2 L778-799 模式,放其后):
  1. cp `static_dir/daily_brief.json` + `daily_brief_history.json` → `STATICDATA_REPO/data/`(STATICDATA_REPO 路径复用 deploy.sh L512 默认 `/Users/linhuichen/code/trade-data-signal-staticdata`)
  2. 持锁 git 提交:`with_lock.py /tmp/trade_deploy.lock`(避免与 deploy.sh staticdata 段并发写同一仓库),`git -C STATICDATA_REPO add` + commit("data backup [daily-brief] ...")+ push origin main(best-effort,失败只告警不阻塞)
  3. 可选:调 `gen_data_manifest.py` 刷新 manifest.json 一并 commit(保证 fetch_data.sh 一键复原索引新鲜)
- **同时覆盖手动 CLI 与定时调度两条路径**(schedule_enabled=true 的 17:50 定时跑也会触发)。

### 2. 通用化:抽 scripts/staticdata_sync.sh(建议,防同类再漏)
把 §四-1 的 cp+commit+push 抽成 `scripts/staticdata_sync.sh`(入参:文件列表 或 无参=全量 rsync 同 deploy.sh L529;持 `/tmp/trade_deploy.lock`;best-effort;commit message 带触发名)。daily_brief 及未来所有「写 static-site/data + R2 但未跑 deploy.sh」的生成器都调用它。deploy.sh L507-558 可后续重构复用它(可选,不阻塞)。

### 3. 历史数据补同步(一次性)
把当前 `static-site/data/daily_brief.json` + `daily_brief_history.json` cp 到 staticdata/data/ + git commit + push(即直接跑一次 §四-1/2 的同步),把 8/11 02:41 真实版补进 staticdata 提交历史。

### 4. 同类新数据类别排查(实施时同步做)
- **排查口径**: 枚举 `scripts/` 下所有「写 static-site/data/ + 调 upload_r2 但不调 deploy.sh」的生成器(gen_daily_brief.py / gen_schedule_stats.py 等),逐个确认是否缺 staticdata 同步,缺则套用 §四-2 的 staticdata_sync.sh。
- **防再漏落档**: 新数据类别上线 checklist 增加一条——「写 static-site/data 的生成器必须同时接 ①R2 上传 ②staticdata 同步(或跑 deploy.sh)」。

### 5. 不做的事(边界)
- 不把 staticdata 同步并入 R2 上传(两者语义不同:R2=线上分发,staticdata=留档/复原)。
- 不改 §8.1 大文件 gitignore 规则(index/industry/lab/trade_sim 仍只走 R2 公开桶,符合「除大小无法进入」)。

## 五、验证步骤

1. **补同步后**: `git -C ~/code/trade-data-signal-staticdata log --oneline -3` 看到新 commit「data backup [daily-brief]」;`git -C ~/code/trade-data-signal-staticdata show HEAD --stat` 含 data/daily_brief.json + data/daily_brief_history.json。
2. **内容一致性**: `diff <(cat ~/code/trade/static-site/data/daily_brief.json) <(cat ~/code/trade-data-signal-staticdata/data/daily_brief.json)` 无差异;history 同。
3. **R2 不受影响**: curl `https://ssd.fx8.store/data/daily_brief.json` 仍是线上最新版(同步只是追加,不动 R2)。
4. **幂等**: 重跑一次 gen_daily_brief.py 或 staticdata_sync.sh,`git -C staticdata status --short` 无新变更(无变更跳过 commit,同 deploy.sh L538 逻辑)。
5. **manifest**: 若启用自动刷新,`grep -c daily_brief ~/code/trade-data-signal-staticdata/manifest.json` ≥2 且 generated_at 是本次时间。
