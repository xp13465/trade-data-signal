# #228 M1+M2(+lint glob) 独立审查报告(merge 前硬门槛)

- 分支:`feat/228-monitor-dims-20261007` tip `3aacffd1374516e35ba923a82b039928be1ffdad`(已 push,未合 main;`git merge-base --is-ancestor origin/main 3aacffd13` 成立⇒可干净合)
- 结论:**PASS(无阻断项)**。逐条 1–10 全过,附 3 条低严重度发现 + 2 条残留窗口说明(均不阻断 merge)
- 审查方式:全只读(diff/show/worktree-detach);零真实外发、零生产写入;业务脚本未 source/exec(§18 L50);测试只在 `/tmp/228rev`(detached,已删)
- diff 基线:`git diff origin/main...3aacffd13 --stat` = 12 文件 +899/−17(代码 4 + fixtures 6 + 报告 1 + 测试 1),逐文件核对无夹带

---

## 逐条结论(对应派单 10 点)

### 1. 有意偏离:`completion_re` 加 `\[run_daily_brief\] ...跳过` 终态 —— PASS(必要性证实 / 无误杀假阴性)
- **必要性(云上全量日志实证)**:12 条「开始生成」中最后一条为 09-30,其后紧跟 10-01~10-06 六条「非交易日,跳过」。M1 窗口=[最后「开始生成」行, 文件尾)⇒ 若不认跳过行为终态,该窗口整个长假不收敛,每轮监控都把 7 天前的旧轮重判 `started_unfinished`(长假全程挂 stale SEVERE)。跳过行 = 脚本自终结终态,纳入合理。
- **无误杀假阴性(run_daily_brief.sh L25/L33/L41 源码逐一核对)**:三条跳过分支(配置缺失/schedule_enabled≠true 拦截/非交易日)均为「打跳过行后立即 `exit 0`」⇒ `[run_daily_brief] ...跳过` 行**只可能是轮次最后一行**,不存在「跳过行之后轮次继续干活再被杀」的形态,不掩盖被杀轮。
- **前缀锚定有效(云上 L186/192/197 反例)**:真实同轮中途行 `[notify] telegram ... 跳过发送`(12+ 条)前缀不同 ⇒ 不被匹配;测试 `test_mid_round_notify_skip_text_is_not_terminal`(L87)收录该反例防裸「跳过」退化。
- 备注:长假期间一个 >24h 的旧杀轮会被首条跳过行「收口」——但其可处置窗口(杀后 ~24h 至次日 20:40)已过,属 stale 噪声,不属有效判别力。

### 2. 现有五通道逐字节未改动 —— PASS
- `schedule_monitor.sh` diff **纯新增 69 行,0 删除**(M1 块 L1042–1092);`fetch_news.py` 纯 +9;**全部删除行**仅出现在 `gen_schedule_stats.py`(签名/文档字符串/返回语句)与 `lint_scripts.sh`(范围字符串),逐行核对:
  - `scan_marker_log` 既有异常窗口计算(L752–761)与 skip 计数逐字节保留;唯一行为等价重构 = 「首个命中即 return」改为「赋值 + break 后统一 return」(L780–791),首命中语义不变;
  - 唯一生产调用方(L1064)已同步 4 元组解包 + 新 kwargs;repo 内无第二调用方(grep 核实);
  - 冻结守卫测试 `test_frozen_round_start_windows_byte_for_byte`(L129)逐字断言两条 `round_start_re`。
- 新告警链核对:key `{task}|round_incomplete` 进 `seen_keys_this_run`(恢复邮件链路自动配对);suppress 分支更新 last_alerted;`_format_alert_item` 对未知任务 .get(default) 不会 KeyError。

