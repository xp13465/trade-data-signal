# #228 实施:调度监控补「被系统层杀」维度(M1+M2)+ `scripts/lib` lint glob 扩展

- 任务来源:主控派单(用户 2026-10-07 已拍板「全按建议来」:M1+M2 做、M3 顺手确认、M4/M5 不做)
- 规格来源:`docs/ops/228-monitor-blindspot-20261007.md`(已合 main `83db1189f`;本次**逐字按 §3 行级方案**实施)
- 角色/方式:实施 agent,worktree 隔离(`.claude/worktrees/agent-aced289613afc641a`),分支 `feat/228-monitor-dims-20261007`
- 日期:2026-10-07

**一句话结论**:新增 schedule_monitor 第 6 通道「EXTRA 轮次完整性」——EXTRA 两任务(gen_daily_brief / fetch_news)被
systemd `TimeoutStartSec` 杀后 ≤1-2 个监控轮内报出 SEVERE;只**新增判别轴**,既有五通道逐字未动。
实施期按真实生产样本发现并修正一处报告未建模的假阳性(长假「跳过」轮),已实测确认。

---

## 1. 改动清单(`git diff --stat`)

```
 scripts/fetch_news.py         |   9 +++          # M2: 「轮次开始」标记(flush=True)
 scripts/gen_schedule_stats.py | 135 +++++++++++---  # M1 数据层: 轮次起点/收尾/unit 态字段
 scripts/lint_scripts.sh       |  22 +++---         # 顺带: glob 扩到 scripts/lib/*.sh|*.py
 scripts/schedule_monitor.sh   |  69 +++++++++++++   # M1 判定层: 第 6 通道
 4 files changed, 218 insertions(+), 17 deletions(-)
```
新增(未跟踪):`scripts/tests/test_228_round_incomplete_20261007.py`(23 用例)、
`scripts/tests/fixtures/228/*.log`(6 份真实生产日志切片)。

落点与报告 §3 的对应:

| 报告要求 | 落点 | 状态 |
|---|---|---|
| `gen_schedule_stats.py` EXTRA_MARKER_SCANS 增 `completion_re`/`systemd_label` | L153-183 | ✓ 逐字按报告 |
| `scan_marker_log` 返回 `round_start_ts`/`completion_seen` | L699-780 | ✓ |
| EXTRA 组装增 `round_state`/`round_start_ts`/`unit_active_state`/`unit_last_exit` | L1053-1092 | ✓ |
| `schedule_monitor.sh` 常量 `EXTRA_ROUND_INCOMPLETE`+`ROUND_INCOMPLETE_GRACE` | L534-538 | ✓ |
| `schedule_monitor.sh` 平级判定块(key `{task}|round_incomplete`,对齐停摆块) | L1042-1092 | ✓ |
| M2 `fetch_news.py` 启动标记 `flush=True` | L585 | ✓ |
| M3(check_failed_units 覆盖确认)**零代码** | 本报告 §6 | ✓ |
| M5 不做 | — | ✓ 未动 |

### 1.1 与报告的一处**有意偏离**(附真实样本证据)

报告 §3 M1 的 `completion_re` 只列了 `✓ 完成` / `✗ 失败 rc=`。实施期按**真实生产日志**核对发现:
`run_daily_brief.sh` 还有 3 条**自终结「跳过」轮**(L26 配置缺失 / L34 `schedule_enabled!=true` 拦截 /
L41 非交易日),均「跑到了、故意不干活、退出码 0」,**不含「开始生成」行**。

若只认 ✓/✗:最后一个「开始生成」轮的窗口会兜到文件尾并**越过后续所有跳过轮** ⇒ 云上实测
(09-30 开始生成 后紧跟 10-01~10-06 六条跳过)长假全程挂一条 7 天前的假 SEVERE(7 天假阳性),
且到期后窗口才被下一次真轮重置。故把 `[run_daily_brief] ...跳过` 并入终态。

**降判别力守卫**:终态正则前缀**锚定** `\[run_daily_brief\]`,不放裸「跳过」——真实生产日志同轮**中途**
有 `[notify] telegram bot_token/chat_id ... 跳过发送`(云上 L186/192/197,正常轮的中间输出),裸匹配会把
被杀轮掩盖。该反例已写成专门用例(`test_mid_round_notify_skip_text_is_not_terminal`)。

---

## 2. 硬约束逐条自验

