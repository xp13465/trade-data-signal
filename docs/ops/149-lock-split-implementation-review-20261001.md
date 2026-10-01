# #149 `trade_deploy.lock` 职责错位根治 — 方案②③独立审查报告

- **日期**: 2026-10-01(reviewer 独立审查,全只读;云上 ssh 只读)
- **审查对象**: 分支 `feat/149-lock-split-20261001` HEAD `d8d9ac255`(commit 链 `564558bbb` 方案② → `8cae67c94` 方案③ → `d8d9ac255` 报告),worktree `/Users/linhuichen/code/trade/.claude/worktrees/agent-a9f8485f7ad73a1b7`,base=main@`4ff477fb1`
- **改动分级**: C 级(动 deploy 主链/灾备链的进程锁结构,merge 前必过独立 review)
- **结论**: **PASS-with-caveat**(4 条 caveat + 2 处报告说法失真 + 1 处台账不同步,均非阻断;建议 merge 前按 §6/§9 处理)
- **验收判据(#149)**: `trade_deploy.lock` 持锁者不再出现 async 长跑段 —— 本地隔离实测证实行为正确;生产生效需云上按 §7 复验

---

## 1. ①测试事故取证(独立取证,不采信自述)

**结论: 实施 agent 自述基本属实 —— 误触确实发生、已清理、无真实副作用;残留 3 类无害痕迹 + 1 个无法 100% 排除的 R2 HEAD 接触点(幂等)。**

### 证据(全部独立命令取证)

| # | 检查项 | 取证结果 |
|---|---|---|
| 1 | 误触发生确认 | staticdata 仓 config/ 今日 20:50 mtime 共 41 文件 = config/launchd 40 plist + wrangler.jsonc,即 step2 config 段(`sed 's|/Users/linhuichen|/Users/USER|g'` 脱敏模板)执行痕迹 —— 误触确实发生,非编造 |
| 2 | rsync 幂等(不改源) | staticdata 仓 data/、db/ 无今日 mtime;rsync 参数 `rsync -a` 无 `--delete`,方向 = trade-data → staticdata(备份方向不改源);内容一致跳过 → 数据文件零损坏 |
| 3 | git 无新 commit | staticdata 仓 reflog 仅 clone `c8a0a46`(09-26),今日无 commit;无 `.git/index.lock` 残留 → git 段被非生产机守卫拦截属实 |
| 4 | 无残留日志 | trade-data/data/logs 今日无 staticdata 相关日志 → 误触日志已删,清理属实 |
| 5 | 清理动作留痕 | 心跳文件写回 fail + note「本地测试误触打断(2026-10-01 20:50)」—— note 字段为手工写(`_hb_write` 不写 note),证明是清理写入;fail 不在 C3 白名单(ok/skip_oversize),不触发告警,无害 |
| 6 | 残留物 | /tmp/trade_deploy.lock + /tmp/trade_backup_r2.lock mtime 20:52,0 字节空文件,flock 已释放无持有者,下次 flock 直接可用(锁机制常态产物) |

### caveat

- **C-1(无法 100% 排除)**: 本机主仓 `.env` 含生产 R2 凭证;误触跑的是旧版(main 版)async,若跑到 step3.5b,`upload_r2.py` load_env 会加载主仓 `.env` → 可能对生产桶发起 HEAD 比对(幂等,无 PUT 无内容污染)。心跳 note 表明未跑完、大概率未到 step3.5b,但无法证实零 HEAD 请求。影响面 = R2 侧只读请求级,风险极低。
- **C-2**: 心跳被清理为 fail(非标准状态),下次生产 deploy async 会覆盖,无害。
- **C-3**: staticdata 仓 config/ 40 plist mtime 变化(内容为脱敏一致模板,无污染)。

---

## 2. 方案②(async 两段式 exec 重入)审查

**结论: PASS。结构正确、逻辑自洽,隔离实测三场景全部符合预期;含 1 条心跳 caveat(C-4)。**

### 逐项核验

| 检查项 | 结果 | 证据 |
|---|---|---|
| 段1 锁外执行 | ✅ 实测 | 隔离三件套(REPO=/tmp 克隆 + STATICDATA_REPO=/tmp + R2_BACKUP_BUCKET=demo-nowhere-404 + notify DRY_RUN),锁预占 30s 下「段1(锁外 rsync+R2)开始 21:29:35」启动瞬间出现,「段2 开始 21:29:49」锁释放后出现 |
| 段2 持主锁 | ✅ 实测 | 段2 仅在 `exec with_lock.py --block-timeout 3600` 重入后出现;预占主锁场景段2 延迟到释放后 |
| step3.5b 独立 R2 锁非阻塞 | ✅ 实测 | 预占 `/tmp/trade_backup_r2.lock` → 输出「跳过(trade_backup_r2.lock 被占, 非阻塞不排队)」;空闲 → 「✓」 |
| 三态判定(grep "已被占用") | ✅ | `upload_r2.py` 全文无「已被占用」字样 → 判定无歧义源;`with_lock.py --nb` 被占输出固定格式(L128);实测两路径均正确 |
| bash -c 参数传递 | ✅ | `bash -c '...' _ "$STATICDATA_REPO" "$GIT_REPO" "$PY" "$GIT_REPO/scripts/upload_r2.py"` → `$0=_(占位) $1=REPO $2=GIT $3=PY $4=upload_r2.py`,命令 = `$3 $4 upload-large-json`,拼装正确 |
| 跨 exec 状态传递 | ✅ | LOG(`STATICDATA_BACKUP_LOG`) / `STATICDATA_BACKUP_ASYNC_R2_DONE=1` / `STATICDATA_BACKUP_ASYNC_R2_FAIL` / `STATICDATA_BACKUP_ASYNC_HB_START` 均 export(L213-215);段2 恢复 `STATICDATA_FAIL`、重置 `_OVERSIZE`/`_SKIP_NONPROD`(L222-225),无变量丢失、无重复执行 |
| 无 exec 死循环 | ✅ | 段2 无二次 exec;`R2_DONE=1` 时跳过段1 if 块直入段2 |
| set 组合 | ✅ | `set -u` + `set -o pipefail`,无 `set -e`(L44 注释明示「每步显式判退出码」),step3.5b 的 grep 无匹配走 else 分支,不中止流程 |
| 仓库缺失早退 | ✅ | 段1 if 块内早退 exit 0 且不写心跳(留上次 ok 心跳自然变旧触发 C3 停摆告警,与旧版契约一致) |

### caveat(方案②)

- **C-4(心跳状态机缺口)**: 改造后 `_hb_write "running"` 提前到段1(锁外)。若段2 `with_lock` 排队 3600s 超时优雅跳过(exit 0),脚本结束但心跳停在 **running**。C3(停摆检查)只看 ok/skip_oversize 新鲜度(running 不在白名单)→ C3 此时不告警。兜底 = `with_lock` 排队超时自身有 notify(warning tier,dedup 21600s),非静默。判断: 非阻断(有兜底),但心跳状态机与 C3 契约出现缺口,建议方案①实施时同步处理(如段2 入口再写一次 running 或 C3 增加 running 超时判定)。

---

## 3. 方案③(9 片调用方兜底点名 + 1 处举一反三)

**结论: PASS(兜底路径全部成立,无漏改、无残留),2 处报告说法失真(结论对、说法错,非阻断)。**

### 独立核实

| # | 调用方 | 核实结果 |
|---|---|---|
| 1 | update_all.sh:146 | ✅ 已改 600;兜底 = 次日 17:50 全量重跑成立。**失真项**: 报告称「17:50 锁空」—— 根因报告 §2 实测 10-01 17:17:48→17:50:37 async(旧版整脚本持锁)在跑,17:50 实际排队 ~37s 后拿到(结论「不触发超时」对,「锁空」错);改造后 async 段1 锁外,届时锁空成立,报告未区分时态 |
| 2 | futures_backfill.sh:97 | ✅ 已改 600;次日重跑兜底成立 |
| 3 | etf_national_team_backfill.sh:123 | ✅ 已改 600 |
| 4 | lhb_backfill.sh:107 | ✅ 已改 600;交易所数据持久 |
| 5 | rzhb_backfill.sh:134 | ✅ 已改 600;08:00/19:15 双机会 |
| 6 | public_fund_daily.sh:82 | ✅ 已改 600;基金净值 T+1 公布,重跑成立 |
| 7 | public_fund_full.sh:87 | ✅ 已改 600 |
| 8 | public_fund_quarterly.sh:90 | ✅ 已改 600。**失真项**: 报告称「凌晨锁空闲」—— 根因 §2 实测 10-01 02:35:40→03:02:27 async 在跑,03:00 实际排队 ~147s(结论「不触发」对,「锁空闲」错) |
| 9 | index_backfill.py | ✅ 实际仅 1 处 with_lock 调用(1139 行,已改 600);根因报告 §1「1125,1140 两处」为行号误差(1125 是注释块,非漏改)。全仓 grep `block-timeout 3600` 仅剩 async:216 / sync:61 两处有意保留,无残留 |
| 10 | pipeline.sh:71(DEPLOY_EACH=1,举一反三) | ✅ 已改 600;update_all 主链每日兜底成立,DEPLOY_EACH=1 为手动场景可重跑 |
| 保留 3600 ×2 | staticdata_sync.sh:61 / async:216 | ✅ 理由成立: `fetch_news.py:744-746` 独立核到 `subprocess.run([... staticdata_sync.sh \; "news-fetch" ...], timeout=600, capture_output=True)`(L744-745 上下文+`except subprocess.TimeoutExpired` L750)→ news-fetch 实际排队上限已 ≈600s;async 段2 由 deploy 末尾触发、锁刚释放大概率立即拿到,且段2 git 秒级拿到即释放,保留 3600 不增加跳过频率 |

### caveat(方案③)

- **C-5(严重性注意)**: update_all 主链改 600 后,「排队 10min 拿不到 = 跳过当天主链 deploy = 当天全站数据缺一天」(全表里唯一跳过即全站级缺数据的调用方,其余为单类 backfill 次日可追)。改造后 async 不再长持锁,超 600 概率大幅下降,可接受;但方案①实施前若出现接力长持锁,17:50 update_all 有排队超时风险(兜底质量低),建议方案①施工前排期观察此点。

---

## 4. §23.3 举一反三: staticdata_sync.sh 不改理由核

**结论: 理由成立(属实,非偷懒),另补 1 条报告未覆盖的并发风险。**

- 持锁内容核 = 小 rsync(本地跨目录增量)+ git,无 `upload_r2` 全量比对段(全仓 grep 证实,与 async 的两字段不同);长跑者实测 = deploy 主链(31~48min)+ async(26~105min),sync 无分钟级持锁记录;触发面不同。4 点理由全部属实。
- **补 Risk(缺陷维度,报告未覆盖)**: 方案②后 async 段1(锁外 rsync 写 staticdata 仓 data/)与 staticdata_sync(持锁 `git add -A` 读同一 staticdata 仓)/async 段2 并发 → 理论上可 stage 到 rsync 半截文件 → 灾备 2 层短期坏档。概率低(rsync 多数文件跳过、写窗口秒级,news-fetch 30min 触发与盘后 async 密集触发存在重叠窗口但窗口内对齐概率低),影响可自愈(次日 deploy async 全量 rsync 幂等覆盖),非生产数据。**不阻断**,但方案①拆锁时应显式处理(如 async 段1 加 staticdata 仓专用写锁 --nb,或 sync git add 与 rsync 协同)。

---

## 5. §15 回归影响面清单(改 10 脚本)

| 链路 | 影响面 | 判定 |
|---|---|---|
| deploy 主链调度(16:30/17:50/18:30/19:15/20:05/20:07/21:00/22:00/03:00) | 9 调用方排队超时护栏 3600→600(更快优雅跳过);deploy.sh 本身未改(L963-1005 async 触发逻辑核过,方案②后语义 = 段1 锁外照跑,无需调整的结论成立) | ✅ 仅护栏收紧,行为一致 |
| 灾备链(async 灾备 + sync) | async 两段式(§2);sync 未改;灾备 1/2 层(磁盘/git)留档语义不变,3/4 层(R2)独立锁 + --nb 跳过,次日幂等补传 | ✅ |
| update_all 并行流水线 | 仅 :146 持锁调用超时;流水线结构未动 | ✅ |
| pipeline.sh(DEPLOY_EACH=1) | 600s 排队上限;手动场景可重跑 | ✅ |
| 数据产物完整性 | `check_data_integrity.py` 本机跑通;告警项(overview date=20260924 / sentiment 卡不一致 / fund_score 09-13 / ad_line 09-11 / a_stock 09-11 等)= 本机 mac 静态产物陈旧(本机不跑定时任务,09-24/09-11 是环境常态),**非本次改动引入,与本改动无关**;生产侧验证见 §7 | ✅ 结构通过,本机旧数据告警与改动无因果 |

---

## 6. §23.12-1 台账一致性 + §23.5 报告四件套 + 分支状态

- **台账不一致(caveat,需处理)**: `pending-features-index.md` L240 #149 状态仍 = 「根因已查明」(researcher 调研后状态),**未更新为「方案②③已实施待 review」**。§23.12-1(状态单一事实源)要求状态列与实际一致 —— 建议 merge 前由实施 agent 或主控在本次 commit 中更新(与 #140/#134 等同一表内维护)。
- **§23.5 四件套**: ✅ 报告本体(`docs/ops/149-lock-split-implementation-20261001.md`)+ 复现段(§8 隔离三件套命令)+ 云上验证命令(§6 4 条)+ 配套 commit(`d8d9ac255`)齐全。
- **分支状态**: 分支基于 main@`4ff477fb1`,落后 main 约 8 commit(已合 main 的 holiday-housekeeping / a1593f5b / fapi 修复 / 告警降噪等分支内容未含)。merge 走 `main-merge.sh` 统一入口处理 base 新鲜;diff 核: main 领先改动在 docs/fapi_fallback.py/schedule_monitor.sh 等,与本次改动文件(10 个 timeout + async)无重叠,冲突风险低。

---

## 7. 云上验证命令核(§6) + 云上补验项

报告 §6 4 条命令**全部可行且必要**:

1. async 日志段1/段2 打点检查 —— 命令正确(新代码部署后日志才有段打点,对照基线 = 旧日志无段字样)
2. `ps aux` async/with_lock + 两锁文件状态 —— ✅
3. 观察器空窗判据(验收主判据,连续 3 交易日) —— ✅
4. 600s 排队超时日志确认 —— ✅

**云上补验项(报告未列)**:

- **A. 三态判定落盘验证**: `grep "已被占用" /home/ubuntu/code/trade-data/data/logs/staticdata_backup_async_202610*.log` —— 确认 step3.5b 跳过路径在生产真实日志出现(本机已实测,云上补生产形态确认)
- **B. 心跳 C3 连续性**: 新代码上线后确认心跳文件 `ok` 仍按日新鲜(C3 白名单),防 C-4 场景在真实盘后触发
- **C. 双锁文件并存确认**: `ls -la /tmp/trade_deploy.lock /tmp/trade_backup_r2.lock` 两锁各自持有者正常(段2 只持 trade_deploy.lock,step3.5b 只持 trade_backup_r2.lock)
- **D. 静态数据一致性(§22)**: 灾备 2 层 staticdata 仓在 async 段2 正常 commit 后,`git log -1` 与磁盘 data/ 文件 mtime 新鲜度一致(确认段1 写入与段2 commit 无撕裂)

---

## 8. 复现段

原始调研命令见 `docs/ops/149-deploy-lock-queue-rootcause-20261001.md` §7。本报告新增(reviewer 独立实测):

```bash
# ① 两段 exec 重入 + 段2 持主锁实证(隔离三件套)
python3 - <<'EOF'
import fcntl, time
f = open('/tmp/trade_deploy.lock','w'); fcntl.flock(f, fcntl.LOCK_EX); time.sleep(30)
EOF
REPO=/tmp/test-rev149-repo GIT_REPO=/Users/linhuichen/code/trade \
  STATICDATA_REPO=/tmp/test-rev149-staticdata R2_BACKUP_BUCKET=demo-nowhere-404 \
  PY=/usr/bin/python3 STATICDATA_BACKUP_NOTIFY_DRY_RUN=1 \
  bash /Users/linhuichen/code/trade/.claude/worktrees/agent-a9f8485f7ad73a1b7/scripts/staticdata_backup_async.sh test-trigger
# 实测输出: 段1 21:29:35(锁外立即) → 段2 21:29:49(锁释放后),守卫拦截非生产机 git 段 rc=1=预期

# ② 三态判定实证(R2 锁预占 → step3.5b 跳过分支)
# 预占 /tmp/trade_backup_r2.lock 后重跑 ①, 段1 输出「step3.5b ... 跳过(trade_backup_r2.lock 被占...)」

# ③ 数据完整性校验(结构通过;本机旧数据告警 = 环境常态非本次引入)
python3 scripts/check_data_integrity.py

# ④ 全仓 3600 残留扫描(应仅剩 async:216 / sync:61)
grep -rn "block-timeout 3600" scripts/ app/ | grep -v ".git/"
```

---

## 9. 结论

**PASS-with-caveat** —— merge 前建议处理(不阻断,但需留痕):

1. **台账 #149 状态列更新**为「方案②③已实施待 review/已实施」(§23.12-1,当前仍「根因已查明」,与实际不符)
2. **报告 §2 表 2 处措辞校正**: update_all「17:50 锁空」、quarterly「凌晨锁空闲」与根因实测数据不符(实为排队 ~37s/~147s 后拿到,结论「不触发超时」成立),建议改为「排队 <600s 可拿到」表述
3. **caveat 跟踪**: C-4(心跳 running 残留 vs C3 白名单)与 C-5(update_all 主链跳过=全站缺一天)列入方案①(git 锁拆分)后续施工的显式处理项;C-1(误触 R2 HEAD 接触点)已核幂等,无需动作,留档即可

**上线后验证**: 云上新代码部署后按 §7 命令 A~D 补验,主判据 = 连续 3 交易日 22:35~02:00 写库窗口可达 + 观察器采样出现空窗(验收判据 #149)。
