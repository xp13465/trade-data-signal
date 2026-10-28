# 系统全局体检报告（2026-10-28）

> 体检方式：六路并行只读调研（数据采集 / 调度运维 / 分发展示 / 业务算法 / 工程治理 / 业界对标），
> 本文由主控合并时**逐条重新取证**：每条 P0 都自己重跑了一次证据（云上只读 SQL、`grep -n` 到行号、`stat`、
> 无痕浏览器实测、`curl` 读头），不照抄六份报告的结论与数字。
>
> 取证基线：代码 `main@d77d7338b`（2026-10-28）；生产事实一侧取自云上 `122.51.111.173`
> `/home/ubuntu/code/trade-data`（只读）；分发事实取自线上 `ss.fx8.store` / `sss.sugas.site` / `s.sugas.site` / `ssd.fx8.store`；
> 本机事实取自开发树（注意本机不是生产）。文中所有数字均标了出处或命令。

---

## 0. 怎么读这份报告 / 覆盖范围 / 未覆盖项

**怎么读**：只看第 1 节一句话结论 → 第 2 节 P0（8 条，全部有本次实测证据）→ 第 4 节路线图"马上做"5 件。
P1 是一张表，按领域分组；P2 只列表。每条建议都写了"从 X 变 Y"和"怎么验"，写不出的降级为建议并注明。

**覆盖范围**：一台云主机上的 43 个定时任务、4 个 SQLite 主库、353+ 个导出 JSON、三域名 + R2 分发链、前端首页与 SW、
34 项数据校验、告警链、备份链、CI 与测试、本机开发树。

**本次明确没覆盖 / 没复算的**：
- 没有跑任何回测、没有跑全量 pytest（只跑了单文件机检脚本与无痕浏览器探针，均只读）；
- 没有枚举 R2 对象（只看日志与线上 HTTP 响应）；
- 没有做手机真机观感、读屏与键盘实测；
- 六份报告里相当一部分 P1 数字是"取一次证据"，本次只抽样复核了与本报告结论强相关的部分，
  未复核的会在表中标「未复算」，不冒充已核实；
- 本机开发树不是生产，本机所有"数据陈旧"结论只对开发场景成立。

**与任务书的口径差异（先对质，不糊过去）**：任务书按"方向1 有 5 条 P0 / 方向5 有 1 条"派单，
但六份报告的**实物**是：方向1 三条、方向2 两条、方向3 三条、方向4 零条、方向5 零条（最高是 P1）、方向6 零条，
合计 **8 条 P0**。本报告以实物报告为准，任务书的 11 条计数不成立（可能写于报告定稿前）。
方向5 的"双数据树"（F1）虽自评 P1，实为"本机上任何脚本都可能读到旧库且不报错"，
本报告把它与方向1 的云上三副本合并成同一条 P0（见 P0-3 的"同族"段）。

---

## 1. 一句话结论

**这台系统不是"用错了工具"，是"同一个事实在盘上有好几份、任务之间只靠掐表排队、整机失联没人知道"三件事叠在一起。**
最急的不是换数据库、换框架，而是：①一个全局上传锁把晚间 20 多个任务串成一队，已经每周打死一次首页评级；
②盘上 3 份全量库副本 + 每次部署全量复制 DB，59G 盘只剩 13G；③告警的"每日下限"设计上就超用户验收线（实测 10~11 条/天 vs 0~3）；
④采集侧没有"入库前"闸门，空值正在按月翻倍地进库（2026-10 单月新增 49,295 行净值涨跌幅为空）。
前端另有三个 P0（冰点日白拉 4.6MB、备站不备数据、零错误上报），属"可用性/可发现性"问题，不属数据正确性问题。

---

## 2. 病症清单

### P0（必须有实证，共 8 条）

---

#### P0-1 一个全局 R2 上传锁，把晚间 20 多个任务串成一队，已造成周期性失败

- **现象**：晚上所有要传 R2 的任务（全量数据、快照、DB 备份、小文件）排队抢一把锁；排在前面的占着，
  后面的干等到自己的超时预算用尽被杀。
- **证据（本次云上只读复核）**：
  - 锁是全局单例：`scripts/upload_r2.py:4636` `_GLOBAL_LOCK_PATH_DEFAULT = "/tmp/trade_r2_upload.lock"`；
    等锁上限默认 7300s：`:4752` `timeout = int(os.environ.get("R2_UPLOAD_LOCK_TIMEOUT", "7300"))`。
  - 2026-10-27 实况：`data/logs/s06_snapshot_launchd.log:1636-1644` 连续打印
    `等待 R2 上传锁 690s…870s(上限 7300s)` → `⚠ latest_posrating R2 同步失败 rc=124` →
    `=== s06_snapshot.sh 结束 2026-10-27 20:50:26 退出码=124 ===`，同一秒发出 severe 邮件 + 飞书（日志 1645/1647 行）。
  - 这步的内层预算是 `scripts/s06_snapshot.sh:161` `run_to 900 ... upload-kelly-snapshots`，
    **等锁上限 7300s 远大于外层 900s ⇒ 只要锁忙过 15 分钟，必然自己把自己杀掉**（与 L55"内外层不成梯度"同型）。
  - 失败不是孤例：该日志 10-12 起的 12 次运行里 4 次 `退出码=124`（10-13、10-15、10-23、10-27），1 次 `=1`（10-16）。
  - 全网日志最大等锁时长 **3990s**（`grep "等待 R2 上传锁" data/logs/*.log` 取最大），出现在 `etf_national_team` 槽。
- **影响**：10-27 当天 `kelly_mode_s06_state.json` 的 R2 副本上传成功（日志 `r2=0`），
  **失败的是随后的 `latest_posrating.json`（首页 K 档评级）R2 同步（`pr_r2=124`）** ⇒ 首页评级卡线上约 21 小时展示昨日版，
  直到次日部署才追上（脚本自身告警文案已写明：`s06_snapshot.sh:100`）。
  同时被推迟的 `etf_national_team` / `backup_db` 会挤压下一棒，形成累积排队。
- **根因**：R2 写入按"一把全局锁"串行化，而最重的一次上传（部署触发的全量上传）与 20:07–20:45 的整段任务重叠；
  等待预算与调用方超时预算不成梯度。
- **建议改法**：A（马上做，小）等锁上限压到小于外层超时（s06 显式 `R2_UPLOAD_LOCK_TIMEOUT=600`）+ s06 挪到 21:05；
  B（治本，中）按产物域分锁（`data-files` / `db-backup` / `kelly-snapshots` / `fund-nav` 各一把，
  仓库里已有 small 锁先例）；C（中）改"入队 + 单 worker 排空"。推荐 A 先止血、B 做完即根治。
- **验证状态**：**证实**（锁串行、超时步、rc=124 次数、最大等锁时长均为本次实测）。
- **成本**：A 1 小时内；B 半天。
- **来源方向**：方向2（P0-1）。
- **实施状态（2026-10-28 追加）**：B 方案已落地（feat 分支 `fix/r2-upload-lock-domains-20261028`）：
  按产物域分锁（域锁 EX + 全局 SH 屏障，未声明域回落全局 EX）+ 每个调用方显式锁等待上限梯度
  （s06=600 < 900；审计 `scripts/r2_lock_gradient_audit.py` PASS）。**A 的时点调整（s06 挪 21:05）
  本单未做**（任务书明确不改调度时点，属另一单，需同批扫全部时点副本）。详见
  `docs/ops/r2-lock-domains-20261028.md`。

