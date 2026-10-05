# #185 新桶首轮回填现状 + s06 unit 配置核对(只读核查,2026-10-05 22:15~22:45 CST)

环境:云上 ssh -i ~/tdsignal.pem ubuntu@122.51.111.173;仓库 /home/ubuntu/code/trade-data-signal @ 1d0898a97(main,与本机 HEAD 同);
全程只读(未改云上任何文件/未 PUT/DELETE 任何 R2 对象/未 commit/未启停 unit)。所有 R2 操作走 scripts/upload_r2.py 的
s3_request/_list_keys(带 continuation-token 分页,#126),跨账号路由 bucket==signal-backup2 → 新账号端点(实测 host=2455352499fc04ddbd92d33e0a0e8614.r2.cloudflarestorage.com)。

## 1. 新桶回填现状 —— 判定:填齐

命令(云上 venv python + import upload_r2 分页枚举全桶):
  TOTAL objects=31682 bytes=1901207753 (1813.1 MB) pages=32
  prefix                        objects          bytes
  decommissioned                      2     1116091071  (1064.4 MB)
  large-json                      31673      454482606  (433.4 MB)
  backup                              2      110197083  (105.1 MB)
  monthly                             2      110197083  (105.1 MB)
  weekly                              2      110197083  (105.1 MB)
  git-branch-bundles                  1          42827  (0.0 MB)
  large-json: total=31673 flat=31673 legacy日期目录=0

对照期望 ≈3.1 万对象 / ≈450MB:large-json = 31673 对象 / 433.4MB → 对象数逐一对上(见 §2 MISSING=0);字节数 433.4MB(gz)
对应 manifest 原始合计 2491683947B(2376.3MB)的 18.2% 压缩比,与「≈450MB」同量级(差 4%,非缺口)。

各前缀明细(LastModified 为 UTC):
- backup/ : sentiment_20261005.db.gz(39.4MB,13:01Z)+ etf_national_team_20261005.db.gz(70.8MB,13:05Z)
- weekly/ monthly/ : 同两个 DB(13:02~13:09Z),即当日副本,符合「周/月备份=当日日备份副本」设计
- decommissioned/ : public_fund.db.bak-20261003_104704.zst(558MB,06:57Z)+ .wal...bak.zst(558MB,06:35Z)
- git-branch-bundles/20261005/branches-not-in-main-20261005.bundle(42.8KB,06:13Z)
- claude-backup/ mac-backups/ pre-upload/ : 0 对象(新桶当日建,切桶后尚无写入,属预期)

## 2. #185② 完整性验证 —— MISSING=0,7/7 逐位一致

期望集来源 = 云上 staticdata 仓 /home/ubuntu/code/trade-data-signal-staticdata/.gitignore 的「large-json auto-generated」
受管区块(L27~L31708,共 31673 行 "/data/<rel>",由 scripts/large_json_excludes.py 维护的权威单一源),
映射 key = large-json/<rel>.gz。该源与上传器自己写的 manifest 相互独立(避免报告↔实现互证闭环)。

  期望(gitignore 区块)=31673  实际(large-json/ 前缀)=31673
  MISSING=0   EXTRA=0
  manifest 中提到 key 数=31673, 与期望集差=0(第二独立佐证)

抽样 GET 后逐位比对(7 个,含 3 个大文件;生产解释器 /home/ubuntu/code/trade-data/.venv/bin/python 3.11.15):
  signal_kelly_trades_sdc.json.gz(14.7MB) / signal_kelly_trades.json.gz(14.6MB) / accum_nav_map.json.gz(6.9MB)
  signal_kelly_trades_sdc_parts/lab_etf_approx__E_p1.json.gz(49.5KB) / fund_nav/{561700,001305,003397}.json.gz(5~6KB)
五项断言全 True:etag==md5(对象体) / md5(对象)==md5(源文件按生产参数重压 gz) / sha256(gunzip(对象))==sha256(源文件)
/ 对象 etag == 上传侧状态清单 data/.r2_large_json_state.json 记录的 md5 / state size == 源文件字节数。结果 7 通过 0 失败。

尺子先验(§5.2):注入 1 字节差异 → 断言可检出 PASS;第一次跑用 /usr/bin/python3(3.10.12)时 gz 容器 md5 全不匹配,
归因=解释器不同(gzip 头/模块行为差异),换生产 venv python(3.11.15)后 4/4 复现 ETag → 结论:容器差异是我尺子选错,
非数据问题(解压后内容 sha256 全程一致)。

## 3. s06 unit 配置核对 —— 三方一致

实测(云上):
- trade-s06-snapshot.service 文件内 TimeoutStartSec=3300;systemctl show -p TimeoutStartUSec → 55min(=3300s)
  (注:新版 systemd 属性名是 TimeoutStartUSec,-p TimeoutStartSec 返回空,勿误读成未设)
- trade-s06-snapshot.timer: OnCalendar=Mon..Fri *-*-* 20:35:00, Persistent=true
- ConditionPathExists: **未设**;快照中仅 3 个单元有此字段(check_monitor_heartbeat / cloud_unit_patrol / check_r2_consistency),s06 不在其中

一致性机检(现成脚本,非手抄):
- 本机 python3 scripts/systemd_timeout_gradient_audit.py --dump docs/deploy/systemd-units-cloud-snapshot.txt --check-doc
  → ✓ 生成源(doc §2)与权威 unit 源一致(82 unit,逐字段全量比对通过) EXIT=0
- 云上 python3 scripts/systemd_timeout_gradient_audit.py --units-dir /etc/systemd/system --snapshot docs/deploy/systemd-units-cloud-snapshot.txt --check-snapshot
  → ✓ 云上 unit 与仓库快照一致(82 unit,逐字段全量比对通过) EXIT=0
- 尺子先验:复制快照到 /tmp 注入 TimeoutStartSec=1234 → FAIL EXIT=1(差异字段 1 处,trade-s06-snapshot.service) → 机检非空转
- 梯度审计:trade-s06-snapshot.service 外层 3300 / 内层 run_to 合计 3000 → OK(余量 300s)

## 4. 10-08 首跑时刻确认

- systemctl list-timers trade-s06-snapshot.timer → NEXT Tue 2026-10-06 20:35:00 CST;LAST Mon 2026-10-05 20:35:01 CST
- data/trade_dates.txt:20261005/06/07 均不在(非交易日),20261008 在;2026-10-08 = Thu,落在 Mon..Fri 内
- 今晚 20:35 实测:timer 触发 → 脚本按交易日闸门 exit 0(journal: 20:35:02 Deactivated successfully;log:「2026-10-05 20:35:02 非交易日, 跳过 S06 快照重生」;10-01/10-02 同)
⇒ 10-06、10-07 会触发但被闸门跳过;**节后首个交易日 2026-10-08(周四)20:35 为首次真跑**(闸门放行),与前两次「跳过」同源路径已验证可跑。

## 5. 回填实际路径(与任务背景的差异)+ 异常项

- 首轮全量回填实际由 **16:52 那轮**完成:staticdata_backup_async_20261005_165200.log(trigger=backfill)
  「large-json 上传 31673/31673 -> signal-backup2/large-json/(私有桶)」[step3.5] 4798s(16:52→18:12);
  journal:staticdata-backup-165200.service 18:12:32 Deactivated successfully。
- **17:50 update-all 触发的那轮(18:00:51)large-json 段是「跳过」的**:
  「[step3.5b large-json R2 上传] 跳过(trade_backup_r2.lock 被占, 非阻塞不排队; ...次日幂等补传)」耗时 8s。
  ⇒ 只看 17:50 日志会误判「没回填」;实际 16:52 那轮已全量完成,且 21:16 那轮增量 36/36 -> signal-backup2(292s)证明切桶后增量正常。
- 切桶时点佐证:10-05 16:52 之前的各轮(00:32/00:48/02:16/05:11/12:25)全部写老桶 signal-backup(日志中 signal-backup2 出现 0 次)。
- 无失败单元(systemctl --failed = 0 units)。
- 待派 implementer 的项:无(P0/P1 级)。观察项 2 条(非本次任务范围):
  ① staticdata 仓 git 报「too many unreachable loose objects; run git prune」+ 存在 .git/gc.log → 清理属删除类动作,须按 §25 先备份后删;
  ② 新桶 claude-backup/ 目前 0 对象,若 Claude 自备份链路期望每日入桶,需另行确认其触发是否已切到新桶。

## 复现段(2026-10-05 22:5x 落档时由主控补;内容为上文各段方法的汇总指针,逐条命令原文见各段内联)

- 环境:云上 `ssh -i ~/tdsignal.pem ubuntu@122.51.111.173`;解释器**必须用生产 venv** `/home/ubuntu/code/trade-data/.venv/bin/python`(3.11.15)。
  **不要用系统 `/usr/bin/python3`(3.10)重压 gz 做比对** —— 容器 md5 会对不上(§2 已归因:是尺子选错解释器,非数据问题)。
- ① 桶枚举:`import scripts/upload_r2.py`,走 `s3_request` / `_list_keys`(continuation-token 分页,32 页)按前缀统计对象数与字节。
- ② 完整性:期望集 = `trade-data-signal-staticdata/.gitignore` 的「large-json auto-generated」受管区块(L27~L31708,31673 行 `/data/<rel>`);
  抽样 GET 后五项断言 = etag==md5(对象体) / md5(对象)==md5(源文件按生产参数重压 gz) / sha256(gunzip(对象))==sha256(源文件)
  / 对象 etag == `data/.r2_large_json_state.json` 记录的 md5 / state size == 源文件字节数。
- ③ unit 核对:`systemctl show -p TimeoutStartUSec trade-s06-snapshot.service` + 现成脚本 `python3 scripts/systemd_timeout_gradient_audit.py`
  的 `--check-doc`(本机)与 `--check-snapshot`(云上),外加「快照副本注入 1234 → 应 FAIL」的尺子先验。
- ④ 首跑时点:`systemctl list-timers trade-s06-snapshot.timer` + `data/trade_dates.txt` 交易日闸门。
- ⑤ 回填路径:`~/code/trade-data/data/logs/staticdata_backup_async_20261005_165200.log`(trigger=backfill)+ journal 对应单元。
