# #245 批1「L3e 双树收口」独立审查报告(reviewer)

- **审查对象**:feat 分支 `feat/245-l3e-repo-env` @ `0db068039`(worktree `.claude/worktrees/agent-a32f28468327c0b72`),含云上 dedup 数据合并操作
- **审查人**:独立 reviewer(未参与实施,不采信自述,逐字独立取证)
- **审查时间**:2026-10-10 13:30-13:5x
- **结论总览**:**10/10 要点 PASS;0 BLOCKER / 0 MAJOR;4 NIT + 1 建议**;过渡期(数据先改、代码后上)判定=**无实际危害**
- **残留后台任务:无**(本会话无 harness 转后台事件;此前 nohup 化 pytest 已跑完退出;收工前 `pgrep -fl "pytest|nohup"` 为空)
- 审查依据:实施报告 `<worktree>/docs/ops/245-l3e-dual-tree-20261010.md`;设计依据 `docs/ops/245-alert-w4-priority-20261010.md` §2.2

## 0. 纪律遵守(本次审查)
- **零真实外发**:三重保障——①dry-run 机制 7 处短路点 static 逐处核对(§6)②阳性对照网络闸 tripwire 自证 2/2 且 dry-run 双路零网络(§6)③云上 W1 台账 `alert_ledger.jsonl` 末条 = **2026-10-10 08:27:04**,审查会话时段(13:19-13:52)零外发记录;latest.md mtime 同为 08:27:04
- **云上只读**:全部 ssh 命令仅 cat/stat/md5sum/git log 等只读动作,未写云上任何文件/数据
- **本地**:未 commit、未 push、未切分支;只写本报告一处
- 禁项全遵守:零 `find /`、零白名单外 `grep -r`、零裸 pip/npm、零 Docker、token 未进 argv、未用 `curl -v/-i`

## 1. 要点1 核心 1 行 — PASS
- 生产运行时代码唯一功能改动 = `scripts/notify.py` 一行:旧 88 行 `REPO = Path(__file__).absolute().parent.parent` → 新 97 行 `REPO = Path(os.environ.get("REPO") or Path(__file__).absolute().parent.parent)`(+9 行注释);`__file__` 全文件仅此一处使用
- md5 独立取证:旧版 `ec60631b0f656a134ef8beb0846000da`(与 `git show c9258e20e:scripts/notify.py` 一致),新版 `d286463032ec0fd75aa7c02d9f3e89f4`(与 `git show 0db068039:scripts/notify.py` 一致)
- **空串陷阱核验**:env 设空串时 `os.environ.get("REPO")` 返回 `""`(falsy)→ `or` 回退旧行为;沙箱场景 D(`REPO=""`)实测回退旧形态、不产生相对路径 → 与设计文档原文形式一致,**判定安全**
- 新增 `scripts/merge_notify_dedup_trees.py` 为一次性运维脚本,不接入任何运行链(核过无被 import)

## 2. 要点2 零回归独立复算 — PASS
- 方法:自搭 `/tmp/l3e-review-sandbox/`(old/new 双树 + `run/scripts → ../code/scripts` 相对 symlink),`probe.py` 以受控 `__file__` exec 顶层打印 12 个派生量 + `_ledger_path()`
- **A(sh 形态,无 env)/ B(py 形态,无 env)**:OLD vs NEW 归一化后**逐字同构**(REPO/EMAIL·TELEGRAM·FEISHU_CONFIG/ALERTS_DIR/ALERTS_FILE/DEDUP_FILE/WARNING_BUFFER_FILE/INFO_LOG_FILE/WARNING_FLUSH_LOCK_FILE/WARNING_DEDUP_STATE_FILE/WARNING_DEDUP_LOCK_FILE + ledger 全同)→ **零回归实锤**
- **C(env+py 形态,即分裂病灶)**:OLD 无视 env 仍落 code 树(分裂复现实锤);NEW 全量落 env 指定的 run 树(**修复生效**)
- E(env+symlink)/F(尾斜杠)均正常
- **第 9/10 个派生量(报告未列)**:`.env` 候选两处 `REPO.parent/"trade-data"/".env"` 与 `REPO/".env"`(notify.py:605-606);云上实测仅运行树有 `.env` 且候选 2 先命中 → **零实际影响**(NIT-3)

## 3. 要点3 同类面 6 处 — PASS
- 第 1-5 处(nextday_gap_check.py、nextday_plan_generator.py、alert_denoise_rules.py、gen_daily_brief.py、signal_kelly_snapshot.py)逐处独立核:均「自愈」——py 侧走 resolve/物理路径的差集被 env 接管;子进程不传 env → 继承 systemd 的 `REPO` → 旧行为同树;sh 侧字面路径本就是 env 指向的 run 树
- 第 6 处**订正正确**:`check_data_integrity.py` 确无 notify 调用;两键真实产生点 = `upload_r2.py:3668`(`verify_r2_mass_mismatch`)/ `:3698`(`verify_r2_standalone_stale`)——且这两键正是云上合并 added 13 名单成员,**证据闭环**
- NIT-1:实施报告 §2 引「:2194 命中 notify」说法不准(实测该行不含 "notify" 字样);订正结论本身不受影响

