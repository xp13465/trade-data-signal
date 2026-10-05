# 老 CF 账号 R2 占用评估 + 可手动清理清单(2026-10-05,全程只读)

> ## ⚠️ #178 安全闸(单独醒目结论)
> ## ✅ **合并 #178 并云上部署后,备份写入将正确路由到新桶 `signal-backup2`,不会因缺 `R2_BACKUP2_*` 回退老账号 → 老账号无该桶 → 404 失败。** 证据=云上+本机 `.env` 4 键全在(各 count=1)、无 `R2_BACKUP_BUCKET` 覆盖、云上全部 systemd unit `EnvironmentFile=` 指向 `trade-data/.env`、worktree 代码在生产等价环境实测(`BACKUP_BUCKET=signal-backup2`、`_route_bucket('signal-backup2')`→新账号 AK、`_route_bucket('signal-backup'/'signal-data')`→老账号)。详见 §5。
> ⚠️ 前置提醒(与上条并列):**新桶 `signal-backup2` 必须配齐与老桶相同的 5 条 lifecycle(尤其 `pre-upload/` 7 天)**,否则新桶单靠自身在约 9 天内爆 10 GB 免费额度(`pre-upload/` 日增 ~1.08 GiB,见 §3.3)。

> 任务:评估老 CF 账号 R2 占用,产出「可手动清理清单」,目标把老账号总占用从当前 >10 GB 降到 ~6 GB。**全程只读**(未改/未删/未传任何对象;清理动作留待用户拍板后另派执行)。
> 取证方式标注:【云上实测】= 2026-10-05 ssh `ubuntu@122.51.111.173`(`~/tdsignal.pem`)+ `/home/ubuntu/code/trade-data/.venv/bin/python` 加载 `scripts/upload_r2.py` 的 `s3_request` 列桶(ListObjectsV2 全量分页,明细落 `/tmp/r2_assess_detail.json`);【代码】= 本地仓库 `文件:行号`;【文档】= `docs/ops/*.md`;【lifecycle】= 用户 CF dashboard 实测(2026-10-05,主控转达)+ 行为佐证。
> 口径备注:本文用 GiB(1 GiB = 1073741824 B);CF 计费口径按 GB(10^9 B)时数字更大(当前两桶 10.968 GiB = 11.78 GB),**结论方向不变**。

---

## 0. 结论总览(一页账)

| 阶段 | 动作 | 释放 | 老账号累计占用 |
|---|---|---|---|
| 现状(2026-10-05 实测) | — | — | **10.968 GiB**(signal-backup 8.147 + signal-data 2.821) |
| A 档:立即可清(待拍板) | 残留对象 163.9 MiB 手动清 | 0.160 | 10.808 |
| B+C 档:10-07 后手动清(待拍板) | fund_nav 531.0 + large-json legacy 266.1 | 0.779 | 10.030 |
| lifecycle 自动:pre-upload/(10-10~12) | 到期自动删(老桶已配 7 天) | 3.217 | 6.813 |
| lifecycle 自动:backup/(10-18~19) | 到期自动删(14 天) | 1.432 | 5.381 |
| lifecycle 自动:weekly/(10-26) | 到期自动删(28 天) | 0.378 | 5.003 |
| lifecycle 自动:claude-backup/(11-04) | 到期自动删(30 天) | 0.023 | **4.980**(已达标 <6 GB) |
| D 档:切换+新桶验证后(可选) | 老桶 large-json flat 手动清 | 0.433 | 4.547 |
| (monthly/ 0.282 一年后自动清) | 2027-07 起逐月 | 0.282 | 4.265 |

- **目标达成路径**:**10-26 前后自然降到 ~5.0 GiB**(<6 GB 目标);若把 A+B+C+D 手动项都做,可提前到 **10-14 前后 ~4.6~5.5 GiB** 区间(不需等到 10-26)。
- **不需要动 mac-backups/archive/(2.122 GiB)**:它在"不可清"清单(§4),清或不清都不影响 6 GB 目标达成。
- **诚实标注**:上表 B/C/D 与 A 均为"待用户拍板后另派执行"的候选;本报告全程只读,未删任何对象。

---

## 1. 两桶现状实测(2026-10-05,【云上实测】)

### 1.1 signal-backup(私有备份桶):66,008 对象 / 8,747,606,224 B = **8.147 GiB**

