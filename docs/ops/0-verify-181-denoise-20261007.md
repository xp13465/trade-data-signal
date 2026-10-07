# #181 ①d(fetch_news R2 skip SEVERE 降噪)§0 上线验证报告(云上只读)

- 验证角色: tester agent(云上严格只读:未启停任何 unit、未跑任何业务脚本、未 source/exec 业务脚本主体、无 R2 写、无通知外发)
- 验证时间: 2026-10-07 18:47:42 ~ 19:16(CST)
- 验证对象: main `cf2440bf2`(feat `feat/181-fetchnews-denoise-20261007` tip `2c1fe1180` 经 main-merge 合入)
- 云主机: ubuntu@122.51.111.173(项目树 `/home/ubuntu/code/trade-data-signal`,`/home/ubuntu/code/trade-data/scripts` 为 symlink)
- **结论: PASS**(必验项 1/2/4/5 全 PASS;项 3 生产实跑已取到新码真实执行硬证据 + 连续 2 轮 rc=0,①d 的 dup/stale 两条**新分支因窗口内无 skip 事件未能在生产复现,如实标注缺口 + 最早可观察窗口**)

## 1. 代码层在云上(PASS)

| 项 | 期望 | 实测 | 结论 |
|---|---|---|---|
| 云上 HEAD | cf2440bf2 | `cf2440bf27...`(branch main,`git status --porcelain` 空) | PASS |
| schedule_monitor.sh md5(树内路径) | 本机 `git show main:...` 同值 | 两侧均 `b6c9280a7f778203e55bc030465adeea` | PASS |
| 同文件 md5(symlink 路径 `~/code/trade-data/scripts/`) | 同值 | 同 `b6c9280a...`(symlink → `/home/ubuntu/code/trade-data-signal/scripts`) | PASS |
| test_181_fetchnews_denoise_20261007.py md5 | 一致 | 两侧均 `62173869338af4440a7d0232ab7d11d9` | PASS |
| fixtures/181/ticks.csv md5 | 一致 | 两侧均 `8636a830560b015642c474b0d1d62cbe` | PASS |

复现:
```
git show main:scripts/schedule_monitor.sh | md5          # b6c9280a7f778203e55bc030465adeea
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cd ~/code/trade-data-signal && git rev-parse HEAD && git status --porcelain && md5sum scripts/schedule_monitor.sh ~/code/trade-data/scripts/schedule_monitor.sh scripts/tests/test_181_fetchnews_denoise_20261007.py scripts/tests/fixtures/181/ticks.csv'
```

## 2. §8「功能 done」三查

- **①main 链含 commit = PASS**:`git fetch origin main` 后 `git merge-base --is-ancestor cf2440bf2 origin/main` 通过。
  注:远端 main 已推进到 `17acab77`(cf2440bf2 之后 +1 提交,内容 = `TASKS.md` + `docs/pending-features-index.md` 各 1 行**纯文档**,`git diff --name-only` 无脚本/前端/数据文件)。任务书「ls-remote == cf2440bf2」按字面现为 17acab77 —— **不判 FAIL**(链上含目标 commit,delta 已核 docs-only);云上 HEAD 尚停 cf2440bf2(差这一个 docs 提交,功能等价,下次云上 pull 会展平)。
- **②数据层 = N/A(PASS)**:判定依据 = merge 相对第一父 `git diff --name-only 26ad2ccad cf2440bf2` 仅 4 个文件:`scripts/schedule_monitor.sh`、`scripts/tests/...`×2、`docs/ops/....md`;无任何 `.json/.db/.parquet/static-site/data/` 变更 ⇒ 本次零 R2/DB 写入面,(数据完整性 check_data_integrity / R2 一致性校验按规不适用)。
- **③前端 = N/A(PASS)**:同上 diff 无 `app.js/lab.js/index.html/sw.js/app.min.js` ⇒ 「未 bump 版本串」正确。线上佐证:`curl -A <浏览器UA> https://ss.fx8.store/` → `http_code=200`,引用 `app.min.js?v=20261004-a642`(与本次改动无关)。
- **CI 独立复核 = PASS**:GitHub API:`cf2440bf2` 的 `CI Quality Gate`(run id 37609468276)`conclusion=success`;`17acab77` 亦 success。

复现:
```
git ls-remote origin main; git merge-base --is-ancestor cf2440bf2 origin/main && echo ANCESTOR
git diff --name-only 26ad2ccad cf2440bf2
curl -s --max-time 20 "https://api.github.com/repos/xp13465/trade-data-signal/actions/runs?per_page=6"
```