---

#### P0-2 告警的"每日下限"设计上就超验收线：实测 10~11 条/天，线是 0~3

- **现象**：机制噪音（摘要、批量预警、升级、恢复、例行、重复）每天 10~26 条，用户 2026-10-27 定的线是 0~3 条/天；
  连续一周 FAIL。而"摘要 / 恢复 / 升级"三类是设计上必然每天发生的。
- **证据（本次实跑官方尺子，只读）**：
  - `alert_noise_count.py --ledger data/alerts/alert_ledger.jsonl --date 2026-10-25` → `噪音 10 <= 3 ? FAIL`；
    `10-26` → `11 FAIL`；`10-27` → `11 FAIL`（构成：digest 2 / warning_batch 0 / escalation 2 / recovery 2 / routine 2 / repeat 3）。
  - 口径出处：`docs/ops/alert-convergence-plan-20261010.md` L4「机制噪音 0~3 条/天，真故障不设上限」。
  - **新发现（比原报告更严重）**：尺子的 `main()` 末尾无条件 `return 0`（`scripts/alert_noise_count.py:483`）——
    不只是"台账缺失时退 0"，而是**判 FAIL 也退出 0**。任何无人值守调用都拿不到失败信号，等于尺子不能当闸门。
    另实测不带 `--ledger` 时读到错误树：输出「无数据，pass=null（不判 PASS）」且 `rc=0`（默认路径落到 `trade-data-signal/data/alerts/`）。
- **影响**：每天手机被 20~50 条消息打扰（含 report 群）；真故障混在其中（10-27 同日还有 history_overwrite critical、failed_units 3 条）；
  告警疲劳 = 真故障漏看。这是历次"告警太多"投诉的实质，3A/3B/3C 修的是判据与发送细节，没动这个下限。
- **根因**：降噪口径与发送路由自相矛盾——`digest`（每日摘要）、`recovery`（恢复留痕）、`escalation`（升级）
  三类"设计上就该发"且必然每天发生，数学下限 ≈3~6 条 > 验收线 3 条；且尺子没有退出码语义。
- **建议改法**：A（马上做，小）`digest` 与 `recovery` 移出 alert 群 → 进 report 群或每日一封邮件；
  B（小）`escalation` 仅在持续 ≥24h 时每天 1 条并并入下一次摘要；
  C（小，必做）尺子改退出码：噪音超标 exit 1 / 台账缺失或无法判定 exit 2，并改用与其它脚本一致的 `resolve_repo`。
- **验证状态**：**证实**（三日噪音数逐日复现；退出码缺陷为本次新发现）。
- **成本**：A+B 半天；C 30 分钟。
- **来源方向**：方向2（P0-2），并入方向1 的 `history_overwrite` 噪音源（见 P1）。

---

#### P0-3 盘上 3 份全量库副本 + 每次部署全量复制 DB，59G 盘只剩 13G（78%）

- **现象**：2.95GB 的 `public_fund.db` 在云上盘里有 3 个独立完整副本；每次真实部署把整个 `data/`（含全部库）
  再 rsync 进代码仓；灾备仓又同步一份。10 月做了 154 次真实部署。
- **证据（本次云上只读复核）**：
  - `stat -c '%i %h %s %y %n'` 三路径：inode `956107` / `1187109` / `1312356`，硬链接数均 1，
    大小均 `2954174464`，mtime 均 `2026-10-28 07:06:00` ⇒ **三个独立完整拷贝，不是软/硬链接**。
  - `df -h /`：`59G 44G 13G 78%`；`du -sh`：trade-data 9.5G / trade-data-signal 11G / staticdata 7.8G。
  - `scripts/deploy.sh:650-653` `rsync -a --exclude=logs/ ... "$REPO/data/" "$GIT_REPO/data/"`（只排除日志/告警/备份等，**DB 全量同步**）。
  - `scripts/staticdata_backup_async.sh:149` `rsync -a "$REPO/data/"*.db "$STATICDATA_REPO/db/"`，部署每次都触发。
  - 10 月真实部署日志（>10KB）：154 个（`find data/logs -name "*deploy*" -size +10k | wc -l`）。
- **影响**：每次部署产生 ≈3.6G(DB)+1.9G(JSON) 写放大；大库快照需要 `size*1.4≈4.1G` 临时空间，
  13G 余量一旦撞上"快照+上传+部署"，磁盘见底会连锁打断采集/备份/部署。
  **数据量再涨 10 倍（单库 29.5G）时，3 份副本需 ≈90G，59G 盘直接装不下——这是下一个必然崩的点。**
- **根因**：「双树单源」早期为了让代码仓也能直读 DB，把数据库文件当普通文件全量复制；灾备仓又复制一份。
  **同族问题（本机）**：`~/code/trade/data` 与 `~/code/trade-data/data` 是两份实体（不是 symlink），
  实测 `sentiment.db` md5 不同（`38a805d2…` vs `5f6fcb97…`），`trade/data/logs` 仅 9.2M vs 活树 281M；
  而 Python 侧 `app/db.py:5` 用 `Path(__file__).parent.parent/"data"` 猜路径，
  实测从代码仓导入得到 `DB_PATH=/Users/linhuichen/code/trade/data/sentiment.db`（旧树），
  worktree 里更会打开 `data/trade.db`（0 字节）而不报错 ⇒ 读库脚本可能静默读到旧/空库。
- **建议改法**：
  1. 代码仓 `data/` 的 DB 同步改为不复制（DB 只在数据仓一份；消费方统一经 `REPO` 定位，读不到就**报错**，不许猜）；
  2. staticdata 灾备仓只备份 JSON，DB 备份统一走已有的 R2 分层；
  3. 本机按 §25 先备份 `trade/data` 再删除/改名，只留一个数据根；worktree 派单强制 `export REPO=~/code/trade-data`；
  4. 顺带清 `data/backups` 里 8 天份的 etf 备份（保留 3 天 + R2 14 天）。
- **验证状态**：**证实**（三副本、rsync 实文、磁盘数字、双树 md5 差异、DB_PATH 实测均为本次复核）。
- **成本**：云上 1（半天）+ 本机 1（1 小时，含备份）。
- **来源方向**：方向1（P0-3）+ 方向5（F1，合并）+ 方向4（P2-3 本地产物陈旧，同源）。

---

#### P0-4 采集层没有"入库前"数据质量闸门，空值/坏值正在持续进库

- **现象**：库里有成片空值、零值、空串，采集与写入两侧都不拦；校验全部后置到产物层，坏数据已经落库甚至上线。
- **证据（本次云上只读复算，全部与方向1 一致或更强）**：
  - `public_fund.db fund_daily_nav`：总行数 `22,793,757`；`nav_change_pct IS NULL` 共 `78,455` 行，
    **按月分布：2026-10 = 49,295 行、2026-09 = 15,895、2026-08 = 13,204** ⇒ 不是历史遗留，是当月产出且明显加速。
  - `fund_purchase_status`：`purchase_status=''` 共 `7,866` 行（按 `update_date` 分月：2026-10 = 1,908、09 = 2,953、08 = 3,005）⇒ 每天约 100 行空串进库。
  - `etf_national_team.db etf_daily`：`amount=0` 共 21 个日期命中，但**只有 2024-11-01 是整批（154 行，同日另有 684 行 amount>0）**，
    其余 20 天各 1 行 ⇒ 方向1"每次源端故障即一批"的表述**夸大**，实际那次整批故障发生在 2024 年 11 月，此后没有第二例。
  - `sentiment.db index_daily`：`close<=0` 仅 1 行（`20130628 / csi_H30199 / close=0.0 / source=collect`），与方向1 一致。
  - 采集层静默吞错面存在（方向1 统计 app/collector 共 276 个 `except`、59 个紧跟 `pass/continue`；本次未逐行复核）。
  - 另：`fund_estimation_nav` 表 0 行（本次复核），该采集链每天 10:00/14:30 空转、退出 0。
