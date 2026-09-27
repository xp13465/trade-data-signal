# 云上生成物写 trade 仓库 tracked 文件审计 + #118 修复落档(2026-09-27)

> 触发:修 #115 云上同步时顺手发现 2 个「已被 git 跟踪、却被云上定时任务反复重写、且无任何环节提交」的生成物 → 云上长期留 ` M` 脏文件 → main 下次改动其一时云上 `git pull` 报 `local changes would be overwritten` 而中断。
> 2026-09-27 因 #115 那份 manifest 已实际发生过一次(靠 `cp` 备份 + `git checkout --` 单文件丢弃解掉)。
> 本审计 = 全量穷举「云上定时任务会写 + trade 仓库 tracked」交集,一次清干净(§23.3 举一反三),并落档修法 + 云上首拉清理步骤。

## 1. 穷举方法(全量,非抽查)

1. 云上 `systemctl list-timers` → 53 timers,其中 **38 个 trade-\*** timer
2. 38 个 `trade-*.service` 全部 ExecStart 提取(全部在 `/home/ubuntu/code/trade-data/scripts/`,该目录 symlink → `trade-data-signal/scripts`)
3. 云上结构: `trade-data`(数据仓)的 `scripts/docs/config/app/web/.venv` 全 symlink → `trade-data-signal`(代码仓);`data/` 与 `static-site/` 为数据仓真实目录
4. 代码仓 tracked 清单(`git ls-files`)=1466 文件,其中 `docs/`=929;tracked 非源码 JSON/gz 全量提取
5. 对 38 个 ExecStart 脚本链内全部 py/sh 写目标穷举 grep(`scripts/ app/ a-stock-data/ static-site/export.py + docs/ 下被调 py`)
6. 反向:对 tracked JSON 候选 grep 文件名找写入方

## 2. 当前已踩响且可安全脱跟踪 = 恰好 2 例(同机制但本次不动的另见 §7)

> 说明:全量同机制对象 = 本 2 例 + §7 的 4 个 `data/` 文件;§7 那 4 个因有真实消费方/bootstrap 契约依赖,本次不动。