## 3. 生产实跑观察

### 3.0 关键时点(与任务书假设不同,如实记录)
- 云上 pull 发生在 **18:45:15**(`git reflog`:`cf2440bf2 HEAD@{2026-10-07 18:45:15}: pull origin main: Fast-forward`;journal 同刻有外部 SSH 会话 `120.229.11.212` 18:45:09 登录,即主控侧「云上 ff 同步」动作,**非本验证动作**)。
- ⇒ 18:45:01 那轮 monitor(任务书以为的「合后首轮」)实际跑的是**旧码**(18:45:01 起、18:45:11 止,pull 晚 4s)。
- ⇒ **首轮真跑新码 = 19:00:01**;第二轮 = 19:15:01(下文均为实测)。

### 3.1 运行流水(rc=0 / 无异常栈)= PASS
| 轮次(云时) | 代码版本 | systemd(journal) | 结果 |
|---|---|---|---|
| 18:45:01~18:45:11 | 旧码(对照组) | Starting → Deactivated successfully,CPU 2.119s | OK(旧码语义:SEVERE 3/3 + 外发,见 §3.3) |
| **19:00:01~19:00:07** | **新码** | Starting → Deactivated successfully,CPU 2.000s | rc=0,无异常 |
| **19:15:01~19:15:09** | **新码** | Starting → Deactivated successfully,CPU 1.901s | rc=0,无异常;<br>`[2026-10-07 19:15:01] OK 所有任务按计划执行，无漏跑，无退出失败` |

- `schedule_monitor_launchd.err` mtime 19:15,内容仅 `resolve_repo: REPO=...` 例行行,**无任何 traceback/异常栈**(文件全程 19KB 级只增例行行)。
- `systemctl --failed` = `0 loaded units listed`(18:52/19:15 两次核,均空);`/tmp/resolve_repo_fatal.*` 不存在;`[196] CHECK_FAILED_UNITS_OK failed=0 watchman=7 个 timer 全部在跑` 每轮在位。

### 3.2 新代码确证在生产跑(**硬证据,非措辞推断**)= PASS
19:00 轮把 `data/alert_state.json` 的 `fetch_news|r2_skip_rounds` 从
`{"skip_rounds": 3, "first_seen": "2026-09-24 12:00:01"}`(18:50 读数,**无 `last_round` 键**)
改写为 `{"skip_rounds": 0, "first_seen": "2026-09-24 12:00:01", "last_round": null}`。

- `last_round` 是 #181 ①d **新增字段**:`git show 26ad2ccad:scripts/schedule_monitor.sh | grep -c last_round` = **0**(旧版零出现),新版 4 处(写点 L961 计数 / L1021 清零)。
- 结合「ExecStart 指向脚本的 md5 == 新版 md5」+「19:00/19:15 时间戳晚于 18:45:15 pull」⇒ 19:00 与 19:15 轮执行的确定是新码;`last_round: null` 即新码「else 真恢复清零点」产出的状态字段。

### 3.3 19:00 轮 r2_skip 语义行为(与设计一致)
- 现场事实:fetch_news 真实轮 17:01 `SKIPPED_LOCKED`、17:45 OK、18:01 `SKIPPED_LOCKED`、18:45 OK(其 launchd 日志);19:00 轮 stats 里 `r2_skip_count=0`(18:45 轮 completed 且同步成功)⇒ 新码走「本轮无 skip」真恢复分支清零。
- 恢复邮件被既有 6h 去重压制:`[notify][dedup] suppress key=schedule_monitor_recovery last_alerted=2026-10-07 18:00:11 age=3596s < window=21600s, 不重发` ⇒ **19:00 无任何真实外发**;`data/alerts/latest.md` md5 保持 `4a3780a61a7cb96407b72cbb13f21489`、mtime 仍 18:45。
- 旧码对照组(18:45 轮):SEVERE `fetch_news R2 上传锁连续 3 轮跳过` + email/飞书(生产定时触发,发生在验证窗口开始 18:47:42 **之前**);其状态 `line_sample=r2_skip_count=1 连续3轮` —— 与判决报告所述「同一真 skip 轮被多 tick 消费致计数虚高」形态一致(仅记录观察,不在本报告下结论)。