| 约束 | 自验结果 |
|---|---|
| ① 绝不降判别力 | **只新增第 6 通道**;既有 `round_start_re` 两窗口 byte-for-byte 未改(`test_frozen_round_start_windows_byte_for_byte`);M1 在 `log_anomaly` 已命中时不报(更具体信号优先);新告警有明确三元素触发条件 + 既有 dedup/recovery 机制 |
| ② §18 L49 真实生产样本 | fixture 全为云上日志**逐行原样切片**(ssh 只读、字节保真);判据**生产侧实跑实证**(§5) |
| ③ §18 L48 零外发 | M2 打桩自测,`urlopen`/`subprocess.run` 被换成「一调用即 AssertionError」硬闸(§7) |
| ④ §18 L50 static-only | 探针只 import 目标模块 + 读日志文本,未 source/exec 任何业务脚本主体 |
| ⑤ §23.2/§23.3 | 同类错误面清单 + 举一反三清单(§3/§4) |
| ⑥ §23.4 同模块冲突 | 开工前查 `docs/pending-features-index.md`:#228 本条、#227(systemd 轴审计扩展)未占 M1 落点;见 §4 |
| ⑦ §23.15 完整版 | 两任务同构覆盖(都新增起点标记语义),无「数据以后补」项 |
| ⑧ git | 只 commit+push feat 分支,不碰 main,不 add 根 `data/` |
| ⑨ §21 算法公示 | **N/A**:无用户可见算法/数值变化。`schedule_stats.json` 仅**新增可选键**(round_state/round_start_ts/unit_active_state/unit_last_exit),前端「数据更新规则」只读既有字段 ⇒ 无公示文案需改 |
| ⑩ §23.11 无静默 | git 全程无冲突/覆盖/倒退(pre-commit lint 通过、push 为 new branch 非 ff 无需 rebase);merge main 由主控走 `scripts/main-merge.sh` 统一入口 |

---

## 3. §23.2 同类错误面清单(「判定源结构性豁免 → 漏报」这一病根) + 逐项结果

| # | 同类错误面 | 是否同病 | 处理 |
|---|---|---|---|
| 1 | `gen_daily_brief` 被杀 | 是(活体直证 8 次/12 交易轮) | ✓ M1+M2 覆盖 |
| 2 | `fetch_news` 被杀 | 是(10-04 20:11 直证) | ✓ M1+M2 覆盖 |
| 3 | `run_daily_brief.sh` 另两条终态(影子对账/ledger 对账 的 ✓/✗) | 否 | ✓ 已核:`✓ 完成` 已是终态,两对账显式「不阻塞主流程」,不影响产物完整性 |
| 4 | `run_daily_brief.sh` 三条「跳过」终态 | 是(会造成假阳性,非漏报) | ✓ 已并入终态(§1.1)+ 专项用例 |
| 5 | 同轮中途 `[notify] ...跳过发送` | 反向风险(会掩盖真故障) | ✓ 前缀锚定排除 + 专项用例 |
| 6 | `_systemd_last_exit` 是否同样缺 LoadState 护栏 | 否 | ✓ 已核 L423 早有同款护栏,`_unit_active_state` 与之对齐 |
| 7 | `scan_marker_log` 其他调用方是否被签名变更波及 | 否 | ✓ 全仓唯一调用点 = EXTRA 组装;无测试引用旧 3 元组返回 |
| 8 | 其余 21 个 trade timer 的「被杀」可见性 | **部分同病**(仅 unit 级 CFU) | ⚠ 未做(超本次范围,§4 已列上报)#227 轴 |
| 9 | `staticdata_sync` 锁等待期间被杀无痕 | 同族(日志面) | ⚠ 报告 §4 已给方案,本任务未含(报告未列 M 项) |

## 4. §23.3 举一反三清单(同模式/同数据源/同组件还被谁用 + 展示位) + 逐项覆盖

**同数据源**:`schedule_stats.json` 的消费方 = `schedule_monitor.sh`(唯一)。新字段只增不改,前端「数据更新规则」
弹窗读的是既有字段 ⇒ 无需前端改动(生产 `schedule_stats.json` 结构属新增可选键,旧消费方忽略)。

**同组件(EXTRA 通道)**:`EXTRA_MARKER_SCANS` 现仅 2 条(gen_daily_brief / fetch_news)⇒ 全量覆盖,无第三条漏改。