## 4. 要点4 云上数据合并操作(本次最高风险项)— PASS
- **a. 过渡期风险判定:无实际危害**,论证链:①云上代码树仍旧 notify(未部署 feat)②合并只往运行树**加 13 键**,13 键无 sh 侧同键(nextday 伪跳空 sh/py 双 key 证实 `_fail` vs `_gen_fail` 分立)③13 键时间戳最晚 10-09 22:30,全部超出各自活跃窗(≤14h+ 前)④读侧 `wrapper_channel_alerted` 查的键(PATROL_DRIFT/R7/R3)不在其中 ⇒ 读侧抑制行为零变化
- **b. 合并规则核验**:39 个共享键全部 = 两树取较晚(max),**绝无改早**;`updated=0` 实锤(备份键在合并结果中全未变化);重跑率幂等(added 只增自 code 树)
- **c. 备份在位**:`/home/ubuntu/code/trade-data/data/notify_dedup.json.bak-20261010-132530`(4958B,取样取回本机 md5 `f3ed6f12af2f235ae48af5f22812ece1`)
- **d. 计数器独立复算(本轮内重跑)**:`run_keys=51 code_keys=52 merged_keys=64 added=13 updated=0 skipped=0`,与实施报告**逐字一致**;`computed(backup+code)=actual(云上合并后)` **diff=[]**;13 键名单与调研报告 §1.5 逐键吻合;时间戳格式全合法、无未来时间、字段集合仅 `{last_alerted}`
- 取样 md5:`run_merged.json` `44d87b64bf32d1519c7d6392b9ae673d`、`code_tree.json` `988b708e23527737cc94dedd7fabf02e`

## 5. 要点5 merge 脚本本身 — PASS
- 默认 dry-run(不带 `--apply` 不写);`changed==0` 时即使 `--apply` 也不写盘;备份**先于**写入(`backup.write_bytes` 在 replace 前);`tmp + os.replace` 原子写;回读校验(code 侧每 key 不早于合并值);不 import notify(无循环依赖)
- **无「dry-run 也写盘」缺陷**(逐行核过 merge() 控制流)
- NIT-4:备份名秒级分辨率(同秒重跑理论上会覆盖备份,运维可注意);回读校验未覆盖 run-only 新键(逻辑上 added 键无被覆盖风险,理论完备)

## 6. 要点6 §18 L48 零外发 — PASS(双重独立)
- **机制 static 核(7 处短路点全在真实外发之前)**:`_send_email` :1006(在 `load_email_config()` 之前 return)、`send_telegram` :532(URL/payload 构造前)、`send_feishu` :950(webhook/app 分支前)、`write_alert` :1232(函数最前,不触碰 latest.md)、`defer_warning` :1910(不写 buffer/状态)、台账 `_record_ledger` :160;CLI main 内全部 dedup check/update 均挂 `not args.dry_run`
- **阳性对照(独立自搭网络闸 tripwire)**:socket 层打闸(getaddrinfo/create_connection/raw connect 全改写为抛错),**自证 2/2 通过**(连接尝试必炸)→ ①A 路(exec 顶层+直调 `send(dry_run=True, severe=True)`)零网络零落盘、email dry-run 打印齐全 ②B 路(`runpy` 真实 `main()` + CLI `--dry-run`)exit 0、零网络零落盘,实现者证据形态逐字复现
  - 诚实标注:首跑唯一新增文件 = 复制进沙箱的真实 `alert_denoise_rules.py` 的 `.pyc` 导入缓存(**harness 自产,非 notify 行为**);`PYTHONDONTWRITEBYTECODE=1` 重跑 `NEW_FILES=[] CHANGED=[]` 全清 PASS
- **复跑未外发双证**:云上 W1 台账末条 08:27:04 + latest.md mtime 08:27:04(见 §0)
- 顺带核实:飞书缺配置告警(`_alert_feishu_config_missing`)的 ".env 已有" 措辞为**固定模板文本**(非沙箱外读取);dry-run 下该路径同样只 print 不写 dedup/ledger

## 7. 要点7 §22 deploy.sh rsync exclude — PASS
- `deploy.sh:557-558` exclude 逐字核对:`--exclude=logs/ --exclude=notify_dedup.json --exclude=alert_state.json --exclude=alerts/ --exclude=warning_* --exclude=backups/`——`alerts/` 即覆盖 latest.md;`warning_*` 覆盖 warning_buffer 与 locks
- 全仓 data 目录 rsync **穷举**:仅 `REPO→GIT_REPO` 单一方向(deploy.sh:529 static-site 与 :557 data/);无反向拷贝;staticdata 两条只涉 static-site/`.db`。双树「各自写」闭环隐患已消除,无需改 deploy

