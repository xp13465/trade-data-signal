# staticdata 备份异步化独立审查报告(2026-09-25)

> reviewer 独立审查(只读)。改动:feat/staticdata-backup-async @ cddaa3758,基线 main 729356692。
> 审查口径:风险 1-7 逐条 + 锁语义数字 + 举一反三复核 + 静默失败专查(§10.4)。

## 结论:**带条件 PASS**

4 个必改项(C-1 触发失败告警 / C-2 git add 失败静默 / C-3 备份缺失检测上报 / C-4 手动补跑提示补全)修掉或明确拍板后放行。核心评估:
- 新脚本逻辑与原 deploy.sh 段一一对应搬入,无逻辑丢失(含云上回退 L40-46 逐字同款)
- 云上触发路径 **实测可用**:sudo -n OK / systemd-run 在 /usr/bin / $REPO/scripts 是 $GIT_REPO/scripts 的 symlink(两路径等价,fund-nav 先例同机制已在生产跑 2 天)
- 失败告警链完整(rsync/commit/push/超时/lock 超时全告警,dedup fail-open 6h 内不静默)
- **锁语义:总锁占用时长与改前基本相等(见 C-7 数字),调用方等待不变长,回退可接受**
- 静默失败专查命中 2 条(C-1/C-2),是唯一"FAIL"级别位点

## 风险 1:备份会不会静默丢失?
| 场景 | 路径 | 结论 |
|---|---|---|
| async 触发起不来 | deploy.sh `sudo -n systemd-run ... || echo ⚠` | **失败只打印 ⚠ 到 deploy 日志,不走 notify,不 fallback nohup**。deploy 日志的 ⚠ 行不在 schedule_monitor 的 scan_log_anomaly 模式(Traceback/FATAL)里 → **静默**。当前云上 sudo -n OK + systemd-run 可用(实测),触发失败概率低;但一旦发生(权限被改/unit 名冲突)备份整日丢失无人知。**P1** |
| 跑一半被杀(重启/OOM) | 无恢复/补跑机制 | 数据层:次日 deploy 触发 async 时 rsync 全量比对比对追平,**数据不丢**;但 git commit 历史缺档,且 db/ rsync 留档缺口无检测(news-fetch 的 30min 同步只覆盖 data/ 文件级,不覆盖 db/) → 见 C-3**
| 拿锁超时 | with_lock --block-timeout 3600 | 告警 + exit 0,不静默 ✓;超时需 deploy 持锁 1h,9-18 事故同场景才会出现 |
| 云上触发方式验证 | systemd-run 分支 `sudo -n true` 实测 OK(2026-09-25),fund-nav 同机制已生产跑通(9-23/9-24) | **云上能起来 ✓**(本次 merge 后首次真跑仍需盯 17:50/20:07 两轮) |
| 备份缺失检测 | schedule_monitor 只检查 fetch_news 的 staticdata 同步超时(gen_schedule_stats.py L206/L608),不检查备份 commit 新鲜度/db/ 留档新鲜度 | **不存在专门检测** → 见 C-3 |

门限判定:rsync DB/JSON 失败、commit/push 失败、push 超时 900s 全部 → STATICDATA_FAIL=1 → notify --severe ✓
性能兜底:变更 >5000 文件或 >300MB → rsync 磁盘留档 + 告警跳过 commit(下日 rsync 全量追平,**数据不丢,仅 git 历史缺一档**)✓

## 风险 2:锁语义变化(数字结论)
改造前后锁占用对比(基于 9-24 实测 deploy 段 41.5min,staticdata 段 ~35min → D≈7min B≈35min;9-25 05:00 D≈1min B≈22min):
- 改前一个 deploy 调用方:锁占用 = D + B(41.5min)
- 改后:锁占用 = D(6-7min)+ async 接棒 B(35min)= **总窗口相同,中间仅秒级空隙**
- **对后续调用方(etf/futures/public_fund/rzhb 等,全部 `with_lock --block-timeout 3600` 同锁):改前等"前一 deploy 的 D+B",改后等"前一 async 的 B",等待时长 ≈ 不变**。唯一差异:改后等待的是 B 而非 D+B,D 缩掉了 → **等待时间相等或略缩短**(临界点:紧邻 deploy 的调用方)。