| 前缀 | 对象数 | 字节 | GiB | 用途 | production 在用? | 别处有副本? | 可清性判定 |
|---|---|---|---|---|---|---|---|
| pre-upload/ | 6,585 | 3,453,993,283 | 3.217 | 每次增量上传前,把**将被覆盖 key 的上一版** COPY 进 `pre-upload/<YYYYMMDD>/`(`_backup_overwritten_keys` upload_r2.py:1006,7 天保留 :936) | 在用(写入中;切桶后停) | 无独立副本 | **等 lifecycle**(10-10~12 自动清空;手动清=提前丢回滚窗口,§2.5 判定) |
| mac-backups/ | 1 | 2,278,230,346 | 2.122 | `mac-backups/archive/mac-backups-2026-10-01.tar.zst`(10-04 拍板"传 R2 归档,本机先留"【文档】r2-archive-upload-20261004.md) | 一次性归档 | 本机有源目录+包+恢复脚本 | **不可清**(拍板异地容灾保留;§4) |
| backup/ | 28 | 1,537,824,096 | 1.432 | DB 每日备份(etf_national_team.db + sentiment.db,21:00 通道,14 天滚动;实际日期 20260921~20261004 各 14 天 ×2) | 在用(切桶后停) | 同族滚动(见 C 档语义) | **等 lifecycle**(已配 14 天;10-05 起逐日到龄,~10-19 清空) |
| large-json/ | 59,346 | 733,530,289 | 0.683 | 大 JSON(>20MB,staticdata git 排除)的 R2 备份;#126 改造后 flat 固定前缀=唯一完整副本,legacy 日期目录 7 天宽限 | 在用(flat);legacy 待清 | **flat 无第二副本**(git 已排除) | 拆分见下:legacy 手动清(C 档)/ flat 切换后清(D 档)/ 详见 §2.3/§2.4 |
| weekly/ | 8 | 405,436,133 | 0.378 | 周备份(9-07/9-14/9-21/9-28 各 2) | 在用(切桶后停) | 滚动窗口 | **等 lifecycle**(已配 28 天;10-26 清空) |
| monthly/ | 8 | 303,160,886 | 0.282 | 月备份(7-21/8-03/9-01/10-01 各 2) | 在用(切桶后停) | 滚动窗口 | **等 lifecycle**(已配 365 天;2027-07 起逐月) |
| claude-backup/ | 30 | 24,451,022 | 0.023 | Claude 配置每日自备份(9-06~10-05;30 天滚动——对象数 61→30 证明 30 天 lifecycle 已实际生效回收) | 在用(切桶后停) | 本机有源 | **等 lifecycle**(已配 30 天;11-04 清空) |
| decommissioned/ | 2 | 10,980,169 | 0.010 | 退役归档(刻意保留,无 prune 代码) | 否 | — | **不可清**(刻意保留;§4) |

- large-json/ 内部分类【云上实测】:legacy 日期目录 27,673 对象 / 279,046,499 B = **266.1 MiB**(2026-09-29: 11,875 对象 143.3 MiB;2026-09-30: 15,798 对象 122.8 MiB);flat 固定前缀 31,673 对象 / 454,483,790 B = **433.4 MiB**。
- pre-upload/ 按日【云上实测】:20261003: 277 对象 757,138,141 B = 0.705 GiB;20261004: 2,697 对象 1,419,232,063 B = 1.322 GiB;20261005: 3,611 对象 1,277,623,079 B = 1.190 GiB。

### 1.2 signal-data(公开主桶):31,480 对象 / 3,029,203,788 B = **2.821 GiB**

