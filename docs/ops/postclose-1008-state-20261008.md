# 2026-10-08 盘后生产现状只读核对 + 云上主机存活性旁证判定(全程不通 ssh)

- 任务:只读核对(零外发 / 零 R2 写 / 不跑任何生产脚本 / **不通 ssh/scp**)
- 执行:`researcher` agent(18:44~19:0x,落 §8 附录部分)+ **`tester` agent(19:14~19:2x,落 §1~§7 为本轮新增/覆盖)**
- 本轮核心方法:**在完全不用 ssh 的前提下**,用"云端产物落到 R2/CDN/GitHub 的最终更新时间"作为主机存活心跳,判断云上主机与定时任务是死是活
- 背景:今晨 deploy 校验失败定性报告 `docs/ops/deploy-integrity-fail-20261008-0206.md`(长假假阳性,预期今天盘后归零)

---

## 1. 【核心结论】云上还活着吗 —— 主机在线,但用户态任务自 18:30 起停摆

**一句话:主机(内核/网络)** 没死,**但盘后任务链自 18:30 起停止产出**;不是"只有 sshd 挂了"这种轻症。

| 观测层 | 结论 | 硬证据(本轮实测) |
|---|---|---|
| 内核 / 网络栈 | **在线** | `ping -c 4` = 4/4 收包 0% 丢包,RTT 32.5/35.3/41.0 ms;TCP `:22` connect 成功 0.04s |
| 用户态(任务链) | **自 18:29:49 起停摆** | R2 最后一笔写入 18:29:49;news-fetch 心跳 18:45 / 19:01 **两拍缺失**;staticdata 备份 commit 停在 18:01:23 |
| sshd | banner 不出(零字节) | `recv(256)` 8s 零字节 ⇒ 已 accept 但**不能完成 banner 交换** |

**事件时间线(北京时,全部实测)**

| 时刻 | 事件 | 证据 |
|---|---|---|
| 15:35~15:40 | 15:35 档链完成并上线 | overview/ad_line/notifications/intraday_snapshot R2 LM 齐在 15:39:4x~15:39:59;overview 内容 `collected_at=20261008 15:35:52` |
| 18:01:02 | news-fetch 最后一次产出 | `news_digest.json` 内容 `generated_at=2026-10-08 18:01:02`(CF 主站,cache-buster 复取同值) |
| 18:01:06 | news-fetch 三产物写 R2 | `data/news_digest.json` / `_index.json` / `2026/2026-10-08.json` 三者 LM **完全相同** = `10:01:06 GMT` |
| 18:01:23 | 云上 staticdata 备份最后一笔 commit | GitHub `efa0e539d` "data backup [news-fetch] 2026-10-08_18:01 - 3 files" |
| **18:29:40 / 18:29:49** | **R2 最后一笔写入(17:50 链跑到 fund-nav 异步上传步)** | `nav_bucket/00.json` LM `10:29:40 GMT`、`nav_bucket/01.json` LM `10:29:49 GMT`(见 §2.3 归属说明) |
| 18:30:10 | 主机自己发出 swap 100% SEVERE 告警 | `schedule_monitor` 告警原文(见 §8 附录 §9.1) |
| **18:45** | **应有心跳缺失** | 基线每小时 :01/:45 各一拍,该拍无 commit / 无 R2 写 |
| **19:01** | **应有心跳缺失** | 同上(19:22 实测仍无) |

---

## 2. 第 1 项:云端产物最后更新时间实测值(带浏览器 UA,`curl --max-time`,禁 `-v/-i`)

### 2.1 今日(10-08)有更新的产物

| 产物 | 位置 | 最后更新(BJ) | 实测值 |
|---|---|---|---|
| `nav_bucket/01.json` | R2 `ssd.fx8.store` | **10-08 18:29:49** | LM=`Thu, 08 Oct 2026 10:29:49 GMT` |
| `nav_bucket/00.json` | R2 | 10-08 18:29:40 | LM=`10:29:40 GMT`,size 2,378,667 |
| `data/news_digest.json` | R2 | **10-08 18:01:06** | LM=`10:01:06 GMT` |
| `data/news_digest/_index.json` | R2 | 10-08 18:01:06 | LM=`10:01:06 GMT` |
| `data/news_digest/2026/2026-10-08.json` | R2 | 10-08 18:01:06 | LM=`10:01:06 GMT` |
| `news_digest.json`(内容) | CF 主站 `ss.fx8.store` | **10-08 18:01:02** | `date=2026-10-08`,`generated_at=2026-10-08 18:01:02`,37 条(最新条 17:55) |
| `data/overview.json` | R2 | 10-08 15:39:59 | LM=`07:39:59 GMT`;`date=20261008`,`collected_at=20261008 15:35:52` |
| `data/intraday_snapshot.json` | R2 | 10-08 15:39:52 | LM=`07:39:52 GMT` |
| `data/notifications.json` | R2 | 10-08 15:39:53 | LM=`07:39:53 GMT` |
| `data/ad_line.json` | R2 | 10-08 15:39:45 | LM=`07:39:45 GMT`;内容末条 `date=20261008`(up 1698/down 3747/ad_line -143210,共 250 条) |
| staticdata 备份仓 commit | GitHub | **10-08 18:01:23** | `efa0e539d`;`per_page=1` 独立端点复核同值 |

