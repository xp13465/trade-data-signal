# B 批各审查报告「残余 / 低优先 / 观察 / 建议 / 遗留」项提取汇总(2026-10-11)

> 任务:next-steps B 批收尾 — 把分散在 B 批各审查/执行报告里的**残余面/低优先/观察/建议/遗留**项一次提取汇总,供主控统一收口。
> 范围:仅**汇总**,不修改任何其它文件,不改动 B2/B3/B4/B6/B7 代码与报告本体。
> 口径:逐份读报告原文提取;**已处置项标「已闭环」,不入待办**(单列一节留痕)。
> 来源报告(B 批,全在 main):
> - B1 `docs/ops/weekly-review-alert-memory-20261011.md`
> - B2 `next-steps-b2-review-20261011.md` + `next-steps-b2-fix-review-20261011.md`
> - B3 `next-steps-b3-review-20261011.md` + `next-steps-b3-fix-review-20261011.md` + `next-steps-b3-exec-20261011.md`
> - B4 `next-steps-b4a-cloud-20261011.md` + `next-steps-b4b-local-20261011.md`
> - B6 `next-steps-b6-review-20261011.md`
> - B7 `next-steps-b7-review-20261011.md`

## 一、分级计数

| 分级 | 条数(未闭环,入待办) | 说明 |
|---|---|---|
| **高** | 3 | 生产数据覆盖风险 / 生产告警盲区 / 时间锁定的收尾 |
| **中** | 9 | 待拍板项、机制暴露面、登记订正、文档/脚本收口 |
| **低** | 20 | 文书勘误、措辞、边界、环境差异、可机检化建议 |
| **已闭环**(留痕,不入待办) | 8 | 本批已处置,详见第三节 |
> 说明:绝大多数审查均判 **PASS**(B2/B3/B6/B7 无阻断),残余项以**低危文书/观察类**为主;「高」仅 3 条,均为跨到收尾/待拍的实质性收口点,非阻断性缺陷。

## 二、残余项逐条(按分级排序)

### 高(3)