| 前缀 | 对象数 | 字节 | GiB | 用途 / 消费方 | 可清性判定 |
|---|---|---|---|---|---|
| data/ | 319 | 623,472,809 | 0.581 | Worker `/data/*` rewrite → R2 直读(worker/headers.js:220 `dataRewriteHandler`);前端 `./data/x.json` 与 `_R2_DATA_BASE(/r2/data/)` 大 range 直链。**内部构成**:signal_kelly_trades\* 38 对象/354.8 MiB(首页模拟回测弹窗,活)+ industry-\* 10 对象/77.2 MiB(**死快照,见 §2.1-A1**)+ accum_nav_map 25.1 MiB(lab.js:8147 活)+ etf_score_list 系列 28.3 MiB + daily_brief_tts_\* 16 个 mp3/14.1 MiB(历史语音,§4 保留)+ overfit_monitor(_ext) 14.0 MiB + 各 range 文件(活) | 主体活;**industry-\* 死快照 + 1 个 .gz 残留可清(A 档)** |
| nav_bucket/ | 256 | 561,548,829 | 0.523 | 基金净值桶化现行版(2026-09-23 上线;worker no-store;前端双读回退 app.js:27770/27840) | **不可清**(现行) |
| fund_nav/ | 26,458 | 556,807,260 | 0.519 | 基金净值旧 per-code 版(桶化前通道;用户拍板"稳定 1-2 周后清旧 per-code",约 10-07~10-14) | **B 档手动清**(拍板窗口;§2.2) |
| trade_sim_data/ | 504 | 385,778,698 | 0.359 | 模拟回测 JSON(`trade_sim_{id}_{stats,full,fee_compare}.json`;前端 app.js:29981/29987 活) | **不可清**(活) |
| trade_sim/ | 103 | 204,784,968 | 0.191 | 模拟回测 HTML(前端 📊 链接 app.js:8952) | **不可清**(活) |
| offshore_fund/ | 7 | 156,048,848 | 0.145 | 场外基金 7 件套(basic/fee_detail/manager/performance/purchase_status/rating/risk_indicator);**定时链 2026-08-22 已停(update_all.sh:217,P2-15 用户确认零消费方),前端零引用**,R2 副本=P2-15"移 R2"存档 | **未决项**(P2-15 待场外基金路线图;非垃圾残留;§4) |
| industry/ | 134 | 128,864,688 | 0.120 | 行业数据**现行版**(前端 app.js:25451-25457 全走 `/r2/industry/...`;check_r2_consistency 检查此版) | **不可清**(现行) |
| etf/ | 1,718 | 117,162,640 | 0.109 | ETF 全历史(`etf/{code}-all.json`;前端 app.js:4798/26566 活) | **不可清**(活) |
| lab/ | 65 | 99,056,999 | 0.092 | 策略实验室(lab.js 多处 fetch `/r2/lab/...` 活) | **不可清**(活) |
| (root) | 5 | 80,372,044 | 0.075 | `__speedtest_{5,20,50}mb.bin`(9-13 测速残留)+ `overview.json`(8-26,根级孤儿)+ `sss.jpg`(7-20) | **A 档手动清**(§2.1-A2/A3/A4) |
| index/ | 173 | 68,879,309 | 0.064 | 指数全历史(`index/{id}-all.json`;app.js:1480 等多处活) | **不可清**(活) |
| accum_nav/ | 1,718 | 26,249,770 | 0.024 | 累计净值(lab.js:8147 同源族,活) | **不可清**(活) |
| test/ | 1 | 10,485,760 | 0.010 | `test/speedtest-10m.bin`(9-13 测速残留) | **A 档手动清**(§2.1-A2) |
| public_fund/ | 13 | 7,251,298 | 0.007 | 场外基金筛选器(前端 app.js:21280/21310 等活) | **不可清**(活) |
| fund_score/ | 2 | 2,434,127 | 0.002 | 基金评分(worker fund_score.js 活) | **不可清**(活) |
| probe/ | 3 | 5,723 | 0.000 | 10-02 CF 边缘探测遗留(设计"读后即删",未删净;【文档】cf-edge-egress-probe-20261002.md) | **A 档手动清**(§2.1-A2) |
| r2test/ | 1 | 18 | 0.000 | `r2test/r2test.txt`(7-20 连接测试残留) | **A 档手动清**(§2.1-A2) |

### 1.3 关键对象时效证据(LastModified,【云上实测】——判"死/活"的决定性证据)

| 对象组 | LastModified | 判读 |
|---|---|---|
| data/industry-\*(10 个) | **全部 2026-08-29T06:11Z**,之后 37 天零更新 | 死快照:形成于 8-29 一次性上传;此后 all-data/data-large 通道已 exclude industry-\*(upload_r2.py:1742 `_DATA_EXCLUDE_PREFIXES`、:1787 注释、`cmd_upload_all_data` docstring),upload-industry 只写 industry/ 前缀 ⇒ **无任何写入通道** |
| data/daily_brief_tts_\*(16 个) | 各日 12:40Z(=北京 20:40,生成时点),最后 2026-09-07 | **09-07 后未再生成**(功能疑似停跑/合成失败;本机同款文件同止于 09-07);历史回看可播(§4 保留) |
| probe/\*(3 个) | 2026-10-02 | 探测遗留(设计本应"读后即删") |
| test/speedtest-10m.bin、__speedtest_\*(3 个) | 2026-09-13 | 测速残留(9-13 批量测试期) |
| sss.jpg、r2test.txt | 2026-07-20 | 早期连接/素材残留 |
| 根级 overview.json | 2026-08-26 | 根级孤儿(前端零走根级,R2 data/ 版为现行) |
| data/signal_kelly_backtest.json.gz | 2026-08-28 | 唯一 .gz 残留(memory fetchjson-skip-gz:前端已统一 .json+CF br 压缩) |

---

## 2. 「可手动清」清单(每项含 §25 可逆性:从哪恢复 + 恢复命令)

> §25 判定原则:每项必须写得出恢复路径才列为可清;写不出=判不可清理。下面每项均过此关。

### 2.1 A 档:立即可清(4 组,合计 **163.9 MiB** / 171,894,762 B;不依赖任何前置)

