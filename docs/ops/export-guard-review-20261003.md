# 本机误传 R2 7 层防护 Review 报告(2026-10-03)

- 审查对象: feat/export-guard-20261003 @ `4fc1645c0`(base=origin/main `11073b291`)
- 审查角色: reviewer(独立于实施 agent,只找问题不改代码)
- 事故背景: 2026-10-02 P0,本机误传 966 个 R2 key 被覆盖, 本次是根因修复的独立审查
- 分级: C 级(后端/数据层改动,动已上线生产上传链路), 审查标准拉满

## 0. 结论

**可 merge**(附 2 项上线观察建议,非阻断)。云上零误伤独立坐实, 本机防护 5 条实测全部 PASS, 判据反例排查无漏网。

1. 云上生产写入方判据(`platform!=darwin AND ROOT 前缀 /home/`)在云上全部真实链路恒成立, L2/L3/L5/L6 全部不拦云上正常上传
2. 本机即使 REPO 显式注入(事故同款路径)也被 L2 用 ROOT 兜底拒绝(实测 rc=2)
3. 诚实性核查: 实施报告无包装, worktree 无 DB 用真值表断言替代已诚实标注, 云上只读未真跑已标注留待 tester

**上线观察建议(不阻断 merge)**:
- S1: L5 周日全量备份量级 ~2.8 GiB/周日 → signal-backup 桶(当前 14.298GiB 已超免费 71%)峰值可能到 ~20GiB, 观察 2 个周日后的 pre-upload/ 实际占用, 若超预期考虑周日跳过备份或压缩
- S2: L3 拦截依赖 16 个状态文件在位, 云上当前全在(已 ssh 确认), 若某通道状态文件意外损坏 → 该通道首次全量被拦(安全方向, fail-closed), 需人工 `ALLOW_FULL_UPLOAD=1` 放行一次; 建议 verify-r2 周日对账保持兜底

## 1. 云上零误伤走查(独立实证,非复述实施报告)

### 1.1 判据事实(ssh 只读确认 122.51.111.173)
| 事实 | 实测值 | 判据成立 |
|---|---|---|
| platform | linux | `!=darwin` ✓ |
| upload_r2.py ROOT | `trade-data/scripts` symlink→`trade-data-signal/scripts`, `resolve()` 后 ROOT=`/home/ubuntu/code/trade-data-signal` | `/home/` 前缀 ✓ |
| export.py ROOT | `absolute()`(不解析 symlink)→ `/home/ubuntu/code/trade-data/static-site` 的 parent=`/home/ubuntu/code/trade-data` | `/home/` 前缀 ✓ |
| 状态文件 | 16 个 `.r2_*_state.json` 全部在位(与代码全部 16 个增量引擎通道逐一对应) | L3 全走增量,不触发 |
| REPO 注入 | systemd 38 service 全注入 `REPO=/home/ubuntu/code/trade-data` | REPO_EXPLICIT=True |

