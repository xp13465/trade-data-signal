# 本机误传 R2 防再犯 7 层防护实施报告(2026-10-03)

- 方案全文: `/tmp/export-guard-plan.md`(researcher 产出)
- 事故报告: `docs/ops/local-export-overwrote-r2-incident-20261002.md`
- 分支: `feat/export-guard-20261003`(base=origin/main `11073b291`, base-fresh 校验 PASS)
- 改动文件: `static-site/export.py` + `scripts/upload_r2.py` + `scripts/deploy.sh`

## 1. 推荐判据(核心,全层共用)

**生产写入方** = `sys.platform != "darwin"` AND `str(ROOT).startswith("/home/")`。两条都是进程/路径事实,不经 env、无法被 REPO 注入伪装(事故即 export.py 注入 REPO=本机树路径绕过 guard 的 REPO_EXPLICIT)。

实现: `scripts/upload_r2.py:82 _is_production_writer()` + `static-site/export.py:1429` 内联同款。

云上实测: platform=linux(ssh 只读确认) + ROOT resolve 到 `/home/ubuntu/code/trade-data-signal`(仍 `/home/` 前缀) → production writer 恒 True → 云上全部放行。本机实测: darwin + `/Users/...` → 恒 False → 本机全部拒绝。

## 2. 每层改动(改前/改后 + 行号 + 为什么云上不受影响)

### L1 去掉 export.py REPO 注入(事故绕过点根断)
- 改前: `static-site/export.py`(原 L1426)`env={**os.environ, "REPO": str(ROOT)}` 强制注入本机树路径 → upload_r2 guard `REPO_EXPLICIT` 提前 return 放行。
- 改后: 上传循环(现 L1441-1457)`subprocess.run([...], capture_output=True, ...)` 不再注入 REPO env。
- 云上为什么不受影响: 云上 `deploy.sh:26 export REPO GIT_REPO` 显式导出(`scripts/deploy.sh:24-26`, 云上 systemd 注入 REPO=/home/ubuntu/code/trade-data), upload_r2.py 子进程继承 REPO → `REPO_EXPLICIT=True` → guard 显式态放行,零变化。intraday_snapshot.sh:27-28 / update_all.sh:35-36 同款显式导出。

### L2 upload_r2 guard 本机树拒绝硬闸(堵 B 类白名单 + REPO 显式伪装)
- 改前: `scripts/upload_r2.py guard_repo_default`(原 L85-86)REPO_EXPLICIT 直接 return;B 类白名单 `_TRADE_FALLBACK_OK={upload-lab,upload-trade-sim,upload-trade-sim-json}`(原 L62)无 REPO 也放行(事故 482+44 落此)。
- 改后: `guard_repo_default`(现 L102-140)开头加 L2 闸(现 L113-128): 本机树 + 「现有 guard 会放行」的路径(REPO 显式 / A 类 / B 类白名单 / purge-low-freq) + 写公共桶 → `sys.exit(2)` + 告警「本机开发树禁止上传公共 R2」。只堵原本会放行的路径,缺省非白名单命令保持原 exit 3(验证命令 2 语义)。
- 云上为什么不受影响: 云上 `_is_production_writer()=True` → L2 不触发;REPO 显式态照常 return。

### L0 export.py 上传段默认语义反转(根治默认值)
- 改前: `static-site/export.py`(原 L1420)`if os.environ.get("EXPORT_SKIP_R2") != "1":` 默认自动上传 10 通道。
- 改后: (现 L1420-1458)默认跳过;仅 `EXPORT_FORCE_R2=1`(或 `EXPORT_SKIP_R2=0`)走上传段;上传前按判据复核,本机树即使 FORCE 也只 dry-run 打印待传清单不 PUT。
- 云上为什么不受影响: 云上 deploy.sh:22 `export EXPORT_SKIP_R2=1` → 本就走「跳过」分支,零变化。方案 2.6 确认云上无「裸跑 export.py 期望自动上传」场景。