关键时点逐条核实(云上 systemctl list-timers 实测):
- **20:05 futures + 20:07 etf async 排队**:存在(async A ≈20:15-20:50, etf deploy 等锁 → async B ≈20:57-21:30)。**改前两 deploy 同样排队(D+B 链)** → 与现状相当 ✓
- **20:40 daily_brief staticdata_sync 等锁**:async A 20:15-20:50 持锁,daily_brief 20:40 触发 → **最坏等 10min**(20:50 释放);若 20:45 etf deploy 抢先拿锁,则先等 D≈7min 再等 async B 27min → 最坏 ~45min,仍在 3600s 护栏内,不告警超时。实施报告"5-10min"偏乐观,但不算错。
- **17:50 update_all async 不撞 20:05**:最坏积压 70min(9-22)跑到 ~19:35,**19:15 rzhb-backfill 会被挡 ~15-20min**(rzhb L134 同锁 block-timeout 模式)**——与改前等价**(改前 9-22 17:50 deploy 积压持锁到 19:35 同样挡 rzhb)。✓
- **backup_db 21:00 持不持 deploy 锁**:云上 backup_db.sh 无 with_lock/trade_deploy.lock 引用 → **不持锁,实施报告正确** ✓
- **22:00 public-fund-full**:最坏 async B 21:30-22:05 → 等 5min,护栏内 ✓
- 结论:锁总占用 ≈ 与改前相同,无新增等待类别;唯一新特征是 async 持锁时点后移。**回退可接受**。

