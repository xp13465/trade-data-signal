# notify.py 契约面 + #241B 前端通知耦合 调研报告(只读)

日期: 2026-10-10 | 调研者: researcher(只读, 未改任何仓库文件) | 依据: docs/ops/alert-convergence-plan-20261010.md §3/§4

## 0. 基线与可复核标识

- 主树 /Users/linhuichen/code/trade, 分支 main, HEAD 6ad3c742e, 工作区干净(调研时点)。
- 文件 sha1: notify.py=6eab3b9123f76feffb6a2b3e47010fae49e81eac; notify_sent.py=59336975424507d2188bf525e572cb3960d2c0ee; detect_intraday_anomaly.py=c41d12811f370e6a53fde3ab11863f632c8999b6; export_notifications.py=4c3973387e378e4a29e8ea441ab6c457ecf64c5f。
- ⚠️ W1 实施者正在独立 worktree(.claude/worktrees/agent-a34bf0abba0b5dde7, 分支 f65831876 locked)改 notify.py; 本报告行号=本树版本。W1 合入后 W2/W3 定位请用「符号名+行号」双锚。
- 无残留后台任务(本调研全部命令同步完成, 无 nohup/后台化)。
- 方法清单(已验证手段): ①源码逐行读+sha 锚定 ②grep 穷举(调用点/文本消费者/字符串) ③实机探针(上一段会话 /tmp/nc-probe: 打桩全渠道后跑抑制分支, 证输出行; 本次未重复) ④既有审查报告交叉(docs/ops/241-family-b-review-20261009.md、alert-system-fullchain-audit-20261009.md) ⑤测试文件静态核对。未做: 未跑 pytest(只读调研范围外)、未触真外发。

## Q1 notify.py 真实外发出口清单 — 结论: 不是单点; 最小覆盖集 = 3 个渠道函数

### Q1-A CLI 单入口(全部 shell/子进程调用经此)
- main() = notify.py:2124-2376, `sys.exit(main())` L2376; 全部分支恒 return 0(L2171/2185/2199/2207/2217/2233/2257/2275/2293/2326/2344/2349/2372)。
- 调用方: 32 个 .sh + ≥15 个 .py 子进程(grep 统计, 附录命令)。

### Q1-B main 分支 × 真实外发调用
| 分支 | 行 | 外发调用 | 抑制早退 return |
|---|---|---|---|
| --flush-warnings | L2168-2171 | flush_warning_batch → _flush_warning_batch_locked L1966 `send(...)`(severe=False) | 无(无 dedup) |
| --tier | L2181-2199 | L2186 send_tiered → L2095 `send(severe=(tier==critical))` | L2185 |
| --agent-done | L2202-2217 | L2203 notify_agent_done → L1365 send() | L2207 |
| R4(dedup_key=staticdata_backup_fail) | L2226-2257 | L2236/2241 send_tiered | L2233 |
| R7(dedup_key=r2_consistency)升级档 | L2266-2293 | L2279 send_tiered | L2275 |
| #196(2 escalate keys)升级档 | L2314-2344 | L2331 send_tiered | L2326 |
| 通用兜底 | L2346-2372 | L2351 send() | L2349 |

### Q1-C 库直调(import notify, 绕过 main; 全量)
| 脚本 | 调用点 | 性质 |
|---|---|---|
| upload_r2.py | L1368-1376 / L1761-1770 / L2057 / L2151-2159 / L3669-3684 / L3699-3714 / L3727-3739(check_dedup+send+update_dedup×7) | 告警(自管去重) |
| check_signals.py | L430 notify.send_to; L2080 notify.send | 信号推送 |
| check_nt_signals.py | L411 notify.send(feishu_post=…) | 信号推送 |
| gen_daily_brief.py | L4051 notify.send(from_prefix="[每日速递]", feishu_group="report"); 另有 L3037 CLI 兜底子进程 | 每日速递 |
| brief_push.py | L198-199 `from notify import _send_email`+调用; L211-212 send_feishu | 每日速递 20:40 |
| codex_notify_bridge.py | L69-70 send_feishu(chat_key="agent_done") | agent 完成 |
| feishu_ws_listener.py | L268 import; L390 send_feishu(chat_key="agent_done"); L728 send_feishu(chat_key="alert") | 回执+异常告警 |
| feishu_chat_hook.py | L239/244 notify.send_feishu(FEISHU_CHAT_KEY) | 消息钩子 |
| agent_inbox_watcher.py | L481-482 send_feishu(chat_key="agent_done") | codex ping |
| signal_kelly_snapshot.py | L345-356 _send_notify(check_dedup+send+update_dedup) | 快照通知 |