### 2.2 仍停在旧版的产物(关键!这些正是"停摆"的反证)

| 产物 | 最后更新(BJ) | 说明 |
|---|---|---|
| `data/alert.json` | 10-07 02:27:47(**内容 date=20260930**) | 内容 09-30 生成,10-07 夜间链原样重传 |
| `data/board_etf_map.json` | 10-07 02:28:06 | 10-06 夜间链产物 |
| `data/kelly_mode_s06_state.json` | 10-07 02:28:09 | 同上(内容 `coverage_end=20260930`) |
| `data/nextday_plan.json` | 10-07 02:28:10 | 同上 |
| `data/auto_trade_steps.json` | 10-07 02:27:58 | 同上 |
| `data/signal_kelly_trades_parts/t2011.json` | 10-07 02:29:39 | 同上 |
| `data/signal_kelly_backtest.json` | 10-07 21:27:36 | |
| `data/overfit_monitor.json` | 10-04 23:01:05 | |
| `nav_bucket/{ab,40,c0,ff}.json` | 10-03 15:2x~15:3x | 增量指纹上传,内容未变的桶不重传(非故障) |
| `data/fund_score.json` / `data/etf_score_list.json` | **08-29 14:11:24 / 14:11:22** | 二者在 `_DATA_EXCLUDE_PREFIXES` 内,走专属通道 `fund-score`/`etf-score`,由 `pf_score_daily`/`pf_score_weekly` 链上传;**不是日更**⇒**不适合当存活指示器**(本轮如实标注,不作心跳用) |

### 2.3 `nav_bucket` 18:29 那笔的归属(为什么它比 news-fetch 更晚)

- `update_all.sh:106-128`:`export_fund_nav` → 完整性闸门 → rsync 镜像 → **`upload-fund-nav` 异步上传**(`fund_nav_upload_async.sh`,2026-09-23 P1 起拆出主链等待区)
- ⇒ 18:29:40~49 的 nav_bucket 写入 = **17:50 `update_all` 链跑到 fund-nav 异步上传步**(链已跑 39 分钟,进度正常)
- ⇒ **这是目前能找到的"最后一口气":18:29:49**。距 swap SEVERE 告警(18:30:10)**仅 21 秒**

---

## 3. 心跳基线(尺子)与网络层复现

### 3.1 尺子:staticdata 备份 commit 的分钟级心跳

云上 `staticdata_backup_async.sh` 每轮往 `xp13465/trade-data-signal-staticdata` 推一笔 commit(消息内带北京时间)。实测(GitHub REST API,**无鉴权 / 禁 -v -i**):

- **基线:10-07 08:00 ~ 10-08 17:00 共 34 小时,每一个整点都有 2 条**(`:01` 与 `:45`),**全窗无一处间隔 ≥ 50 min**
- 盘中另有 `[intraday]` 心跳每 10 min 一条(10-08:13:09/13:19/…/15:40)
- 10-08 18:00 整点:**只有 1 条(:01)** ⇒ **18:45 拍缺失**;19:00 整点:**0 条** ⇒ **19:01 拍缺失**
- 19:22 实测:最新 commit 距今 **80.9 min**(基线最大间隔仅 44 min)
- **尺子自检(防分页假象)**:换 `per_page=1` 独立端点复核,最新 commit 同为 `efa0e539d @ 18:01:23` ⇒ 不是分页/排序造成的假空白
- 另注:34 小时内 news-fetch 心跳**从未**与 17:50 长跑链互斥(10-07 晚间整条链运行期间 :45/:01 照常两拍)⇒ **不能用"被锁挡住"解释今天的缺失**

### 3.2 网络层复现(**一次性,无重试循环**)

