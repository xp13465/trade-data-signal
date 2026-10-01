# #149 `trade_deploy.lock` 职责错位根治 — 方案②③实施报告

- **日期**: 2026-10-01(implementer 实施,base=main@4ff477fb1)
- **分支**: `feat/149-lock-split-20261001`
- **commit 链**: `564558bbb`(方案② async 锁分离)+ `8cae67c94`(方案③ 排队上限 600)
- **任务范围**: 方案②(必做)+ 方案③(条件做);方案①⑤明确不做;deploy.sh async 触发逻辑本轮不改(见 §7)
- **验收判据(#149)**: `trade_deploy.lock` 持锁者里不再出现 `staticdata_backup_async`(长跑段)

---

## 1. 方案②改造前后锁获取点对照(async 灾备)

| 段 | 改造前(2026-09-25 引入 step3.5b 后) | 改造后(本轮) | 持锁时长 |
|---|---|---|---|
| rsync(step1 DB / step2 config / step3 JSON) | `trade_deploy.lock` 内 | **锁外**(磁盘操作天然可并发, rsync 幂等) | 秒~分钟 |
| step3.5a large-json .gitignore 排除 | 锁内 | **锁外** | 秒 |
| step3.5b `upload_r2.py upload-large-json`(3.1 万文件 R2 跨境 HEAD 比对) | 锁内(**长跑主因, 实测 26~105min**) | **`/tmp/trade_backup_r2.lock` 独立锁, `--nb` 非阻塞抢**; 抢不到直接跳过本轮绝不排队 | 0 或 26~105min(但不在主锁上) |
| step4 git add/commit/push | 锁内 | **`trade_deploy.lock` 内**(两段式 exec 重入, 仅此段持主锁) | 秒~分钟级 |

**锁获取点变化**: async 从「整脚本 1 次持锁」(`scripts/staticdata_backup_async.sh:66` 原 `--block-timeout 3600`)改为「两段式」:

- **段1(首次进入, 不持主锁)**: rsync + step3.5a + step3.5b(R2 独立锁非阻塞)。末尾 export 状态(`LOG`/`STATICDATA_BACKUP_ASYNC_R2_DONE`/`_HB_START`/`STATICDATA_FAIL`)后 `exec with_lock.py --block-timeout 3600 $LOCK bash "$0" "$@"` 重入。
- **段2(重入进程, 已持主锁)**: 仅 git 段。从环境变量恢复段1累积状态, 心跳总时长跨段连续。

**step3.5b 三态判定关键实现**: `with_lock.py --nb` 在锁被占时也 `exit 0`(stderr 打「已被占用」), 与上传成功无法只靠退出码区分 → 捕获输出到临时文件 `grep "已被占用"` 区分 ①被占跳过 ②上传成功 ③失败(`STATICDATA_FAIL=1`, 不阻塞)。

**副作用(按 #129 已论证)**: 某轮灾备 R2 上传跳过 → 数据磁盘+git 留档, 次日 rsync + HEAD ETag 幂等补传(灾备 1/2 层不丢)。

## 2. 方案③: 做了 —— 9 片点名 + 1 处举一反三, `--block-timeout 3600→600`

任务门槛 = 能逐一点名每个被改调用方的兜底路径。**全部点名成立**:

| # | 调用方 | timer 时点 | 超时跳过后的兜底路径 | 可靠性 |
|---|---|---|---|---|
| 1 | update_all.sh:146(deploy all, 主链) | 17:50 | 次日 17:50 全量重跑追平; 17:50 锁空, 实际不触发超时 | ✓ |
| 2 | futures_backfill.sh:97 | 20:05 | 次日 20:05 重跑; 期货数据源持久可重拉 | ✓ |
| 3 | etf_national_team_backfill.sh:123 | 20:07 | 次日 20:07 重跑 | ✓ |
| 4 | lhb_backfill.sh:107 | 18:30 | 次日 18:30 重跑; 交易所公布数据持久 | ✓ |
| 5 | rzhb_backfill.sh:134 | 08:00/19:15 | 次日 08:00+19:15 双机会 | ✓ |
| 6 | public_fund_daily.sh:82 | 16:30 | 次日 16:30 重跑; 基金净值 T+1 公布 | ✓ |
| 7 | public_fund_full.sh:87 | 22:00 | 次日 22:00 重跑 | ✓ |
| 8 | public_fund_quarterly.sh:90 | 03:00 | 下季度 03:00; 凌晨锁空闲, 600s 实际不触发 | ✓ |
| 9 | index_backfill.py:1139(backfill-evening) | 21:00 | 次日 21:00 重跑 | ✓ |
| 10 | pipeline.sh:71(DEPLOY_EACH=1, 举一反三) | 手动/单跑 | 下一轮完整 deploy(update_all 主链每日)兜底 | ✓ |

**改动文件(10)**: `scripts/update_all.sh` `scripts/futures_backfill.sh` `scripts/etf_national_team_backfill.sh` `scripts/lhb_backfill.sh` `scripts/rzhb_backfill.sh` `scripts/public_fund_daily.sh` `scripts/public_fund_full.sh` `scripts/public_fund_quarterly.sh` `app/collector/index_backfill.py` `scripts/pipeline.sh`。

**保留 3600 的两处及理由**:
- `scripts/staticdata_sync.sh:61`: news-fetch/daily-brief 排队护栏。news-fetch 已被调用方 `fetch_news.py:744` subprocess `timeout=600` 截断(排队最多 10min 被杀, 30min 后重来)——改不改实际排队上限已 ≈600s; 不引入无谓 diff。
- `scripts/staticdata_backup_async.sh:216`(段2 git 段重入): async 由 deploy 主链末尾触发, 触发时 deploy 刚释放锁, 大概率立即拿到; 且灾备失败(超时跳过)语义=磁盘+R2 已留档次日幂等补传, 保留 3600 不增加跳过频率。

## 3. 举一反三(§23.3): staticdata_sync.sh 要不要同样处理

**结论: 本轮不改, 且不需要按方案②同样处理。** 理由:

1. **持锁内容无小时级段**: sync 持锁内 = 小 rsync(增量 JSON, 本地跨目录, 秒~分钟级)+ git; **没有** async 才有的 `upload_r2.py upload-large-json` 全量 HEAD 比对段(R2 大文件上传由 async 灾备承担, sync 不碰 R2 上传)。
2. **不在 #149 长跑之列**: 报告 §2 实测长跑者 = deploy 主链(31~48min)+ async(26~105min); sync 未见分钟级持锁记录。
3. **排队上限已被调用方截断**: news-fetch `timeout=600`, daily-brief 20:40 触发时锁竞争窗口(19:23+)已基本结束。
4. **触发面不同**: sync 是高频小数据同步, async 是全量灾备; async 的长跑根因(step3.5b 3.1 万文件跨境 HEAD)在 sync 中不存在。

**预防性建议**: 若未来给 sync 增加 R2 大上传段或大规模 rsync, 参照方案②两段式结构处理(报告 §5②)。

## 4. 同类错误面清单(§23.2)

| # | 同类位置 | 是否处理 | 理由 |
|---|---|---|---|
| 1 | staticdata_backup_async.sh(整脚本持锁) | **已处理**(方案②) | 长跑主因 |
| 2 | staticdata_sync.sh:61 | 不改 | §3 论证 |
| 3 | pipeline.sh:71(DEPLOY_EACH=1 持锁 deploy) | **已随方案③改 600** | 同模式, 兜底明确 |
| 4 | deploy.sh 主链(锁内 export+R2+git, 31~48min) | 本轮不做 | 属方案①(锁粒度拆分)范畴, 任务明确留待下一批 |
| 5 | intraday_snapshot.sh / kelly_intraday_rerun.sh(`--nb` 非阻塞) | 不涉及 | 非阻塞, 锁在位即跳过不排队 |
| 6 | gold_night.sh(阻塞) | 不涉及 | 02:40 凌晨低竞争 |

## 5. 逐项自测结果

| # | 自测项 | 结果 |
|---|---|---|
| 1 | `bash -n scripts/staticdata_backup_async.sh` | ✅ |
| 2 | 完整流程(段1锁外 rsync+R2 + 段2锁内 git), notify DRY_RUN, 非生产机守卫拦截 git 段(rc=1 跳过 commit=预期) | ✅ 日志见 `[写权限守卫] ✗ 非生产机...` |
| 3 | 预占 `/tmp/trade_backup_r2.lock` → step3.5b 走「已被占用跳过」路径 | ✅ |
| 4 | R2 锁空闲 → with_lock `--nb` 参数经 `bash -c` 正确传递(upload_r2 被真调用, 返回「无大 JSON 需备份」) | ✅ |
| 5 | **预占 `/tmp/trade_deploy.lock` 30s** → 段1 于启动瞬间执行(锁外不等待), 段2 于锁释放后 31s 处执行, git 段 0s 完成 | ✅ **= #149 效果判据的本地镜像** |
| 6 | 方案③: 10 文件改后 `bash -n` 8 shell + `py_compile` index_backfill.py + pipeline.sh | ✅ lint 全过(含全仓 188 .sh + .py) |
| 7 | 改后残留扫描: `--block-timeout 3600` 仅剩 async:216 / sync:61(有意保留, 见 §2) | ✅ |

**测试隔离三件套**: `STATICDATA_REPO=/tmp/test-staticdata-149` + `R2_BACKUP_BUCKET=demo-nowhere-404`(不存在桶, 404 不污染生产)+ `STATICDATA_BACKUP_NOTIFY_DRY_RUN=1`。

**测试事故记录(诚实标注)**: 测试中途一次裸跑脚本漏 env 前缀误触本机真实 `trade-data`(`rsync` 只写备份方向幂等、不改源; git 段被非生产机守卫拦截无新 commit `git -C ... log -1` 仍 `c8a0a46`)。已清理: 误触日志删除 + 心跳文件写回 `fail`(注: 本地测试被打断)。报告复现段包含正确测试命令, 供复核。

## 6. 本机验证不了的部分 + 云上验证命令

本机 mac 非生产机, staticdata 写守卫会拦截 git 段 → **云上 git add/commit/push 完整行为 + 心跳 ok 落盘无法本机复现**。云上验证(全部只读):

```bash
# ① async 分段执行验证: 应看到 段1(锁外 rsync+R2) 与 段2(锁内 git) 两个打点, step3.5b 持独立 R2 锁
ssh -i ~/tdsignal.pem -o BatchMode=yes ubuntu@122.51.111.173 \
  'cd /home/ubuntu/code/trade-data/data/logs && for f in $(ls -t staticdata_backup_async_*.log | head -3); do echo "--- $f"; grep -E "段1|段2|step3.5b|trade_backup_r2|已被占用" $f | head -12; done'

# ② 效果判据: trade_deploy.lock 持锁者不再含 async(段2 git 段秒级, 观察器采样应见空窗)
ssh -i ~/tdsignal.pem -o BatchMode=yes ubuntu@122.51.111.173 \
  'ps aux | grep -E "staticdata_backup_async|with_lock" | grep -v grep; ls -la /tmp/trade_deploy.lock /tmp/trade_backup_r2.lock'

# ③ 验收主判据: 连续 3 交易日 22:35~02:00 写库窗口可达 + 观察器连续采样出现空窗
#    (观察器/写库窗口监控逻辑在云上, 盘后连板写库任务须能拿到锁)

# ④ 排队超时日志确认新护栏(600s): 若 20:05 futures 再排队, 应约 10min 后出现「排队等锁超时」
ssh -i ~/tdsignal.pem -o BatchMode=yes ubuntu@122.51.111.173 \
  'grep -l "排队等锁超时" /home/ubuntu/code/trade-data/data/logs/*_backfill_202610*.log 2>/dev/null'
```

## 7. deploy.sh async 触发逻辑(963-1005)方案②生效后是否需调整

**结论: 本轮不需调整。** 理由:

- 触发语义 = 「deploy 后做一次灾备」, 方案②后 async 的 rsync+R2 段锁外/独立锁, 不再加剧主锁竞争; 即使 `trade_deploy.lock` 被占, 段1 照跑。
- async git 段仍持主锁, 若排队超时(3600)跳过 git → 数据磁盘+R2 留档, 次日幂等补传, 符合灾备语义。
- 可选未来优化(非必需): 触发 async 前先探测 `trade_backup_r2.lock` 空闲才拉起进程, 省去「每次 deploy 都拉起一个可能跳过的进程」; 当前成本可忽略, 不引入改动面。

## 8. 复现段

原始只读调研命令见 `docs/ops/149-deploy-lock-queue-rootcause-20261001.md` §7。本报告新增(方案②改造后本地行为):

```bash
# 本地复现「段1锁外立即执行」+「段2锁释放后执行」(测试隔离三件套)
rm -f /tmp/trade_deploy.lock /tmp/trade_backup_r2.lock
python3 - <<'EOF'
import fcntl, time, sys
f = open('/tmp/trade_deploy.lock','w'); fcntl.flock(f, fcntl.LOCK_EX); time.sleep(30)
EOF
REPO=/tmp/test-repo-149 GIT_REPO=$PWD STATICDATA_REPO=/tmp/test-staticdata-149 \
  PY=/usr/bin/python3 STATICDATA_BACKUP_NOTIFY_DRY_RUN=1 R2_BACKUP_BUCKET=demo-nowhere-404 \
  bash scripts/staticdata_backup_async.sh test-trigger
# 期望: 段1 立即出现(锁外); 段2 在 30s 后锁释放时出现, git 段被非生产机守卫拦截(rc=1, 跳过 commit)

# 本机完整 lint
bash scripts/lint_scripts.sh
```

**修复链说明**: 方案②③上线后需重跑 §6 云上验证命令(尤其判据 ③), 出现空窗 + 写库窗口可达才算根治闭环。