- **影响**：所有用到这些行的统计/信号被污染（如 `etf_signal.amount_ratio` 用 5 日均额）；
  用户侧表现是"某基金没有涨跌幅/累计净值"；最坏的是**没有任何闸门能在入库时拦住下一批坏值**。
- **根因**：结构上没有"采集 → 校验 → 入库"的闸门。`app/db.py` 只建表+迁移；`app/collector/runner.py::upsert_*`
  只做 UPSERT；字段级合法性（范围 / 非零 / 空值率预算）无人负责。
- **建议改法**：新增 `app/data_quality.py::validate_batch(table, rows, rules)`，声明式规则（日期格式与交易日、数值区间、
  禁零列、空值率上限、批内主键重复），挂在 5 个核心 upsert（index_daily / daily_metric / signal_daily / etf_daily / fund_daily_nav）；
  **整批拒绝优先于静默丢行**，拒绝写 `collect_log(status=error)` + 隔离表保留原始行。
  不建议引入 Great Expectations / pandera 框架（19+18+4+3 张表，手写 60 行规则更可控）。
  实施前必须先拆因：当月 49,295 行空值是"新基金首行"（合理可空）还是源端缺失（真故障）——
  按 §5.9 三验，拆不清就先只做"空值率环比突增 >20pp 告警"，不直接拒绝。
- **验证状态**：**证实**（坏值存在且当月仍在增长）；"整批 amount=0 频发"**被削弱**（仅 2024-11 一例）。
- **成本**：中（≈1 天 + 拆因半天）。
- **来源方向**：方向1（P0-1）。

---

#### P0-5 最大的库 `public_fund.db` 的备份从未做过恢复演练

- **现象**：每日备份确实包含 public_fund（R2 上传成功），但自动恢复演练只验 sentiment + etf 两个小库；
  这个 2.95GB 的主库从未被下载回来验证过"能不能恢复"。
- **证据（本次读脚本原文）**：
  - `scripts/backup_db.sh:2,78-79`：只热备 `sentiment.db` + `etf_national_team.db`（public_fund 不在本地热备里）。
  - `scripts/verify_backup.sh:58-63`：只 `download-db sentiment` 与 `download-db etf_national_team`；
    报告段 `:98-99` 也只列这两库 ⇒ **恢复演练覆盖 2/3 个库**。
- **影响**：若 public_fund 损坏/误删，唯一恢复路径是这条从未验证过的 763MB 分片 gzip；
  分片拼接/解压/完整性任一环节坏 = 2,279 万行净值 + 19 张季报表全丢（东财历史季报重爬成本高、部分可能已不可得）。
  发生概率低，但后果不可逆，且**其它两项（备份成功、小库演练）会给人"备份没问题"的错觉**。
- **根因**：备份链按"小库先做、大库后加"演进，验证脚本没跟着扩；大库演练要下载 763MB + 解压 2.95G，
  成本高被跳过。
- **建议改法**：给 `verify_backup.sh` 加大库分支（低频：每周一次或每月第一个周日）：
  下载 → 解压到临时目录（先判 ≥4G 空间）→ `PRAGMA integrity_check` + 三张表行数与生产比对 → 结论落 alerts。
  借 restic 的 `check --read-data` 思路（默认只验结构、加 `--read-data` 才验数据本体），**不引入 restic 工具**。
- **验证状态**：**证实**。
- **成本**：小（脚本 1 小时，运行约 10 分钟/周）。
- **来源方向**：方向1（P0-2）+ 方向6（§7）+ 方向2（正面项"要补的两点"），三处合并。

---

#### P0-6 冰点日首屏白拉 4.6MB 全史情绪序列，首屏实测 15 个数据请求 / 2.42MB / DCL 7.3s

- **现象**：当至少 3 个宽基同日"冰点"，首页为了算一句"近 X 月首次"，下载整份 4.64MB（解码后）情绪全史。
- **证据（本次无痕浏览器实测，零 localStorage / 零 SW，系统 Chrome）**：
  - `REQS 47 / DATA_REQS 15 / ERRS 0`；`transferTotal 2,422,248` B（2.42MB）；`dcl 7,323ms`、`ttfb 3,831ms`。
  - 传输 top：`/r2/data/sentiment-all.json` 513,818B（解码 4,641,354B）、
    `/data/overfit_monitor.json` 469,147B（解码 4,007,639B）、`echarts.min.js` 339,913B、`app.min.js` 327,200B、`boot.json` 176,421B。
  - 代码触发点：`static-site/app.js:16489` `const sall = await fetchJSON(dataUrl("sentiment-all.json"))`，
    位于 `_frozenList.length >= 3` 冰点扫描块内（`:16486`）；本次实测确实触发了该请求（今天就是冰点日）。
  - 另一个白拉：`app.js:2294` `_overfitMonitorPromise = fetchJSON(dataUrl("overfit_monitor.json"), 60000)`，页面初始化即发，
    但监控卡在页面中下部（不在首屏可见区）。
  - 对照设计意图：`app.js:9827` 注释自述"boot.json 首屏单 fetch 合并 11 个 JSON（请求数 22 → 2）"，
    合并机制还在，但新功能各拉各的，请求数已回涨到 15。
- **影响**：越是"全市场冰点"这种用户最关心的日子，首屏越慢（多一次跨洋往返 + 4.6MB 解析）；
  弱网下叠加超时可能直接落到失败卡片。
- **根因**：本该后端预算的派生指标（"近 X 月首次"是纯历史计算）放在前端用全量历史现算；
  "首屏聚合"方案没有准入约束，新功能默认自己 fetch。
- **建议改法**：后端在 overview 里预算 `freeze_hint`（几十字节），前端删掉 16489 那段全史扫描；
  `overfit_monitor` 改可见即拉（IntersectionObserver）或首帧后延迟 3s。
- **验证状态**：**证实**（数字逐项复现：2.42MB 与请求数 15 完全一致）。
- **成本**：小（后端加字段）+ 小（前端删逻辑），合计半天。
- **来源方向**：方向3（A-1 / A-2，原 P0 组合项）。

---

#### P0-7 "备站"只备壳不备数据，三个域名实际共用一条数据链

- **现象**：备站页面能打开，但所有数据请求被前端主动改写到主站；主站 Worker / R2 / CF 账号任一故障，三个域名一起没数据。
- **证据（本次实测 + 读码）**：
  - `curl sss.sugas.site/data/overview.json` → **404**；`s.sugas.site/data/overview.json` → **404**；
    `ssd.fx8.store/data/overview.json` → **200**（独立通道存在且可用）。
  - `static-site/app.js:9662` `const _R2_FALLBACK_BASE = "https://ss.fx8.store/data/";`，
    `:9675-9677` 备站（非主站非 localhost）把所有 `./data/*` 重写为主站 `/data/`；
    `:9655` `_R2_DATA_BASE = "https://ss.fx8.store/r2/data/"` 大 range 也直连主站。
  - 三站 `app.min.js` 版本串一致：均为 `?v=20261027-a651`（`curl` 首页取 `<script>` 引用）。