**同模式(云上 timer 全表比对,2026-10-07 实测 41 个 trade-*.timer)**:
- 已被 TASKS 表(17 任务,①②③ 通道)+ EXTRA(2 任务,M1)覆盖 = 19 个。
- **不在任一判定通道、仅靠 CFU 做 unit 级兜底 = 21 个**:`backup-db`、`brief-push`、`check-monitor-heartbeat`、
  `daily-summary-supplement`、`etf-track-index`、`fapi-daily`、`gold-night`、`kelly-intraday-rerun`、
  `lof-track-index`、`pf-score-daily`、`pf-score-weekly`、`pf-stage0-{manager,nav,overview,risk}`、
  `public-fund-{daily,estimation,full,quarterly}`、`schedule-monitor`、`self-heal`。
  ⇒ 这些 unit 被 timeout 杀时,**unit 级**可见(CFU,10-05 起),但**无任务级归因/无恢复配对**,且历史窗不可追补 ——
  与 M3 登记的 CFU 三局限同源。**本次不动**(超报告范围,扩面会引入新的阈值/口径设计),已列**上报主控**项(§8)。
- 已排除的假同类:`ua-timer`/`update-notifier-*` = 系统自带,非本项目。

**同组件(预算轴)**:#223⑤ 外墙 600→1740/1080 已于 10-06 23:48 生效;`EXTRA_ROUND_INCOMPLETE` 45/30min
**实测 > 现外墙**(云上 `TimeoutStartUSec=29min`/`18min`,§5)且 **<< 停摆阈值**(26h / 4h)⇒ 阈值关系成立。

---

## 5. §18 L49 生产侧实跑实证(必需项)

方式:把**新代码**(`gen_schedule_stats.py` + `util_atomic.py`)只拷到**云上 `/tmp/228x/`**,跑 static-only 探针
读**真实生产日志**,并对两 unit 做只读 `systemctl show`。**业务树零写入**(实测输出 `READONLY_PROBE_DONE`)。

```
[gen_daily_brief] log_lines=205 round_state=completed round_start_ts=2026-09-30 20:40:00 completion_seen=True log_anomaly=None
    unit_active_state='inactive' unit_last_exit=0
[fetch_news] log_lines=2917 round_state=no_start round_start_ts=None completion_seen=None log_anomaly=None
    unit_active_state='inactive' unit_last_exit=0
[gen_daily_brief 真日志截断到09-30被杀轮] round_state=started_unfinished round_start_ts=2026-09-30 20:40:00 completion_seen=False
```

含义(逐条):
1. **生产空转排除**:`unit_active_state`/`unit_last_exit` 取到真实值(`LoadState=loaded` ⇒ 才采信 ActiveState),
   说明 M1 的 unit 探测在真实生产对象上**有字段可得**,不是「解析器能解析但对象没该字段」(L49 病灶)。
2. **真阳性可达**:用真实日志截断复现 09-30 被杀轮(该轮确实无 ✓,报告 §1.5 的 8 次杀之一)⇒ `started_unfinished`,
   即 M1 在真实数据上能报。
3. **长假假阳性已消**:完整实时日志 ⇒ `completed`(§1.1 修正生效)。
4. `fetch_news` 现为 `no_start`(M2 未上线)⇒ 优雅降级**不误报**,且既有异常窗口行为不变。

云上只读实测的两 unit 属性(阈值依据):
```
Id=trade-daily-brief.service  LoadState=loaded ActiveState=inactive TimeoutStartUSec=29min  Result=success
Id=trade-fetch-news.service   LoadState=loaded ActiveState=inactive TimeoutStartUSec=18min  Result=success
```

**部署后预期(供主控 §0 核对)**:merge+云上 pull 后**无历史积压告警**
- `gen_daily_brief` 首轮即 `completed` ⇒ 不报;`fetch_news` 首轮前 `no_start` ⇒ 不报;
- 下一次真被杀 ⇒ ≤1-2 个监控轮内 `SEVERE: <task> 轮次未正常收尾(...)`;下一轮成功收尾自动发恢复。

## 6. M3:CFU 覆盖确认(零代码,按报告登记)

`check_failed_units.py` **已部分覆盖**该维度,覆盖到哪/漏在哪:
- **覆盖**:`systemctl list-units --state=failed` 全量单位级扫描(每 15min,随 schedule_monitor;10-06 00:15 云上首见);
  rc=1 时自身通道 `--severe --dedup-key failed_units_patrol --dedup-window 21600`。两任务实测 failed 存续窗
  34min(fetch-news 20:11→20:45)/ ~24h(daily-brief)≥2 巡检节拍 ⇒ **10-05 起该类杀的 unit 级发现已闭环**。
- **漏在哪**:① 只覆盖 failed 状态**存续窗**(重试快于 15min 或人工 `reset-failed` 会漏);② 告警是 **unit 级,
  无任务归因、无恢复配对**;③ **历史盲窗** 09-14~10-04 的 9 次杀发生时该通道不存在(不可追补)。
⇒ M1 与 CFU 是「任务级 + 持久判据」vs「unit 级 + 状态窗」两视角,同事件双报为报告认可的设计选择。