### 1.2 deploy.sh 17 条 run_r2_upload 通道逐条走查
| # | 命令 | 引擎 | 状态文件 | L2(云上) | L3 | L5 备份 | 结论 |
|---|---|---|---|---|---|---|---|
| 1 | upload-lab | 增量 | .r2_lab_state.json 在 | 放行 | 增量不拦 | 对覆盖 key 备份 | 零变化 |
| 2 | upload-trade-sim | 增量 | .r2_trade_sim_html_state.json 在 | 放行 | 增量不拦 | 同上 | 零变化 |
| 3 | upload-trade-sim-json | 增量 | .r2_trade_sim_json_state.json 在 | 放行 | 增量不拦 | 同上 | 零变化 |
| 4 | upload-index | 增量 | .r2_index_state.json 在 | 放行 | 增量不拦 | 同上 | 零变化 |
| 5 | upload-etf-hist | 增量 | .r2_etf_hist_state.json 在 | 放行 | 增量不拦 | 同上 | 零变化 |
| 6 | upload-accum-nav | 增量 | .r2_accum_nav_state.json 在 | 放行 | 增量不拦 | 同上 | 零变化 |
| 7 | upload-industry | 增量 | .r2_industry_state.json 在 | 放行 | 增量不拦 | 同上 | 零变化 |
| 8 | upload-public-fund | 增量 | .r2_public_fund_state.json 在 | 放行 | 增量不拦 | 同上 | 零变化 |
| 9 | upload-etf-score | 增量 | .r2_etf_score_state.json 在 | 放行 | 增量不拦 | 同上 | 零变化 |
| 10 | upload-data-large | 增量 | .r2_data_large_state.json 在 | 放行 | 增量不拦 | 同上 | 零变化 |
| 11 | upload-kelly-parts | 增量 | .r2_kelly_parts_state.json 在 | 放行 | 增量不拦 | 同上 | 零变化 |
| 12 | upload-kelly-parts-sdc | 增量 | .r2_kelly_sdc_state.json 在 | 放行 | 增量不拦 | 同上 | 零变化 |
| 13 | upload-all-data | 增量 | .r2_all_data_state.json 在 | 放行 | 增量不拦 | 同上 | 零变化 |
| 14 | upload-kelly-snapshots | 增量 | .r2_kelly_snapshots_state.json 在 | 放行 | 增量不拦 | 同上 | 零变化 |
| 15 | upload-feed(upload-data-files feed.xml) | _upload_glob 非增量 | 无状态文件 | 放行 | 不经 L3 | 不经 L5 | 零变化 |
| 16 | verify-r2 | 只读对账(_READ_ONLY_CMDS) | — | 放行 | 不经 L3 | 不经 L5(L6 生效) | 零变化 |
| 17 | purge-low-freq | 只读 purge(_READ_ONLY_CMDS) | — | 放行 | 不经 L3 | 不经 L5 | 零变化 |

### 1.3 deploy.sh 之外云上 upload 通道(deploy.sh 调 export.py 走 EXPORT_SKIP_R2=1 跳过上传段)
| 通道 | 来源脚本 | 引擎/状态 | 结论 |
|---|---|---|---|
| upload-index / upload-data-files | intraday_snapshot.sh(REPO 显式) | 增量/glob | 放行 |
| upload-fund-nav | fund_nav_upload_async.sh | 增量 .r2_fund_nav 在 | 放行 |
| upload-etf-hist | etf_national_team_backfill.sh(REPO 显式) | 增量 | 放行 |
| upload-data-files | fapi_daily_syn.sh(fapi_bj_width_export.py 注入 REPO=/home 前缀) | glob | 放行 |
| upload-db / upload-claude-backup | backup_db.sh / backup_claude_self.sh | _PRIVATE_ONLY_CMDS 私有桶 | 放行(私有桶不受 L2 限) |
| upload-intraday / upload-data-large | turnover_backfill.sh(REPO 显式) | 增量 | 放行 |

> 云上所有上传链路均经 upload_r2.py CLI(`__main__` 的 guard_repo_default), 无一绕过 guard; 唯一 import upload_r2 的是本机 sync_dev_from_r2.sh(只调只读对账函数,不触发 guard 的写闸,不 PUT)。

### 1.4 判据反例排查(独立穷举)
- ❌ 无「云上 ROOT 非 /home/」反例: 云上仅 trade-data + trade-data-signal 两棵树, 均 /home/ubuntu/code 下
- ❌ 无「云上缺状态文件」反例: 16 个状态文件 ssh 逐一确认在位, 与代码全部 16 个增量通道一一对应
- ❌ 无「云上裸跑 export.py 期望自动上传」链路: deploy.sh(SKIP=1)/sync_dev(SKIP=1)/etf_backfill(直接 upload)/turnover_backfill(importlib 不跑 main)/fapi(自己 upload-data-files)
- ❌ 无「REPO 显式伪装逃逸」: L2 判据用 ROOT(进程/路径事实,不经 env), 不受 REPO 注入影响(本机实测 rc=2)
- ⚠️ 边界: 云上手动跑 deploy.sh 若 REPO 未设(shell 无 systemd 注入)→ fallback 本机路径, 但 _is_production_writer 仍按 ROOT(云上 /home/)判 True, 上传不拦(行为与改前一致, 非本次回归)