### Q1-D 渠道函数与网络原语(内部穷举)
- 渠道层(被 CLI 与库直调共同触达): send_feishu L778(分段循环 L830-831/L870-877, webhook L851-868) / send_telegram L388(dry-run L432-433, 占位符跳过 L422) / _send_email L883(dry-run L898-901, 占位符跳过 L918-920)。
- 原语层: urlopen L446(send_telegram 内) / urlopen L536+L547(_feishu_http_post_json L530 内) / smtplib.SMTP_SSL L938(_send_email 内); 佐证=scripts/tests/_zero_outbound.py L11-14(官方穷举「notify 家族真正外发原语只有三处」)。
- 内部调用点穷举: send L992-1002 / send_to L1025-1030 / notify_agent_done L1365 / flush digest L1966 / send_tiered L2095 / send_feishu_post_segmented L370/L380(→send_feishu, 无外部调用方) / _alert_feishu_config_missing L714-749(飞书配置异常缺失时 L747 直发邮件, 不经 send)。
- 无第四出口: 除上表外 notify.py 无其他 urlopen/SMTP 调用点(grep 实证)。

### Q1 结论
1. **不是单点**。plan §2 所述「写点=通用汇总处 L2359/2368-2371 附近」不成立 —— 那只是通用分支的打印; tier/agent-done/R4/R7/#196/flush 六个分支与全部 10 个库直调脚本都不经过它。
2. **最小覆盖集 = {send_feishu, send_telegram, _send_email} 三个渠道函数**(任何真实外发必经其一; 原语皆藏其内)。W1 现走渠道层=覆盖集正确。
3. W1 落地注意: ①hook 必须放各函数 dry-run 早退之后、真发出分支(行号见 Q1-D); ②勿漏 send_telegram(config/telegram.json 存在, telegram_configured L241-245); ③渠道级=按渠道记录, 与台账「每封一行 channels{}」口径需再定聚合(建议同进程+subject 聚合, 或渠道行+查询层聚合); feishu 分段在函数内部循环, 渠道级=1 行/逻辑消息, 原语级会 N 行。

## Q2 解析 notify.py stdout/stderr 的调用方 + 新增输出行破坏判定

### Q2-A 消费者全量清单
1. notify_sent.py L56-76(唯一判据; 模块 docstring L3-51): 判据=「`全部渠道未发出`⇒False 优先; `已发出`⇒True; `路由完成：`后 res dict 段含 `True`⇒True; 未知⇒False(fail-safe)」。调用方 12 处:
   - py: detect_intraday_anomaly L31/L320; overfit_monitor L84/L1447; check_data_gap_alerts L124/L1476; check_s06_freshness L47/L144; check_failed_units L94/L245-253/L277(wrapper); sensenova-proxy-healthcheck L44/L153; retry_failed_metrics L56/L163。
   - sh 内嵌 python: monitor_72h.sh L100/L918-919; schedule_monitor.sh L81/L2835-2837。
2. retry_failed_metrics.py L130 `if "dedup 窗口内 suppress" in stderr:` —— **唯一**匹配既有 suppress 文本者(判 tier 分支抑制)。⇒ notify.py L2183 该措辞禁改。
3. gen_schedule_stats.py L255-267 ANOMALY_RE / L277-281 PUSH_FAIL_RE 扫任务日志: 逐条核对=异常类名清单带 `\s*:` / `FATAL\b` / `panic:` / `Segmentation fault` / `core dumped` / `✗ R2_*` 专属 —— `[notify] dedup-suppressed key=<k>` 不匹配任何分支; 既有 suppress 行同样不匹配(长期共存已证)。
4. 测试: test_240/test_241 家族用硬编码输串喂 notify_sent(合成串), 与真实输出新增行无关。
5. shell 无直接 grep notify 输出文本(全库 grep "suppress|已发出|渠道未发出" 在 *.sh 命中项全部是各脚本自身去重注释, 非输出解析; sh 侧唯一解析=内嵌 notify_sent)。

### Q2-B 「新增一行」逐项判定
- 目标行形如 `[notify] dedup-suppressed key=<k>`(对照 plan §3 建议): 对上述 1/2/3/4/5 **全部非破坏**, 条件=该行不含 `已发出` / `全部渠道未发出` / `路由完成：` / `True` 子串(不含即不影响 notify_sent 三分支与 dict 判定)。