- **影响**：主站侧故障时"备站"只解决"HTML 壳还活着"，不解决数据；用户看到的是一片空壳。
  这是"以为有灾备、实际没有"的典型盲区。
- **根因**：备站方案只复制了静态壳（GitHub Pages / MaoziYun），数据域单一指向主站；`ssd.fx8.store` 的独立桶
  早在代码注释里被评估过（`:9660-9661` 写了切换原因），但没有作为最后一级兜底接回来。
- **建议改法**：前端兜底链加最后一级 `ssd.fx8.store/data/*`（顺序：本站 → 主站 → ssd 桶），带开关；
  ssd 无边缘缓存、回源慢，只做最后一级。顺带加 `scripts/check_site_consistency.sh`
  （对 4 个域名抽 5 个关键 JSON/资源比 md5 与版本串，不一致告警，挂部署收尾）。
- **验证状态**：**证实**。
- **成本**：小（前端加一级 fallback + 一个开关，半天）。
- **来源方向**：方向3（C-1，P0）。

---

#### P0-8 零错误上报 + 老壳可无限期常驻：白屏/错渲染只能等用户投诉

- **现象**：前端没有 `window.onerror` / `unhandledrejection`；SW 对 HTML 走 CacheFirst，新版靠提示用户点刷新，
  用户不点就一直跑旧 JS，而数据永远是最新的 —— 新数据结构遇上旧 JS 是**静默错渲染**，不是白屏，更难发现。
- **证据（本次 grep 复核）**：
  - `grep -n "window.onerror\|unhandledrejection\|reportError" static-site/app.js static-site/common.js static-site/inline-init.js`
    → **零命中**（rc=1）。
  - `static-site/sw.js:221` `if (req.mode === 'navigate' || APP_SHELL_ASSET_PATTERN.test(url.pathname)) event.respondWith(cacheFirst(req))`；
    更新只靠 `CACHE_VERSION` bump + `postMessage` 提示（`sw.js:124-156`），无强制收敛。
  - 现状仅百度统计 + CF Web Analytics beacon（RUM，不含 JS 错误）。
- **影响**：8-14 全白事故那一类问题，发现路径只有"用户来投诉"；34k 行单文件天然容易出
  `Cannot read 'x'` 这类错，现在完全不可见；配合老壳常驻，错渲染连报错都没有。
- **根因**：为修 8-14 白屏把 HTML 放进 CacheFirst 后，没有补"版本强制收敛"回路；也没有任何前端错误采集。
- **建议改法**（最小成本）：Worker 加 `POST /api/err`（写 R2 追加日志或 KV 计数，**不引 Sentry**），
  前端在 `inline-init.js` 装 `window.onerror` + `unhandledrejection`，1% 采样，只带
  `message / filename:lineno / build id / UA / 当前 tab`；每日汇总进既有告警渠道。
  版本收敛：`index.html` 内嵌 BUILD_ID，启动后取 `__build.json`（no-store）比对，不一致且用户空闲 5s 无交互 → 静默 reload。
- **验证状态**：**证实**。
- **成本**：小（前端 20 行 + Worker 30 行，半天）。
- **来源方向**：方向3（D-1 + B-2 合并）。

---

### P1（表格；"复核"列=本次是否亲自复算）