### 3. fixtures 真实性 —— PASS(附 1 条表述发现,见发现②)
- 逐字节子串校验(以云上整份日志为底):`daily_brief_20260914_completed / 20260927_holiday_tail / 20260928_killed / fetch_news_20261007_tail` = **4/6 整片逐字节子串**;2 个 fetch_news 场景各含 1 行合成「轮次开始」标记(M2 未上线,该行在生产日志中结构性不存在;按 M2 format string 生成,被杀轮时间戳 20:01:00 = 报告 §1.3 直证的真实被杀轮时点)。
- 合规判定:M2 标记行「无法取真样」是部署时序决定的,属可解释的不可得;合成方式非「看起来合理的杜撰」(时间戳有真实来源),符合 §18 L49 精神。

### 4. 阈值口径 45/30 vs TimeoutStart 29/18 —— PASS
- 云上只读复核:`trade-daily-brief.service TimeoutStartUSec=29min`(timer 20:40)、`trade-fetch-news.service TimeoutStartUSec=18min`(timer `*:01,45`)。45>29、30>18 成立(纯 age 兜底不会把正常慢跑误报);且 << 停摆阈值 26h/4h,两通道互斥不打架(`no_start` 归停摆通道、`started_unfinished` 归 M1)。
- 云上常态走「unit 可读 → 10min 宽限」路径;45/30 仅 unit 不可读(非 Linux/探测失败)时兜底,梯度合理。