### Q2-C 前提修正(关键, 影响 W2 方案选择)
plan §3「dedup 抑制分支静默 return 0(不打任何输出)」**与代码事实不符**。抑制路径全部有 stderr 打印:
- 通用: check_dedup L1272-1273 `[notify][dedup] suppress key=… last_alerted=… age=…s < window=…s, 不重发`
- tier: L2183-2184 `[notify][tier=<t>] dedup 窗口内 suppress key=<k>`(其前 L2182 的 check_dedup 又打一条=共 2 行)
- R4 L2232 / R7 L2274 / #196 L2325 `[notify][rX] …已发, suppress`
- agent-done L1348 `[notify][agent-done] suppress …`
- (另 defer_warning 指纹层 L1779-1780 `[notify][dedup] 同源抑制(...)`)
实机探针(/tmp/nc-probe, 上一段会话)已证: 通用抑制路径输出 L1272 行; tier 分支两行; dry-run 不走去重。
⇒ **W2 两条路线**:
- **路线 B(不动冻面)**: notify_sent.py 新增三态函数(如 `notify_state(out) -> "sent"|"suppressed"|"failed"`), 按行首标记识别既有 5 类 suppress 行; 既有 `notify_sent()` 一字不改(全部既有调用方零回归); 3 个 B 站点改用它。与 W1 无同文件冲突。
- **路线 A(照 plan)**: 在 notify.py 抑制分支加显式行 ⇒ 动冻面 ⇒ 与 W1 串行; 新行须避开 4 个保留子串(Q2-B); 既有 5 类行措辞仍禁改(替换措辞会破坏 retry_failed_metrics L130)。
- 三态精度要求(W2 自测必含): ①反向用例: tier res dict 含 `'defer_status': 'suppressed'` 的行同时含 `路由完成：`+`True` ⇒ 必须判 sent 而非 suppressed(既有 notify_sent 已 True); ②正向: 通用抑制行判 suppressed; ③标记必须行首锚定(如 `[notify][dedup] suppress key=`), 禁裸 `suppress` 子串分类。
- **新暴露的测试耦合(W2 必改)**: tests/test_alertchain_hardening_20261003.py L183-217(fake subprocess 返回 stdout=""+stderr=""+rc=0, L205-217 断言 rc==0)。cmh 换判据后空输出→fail-safe(unknown→failed)→return 2 ⇒ 该用例必挂; 需把 fake 改为真实汇总行输出。
- B 站点现无判据测试(tests/ 无 heartbeat/gap/plan 判据用例; 仅 test_223 超时静态、test_196 装机路径、test_alertchain 行为)⇒ W2 须新增 red-before-green 用例。sweep 测试( test_241_family_rc_sent_sweep L233-247)只锁 3 个已改站点(cdg/svh/overfit), 不含 B 站点。

## Q3 dedup 抑制分支精确定位 + 交互

### Q3-A 7 处抑制分支(行号+行为)
| # | 位置 | 触发条件 | 打印 | 后续 |
|---|---|---|---|---|
| 1 | 通用 L2346-2349 | `args.dedup_key and not dry_run and check_dedup(key, args.dedup_window)` | 分支自身无; check_dedup L1272-1273 | return 0; 跳过 send/汇总/update_dedup/write_alert |
| 2 | tier L2181-2185 | 同上(L2182) | L2183-2184 + L1272 | return 0 |
| 3 | R4 L2231-2233 | `not dry_run and check_dedup(key, 21600)`(固 21600) | L2232 + L1272 | return 0 |
| 4 | R7 升级档 L2273-2275 | check_dedup(escalated_key, args.dedup_window) | L2274 + L1272 | return 0 |
| 5 | #196 升级档 L2324-2326 | check_dedup(escalated_key, args.dedup_window) | L2325 + L1272 | return 0 |
| 6 | agent-done L1347-1349 | `not dry_run and check_dedup("agent_done_<name>", 300)` | L1348 | 返回 dict{suppressed:True}→main L2206-2207 return 0 |
| 7 | defer_warning 指纹 L1760-1781 | 同指纹 4h 窗(WARNING_DEDUP_WINDOW L162) | L1779-1780 | return "suppressed"(成功语义, L2118/L2094) |