#### A1. signal-data `data/industry-*` 10 对象 —— **77.2 MiB / 80,963,161 B**
- **性质**:8-29 死快照(§1.3);前端零引用(全仓 `data/industry-` grep 仅命中注释/上传脚本/worker 缓存规则,**前端 js 零 fetch**;industry 现行加载全走 `https://ss.fx8.store/r2/industry/...` app.js:25451-25457;check_r2_consistency 亦检查 industry/ 版);上传通道已 exclude(三处证据见 §1.3)。
- **§25 可逆性**:恢复=用云上/本机现役源文件重传(同名文件现役版全部在位:`/home/ubuntu/code/trade-data/static-site/data/industry-*.json` 由 export 每日生成;本机 static-site/data/ 同族文件在位且更新)。内容无丢失(它们是旧快照,现行版本在 industry/ 前缀 + 本地源)。
- **恢复命令**(示意,单 key PUT 复用仓库通路):
  ```bash
  # 云上执行:REPO=/home/ubuntu/code/trade-data .venv/bin/python - <<'PY'
  #   import os,sys; os.environ.setdefault('REPO','/home/ubuntu/code/trade-data')
  #   sys.path.insert(0,'scripts'); import upload_r2 as u
  #   data=open('static-site/data/industry-1y.json','rb').read()
  #   print(u.s3_request('PUT','data/industry-1y.json',data,bucket='signal-data'))
  # PY
  ```
- **删除命令(执行 agent 用,逐 key 精准 DELETE,禁止前缀通配)**:
  ```bash
  # 云上执行:对 ≤2.1 列出的 10 个 key 逐个 u.s3_request('DELETE', key, bucket='signal-data')
  ```

#### A2. 测速/探测/连接测试残留 8 对象 —— **89,134,701 B ≈ 85.0 MiB**
- `__speedtest_5mb.bin`(5,242,880)、`__speedtest_20mb.bin`(20,971,520)、`__speedtest_50mb.bin`(52,428,800)、`test/speedtest-10m.bin`(10,485,760)、`probe/cf-egress-202610021509514.json`(5,613)、`probe/ping-*.json`×2(55+55)、`r2test/r2test.txt`(18)——合计 **89,134,701 B(8 对象)**,各对象 LastModified 见证(§1.3)。
- **性质**:全仓代码零引用(grep py/sh/js 无命中);probe/ 有文档明示"读后即删"设计意图(cf-edge-egress-probe-20261002.md);speedtest 系为填充字节的测速文件。
- **§25 可逆性**:恢复=重新生成(均非数据资产):`dd if=/dev/zero bs=1M count=5 of=__speedtest_5mb.bin` 后 PUT 即可;probe=重跑该文档探测流程。
- **恢复命令**:
  ```bash
  # 重生成 + 重传(云上):
  # dd if=/dev/zero bs=1M count=5 of=/tmp/__speedtest_5mb.bin && 单 key PUT 回同 key(同上 s3_request 模式)
  ```

#### A3. 根级 `overview.json` —— **1,585,628 B ≈ 1.5 MiB**
- **性质**:根级孤儿(8-26);前端全走 `./data/overview.json`(worker rewrite→key `data/overview.json`)或 `/r2/data/overview.json`;根级零引用(grep `/r2/overview`、站内引用均空);check_r2_consistency 检查 data/ 版。
- **§25 可逆性**:恢复=现役 `data/overview.json`(1,831,451 B,现行)内容为准,如需根级旧样可直接 PUT 复制(或直接丢弃,无消费方)。
- **恢复命令**:`cp static-site/data/overview.json /tmp/root-overview.json` 后单 key PUT 到 `overview.json`。

#### A4. 根级 `sss.jpg` —— **143,216 B ≈ 0.14 MiB**
- **性质**:7-20 素材;全仓宽搜(所有文件)grep `sss.jpg` **零命中**;站内 og/twitter 图用 `https://ss.fx8.store/og.png`(index.html:28 等)。
- **§25 可逆性**:本机如仍有素材可重传;**无站内消费方**。风险仅"若该 URL 曾被外部平台(社交分享)引用过,删除后该外部链接 404"——按用户对素材的处置意见定;若无印象,可清。
- **恢复命令**:素材若在本机 `find ~ -name 'sss.jpg'` 找到后单 key PUT 回根级(或忽略)。

> A 档合计 = A1 80,963,161 + A2 89,134,701 + A3 1,585,628 + A4 143,216 + `data/signal_kelly_backtest.json.gz` 68,056(8-28 残留,前端已统一 .json 不读 .gz,恢复=从 data/signal_kelly_backtest.json 现行版重生成)= **171,894,762 B = 163.9 MiB ≈ 0.160 GiB**(与 §0 表一致)。

### 2.2 B 档:fund_nav/(旧 per-code)—— **531.0 MiB / 556,807,260 B;10-07 后 + 前置验证**