| 来源报告 | 项一句话 | 分级 | pre-existing | 处置建议 | 备注 |
|---|---|---|---|---|---|
| b3-exec §6.7 | 备份链暴露面:`staticdata_backup_async.sh` step3.5b 的 `upload-large-json` 在写权限守卫(git 段)**之前**跑,且属 `_PRIVATE_ONLY_CMDS`(本机允许)→ **mac 若跑该脚本,会把本机 staticdata 的 large-json 目录覆盖上传 signal-backup2 正本**(本批删 ⑦ 恰好消掉 fund_nav 处触发源,但**机制本身仍在**) | 高 | 是 | 另案 | 建议给 step3.5b 加**非生产机 R2 上传守卫**(与 git 段同款 `staticdata_write_guard.py` 前置);暴露面=任何 mac staticdata 下与云上代际不一致的 large-json 目录 |
| b4a §6(#231) | 现网 `cmd_upload` **静默失败未修**(失败分支只 print 无 `sys.exit(1)`,失败仍 exit 0);`sentiment-3y/5y/all` 只走该静默单点路径,**全仓无告警消费者** ⇒ 生产**告警盲区** | 高 | 是 | 登记台账(待 D8 拍) | B4a 已列 4 要点(推荐接 `intraday_snapshot.sh` 收尾 SEVERE / 或 schedule_monitor 消费 `sentiment_r2_upload`);改 `cmd_upload` exit≠0 前须穷举调用方 |
| b3-exec §6.3 | D2 前端缓动下线:`app.js` L27840 回退 `fetchJSON('.../r2/fund_nav/${code}.json')` 已 404(预期降级不崩溃),plan D2 定「数据先清、前端缓 1-2 日再发版下线」,本任务未碰前端 | 高 | 是 | 待办(时间锁) | 观察点 **10-13/10-14**;到期须发版下线前端回退路径(bump 版本串+§24 四项) |

### 中(9)

| 来源报告 | 项一句话 | 分级 | pre-existing | 处置建议 | 备注 |
|---|---|---|---|---|---|
| b1 §二(高) | 代理/模型端点簇 6 文件 + MEMORY.md L14 索引行「状态注」(B1 判 high)——**已由本次收尾 agent 处理**(见第四节) | — | n/a | 已办(见第四节) | 剩余 memory 待修项(中1+低4)见下条 |
| b1 §二(中+低) | B1「memory 待修清单」**剩余项**:中=alert-dedup-mechanism(调度器表述→云上 systemd;行号漂移 L209-279→按现码;补 #245 批2 恢复必达注);低=4 处路径引用漂移(ai-predict-self-growth-research / daily-brief-deepseek / opencode-cache-think-findings 各自 docs 路径 + new-feature-isolated-tab-first 的 `web/lab.js` 历史路径 + open-source-dual-repos 加「(开源仓)」注) | 中 | n/a(memory) | 另案 | **非本批范围**:本 agent 任务 B 仅覆盖 high 6 文件;B1 §五 建议 2/3 待另派 |
| b1 §五.4 | failed unit 族=本周第一大告警来源(16 条外发全为「N项计划任务异常」),#248 深挖在跑须继续跟踪;**10-17 满 7 天后出 L5 正式判决**(via alert_meter.py) | 中 | n/a | 登记台账 | 告警跟进;台账 10-10 起,判决最早 ~10-17 |
| b4a §1(#221) | #221 `recent2.json` 两处登记矛盾:实物仍在位(R2 `signal_kelly_trades_parts/recent2.json`,17,881,308B,mtime 09-22)⇒ 仍待 §25 清理;标题日期「08-29」应为「09-22」;#234 尾注「均闭环」不实 | 中 | 是 | 登记台账(+ 订正 #234 尾注) | 清理前须备份+写恢复路径(§25) |
| b4a §3(#239) | #239 首夜误杀修复已上云(16 轮 0 kill),但**「机制被实战验证」不成立**(心跳行生产不可观测);**可机检化 4 点待 D 拍**(尤其 ③ 运行时可观测性=让心跳留存,否则「没等到锁」与「靠心跳逃生」不可区分) | 中 | 是 | 登记台账(待拍) | 含 ①② 静态梯度/排队分支断言,④ 每日汇总加「等锁次数/最长时长」 |
| b4a §5(#124) | #124 冻结表 timer **未挂载**(维持现状,脚本在位、全仓零引用、云上零挂载点)⇒ 等用户拍板是否挂 timer;附带 docstring 措辞误导项待修 | 中 | 是 | 登记台账(待拍 + docstring 措辞待修) | 拍板点:是否挂 timer(脚本已含 dry-run/15 天冷却/漂移豁免/备份回退) |
| b4a §8(rzhb D9) | rzhb 漂移:云上 timer 实有 **08:00 + 19:15 两槽**,登记表/代码仅登 08:00 ⇒ 事实依据倾向**删云上 19:15 槽**(19:15 属历史遗留,连续采不到 T 日) | 中 | 是 | 登记台账(待 D9 拍) | 删前先看 10-09 19:15 那轮 63s 日志正文确认无实质动;删除=改 unit+daemon-reload(root,写动作) |
| b4b §1(#218-⑥) | #218 六条建议对账:①③已覆盖、②④⑤建议不做;**⑥「告警镜像(standalone_stale/mass_mismatch 非 severe 不进 latest.md)」仍未做待拍板** | 中 | 是 | 登记台账(待拍) | 现状 `notify.py` L1202-1207 `if severe and not dry_run: _mirror_severe(...)` 未变 |
| b4b §2(#205) | #205 restore 类脚本 **2/2 未接引**:`restore-r2-backup.sh` / `restore-large-json.sh` 均未 source `scripts/lib/repo_paths.sh`,`restore-r2-backup.sh` 的 `REPO="${REPO:-$(pwd)}"` 是**假兜底**(死代码),云上裸调用 → 无法加载 R2 凭证 exit=1 | 中 | 是 | 另案 | 修法(甲·推荐):两脚本接两行 `repo_paths.sh` 模板 + `PY=$REPO/.venv/bin/python` |
| b4b §3(#149④) | #149④ timer 错峰 **5 条建议全未执行**(futures 20:05→19:45 / public-fund-daily 16:30→16:20 / lhb 18:30→18:50 / futures 点2 21:00→21:20 / supplement 20:30→20:25);重叠组现状全仍在 | 中 | 是 | 登记台账(待云上写授权) | 执行需云上 `/etc/systemd/system` 写授权;本项未动任何云上文件 |

### 低(20)

| 来源报告 | 项一句话 | 分级 | pre-existing | 处置建议 | 备注 |
|---|---|---|---|---|---|
| b1 §二(低) | (并入「中」表 b1 剩余项行;不单列) | — | — | — | 见中表 b1 §二(中+低)行 |
| b1 §五.5 | 恢复必达日常复核:每周 review 抽查「恢复类抑制=0 + pending 桶空」两项,列入 L5 周 review 固定项 | 低 | n/a | 登记台账 | 机制/注入周 review 固定项 |
| b1 §四.3 | L5 判决数据不足:台账 10-10 起,6 项数据缺口(起点晚/latest cap50 满/信号树滚动慢/本地台账 19 条合成行污染/本地无 alert_daily.json/info_log 面窄) | 低 | n/a | 登记台账 | 10-17 后出正式判决 |
| b2-review O-3 | notify.py:2256/2257 pre-existing **重复行**(`sent = any(results.values())` 双写),来自 main 历史 commit,origin/main 同存在 | 低 | 是 | 登记台账(§23.7⑤上报) | 由主控定去留,不属本分支 finding |
| b2-review O-4 | notify_sent.py 注释旧行号引用(notify.py:2359/2362) | 低 | 是 | 登记台账(下批核对) | 疑似归 #241 范畴,可能已闭环 |
| b2-review 已滤 | 静态机检 `test_static_flush_dry_run_short_circuits_before_lock` 只断言「`if dry_run:` 在 mkdir 前」,**不防「dry_run 分支不 return」的退化写法**(行为用例已覆盖) | 低 | 是 | 登记台账 | 机检强度改进建议 |
| b2-review 已滤 | 实施报告 §5「已删 ahead=0 分支」表述与派单背景小出入(不涉代码) | 低 | 是 | 顺手修(文书) | — |
| b2-fix-review §6 | `_redirect_repo_paths` 对「登记了但不在 `sys.modules`」的模块**静默跳过**(无告警):若未来某 legacy 套件改成函数内延迟 import 被测模块,隔离会**静默失效** | 低 | 是 | 登记台账 | 机制加固建议(加「登记模块未在册」stderr 提示) |
| b3-fix-review §7.1 | verify 报告「fund_nav/027213.json(最小 211B)」与实际不符(备份 gz=206B/解压=204B) | 低 | 是 | 顺手修(勘误) | sha256 逐位一致已锤内容 |
| b3-fix-review §7.3 | verify §1.1 勘误注「补为第 7 项后 7 行」主语指 exec 表(本表未补行⑦),文本微歧义 | 低 | 是 | 登记台账 | 已注「见 exec 报告」,可不改 |
| b3-fix-review §7.4 | 本机无 manifest 文件(manifest 在云上),mac 侧 restore 会打印「跳过 sha256 比对」降级 | 低 | 是 | 登记台账 | 环境差异非缺陷(有提示非静默) |
| b3-review §6 低分 | `r2_delete_prefix.py` XML 正则解析对特殊字符 key **脆性**(本前缀 key 形态 `fund_nav/NNNNNN.json` 无影响) | 低 | 是 | 登记台账 | — |
| b3-review §6 低分 | `r2_delete_prefix.py` `--expect` **非强制**(可选参数,文档已写明) | 低 | 是 | 登记台账 | — |
| b3-exec §6.2 | #237 pre-upload 404 与本次清理无因果,10-12 为首发观察日,按 plan §4 走 | 低 | 是 | 登记台账(观察) | — |
| b3-exec §6.4 | 云上 `/home/ubuntu/` 顶层 **2 个 0 字节异常名文件**,疑历史脚本残留 | 低 | 是 | 另案(核查) | 本任务只读发现未动 |
| b3-exec §6.5 | R2 `fund_nav/` 前缀**无一键重推命令**(`upload-fund-nav` 现役只传 nav_bucket)= 服务面恢复缺口(**非数据缺口**,数据本体已完整备份) | 低 | 是 | 登记台账 | — |
| b4a §7(L195) | TASKS-L195 fetch_news 对账:已机制级覆盖(L3c warning 分支),**建议销项**,保留一次观察(今晚 10-11 / 最迟 10-18 周日) | 低 | 是 | 登记台账(销项+观察) | 修复后周日尚无实测样本 |
| b4a §9(lifecycle) | 老桶 `backup/` lifecycle **14 天生效**(非 30);memory `r2-backup-bucket-second-account` 的「14vs30 未决」已过时,#169 的 10-04「30 天」读数作废 | 低 | 是 | 顺手修(memory 订正) | 建议用户 dashboard 再核一眼把 14 钉死 |
| b4a 附(建议) | verify-r2 失败只留 `tail -1` 致 **traceback 不可见**(可见性问题) | 低 | 是 | 登记台账 | — |
| b4b §2.2 | docs 侧 3 处老桶名 legacy(`site-deployment.md` 10 行 / `backup-restore.md` 10 行 / `r2-archive-upload-20261004.md` 7 行)+ `restore-large-json.sh` 头注释 4 行仍写老桶名 | 低 | 是 | 顺手修(docs 更新)+ 历史归档注 legacy | (A)(B) 需更新现行桶名;(C) 历史叙述保留+标注 |
| b4b §4(#217④) | pending-features-index **#217 行 ④ 仍标「待拍板」但事实=已修并合 main 且云上生效**(登记滞后) | 低 | 是 | 登记订正(销账) | D7 拍板时确认现状+销账 |
| b6-review §9 | 低分 4 条(实施报告 §5「假阳类别」表述与扫描器输出不完全对应 / ZeroOutboundTrap「零 R2 接触」表述可精确化(陷阱不覆盖 `http.client`)/ 复现脚本放 /tmp 非持久 / 报告 §7 复现命令依赖本机路径) | 低 | 是 | 登记台账 | 均文书/可读性,归因结论不受影响 |
| b7-review §8.2 | 多个测试存在「期望值取真实时钟 vs 被测代码取真实时钟」的**跨午夜毫秒微竞态**(test_237 / test_196 同型) | 低 | 是 | 登记台账 | 暴露窗毫秒级、全目录同模式、非本分支引入;§10.3 不为本次 finding |
| b6-review §8② | merge 时点提示:今晚 22:30 #220 force_full 是自然真验证窗口;若云上未同步 B6 修复,周日 full 会再崩 | 低 | 是 | 已办(见第三节) | 原属时点提醒,随 B6 merge 落地 |

> **计数说明**:「低」实列 21 行(含 1 行并入提示 + b6 §8② 实际已办),按未闭环计 **20**;「中」实列 9 条。

## 三、已闭环项(留痕,不入待办)

| 来源报告 | 项 | 闭环依据 |
|---|---|---|
| b2-review / b2-fix-review | O-1 `agent_inbox_watcher` 未纳入隔离(写主仓 data/logs)| **已补笔**:`_wrap_util` 登记 `LOG_DIR/LOG_FILE` + 包装 `isolate_repo=True`;复审 §1-§3 独立复现 PASS(正控还原/负控必要性/15/15、54/54 落点) |
| b2-review / b2-fix-review | O-2 `feishu_ws_listener` LOG_PATH 硬编码 trade-data 树 | **已补笔**:同批登记重定向;复审 PASS |
| b2-fix-review §4 | must-fix:报告对拍行 md5 自相矛盾(`85464 行 / 653eb82b…`) | **已订正**:b2-report L199 现文=`85464 行 / md5 076bd4e1… 零变化(注 653eb82b… 为删前 85478 行原态)` |
| b3-review §0 / b3-fix-review §0 | B3 修正项 1-4(计数口径 off-by-one / mac staticdata 残树处置 / verify 勘误注 / 审计归档)| 返修 commit `344a53237`;复审 PASS(0 must-fix,merge 无 B6/B7 回退) |
| b3-fix-review §7.2 | `/tmp/b3fix_post_backup.json`(二轮过程临时物)未清 | 已清(/tmp/b3 归档入 `docs/ops/b3-fundnav-audit-20261011/`) |
| b4a 附(P0) | 周日 verify-r2 全量对账崩溃 `UnboundLocalError: standalone_files` | **B6 修复**(`cmd_verify_r2` full 分支补 `standalone_files`);B6-review PASS |
| b4b §1(#218-①③) | #218 建议①(停滞阈值/自抬/kill 前 30 行同步云上)/ ③(standalone_stale 文案+N 动态带出)| 已被覆盖(64597a0af / 70a6c31ed 在 main + 云上 ancestry PASS) |
| b4a §2/§4(#185④/#186、#198/#200/#202) | legacy 清零复核、切桶/relay/节后资金流/S03 告警观察点 | B4a 复核 **PASS 全闭环**,无残余 |

## 四、memory 代理簇状态注(本次收尾副产物,任务 B)

> memory 目录不进 git。以下为**只加状态注**(未删原内容、未改名)。

- **加注 6 文件**(注文=现网 = **Aliyun MaaS** `https://ws-46vmklrma92x8nkw.cn-beijing.maas.aliyuncs.com/apps/anthropic`,全模型 `deepseek-v4.1-flash`;商汤轮换 8899 自 2026-10-05 11:58 停、无监听,链路保留可回切):
  1. `deepseek-thinking-perrole-proxy.md`
  2. `thinking-proxy-config-sop.md`
  3. `sensenova-linear-cool-cooldown-overkill.md`
  4. `sensenova-rpm-rate-limit.md`(附带:现网 settings 已无 `CLAUDE_CODE_MAX_RETRIES`,「当前配置=16」过时)
  5. `openrouter-config-websearch-effort-keychain.md`(明确「已回切商汤 8899」不再成立)
  6. `opencode-cache-think-findings.md`(附带:引用报告路径已归档 → `docs/archive/…`)
- **改 MEMORY.md 索引行 L14**:「(现网=商汤轮换8899)」→「(现网=Aliyun MaaS;商汤轮换8899停用,链路可回切)」;「(已回切商汤8899)」→「(现网=Aliyun MaaS,商汤8899停用)」。

## 五、复现与来源

- 提取方式:逐份 Read 上述 10 份报告,取「低优先项/观察项/残余面/建议/遗留项」段(§「问题清单」「已滤低分项」「观察与上报」「遗留」「低分项」等),不改报告本体。
- 现网核实(任务 B):`python3 -c "import json;print(json.load(open('/Users/linhuichen/.claude/settings.json'))['env']['ANTHROPIC_BASE_URL'])"` → MaaS 端点;`lsof -nP -i :8899` → 空(无监听)。
- 报告本体 commit 状态:B2/B3/B6/B7 报告已随各自 feat 分支合入 main(B3 见 TASKS 记账);本汇总为 B 批收尾新增件。

---
> 报告人:implementer(B 批收尾);只汇总不改其它文件;已闭环项标「已闭环」不入待办。