### L3 无状态全量默认 dry-run + 告警
- 改前: `_incremental_upload`(原 L987/992-993)状态文件缺失 → 自动退化为全量上传(事故:本机状态缺失→无状态全量覆盖线上)。
- 改后: (现 L1156-1178)mode=「首次/无状态全量」且非 dry-run 且未设 `ALLOW_FULL_UPLOAD=1` → 打印 dry-run 待传清单 + notify 告警 + `sys.exit(1)`(fail-closed)。周日设计内全量/增量/中断强制全量不受影响。
- 云上为什么不受影响: 云上树实测有 16 个 `.r2_*_state.json`(ssh 只读确认) → 正常增量,不触发 L3;周日全量(mode=「周日强制全量」)显式排除。

### L4 deploy 校验失败升级 --severe 告警
- 改前: `scripts/deploy.sh` 三处校验 FAIL 分支直接 `exit`,无任何通知(事故 5 次 deploy 失败无人知)。
- 改后: check_data_integrity(现 L328-329)/check_task_state(现 L345-346)/check_universe_alignment(现 L362-363)/check_version_consistency(现 L444-445)/check_data_gap_alerts(现 L461-462)FAIL 分支 exit 前追加 notify.py `--severe`(各独立 dedup-key 防轰炸)。
- 云上为什么不受影响: 仅新增通知,不改变校验与阻断行为。

### L6 verify-r2 平日抽样增强 + 异源覆盖阈值告警
- 改前: `cmd_verify_r2`(原 L2828)平日抽样 20;对账不一致只自动补传不告警。
- 改后: (现 L2987)`sample_n = 100`;(现 L3027/3044-3063)累计不一致 key,`>50` → notify 告警「R2 可能被异源覆盖,建议查本机误跑」(dedup 6h,标注周日设计内可忽略)。
- 云上为什么不受影响: 抽样只是多 HEAD(成本 ~0),告警只提示不阻断,周日全量仍是最终兜底。