| # | 结论（一句话） | 关键证据 | 复核 | 建议改法 | 成本 | 来源 |
|---|---|---|---|---|---|---|
| P1-1 | 数据契约只有"文件名级"，没有字段级单一事实源 | `static-site/export.py:715-789 EXPORT_MANIFEST` 是 `{文件名: 一句话}`；`check_data_integrity.py:2046` 只校验清单⟺文件在位 | 读码未逐行复算 | 导出成功即产出"键路径→类型"黄金签名 `_contract/manifest_contract.json` 入 git，校验只比形状（变化即 FAIL） | 小~中 | 方向1 |
| P1-2 | `public_fund.db` 三张每日全量快照表是增长引擎 | 本次复核 `fund_daily_nav` 共 22,793,757 行、最新 20261026 单日 24,269 行；方向1 另测 performance 20,659/日、purchase 27,884/日、rating 18,566/日 | 部分（nav 已复算） | 快照表改"仅变更行 + last_seen"；净值按年归档；先降 `fund_rating` 到周频 | 中 | 方向1 |
| P1-3 | 采集失败面覆盖不全：静默吞错与"跑成功但 0 行"不留痕 | 本次复核 `fund_estimation_nav` 0 行；方向1 统计 276 个 except / 59 个静默吞 | 部分 | 采集器统一出口 `log_collect(metric_id,status,rows)`；`rows==0` 且期望非空 → warn/error；"连续 2 天 0 行"进 gap 检查 | 小~中 | 方向1 |
| P1-4 | 历史改写审计表 509,552 行里 99.77% 是假改写，且无保留策略 | 本次复核：total 509,552 / changed 491,532 / appeared 9,011 / disappeared 9,009，与方向1 逐位一致 | 是 | 按 §25 先备份再一次性清理等价改写行（约 49 万行）+ 180 天保留期；**不再加新规则** | 小 | 方向1 |
| P1-5 | 调度没有依赖声明，14 个服务外层超时=无限 | 本次复核 `grep -l "^TimeoutStartSec=0" /etc/systemd/system/trade-*.service` = **14 个**（含 update-all、public-fund-full）；方向6 另测 public-fund-full 22:00 跑 86 分钟，而 check-data-gap 22:35 就读同一个库 | 是（超时数） | 给 14 个补 `TimeoutStartSec`（近 30 天 P99×1.5，外层 > 内层留 ≥120s 梯度）；给真实依赖对加"前置产物新鲜度"闸门 | 中 | 方向2 + 方向6 |
| P1-6 | 整机失联没有外部视角 | 本次复核 `grep uptime_check` 只命中脚本自身 + `check_repo_paths_ratchet.py` 白名单，无调度引用；云上 0 个 uptime unit（方向2 七面交叉） | 部分 | 接 healthchecks.io 死手心跳（每天 1 次 ping，25h 不来就外报）+ 把 uptime_check.sh 挂 timer 管"数据新不新" | 小 | 方向2 + 方向6 |
| P1-7 | "漏跑"检测只覆盖 17/43 | `scripts/schedule_monitor.sh` 手写 TASKS 表 17 项；systemd 对"timer 到点未触发"完全静默 | 未复算 | 新增通用判据 `timer_stall_check`：读 `LastTriggerUSec` + 解析 OnCalendar 最大间隔，`now-last > 2×间隔` 告警，挂进已有的 cloud_unit_patrol | 中 | 方向2 |
| P1-8 | 部署锁跳过写 exit 0，12 次无声未部署 | 本次复核 4 个日志合计 12 条 `排队等锁超时`（1+3+4+4） | 是 | 跳过改专用退出码 75 + 映射为 notice（不进 alert 群） | 小 | 方向2 |
| P1-9 | 告警尺子不能当闸门（本次加强：FAIL 也 exit 0） | 本次实测 no-arg → `无数据 pass=null` rc=0；带 ledger 判 FAIL 仍 rc=0；源码 `:483` 无条件 `return 0` | 是 | 改退出码 1/2 + 用 `resolve_repo` | 小 | 方向2（本次强化） |
| P1-10 | nextday 开盘价闸单一上游连丢 5 轮，重试不换源，"待人工"标记无消费方 | 10-27 日志 `主源 fund_etf_spot_em 失败 ×5` → fail-closed rc=2；产物里 pending 标记无读取方 | 未复算 | 重试轮换源（不是重复打主源）+ pending 标记发 notice 进 report 群 | 小~中 | 方向2 |
| P1-11 | 页面默认 S06（今日 a9）与邮件/飞书 NEW14 两套过滤，同日候选池差 26 条 | 本次复核 `common.js:845 _KELLY_FADE_DEFAULT_MODE="s06"`；线上 s06 state `2026-10-27T20:35:03 / on_base=a9 / off_base=new14 / last effective_mode=a9` | 部分（两端事实已核，26 条差集未复算） | 邮件链路切 S06 **必须用户拍板**（§23.7）；未拍板前先加口径提示（邮件尾注 + 页面标签） | 小（提示）/中（切换） | 方向4 |
| P1-12 | "默认档键集"闸门实际只锁 NEW14，默认是 s06 仍 PASS（假绿） | 本次实跑 `python scripts/check_fade_keys_alignment.py --repo .`：输出`默认档生产键集: 14 键`且 A1-A7 全 PASS，同时 A4 打印`默认档=s06`；源码 `:85-91 default_mode_prod_keys()` 无默认档参数、`:94-100` 硬取 `id=="new14"` | 是 | 闸门先读默认档 → 若 s06 则解析 state 的 on/off base，断言后端/前端/邮件/overfit 覆盖 a9∪new14；改掉 `:27` 的 a9/new15 过时注释 | 小 | 方向4 |
| P1-13 | 规则版每日速递命中率恒为 n=0，90 天档案只剩 26 条 | 本次实测线上 `daily_brief_history.json`：`total 26`，`stats.30d.n=0 / 90d.n=0` | 是 | 规则版用"大盘区间命中"独立口径，不套三层口径；查 09-14 前档案备份能恢复就恢复，否则页面标起始日 | 小~中 | 方向4 |
| P1-14 | 回测产物没有代码版本/数据截止/运行 ID，报告数字不可溯源 | 方向4 实测顶层只有 `generated_at/config/quadrants`；本次未复算 | 未复算 | 顶层加 `run_id/git_sha/git_dirty/data_cutoff/config_hash`；快照 index 存 config_hash；加对比 CLI | 中 | 方向4 |
| P1-15 | 过拟合监控风险分权重人工设定，D2 不是真样本外，D4 基线含近窗，且完全不覆盖 S06 | 方向4：`overfit_monitor.py:19-21,102` 权重 0.40/0.25/0.20/0.15；`grep -i s06` = 0 | 未复算 | 先把口径改诚实（改名/基线改 expanding），再把 S06 并入监控；真 walk-forward 另排 | 小~大 | 方向4 |
| P1-16 | 评级阈值 0.75/0.55 与费率档在 5+ 处各写一份，阈值无机检 | 方向4 列 5 处 + app.js 至少 8 处；本次未复算 | 未复算 | 阈值只留 artifact/config 一处，后端/前端都读它；CI 加字面量比对 | 小 | 方向4 |
| P1-17 | `industry-all-concepts.json` 单文件 br 8.14MB，"分片"已有先例却没照抄 | 本次实测 `br_dl=8,139,936`；`:25613` 单文件整包拉；同目录 `-indices/` 已分片 | 是 | 照抄 indices 模式：meta（92 概念统计）+ 单概念历史，点开才拉 | 中 | 方向3 |
| P1-18 | 两个前后端 parity 闸门写了没人跑（死闸门），一个只在注释里 | 本次 grep：`check_kelly_unique_frontend_parity.mjs` 除自身+1 文档零引用；`check_consensus_parity.mjs` 只被 app.js 注释与文档提及；ci.yml/deploy.sh/main-merge.sh 均无这两个；ci.yml `continue-on-error` 恰 4 处（126/198/466/473） | 是 | 两个死闸门接入 CI 或明确删除；posrating 从注释改自动链；**不要新增闸门**（见第 5 节） | 小 | 方向3 + 方向5 |
| P1-19 | 缓存层 TTL 与业务新鲜度不对齐（间歇性拉长到 4h） | 本次复测：`boot.json` = `max-age=60`、`overfit_monitor.json` = `max-age=600`（**均未复现 14400**），但 `r2/industry/industry-all-concepts.json` = `max-age=14400, cf-cache-status HIT, age 748` ⇒ 拉长是**间歇性**的，不是恒态 | 是（推翻"boot 恒为 4h"） | 短期：前端按 `collected_at`（分钟级）判陈旧，不只比日期；中期：boot 拆低频壳/盘中快照 | 小~中 | 方向3 |
| P1-20 | 本机双数据树 + Python 侧默认指向旧树（与 P0-3 同源，单独留一行跟踪） | 本次实测两树 `sentiment.db` md5 不同、logs 9.2M vs 281M；`app/db.py:5` 实测指向 `trade/data/sentiment.db`；worktree 内 `data/trade.db` 0 字节 | 是 | 见 P0-3 建议 1/3/4；另加 `app/db.py` 等统一 `REPO` 且读不到即报错 | 中 | 方向5 |
| P1-21 | 治理体量棘轮仍在加速（规则上线 10 天，三个上限全破） | 方向5：CLAUDE.md 69,830B（21 天 +34%）、role skills 127,111B（+11.6%）、Q4 条款 +8（上限 3） | 未复算 | 超阈值即"当月禁止新增条款"（机械可判）；docs/ops 索引脚本生成；把仅主控需要的段落移出子 agent 注入 | 小~中 | 方向5 |
| P1-22 | 测试与生产代码错位：66 个 app 模块 57 个在测试里零引用 | 方向5：1931 用例全在 `scripts/tests/`；`app/queries.py` 无直接 import | 未复算 | `queries/signals/alert_score` 各补 1 个冻结样本用例；`--cov=app` 只报不拦；测试按模块命名 | 中 | 方向5 |
| P1-23 | 数据源健康没有"跨轮次"状态：坏源每天被优先重试 | 方向6：退避只在单次运行内；仅 sensenova 有健康状态文件 | 未复算 | `source_health.json`（last_fail/last_ok/fail_streak），选源入口跳过 open 态，隔 N 小时半开探测 | 小（1 天） | 方向6 |

### P2（表格即可）

