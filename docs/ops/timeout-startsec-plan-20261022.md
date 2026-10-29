# 计划任务外层超时(TimeoutStartSec)建议值清单(2026-10-22,只读盘点 + 应用 + 复查)

> 状态:**第一批 7 个已应用(2026-10-22,见 §9),其中 4 个值同日复查修正**(原「P99×2」口径被历史实测反证,见 §9.1);第二批 / 第三批 14 个仍未应用(云上仍为 `TimeoutStartSec=0`),按新规则复查结果见 §10。
> 基线:`origin/main` = `7b767f9dc`;盘点时点 2026-10-22 13:43(北京时间)。
> 依据:稳定性评估报告 §5 单点 #5「21/43 个 unit 没设 TimeoutStartSec」、§7 P1-2。
> 目的:单机云上,一个挂死的任务会一直占着锁/内存,还可能挡住下一个定时任务;
> 给每个 unit 一个「按真实运行时长算出来」的外层封顶,挂了就杀掉,下一轮自愈/重跑。
>
> **口径取代关系**:**本文件取代** `docs/deploy/timeout-caliber-20260916.md` 的「未设超时 unit 口径」
> (旧口径 = 慢任务一律 `0`=无限等);旧文件作为**历史记录不追改**,仅供溯源。已设超时 unit 的现值体检仍见 §5。

## 1. 结论

- 全站 43 个 `trade-*.service`,**21 个原本没有设 `TimeoutStartSec`(等于无限等)**;其中 7 个已于 2026-10-22 应用(§9),剩 14 个待应用(§10)。
- 建议值口径(2026-10-22 复查后现行,旧口径已废):**新值 = max(实测历史 max × 1.2, 内层看门狗 × 2, 脚本头文档时长 × 1.2),向上取整到 60 秒倍数**;另设两条硬约束:
  1. **不低于 5 分钟下限**(300s):否则冷启动/网络抖动会把正常跑误杀;
  2. **必须大于脚本内层看门狗**:有内层 `run_to`/subprocess 超时的,外层还要 > 内层×2(逐个对照见 §10)。
  - 唯一例外:历史 max 明显由**已知外部故障**(如 R2 全局锁)造成且该故障另有独立治理项时,可用「**近期正常 max × 2**」并注明原因(gold-night 即此例)。
- 其中 **3 个 unit 近 30 天没有可用样本**(月频/季频 + journald 只留 ~7 天),
  建议值改用**脚本头注释里的文档时长 × 1.2** 兜底,并在表里明确标注「待实测后复算」,不假装是实测算出来的。
- 另外发现 3 个**已有**超时值的 unit 偏紧(`kelly-intraday-rerun` / `nextday-plan` / `public-fund-daily`),
  其中两个 P99 恰好等于现有上限 = 在超时边缘被砍,需先查是「真需要更久」还是「挂死」,**不要盲目调大掩盖问题**(见 §5)。
- ⚠️ **方法论教训(2026-10-22 复查新增,详见 §2.1)**:原口径依赖「P99×2」,但**增量样本≠全量样本**、**n≤2 的样本不得当 P99 用**;
  第一批 4 个值被历史实测反证即此病(stage0 用 n=1 增量样本 327s 当全量,实际历史全量 17395s)。

## 2. 数据来源与方法(可复核)

| 项 | 内容 |
|---|---|
| 当前值 | 云上 `/etc/systemd/system/trade-*.service` 的 `TimeoutStartSec=` 行(43 个全部读到,无缺行) |
| 样本源 A | `journalctl -u <unit> --since 2026-09-22`,按 `Starting ` / `Finished ` / `Failed ` 生命周期消息配对算单次时长;成功=`Finished`,失败=`Failed` |
| 样本源 B | 任务日志(`data/logs/*.log`)里 2026-09-22 之后的运行记录,复用 `scripts/gen_schedule_stats.py` 的 `parse_standard` / `parse_etf_nt` 解析器(不另写一份日志解析,避免第二实现漂移) |
| 合并 | A+B 合并计算;两路可能记录同一次运行(同一任务既有 journal 又有日志),**未按时间戳去重**——对 P99 影响有限(尾部样本少),复算时可凭 `end` 时间戳去重 |
| P99 | 最近秩法(nearest-rank):排序后取第 `ceil(0.99 × n)` 个;样本 n<100 时 P99 = 最大值(所以小样本数字偏保守) |
| 总样本 | journal 2505 条 + 任务日志 1436 条 = 3941 条 |
| 读云方式 | `ssh -o ConnectTimeout=10 -i ~/tdsignal.pem ubuntu@122.51.111.173`,每条远端命令都套 `timeout`;全程只读(只跑 `cat` / `journalctl` / `systemctl show`),未写任何文件、未 daemon-reload |

**诚实标注(局限)**

1. **journald 不是 30 天**:云上 journald 只保留约 7 天(200MB 轮转),实际最早样本 2026-10-15T16:44。
   所以「近 30 天」这半句只对**有任务日志的 unit**成立;journal 单独覆盖的 unit 实际只有 ~7 天。
2. **不是每个 unit 都有任务日志**:未登记进 `gen_schedule_stats.TASKS` 的 unit 只有 journal 一路,
   月频/季频任务在 7 天窗口里可能 0 样本。
3. **P99 受「已有超时砍断」影响**:已有超时值的 unit 若长期在边缘被杀,P99 会等于上限(见 §5),这类数字不能直接拿来算建议值。
4. 采集时点与样本窗口写死为 2026-09-22 ~ 2026-10-22;以后复算请改 `--since` 并按 §7 命令重跑。
5. **`parse_standard` 会静默丢弃 >3h 的整轮运行**(`gen_schedule_stats.py:36 MAX_GAP_SEC = 3*3600`,超限视为配对错位不入 pairs)。
   本表原「max」列因此**系统性偏低**:如 public-fund-full 真实最长 16614s(10-14 22:00→10-15 02:36,全量 9000 只正常跑完),
   解析器只报 5151.5s;update-all 真实最长 14912s(09-18),解析器只报 10055s。§10 复查已改用「原始 start/end 行配对」补长跑,并逐行标注来源。

### 2.1 方法论条款(2026-10-22 立,防再次「为了给个数而给个数」)

1. **n≤2 的样本不得直接当 P99 用**:P99 在 n<100 时退化为最大值,样本只有 1~2 个时它只是那一次的耗时,不代表分布尾部。
   凡建议值依赖 n≤2 样本,**必须另取历史全量 max 或脚本头文档时长交叉验证**,取三者(含内层看门狗×2)的最大值。
2. **增量样本 ≠ 全量样本**:同一脚本「补增量」和「补全量」耗时可能差一个数量级,不能拿增量那一轮当全量依据。
   (本次事故:stage0-overview 拿 2026-10-18 的 327s 增量样本当全量,而历史全量最长 17395s,660s 的建议值会把正常全量跑拦腰砍断。)
3. **每条建议值必须写出来源**:要么「历史 max(日期)+×1.2」,要么「内层看门狗 N×2」,要么「脚本头文档时长(行号)+×1.2」;
   写不出可复核来源的值不许进表。