| 探测 | 结果 | 判定 |
|---|---|---|
| `python3 socket` connect `122.51.111.173:22` | **成功,0.04s** | TCP 层通(内核 accept 正常) |
| 同 socket `recv(256)` | **8s 零字节(无 banner)** | 用户态 sshd 不能完成 banner 交换 |
| `ping -c 4 -W 2000` | **4/4 收包,0% 丢包**,RTT min/avg/max 32.513/35.255/41.000 ms,stddev 3.389 | 主机在线、链路健康(非网络黑洞) |
| `nc -G 8 -v ...:22`(仅 1 次) | 未回 banner;`-G` 只管 connect 超时**不杀读等待** ⇒ 进程悬挂被 harness 转后台 | 见 §7 残留登记 |

**综合:内核在线 + TCP accept 正常 + ICMP 0 丢包 + 用户态零响应 = 典型的"整机级用户态停摆"(重度换页/换页死亡),而不是网络故障,也不是 ssHD 单点问题。**

---

## 4. 两个可区分假设:H-A vs H-B(**给判据,不断言**)

### H-A 公网 22 被爆破洪泛打满 `MaxStartups`(腾讯云 Lighthouse 公网 22 长期被扫,是已知真实故障模式)
- **判据**:TCP 可连但无 banner;sshd 日志出现 `Exceeded MaxStartups`;**与主机内存无关 ⇒ 定时任务/产物更新照常**;`ss -tn state syn-recv | wc -l` 高企

### H-B 主机内存耗尽 / 资源枯竭(用户今日收到「主机 swap 100%」告警)
- **判据**:不只 sshd,**定时任务与产物更新一起停**;`free -m` 显示 swap 用尽、`/proc/pressure/memory` 高、`vmstat` 大量 si/so;`dmesg` 有 OOM / 或进程大面积 D 态

### 【第 1 项观察到的事实更支持 H-B】理由(逐条)

1. **产物更新确实停了**:news-fetch 三产物 R2 LM 齐停在 `18:01:06`,`18:45` / `19:01` 两拍心跳**两处证据源同时缺失**(R2 写入 + git commit),而基线 34 小时每小时两拍无例外。
2. **量级对不上 H-A**:sshd 的连接数上限问题**不可能**让文件写入与定时上传停摆 ⇒ H-A **不能解释**全部现象。
3. **`Exceeded MaxStartups` 是下游症状而非病因**:用户态被换页拖死时,已 accept 的连接无法完成 banner/密钥交换,未认证连接持续堆积 ⇒ 一样会撞 `MaxStartups`(前一轮 18:48/18:51 抓到过该句,与本判定不矛盾)。
4. **时间吻合到分钟**:主机自己在 **18:30:10** 发出 swap 100% SEVERE;R2 最后一笔写 **18:29:49**(差 21 秒);此后 18:45 起心跳全无。
5. **负荷背景**:同日 15:30 `intraday_snapshot` 耗时 928s 破 900s 阈值(见 §8 附录 A4)⇒ 全天资源本来就紧。

**诚实标注(不做断言)**:内核在线 + 用户态停摆的组合,除"重度 swap 抖动/换页死亡"外,还可能是「某长跑进程把 CPU/IO 吃满导致整机饥饿」或「宿主层冻结」——三者同属**整机级(H-B 家族)**,**都不是 H-A**。要**定死根因**,必须按 §6 走控制台 VNC 现场取证(`free` / `dmesg` / `journalctl`)。

---

## 5. #199(claude_self_backup 是否还写死老桶名)—— **PASS**

日志:`/Users/linhuichen/code/trade-data/data/logs/claude_self_backup.log`(本机 launchd,云上无此 unit)

**10-07 03:17 那轮原文三行(逐字)**:
```
[2026-10-07 03:17:01] Claude 自我备份完成: /Users/linhuichen/.claude/backups/daily/claude-self-20261007.tar.gz (933K)
✓ claude-self-20261007.tar.gz (933KB) -> signal-backup2/claude-backup/claude-self-20261007.tar.gz (私有桶)
[2026-10-07 03:17:04] R2 云端备份成功: claude-backup/claude-self-20261007.tar.gz
```

- **切换点清晰**:至 10-05 两行都还写 `signal-backup/...`(老桶);**自 10-06 起**第一行变 `signal-backup2/...`(新桶),第二行**不再出现任何桶名**(只剩 key)。
- 10-08 03:17 轮同形态(`signal-backup2` + 无桶名 key),即**已连续 3 轮稳定**。
- **独立锚点(不靠日志自证)**:
  - `scripts/backup_claude_self.sh:50` 成功文案 = `echo "... R2 云端备份成功: claude-backup/claude-self-$TS.tar.gz"`(**硬编码串里无桶名 ⇒ "写死老桶名"的病灶已消除**)
  - `scripts/upload_r2.py:299` `BACKUP_BUCKET = os.environ.get("R2_BACKUP_BUCKET", BACKUP2_BUCKET)` ⇒ 默认即 **signal-backup2**
  - `.env:16-18` 注释「备份桶独立账号(signal-backup2, 新 CF 账号, 独立免费额度)2026-10-05」