### L5 上传前把被覆盖 key COPY 到备份桶(§25 备份先于覆盖机制化)
- 改前: 无覆盖前备份,事故恢复只能靠事后 R2 快照。
- 改后: `s3_request` 扩展 `extra_headers`(现 L404/439-440,支持 `x-amz-copy-source`);新增 `_backup_overwritten_keys`(现 L973-1006)+ `_prune_pre_upload`(现 L939-970);在 `_incremental_upload` 真 PUT 前(现 L1252-1256)对「将被覆盖的既有 R2 key」(HEAD 200)先 COPY 到 `BACKUP_BUCKET/pre-upload/<YYYYMMDD>/<key>`;保留 7 天按天 prune(防无限增长,memory #151 备份桶容量教训)。
- 云上为什么不受影响: 备份是上传前多一次服务端到服务端 COPY(带宽 0),失败不阻断上传;云上正常增量仅在 changed 非空时对覆盖 key 备份。

## 3. 自测证据

### 3.1 本机 5 条拒绝(期望全「被拒/不上传」,全部 PASS)
| # | 命令 | 期望 | 实测 | 证据 |
|---|---|---|---|---|
| 1 | `python static-site/export.py` | 跳过自动上传/dry-run,无 PUT | 上传段默认跳过(真值表断言 PASS,见 3.2) | worktree 无 sentiment.db 无法完整实跑,用断言+走查替代(见 4) |
| 2 | `python scripts/upload_r2.py upload-index` | exit 3 | **rc=3** | guard REPO 缺省拒绝,输出「✗ REPO 未设」 |
| 3 | `python scripts/upload_r2.py upload-lab` | exit 2 | **rc=2** | L2 本机树拒绝,输出「本机开发树...禁止上传公共 R2」 |
| 4 | `REPO=/Users/linhuichen/code/trade-data python scripts/upload_r2.py upload-index` | exit 2 | **rc=2** | 即使 REPO 显式也被 L2 拒 |
| 5 | `EXPORT_FORCE_R2=1 python static-site/export.py` | 仅 dry-run + 告警 | 上传段 FORCE 分支本机 → dry-run(真值表断言 PASS) | 同 #1 替代验证 |

### 3.2 单元断言(ALL PASS)
- `/tmp/exportguard_assert.py`: export.py 上传段真值表 7 条(默认跳过/本机 FORCE dry-run/SKIP=1 优先级/云上 FORCE 真传/云上默认跳过)+ 本机判据 + 命令分类 13 项 + 云上无 REPO B 白名单放行。
- `/tmp/cloud_sim.py`: 云上 REPO 显式子进程(REPO env 启动时注入)5 命令(upload-index/upload-lab/upload-db/upload-industry/upload-kelly-parts)全部放行。
- `/tmp/exportguard_assert2.py`: L3 真值表 6 条 + L3 拦截分支走查 + L5(s3_request extra_headers/备份函数/7 天 prune/备份先于上传)+ L6(抽样 100/阈值告警)+ L0/L1/L2 源码在位。

### 3.3 云上 2 条(本次只读验证,未在云上写任何东西)
方案验证命令(云上 deploy.sh all rc=0 / 云上 upload-index 正常增量)会真写 R2,本次**按任务要求只读**未跑,用只读替代验证 + 单元级云上模拟:
- **环境事实(ssh 只读)**: platform=linux;ROOT resolve=`/home/ubuntu/code/trade-data-signal`(`/home/` 前缀,production writer 成立);`/home/ubuntu/code/trade-data/scripts`→symlink→trade-data-signal/scripts;树内 16 个 `.r2_*_state.json`(增量上传,不触发 L3);systemd service 注入 REPO(抽查 3 个)。
- **逻辑验证(单元级云上模拟)**: production writer=True 时 guard 全放行(3.2 两组断言),deploy.sh 显式 `export REPO`+`EXPORT_SKIP_R2=1` 使 L0/L1 不改变云上行为。
- **云上真跑留待**: merge 上线后由 tester 按方案 2.5 云上 2 条实测(本次不动云上任何状态)。

### 3.4 L5/L4/L6 生效验证
- L5(备份 key 出现): 需真实增量上传发生才产生 `pre-upload/` key,本次未真传 → 上线后首次上传由巡检确认。
- L4(告警): 需云上制造 check 失败 → 本次只读未触发 → 上线后按方案 2.5 L4 项验证。
- L6(阈值告警): 需构造 >50 差异 → 本次未构造 → 上线后按方案 2.5 L6 项验证。

## 4. 诚实标注
- 完整实跑 `python static-site/export.py` 无法在本次 worktree 进行(worktree 无 `data/sentiment.db` 且无 `static-site/data/`,本机主库在 trade-data),故验证 1/5 采用「真值表断言 + 源码走查」替代(方案允许),断言脚本复刻上传段条件逐字提取自改动后源码。
- 云上 deploy.sh all / upload-index 真跑链路由 tester 在 merge 上线后验证(本次只读,不写云上)。
- verify-r2 平日抽样阈值 100、异源覆盖告警阈值 50 为方案建议初值,上线后观察调整。

## 5. 零误伤云上走查汇总
| 层 | 云上链路 | 为什么不受影响(引用行号) |
|---|---|---|
| L0/L1 | deploy.sh 调 export.py | deploy.sh:22 `export EXPORT_SKIP_R2=1` 走跳过分支;deploy.sh:26 `export REPO GIT_REPO` 子进程继承 REPO 显式态放行 |
| L2 | deploy.sh 全部 18 个 upload 通道 | 云上 `_is_production_writer()=True`(linux+`/home/` 前缀)不触发 L2 |
| L3 | 云上增量/周日全量 | 树内 16 状态文件→增量;周日全量 mode 显式排除 |
| L4 | deploy 校验闸门 | 仅新增通知,不改阻断行为 |
| L6 | verify-r2 平日 | 抽样多 HEAD 成本 ~0,告警只提示不阻断 |
| L5 | 云上正常增量 | 仅对覆盖 key 多一次服务端 COPY,失败不阻断 |

## 6. 防重犯索引锚点(建议落 memory)
- 触发词: 本机跑 export/deploy/upload_r2、R2 被异源覆盖、状态文件缺失全量上传、REPO 注入绕过 guard。
- 核心: 生产写入方判据 = platform!=darwin AND ROOT 前缀 `/home/`;REPO env 不可作为信任判据(会被注入伪装)。7 层防护: L1 去 REPO 注入 / L2 guard 本机树拒绝 / L0 export 默认跳过 / L3 无状态全量 dry-run / L4 check 失败 --severe / L6 verify 抽样+异源告警 / L5 覆盖前备份到 signal-backup/pre-upload。