| # | 项 | 证据/说明 | 来源 |
|---|---|---|---|
| P2-1 | 死表/死管线残留（board_daily 0 行、4 个 0 字节 DB、invalid_metric、旧指标命名、fund_estimation_nav 0 行） | 方向1（fund_estimation_nav 0 行本次复核） | 方向1 |
| P2-2 | 指数 pct_change 仍有 2,046 行 NULL（2025 年 1,587 行） | 本次复算：按年合计 2,046，2025=1,587、2022=335，与方向1 一致；修复只覆盖 upsert 首行 | 方向1 |
| P2-3 | 指数/ETF 覆盖"最后一公里"缺口无 `expected_freshness` 声明 | 方向1 | 方向1 |
| P2-4 | `signal_daily` 仍是每日 DELETE+重算，历史信号不是事实 | 方向1 | 方向1 |
| P2-5 | 日志无轮转（`data/logs` 117M，intraday 单文件 24.9MB） | 方向2；本次未复核大小 | 方向2 |
| P2-6 | 部署链无回滚（"回滚" = 人工 revert + 再部署） | 方向2；`deploy.sh` 无 rollback 分支 | 方向2 |
| P2-7 | 告警台账/日志不在备份内；R2 只读凭证与主机同放 | 方向2 | 方向2 |
| P2-8 | 本地 `static-site/data` 1.2GB 陈旧镜像，本机验证≠线上 | 方向3；与 P1-20 同源 | 方向3 |
| P2-9 | `etf_score_list.json` 死产物仍每日生成上传；77 个 `.gz` 残留 | 方向3；线上 200 + gzip 980KB | 方向3 |
| P2-10 | 跨域名一致性无自动机检 | 方向3 | 方向3 |
| P2-11 | 移动端仍有 9~10px 字号；无障碍基础薄弱 | 方向3（style.css 9 处） | 方向3 |
| P2-12 | 静态兜底 86.60% 与动态 150.85% 落差 64pp，兜底时未显式标注 | 方向4 | 方向4 |
| P2-13 | 机检登记表与 CI 实际挂载漂移 | 方向4 | 方向4 |
| P2-14 | docs/kelly/analysis 107 个条目没有"当前权威"索引 | 方向4 | 方向4 |
| P2-15 | scripts/ 约 20% 脚本无活调用方；全仓零 lint / 零类型检查 | 方向5 | 方向5 |
| P2-16 | 依赖 pin 不完整（numpy/pandas/pyarrow 不在 requirements.txt） | 方向5 | 方向5 |
| P2-17 | 发布链三路并存 + 云上 timer 与 git 脱钩 + 前端 113 处 17:50 字面量 | 方向5 | 方向5 |
| P2-18 | 单文件巨石（upload_r2.py 4,975 行 / schedule_monitor.sh 4,608 行 / notify.py 3,884 行）与 9 个重复原子写实现 | 方向5 | 方向5 |
| P2-19 | merge 前置全量 pytest 每月约 8 小时；CI checkout 69s（仓库 1.5G） | 方向5（未实跑计时） | 方向5 |
| P2-20 | docs 里 163MB 是分析数据 json，与文档混住 | 方向5 | 方向5 |

---

## 3. 架构评估：哪些该保留、哪些该换

判断基线：单人维护、一台 4C/4G 云主机、SQLite、静态站、零/低预算。
"保留自建"不是偷懒，是这些层的能力是**领域语义**，换框架等于丢能力；"引入轻量工具"只挑**自建做不到**的那一件。

| 层 | 判断 | 依据 | 业界出处 |
|---|---|---|---|
| **存储（SQLite 主库）** | **保留** | 最大库 2.95GB，落在 SQLite 舒适区；单机、单写者、批处理；10x 先崩的是"三副本 + 全量 rsync + 快照表全量重插"，换 Postgres 三件照样存在甚至更贵。要做的是 P0-3 + P1-2，不是换引擎 | https://www.sqlite.org/whentouse.html ， https://duckdb.org/why_duckdb |
| **分发（Workers 静态资源 + R2 + D1 + KV）** | **保留现状的分层** | 单文件 >25MB 走 R2、小文件走 Workers、关系型分页走 D1、订阅走 KV —— 已经是业界推荐的分层；D1 免费限额 500MB/库装不下 1.2G 数据，不能全量搬 | https://developers.cloudflare.com/workers/static-assets/ ， https://developers.cloudflare.com/d1/platform/limits/ ， https://developers.cloudflare.com/workers/platform/limits/index.md |
| **调度（43 个 systemd timer）** | **保留** + 只补"前置就绪闸门" | 全部是单机单脚本、无分支 DAG；Airflow 官方要求 ≥4GB 内存且明说 SQLite 不得用于生产，本机总内存 3719MB；systemd 的 `Persistent=true` 补跑与 unit 级互斥是 cron 没有的 | https://airflow.apache.org/docs/apache-airflow/stable/installation/prerequisites.html ， https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html |
| **可观测（自建告警 + 34 项数据断言）** | **保留自建 + 引入外部死手开关** | 自建解决"数据对不对/任务成没成"，这是领域知识；买不到的是"整机还活着吗"，必须从机器外面看。已有 Cloudflare Worker，零新增费用；不要在 4G 机器上装 Prometheus/Grafana | https://healthchecks.io/docs/ ， https://healthchecks.io/pricing/ |
| **告警治理（自建规则引擎）** | **保留自建** + 借 Alertmanager 的"抑制表"写法 | 本项目告警是脚本直接产生的事件流，中间没有指标层；上 Alertmanager 等于先造一层不需要的指标。可借的是"如果 A 在活跃，B 只留一行摘要"（整机级根因抑制） | https://prometheus.io/docs/alerting/latest/alertmanager/ |
| **数据质量（自建 34 项业务断言）** | **保留自建** + 入库前 60 行声明式规则 | 34 项里一半是"文件 A 字段 = 文件 B 字段"和业务区间，GX/pandera 表达更长；dbt 官方支持平台不含 SQLite。只有新增表要列级约束时才值得看 pandera | https://docs.getdbt.com/docs/supported-data-platforms ， https://pandera.readthedocs.io/en/stable/ |
| **前端（手写 JS + terser + SW）** | **保留手写**，不换框架；补"版本收敛 + 错误上报 + 首屏预算" | 2.2MB 手写交互重写 = 数月风险，收益接近 0；瓶颈是首屏请求数与体积，不是渲染框架。SW 的 `skipWaiting()` 是主动绕过 MDN 说的安全默认（新 SW 默认停在 waiting） | https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API/Using_Service_Workers ， https://developers.cloudflare.com/workers/static-assets/ |
| **灾备（本地热备 + R2 三层 + 每日演练）** | **保留自建** + 补 public_fund 读回校验 | 每日真下载 + `integrity_check` + 行数对账，已超过多数团队；唯一缺口是最大库没做过日常恢复验证。借 restic 的 `check --read-data` 思路，不引工具 | https://restic.readthedocs.io/en/stable/045_working_with_repos.html |
| **多源健康（异源兜底 + 单轮退避）** | **保留自建** + 补跨轮次状态 | 熔断的本义是"跨请求记住失败"；本项目每个任务是独立进程，pybreaker 这类进程内库退出即丢状态，所以只能自己落一个小 JSON | https://martinfowler.com/bliki/CircuitBreaker.html |
| **备份保留策略** | **保留三层 R2（14/28/365）** | 已有分层 + 生命周期清理日志；restic/borg 的块级去重在"每天整库换一份"场景收益有限，`prune` 语义还会与现有分层打架 | 同上 |

**已投入但未达标的证据（不在本节重复立项，只在 P0-2 引用）**：告警降噪 3A/3B/3C 已上线，
本轮实测噪音仍是 10~11 条/天 —— 说明"判据/发送细节"层面的投入碰到了结构性下限，需要动"哪类消息该进 alert 群"。

---

## 4. 路线图

### 马上做（本周，5 件）