- ⇒ 三条独立证据(打印行 / 脚本默认值 / 配置注释)同向一致 = **老桶名 `signal-backup` 已不再写死**。

---

## 6. 不依赖 ssh 的替代恢复通路(清单:**只给建议命令,本轮一条都没执行**)

### 6.1 第一优先:腾讯云控制台 VNC(最可能成功,不走 22 端口)
路径:轻量应用服务器控制台 → 选中实例 → 「登录」/「VNC 登录」(Web 终端)

进现场后**按序取证**(只读优先):
```bash
uptime                                  # 负载/是否刚重启
free -m                                 # swap 是否真满(核心)
cat /proc/pressure/memory               # PSI:some/full 的 avg10 是否高
vmstat 1 5                              # si/so 是否持续非零 = 换页风暴
dmesg -T | tail -50                     # OOM-killer / hung task 痕迹(关键)
journalctl -k -n 100 --no-pager         # 内核告警
ps -eo pid,ppid,rss,etime,state,cmd --sort=-rss | head -20   # RSS 排行找大户
ps -eo state,pid,cmd | awk '$1=="D"'    # D 态(不可中断 IO)= 卡死证据
journalctl -u sshd -n 50 --no-pager     # 是否有 Exceeded MaxStartups(区分 H-A)
ss -tn state syn-recv '( sport = :22 )' | wc -l   # 未认证连接积压量
systemctl list-units --failed           # 哪些 trade-* 进了 failed
systemctl list-timers | grep trade      # 下一次触发时点(确认调度还活着)
tail -80 /var/log/.../update_all_20261008_1750.log   # 17:50 链断在哪一步
```
**判读**:`dmesg` 有 OOM / `vmstat` si+so 持续非零 / `free` swap 满 ⇒ **H-B 坐实**;反之若一切正常而只有 sshd 积压 ⇒ 偏 H-A。

### 6.2 是否值得从控制台重启实例
- **先 VNC 再重启**:VNC 能进 ⇒ 先取证 + 尽量救现场(VNC 可登录说明用户态没全死,可能只需 `systemctl restart sshd` + 清内存大户)。
- VNC **同样卡死/黑屏**(用户态已全停)⇒ 现场已无法取证,**重启是唯一出路**;重启前尽量记住 `journalctl` 里已有线索(`-T | tail`)。
- 重启后立即:`systemctl list-units --failed` → `journalctl -u <trade-*> -n 100` → 按 SOP 补跑当日 17:50 链(**不要盲目重跑全量**,先确认 15:35 档产物已在线上)。