### Q3-B 交互
- **--dry-run**: 6 处守卫全含 `not args.dry_run`(L2348/L2182/L2231/L2266(+L2273)/L2314(+L2324)/L1347) + defer dry_run 短路 L1726-1729 ⇒ dry-run 永不抑制、永不占窗、不写 latest.md(既契合同 test_184: dry-run 通用路径仍模拟"已发出")。
- **_mirror_severe**: 仅在 send() L1000-1003(`severe and not dry_run`)调用; 抑制=send() 不被调用 ⇒ latest.md 镜像 与 write_alert(--alert-issue, 各分支均在被抑制 return 之后) **双零留痕**。这是 W1「对账缺口」最硬证据。
- **1800s buffer**: 三层独立: ①主层 dedup(notify_dedup.json per-key, 默认 --dedup-window 1800 L2150)在入队前拦(L2182); ②buffer 聚合(WARNING_BATCH_WINDOW=1800 L142)只决定批发时点, 不拦; ③指纹层(WARNING_DEDUP_WINDOW=4h L162)在入队时拦(L1760-1781, 返回 suppressed=成功)。tier=warning 重复消息可能命 ①(打印 2 条)或 ③(返回 suppressed)。
- **update_dedup 只在成功**: L2365-2366 / L2192-2193 / L2252-2253 / L2288-2289 / L2339-2340 / L1370-1371(+库侧 upload_r2 7 处自管) ⇒ 抑制不刷新窗口(TTL 不因抑制延长)。

## Q4 #241B 现状(前端通知与邮件送达耦合)

### Q4-A 门控=邮件送达后(实锤)
- detect_intraday_anomaly.py: L35 `DEDUP_FILE = REPO/"data"/"anomaly_notified.json"`; filter_and_record L223-250(只算不写, 返回 (new_alerts, dedup)); record_notified L253-265(**唯一写入点**, atomic_write_json L262, 注释 L254「仅在告警确认送达后由 main 调用」); send_alert L287-329(子进程 notify.py, argv L314-317 **无 --dedup-key**, 合并 out L319, notify_sent L320); **main 门控 L348-357**: `if send_alert(new_alerts): record_notified(_dedup_pending)` else 打印「未确认送达 ⇒ 不落去重签(下轮将重试)」。
- 耦合是 #241 B 波引入(consign 测试头 L13-14 + 241 审查报告 L92 F1): 旧「先写签后 fire-and-forget」致全失败永久失报, B 波改「送达成功才落签」——修了邮件丢失, 但把前端唯一数据源绑上了邮件送达。

### Q4-B 数据链(文件→front-end)
- export_notifications.py L51 ANOMALY_NOTIFIED_PATH → `_load_anomalies_today` L308-335(读 `{date: {"type|kind|name": iso_ts}}`; value 直进输出 `"ts": ts` L335; tier 映射 L327: rapid_move/breakout_down=severe) → merge L382-383 → OUT_JSON=static-site/data/notifications.json L48-49 原子写 L399。
- 发行: intraday_snapshot.sh L126-128(每轮跑 export; **先于** detect 的 L216) + L202-211 staticdata_sync 列表含 notifications.json(R2 同步); update_all.sh L284-285。
- 前端: static-site/app.js L15024-15038 fetch ./data/notifications.json(独立 30s 轮询) + L15128-15143 (`data.anomalies` 只弹 tier==='severe'; key=`anomaly_${type}_${kind}_${name}_${today}`, localStorage 逐条去重)。
- anomaly_notified.json 本身不外发(仅服务端 export 读; 引用面: detect L15/35/226/254/274 + export L4/10/17/51/309/382 + intraday_snapshot.sh L215 注释 + tests)。

### Q4-C W3 最小改动面
- 必改: detect_intraday_anomaly.py main 落签段 L348-357 + 新增「邮件未达 payload 暂存 + 下轮重试」helper(send_alert L303-307 依赖 `a['desc']`, 不可从 key 重建 ⇒ 需存整 payload)。
- 不动(前提: json value 保持 ts 字符串): record_notified/filter_and_record、export_notifications、app.js、intraday_snapshot.sh。若给 value 加 email 状态字段 ⇒ export L320-335 与前端 ts 消费须同改 ⇒ 不推荐(或独立文件)。
- 必改测试: tests/test_241_family_b_consign_20261009.py L279-285(负控「全渠道失败⇒不写文件」须翻转为「全渠道失败⇒文件已写(前端源)+邮件待重试」); L294-305(正控保持)。
- 次要事实: export(L127)先于 detect(L216) ⇒ 新签最快下一轮(15-30min)进前端, 与现状一致无新增滞后。
- 与 W2: detect 的 notify 调用无 dedup-key ⇒ 不存在被抑制态; send_alert 两态已够, 三态复用是工具统一(软依赖)。