| # | 做什么 | 预期可观测变化（X → Y） | 验收用例 | 成本 | 风险 |
|---|---|---|---|---|---|
| 1 | **拆上传锁 + 超时梯度**：s06 显式 `R2_UPLOAD_LOCK_TIMEOUT=600`、挪 21:05；随后按产物域分锁（data-files / db-backup / kelly-snapshots / fund-nav） | s06 `退出码=124` 次数 4/12 次运行 → 0；全网最大等锁 3990s → <300s；`etf_national_team` 21:30 槽结束不晚于 22:00 | `grep -c "退出码=124" s06 日志`（近 7 天）=0；`grep -o "等待 R2 上传锁 [0-9]*s"` 最大值 <300 | A 1 小时；B 半天 | 分域锁写错会让同一产物被两个进程同时写；先做 A 验证一天再上 B |
| 2 | **腾磁盘**：部署不再全量 rsync DB（代码仓 DB 改为不复制/统一 REPO）+ staticdata 只备 JSON + 清 8 天份本地 etf 备份 | `df` 可用 13G → ≥19G；每次部署少写 ≈3.6G；三份 inode → 一份 | `stat -c '%i'` 三路径不再各自独立（或代码仓无 DB）；`df -h /` 可用 ≥19G；部署日志无"DB 同步"段 | 半天（云上）+ 1 小时（本机，含 §25 备份） | 有消费方直接从代码仓读库；必须先把路径统一再删副本，否则会读到空 |
| 3 | **告警出口分层 + 尺子设闸**：digest/recovery 移出 alert 群；escalation 合并进摘要；尺子退出码 1/2 | `alert_noise_count` 噪音 11 → ≤3 条/天（连续 7 天）；尺子 FAIL 时 CI/巡检能拿到非零退出码 | 连续 7 天跑尺子看 PASS；构造噪音超标样本断言 exit 1、台账缺失断言 exit 2 | 半天 | 真故障可能被"合并进摘要"后延后看到；必须保留 "被抑制条数" 计数 |
| 4 | **数据质量入库闸门（先告警后拦截）**：先拆因当月 49,295 行空值（新基金首行 vs 源缺失），再挂 5 个核心 upsert 的整批校验 | `fund_daily_nav` 当月 `nav_change_pct IS NULL` 从 49,295 → ≤9 月水平（≈16,000，即回到 3.6%）；`purchase_status=''` 当月 1,908 → 0；`collect_log` 出现 quality 类 error | `select substr(date,1,6),count(*) ... where nav_change_pct is null group by 1`（当月值环比）；注入 close=-1 的测试行断言整批未入库（内存库） | 1 天（含拆因） | 规则写太严会整批拒掉正常数据；先用 `DQ_GATE=warn` 跑一周再切 reject |
| 5 | **public_fund 备份读回校验（周频）**：verify_backup 加大库分支 | public_fund 的"可恢复"从"从未验证"→ 每周一次有证据；失败发 severe | 周任务日志含 `integrity ok` + 三表行数 diff=0 | 脚本 1 小时 + 10 分钟/周 | 下载 763MB 占出网；解压需 ≥4G 空间，脚本先判 |

### 一个月内

| # | 做什么 | 预期（X → Y） | 验收 | 成本 | 风险 |
|---|---|---|---|---|---|
| 6 | 首屏瘦身：冰点"近 X 月首次"改后端预算；overfit_monitor 可见即拉 | 首屏传输 2.42MB → ≤1.9MB；数据请求 15 → 13；DCL 7.3s → ≤6s | 无痕探针复测 `transferTotal` 与 `DATA_REQS`；断言请求清单不含 `sentiment-all.json` | 半天 | 后端加字段要同步 §22 三处产物；冰点判定逻辑不能变 |
| 7 | 前端错误上报 + 版本收敛 | JS 错误从"不可见" → 1% 采样可查；版本落后时长从"无上界" → ≤10s 自动收敛 | 注入 `throw new Error('probe')` 后 `/api/err` 收到记录；BUILD_ID 不一致时 10s 内 reload | 半天 | Worker 新增路由要防刷（限流/采样）；自动 reload 可能打断用户操作，需空闲条件 |
| 8 | 备站数据兜底链加 `ssd.fx8.store` + 跨域名一致性机检 | 主站 `/data/` 故障时备站仍能渲染（现为 100% 空壳）；域名漂移从"人工抽查"→ 自动告警 | 探针拦截 `ss.fx8.store/data/*` 返回 502，断言关键数字仍非空；一致性脚本 4 域名 md5 一致 | 半天 | ssd 无边缘缓存，回源慢；只做最后一级，且加开关 |
| 9 | 默认档单一事实源 + 闸门真按 S06 判 | 闸门从"14 键假绿"→"a9∪new14 24 键真守护"；页面/邮件差异要么为 0，要么显式标注 | 删任一 a9 专有键的判定分支 → 闸门 FAIL；恢复后 PASS | 小（闸门）+ 中（邮件切换需用户拍板） | 动真实外发行为必须先拍板（§23.7） |
| 10 | 调度：14 个无限超时补上限 + 真实依赖对加"前置就绪"闸门 | `systemctl show -p TimeoutStartUSec` 无限值 14 → 0；`public-fund-full` 运行中触发的 `check-data-gap` 等待/跳过而非读半程数据 | 注入 `sleep 999` 的隔离 unit 被 systemd 杀掉并留 failed；gap 任务日志出现等待记录 | 1 天 | 上限设太小会杀正常长任务（按 5149s 实测×余量） |
| 11 | 外部死手心跳（healthchecks.io 或 Worker cron） | 整机失联发现时间 ∞ → ≤15 分钟（heartbeat 方案）或 ≤25h（死手方案） | 停 ping 25h 收到外部告警；恢复后一轮内不再报 | 2 小时 | 第三方依赖；只加"外部视角"，不改现有告警链 |
| 12 | 回测产物加运行指纹（run_id/git_sha/data_cutoff/config_hash） | 任意数字从"无法溯源"→ 可回指哪版代码/哪份数据/哪套参数 | 连续两天 run_id 不同、config_hash 相同；两份 run 能一键 diff | 1~2 天 | 每天覆盖写，需注意产物体积；旧消费方兼容 |
| 13 | 规则版命中率独立口径 + 历史档案恢复 | 页面 30 日命中率从 `--` → 真实百分比；档案 26 → ~90 条（或明标起始日） | `stats.30d.n > 0`；页面出现非 `--` 数值 | 1 天 | 09-14 重置根因未证实，恢复失败就明标，不硬造 |

### 季度级

| # | 做什么 | 预期（X → Y） | 验收用例 | 成本 | 风险 |
|---|---|---|---|---|---|
| 14 | 快照表改增量 + 净值按年归档（P1-2） | 三表日写 4.9 万行 → <5 千；库年增 ≈4G → <1.5G | 改造后连续 3 个交易日：`insert/update 行数` <5 千/日；`select count(*)` 归档前后合计相等；页面"近 30 天评级变动"与改造前逐位一致 | 中 | 若需"按日回溯某基金当日外部评级"，得保留近 N 天+归档，不能只增量 |
| 15 | 数据契约黄金签名 + 权威源声明（P1-1） | 字段悄悄变 → CI/deploy 即 FAIL 并打印 diff | 人工删掉 `overview.json` 一个字段重跑导出 → 校验 FAIL 且打印缺失键路径；恢复后 PASS | 小~中 | 首次生成会把现存怪形状固化成基线，需人工过一遍 |
| 16 | 治理体量从 WARN 改硬约束（P1-21） | CLAUDE.md 月环比 ≤ +2%；每 agent 注入 ≤ 60KB（建议目标值，需先实测当前注入基线再定） | `scripts/gen_governance_size_report.py --check` 在环比 +2% 时退出非零；打印当月各对象字节与净增条款数 | 小~中 | 条款合并可能丢教训，退役须按 §5.3② 可逆归档 |
| 17 | 跨轮次源健康状态（P1-23） | 坏源不再每天被优先重试；采集批总耗时下降 | 人为让主源连续失败 3 轮 → 第 4 轮选源日志显示跳过该源并在半开时间窗探测；好源不被误标 | 小 | 阈值定错会长期拉黑好源，需半开探测 |
| 18 | 内容寻址 + 增量发布（方向6 唯一"值得评估"的大改） | 部署传输从"全量 1.2G" → 只传变更对象 | 连续两次部署（内容不改）第二次传输字节 ≈0；改 1 个文件只传 1 个对象且线上哈希==源哈希 | 大（多天，需拍板） | 要重建 manifest 与缓存失效逻辑，收益需先量化 |