## 7. §18 L48 零外发证据(M2 自测打桩)

`test_m2_main_emits_marker_and_zero_outbound`:对 `fetch_news.main()` 打桩后跑**真 main()**:
- 三个采集器 / `build_digest` / `read_existing_archive` / `_merge_new_into_archive` / `atomic_write_json` /
  `_write_index` / `sync_news_digest_live` 全替换为记录桩;`DATA_DIR`/`ARCHIVE_DIR`/`OUT_FILE`/`archive_path` 指向 tmp。
- **硬闸**:`urllib.request.urlopen` 与 `subprocess.run` 换成「一调用即 `AssertionError`」⇒ 任何真实网络上传/子进程
  都会让用例**响亮失败**。(fetch_news 的落盘/上线链路全走这两条 ⇒ 双闸即覆盖全部外发出口。)
- 断言:① stdout 出现 `[fetch_news] 轮次开始 YYYY-mm-dd HH:MM:SS` ②`atomic_write_json` 2 次、`sync_news_digest_live` 1 次
  (证明主流程真跑完且**全被打桩截住**)。**本次自测零真实外发**(未发邮件/飞书、未上传 R2、未写生产文件)。

## 8. `scripts/lib` lint glob 扩展(顺带项)

`scripts/lint_scripts.sh` 三处扫描范围由 `scripts/*.sh|*.py` 扩到**含 `scripts/lib/*.sh|*.py`**:
① bash -n(L24)② `$VAR`+非 ASCII 扫描的 python glob(L51-52)③ py_compile(L80);头部 docblock 同步。
- **既有 lib 全过**:`repo_paths.sh`/`ci_selfcheck.sh`(bash -n OK)、`check_repo_paths_ratchet.py`(py_compile OK);
  全量 `=== lint 全通过 ===`(退出码 0)。
- **尺子有效性负向验证**(防「扩了却没生效」的空转, L42):临时投放 `scripts/lib/zzz_probe_bad_*.sh|.py`
  语法错文件 ⇒ 两条均 `FAIL: ...` + `=== lint 失败 ===`(证明新 glob 真在扫 lib);随后删除探针并复测全过。

## 9. 自测清单(pytest 全量)

```
$ .venv/bin/pytest -q scripts/tests/test_228_round_incomplete_20261007.py   → 23 passed
$ .venv/bin/pytest -q scripts/tests/                                        → 286 passed, 1 skipped
$ bash scripts/lint_scripts.sh                                            → === lint 全通过 ===
```
23 用例覆盖:6 个真实样本 round_state 判定 / 冻结窗口逐字守卫 / 终态正则覆盖(含 notify 反例)/
`_unit_active_state` LoadState 护栏 + 全部 None 路径 / M1 常量漂移守卫 / M1 判定 8 组(触发·三态宽容·
宽限边界·纯 age 回退 45/30·log_anomaly 降噪·非 EXTRA 与脏数据不崩·持续中不重发·恢复后再现重发)/
M2 标记 flush + 零外发。判定层源码用 **ast 从 `schedule_monitor.sh` heredoc 真提取**(非第二份实现)。

## 10. 复现命令

```
# 数据层真实样本(本机)
.venv/bin/pytest -q scripts/tests/test_228_round_incomplete_20261007.py
# 云上生产侧实跑(static-only; 先上传新码到 /tmp)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'mkdir -p /tmp/228x'
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cat > /tmp/228x/gen_schedule_stats.py' < scripts/gen_schedule_stats.py
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cat > /tmp/228x/util_atomic.py'        < scripts/util_atomic.py
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cat > /tmp/228_probe_cloud.py'         < /tmp/228_probe_cloud.py
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'python3 /tmp/228_probe_cloud.py'
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'systemctl show trade-daily-brief.service trade-fetch-news.service -p LoadState -p ActiveState -p TimeoutStartUSec'
```

## 11. 上报主控(不在本任务范围 / 需拍板)

1. **21 个 timer 的任务级归因缺口**(§4):被杀只有 unit 级 CFU 可见,无归因/无恢复配对 ⇒ 建议并入
   `#227(systemd 轴审计扩展)` 或另立任务(扩面需先定阈值/口径,不擅自动)。
2. **部署动作归主控**:merge 入 main 后,云上 `git pull` 才使 M1/M2 生效(monitor/gen_schedule_stats/fetch_news
   均为仓内脚本);生效后首轮预期见 §5 末。
3. **M2 生效时点**:`fetch_news` 的「轮次开始」标记要到云上下一轮 fetch_news 执行后才出现在日志里;
   在此之前 M1 对 fetch_news 判 `no_start`(不误报),属预期过渡态。