- **性质**:基金净值桶化(2026-09-23 上线)前的 per-code 26,458 文件;已被 nav_bucket/(256 桶)替代;worker 双前缀同语义 no-store(worker/headers.js:142),前端有回退双读(app.js:27770/27840)。**用户已拍板"稳定 1-2 周后清旧 per-code"** = 约 2026-10-07~10-14(memory fund-nav-bucket-p3-followups)。
- **前置条件(清之前必须核)**:①连续多日每日 PUT 256/256 稳定;②无 severe 告警;③`scripts/check_r2_consistency.py` 通过。
- **§25 可逆性**:恢复=源文件在位(云上 `static-site/data/fund_nav/` 全量 per-code 文件由 export 生成;或重跑 `upload_r2.py upload-fund-nav` 通道重建)。且 nav_bucket/ 现行版内容同源可交叉恢复。
- **恢复命令**:
  ```bash
  # 云上重跑:REPO=/home/ubuntu/code/trade-data bash -c 'cd /home/ubuntu/code/trade-data && .venv/bin/python scripts/upload_r2.py upload-fund-nav'
  ```

### 2.3 C 档:large-json/ legacy(9-29/9-30 日期目录)—— **266.1 MiB / 279,046,499 B;10-07 后**

- **性质**:#126 改造前旧机制产物(按日全量副本),设计上 7 天宽限后由 `_prune_large_json` 清理(upload_r2.py:2403 `(today-d).days < 7` 保留)。**9-29 目录 10-06 过窗口、9-30 目录 10-07 过窗口。**
- **⚠️ 关键断链风险(本报告新发现)**:合并 #178 后 `_prune_large_json` 的目标桶 = `bucket or BACKUP_BUCKET` → **新桶 signal-backup2**(upload_r2.py:2541 附近 / L299 BACKUP_BUCKET 默认改新桶),而老桶 large-json/ **无 lifecycle 规则**(用户 10-05 实测确认不配)⇒ **切桶后老桶 legacy 266.1 MiB 变成"无人清"孤儿**。故建议:10-07 后(设计窗口全过)手动清一次(补刀),不要指望代码。
- **§25 可逆性**:恢复=**不可恢复,但属于"设计既定作废"**——这些对象是"被覆盖 key 的滚动副本",系统设计 7 天窗口过期即弃(与 backup/ 14 天滚动同理);10-06/10-07 到期删除本就是代码既定行为,手动清=把既定行为按时执行(且因断链,手动是唯一可达路径)。判定:**可清(10-07 后,纯补刀,零回滚承诺破坏)**。
- **删除命令(10-07 后,逐 key 精准 DELETE,禁前缀通配;或按日期目录前缀 27,673 个 key 逐删/分批)**:
  ```bash
  # 云上:list prefix='large-json/2026-09-29/' 与 'large-json/2026-09-30/' 的 key 全量,逐个 u.s3_request('DELETE', key, bucket='signal-backup')
  ```

### 2.4 D 档:large-json/ flat(固定前缀)—— **433.4 MiB / 454,483,790 B;切换完成 + 新桶验证后**

- **性质**:31,673 个"大 JSON 当前版本"备份(staticdata git 排除后的唯一 R2 副本,upload_r2.py:1787/1591 语义;fixed 前缀"内容变才 PUT")。当前**不可清**(它是唯一副本,且老桶仍是现行写入目标)。
- **前置(任务书口径"须切新桶+验证后才能清")**:①#178 合并+部署,新桶 signal-backup2 的 flat 全套 31,673 对象完成首轮就位;②抽查回读验证(取 N 个对象 GET 与本地 md5 对账 PASS);③确认新桶每日 flat 更新正常(连续 2-3 天)。
- **满足后**:老桶 flat = 过时快照集合(其"当前版备份"职能已由新桶接管)→ 可清,恢复=新桶同名对象(内容=最后一次上传时的版本,新桶持续滚动更新)。
- **§25 可逆性**:恢复=新桶 signal-backup2 对应 key(内容现行/更新);老桶副本内容无独有价值(flat 不保留历史版本,新旧桶内容互踩滚动)。
- **恢复命令**:`s3_request('GET','large-json/<path>',bucket='signal-backup2')` 取回后 PUT 回老桶同 key(如需)。

> **A+B+C+D 合计可手动释放:163.9 + 531.0 + 266.1 + 433.4 = 1,394.4 MiB ≈ 1.362 GiB。**

### 2.5 pre-upload/ 为什么"不列手动清而在 lifecycle 清"(任务书重点问题的回答)

- 任务问:pre-upload/ 3.13 GiB(lifecycle 会清,能否**现在**手动清?清了是否丢"被覆盖 key 上一版"回滚能力?)。
- **判定:不建议现在手动清;等 lifecycle(10-10~12 自动清空)**。理由:①它的价值=10-03~05 增量上传中"被覆盖 key 的上一版"回滚窗口(**无独立恢复副本**,§25 写不出恢复路径 → 不得列为可清);②老桶已配 7 天 lifecycle,10-03/04/05 三层分别在 10-10/10-11/10-12 到期自动清,**收益(提前几天)与代价(丢回滚窗口)不成比例**;③切桶后无新写入,自动清后不会回填。
- 如需极速路径(接受丢回滚窗口):10-06 起可手动清 10-03 层、10-07 清 10-04 层、10-08 清 10-05 层(逐日按目录清,不一次全清)。**默认不推荐。**