## 风险 3:兜底阈值
- 阈值依据:正常日 58~487 vs 积压 25789,5000 间隔 10x/1/5 清晰 ✓;300MB > 正常 ≥> 9-22 的 165MB 不误触发 ✓
- 字节口径:`git add -A` 后 `diff --cached --name-only` 逐个 `wc -c` 累加(变更文件当前全文件大小,保守计,宁高勿低)→ 正确;deleted 文件 `[ -f ]` 保护 sz=0 ✓;.gitignore 排除文件不进 cached diff 不计字节 ✓
- 边界:正好 5000 文件 → 不短路,走 wc 路径(多 5k 次 wc ~数秒,无害);正好 300MB → `-gt` 不触发,正常 commit(阈值语义合理)✓
- 跳过 commit 后次日追平:rsync 全量比对(源 static-site/data + 源 data/*.db),次日 commit 会纳入前日遗漏,数据不丢 ✓
- 跳过后告警文案:含跳过原因(文件数/字数)+ 数据留档位置 + 次日追平说明 + 连续触发评估建议 ✓

## 风险 4:云上路径回退
- 回退逻辑(L40-46)与原 deploy.sh L951-957 **逐字同款**,与 staticdata_sync.sh L29-34 同款 ✓
- 云上实测:GIT_REPO=/home/ubuntu/code/trade-data-signal,trade-data-signal-staticdata/.git 存在 → 回退路径正确 ✓
- STATICDATA_REPO 默认值(/Users/...trade-data-signal-staticdata)在云上不存在 → 必然走回退 ✓;**回退条件 GIT_REPO 已由 systemd-run --setenv 传入** ✓
- 两个都不存在边界:`[ ! -d "$STATICDATA_REPO/.git" ]` → echo ⚠ + exit 0 **无告警**(原 deploy.sh 同款行为,pre-existing 搬入);云上实测二仓都在,概率极低。可选修:该分支也 notify。

## 风险 5:deploy.sh 主链不阻塞
- 触发块:systemd-run sync 调用 `| tee -a "$LOG"`,等 systemd-run 返回(秒级)后立即继续 → **fire-and-forget,不阻塞** ✓
- `$NAME`(L38)/`$LOG`(L37)/`$REPO`(L24)/`$GIT_REPO`(L25)均在头部定义,触发块引用安全 ✓
- deploy.sh 无 set -e(L17 注释),`sudo -n systemd-run ... || echo` 失败不传染主链 ✓;nohup `&` 不阻塞 ✓
- 顺带修复:feat 分支里 `grep STATICDATA scripts/deploy.sh` = 0(实测),无双跑 ✓

## 风险 6:告警路径
- dedup-window:fail=3600s/oversize=21600s → **每天多次失败(16:30/17:50/20:05/22:00 间隔>1h)会各发一封,连续多日失败隔天也发,不构成黑洞** ✓
- dedup 实现 fail-open 且"发送成功才更新 last_alerted"(notify.py L1230)✓
- --severe:写 data/alerts/latest.md(L28-31),latest.md 由 schedule_monitor 汇总 → 云上 latest.md 实测含 severe 告警条目 ✓
- 告警文案含失败动作/日志路径/补跑建议 ✓

## 风险 7:测试隔离
- feat commit 只 3 文件(deploy.sh / 新脚本 / 落档),无额外痕迹 ✓
- /tmp/staticdata-async-test 残留(临时仓库 6 个目录,全在 /tmp),未碰生产 staticdata ✓
- 云上 staticdata 仓库最近 commit 均为 news-fetch(13:01/12:45/12:01),无测试写入 ✓
- 主仓库/trade 无异常脏文件 ✓

## 按严重度排序的发现
1. **C-1(P1)触发失败静默**:deploy.sh `sudo -n systemd-run ... || echo ⚠` 失败只打日志,**不 notify 告警,也不 fallback nohup**。导致备份整日静默丢失。修:失败分支追加 notify --severe(或 fallback nohup)。复现:云上 `sudo -n systemd-run --unit=staticdata-backup-test-$(date +%H%M%S) --uid=1000 --gid=1001 true` 或人为让 systemd-run 失败,观察 deploy 日志仅 ⚠ 行。
2. **C-2(P1 静默失败专查命中)git add -A 失败被吞**:`git add -A 2>&1 | tee -a "$LOG" || true`,add 失败(权限/仓库损坏)被 `|| true` 吞 → 后续 `diff --cached --quiet` 空 → "✓ 无新变更跳过 commit",**看似正常实际 git 历史缺口,无告警**。修:add 失败置 STATICDATA_FAIL 或检测 add 退出码。复现:`chmod 500 $STATICDATA_REPO/.git` 后跑脚本,观察无告警退出 0。
3. **C-3(P1 拍板项)备份缺失检测不存在**:schedule_monitor/gen_schedule_stats 只监控 news-fetch 通道的同步超时,不检查备份 commit 新鲜度或 db/ 留档新鲜度。async 连续多日整体没跑(触发静默失败/被杀)时无人知道。建议:schedule_monitor 加"staticdata 仓库最新 commit 时长"检查(或更新 gen_schedule_stats)。**主控拍板要不要加**。
4. **C-4(P2)手动补跑提示缺 REPO env**:deploy.sh 失败提示 `bash $GIT_REPO/scripts/staticdata_backup_async.sh $NAME` 在云上手跑时 REPO 未设 → 脚本默认 /Users/.../trade-data(云上不存在)→ PY 解析失败直接崩。修:提示加 `REPO=/home/ubuntu/code/trade-data GIT_REPO=...` 前缀。
5. **C-5(P2,pre-existing 搬入)回退失败两仓都不存在时静默 exit 0**(原 deploy.sh 同款行为,云上实测二仓都在,概率极低;可选加 notify)。
6. **C-6(P2 边界)git add -A 无 --delete 的 db/ 目录残留**:pre-existing 行为,deploy 侧删除的 *.db 在 staticdata/db/ 永久残留,不进 git。不影响功能。
7. **C-7(信息)22:00 public-fund-full 最坏等 5min**:改后 async B 最坏 22:05 释放,等锁 5min 在护栏内。可接受。

## 举一反三复核(§23.3)
1. staticdata_sync.sh 独立生成器链路,未改,与 async 同锁串行零破坏 ✓;与 async 非重复实现(它走 files 模式/alldata,async 走全量)✓
2. deploy.sh 其他阻塞同类项:fund-nav 已拆(4fdb52d88 实证生产跑通)/ R2 upload-data-large+verify-r2 后续候选 / export 类分钟级不值得 → 与调研报告一致 ✓
3. **staticdata 读写方 8 个清单复核(全仓 grep trade-data-signal-staticdata / staticdata_sync)**:deploy.sh(现仅触发)/ ×新脚本 / staticdata_sync.sh / intraday_snapshot.sh(NONBLOCK)✓ / gen_daily_brief.py(files 模式)✓ / fetch_news.py L744(阻塞模式)✓ / gen_schedule_stats.py(只读监控)✓ / pickup_repo.py / staticdata 仓库内 fetch_data.sh+gen_data_manifest.py(消费)✓。**清单无漏**。另确认 intraday_snapshot.sh 不调 deploy ✓。
4. §21 算法公示:纯运维备份链路,不动算法/前端,无需同步公示 ✓

## 处置建议
- merge 前:修 C-1、C-2(小改:失败分支补 notify / add 失败置 fail);C-4 提示补 env(可选)
- merge 后首日盯 17:50 update_all(触发+async 开跑)+ 20:07 etf(排队)+ 次日晨核 staticdata 仓库 commit 含 [all]
- C-3 备份缺失检测:主控拍板是否加监控(建议加,防静默黑洞)

## 复现段
```
# C-1 触发失败静默:
# 在云上(只读验证,勿真发):
sudo -n systemd-run --unit=staticdata-backup-test --uid=1000 --gid=1001 /bin/true; echo rc=$?
# 观察 deploy.sh 触发块失败时仅 echo ⚠(无 notify)
# C-2 add 失败吞掉:
chmod 500 /tmp/staticdata-async-test/staticdata/.git && STATICDATA_REPO=/tmp/... bash scripts/staticdata_backup_async.sh test → 观察"无新变更"无告警;chmod 755 恢复
# 锁语义数字依据:
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'systemctl list-timers | grep trade'; grep -n block-timeout /home/ubuntu/code/trade-data/scripts/{update_all,futures_backfill,etf_national_team_backfill,rzhb_backfill}.sh
```

## 整改复验(b13c7853d) · 静态层

> 作用域:纯静态复核(读代码 + 轻量只读命令 + bash -n),未跑任何测试脚本、未建临时仓库、未动生产路径。动态端到端(改1 四环境 PATH shim、C-2 chmod500 .git 注入、C-3 超36h/未超/fail&running/suppress+恢复、心跳文件真实写入与 monitor 读取闭环)由 tester 独立执行,本层不含。
> 环境说明:本机 macOS 无 `timeout`/`gtimeout`,git 只读命令均本地秒级完成故直接执行;bash -n 因 `git show | bash -n` 管道被 worktree 沙箱拒绝,改 `git show b13c7853d:<f> > /tmp/sdreview-<f>.sh && bash -n <tmp>` 完成。

| # | 复核项 | 结论 | 证据(命令 + 关键输出) |
|---|---|---|---|
| 1 | C-1 PIPESTATUS 紧邻性 | **PASS** | b13c7853d 版 deploy.sh L964 管道 → L965 纯注释 → L966 `_SDRUN_RC="${PIPESTATUS[0]:-0}"`;`git show b13c7853d:scripts/deploy.sh | awk NR 960-966` 可见中间仅注释无命令,注释不重置 PIPESTATUS |
| 2 | C-1 两级分支自洽 | **PASS** | L960 `if command -v systemd-run && sudo -n true`;else L983 `if [ -d /run/systemd/system ]` → L984-988 alert-only(无 nohup);L989 else → L991 `nohup bash ... >>"$LOG" 2>&1 &` 仅 echo 不发告警。云上 sudo 不可用但 systemd 在跑 → 正确落 alert-only;本机 mac 无 /run/systemd/system → 正确落 nohup。方向未写反 |
| 3 | C-1 语法 | **PASS** | `bash -n` 三脚本(deploy.sh / staticdata_backup_async.sh / schedule_monitor.sh)均无输出,`&& echo "SYNTAX OK"` 三行全打印 |
| 4 | C-4 补跑提示 | **PASS** | L971 / L984 echo 提示串均含 `REPO=$REPO GIT_REPO=$GIT_REPO bash $GIT_REPO/scripts/staticdata_backup_async.sh $NAME`,云上可整段粘贴执行 |
| 5 | C-5 仓库缺失降级 | **PASS** | async L94-104:notify 不带 `--severe`(仅 `--from-prefix "[通知]"`)、`--dedup-key staticdata_backup_repo_missing --dedup-window 21600`、echo 明文列出「候选1 ${STATICDATA_REPO:-无} / 候选2 ${GIT_REPO:-无}-staticdata」、L103 `exit 0` |
| 6 | DUR_THRESHOLDS 未动 | **PASS** | `git diff cddaa3758 b13c7853d -- scripts/schedule_monitor.sh | grep -c DUR_THRESHOLDS` → 0 |
| 7 | 扫漏(找「该判退出码却被吞」第三处) | **FAIL(发现 3 处,均 pre-existing,见下)** | `git show b13c7853d:scripts/staticdata_backup_async.sh | grep -n "| tee"` 逐条分类 |
| 8 | C-3 静态复核(monitor↔async 终态对齐) | **PASS** | 见下 |

### 7. 扫漏详述(异步脚本 `| tee` 全量分类)

grep 全量:async 脚本 29 处 `| tee` / deploy.sh 20 处。分类结论:

- **a) 纯 echo 日志管道(无判定需求)**:async L61/62/83/98/106/117/127/136/152/155/176/178/224/242/245 与 deploy.sh 多数 echo 行,tee 为管道末命令,后续无分支判定,OK。
- **b) notify `... 2>&1 | tee -a "$LOG" || true`(有意,正确)**:async L102(仓库缺失降级)/L182(oversize 跳过)/L241(失败告警),deploy L975/L988。notify 失败不应影响主流程,`|| true` 合理,符合任务给的区分标准。
- **c) 数据/git 操作判定失效(漏网,pre-existing)——本项 FAIL 发现的 3 处**:
  1. **async L113** `rsync -a "$REPO/data/"*.db "$STATICDATA_REPO/db/" 2>&1 | tee -a "$LOG" || { STATICDATA_FAIL=1 }`:脚本**无 `set -o pipefail`**(仅 `set -u`,L32),管道退出码=tee(恒 0)→ `|| {}` 几乎永不触发 → rsync 失败不置 STATICDATA_FAIL → 心跳照写 ok → 无告警。
  2. **async L132** rsync JSON 同构,L134 `|| { STATICDATA_FAIL=1 }` 同样失效。
  3. **async L186** `if ! git -C "$STATICDATA_REPO" commit -m ... 2>&1 | tee -a "$LOG"; then`:`! (管道)` 判的是 tee 退出码反值(恒 0 → `! 0`=false)→ commit 失败永走 else(成功路径,进 push)→ 最终心跳 ok 无告警。与改2 修的 add 处(L146-151,已改 PIPESTATUS 判定)同为「git 操作 + tee 管道判定失效」模式。
  - **定性**:3 处均非本 commit 引入——`git show cddaa3758:scripts/staticdata_backup_async.sh` 核实基线 L79/L97/L145 已是同样写法(本 commit 仅改 add 行)。按 §10.3① pre-existing 不算本次 finding,但**不默默吞**:与改2 整改精神同类(「该判退出码却被吞」→ git 历史缺口/备份失败静默),建议后续同模式取 `PIPESTATUS[0]` 判定或脚本开头 `set -o pipefail`,作为遗留改进项上报主控。
- **deploy.sh 其他管道**:L160 `git checkout origin/main -- "$_u" 2>&1 | tee -a "$LOG"` 无判定(后续 unmerged 检查兜底),低危。

### 8. C-3 静态复核详述(monitor ↔ async 终态对账)

| 维度 | async 写入端(b13c7853d) | monitor 检查端(b13c7853d) | 一致性 |
|---|---|---|---|
| 心跳路径 | L68 `HB_FILE="$REPO/data/staticdata_backup_heartbeat.json"` | L1058 `STATICDATA_HB_FILE = REPO / "data" / "staticdata_backup_heartbeat.json"` | 一致 |
| ts 格式 | L74 `date '+%Y-%m-%d %H:%M:%S'` | L1067 `strptime(_hb_ts, "%Y-%m-%d %H:%M:%S")` | 一致 |
| 状态名 | L109 running / L229-235 fail·skip_oversize·ok | L1066 只认 `ok`/`skip_oversize` 判新鲜度,fail/running 自然忽略 | 拼写一致,消费集合一致 |
| 阈值 | — | L1059 `STATICDATA_HB_STALE = timedelta(hours=36)`;L1069 超→SEVERE+写 alert_state | 单位 h,与 async 无阈值依赖(阈值仅 monitor 侧) |
| 文件不存在 | — | L1097-1099 不告警(优雅跳过,由 C-5 降级 notify 覆盖) | 与 C-5 注释一致 |
| 解析异常 | — | L1094 except (ValueError, TypeError, KeyError) → 按无有效状态跳过不告警 | 防假 SEVERE |
| REPO 取值 | L35 `REPO="${REPO:-/Users/linhuichen/code/trade-data}"`(deploy L963 `--setenv=REPO="$REPO"` 传入) | L44/L64 同默认 /Users/linhuichen/code/trade-data,由 env 传入 | 静态一致,云上 env 实际值未验证 |
| NOW 类型 | — | L69 `NOW = datetime.now()`(datetime 类型,与 strptime 结果可比较) | 类型匹配 |

### 发现的其他观察(置信度 <80,已过滤,供主控知悉)

- **C3 except 未捕 AttributeError**:L1063 `_hb = json.load(_f)` 后 L1064 `_hb.get("result")`,若心跳文件顶层为 JSON 数组(手工误写)则 `.get` 抛 AttributeError,不在 except (ValueError/TypeError/KeyError) 列表内 → 可能拖崩 monitor Python 主流程。概率极低(仅外部误写文件),25 分过滤,提示一句。
- **result=running 卡死不告警**:若异步被强杀留 running 心跳且后续触发持续失败,monitor 只认 ok/skip_oversize 不告警——设计取舍已在注释声明(触发失败另有 C-1 SEVERE 兜底),动态团队评估是否需补 running 停滞检测。
- **心跳文件路径不进 git**:async 注释声明写根 `$REPO/data/`(gitignore/未跟踪区)。静态与 deploy add 范围(static-site/data/+min)无冲突,未逐字验 .gitignore,低危。

### 未验证项(动态测试由 tester 独立执行,本层不含)

1. 改1 四环境 PATH shim(fake sudo/systemd-run + fake PY 拦截 notify)——本层仅静态核分支结构,未跑。
2. C-2 chmod500 .git 注入验证「FAIL+告警+无✓无新变更」——本层未注入。
3. C-3 超36h 告警 / 未超不告警 / fail&running 不告警 / suppress+恢复——本层未动生产心跳。
4. 心跳 ok/skip_oversize 真实文件写入(tmp+mv 原子)与 monitor 读取闭环——未真跑。
5. 云上 REPO env(monitor 与 async 同值)、云上 /run/systemd/system 存在性、KillMode=control-group 连带杀 nohup 的实测结论——本层无云上访问。