## Q5 W2/W3 最小改动点清单(文件:行 / 改法 / 风险 / 回滚 / 串行)

### W1(现状实施中, 事实性核对)
- scripts/notify.py 渠道函数层 hook(进度字符串=wrap send_feishu+_send_email)。建议: 补 **send_telegram**(勿漏); hook 置各函数 dry-run guard 之后; 聚合口径见 Q1 结论 3。与 W2-A 同文件 ⇒ 串行; 与 W2-B 不同文件。

### W2-B(推荐候选: 不动冻面)
- scripts/notify_sent.py: 新增 `notify_state()`(识别 5 类既有 suppress 行, 行首锚定; 既有 notify_sent 不动); 顺手修 docstring 漂移行号(2368/2371→2359/2362, 2189/2335)。
- scripts/check_monitor_heartbeat.py L96-107: rc 判据→三态(合并 stdout+stderr; sent/suppressed→return 0; failed/异常→return 2)。
- scripts/nextday_gap_check.py L378-386: rc→三态(sent/suppressed→notify_rc=0; failed→1); 可选 L73-74(_severe_alert 现 fire-and-forget 仅 log rc, 是否一并升=拍板项)。
- scripts/nextday_plan_generator.py L1246-1257: 同上; 可选 L115-116。
- 测试: 更新 tests/test_alertchain_hardening_20261003.py L184-186(fake 输出补真实汇总行); 新增 3 B 站点正/负控 + suppressed 分类用例(red-before-green)。
- 风险: ①suppressed 误判 failed⇒每窗假报警; ②failed 误判 sent⇒吞故障; 对策=行首标记精确匹配+双向测试; ③unknown fail-safe 方向=保守 failed(不吞真故障, 沿用 #241 精神)。
- 回滚: 单提交 revert(或加常量/env 开关)。**与 W1 无文件冲突**(可与 W1 并行; 波次纪律由主控定)。

### W2-A(照 plan 原文: 加显式行)
- scripts/notify.py 抑制分支追加机器可读行(通用 L2346-2349; 若要覆盖全部 5 类=5 处)+ W2-B 的调用方/测试部分。**与 W1 串行(同文件)**。文本须避开 `已发出`/`全部渠道未发出`/`路由完成：`/`True`; 禁改既有 5 类行措辞。

### W3
- 见 Q4-C。文件层与 W1/W2 均不同; 对 W2 契约=软依赖。回滚=单提交 revert。

### 不变式核对(plan §5)
- W2-W2 皆不动 critical/首报/新 key 语义(那些全在 notify.py, 不动); W3 不动降噪层; 均为加法/换判据, 不引入新告警源、不失报。

## 附录: 复现命令(全只读)
- `shasum scripts/notify.py scripts/notify_sent.py scripts/detect_intraday_anomaly.py scripts/export_notifications.py`
- `grep -n "def send\|def check_dedup\|def update_dedup" scripts/notify.py`
- `grep -rn "import notify\|from notify import" scripts/*.py scripts/*.sh | grep -v /tests/`
- `grep -rn "from notify_sent import\|notify_sent(" scripts --include="*.py" --include="*.sh" | grep -v scripts/notify_sent.py`
- `grep -rn "notify\.\|ntf\.\|send_feishu\|_send_email" scripts/*.py | head -60`(库直调穷举)
- `grep -n "suppress" scripts/notify.py`(抑制打印穷举)
- `awk 'NR>=2346&&NR<=2372' scripts/notify.py`(通用路径); `awk 'NR>=2181&&NR<=2199' scripts/notify.py`(tier);
- `awk 'NR>=348&&NR<=357' scripts/detect_intraday_anomaly.py`(门控)
- `grep -rn "anomaly_notified" scripts static-site --include="*.py" --include="*.sh" --include="*.js" | grep -v app.min.js`
- 实机抑制探针(重建): 见 /tmp/nc-probe/probe.py(打桩全渠道+替换 DEDUP_FILE 后跑 notify.main 各分支)。

## 口径诚实标注
- 本报告为静态源码+probe 调研; 未重跑 pytest、未触真外发; 未在云树复核(云上 dual-tree 的 DEDUP_FILE 均在各自树内, 与 W4/L3e 相关, 不影响本文结论)。
- plan §3「静默」前提已证伪(Q2-C), W2 建议按三态语义落地但实现路线 A/B 由主控拍板; 若选 B, 「W1 与 W2 串行」的约束可放宽为「W2 内部与 W1 无冲突」(串行与否=主控决定)。