## 2. 本机 5 条实测(本次独立重跑, 实际输出)
| # | 命令 | 期望 | 实测 | 结论 |
|---|---|---|---|---|
| 1 | `python3 static-site/export.py`(worktree 无 DB 用真值表断言) | 跳过上传, 无 PUT | 断言 active=False 全 PASS | PASS |
| 2 | `python3 scripts/upload_r2.py upload-index` | rc=3 | **rc=3** REPO 未设拒绝 | PASS |
| 3 | `python3 scripts/upload_r2.py upload-lab` | rc=2(L2) | **rc=2** 本机开发树禁止上传公共 R2 | PASS |
| 4 | `REPO=/Users/linhuichen/code/trade-data python3 scripts/upload_r2.py upload-index` | rc=2(事故同款伪装) | **rc=2** 即使 REPO 显式也被 L2 拒(判据用 ROOT 非 REPO) | PASS |
| 5 | `EXPORT_FORCE_R2=1 python3 static-site/export.py` | 本机 dry-run 不 PUT | 断言 FORCE 分支走 dry-run 全 PASS | PASS |

### 2.1 本机私有桶合法链路不受 L2 误伤
- `_PRIVATE_ONLY_CMDS={upload-db, upload-large-json, upload-claude-backup, upload-decommissioned}` → `_is_public_bucket_write=False` → L2 不拦 → backup_db.sh / backup_claude_self.sh 本机备份私有桶照常
- `_READ_ONLY_CMDS={list, download-db, verify-r2, verify-channels, purge-low-freq}` → 本机只读对账照常

## 3. 逐层风险点

### L1 删 export.py REPO 注入
- sync_dev_from_r2.sh 合法: 步骤3 `EXPORT_SKIP_R2=1 REPO=... export.py`(跳过上传段), 步骤4 import upload_r2 只调只读对账(不触发 guard 写闸) → 不受影响
- 云上 deploy.sh 显式 `export REPO GIT_REPO`(L26)→ 子进程继承 REPO → REPO_EXPLICIT=True → 零变化

### L2 guard 本机树拒绝硬闸
- 私有桶排除逻辑正确: _PRIVATE_ONLY_CMDS/_READ_ONLY_CMDS 均被 `_is_public_bucket_write` 排除, 本机备份/对账不误伤
- 反例: 本机缺省非白名单命令(upload 裸命令)→ `_would_pass=False` → 保持原 exit 3(不误升级为 2, 语义保持)

### L3 无状态全量 dry-run
- 周日 10-04/10-05 设计内全量: mode="周日强制全量"(weekday==6 且 old_files 在)→ **不在拦截名单**(仅拦 "首次/无状态全量")→ 云上不被拦
- ⚠️ 边界: 若某通道状态文件缺失/损坏 + 非周日 → mode="首次/无状态全量" → 被拦(告警+fail-closed)。云上 16 状态文件全在, 正常不触发; 首次上线某新通道需 ALLOW_FULL_UPLOAD=1 人工放行一次(设计正确)

### L4 deploy 校验失败 --severe 告警
- 5 处(check_data_integrity/check_task_state/check_universe_alignment/check_version_consistency/check_data_gap_alerts)FAIL 分支 exit 前各追加 notify.py --severe, dedup-key 各自独立防轰炸
- 仅新增通知, 不改校验与阻断行为 → 云上阻断逻辑零变化