### 5. CI 语义等价 —— PASS
- 本地复跑(venv py3.11):新增文件 **23 passed**;全套件 **288 passed + 1 skipped**。
- CI 收编确认:`.github/workflows/ci.yml` Job1 ⑧ `python3 -m pytest -q scripts/tests/`(pip install pytest pyyaml)⇒ 新测试文件会被执行。
- 跨环境自验(#223④ 教训):测试对 `G.sys.platform` 全部显式 `mock.patch.object` 强制平台 + `G.subprocess.run` 打桩,无「本机有无 systemctl」类环境假设;`LoadState=='loaded'` 守卫测试(L175)正是 #223-4 教训的断言化。导入面 = 纯 stdlib + 仓内 `util_atomic`。
- 唯一本机跑 CI 不会复现的差异点:无(测试不触网、不触 systemd、不触真实路径;fixtures 已随仓提交)。

### 6. §18 L48 零外发 —— PASS
- `test_m2_main_emits_marker_and_zero_outbound`(L348):`urlopen`/`subprocess.run` 均被替换为「一调用即 AssertionError」硬闸,跑**真 `main()`**,所有 IO 边(三 fetch/build/archive/原子写/sync)全打桩;断言 stdout 出现标记 + 主流程走完(write==2/sync==1)。
- 本人审查全程零外发:仅 diff/show/本地 pytest/只读 ssh;未触 notify/邮件/飞书/R2 任何发送链。

### 7. §18 L50 仅静态探针 —— PASS
- 实施侧云上探针(`/tmp/228x/`:gen_schedule_stats.py md5 与分支一致 + util_atomic.py,均只拷到 /tmp;`/tmp/228_probe_cloud.py`)逐一检查:仅 import/纯函数调用,无 source/exec 业务脚本主体,业务树零写入。
- 本人独立探针同规(本地 `/tmp/228_probe_review.py`,云上仅上传到 `/tmp/228rv/probe.py`,只写 /tmp;该残留可随时删,无副作用)。

### 8. lint glob 扩展 —— PASS
- 三处 glob 全扩:`bash -n`(L24)、`$VAR+非ASCII` 扫描(L51–52,Path.glob 天然只列存在文件)、`py_compile`(L80);空 glob 安全(`[ -f "$f" ] || continue` L25/L81)。
- 负向探针实测:临时放入 `scripts/lib/zzz_rev_probe_bad.sh/.py` ⇒ `FAIL:` 两处 + exit 1;清理后 exit 0。lib 现有 `repo_paths.sh/ci_selfcheck.sh` 经检查通过。
- 注:CI 不跑 lint(仅 pre-commit 调),扩范围的意义=给未来新增 lib 脚本上尺子,与 docblock 声明一致。

### 9. §23.7 冻结面 —— PASS
- 仅新增判别轴:五通道行为、既有 JSON 字段、恢复/去重语义全不变;**新增 JSON 键**(round_state/round_start_ts/unit_active_state/unit_last_exit)为附加键。
- 前端消费方核对:`static-site/app.js:33237` 仅读 name/task/schedule/est_text/last_run/last_exit/r2_skip_count ⇒ 新键不影响渲染;§21 公示无算法/数值变化 = N/A 成立。

### 10. §23.3 举一反三(21 timer 归因缺口)—— PASS(附 1 条计数发现,见发现①)
- 判别轴成立:EXTRA_MARKER_SCANS 仅 2 条(M1 全量覆盖),其余 timer 被杀只有 unit 级 CFU(`check_failed_units.py` 走 `systemctl list-units --state=failed` 全量通用,无任务级归因/无恢复配对)⇒「并入 #227」判断**同意**。
- 计数修正(发现①):报告称「41 实测 = 已覆盖 19 + 缺口 21」,但 19+21=40,实测 41,逐名对账缺口实为 **22 个**,漏的是 `trade-ab-direction-anchor`。无代码影响,属报告枚举遗漏。

---

## 低严重度发现(均不阻断 merge)

① **报告 §4 缺口清单 41−19=22,写成 21**:遗漏 `trade-ab-direction-anchor`(云上实测 active+enabled,`OnCalendar=21:15`,ExecStart=`run_ab_direction_anchor.sh`;不在 TASKS(17)/EXTRA(2)/WATCHMAN_UNITS(7)/cloud_unit_patrol 任何名单,仅通用 CFU unit 级兜底,与其余 21 个同类)。建议:归入 #227 时清单补上该 unit(报告级修正,无代码改动)。

② **测试文件 docstring(L15–17)称 fixtures「唯一例外 = fetch_news 被杀轮的标记行」**:实际 `fetch_news_20261004_completed.log` 第 0 行也是合成「轮次开始」行(M2 未上线,completed 场景同样需要该行才能测成 completed)。两个 fetch_news fixture 各含 1 行合成标记,表述应为「两个用例各一行」。测试有效性与样本可解释性不受影响。

③ **实施报告 §8 位置表述**:把 `check_repo_paths_ratchet.py` 归为 lib 脚本,实际在 `scripts/` 顶层(非 `scripts/lib/`)。纯文档瑕疵。

④ **残留窗口(已知边界,已量化)**:被杀轮检测窗口 = 杀后至次日 20:40(下一个「开始生成」开新窗口)→ 之后旧轮被自然掩蔽。监控 15min/轮(≈23.5h 内 ~90+ 次机会)+ 监控自身心跳/CFU 兜底 ⇒ 实际漏检仅当「监控恰在整个窗口内宕机」,与既有「轮次作用域只认最后一轮」同源边界,非本改动引入。

⑤ **手动运行边缘**:手工跑 `run_daily_brief.sh`(非 systemd)运行超 10min 且 unit 非 active ⇒ 会被判 `started_unfinished` 告警(输出文案指向「疑被 systemd 超时杀」)。属罕见的边缘真阳性偏噪声,可与 #227 一并评估,不阻断。

## 复现命令(只读)
```
git worktree add --detach /tmp/228rev 3aacffd13
cd /tmp/228rev && /Users/linhuichen/code/trade-data/.venv/bin/python -m pytest -q scripts/tests/test_228_round_incomplete_20261007.py   # 23 passed
/Users/linhuichen/code/trade-data/.venv/bin/python -m pytest -q scripts/tests/                                                        # 288 passed, 1 skipped
bash scripts/lint_scripts.sh   # exit 0;负向探针(临时放 lib/zzz_bad.sh)可复现 FAIL+exit 1
# 云上只读:systemctl show trade-daily-brief.service -p TimeoutStartUSec(29min) / trade-fetch-news.service(18min)
```

- reviewer 独立审查,静态探针,零外发;报告 untracked,交主控决策 merge。