| 文件 | 写入方 | 触发 | 频率 | tracked | 消费方 | mtime |
|---|---|---|---|---|---|---|
| `docs/kelly/position/scripts/accum_nav_map.json`(26MB) | `export_accum_nav_map.py` L41 `OUT_JSON`(脚本同目录)+ L44 `SPLIT_DIR` 同目录 `accum_nav/`,经 `deploy.sh` L284 `--all` 调 | `trade-us-stock-morning`(每天 05:00)+ `trade-update-all`(每天 17:50)→ 各跑一次 deploy.sh | 每天 2 次 | 是(`git ls-files`) | 无直接消费;**唯一=deploy.sh L290 cp 到 static-site/data/**(cp 源只需磁盘存在,不需要进 git);前端读 R2/`./data/`(common.js L1266 / lab.js L8147) | 09-27 05:08:38, 26MB |
| `docs/ai-predict/out/ab_direction_anchor_7d.json`(3KB) | `scripts/ab_direction_anchor.py` L85 `AB_OUT_FILE` + L312 `--reconcile` 分支写 | `trade-ab-direction-anchor`(每天 21:15;满 7 交易日后每次触发都走 `--reconcile --force`) | 满 7 交易日后每天 21:15 重写(无条件 atomic_write,内容可能不变) | 是(`git ls-files`) | **零消费方**(全仓 grep 仅自身 docstring) | 09-24 21:15:01, 3062 B |

**踩响频率判据(提交历史)**:`accum_nav_map.json` main 近 5 commit(b2e588e30/c7637cd0e/1e8474a05/c9a69190d/d1a26756f,08月底~09-06)→ main 改动约周级 → **踩响≈周级**;`ab_direction_anchor_7d.json` main 仅 2 commit → 几周~几月级。

## 3. 触发链证据(行号)

- `us_stock_morning.sh` L9 注释 + L70:采集成功后 `bash "$GIT_REPO/scripts/deploy.sh"`(journalctl 2026-09-27 05:00:01 `trade-us-stock-morning.service` 启动)
- `update_all.sh` L69/L146:`bash "$REPO/scripts/deploy.sh"`(17:50)
- `deploy.sh` L284:`"$PY" "$GIT_REPO/docs/kelly/position/scripts/export_accum_nav_map.py" --all`
- `deploy_20260927_0500.log` L539-540:"生成 accum_nav_map.json ... exported 1710 ETF 1472559 date-rows -> /home/ubuntu/code/trade-data-signal/docs/kelly/position/scripts/accum_nav_map.json"
- `export_accum_nav_map.py` L41 OUT_JSON = 脚本同目录;L44 SPLIT_DIR = 同目录 `accum_nav/`
- `run_ab_direction_anchor.sh`:满 7 日 → 每次调用都走 `ab_direction_anchor.py --reconcile --force`(即满 7 交易日后每天 21:15 都重写,不再只写一次);`ab_direction_anchor.py` L312 out_path = git_repo / `docs/ai-predict/out/` / `ab_direction_anchor_7d.json`(reconcile 分支内无条件 `atomic_write_json`)
- `trade-ab-direction-anchor.timer` OnCalendar=21:15(每天);满 7 交易日后每次触发都 `--reconcile --force` 重写;mtime 09-24 21:15:01 吻合

## 4. 消费方分析(为何脱跟踪安全)

### 4.1 accum_nav_map.json
- 前端读 R2 + 线上 `./data/`:`static-site/common.js:1266` / `static-site/lab.js:8147`,`urls = ["https://ss.fx8.store/r2/data/accum_nav_map.json", "./data/accum_nav_map.json"]`
- deploy 链:deploy.sh L290 `cp "$GIT_REPO/docs/.../accum_nav_map.json" "$REPO/static-site/data/"` → R2 上传源;L296 `cp -R accum_nav/` per-ETF 拆分
- 机检:`check_data_integrity.py` L979/1014/1069 全用 `data_dir / "accum_nav_map.json"`(data_dir = `$REPO/static-site/data`,见 deploy.sh L305 传参 + detect_dirs L2216-2236)
- R2 上传:`upload_r2.py` L1242 `cmd_upload_accum_nav` 读 `STATIC_DIR / "data/accum_nav"`(L1260)+ L2325 上传清单
- **代码仓 `docs/` 那份唯一用途 = deploy.sh L290/296 的 cp 源**(只需磁盘存在,不需要进 git)

### 4.2 ab_direction_anchor_7d.json
- 全仓 grep 零消费方(仅 `scripts/run_ab_direction_anchor.sh` 引用自身生成器 + 自身 docstring)

## 5. 潜在风险(非当前交集,本次部分处理)

| 项 | 现状 | 判定 |
|---|---|---|
| `GIT_REPO/data/` 下 tracked 4 文件(`index_etf_map.json`/`stock_codes.json`/`trade.db`/`trade_dates.txt`) | deploy.sh L513-514 `rsync "$REPO/data/" → "$GIT_REPO/data/"` 会覆盖写;当前 mtime 09-12 后未变、`git status data/` 无 M → 未踩响;未来数据仓侧更新即会变 M 无提交 → pull 隐患(与 #115 同源机制) | **本次不动**(见 §7:有消费方/拿不准) |
| `GIT_REPO/docs/kelly/position/scripts/accum_nav/`(1710 文件 29MB) | deploy.sh L296 `cp -R` 到 static-site;`git ls-files` = 0 **未 tracked** → 当前不挡 pull;但 29MB untracked 在代码仓,`git add -A` 有误纳风险(非 pull 隐患) | **已 ignore**(防 add -A 误纳) |
| `static-site/data/` 全部 0 tracked | deploy rsync(`static-site/data` → `GIT_REPO/static-site/data`)安全 | 无隐患 |
| `sync_dev_from_r2.sh`(写 `GIT_REPO/data/board_etf_map.json`) | 仅手动,非定时任务 | 无隐患 |

## 6. 修法与选型理由(为何否掉①搬仓/③云上提交)

| 候选 | 评价 | 结论 |
|---|---|---|
| ① 生成器输出迁 static-site/data(或数据仓) | accum_nav_map 消费方(deploy L290 cp / upload_r2 L1242)全在 static-site 侧,代码仓 docs/ 那份无直接消费方 → 适用;#115 先例;**但需改 export_accum_nav_map.py 输出路径 + deploy.sh L284/L290/L296 + check_data_integrity L1023/1063 + upload_r2 L1242 四处且零收益** | **否掉**(改 4 处零收益) |
| ② `.gitignore` + `git rm --cached` | 两个文件都适用;保留磁盘 + static-site/R2(前端无感知);消费方无 git 历史依赖;ab_direction_anchor_7d 纯报告产物,零消费方 | **主推,本次执行** |
| ③ 云上跑完就提交 | **不取**——trade 代码仓不该被生产任务写;且 deploy 已改为精确 add 6 min,引入全量提交会破坏 #115 机制 | **否掉** |

**执行(2026-09-27,feat 分支)**:
- `git rm --cached docs/kelly/position/scripts/accum_nav_map.json docs/ai-predict/out/ab_direction_anchor_7d.json`(只脱跟踪,磁盘文件保留)
- 根 `.gitignore` 追加两条精确路径(第三条约 `accum_nav/` 已存在于既有条目):
  - `docs/kelly/position/scripts/accum_nav_map.json`
  - `docs/ai-predict/out/ab_direction_anchor_7d.json`
  - (`docs/kelly/position/scripts/accum_nav/` 既有,防 add -A 误纳)

## 7. data/ 下 4 个 tracked 文件:本次不动(验证结论)

`deploy.sh:513` `rsync "$REPO/data/" → "$GIT_REPO/data/"` 会覆盖写代码仓 `data/` 下 4 个已跟踪文件。grep 消费方结论:

- **`index_etf_map.json`**:`scripts/simulate_trade.py:97-98` 注释「旧的 data/index_etf_map.json 不再读,保留文件作历史兼容」,`INDEX_ETF_MAP_PATH` 实际指向 `board_etf_map.json` → **代码仓路径无消费者**
- **`trade.db`**:全仓(含 docs)grep 仅 migration-data-bootstrap-plan 提到「0B 占位 DB,旧 trade 项目占位」→ **代码仓路径无消费者**
- **`stock_codes.json`**:`app/collector/{stock_daily,mootdx_daily,baostock_daily}.py` 读 `_DATA_DIR / "stock_codes.json"`,`_DATA_DIR = Path(__file__).absolute().parent.parent.parent / "data"`——云上 `app/` 是 symlink → 代码仓,`Path(__file__).absolute()` **不 resolve symlink**,数据路径落 `REPO/data`(数据仓)**非代码仓** → 生产消费方读数据仓,代码仓这份是 rsync 镜像
- **`trade_dates.txt`**:`app/calendar.py:11` `_CACHE_PATH = Path(__file__).absolute().parent.parent / "data" / "trade_dates.txt"`(同上,落数据仓);`scripts/check_data_gap_alerts.py:742-744` 读 `repo / "data" / "trade_dates.txt"`,`repo` 默认 `REPO`(数据仓);**但 `scripts/nextday_plan_generator.py:169-170` `for base in (db_path.parent, ROOT / "data", REPO / "data")` 含 `ROOT / "data"`(`ROOT = Path(__file__).resolve().parent.parent` **resolve 到代码仓**)→ 代码仓 `trade_dates.txt` 是真实 fallback 消费路径**
- 迁移 bootstrap 文档 `docs/deploy/migration-data-bootstrap-plan-20260912.md:41/72-74/118` 显式把 4 文件列「git tracked 自带」= **依赖 tracked 状态做新机 bootstrap 种子**

**结论:代码仓 `data/` 4 文件未做脱跟踪**。原因:
1. `trade_dates.txt` 有真实 fallback 消费方走代码仓路径(nextday_plan_generator L169-170,ROOT resolve 到代码仓)
2. 迁移 bootstrap 文档把 4 文件当作「git tracked 自带」的 bootstrap 种子(脱跟踪后新机 clone 即缺,破坏 bootstrap 契约)
3. 当前两侧内容一致未踩响(低优先级),且与 #115/#118 两文件的「定时频繁重写+零消费方」性质不同
→ **拿不准则不动**,上报主控拍板后再定。

## 8. 云上首拉清理步骤(主控 merge 后执行,精确命令)

> ⚠️ **时序硬约束**:merge 后必须赶在云上下一次定时 deploy(**`trade-us-stock-morning` 每天 05:00 / `trade-update-all` 每天 17:50**)之前完成本清理。否则定时 deploy 的 fetch+rebase(`deploy.sh:799-887`)遇「本地 M + main 删除该文件」会被挡;deploy 的 unmerged 兜底只清 `static-site/data/*`(`deploy.sh:161/798`),不覆盖这类数据文件 → 非数据 unmerged 直接 `exit 1` 拒绝整轮 deploy(`deploy.sh:169`),且会反复阻断当日所有定时任务。

> 目标:云上代码仓 `GIT_REPO=/home/ubuntu/code/trade-data-signal` 在 pull main 前先清掉本地脏文件,使两文件回到「untracked + ignored」状态,不再因 main 改动该文件而中断 pull。

```bash
# 1. 登录云上
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173
cd /home/ubuntu/code/trade-data-signal

# 2. 确认脏文件(mtime 近 = 定时任务刚写过;git status 应为 M)
ls -l docs/kelly/position/scripts/accum_nav_map.json docs/ai-predict/out/ab_direction_anchor_7d.json
# 先跑全量 git status --porcelain:任何 tracked M 都会挡 git pull(不只这两文件;
#   §7 的 data/ 下 4 个(index_etf_map.json/stock_codes.json/trade.db/trade_dates.txt)也会被 deploy.sh:514 rsync 覆盖写)
git status --porcelain
# ⚠️ 发现除这两文件外的任何 M → 先停下上报主控,不要盲清

# 3. 备份一份到 /tmp(防 merge 前后续任务仍要 cp 源);必须成功才继续,失败=停下,不能丢弃本地数据
cp docs/kelly/position/scripts/accum_nav_map.json /tmp/accum_nav_map.json.bak-20260927 || { echo "✗ 备份失败,停止"; exit 1; }
cp docs/ai-predict/out/ab_direction_anchor_7d.json /tmp/ab_direction_anchor_7d.json.bak-20260927 || { echo "✗ 备份失败,停止"; exit 1; }

# 4. 丢弃本地脏(只这两个文件,精准路径,不用 git reset/checkout -- . )
git checkout -- docs/kelly/position/scripts/accum_nav_map.json docs/ai-predict/out/ab_direction_anchor_7d.json

# 5. 拉 main(merge 后此步无阻碍)
git pull
#    若仍被挡 = 步骤 2 有漏 M,停下上报,不要继续丢弃其它文件

# 6. 拉完重建磁盘文件(下次定时任务会自己重写;若需立即到位,手动重跑生成)
#    accum_nav_map: 等下次 17:50 update_all 或 05:00 us-stock-morning 自动重写即可(2 次/天)
#    ab_direction_anchor: 满 7 交易日后每天 21:15 定时自动重写(无条件 atomic_write)
#    也可手动: cd /home/ubuntu/code/trade-data && bash scripts/deploy.sh(会触发 export_accum_nav_map)
```

⚠️ 步骤 4 只 checkout 这两个文件,**禁用** `git checkout -- .` / `git reset --hard`(会把其他本地产物一起丢)。merge 前这两文件在云上仍是 untracked+ignored 正常态,定时任务照常重写磁盘文件不影响。

## 复现段

- **踩响复现(2026-09-27 #115 实测)**:云上 `git pull` 报 `error: Your local changes to the following files would be overwritten by merge`(accum_nav_map.json 或 ab_direction_anchor_7d.json),中断代码同步;解法=`cp` 备份 + `git checkout -- <文件>` 单文件丢弃
- **修复复现**:本地 `git rm --cached` 两文件 → `git status` 中两文件进入 D(未 staged);磁盘文件仍在(`ls -l` 验证);`.gitignore` 新增两条后 `git check-ignore` 两路径返回命中 → 云上 `git pull` 不再因这两文件中断
- **消费方不受影响验证**:前端读 R2/`./data/`(common.js L1266 / lab.js L8147);deploy.sh L290 cp 源只需磁盘存在;check_data_integrity / upload_r2 全走 static-site/data
- **四件套**:本体(本文)+ 生成脚本(无,纯手动审计 + 命令)+ 复现段(本节)+ 配套 commit(feat 分支)

## reviewer 审查结论与 P2 整改记录(2026-09-27)

reviewer 独立审查结论 = **可 merge**(P0 无 / P1 无阻塞项),提出 4 条 P2(全在报告文本)+ 1 条时序提醒,已全部整改:

| 项 | 改了什么 |
|---|---|
| **P2-1(事实错误,必修)** | `ab_direction_anchor_7d.json` 写入频率改准:此前误记为低频(约两周才写一次),实际满 7 交易日后**每天 21:15** 都经 `--reconcile --force` 无条件 `atomic_write_json`(内容可能不变);同步改 §2 表格频率列/触发列、§3 触发链、§8 步骤 6 注释 |
| **P2-4(口径表述,必修)** | §2 标题改为「当前已踩响且可安全脱跟踪 = 恰好 2 例(同机制但本次不动的另见 §7)」,标题下补说明「全量同机制对象 = 本 2 例 + §7 的 4 个 data/ 文件」 |
| **P2-2(执行步骤补强,必修)** | §8 步骤 2 改先跑全量 `git status --porcelain`(不再只 grep 两文件),发现除这两文件外的任何 M 先停下上报不盲清;步骤 5 `git pull` 后补「若仍被挡 = 步骤 2 有漏 M,停下上报」 |
| **P2-3(静默吞失败,必修)** | §8 步骤 3 两条 `cp ... 2>/dev/null || true` 改为失败即 `exit 1` 停止,上方注释写明「必须成功才继续,失败=停下,不能丢弃本地数据」 |
| **P1(时序提醒)** | §8 开头补醒目前置:merge 后必须赶在云上下一次定时 deploy(05:00 / 17:50)前完成清理,否则 fetch+rebase 被本地 M 挡,deploy unmerged 兜底只清 `static-site/data/*`,非数据文件直接 exit 1 拒绝整轮 deploy |

## 上线验证与云端落地记录(主控 §0, 2026-09-27)

**① main 链**:`scripts/main-merge.sh worktree-agent-ac68db13b10659eb5` → `89eade0a9..21c5cd55e`
(版本哨兵 A/B PASS、critical-css 双源 77/77 PASS、前端零改动跳过统一 bump)。

**② 云上清理(§8 修正版实跑,可逆非静默)**:清理前云上全量 `git status --porcelain` = **恰好 2 个 M**
(仅本两文件,**无第三例**,与 §2 穷举结论一致)→ 两文件 `cp` 备份到 `/tmp/*.bak-20260927`
(`accum_nav_map` sha256 `9fa1cb91…` / 26,181,355 B;`ab_direction_anchor_7d` sha256 `ef26c646…` / 3,062 B)
→ `git checkout --` 精准两文件(未用 `checkout -- .` / `reset --hard`)→ status 归零 → merge 第 10 步
自动 `git pull` 成功(未再被挡)。

**③ 云上终态**:HEAD = `21c5cd55e`(与 origin/main 逐位一致),`git status --porcelain` **空**;
两文件已从云上磁盘消失(下次 deploy L284 / 21:15 reconcile 自动重生),
`git check-ignore` 两路径命中 `.gitignore:245` / `:248` → **「M 脏文件挡 pull」机制闭环根除**。

**④ 生产未受影响(关键)**:云上 `static-site/data/accum_nav_map.json`(26,181,355 B, 09-27 05:08)
与 `accum_nav/` per-ETF 桶目录**原样未动**——前端读 R2 / `./data/`,脱跟踪只动代码仓 `docs/` 那份副本;
生产数据位无缺口,无需补数。

**⑤ 本机同态与一条使用注意**:本地 main 同样已脱跟踪 + ignore 生效;本地 `docs/` 那份磁盘文件随 merge
一并删除(deploy.sh L284 下次本地 deploy 自动重生)。**注意**:手动回测脚本
`docs/kelly/position/scripts/kelly_ghi_avsp_sweep.mjs:32`(`NAV_JSON = path.join(__dirname, "accum_nav_map.json")`)
读的是脚本同目录磁盘文件——本机首次使用前需先跑一次 `python3 docs/kelly/position/scripts/export_accum_nav_map.py --all`
生成,否则报文件缺失。该脚本无 git 历史依赖,脱跟踪本身不影响它。

**⑥ §0 三查③(前端展示层)**:本次前端零改动,不涉及。

## 关联

- #118 索引行:pending-features-index.md(状态 → 已完成)
- #115 先例:同「云上定时任务写 + 代码仓 tracked」机制,先修 manifest
- 归档明细:`/tmp/cloud-write-audit-detail.md`(原始穷举证据)