## 8. 要点8 pytest 独立跑 — PASS
- `/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q <worktree>/scripts/tests/` → **639 passed, 2 skipped, 0 failed/error, 93.20s**(未传管道吞退出码;nohup 跑完后无残留进程)

## 9. 要点9 切换收尾第二次 merge — 条件 PASS + 建议
- **必要性判定:必要(低危瞬态,非阻塞项)**——代码树在 merge#1(13:25)到 feat 部署之间仍会由旧代码路径新增 py 键;不跑则该窗口键不迁移,部署后 ≤6h 窗内同 key 可能补发一次。正是本脚本设计要消除的瞬态,命令已在实施报告 §3/§7
- **缺口**:该收尾动作**未登记进** `docs/pending-features-index.md` #245 状态格(该格仍为「待用户拍板」)→ 建议:主控 merge 时写入切换清单(建议 F5,防部署后漏跑)

## 10. 要点10 §23.3 穷举扫描 — PASS
- `check_s06_freshness.py`「不改」判定**成立**:其 :44-45 注释在无 env 场景仍真实;env 场景下归因被 env 接管;按 §23.7 冻结契约最小化改动正确
- 我扩展穷举:py 子进程调用族(overfit_monitor/retry_failed_metrics/detect_intraday_anomaly/sensenova-proxy-healthcheck/check_monitor_heartbeat/agent_inbox_watcher/check_ds_resilience)+ sh 调用族(backup_db/gold_night/intraday_snapshot/monitor_72h/on_skip_notify/r2_upload_skip_notify/check_r2_consistency/cloud_unit_patrol 等)全部「不传 env→继承;无 env 时与旧行为同树」→ **无回归、无需改代码**
- systemd 独立复核:**41/41** 个 trade-*.service 全部含 `Environment=REPO=/home/ubuntu/code/trade-data`,`sort -u` 仅一个值
- NIT-2:实施报告 §2.1「16 个脚本 import notify」按严格 import 口径实测 **10 个**(其余为 notify_sent 相关或经 subprocess 调用);报告完备性口径放宽,**无代码缺陷**

## 11. Findings 列表(分级)
| 级别 | 数 | 内容 |
|---|---|---|
| BLOCKER | 0 | — |
| MAJOR | 0 | — |
| NIT-1 | — | 报告 §2 引「check_data_integrity.py:2194 命中 notify」行号说法不准(该行无 notify 字样);订正本身正确 |
| NIT-2 | — | 报告「16 个脚本 import notify」严格口径实测 10 个;完备性口径放宽 |
| NIT-3 | — | 报告未列第 9/10 派生量(`.env` 候选 x2,notify.py:605-606);云上零实际影响 |
| NIT-4 | — | merge 脚本备份名秒级分辨率;回读校验未覆盖 run-only 键(逻辑已保证) |
| 建议 F5 | — | 切换收尾第二次 merge 须登记进主控 merge 切换清单 / pending-features-index #245 |

- ✳§10.2 阈值(80 分以下)滤除计数:**0 条**(本次全部发现已列于上,无隐藏)

## 12. 独立复跑数字汇总
- 沙箱 A-F:无 env OLD/NEW 逐字同构;C 场景 OLD 落 code 树 / NEW 落 run 树
- 云上复算:`51 / 52 / 64 / added=13 / updated=0 / skipped=0`,`computed==actual diff=[]`
- pytest:**639 passed, 2 skipped, 93.20s**
- systemd:**41/41** units `REPO=trade-data` 唯一值
- 台账末条:**2026-10-10 08:27:04**(会话期间零外发)
- tripwire 阳性对照:自证 **2/2**;dry-run A/B 双路零网络零落盘(重跑 `NEW_FILES=[] CHANGED=[]`)
- 工件:worktree `agent-a32f28468327c0b72`;沙箱 `/tmp/l3e-review-sandbox/`;云上取样 `/tmp/l3e-review-cloud/`

## 13. 未覆盖面声明
- 未做 §0 上线后生产验证:批1 = 代码+数据准备,feat 未部署,前端/数据产物零改动,不涉 §22 三处同值场景
- 未重跑云上真实 `--apply`(以「只读取样 + 本机复算逐 key 全等 + 备份可取样」替代);切换后第二次 merge 属部署后动作,本轮物理上无法验
- 站点 P0 smoke(curl 数据层)未跑:本改动不触碰任何数据产物/前端;替代证据 = §22 deploy exclude 核 + pytest 639
- 「零网络」证明基于同进程 socket 层 tripwire,未做抓包级独立验证(穷尽度声明)
- 会话内云上数字(台账/md5/mtime)均为 2026-10-10 13:4x 取样快照
