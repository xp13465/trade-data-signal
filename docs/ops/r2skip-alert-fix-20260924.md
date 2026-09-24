# r2_skip_alert 告警误报修正 + 假成功标记修复(2026-09-24)

## 结论

按分诊报告 `docs/ops/r2skip-alert-triage-20260924.md` 判据①实施:
- **P1(计数语义误配)**:monitor 端 `schedule_monitor.sh` 消费 r2_skip_count 时新增 **last_run 新鲜度闸门**——任务最近运行落在本轮观察窗口(30min)外(即本轮无新运行)时,滞留的 `r2_skip_count>0` **不参与跨轮「连续 N 轮」计数**,直接清零。高频任务(intraday_snapshot/fetch_news)每轮 fresh last_run,连续 N 轮 SEVERE 行为**逐条保留**。阈值数值(3)未动。
- **P2(假成功标记)**:`push_schedule_stats.sh` 上传段改用 `PIPESTATUS[0]` 取 upload_r2 真实退出码 + 合并输出 grep `SKIPPED_LOCKED` 区分三态:跳过(⚠ 已跳过下轮重试,非成功)/ 真成功(✓)/ 真失败(✗ rc≠0 发告警邮件 exit 1)。假成功标记彻底消失。

**base commit(改动前 HEAD)**:`fd036824a`(build(统一bump): main-merge.sh 统一 build_min+bump 版本串)
**feat 分支**:`worktree-agent-a4474317daa5a4a07`

## 改动文件

| 文件 | 位置 | 改了什么 |
|---|---|---|
| `scripts/schedule_monitor.sh` | L398-404 | 新增 `R2_SKIP_OBS_WINDOW = timedelta(minutes=30)` 观察窗口常量 + 说明注释 |
| `scripts/schedule_monitor.sh` | L690-766 | r2_skip 消费块重写:last_run 解析 → 新鲜度判定 → stale 分支清零不计入跨轮 / fresh 分支保留原计数逻辑(SEVERE 触发条件不变) |
| `scripts/push_schedule_stats.sh` | L68-88 | P2-5:捕获合并输出 + `PIPESTATUS[0]` 真实退出码;`grep SKIPPED_LOCKED` 分流 ⚠/✓;rc≠0 走失败告警分支 |
| `docs/ops/scripts/verify_r2skip_fix.py` | 新增 | 验证 harness(同构:OLD 块从 git HEAD 逐字节提取,NEW 块从 worktree 文件逐字节提取,done 后 dedent 包成 consume 函数,杜绝第二份实现漂移 §5.4⑦) |

## 验证对照(实际输出,缺一不可)

### ① 每日一轮单次 skip(overfit_monitor 21:40 撞锁,r2_skip_count=1 滞留,monitor 连续 6 轮观察)
| 轮次 | OLD(改前) | NEW(改后) |
|---|---|---|
| 21:45 | 连续1/3(未达) | 连续1/3(未达) |
| 22:00 | 连续2/3(未达) | 连续2/3(未达) |
| 22:15 | **SEVERE 触发!**(误报) | `[r2-skip-stale]` 清零(最近运行距今>30min,不参与连续计数) |
| 22:30-23:00 | suppress 持续 | 无 |
| 终值 | 计数 key=**6** / SEVERE **1 条(误报)** | 计数 key=**0** / SEVERE **0 条** |

### ② 高频任务连续 skip(intraday_snapshot 每轮 fresh last_run,连续 5 轮)
| 项 | OLD(改前) | NEW(改后) |
|---|---|---|
| 10:30(第 3 轮) | **SEVERE 触发!** | **SEVERE 触发!**(逐条保留) |
| 终值 | SEVERE 1 条 / 计数 5 | SEVERE 1 条 / 计数 5 |

→ 真告警一条没削弱(§14 通知即时性:只修计数语义,不降频/不停后台/不去重真告警)。

### ③ 恢复场景(skip 第 3 轮停止)
OLD/NEW 都清零,计数终值 0,无 SEVERE(无回归)。

### ④ 存量误报过渡(线上 9-24 已挂 overfit_monitor|r2_skip_alert active)
NEW 消费滞留 skip:新 SEVERE 0 条、计数清零后值 0、告警 key 本轮 **seen=False** → 主恢复循环(seen_keys_this_run 缺失判定)将判告警消失自动发恢复邮件,不振荡。与分诊第 3 条一致(次日 21:40 新一轮打点恢复,无需手工)。

### ⑤ P2 三态(沙箱 stub upload_r2 实测)
| 场景 | 输出 | 退出码 |
|---|---|---|
| skip(撞锁) | `⚠ schedule_stats R2 上传锁忙, 本轮跳过(SKIPPED_LOCKED, 下轮重试; 缺口由 deploy 17:50 upload-all-data 兜底), 非上传成功` **无任何 ✓** | 0 |
| 真成功 | `✓ schedule_stats.json R2 上传完成` | 0 |
| 真失败 | `✗ schedule_stats R2 上传失败(rc=1), 发告警邮件` + notify(||true) | 1 |