### 3.4 缺口 + 最早可观察窗口(不编造)= 如实标注
19:00 起 skip 链清零,19:01 fetch_news 轮 R2 同步 OK(无新 skip)⇒ ①d 的「轮去重 `[r2-skip-dup]`」「滞留保链 `[r2-skip-stale] 保链不计数`」两条**新分支本次窗口内无生产样本**(无 skip 事件不进入该分支),生产侧未能复现;已复现的是 else 真恢复分支(`last_round=None` 产物)+ 连续 2 轮 rc=0 无回归。
- **最早可观察窗口** = 下一次真实 `SKIPPED_LOCKED` 轮被 ≥2 个 monitor tick 消费时(monitor 15min/轮 × fetch_news `:01/:45` 两轮,常态 1-2 个 tick 内即出现)。
- 事后复核命令(只读):
  `grep -nE "r2-skip-dup|保链不计数|且无历史链" ~/code/trade-data/data/logs/schedule_monitor_launchd.log`
  再加核 `fetch_news|r2_skip_rounds` 的 `last_round` 是否按「同一轮只 +1」变化。

## 4. 零真外发(本验证验收点)= PASS
- 本 agent 命令全集只读:ssh 侧(git rev-parse/status/log/reflog、md5sum、ls、tail/grep/awk、journalctl、systemctl list-timers/--failed/cat)、本机(git show/diff/grep/md5、curl 公开 API/站点、pytest 静态测试)。
- 未执行任何 `systemctl start/stop/restart`、未跑任何业务脚本、未 source/exec 业务脚本主体、未做任何 R2 写;未触碰 `.env`。
- 验证窗口(18:47:42 起)内两个告警产物:①`latest.md` **零写入**(md5/mtime=18:45 保持到 19:15 不变);②`alert_state.json` mtime 19:00→19:15 —— 归因 = **生产 systemd timer 自跑轮**的落盘(journal 有对应 Starting/Deactivated 时间戳,非本 agent 动作)。
- 窗口内唯一外发候选(19:00 恢复邮件)被 6h 去重压制,日志无「邮件已发送」行;18:45 的真外发发生在窗口开始前(生产定时触发,非验证动作)。

## 5. 本机侧 = PASS
- `git status`:tracked 全干净;仅 2 个 untracked docs(`docs/ops/181-fetchnews-denoise-review-20261007.md` 系他 agent 产物 + 本报告)⇒ 本 agent 未动任何 tracked 文件。
- `pytest scripts/tests/ -q -p no:cacheprovider` → **357 passed, 2 skipped**(复现实施报告口径);单跑新测试 → **14 passed**。
- `bash -n scripts/schedule_monitor.sh` → OK。
- **红先验(§5.2 尺子先验)**:/tmp 临时树 `/tmp/redcheck-181/` 喂**旧码**(`git show 26ad2ccad:scripts/schedule_monitor.sh`,md5 `ba857f519ddf70e2badbbf5555017aee`)+ 同一测试 ⇒ **8 failed**(含 `test_block_is_1d_not_old`/`test_dup_tick_same_round_not_double_counted`/`test_stale_keeps_chain_no_reset`/`test_zero_real_outbound`);换新码 ⇒ 14 passed ⇒ 测试确实能区分新旧语义(尺子有效)。坏样本只在 /tmp,未动生产数据产物。

复现:
```
.venv/bin/python -m pytest scripts/tests/ -q -p no:cacheprovider
rm -rf /tmp/redcheck-181 && mkdir -p /tmp/redcheck-181/scripts && cp -R scripts/tests /tmp/redcheck-181/scripts/tests
git show 26ad2ccad:scripts/schedule_monitor.sh > /tmp/redcheck-181/scripts/schedule_monitor.sh
cd /tmp/redcheck-181 && PYTHONDONTWRITEBYTECODE=1 /Users/linhuichen/code/trade/.venv/bin/python -m pytest scripts/tests/test_181_fetchnews_denoise_20261007.py -q -p no:cacheprovider   # 预期 8 failed
```

## 6. 云上复现命令(只读,勿改)
```
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 '
  cd ~/code/trade-data-signal && git reflog --date=iso -3 && md5sum scripts/schedule_monitor.sh;
  tail -60 ~/code/trade-data/data/logs/schedule_monitor_launchd.log;
  journalctl -u trade-schedule-monitor.service --since "2026-10-07 18:40:00" --no-pager -o short-iso | tail -20;
  python3 -c "import json;d=json.load(open(\"/home/ubuntu/code/trade-data/data/alert_state.json\"));print({k:v for k,v in d.items() if \"r2_skip\" in k})";
  ls -la /home/ubuntu/code/trade-data/data/alerts/latest.md; md5sum /home/ubuntu/code/trade-data/data/alerts/latest.md'
```

## 7. 残留后台任务
无(本 agent 全程无 `moved to the background` 事件;nohup 起的本机 pytest 已正常退出,`pgrep pytest` 无进程)。