4. **脚本头文档时长与实测全量冲突时,以实测全量为准并注明**:脚本头注释里的「~2.3h / ~6.2h」是作者当时的估计,
   不是实测;两者冲突时按**实测全量 max** 定值,并在表里写明「脚本头写 X,实测 Y,取实测」;**脚本头明显过时的顺手改注释**
   (本次未改 `scripts/` 代码,只在此登记待改,见 §9.2)。

### 2.2 第 8 轴:生成器回灌风险(#189 `--check-doc` 怎么防)

前面 7 个维度都在算「值给多少」;第 8 个维度是**值会不会被写回去时被人为改回旧值**。风险链:

1. 云上 unit 是**生成源**(`docs/deploy/systemd-units-20260912.md` §2 ini 块)渲染/比对的对象,而 doc §2 是仓库里的一份**副本**;
2. 若只改云上 unit + 刷新快照,**没同步 doc §2**,那么下次有人重跑生成器(`gen_systemd_units.py`)按 doc §2 重新出 unit 时,
   就会把 **doc 里的旧值(如 `TimeoutStartSec=0`)静默装回云上** ⇒ 前面的改动全白做,且没人会报错。
3. **防线 = #189 `--check-doc`**:`scripts/systemd_timeout_gradient_audit.py --check-doc` 把
   「doc §2 解析结果」与「权威 unit 源(云上 `--units-dir` 或仓库快照 `--dump`)」**逐字段全量比对**(`key=value` 多重集、顺序无关),
   任一字段不一致即 `exit 1`;`--align-doc` 则是把 doc §2 就地改写成权威源值(改文档,不碰云上)。
4. **挂载点**:`scripts/main-merge.sh:389-400` 的 **7.8 闸门**在合并主入口自动跑 `--check-doc`
   ⇒ doc §2 与快照不一致时**合不进 main**,「旧值回灌」在合并这一步被拦住,不靠人记着同步。