### L5 上传前 COPY 备份(容量/成本风险, 需观察)
- 7 天 prune 已配(`_PREUPLOAD_RETENTION_DAYS=7`, 按 pre-upload/<YYYYMMDD>/ 前缀 DELETE)
- 备份只对「R2 已存在的将被覆盖 key」(HEAD 200 才 COPY), 新 key 跳过
- ⚠️ 容量: signal-backup 桶当前 14.298 GiB(超免费 71%), 周日全量时 changed=全部 → 每个既有 key 备份一次, 量级 ~2.8 GiB/周日(主站桶 31,470 对象 2.817 GiB), 7 天窗口重叠 1~2 个周日, pre-upload 峰值 ~3~6 GiB, 桶峰值可能 ~20 GiB。绝对成本低(超额 ~10GiB×$0.015 ≈ $0.15/月)非爆炸, 但属持续增长项 → 建议观察(S1)
- ⚠️ 性能: 周日全量备份为串行 HEAD+COPY(keep-alive 复用), 单通道几秒~几分钟量级, 有叠加超时风险但失败不阻断(R2_FAIL→verify-r2 周日对账兜底) → 非阻断
- COPY 走服务端到服务端(带宽 0), 失败不阻断 → 正确

### L6 verify-r2 抽样 100 + 异源覆盖告警
- 平日抽样 20→100, 每次 HEAD keep-alive ~几十 ms → 额外 ~10s, 成本可忽略
- 不一致 key 累计 >50 → notify 告警(dedup 6h), 只提示不阻断 → 正确

## 4. §23.3 举一反三(全库 REPO 注入点排查)
- `grep -rn "REPO": str(REPO)` 全库: **仅 scripts/fapi_bj_width_export.py:73 一处** 仍注入 REPO
- 该处靠 L2 用 ROOT 兜底: 本机 REPO 默认本机路径 → ROOT 非 /home/ → L2 拒(exit 2); 云上 REPO 注入 /home 前缀 → L2 放行 → **闭环无漏网**
- export.py 原注入点已删(L1), 其余调用方均显式 export REPO(合法显式态)

## 5. 诚实性核查(验收铁律: 不信实施报告, 本次逐字复核)
- 实施报告 §4 已明确标注: ①worktree 无 sentiment.db 无法完整实跑 `export.py`, 验证 1/5 用「真值表断言+源码走查」替代 ②云上 2 条真跑链路(会真写 R2)按任务要求只读未跑, 留待 merge 后 tester 实测 ③verify-r2 抽样阈值 100/异源告警阈值 50 为初值待观察
- **无把「断言替代」包装成「实跑通过」** → 诚实性 PASS
- 我本次独立重跑断言脚本全部 PASS, 云上判据事实 ssh 逐一确认, 非转述实施报告

## 6. 影响面清单(改动文件被谁引用)
| 改动文件 | 引用方 | 影响 |
|---|---|---|
| static-site/export.py(L0/L1) | deploy.sh(云上 SKIP=1)/sync_dev_from_r2.sh(SKIP=1)/turnover_backfill.sh(importlib 不跑 main)/fapi_bj_width_export.py(import 复用 write_json) | 云上零变化, 本机裸跑默认跳过 |
| scripts/upload_r2.py(L2/L3/L5/L6) | 全部 17 条 deploy.sh 通道 + intraday/fund_nav/etf_backfill/fapi/backup/turnover 脚本(全 CLI 走 guard) | 云上 production_writer 放行, 本机写公共桶全拒 |
| scripts/deploy.sh(L4) | 云上 17:50 update_all 主链 + 手动 deploy | 仅新增 --severe 告警, 阻断逻辑不变 |

## 7. 复现段
- 本机判据: `python3 scripts/upload_r2.py upload-index`(rc=3) / `upload-lab`(rc=2) / `REPO=/Users/linhuichen/code/trade-data ... upload-index`(rc=2)
- 断言脚本: `/tmp/exportguard_assert.py`(export.py 上传段真值表) / `/tmp/exportguard_assert2.py`(L3/L5/L6 真值表) / `/tmp/cloud_sim.py`(云上 REPO 显式放行, 需 `REPO=/home/ubuntu/code/trade-data` 前缀跑)
- 云上只读确认: `ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'ls data/.r2_*_state.json; ls -ld trade-data/scripts; ls -l trade-data/scripts/upload_r2.py trade-data/static-site/export.py'`