### 6.3 治本(重启后做,防再犯)
1. **22 端口加固**:安全组**只放行自己的出口 IP**(Lighthouse 支持源 IP 白名单)+ 改非标端口 + **仅密钥登录**(`PasswordAuthentication no`)+ 上 fail2ban;若确属 H-A,这一步直接把病因去掉。
2. **内存侧**:查清 swap 打满的元凶(RSS 排行 + 当日链的峰值内存);评估**加 swap / 升配 / 给长跑链加 `MemoryMax` 限制**(systemd 单元已有超时治理先例 #223-5,可同法加内存上限)。
3. **确认 17:50 链是否已死**:链若中途死掉,recovery 视产物完整性决定补跑范围(`check_data_integrity` 先过一遍)。
4. 建议把「**心跳缺失 ≥2 拍**」做成一条独立告警(本次靠人工比对 GitHub commit 才看出来)——这是本次唯一能"看见"主机死亡的信号。

---

## 7. 未测项 / 本机残留

### 7.1 未测项(如实标注)
1. 云上任何日志(`update_all/deploy/journalctl`)——**ssh 不可达,按任务要求不通 ssh**
2. #200 rsync 日志、#202 journalctl patrol —— 同上
3. §8 附录 §9.2 要求的 swap 采样曲线 / 进程级 RSS 证据 —— 同上
4. 16:32 档 deploy 触发链细节 —— 同上
5. 10-08 19:00 之后段时间的最终结论 —— 受本轮观测窗口(19:23)限制;19:15 之后的拍子需再取一次(**终验 19:23:25 实测仍无推进**:最新 commit 仍 18:01:23 / news_digest 仍 18:01:02 / nav_bucket/01 LM 仍 18:29:49,缺口 82 min)
6. `fund_score` / `etf_score_list` 是否正常 —— **本轮证伪其"日更指示器"资格**(非日更,见 §2.2),未再深挖

### 7.2 本机残留(按纪律首行声明)—— **已清理完毕**
- 曾残留后台任务 `bz3kpu43x`,命令 = `( nc -G 8 -v 122.51.111.173 22 < /dev/null ) 2>&1 | head -20`,预期退出 = **不会自行退出**(macOS `nc -G` 仅约束 connect 阶段、读等待无上限,悬挂 60min+);子进程 `nc` PID 83915,PPID 83912 = 本 agent 自己的 shell(属主链已核实)⇒ 已上报主控
- **清理结果(19:24:16 实测)**:主控 TaskStop 该后台任务;`pgrep -fl "nc -G 8"` **exit 1(零进程)**、`ps -p 83915` 无输出、`pgrep -fl "122.51.111.173"` 零命中 ⇒ **残留已彻底清空,无遗留进程**
- 本轮未跑任何生产脚本、未写数据产物、未做 R2 写、未发任何通知、未切分支/未 commit

---

## 8. 附录:前一轮 agent(18:44~19:0x)产出**保留**(与本轮结论不冲突,可互证)

### 8.0 传输通道障碍(前一 agent 记录)
- 18:44 起 ssh 无法建立会话;18:48/18:51 两次抓到 `Exceeded MaxStartups`;其后 banner 长期无响应。**(本轮 §3.2/§4 已给出该现象的新定性:更可能是 H-B 的下游症状)**

### 8.1 今日盘后链路现状
- **A1** 17:50 `update_all` 是否跑完:线上 alert.json 仍为 09-30(未更新);15:35 档产物(notifications/overview/ad_line)已到 10-08。**本轮补强**:17:50 链**确实在跑**(18:29:49 完成 fund-nav 异步上传步),但 18:30 后无后续产出
- **A2** 今晨校验失败是否归零:16:32 档 deploy **再次 FAIL** → 16:39 发「deploy 数据产物校验失败」(今晨预告的"预期内噪音");最新一轮汇总待云上读日志(**未测**)
- **A3** 线上数据 date 实测:alert.json `date=20260930` / `ad_line.json` 末条 `20261008` / `notifications.json` `date=20261008, generated_at=15:38:40` / `overview.json` `collected_at=20261008 15:35:52` / `kelly_mode_s06_state.json` `coverage_end=20260930`(20:35 档重生前属正常)。**本轮已用 R2 LM 独立复现全部上述值,逐项一致**
- **A4** 今日告警全量(飞书 alert 群只读拉取,10-08 00:00~19:02 共 8 条):

| 时间 | 告警 | 定性 |
|---|---|---|
| 02:16 | deploy 数据产物校验失败(`deploy_20261008_0206.log`) | 已定性:长假假阳性,预期内 |
| 09:40 | 凯利盘中增量回测失败(退出码 5) | 数据就绪闸取不到真实开盘价 → 跳过留 17:50(代码 L102);09-30 同款复发 |
| 09:45 | 云上 unit 巡检异常(1 项):`trade-kelly-intraday-rerun.service failed` | 09:40 失败连锁 |
| 15:30 | [SEVERE] `intraday_snapshot` 耗时 928s 超阈值 900s | 进程退化信号 |
| 15:45 | [恢复] 上条消失 | 自动恢复 |
| 16:00 | 云上 unit 巡检异常(同上) | 复报 |
| 16:39 | deploy 数据产物校验失败(`deploy_20261008_1632.log`) | 今晨预告的"16:35 档预期内噪音"(真发了) |
| **18:30** | **[SEVERE] 主机 swap 使用率 100.0% 超严重线 90%** | **用户所指"内存/泄漏"告警,本报告 §4 的核心证据** |

### 8.2 内存/swap 告警机制(前一 agent)
- 原文:`[10-08 18:30:10] [SEVERE] 主机swap 使用率 100.0% (host) 超严重线 90% —— 主机资源告急`(`schedule_monitor` 发出,邮件+飞书)
- 指标:`_swap_used_pct()` = `/proc/meminfo` (SwapTotal-SwapFree)/SwapTotal(`schedule_monitor.sh:1545-1556`);阈值 warn 85 / severe 90(`:1466-1467`)
- 该维度(主机资源:磁盘/inode/内存/swap)**2026-10-05 才上线(#164)** ⇒ 10-05 前无此维度不代表当时无内存压力
- 首现与频率:10-05(维度上线)~10-08 间首次出现;10-05/06/07 为长假休市任务轻,无此告警