## 同类错误面清单(§23.2 修 bug 三铁律)

逐项排查「同模式/同组件还被谁用」,结论:

| 排查点 | 结论 |
|---|---|
| `scripts/overfit_monitor.py` L1822-1839 | R2 自传段**已**显式识别 `SKIPPED_LOCKED` 输出哨兵日志(撞锁打点),无假成功标记。不改 |
| `scripts/fetch_news.py` L714-741 | R2 上传 skip 判定**已正确**(skip 走 `已跳过` 分支,不打印成功),与本次 P2 同模式但已收口。不改 |
| `scripts/intraday_snapshot.sh` L145-183 | 上传用 `if !` 无「✓ 上传完成」打印,skip 静默落空——静默≠假成功标记,且该通道高频本就需要静默让位;不打成功标。不改 |
| `scripts/gen_daily_brief.py` L3089-3096 | 不带 `--skip-if-locked`(用 `✗_TIMEOUT` 语义),不存在 SKIPPED_LOCKED 假成功。不改 |
| `scripts/gen_schedule_stats.py` L527-529 | `r2_skip_count` 生成端窗口滞留计数是**数据供给源头**,分诊判据①定案在 **monitor 消费端**修(生成端附 last_run 输出已在,monitor 读它);生成端不改,避免动盘后产物格式 |
| 前端 `static-site/app.js` L32403-32404 | tooltip「R2跳过 N 次」读 r2_skip_count 展示。修后语义仍准确(展示的是最近窗口内跳过次数,不是告警状态);改它需 build_min+bump 前端链,超出本任务范围。不改 |
| 同文件其他 EXTRA_MARKER 消费块 | `schedule_monitor.sh` L121-144 `EXTRA_MARKER_SCANS` 已用 `round_start_re` 轮次作用域(非跨轮累计),与本 P1 不属同类病。不改 |

结论:**同类假成功/跨轮累计错误面全部收口或天然免疫,无残留补丁**。

## 举一反三清单(§23.3)

- 同数据源(r2_skip_count):消费端只有 schedule_monitor 一处(已修);展示端 app.js tooltip(语义仍准,不动)。
- 同组件(上传锁路径):`--skip-if-locked` 通道消费方 overfit_monitor/fetch_news/intraday_snapshot/push_schedule_stats 全查过(见上表),仅 push_schedule_stats 有假成功(P2 已修)。
- 相关展示位:schedule_stats.json 由 deploy 17:50 upload-all-data 兜底上传,前端「执行统计」读 R2;本次改动不触数据文件,无一致性影响。

## §14 确认

- 本次是**告警语义修正(去重/聚合维度)+ 打印标记修正**,非降频/非后台暂停;高频任务 SEVERE 行为逐条保留(见验证②)。
- 无任何真告警被静默。存量误报告警走恢复循环自动发恢复邮件,不是静默吞掉。
- 未跑 deploy.sh / 未 push main / 未动生产 R2 / 未动云上文件。只 commit+push feat 分支。
- push 时点 23:17(盘后禁区时点 15:35/16:00/17:50/20:35/22:00 全避开,安全窗口 23:00 后)。

## 可选兜底判据(未实施,建议后续评估)

分诊判据②「次日 deploy 后 R2 generated_at 仍非最新 → SEVERE」**未实施**,原因:
- 正确实现需 curl R2 文件 `generated_at` 比对(需引入网络依赖+脆弱);
- 低频任务「真断了」已有覆盖:overfit_monitor 本身在 TASKS 表(21:40 定时),其 漏跑/exit-failure/DUR 超时 均有独立告警,不会因 r2_skip 静默;
- 残余盲区 =「任务跑成功但 R2 自传永远 skip 且 deploy 链也坏」,属二阶故障(deploy 链坏会触自己那套告警)。
建议:若后续想补,单独排期做 R2 curl 判据,不在本次改动内混入。

## 复现段(§23.5 四件套)

```
# 在 worktree 根(agent-a4474317daa5a4a07)运行 P1 验证:
python3 docs/ops/scripts/verify_r2skip_fix.py
# 输出:每日单次skip OLD=SEVERE×1(误报) vs NEW=0条;高频连续skip 改前后都 SEVERE×1;
#        恢复清零;存量误报过渡 0新SEVERE+计数0+key未seen

# P2 三态沙箱(临时目录,不影响仓库):
#   构造 /tmp/r2test/scripts/upload_r2.py stub(按 R2_STUB_MODE=skip/ok/fail 返回)后:
#   REPO=/tmp/r2test bash scripts/push_schedule_stats.sh
#   期望:skip→⚠无✓, ok→✓, fail→✗ rc=1
```

## §23.4 待办对账

`docs/pending-features-index.md` 扫描:监控告警模块无在案冲突项——#27/#30(R2 上传失败/审计)已废弃移入 abandoned-features.md;#110(update_all 静态备份积压)与 #111(旧 fund_nav 清理)主题与本任务无关,不冲突。无同模块多任务占用。