---

## 3. 「等 lifecycle 自动清」时间线(老桶 5 条已配,【lifecycle】用户 dashboard 实测)

### 3.1 逐前缀到期时间线(自 2026-10-05 起;前提=切桶后老桶无新写入,如有新写入相应顺延)

| 前缀 | 现存量 | 规则 | 到期行为 | 清空时点 |
|---|---|---|---|---|
| pre-upload/ | 3.217 GiB | 7 天(与代码 `_PREUPLOAD_RETENTION_DAYS=7` 一致) | 10-03 层 10-10、10-04 层 10-11、10-05 层 10-12 逐层过期 | **~10-12 清空** |
| backup/ | 1.432 GiB | 14 天 | 9-21 起逐日到龄(10-05 起),最后 10-04 层 10-18 到龄 | **~10-18/19 清空** |
| weekly/ | 0.378 GiB | 28 天 | 9-07→10-05、9-14→10-12、9-21→10-19、9-28→10-26 | **~10-26 清空** |
| monthly/ | 0.282 GiB | 365 天 | 7-21→2027-07-21 起逐月 | **2027-08 前后清空** |
| claude-backup/ | 0.023 GiB | 30 天 | 9-06→10-06 起逐日 | **~11-04 清空** |
| large-json/ legacy | 266.1 MiB | **无规则(用户确认不配)** | 无人清(#178 后代码断链,§2.3) | **需 10-07 后手动补刀** |
| large-json/ flat | 433.4 MiB | 不配删除(唯一副本) | 保留(切换验证后按 D 档另议) | — |
| decommissioned/、mac-backups/ | 0.010+2.122 GiB | 不配删除(刻意保留) | 保留 | — |

### 3.2 月度视图

- 10-05(今天):10.968 GiB
- 10-12 前(A+B+C 手动 + pre-upload 自动):**~6.8 GiB**
- 10-18/19:再 −1.432(backup)→ **~5.4 GiB**
- 10-26:再 −0.378(weekly)→ **~5.0 GiB**(<6 GB 目标达成,且不手动也达标)
- 11-04:再 −0.023(claude)→ ~4.98 GiB;若 D 档亦清 → ~4.55 GiB。

### 3.3 ⚠️ 新桶 signal-backup2 的前置(切桶前必查,防"新桶爆额度")

- **pre-upload/ 是唯一"无 lifecycle 且无代码清就会堆满"的前缀**:日增 ~1.08 GiB/天(10-04 实测 1.42 GB/日、10-05 1.28 GB/日;audit 估 ~1.08 GiB/天【文档】r2-backup-prefix-lifecycle-audit-20261005.md §3.2/§3.3)。**新桶若缺 `pre-upload/` 7 天规则,约 9 天爆 10 GB 免费额度。**
- **动作项**:#178/#179 切换时,请确认用户已在 CF dashboard 为**新桶**配好同套 5 条(pre-upload 7 / weekly 28 / monthly 365 / claude-backup 30 / backup 14;large-json、decommissioned、mac-backups 不配)。#179 报告建议"直接在已建好的空桶上照抄同一套规则"。

---

## 4. 「不可清」清单(生产在用 / 唯一副本 / 刻意保留;禁止为凑数字当可清)

| 项 | 体量 | 不可清理由 | 清了会丢什么 |
|---|---|---|---|
| signal-backup/mac-backups/archive/mac-backups-2026-10-01.tar.zst | 2.122 GiB | 10-04 用户拍板"传 R2 归档,本机先留"=**异地容灾副本**(【文档】r2-archive-upload-20261004.md;独立复核 PASS r2-archive-review-20261004.md)。本机有源目录+压缩包+恢复脚本(~/tmp) | 丢异地容灾(本机单点) |
| signal-backup/large-json/ flat | 433.4 MiB | **唯一副本**(staticdata git 已排除 >20MB 大 JSON;R2 flat 是唯一备份)。当前还有 D 档前提未满足(新桶未就位) | 大 JSON 无备份(数据丢失风险) |
| signal-backup/decommissioned/ | 10.5 MiB | 刻意保留(退役归档,无 prune) | 退役历史归档 |
| signal-data/nav_bucket/ | 0.523 GiB | 现行(桶化净值;前端双读现行路径之一) | 基金净值断供 |
| signal-data/trade_sim/ + trade_sim_data/ | 0.550 GiB | 现行(模拟回测 HTML+JSON;前端 app.js:8952/29981/29987 活) | 模拟回测弹窗/详情断供 |
| signal-data/industry/ | 0.120 GiB | 现行(前端 app.js:25451-25457;check_r2_consistency 检查对象) | 行业 tab 断供 |
| signal-data/etf/、index/、lab/、accum_nav/、public_fund/、fund_score/、data/(活部) | ~1.6 GiB | 现行(前端/worker 多处活引用,见 §1.2 各"消费方") | 对应功能断供 |
| signal-data/data/daily_brief_tts_\*(16 mp3) | 14.1 MiB | **历史 AI 预测语音,前端历史回看可播**(app.js:28727 仅需该日 meta.tts_available===true 即渲染播放按钮,URL=/r2/data/同名 mp3);09-07 后未再生成,但历史期对象无过期设计 | 历史语音回放能力 |
| signal-data/offshore_fund/(7 件套) | 0.145 GiB | **P2-15"移 R2"存档(唯一副本)**——定时链 8-22 停(update_all.sh:217"零消费方"),本地(本机+云上)已无该文件;去留待"场外基金路线图"决策(pending-features-index #80 P2-15 未决) | 场外基金 7 件套数据(R2 为唯一副本)。**若日后用户确认该数据不再需要,可另行拍板清理 145 MiB** |
| signal-backup/monthly/ | 0.282 GiB | 滚动月备,已配 365 天 lifecycle,自动清(不必手动) | 月回溯窗口 |

---

## 5. #178 切换前云上前提核查(只读,密钥值全程未打印)

### 5.1 三处核查结果(2026-10-05)

| # | 核查点 | 结果 | 证据 |
|---|---|---|---|
| ① | 云上 `/home/ubuntu/code/trade-data/.env` | `R2_BACKUP2_ENDPOINT`**存在(1)**、`R2_BACKUP2_BUCKET`**存在(1)**、`R2_BACKUP2_ACCESS_KEY_ID`**存在(1)**、`R2_BACKUP2_SECRET_ACCESS_KEY`**存在(1)**;`R2_BACKUP_BUCKET` **不存在(0,无覆盖)** | grep -c 计数,未打印任何值 |
| ② | 云上 systemd unit(`trade-backup-db` / `trade-update-all` 等全部 `trade-*.service`) | 全部 `EnvironmentFile=/home/ubuntu/code/trade-data/.env`;另注入 `GIT_REPO=/home/ubuntu/code/trade-data-signal`、`REPO=/home/ubuntu/code/trade-data`、`MAIN_REPO=...` | `cat /etc/systemd/system/trade-*.service`(主控/本 agent 双人核对) |
| ③ | 本机 `~/code/trade/.env` | 同样 **4 键全在(各 1)**、`R2_BACKUP_BUCKET` **不存在(0)**(共 20 行) | 同 ① 方式 |

### 5.2 生产等价环境路由实测(实证,非静态阅读)

- 用 #178 worktree 版代码(`BACKUP2_BUCKET` 默认 `signal-backup2`、`_route_bucket` 见 upload_r2.py feat/178-r2-backup2-route-20261005 分支 L286-299/L405-412)+ **真实 .env** 加载(云上,`REPO=/home/ubuntu/code/trade-data`),实测:
  - `BACKUP_BUCKET = "signal-backup2"`(新默认生效,无环境覆盖)
  - `BACKUP2_HOST = 2455352499fc04ddbd92d33e0a0e8614.r2.cloudflarestorage.com`(非空)
  - `_route_bucket("signal-backup2") → 新账号凭据`(AK 前缀 b3bdd5…);`_route_bucket("signal-backup") / ("signal-data") → 老账号凭据`
- 另:#179 复核已证新桶存在且为空(token 具备 ListObjects 权限;主控五动作实测 PUT/HEAD/DELETE/复查全过,见 r2-backup-prefix-lifecycle-audit-20261005.md 顶部复核注)。

### 5.3 结论(一行,与报告顶部一致)

**✅ 合并 #178 + 部署后,云上备份写入正确路由新桶 signal-backup2;不会因缺 4 键回退老账号→404 失败**(四键在位+无覆盖+全 systemd 指向 trade-data/.env+生产等价路由实测,四层证据互证)。**唯一联合前置=新桶 lifecycle 5 条配齐(§3.3)。**

---

## 6. 复现命令段(每条数字可复核)

```bash
# ① 两桶全量明细(前缀×对象数×字节;本报告 §1 主表数据源)
#    云上执行(注意 REPO 注入,否则 load_env 找不到 .env——upload_r2.py 的 ROOT 经 symlink 解析到 trade-data-signal)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  "REPO=/home/ubuntu/code/trade-data /home/ubuntu/code/trade-data/.venv/bin/python /tmp/r2_cleanup_assess.py"
# (本机留存同内容明细: /tmp/r2_assess_detail.json,4,527,582 B;本机复算前缀聚合/按日/分类用 python3 直读该 JSON)

# ② 关键对象 LastModified(§1.3 时效证据)
#    云上:s3_request('GET','',query='list-type=2&prefix=<P>&max-keys=1000',bucket='signal-data')
#    对 P ∈ {data/industry, data/daily_brief_tts_, probe/, r2test/, test/, __speedtest, sss.jpg, overview.json}

# ③ #178 闸:路由判定(生产等价)
#    云上:加载 worktree 版 upload_r2.py(复制为 /tmp/upload_r2_feat178.py)+ 真 .env 后打印
#    BACKUP_BUCKET / BACKUP2_HOST / _route_bucket('signal-backup2') / _route_bucket('signal-backup')

# ④ 前端引用核(判定"死/活"的代码侧)
#    本机:grep -rn "data/industry-" static-site/ scripts/ worker/ | grep -v .min.
#         grep -n "r2/industry/" static-site/app.js            # 现行加载 = industry/ 前缀(app.js:25451-25457)
#         grep -rn "offshore_fund_" static-site/*.js           # 空=零引用
#         grep -rn "r2/trade_sim_data\|r2/lab/\|r2/index/\|r2/etf/" static-site/*.js  # 活前缀证据
# ⑤ fund_nav 前置(清理前必跑):云上 .venv/bin/python scripts/check_r2_consistency.py
```

---

## 7. 诚实标注(局限 / 未验项 / 待拍板)

1. **本报告全程只读**:未执行任何删除/上传;A/B/C/D 档均为"拍板后另派执行"的候选清单。
2. **lifecycle 无法从代码侧读取**:`GetBucketLifecycleConfiguration` 对该 S3 凭证 403(见 r2-archive-upload-20261004.md §⑤);本报告 hit 的 5 条规则以用户 dashboard 实测(10-05)为准,行为佐证=claude-backup/ 61→30 的实际回收。**"到期清空时点"为按规则的推算值**(按对象 LastModified 逐日到龄),非已发生事实。
3. **外部引用无法程序化穷尽**:A4(s s.jpg)等早期素材的"站外引用(社交分享缓存)"无法由代码排除,已按"无站内消费方"判、并标注风险;A1/A3 有源文件在位,恢复零成本。
4. **fund_nav 清理窗口(10-07~10-14)与前置验证未到**:本次仅核在"可清候选"档;前置(每日 PUT 256 稳定/无 severe/check_r2_consistency PASS)需执行前复核。
5. **D 档(flat 433.4 MiB)依赖"新桶就位+回读验证"**,该前置今天尚未满足(新桶空,首轮 flat 尚未跑)→ 列为"切换后阶段"。
6. **offshore_fund/ 为唯一副本存档(P2-15)**,本报告不主动建议清;如用户确认场外基金路线图不再需要,可另拍板释放 0.145 GiB。
7. **任务书与实况的一处纠正**:任务传闻中"本机 86 散文件已删"**不准确**——R2 侧 86 散文件已于 10-02 删净(【文档】r2-mac-backups-restore-20261002.md),**本机 `~/code/trade-data/data/mac-backups-20261001/` 86 文件仍在**(10.171 GiB,拍板"本机先留")。
8. **数字口径**:GiB(1073741824)为主;CF 计费 GB(10^9)口径下现状 11.78 GB,超额度更甚,结论方向不变。
9. **待用户拍板事项汇总**:①A 档 163.9 MiB 是否清;②B 档 fund_nav 10-07 后是否执行(前置核后);③C 档 legacy 10-07 后补刀是否执行;④D 档切换后是否执行;⑤新桶 lifecycle 5 条是否已配齐(§3.3,#178 联合前置);⑥offshore_fund/(P2-15)去留。

---

## 参考

- docs/ops/r2-backup-prefix-lifecycle-audit-20261005.md(老桶 8 前缀普查 + #179 lifecycle 建议 + 新桶复核注)
- docs/ops/r2-archive-upload-20261004.md / r2-archive-review-20261004.md(mac-backups 归档上传 + 独立复核)
- docs/ops/r2-mac-backups-restore-20261002.md(86 散文件取回 PASS + 删 R2 散文件)
- docs/ops/cf-edge-egress-probe-20261002.md(probe/ 对象来历:临时 worker 探测,"读后即删"设计)
- docs/ops/r2-backup-bucket-capacity-20261002.md(主桶 31,470 对象普查,root 5/r2test/test 计数)
- memory: fund-nav-bucket-p3-followups(fund_nav 拍板窗口)、fetchjson-skip-gz(.gz 废弃)、test-baseline-v112-anchor(基准概念,无关)、cf-workers-large-json-404-r2-fallback(worker /data/ 路由机制)