---

## 5. 明确不做（含理由）

1. **不换数据库（SQLite → Postgres/DuckDB）**。当前崩点是"三副本 + 全量 rsync + 快照表全量重插"，
   换引擎这三件照样存在，甚至多一个常驻服务和备份对象。先做 P0-3 / P1-2，成本低一个数量级。
2. **不引入编排框架（Airflow / Dagster / Prefect）**。单机、单脚本、无分支 DAG；Airflow 官方要 ≥4GB 内存、
   且明说 SQLite 不得用于生产，本机总内存 3719MB，装了就是抢生产内存。
3. **不上 Prometheus + Grafana + Loki**。4G 机器装监控栈会挤掉采集；它给的指标趋势已由 `schedule_stats` + 34 项断言覆盖，
   而真正缺的"整机失联"它同样解决不了（同机）。
4. **不重写前端框架（Astro / Next / SvelteKit）**。2.2MB 手写交互重写是数月风险敞口，
   而所有版本串/SW/min 构建/防撕裂机制都建立在"单文件 + `?v=`"之上；先修版本收敛与错误上报。
5. **不引数据质量框架（Great Expectations / dbt / Soda）**。34 项断言是业务口径，这些框架表达不了，
   引进来就是维护两套；新增表写 30 行 `assert_schema` 就够。
6. **不再新增 check_* 闸门**。现有 33 个检查脚本（16,921 行）+ 41 条登记闸门，已经需要 `check_gate_registry.py`
   来守护闸门本身；其中 2 个还是死闸门。应先合并/退役/接线，不是再铺一层。
7. **不给 `history_overwrite_audit` 再加规则**。问题不是判据不够细，是 99.77% 假记录造成的信任崩塌 + 无保留策略；
   正确动作是清存量 + 定保留期 + 让真事件单独可见。
8. **不经用户拍板把邮件/飞书白名单从 NEW14 切 S06**。这是真实外发链路，实现报告明确写了"须用户另行拍板"（§23.7）；
   先做口径提示与逐条 diff 观察。
9. **不引 Sentry 做前端错误**。要改 CSP、加第三方脚本、多 200KB；`/api/err` 30 行就能覆盖"错在哪个 build"。
10. **不做"覆盖率门槛/全面铺测试"**。1931 用例 / 334s 已占 CI 78%；应先定向补三大盲区模块 + 约定按模块命名。

---

## 6. 未证实项清单（要什么证据才能定论）

| 项 | 现状 | 定论需要什么 |
|---|---|---|
| 09-14 每日速递历史档案从 90 条掉到 26 条的根因 | 只确认时间点与 09-12 部署路径 env 化、09-14 首跑重合；无直接日志 | 找到当时部署/覆盖日志或 staticdata/R2 旧快照，证明是覆盖还是迁移；或 git 旧版文件 |
| 今日"页面候选池 vs 邮件候选池"差 26 条 | 两端事实已核（默认 s06、effective_mode=a9、AI_MACRO_KEYS=14），差集未复算 | 用同一份 overview.json 跑 a9/new14 键集求交脚本，并给出逐条名单 |
| `check_posrating_parity.mjs` 最新是否通过 | 只确认机制存在，未重跑 | 跑一次闸门看退出码与 diff |
| 部署锁"优雅跳过"是否真造成某天产物漏上线 | 12 次跳过已证实，是否真漏未对账 | 逐案比对 10-19~10-27 的 R2 产物时间戳与部署日志 |
| `auto_trade_steps.json` 的"待人工"标记有无消费方 | 脚本与告警链未见读取 | 前端 grep + agent 侧读取点，或确认无人用 |
| CI ⑥⑦ 历史上"窗口差以外的真回归"发生率 | 未见 | 逐条翻 CI 失败日志（本次禁跑/未翻） |
| 47 个"死脚本"能否安全移走 | 只人工确认 7 个零引用脚本性质 | 逐个确认 27 个"仅 docs 提及"是否手工运维用 |
| R2 备份是否含告警台账/日志/config | 未展开 | 列 upload-claude-backup 的清单 |
| 云上曾到 92% 磁盘（现 78%）的原因 | 无历史采集 | 需要历史 df 记录或当时的清理日志 |
| 方向6 的 43 个 timer"全 Persistent、0 Restart、0 OnFailure" | 本次未复算（只复算了 timer 数与超时数） | `grep -l "Persistent=true"` / `Restart=` / `OnFailure=` 全量核 |
| P1 表中标"未复算"的 12 项数字（额度/行数/耗时） | 沿用方向报告单次取证 | 各给一次独立命令复算 |

---

## 7. 附录：六路报告索引 + 体检方法

| 方向 | 报告 | 大小 | 本报告引用 |
|---|---|---|---|
| 1 数据采集与存储 | `/tmp/system-audit-1-data.md` | 28.8KB | P0-4、P0-3、P0-5、P1-1/2/3/4 |
| 2 调度运维可观测灾备 | `/tmp/system-audit-2-ops.md` | 35.5KB | P0-1、P0-2、P1-5~10 |
| 3 分发展示层 | `/tmp/system-audit-3-frontend.md` | 25.2KB | P0-6、P0-7、P0-8、P1-17/18/19 |
| 4 业务算法与回测 | `/tmp/system-audit-4-algo.md` | 36.6KB | P1-11~16 |
| 5 工程 CI 测试治理 | `/tmp/system-audit-5-eng.md` | 29.6KB | P1-20/21/22、P0-3 同族 |
| 6 业界对标 | `/tmp/system-audit-6-bench.md` | 34.2KB | 第 3 节架构评估、P1-5/6/23 |
| 共同口径 | `/tmp/audit-brief-20261028.md` | 2.4KB | 报告格式与纪律 |

**本次合并用了哪些方法**（可复现）：
- 云上只读 SQL：`python3` + `sqlite3.connect("file:...?mode=ro", uri=True)`，查坏值计数、按月分布、审计表构成、全表行数；
- 云上只读 shell：`stat -c '%i %h %s %y %n'`、`df -h`、`du -sh`、`ls /etc/systemd/system/trade-*.timer | wc -l`、
  `grep -l "^TimeoutStartSec=0"`、`find data/logs -name "*deploy*" -size +10k | wc -l`；
- 云上只读尺子：`scripts/alert_noise_count.py --ledger ... --date <d>`（并实测其退出码）；
- 本地读码：`grep -n` / `sed -n` 定位到行号；实跑 `check_fade_keys_alignment.py --repo .`；
- 线上实测：无痕 Playwright（系统 Chrome、零 localStorage、零 SW）读 `performance.getEntriesByType('resource')`；
  `curl -D -` 读缓存头（禁 `-v/-i`）；三域名取版本串；`ssd` 直链 200 / 备站 404；
- 本机事实：`md5 -q` 比双树库、`app.db.DB_PATH` 实测、worktree 内 `data/` 列表。

**边界声明**：本次所有动作只读，未改代码、未部署、未发任何通知、未跑业务脚本；
本报告唯一写入 = 本文件 + `docs/pending-features-index.md` 的登记行。