5. 配套:`--check-snapshot`(#191,云上 `cloud_unit_patrol` 每日 08:27)补另一半——
   「快照 == 云上当前」,消掉 `--check-doc` 只看「doc == 快照」时的快照陈旧窗口。

⇒ 所以 §4.3 的「云上改 → 快照 → doc §2 对齐」三步里,**第三步(doc §2)不是可选项**,它是第 8 轴的防线本身。

## 3. 21 个未设超时的 unit:建议值(逐行可执行)

「样本(成功)」= 总样本数(其中退出码为 0 的条数)。「依据」列写明来源(历史 max / 内层看门狗×2 / 脚本头文档时长),口径见 §1 与 §2.1。
> 已应用的 4 个值(2026-10-22 复查修正)在本表直接写**已应用值**,应用事实与云上核对见 §9.1;其余 14 个的复查结果见 §10。

| # | unit | P99 实测(s) | 样本(成功) | max(s) | 建议值 | 折算 | 依据 | 风险/备注 |
|---|---|---|---|---|---|---|---|---|
| 1 | `trade-backfill-evening.service` | 8829.0 | 106(102) | 9355.0 | 17700s | 295min | P99=8829.0s×2,n=106 | 长任务(2.5h);被杀则当日回填中断,次日 update_all 前须确认补完。无内层看门狗,封顶=唯一上限。 |
| 2 | `trade-backup-db.service` | 2793.2 | 6(6) | **10220**(09-29) | **12600s**(已应用) | 210min | 历史 max 10220s(09-29,含 R2 下载/上传)×1.2=12264 → 取 12600 | 旧值 5640s 也是 2×P99 但从 P99 样本里漏掉了 09-26(9797s)/09-29(10220s)两次 R2 慢跑,按旧值会砍断;备份被杀只是少一份当日备份,不动线上数据,下一轮续。 |
| 3 | `trade-etf-national-team.service` | 2671.7 | 44(25) | 2671.7 | 6240s | 104min | 历史 max 5170s(10-22 13:30→14:56,journal 墙钟)×1.2=6204 → 取 6240(§10 #5) | 44 样本中 19 次非零退出;被杀会缺当日 ETF 国家队数据,次日重跑可补。 |
| 4 | `trade-fapi-daily.service` | 61.3 | 6(6) | **639**(09-27) | **1800s**(已应用) | 30min | **内层 subprocess 超时 900s×2=1800s**(`scripts/fapi_bj_width_export.py:76 _R2_UPLOAD_TIMEOUT = 900`);历史 max 639s(09-27)×1.2=767s 也远小于此 | 旧值 300s **比内层 R2 上传超时(900s)还短**,等锁/上传时会先被 systemd 杀掉,连脚本自己的诊断输出都拿不到;现 1800s 保证内层先到。 |
| 5 | `trade-futures-backfill.service` | 4961.0 | 74(68) | 4961.0 | 13380s | 223min | 历史全量 max 11102s(09-18 20:05,日志)×1.2=13322 → 取 13380(§10 #3) | 回填按日写入,中断后次日续跑;不影响当日行情。 |
| 6 | `trade-gold-night.service` | 953.4 | 6(5) | **10615**(09-30)/近期正常 1336(10-01) | **2700s**(已应用) | 45min | **例外口径**:历史 max 10615s(09-30)是 R2 全局锁等待(~2h56m,日志显示等 `--skip-if-locked`),该故障由 R2 分锁优化独立治理;按近期正常 max 1336s(10-01)×2=2672 → 取 2700 | 锁复发时本任务被杀属**预期**(外层兜底生效),不因此再抬值;夜间数据延迟可重跑。无内层看门狗。 |
| 7 | `trade-intraday-snapshot.service` | 1526.0 | 1079(1079) | 5122.6 | 3060s | 51min | P99=1526.0s×2,n=1079 | **用户 2026-10-22 已拍板取 3060s**(P99×2 口径;接受约 45 天一次长跑被杀,代价 = 少一张快照、10 分钟后下一轮自动补);规则值 6180s 不采用。用户拍板优先于规则值。 |
| 8 | `trade-lab-auto.service` | 5401.0 | 36(35) | 5401.0 | 10860s | 181min | P99=5401.0s×2,n=36 | 样本 36<100 → P99=最大值(保守);lab 产物非交易关键,误杀影响小。 |
| 9 | `trade-lhb-backfill.service` | 5061.0 | 72(66) | 5061.0 | 18660s | 311min | 历史全量 max 15510s(09-18,日志)×1.2=18612 → 取 18660(§10 #4) | 回填中断次日续跑;18660s 覆盖历史全量 max 15510s 的 ×1.2。 |
| 10 | `trade-lof-track-index.service` | 154.1 | 1(1) | 154.1 | 360s | 6min | P99=154.1s×2,n=1 | 仅 1 个样本,P99=该样本;2×=308s 低于 5min 下限,按 6min 给,待样本积累复算。 |
| 11 | `trade-overfit-monitor.service` | 169.9 | 20(20) | 169.9 | 360s | 6min | P99=169.9s×2,n=20 | 只读监控,误杀只是少一次巡检;6min 已覆盖实测 170s 的 2 倍。 |
| 12 | `trade-pf-score-weekly.service` | 2052.1 | 1(1) | 2052.1 | 4140s | 69min | P99=2052.1s×2,n=1 | 仅 1 个样本,P99=max 保守;周频任务,误杀下周重跑。 |
| 13 | `trade-pf-stage0-manager.service` | — | 0(0) | — | 21600s | 360min | 无实测样本;脚本头注明自爬补任职历史 ~3h(`scripts/stage0_manager.sh:4`),按 2×3h 封顶 | 月频、11-01 才再次触发;6h 依脚本头文档值,首次实跑后须按 §1 新规则(实测 max×1.2 / 脚本头×1.2,取大者)复算。 |
| 14 | `trade-pf-stage0-nav.service` | — | 0(0) | — | 3600s | 60min | 无实测样本;脚本头注明 5 年净值分批断点续采(`scripts/stage0_nav.sh:4-5`),单次封顶 1h 不影响最终完成(下周续跑),待首个实测样本后按 §1 新规则复算 | 断点续采:封顶只降低单次进度,完成时间可能延后;若发现进度长期不推进,应改 6h。 |
| 15 | `trade-pf-stage0-overview.service` | 326.7 | 1(1) | **17395**(10-04) | **26820s**(已应用) | 447min | 历史全量 max 17395s(10-04 02:17→07:06)×1.2=20874;脚本头「~6.2h」=22320s×1.2=26784 → 向上取整 26820 | **定时是每周日 02:17(周频,不是月频)**。**该 unit 被杀代价高于普通任务**:断点进度文件在 `/tmp` 且非原子写,SIGTERM 会丢进度 → 下次仍从头补;加**内层 public_fund.lock** 撞锁直接跳过。原 660s 是拿 2026-10-18 的 327s **增量样本**当全量(实际那轮只补了几只),会砍断正常全量跑。 |
| 16 | `trade-pf-stage0-risk.service` | — | 0(0) | — | 32400s | 540min | 无实测样本;脚本头注明季报后逐只采 ~4.5h(`scripts/stage0_risk.sh:4`),按 2×4.5h 封顶 | 季度月(1/4/7/10)才真跑,下一次实测 2027-01;9h 依脚本头文档值,首次实跑后复算。 |
| 17 | `trade-public-fund-full.service` | 5151.5 | 6(4) | 5151.5 | 22680s | 378min | 脚本头 5.25h=18900s×1.2=22680(历史全量 max 16614s×1.2=19937,取大者;§10 #10) | 全量基金任务;6 样本中 2 次非零退出,封顶后被杀可次日重跑。 |
| 18 | `trade-public-fund-quarterly.service` | 2350.0 | 18(12) | 2350.0 | 4740s | 79min | P99=2350.0s×2,n=18 | 18 样本中 6 次非零退出;季度任务,中断下周重跑。 |
| 19 | `trade-turnover-backfill.service` | 7691.0 | 26(19) | 7691.0 | 27240s | 454min | 内层 `run_to` 合计 13620s(7200+900+2760+2760)×2=27240(§10 #9) | 必须大于内层 `run_to` 合计 13620s(227min);454min = 内层×2,倒挂=外杀内层未完成。 |
| 20 | `trade-update-all.service` | 10055.0 | 36(36) | 10055.0 | 20160s | 336min | P99=10055.0s×2,n=36 | 最长任务(2.8h)。若在 export/deploy 阶段被杀,deploy 可能半途;数据产物原子写,git push 中断需次日重跑确认。上线后首周重点看有无 >5h 长跑。 |
| 21 | `trade-us-stock-morning.service` | 7149.0 | 37(37) | 7149.0 | 14340s | 239min | P99=7149.0s×2,n=37 | 美股早间任务;被杀则当日美股数据缺失,可手动/下次重跑补。 |

> 注:`trade-pf-stage0-manager` / `-risk` / `-nav` 三个的「P99=—」是**没有样本**,不是漏算;
> 表里已改用脚本头注释的文档时长兜底,并写明「首次实跑后复算」。
> 若审核要求「必须全部由实测 P99 推导」,则这 3 个只能等有样本后再定值——本清单选择先给安全兜底,不让它们继续无限等。

> **本 5 条同步自 §10 复查表(2026-10-22 复核后修正)**:futures-backfill 9960→**13380**、lhb-backfill 10140→**18660**、etf-national-team 5400→**6240**、turnover-backfill 15420→**27240**、public-fund-full 10320→**22680**(对应 §10 表 #3/#4/#5/#9/#10)。
> 其余行未动:已应用的 7 行见 §9 / §9.1;`intraday-snapshot` 见 §7.2 用户拍板(3060s)。

## 4. 怎么应用(本次**未执行**,留给后续上线)

### 4.1 为什么不能只 `systemctl edit`(drop-in)

仓库有两道一致性检查依赖**主 unit 文件**:

- `scripts/cloud_unit_patrol.sh`(**每日 08:27**:云上 `trade-cloud-unit-patrol.timer` `OnCalendar=*-*-* 08:27:00`)比对云上 `/etc/systemd/system/trade-*.{service,timer}` vs **云上仓库**里的快照 `/home/ubuntu/code/trade-data-signal/docs/deploy/systemd-units-cloud-snapshot.txt`——比对源是**云上仓库**该文件(脚本取 `$GIT_REPO/docs/deploy/...`),**不是本机工作区那份**,漂移就告警;
- `scripts/main-merge.sh` 用 `systemd_timeout_gradient_audit.py --check-doc` 比对 doc §2 生成源 vs 快照;
- `systemd_timeout_gradient_audit.py` 读 unit 文件(`--units-dir` / `--dump`),**不读 drop-in**。

所以用 drop-in 虽然 systemd 生效,但巡检/审计会看到外层仍是 0(假阴性)。**正确做法:直接改主 unit 文件,并同一批刷新快照与 doc §2。**

### 4.2 单 unit 应用模板(云上执行;`<SEC>` 换成上表建议值)

```bash
U=trade-update-all.service
sudo cp -a "/etc/systemd/system/$U" "/etc/systemd/system/$U.bak-20261022"
# 幂等写入:删掉旧的 TimeoutStartSec,在 [Service] 段尾插一行(不存在则追加段)
sudo python3 - "$U" 20160 <<'PY'
import re, sys
path, sec = "/etc/systemd/system/" + sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8").read()
text = re.sub(r"(?m)^TimeoutStartSec=.*\n", "", text)
if "[Service]" not in text:
    text += "\n[Service]\n"
text = text.replace("[Service]\n", f"[Service]\nTimeoutStartSec={sec}\n", 1)
open(path, "w", encoding="utf-8").write(text)
PY
sudo systemctl daemon-reload
systemctl show "$U" -p TimeoutStartUSec        # 应显示建议值
```

`sudo systemctl show` 回来若是建议值即生效;**不要**在应用后立刻重启 timer,下一轮触发自然生效。
回滚 = 把 `.bak-20261022` 拷回 + `daemon-reload`。

### 4.2.1 回滚源:临时备份 vs 持久回滚源(2026-10-22 补)

- **云上 `/tmp/timeoutsec-bak-*` 只算临时备份**:云上 `/tmp` 重启即失(不做持久化),不能当唯一回滚依据。
- **权威回滚源 = git 快照**(仓库内固化,任何时候都能取回):
  - **原始态**(21 个未设超时的 unit 全部 `TimeoutStartSec=0`):`git show 6fe1c59c2^:docs/deploy/systemd-units-cloud-snapshot.txt`
    (即 `5a0e654b7` 时的快照;实测 43 条 `TimeoutStartSec` 行中 21 条为 `=0`)。
  - **第一批应用态**(7 个值,其中 4 个后被复查修正):`git show 6fe1c59c2:docs/deploy/systemd-units-cloud-snapshot.txt`
  - **修正后 / 当前态**:`git show ced9366b6:docs/deploy/systemd-units-cloud-snapshot.txt`
- 回滚步骤(目标态换成任意上述 commit 均可):
  1. 取快照:`git show <commit>:docs/deploy/systemd-units-cloud-snapshot.txt > /tmp/snapshot-target.txt`
  2. 按 `@@@FILE:<name>` 切出目标 unit 段,写回云上 `/etc/systemd/system/<name>`
     (写前仍先 `cp -a` 现文件到 `/tmp/timeoutsec-bak-<日期>/`);
  3. `sudo systemctl daemon-reload`;
  4. 验:`python3 scripts/systemd_timeout_gradient_audit.py --dump /tmp/snapshot-target.txt --check-snapshot`
     (云上可直接用 `--units-dir /etc/systemd/system --check-snapshot`),rc=0 即云上已回到目标态。

### 4.3 同批必做的三件(否则巡检告警/合并被拦)

```bash
# ① 云上刷新快照(在云上仓库目录执行;@@@FILE: 格式与现快照一致)
cd /home/ubuntu/code/trade-data
{ for f in /etc/systemd/system/trade-*.service /etc/systemd/system/trade-*.timer; do
    echo "@@@FILE:$(basename "$f")"; sudo cat "$f"; done; } \
  > docs/deploy/systemd-units-cloud-snapshot.txt
# ② 本机对齐 doc §2 生成源(否则 --check-doc FAIL)
.venv/bin/python3 scripts/systemd_timeout_gradient_audit.py \
  --dump docs/deploy/systemd-units-cloud-snapshot.txt --align-doc
# ③ 两道闸门都跑绿再提交
.venv/bin/python3 scripts/systemd_timeout_gradient_audit.py \
  --dump docs/deploy/systemd-units-cloud-snapshot.txt --check-doc
.venv/bin/python3 scripts/systemd_timeout_gradient_audit.py \
  --dump docs/deploy/systemd-units-cloud-snapshot.txt --check-snapshot
```

> 第 ③ 步在云上也可直接跑 `--check-snapshot --units-dir /etc/systemd/system`(不加 `--dump`)。
> 注意:`cloud_unit_patrol` 在「改完 unit」到「快照合并进 main」之间会报一次漂移(预期内),
> 尽量在盘后低峰一次做完,别分散成多天。

### 4.4 建议应用顺序(先轻后重,每批观察 24h)

1. **第一批(低风险、短任务)**:`fapi-daily` / `lof-track-index` / `overfit-monitor` /
   `pf-score-weekly` / `pf-stage0-overview` / `backup-db` / `gold-night`。
2. **第二批(中长任务)**:`etf-national-team` / `public-fund-quarterly` / `public-fund-full` /
   `futures-backfill` / `lhb-backfill` / `lab-auto`。
3. **第三批(最长、影响面大)**:`update-all` / `turnover-backfill` / `intraday-snapshot` /
   `backfill-evening` / `us-stock-morning` / `pf-stage0-*`。
4. 每批应用后看:**有没有出现 `Failed ... timeout` 生命周期消息**、次日任务是否正常补跑;
   若某 unit 在建议值内被杀,先看 §3 风险列,再决定调大还是查挂死。

## 5. 既有超时值的 22 个 unit:体检结果

口径同上(P99×2 与现有值比)。**`偏紧` 不等于要调大** —— 两处 P99 恰好等于现有上限,
说明是「跑到上限被砍」而不是「正常需要这么久」,要先查根因。

| unit | 现有值 | P99(全部) | P99(成功) | 样本(成功) | max | 2×P99 | 判定 |
|---|---|---|---|---|---|---|---|
| `trade-ab-direction-anchor.service` | 600s | 1.3 | 1.3 | 6(6) | 1.3 | 60 | OK |
| `trade-alert-weekly-review.service` | 600s | 0.3 | 0.3 | 2(2) | 0.3 | 60 | OK |
| `trade-brief-push.service` | 600s | 3.7 | 3.7 | 6(6) | 3.7 | 60 | OK |
| `trade-check-data-gap.service` | 600s | 39.0 | 39.0 | 20(20) | 39.0 | 120 | OK |
| `trade-check-monitor-heartbeat.service` | 600s | 0.1 | 0.1 | 594(594) | 4.1 | 60 | OK |
| `trade-cloud-unit-patrol.service` | 600s | 4.0 | 1.0 | 25(23) | 4.0 | 60 | OK |
| `trade-daily-brief.service` | 1740s | 267.3 | 267.3 | 6(6) | 267.3 | 540 | OK |
| `trade-daily-summary-supplement.service` | 600s | 6.0 | 6.0 | 6(6) | 6.0 | 60 | OK |
| `trade-etf-track-index.service` | 600s | 33.4 | 33.4 | 1(1) | 33.4 | 120 | OK |
| `trade-fetch-news.service` | 1080s | 116.8 | 116.8 | 296(296) | 306.0 | 240 | OK |
| `trade-freeze-orphan-cleanup.service` | 600s | 0.2 | 0.2 | 1(1) | 0.2 | 60 | OK |
| `trade-kelly-intraday-rerun.service` | 600s | 600.3 | 64.3 | 7(5) | 600.3 | 1260 | **偏紧,先查根因** |
| `trade-nextday-gap-check.service` | 1800s | 352.8 | 352.8 | 28(23) | 352.8 | 720 | OK |
| `trade-nextday-plan.service` | 600s | 492.0 | 457.0 | 21(14) | 492.0 | 1020 | **偏紧** |
| `trade-pf-score-daily.service` | 600s | 117.6 | 117.6 | 6(6) | 117.6 | 240 | OK |
| `trade-public-fund-daily.service` | 900s | 900.2 | 1.1 | 12(4) | 900.2 | 1860 | **偏紧,先查根因** |
| `trade-public-fund-estimation.service` | 600s | 8.1 | 8.1 | 27(27) | 8.1 | 60 | OK |
| `trade-r2-consistency.service` | 960s | 407.0 | 407.0 | 25(14) | 407.0 | 840 | OK |
| `trade-rzhb-backfill.service` | 600s | 65.6 | 65.6 | 73(73) | 65.6 | 180 | OK |
| `trade-s06-snapshot.service` | 7020s | 1523.0 | 902.0 | 18(14) | 1523.0 | 3060 | OK |
| `trade-schedule-monitor.service` | 600s | 45.4 | 45.4 | 593(593) | 129.4 | 120 | OK |
| `trade-self-heal.service` | 600s | 40.9 | 40.9 | 593(593) | 47.2 | 120 | OK |

**三处偏紧的单独说明(本清单不给调大建议,先查因)**

- `trade-kelly-intraday-rerun`:7 个样本 5 成功,失败 2 次时长≈600s = 撞上限;成功样本 P99 仅 64.3s。
  ⇒ 大概率是偶发挂住(网络/锁等待),应先看对应日志定位,再决定「调大到 1260s」还是「修挂住本身」。
- `trade-public-fund-daily`:12 个样本只有 4 个成功,成功样本 P99 仅 1.1s(!),失败 8 次≈900s 撞上限。
  ⇒ 正常路径是秒级,900s 被杀说明是**卡住等锁/等外部接口**,调大只会让它卡更久,建议先查锁竞争。
> **更正（2026-10-29）**：本条「成功样本 P99=1.1s」结论错误——那 4 个成功样本是周末非交易日跳过（实测同款 2.3–2.9s / 日志 228 字节），被误当成正常路径样本污染了统计。真实工作日耗时 845–890s。详见 docs/ops/pf-daily-timeout-rca-20261029.md。
- `trade-nextday-plan`:21 个样本 14 成功,P99 492s 已接近 600s,2×P99=1020s > 600s。
  ⇒ 属于「正常慢」还是「偶发慢」需看成功样本分布;可先按 2×P99 调到 1020s,属低风险(只读生成明日计划)。
  这一条与本清单主线(21 个无超时)分开处理,不混在同一批。

## 6. 复现命令(谁都能重算上表)

### 6.1 单 unit 时长(P99 / 样本数 / max)

把 `-u` 后的 unit 换掉即可;`--since` 按需改窗口。

```bash
journalctl -u trade-update-all.service --since '2026-09-22' --no-pager -o short-unix 2>/dev/null |
awk '/Starting /{s=$1} /Finished |Failed /{if(s){print $1-s; s=0}}' |
sort -n |
awk '{a[NR]=$1} END{if(NR==0){print "n=0";exit}
     print "n="NR" P99="a[int((99*NR+99)/100)]" max="a[NR]}'
```

一次跑完 21 个(把 unit 清单粘进 for):

```bash
for U in trade-backfill-evening trade-backup-db trade-etf-national-team trade-fapi-daily \
         trade-futures-backfill trade-gold-night trade-intraday-snapshot trade-lab-auto \
         trade-lhb-backfill trade-lof-track-index trade-overfit-monitor trade-pf-score-weekly \
         trade-pf-stage0-manager trade-pf-stage0-nav trade-pf-stage0-overview \
         trade-pf-stage0-risk trade-public-fund-full trade-public-fund-quarterly \
         trade-turnover-backfill trade-update-all trade-us-stock-morning; do
  printf '%s\t' "$U"
  journalctl -u "$U.service" --since '2026-09-22' --no-pager -o short-unix 2>/dev/null |
  awk '/Starting /{s=$1} /Finished |Failed /{if(s){print $1-s; s=0}}' |
  sort -n | awk '{a[NR]=$1} END{if(NR==0){print "n=0";exit}
        print "n="NR" P99="a[int((99*NR+99)/100)]" max="a[NR]}'
done
```

### 6.2 任务日志补 30 天样本(源 B)

`<log>` / `<script>` 取 `scripts/gen_schedule_stats.py` 的 `TASKS` 表(`task` → `log` / `script`)。

```bash
.venv/bin/python3 - <<'PY'
import sys; from pathlib import Path
sys.path.insert(0, "scripts")
import gen_schedule_stats as g
task = "update_all"                      # 换成目标任务
spec = next(t for t in g.TASKS if t["task"] == task)
pairs, _ = g.parse_standard(Path("data/logs") / spec["log"], spec["script"])
durs = sorted(p[3] for p in pairs if p[1].date().isoformat() >= "2026-09-22")
print("n=", len(durs), "P99=", durs[int((99*len(durs)+99)/100)-1] if durs else None,
      "max=", durs[-1] if durs else None)
PY
```

### 6.3 当前值与内层看门狗(静态核对)

```bash
# 当前外层值
grep -H '^TimeoutStartSec' /etc/systemd/system/trade-*.service
# 外层 vs 内层 run_to 串行合计(现有工具,无内层会标「外层即唯一看门狗」)
.venv/bin/python3 scripts/systemd_timeout_gradient_audit.py --units-dir /etc/systemd/system
```

## 7. 应用前必须知道的两个口子(2026-10-22 审查补充)

### 7.1 自愈重跑的子进程不受 `TimeoutStartSec` 约束(没有外层超时兜底)

`scripts/self_heal.sh` 触发重跑的方式是 `nohup bash scripts/<task>.sh >> data/logs/<task>_heal.log 2>&1 &`,
然后本脚本立刻 `exit 0`。由此产生两个后果:

1. **`TimeoutStartSec` 管不到重跑**:它约束的是 unit 自己的启动阶段(主进程),而重跑是后台孙子进程;
   `self_heal.sh` 秒级退出后,unit 认为"跑完了",重跑还在跑。
2. **`KillMode=process` 时连 unit 停止都不会顺手清掉它**:systemd 只给主进程发信号,cgroup 里剩下的
   重跑进程继续活着(这也是自愈重跑能脱离 unit 生命周期的原因,是设计意图,不是 bug)。

⇒ **自愈重跑的时长上限只由各任务脚本自己的内部超时/看门狗(`run_to` 之类)决定**;某些脚本没有内层
超时,就等于**完全没有超时兜底**(挂了会一直挂着,直到下次机器重启或人工清理)。
本批只调整外层 `TimeoutStartSec`,**不会**改变这条;要不要给 `HEAL_ACTIONS` 的重跑命令加一层显式
`timeout <秒>`(秒数按 §6.2 实测 max×1.2 定),需要单独评估后另行拍板,不与本批混在一起改。

### 7.2 `intraday-snapshot` 的 3060s 是「会砍掉历史极端长跑」的口径(**2026-10-22 已拍板 3060s**)

§3 表里 `trade-intraday-snapshot.service` 的建议值是 **3060s(P99 1526.0s×2)**;但同一份样本里
实测 **max = 5122.6s(85min,该次还是成功的)**,n=1079。两条口径的结果不同:

| 口径 | 值 | 代价 | 依据 |
|---|---|---|---|
| P99×2(本表建议) | 3060s | 历史上会砍掉 1/1079 次(那次成功的长跑);被杀只少一张快照,10min 后下一轮补 | n=1079 实测 |
| max×1.2(非本表口径) | ≈6200s | 不砍历史样本;极端挂死时多挂 ~1h 才被杀 | 同上,另需确认 85min 长跑是否正常业务 |

**这两条都要用户拍板后才能应用,实施方不得自行选 3060**(拍板结论见下):
- 选 3060 = 接受「1/1079 概率少一张快照」的取舍;
- 选 6200 = 接受「极端挂死时外层要等 ~1h」的取舍;

拍板结果要写回本表「建议值/已应用值」列并注明口径,否则后续复核会再次对不上。

> **2026-10-22 复查补**:按 §1 现行规则(历史 max×1.2),`intraday-snapshot` 的规则值是 **6180s**
> (max 5120s(10-19 09:25 成功长跑)×1.2=6144,向上取整 60 倍数),与旧「max×1.2≈6200」一致。

> **2026-10-22 拍板(最终)**:用户已拍板取 **3060s**(P99×2 口径;接受约 45 天一次长跑被杀,代价 = 少一张快照、
> 10 分钟后下一轮自动补);**规则值 6180s 不采用,用户拍板优先于规则值**。本批仍未应用到云上(状态见 `#306`)。

## 8. 后续

- 第一批 7 个已应用并同批完成三处同步(§9);**7 天后(2026-10-29 之后)复核一次**有无 `Failed ... timeout`。
- 第二批 / 第三批 14 个:按 §10 复查表的值再走一轮「云上改 → 快照 → doc §2」同一批(**本次未应用**)。
- 3 个无样本 unit(manager / risk / nav)在首次真实运行后按 §10 重算,替换兜底值。
- `intraday-snapshot` 已按 §7.2 拍板取 **3060s**(2026-10-22);云上应用与第二批一起走(在此之前**保持现状不改**)。
- 自愈重跑的超时兜底按 §7.1 单独评估(是否给重跑命令加 `timeout`),不在本批范围。
- 本文 §9 是**已应用事实**(与云上一致);§3 其余 14 行与 §10 仍是**建议**,不构成已应用事实;上线动作与快照/doc 同步必须同一批完成(§4.3)。

## 9. 第一批应用记录(2026-10-22)

**只应用了 §4.4 第一批 7 个 unit**;§3 表内其余 14 个(第二批 / 第三批)**仍为 `TimeoutStartSec=0`(无限等)**,所以没有把 §3「建议值」列整体改名成「已应用值」——那会把未应用的 14 个也标成已应用(§22 一致性:文档不得与生产实况相反)。逐 unit 应用事实登记在本节。

| unit | 改前 | 已应用值 | 云上核对(`systemctl show -p TimeoutStartUSec`) |
|---|---|---|---|
| `trade-fapi-daily.service` | 0 | **300s** | 5min ✓ |
| `trade-lof-track-index.service` | 0 | **360s** | 6min ✓ |
| `trade-overfit-monitor.service` | 0 | **360s** | 6min ✓ |
| `trade-pf-score-weekly.service` | 0 | **4140s** | 1h 9min ✓ |
| `trade-pf-stage0-overview.service` | 0 | **660s** | 11min ✓ |
| `trade-backup-db.service` | 0 | **5640s** | 1h 34min ✓ |
| `trade-gold-night.service` | 0 | **1920s** | 32min ✓ |

- 三处同步已同批完成:云上 `/etc/systemd/system/*.service` → 仓库快照 `docs/deploy/systemd-units-cloud-snapshot.txt`(从云上重新 dump,非手改)→ doc §2 生成源(`docs/deploy/systemd-units-20260912.md`,用 `systemd_timeout_gradient_audit.py --align-doc` 对齐)。#189 `--check-doc` 与 `--check-snapshot` 均 PASS。
- 每 unit 只改 `TimeoutStartSec` 这一行(改前改后 diff 逐文件确认只有 1 行);未 restart / start 任何服务;`daemon-reload` 时 `systemctl list-jobs` 有 3 个**不属于本批**的任务在跑(turnover-backfill / etf-national-team / public-fund-full),reload 前后均 `running`,未受影响。
- 改前备份:云上 `/tmp/timeoutsec-bak-20261022/<unit>.service`(回滚 = 拷回 + `daemon-reload`)。
- 待办:**7 天后(2026-10-29 之后)复核一次**——查这 7 个 unit 有无 `Failed ... timeout` 生命周期消息、次日任务是否正常补跑;若某 unit 在建议值内被杀,先看 §3 风险列再决定调大还是查挂死。

### 9.1 第一批 4 个值复查修正(2026-10-22 晚,云上已生效)

依据:独立审查判定原 4 个值被历史实测反证。本次**自己从云上日志复算历史 max**(不采信审查给的数字),再按 §1 现行规则定值。

复算方法:`journalctl -u <unit> --since 2026-09-01`(云上 journald 只留 ~7 天)+ `data/logs/` 全历史 start/end 行配对:
stage0 用 `stage0-overview.log`、fapi 用 `fapi_daily_launchd.log`、gold 用 `gold_night_YYYYMMDD_0240.log`、backup 用 `backup_db_YYYYMMDD_HHMM.log`。

| unit | 复算历史 max(日期) | 样本数 | 旧值 | **新值** | 依据 |
|---|---|---|---|---|---|
| `trade-pf-stage0-overview.service` | **17395s**(2026-10-04 02:17→07:06,全量 rc=0);次长 11726s(09-13 21:26→09-14 00:41) | 7 轮(全量 2 轮 + 1 轮 rc=1 中途结束 + 4 轮秒级空跑/增量) | 660s | **26820s** | 17395×1.2=20874;脚本头「~6.2h」=22320×1.2=26784 → 26820 |
| `trade-fapi-daily.service` | **639s**(09-27);次长 502s(09-26)/397s(10-10) | 39 | 300s | **1800s** | 内层 subprocess 900s(`fapi_bj_width_export.py:76`)×2 |
| `trade-gold-night.service` | **10615s**(09-30,R2 全局锁等待);近期正常 max 1336s(10-01),次 1277s(10-14) | 39 | 1920s | **2700s** | 例外口径:近期正常 max 1336×2=2672 → 2700(R2 锁由独立治理项负责) |
| `trade-backup-db.service` | **10220s**(09-29);9797s(09-26) | 41 | 5640s | **12600s** | 10220×1.2=12264 → 12600 |

**与审查表数字的差异**:stage0 审查写 17393s、本次复算 17395s(+2s,日志行秒级时间戳取整);fapi/gold/backup 与审查表一致。
**与任务书目标值的差异(诚实标注)**:任务书原拟 stage0 = 25200s(7h),那是「脚本头 6.2h 直接取 7h」的算法、**漏了 ×1.2**;按本文件写死的规则应为 26784→26820,本表取 26820(更大、更保守,不影响其它单位)。

**云上生效核对(2026-10-22 22:58,`systemctl show -p TimeoutStartUSec`)**

| unit | 文件 `TimeoutStartSec=` | `systemctl show` |
|---|---|---|
| `trade-pf-stage0-overview.service` | 26820 | 7h 27min ✓ |
| `trade-fapi-daily.service` | 1800 | 30min ✓ |
| `trade-gold-night.service` | 2700 | 45min ✓ |
| `trade-backup-db.service` | 12600 | 3h 30min ✓ |

- 备份:云上 `/tmp/timeoutsec-bak-20261022/<unit>.service.v2`(= 旧值 660/300/1920/5640);回滚 = 拷回 + `daemon-reload`。
- 未 restart / stop / start 任何服务;`daemon-reload` 在盘后 22:58 执行(本机与云上均无盘后定时任务重叠)。
- 三处同步:云上 unit → 仓库快照(从云上重新 dump,`diff` 仅这 4 行)→ doc §2(`--align-doc` 对齐 4 处);#189 `--check-doc` / `--check-snapshot` 均 rc=0。

### 9.2 脚本头文档时长 vs 实测:7 个已应用值逐个核对(2026-10-22 按 §2.1 第 4 条复查)

口径 = §2.1 第 4 条:**脚本头文档时长与实测全量冲突时,以实测全量为准并注明**。逐个读脚本头(本次只核对,未改 `scripts/` 任何文件):

| unit | 已应用值 | 脚本头写什么 | 实测依据 | 结论 |
|---|---|---|---|---|
| `trade-fapi-daily` | 1800s | `fapi_daily_syn.sh` 头无时长描述 | 内层 subprocess 900s(`fapi_bj_width_export.py:76,102`)×2 | 无冲突 |
| `trade-lof-track-index` | 360s | `fetch_lof_track_index.py` 头无时长描述(只写数据源稳定性) | P99 154.1s(n=1)×2 → 5min 下限取 360 | 无冲突 |
| `trade-overfit-monitor` | 360s | `overfit_monitor.sh` 头无时长描述(只写时点/依赖) | P99 169.9s(n=20)×2 → 360 | 无冲突 |
| `trade-pf-score-weekly` | 4140s | `pf_score_weekly.sh:5` 写「全量27409只~2.3h」(≈8280s;×1.2=9936) | **实测全量约 34min**(P99 2052.1s,n=1);4140 = 2052.1×2 | **冲突 → 取实测**(按 §2.1 第 4 条);脚本头 2.3h 明显过时,建议顺手改注释(本批不动代码) |
| `trade-pf-stage0-overview` | 26820s | `stage0_overview.sh:5` 写「~6.2h」=22320s;×1.2=26784 → 26820 | 历史全量 max 17395s(10-04)×1.2=20874,小于脚本头派生值 | **无冲突**(取两者较大 = 脚本头×1.2) |
| `trade-backup-db` | 12600s | `backup_db.sh` 头无时长描述(只写备份语义/保留期) | 历史 max 10220s(09-29)×1.2=12264 → 12600 | 无冲突 |
| `trade-gold-night` | 2700s | `gold_night.sh` 头无时长描述(只写闸门/锁/时点) | 近期正常 max 1336s(10-01)×2=2672 → 2700(例外口径) | 无冲突 |

> 小注:`trade-backup-db` 的历史 max 10220s(09-29)含 R2 下载/上传慢段,已按 §1 例外说明处理;与脚本头无冲突。
> **gold-night 的 R2 分锁「独立治理项」立案状态(A8 核查)**:在 `docs/pending-features-index.md` grep「分锁」**0 命中**,
> 「上传锁 / R2 锁」只命中 #129(R2 独占锁事故)/#237(pre-upload 备份)/#258(R2 锁等待计入预算)等**在办条目,均非本条治理项**
> ⇒ **未立案,建议新立案**,本批已按 B2 登记为 **#308**「R2 上传全局锁独立治理(超时兜底依赖项)」。
> 在 #308 落地前,gold-night 的 2700s 属**预期内例外**(锁复发时任务被杀 = 外层兜底生效,不因此抬值)。

## 10. 剩余 14 个未上云 unit:按新规则复查(2026-10-22,**只落文档,未应用**)

口径 = §1 现行规则。历史 max 两路来源:`journalctl`(云上只留 ~7 天)+ `data/logs` **全历史原始 start/end 行配对**(补 `parse_standard` 丢弃的 >3h 轮,见 §2 局限 5);
「内层看门狗」用脚本实文(`grep run_to` / `timeout`)。**复查建议值 = 规则值;若计划原值已 ≥ 规则值,保留原值(更保守,复查不向下调)。**

| # | unit | 历史 max(日期,来源) | n | 内层看门狗 | 规则值 | 计划原值 | 复查结论 |
|---|---|---|---|---|---|---|---|
| 1 | `trade-update-all.service` | 14912s(09-18,日志) | 40 | 无 | 17940 | 20160 | **保持 20160**(原 max 10055 漏了 >3h 长跑,值仍够) |
| 2 | `trade-backfill-evening.service` | 14437s(09-20 16:35,日志) | 117 | 无 | 17340 | 17700 | **保持 17700**(同上,max 更正) |
| 3 | `trade-futures-backfill.service` | 11102s(09-18 20:05,日志) | 79 | 无 | 13380 | 9960 | **改 → 13380**(原值会砍断 11102s 正常长跑) |
| 4 | `trade-lhb-backfill.service` | 15510s(09-18,日志) | 79 | 无 | 18660 | 10140 | **改 → 18660**(同上) |
| 5 | `trade-etf-national-team.service` | 5170s(10-22 13:30→14:56,journal) | 12(journal) | 无 | 6240 | 5400 | **改 → 6240**(日志解析器给的 204s 是完成行「耗时」字段、不是墙钟;journal 才是墙钟) |
| 6 | `trade-intraday-snapshot.service` | 5120s(10-19 09:25,成功长跑) | 1158 | 无 | 6180 | 3060 | **已拍板 3060s(2026-10-22,§7.2)**:P99×2 口径,规则值 6180 不采用,用户拍板优先;未上云 |
| 7 | `trade-lab-auto.service` | 5401s(09-22,日志) | 39 | 无 | 6540 | 10860 | **保持** |
| 8 | `trade-us-stock-morning.service` | 11678s(09-20,日志) | 38 | 无 | 14040 | 14340 | **保持**(max 更正) |
| 9 | `trade-turnover-backfill.service` | 7691s(09-24,exit=124=内层超时) | 27 | **13620**(7200+900+2760+2760) | 27240(内层×2) | 15420 | **改 → 27240**(原值只比内层多 1800s,不满足「外层 > 内层×2」) |
| 10 | `trade-public-fund-full.service` | 16614s(10-14 22:00→10-15 02:36,全量 9000 只正常跑完) | 40 | 无 | 22680(脚本头 5.25h=18900×1.2;hist 19980) | 10320 | **改 → 22680**(原值会砍断 16614s 全量跑) |
| 11 | `trade-public-fund-quarterly.service` | 2350s(journal) | 18(journal)/117(日志) | 无 | 2820 | 4740 | **保持** |
| 12 | `trade-pf-stage0-manager.service` | 无样本 | 0 | 无 | 12960(脚本头 3h×1.2) | 21600 | **保持**(零样本月频,保留旧 2× 兜底更稳;规则值记此备查) |
| 13 | `trade-pf-stage0-nav.service` | 无样本 | 0 | 无 | 脚本头无时长(断点续采) | 3600 | **保持**(断点续采,单次封顶只影响进度) |
| 14 | `trade-pf-stage0-risk.service` | 无样本 | 0 | 无 | 19440(脚本头 4.5h×1.2) | 32400 | **保持**(同 manager) |

**内层超时逐个对照(2026-10-22 补:shell 层 + Python 层实扫)**

> ⚠️ **修正上一版结论**:上一版写「其余 13 个无内层看门狗」,那是**只扫 shell 的结论,不成立**——
> 它只 grep 了 `run_to` / shell `timeout`。本次按 `grep -rn "subprocess\.\(run\|Popen\|call\|check_output\)" scripts/*.py` 实扫后发现
> **Python 层普遍存在内层等待**;`systemd_timeout_gradient_audit.py` 的 docstring 也自己写明「Python 侧 subprocess timeout 不计入,
> 这类 service 判定为无 shell 内层看门狗」⇒ 旧表述只是**工具口径**,不等于这些 unit 真没有内层等待。
>
> - **shell 层**:`run_to` 仍然**只有 `trade-turnover-backfill`** 有(7200+900+2760+2760=13620s,`turnover_backfill.sh:128,140,177,181`)。
> - **Python 层**(与超时兜底直接相关的两类,量级够大):
>   1. **R2 上传锁排队等待**:`scripts/upload_r2.py:4181,4210`,缺省上限 **7300s**(`R2_UPLOAD_LOCK_TIMEOUT`;带 `--skip-if-locked` 的调用只等 60s 有界窗口(`R2_UPLOAD_SKIP_RETRY_SECS`)后跳过,其余 blocking 调用按 7300s 排队)。
>   2. **git 锁排队等待**:`scripts/deploy.sh:750` `with_lock.py --block-timeout "${GIT_LOCK_TIMEOUT:-3600}"` ⇒ 最长 **3600s**。
> - **不构成内层等待的**(已核,免得下一轮重复怀疑):`with_lock.py --nb` 拿不到锁立即跳过(`scripts/with_lock.py` nonblock 分支);
>   `app/collector/public_fund.py:545,555` 的 `_acquire_lock` 默认 nonblock,撞锁直接放弃;其余 subprocess 超时都是通知/小工具级(≤120s:
>   `detect_intraday_anomaly.py:290` 120s、`:322` 60s;`check_sentiment_r2_upload.py:159` 60s;`lock_watchdog.py:49` 10s),
>   相对外层值是 1~2 个数量级以下,不会倒挂。
> - **无上限(根本没传 timeout)的内层调用**(这类**不提供**内层兜底,外层 `TimeoutStartSec` 就是唯一封顶,与旧结论「外层即唯一墙钟」同向):
>   `app/collector/index_backfill.py:1145`(`app.compute.runner`)、`:1158`(deploy.sh)、`:1178`(check_signals.sh)subprocess 均不传 timeout;
>   `app/collector/baostock_parallel.py:201-212` 的 worker 监控是 `while True`(所有 worker 退出才结束,无时限),经 `app/collector/runner.py:412,613` 被 update_all 等主链调用。

| unit | 脚本:行号(内层等待) | 内层值 | 外层要求(=内层×2) | 本表值 / 判断 |
|---|---|---|---|---|
| `trade-update-all` | `upload_r2.py:4210`(R2 锁)+ `deploy.sh:750`(git 锁) | 7300 / 3600 | ≥14600 / ≥7200 | 20160 ✓ |
| `trade-backfill-evening` | `deploy.sh:750`(经 `index_backfill.py:1158` 调 deploy) | 3600 | ≥7200 | 17700 ✓ |
| `trade-futures-backfill` | `deploy.sh:750`(`futures_backfill.sh:99`) | 3600 | ≥7200 | 13380 ✓ |
| `trade-lhb-backfill` | `deploy.sh:750`(`lhb_backfill.sh:109`) | 3600 | ≥7200 | 18660 ✓ |
| `trade-etf-national-team` | `upload_r2.py:4210` + `deploy.sh:750`(`etf_national_team_backfill.sh:124`) | 7300 / 3600 | ≥14600 / ≥7200 | 6240 **⚠ 低于 14600** |
| `trade-intraday-snapshot` | `upload_r2.py:4210`;通知类 120 / 60 / 10 | 7300 | ≥14600 | 3060(已拍板)**⚠ 低于 14600** |
| `trade-lab-auto` | `upload_r2.py:4210`(`update_lab.sh:294,311`) | 7300 | ≥14600 | 10860 **⚠ 低于 14600** |
| `trade-us-stock-morning` | `deploy.sh:750`(`us_stock_morning.sh:71`) | 3600 | ≥7200 | 14340 ✓ |
| `trade-turnover-backfill` | `turnover_backfill.sh:128,140,177,181`(run_to)+ `upload_r2.py`(env 改 1800) | 13620 / 1800 | ≥27240 / ≥3600 | 27240 ✓ |
| `trade-public-fund-full` | `deploy.sh:750`(`public_fund_full.sh:89`) | 3600 | ≥7200 | 22680 ✓ |
| `trade-public-fund-quarterly` | `deploy.sh:750`(`public_fund_quarterly.sh:92`) | 3600 | ≥7200 | 4740 **⚠ 低于 7200** |
| `trade-pf-stage0-manager` / `-nav` / `-risk` | 无(`public_fund` 锁 nonblock,撞锁跳过) | — | — | 保持 ✓ |

> **⚠ 4 处冲突只登记、不改值(下一批复核)**:上表 4 个 ⚠ = 按「外层 ≥ 内层×2」口径,本表值小于内层等待上限。
> 但 R2 锁 / git 锁的等待是**合法排队**(共享锁竞争),不是挂死,和 `run_to` 那种「步骤跑不完」性质不同。
> 是否要这些 unit 一律抬到 14600 / 7200,还是给「锁等待类内层」单列豁免口径,**属口径决策**,
> 本批不擅自改值(§23.7 版本冻结精神),留待下一批拍板;定了再按 §4.3 同一批同步云上 / 快照 / doc §2。

**被改动的 5 条(上表 #3/#4/#5/#9/#10)汇总**:futures-backfill 9960→13380、lhb-backfill 10140→18660、
etf-national-team 5400→6240、turnover-backfill 15420→27240、public-fund-full 10320→22680。
其余 9 条保持原值(#6 已拍板 3060s,待上云;#1/#2/#8 仅更正 max 数字;#7/#11/#12/#13/#14 无变化)。

> **口径冲突标注(诚实留痕)**:已设超时的 `trade-s06-snapshot.service`(7020s)内层串行合计 6720s,按本轮「外层 > 内层×2」会要求 13440s。
> 它属于「已有超时值」的 22 个(不在本次 14 个、也不在 §3 无超时清单),2026-10-22 的 7020s 是审查通过的「内层+300 余量」口径,**本表不改**,留待下一批评估两条口径如何收敛。