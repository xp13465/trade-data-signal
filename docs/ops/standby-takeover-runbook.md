# 备用机接管 / 回切 / 回滚手册(实测校正版)

> 版本:2026-11-16(在 2026-11-15 骨架上按**本轮实测**重写)· 状态:**可照做**(命令逐条标了实测方式,见 §12)
> 写作过程云端**只读**:只跑了 `systemctl list-timers` / `systemctl show` / `systemctl cat` / `ls`,**没有停任何生产任务、没有碰生产库**;唯一副作用是云上 `/tmp/rb-timers.txt` 一个临时清单文件(非生产路径,可随时删)。
> 本轮出现的所有数字都来自本机实测、云上只读实测或本任务的演练证据(路径见 §11),**没有编造、没有凭印象估抄**(凡合计值都由实测数相加);时间统一写 **CST(+0800,北京时间)**,需要世界时间的地方同时标 UTC。

---

## 0. 一页速查

| 问题 | 答案 | 依据 |
| --- | --- | --- |
| 现在能不能接管? | **能,数据面可接管**;但有一批东西不在恢复集里,接管后通知链、公募库、站点展示要单独补 | §3 前置检查 / §9 缺口 |
| 手上有哪个版本? | `2026-11-13-364b4665cd4242c89779f321-8b0a4852b9`,业务日 2026-11-13,4 个文件 217,259,895 字节,4/4 sha 一致 | `standby_sync.py status` 实测 |
| 恢复点有多旧? | 恢复点年龄 **1 个交易日**(2026-11-16 01:09 实测),阈值 2 个交易日 | 同上 |
| 接管要多久? | **数据面约 24.4 分钟**;其中 **24.1 分钟(99%)是公募库 public_fund 慢链**;不带公募库约 16 秒(纯命令) | §4 分步实测 |
| 丢多少数据? | 演练 2026-11-15 23:47 开始、2026-11-16 00:45 CST 收尾(UTC 15:47–16:45);恢复点 `db_cutoff` = 2026-11-13 周五 ⇒ **0 个交易日 / 2 个自然日**(14/15 是周末)。注:sentiment.db 自身最大日期是 2026-11-14,比 `db_cutoff` 多 1 天,判缺口仍只认 `db_cutoff` | RPO 实测 |
| 每天几点同步? | **01:00 CST**(launchd,已装并已真实触发过)| §12 |
| 一次同步多久? | 首次 28.6 秒(工具自记)/ 无新集合 1~2 秒 | §12 |

---

## 1. 名词(说人话)

| 名词 | 意思 | 在哪儿看 |
| --- | --- | --- |
| 云端主生产 | 唯一生产节点,云上 systemd timer 跑采集/发布 | `ssh` 云上 `systemctl list-timers` |
| 本机备用 | 这台 Mac(备用机),平时只同步+演练,不写生产 | `~/trade-standby/` |
| 恢复集合 | 一次捕获产出的"成套状态":清单 + 4 个压缩包 | 云上 `data/backups/state-capture-sets/<集合名>/` |
| 版本目录 | 本机把集合校验通过后固化的目录 | `~/trade-standby/archive/versions/<版本号>/` |
| `latest_verified` | 指向"最近一次校验通过的版本目录"的符号链接(原子切换) | `~/trade-standby/archive/latest_verified` |
| `db_cutoff` | 三个库各自 `MAX(date)` 里**最小的那个** = 所有库共同覆盖到哪天。**判数据截止日只认它** | 集合内层 `manifest.json` |
| `common_business_cutoff` | 集合里"最新触点",含文件修改时间,**不是**数据截止日 | 同上 |

---

## 2. 触发条件与判定:什么时候必须接管、什么时候只看着

### 2.1 必须接管(满足任一条)

| 现象 | 判据 | 为什么必须 |
| --- | --- | --- |
| 云端写库任务连续 2 个交易日没产出 | 云端最新业务日期连续 2 个交易日不前进(看首页数据日期,或 `check_data_gap`) | 数据断了,用户看到旧数据 |
| 云端主机不可达(宕机/欠费/被封) | `ssh` 连不上且控制台也进不去 | 没有生产节点 |
| 云端磁盘/数据库损坏 | 云端 `PRAGMA integrity_check` 非 `ok`,或磁盘满 | 数据可能已经坏了 |
| 云端定时任务集体失效 | `systemctl list-timers` 里 45 个 `trade-*.timer` 全部 `inactive`,且不是人为停的 | 没人写数据了 |

### 2.2 只观察(先别接管)

| 现象 | 先做什么 |
| --- | --- |
| 单个任务失败、下一轮自愈 | 看告警,不动生产;等一轮 |
| 数据落后 1 个交易日(节前/周末) | 正常,**别**按日历天数误判成故障 |
| 云端可 ssh、任务在跑,只是某个产物重生慢 | 观察,别切 |

### 2.3 铁律

- **不允许自动接管、不允许双写**(云与本机同时写同一份数据)。
- 接管 = 生产角色切换,**必须用户明确拍板"从 X 时点起由本机接管"**。
- 接管前先记下**冻结时点**和 `db_cutoff`,缺口 = `db_cutoff + 1 天` 到接管时点,逐日列清,不许重写时间戳装连续。

---

## 3. 前置检查(接管前 5 分钟,全只读)

### 3.1 身份核对

```bash
sysctl -n hw.model            # 期望 MacBookAir10,1
uname -m                      # 期望 arm64
sysctl -n hw.ncpu             # 期望 8
sw_vers -productVersion       # 期望 14.4.1(构建号 sw_vers -buildVersion = 23E224)
date +"%Y-%m-%d %H:%M:%S %Z%z"  # 期望 ... CST+0800
readlink /etc/localtime       # 期望 .../zoneinfo/Asia/Shanghai
```

本轮实测:`MacBookAir10,1` / `arm64` / `8` 核 / 16GB(`sysctl -n hw.memsize` = 17179869184)/ macOS `14.4.1`(23E224)/ `2026-11-16 01:12:10 CST+0800` / `Asia/Shanghai`。

### 3.2 代码与解释器

```bash
cd /Users/linhuichen/code/trade
.venv/bin/python3 --version      # 本轮实测 Python 3.11.0
git branch --show-current        # 记下当前分支,防误判"同步的是哪份代码"
```

> 注意(实测现状):launchd 里 `--repo-dir` 直接指向 **开发树** `/Users/linhuichen/code/trade`(不是独立 clone)。好处是不用再维护第二份代码;代价是**切分支/改脚本会立刻影响同步逻辑**。接管期间不要在这个树上做开发改动。

### 3.3 凭据

```bash
ls -l /Users/linhuichen/code/trade/.env          # 期望 -rw------- 权限 600
grep -o '^[A-Za-z0-9_]*=' /Users/linhuichen/code/trade/.env   # 只列字段名,不打印值
```

本轮实测:文件 21 行、权限 600、12 个字段;备用同步只用到其中 4 个 —— `R2_BACKUP2_ENDPOINT` / `R2_BACKUP2_BUCKET` / `R2_BACKUP2_ACCESS_KEY_ID` / `R2_BACKUP2_SECRET_ACCESS_KEY`。**手册里不写任何值**。

### 3.4 磁盘空间

```bash
df -h /System/Volumes/Data | tail -1     # 本轮实测:460Gi 总、385Gi 已用、41Gi 可用(91%)
du -sh ~/trade-standby/archive ~/trade-standby/restore-drills   # 2.1G / 7.3G
```

预算口径:下载前工具自己要求 ≥ 5 GiB(`--min-free-gb 5`);标准集合压缩 207MiB(217,259,895 B)、解压 700MiB(734,541,824 B);若要连 public_fund 一起恢复,**额外**要 823MiB(压缩,863,305,551 B)+ 3,028MiB(解压,3,175,059,456 B)。全算上峰值 ≈ 4.6GiB,再加 5GiB 保底余量更稳。

### 3.5 交易日历(判龄口径的命门)

```bash
tail -1 /Users/linhuichen/code/trade/data/trade_dates.txt   # 本轮实测 20261231
wc -l < /Users/linhuichen/code/trade/data/trade_dates.txt   # 本轮实测 8796 行
ls -l /Users/linhuichen/code/trade/data/trade_dates.txt     # mtime 2026-09-12 17:41
```

判据:文件最后一行 ≥ 今天 ⇒ 交易日口径可用;最后一行 < 今天 ⇒ 工具自动**降级为自然日**并标注「天(日历不可用回退自然日)」,周末会误报。当前覆盖到 2026-12-31(内容最后一次变更是 2026-07-07 的那次提交,9-12 只是拷贝时间),**跨年前必须重刷**,见 §10。

### 3.6 网络与远端清单(一条命令全测)

```bash
cd /tmp && /Users/linhuichen/code/trade/.venv/bin/python3 \
  /Users/linhuichen/code/trade/scripts/standby_sync.py \
  --root /Users/linhuichen/trade-standby --repo-dir /Users/linhuichen/code/trade status
```

本轮实测(2026-11-16 01:09:23,耗时 0.45 秒):`latest_verified: 2026-11-13-364b...`,`last_success_ts: 2026-11-16 01:00:05`,`business_date: 2026-11-13`,`latest_recovery_point_age_days: 1`(单位 `trading`),版本列表 1 条、`size_bytes: 217263649`。

判定表:

| 看到什么 | 结论 | 处置 |
| --- | --- | --- |
| `latest_verified: "(none)"` | 本机没有已验证版本 | 先补同步(§6/§8),别谈接管 |
| `latest_recovery_point_age_days` > 2 且单位是 `trading` | 恢复点过期 | 查云上备份是否还在产;仍要用旧点就如实记缺口 |
| 单位变成自然日却又带「日历不可用」标注 | 日历过期了 | 先按 §10 刷日历,再看判龄 |
| 命令报 TLS/签名错 | 网络或凭据问题 | 查 §12 里的历史缺陷是否复发 |

---

## 4. 接管步骤(按实测顺序,每步给命令/预期/失败怎么办/耗时预算)

> 本章命令全部在**隔离目录**里做,不动任何生产路径。实测容器:`~/trade-standby/restore-drills/20261115T154720Z/`。

### 4.0 第 0 步:冻结云端(写操作,必须用户拍板)

> ⚠️ 下面两条**本轮没有执行**(会停生产),属于"照抄可用、但只能在真正接管时跑"的命令。命令形态已用只读方式核过:`systemctl cat 'trade-*.timer'` 实测展开出 **45 个** unit 文件,证明通配符有效。

```bash
# 1) 先留一份"停之前有哪些任务"的清单,恢复时照着起
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  'systemctl list-timers --all --no-pager | grep -oE "trade-[a-z0-9-]+\.timer" | sort -u' \
  > ~/trade-standby/frozen-timers-$(date +%Y%m%d_%H%M).txt

# 2) 全停(定时器停 = 以后不再触发;正在跑的 service 不受影响)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 "sudo systemctl stop 'trade-*.timer'"

# 3) 需要连"当前这一轮"也停(会截断正在跑的任务,单独拍板)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 "sudo systemctl stop 'trade-*.service'"
```

验证:再跑一次 `systemctl list-timers --all --no-pager | grep -c 'trade-.*\.timer'` ⇒ 期望 `0`。
**记录冻结时点**(本地 `date -Iseconds`),后面算缺口要用。
失败怎么办:某条停不掉(报 unit not loaded)先 `systemctl status <unit>` 看状态,不要反复重启服务。

### 4.1 取版本号(1 秒)

```bash
readlink ~/trade-standby/archive/latest_verified
```

预期:`versions/2026-11-13-364b4665cd4242c89779f321-8b0a4852b9`(本轮实测)。
失败:`latest_verified` 不存在/不是链接 ⇒ 停,先按 §8 重做同步,不要手搓目录。

### 4.2 复验这个版本(11 秒)

```bash
cd /tmp && /Users/linhuichen/code/trade/.venv/bin/python3 \
  /Users/linhuichen/code/trade/scripts/standby_sync.py \
  --root /Users/linhuichen/trade-standby --repo-dir /Users/linhuichen/code/trade verify
```

预期(本轮实测,01:18:21→01:18:32):`复验 2026-11-13-364b... PASS (business_date=2026-11-13, files=4)`,退出码 0。
失败:报 sha 不符/文件缺失 ⇒ **这个版本不能用**,退回上一个版本或重新同步,别"差不多就用"。

### 4.3 校验压缩包(1 秒内)

```bash
cd ~/trade-standby/archive/versions/2026-11-13-364b4665cd4242c89779f321-8b0a4852b9
shasum -a 256 backup/state_20261115.tar.gz
```

预期(本轮实测):`628fed47edba3756908cbe881f3018dc48e2ef6c319e8fd673218deb7f600bec`,与 `manifest.json` 里 `state_20261115.tar.gz` 的 `sha256_gz` 逐位相同。
其余三个包的期望值(来自同一份清单,4/4 一致):

| 文件 | 字节 | sha256 |
| --- | --- | --- |
| `backup/sentiment_20261115.db.gz` | 59,286,140 | `df0bd960...f0371` |
| `backup/etf_national_team_20261115.db.gz` | 73,235,093 | `21bf6778...aa78` |
| `backup/stock_daily_20261115.db.gz` | 82,920,181 | `d7a7c021...9285` |
| `backup/state_20261115.tar.gz` | 1,818,481 | `628fed47...bec` |

### 4.4 解压三个小库(约 1.3 秒)

```bash
mkdir -p ~/trade-standby/restore-drills/$(date -u +%Y%m%dT%H%M%SZ)/dbs
cd ~/trade-standby/restore-drills/<刚建的目录>/dbs
for n in sentiment etf_national_team stock_daily; do
  gunzip -c ~/trade-standby/archive/versions/2026-11-13-364b4665cd4242c89779f321-8b0a4852b9/backup/${n}_20261115.db.gz > ${n}.db
done
ls -l
```

预期字节(本轮实测):236,056,576 / 261,947,392 / 215,965,696。
失败:解压报 `unexpected end of file` ⇒ 压缩包坏了,回 §4.3 重验 sha,再不行重新同步。

### 4.5 三小库完整性 + 行数对账(约 9 秒)

```bash
cd ~/trade-standby/restore-drills/<目录>/dbs
sqlite3 sentiment.db "PRAGMA integrity_check; SELECT COUNT(*) FROM score_daily; SELECT COUNT(*) FROM signal_daily;"
sqlite3 etf_national_team.db "PRAGMA integrity_check; SELECT COUNT(*) FROM etf_daily;"
sqlite3 stock_daily.db "PRAGMA integrity_check; SELECT COUNT(*) FROM baostock_daily_raw;"
```

本轮复跑实测:`ok` / 38856、72140 / `ok` / 1528786 / `ok` / 427096 —— 与清单里 `tables` 的数字逐个相等;`sentiment.db` 的 `integrity_check` 耗时 2.81 秒。
失败:`integrity_check` 非 `ok` ⇒ 库坏了,别用;行数差 1 行也要停下查版本对不对。

### 4.6 解包状态集(约 0.4 秒)

```bash
cd ~/trade-standby/restore-drills/<目录>
mkdir -p state && tar -xzf ~/trade-standby/archive/versions/2026-11-13-364b4665cd4242c89779f321-8b0a4852b9/backup/state_20261115.tar.gz -C state
tar -tzf ~/trade-standby/archive/versions/2026-11-13-364b4665cd4242c89779f321-8b0a4852b9/backup/state_20261115.tar.gz | wc -l
```

本轮实测:清单登记 **1491 个文件**(合计 16,723,023 字节),`tar -tzf` 列 **1530** 条(多出的 39 条是目录项),逐文件 sha 与内层清单 **1491/1491 一致**。
内容包含:T0 冻结表 `signal_kelly_etf_freeze.json`(实测 **28,641 条**,键范围 `19910205|sh|buy_aux` ~ `20261113|sw_801960|buy_aux`,文件 5,900,784 B)、采集游标 `baostock_progress.json` / `mootdx_progress.json`、发布状态 `.r2_*_state.json` / `unit_exit_ledger.json`、通知状态(`signal_notified.json` / `nt_signal_notified.json` / `alerts/alert_digest*` / `alerts/warning_buffer*`)、证明台账 `logs/r2-db-source-*.json`(6 个)、`audit/frozen_missing/`(205 个条目)、发布证据 `ops_delivery/`(403 个回执 + 280 个发布证据文件,后者只记对象名/sha/字节数,**不含载荷本体**)。
失败:数量对不上 ⇒ 记录差多少、差哪些(manifest 里 `missing` 字段),不许"少几个也照用"。

### 4.7 公募库 public_fund(可选,慢链,约 22 分钟)

> 这个库**不在集合清单里**(清单里 `excluded` 明写"大库走独立链"),要单独流式拉。实测:压缩 863,305,551 字节 → 解压 3,175,059,456 字节,22 张表,`integrity_check=ok`,最大业务日 20261113。

```bash
mkdir -p ~/trade-standby/restore-drills/<目录>/dbs
cd /Users/linhuichen/code/trade
.venv/bin/python3 docs/scripts/restore_r2_db_backup.py \
  --name public_fund --out-dir ~/trade-standby/restore-drills/<目录>/dbs
```

预期:脚本打印分片下载信息,最后产出 `public_fund_<日期>.db`;`PRAGMA integrity_check` = `ok`,页数 775161。
失败怎么办:
- 中途卡住超过 10 分钟无进度:实测出现过一次约 7 分钟无写入后自恢复,**先等**;确要重来就**删掉本次的 gz 再重拉**(实测:重复拉取会覆盖 gz 导致 md5 变,已恢复的 .db 不受影响)。
- 磁盘不够:先扩空间,别删唯一可用版本换空间。

**能不能跳过?** 能。这个库只服务公募筛选,信号链不读它。只要信号链,跳过本步,接管时间从 24.4 分钟降到几十秒(实测纯命令 16.1 秒 + 人工段)。

### 4.8 建最小运行环境(约 5 秒)

```bash
R=~/trade-standby/restore-drills/<目录>/repo
mkdir -p $R/scripts $R/data $R/config
cp -R /Users/linhuichen/code/trade/app $R/app
cp /Users/linhuichen/code/trade/scripts/{check_signals.py,notify.py,alert_denoise_rules.py,alert_digest_delivery.py} $R/scripts/
cp ~/trade-standby/restore-drills/<目录>/dbs/*.db $R/data/
cp /Users/linhuichen/code/trade/config/{indicators.yaml,universe_rules.yaml,site.yaml} $R/config/
cp -R ~/trade-standby/restore-drills/<目录>/state/state-capture/*/. $R/data/
printf 'REPO=%s\nTRADE_SENTIMENT_DB=%s\nNOTIFY_SOURCE=restore-drill\nALERT_LEDGER_DISABLE=1\nALERT_DIGEST_DISABLE=1\n' \
  "$R" "$R/data/sentiment.db" > $R/.env
```

**这一步的关键是"把外发通道掐掉"**:只复制 3 个 yaml,不复制 `config/email.json`、`feishu.json`、`telegram.json`、`subscriptions.json`、`sub_pwd.json`、`brief_push.json`(本轮实测这 6 个在演练树里全部 `ABSENT`),也不复制 `scripts/sync_subscriptions_from_cf.py`。所以即使代码想发通知也发不出去。

### 4.9 跑代表业务链(约 0.2 秒)

因为 `check_signals.py` 里有多条发送路径,接管演练**必须先打桩再跑**,直接裸跑 `--dry-run` 也不保险(本轮用的打桩覆盖 `notify.send/send_to/send_tiered/send_feishu/send_telegram`,并把 `smtplib.SMTP_SSL` 换成"一调用就抛错")。最小可复现做法:把下面这段写成 `$R/run_business_chain.py`,再执行。

```bash
cat > $R/run_business_chain.py <<'PY'
import os, sys
REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO); sys.path.insert(0, os.path.join(REPO, "scripts"))
os.environ.update({"REPO": REPO,
                   "TRADE_SENTIMENT_DB": os.path.join(REPO, "data", "sentiment.db"),
                   "ALERT_LEDGER_DISABLE": "1", "ALERT_DIGEST_DISABLE": "1",
                   "NOTIFY_SOURCE": "restore-drill"})
import notify, smtplib
calls = []
def _stub(name, ret):
    def f(*a, **k):
        calls.append(name); return ret
    return f
for fn, ret in (("send", {}), ("send_to", {}), ("send_tiered", {}),
                ("send_feishu", False), ("send_telegram", False)):
    setattr(notify, fn, _stub(fn, ret))
class Tripwire(RuntimeError): pass
def _blocked(*a, **k):
    calls.append("smtplib.SMTP_SSL"); raise Tripwire("SMTP blocked")
smtplib.SMTP_SSL = _blocked
import check_signals as cs
rc = cs.main(["--date", "20261113", "--dry-run"])
import sqlite3
con = sqlite3.connect(f"file:{REPO}/data/sentiment.db?mode=ro", uri=True)
def one(sql):
    return con.execute(sql).fetchone()[0]
sig = one("SELECT COUNT(*) FROM signal_daily WHERE date='20261113'")
sc = one("SELECT COUNT(*) FROM score_daily WHERE date='20261113'")
idx = one("SELECT COUNT(*) FROM index_daily WHERE date='20261113'")
con.close()
print("CHAIN_RC", rc, "signals", sig, "scores", sc, "index", idx, "notify_calls", len(calls))
sys.exit(0 if rc == 0 and len(calls) == 0 and sig > 0 else 1)
PY
cd $R && /Users/linhuichen/code/trade/.venv/bin/python3 run_business_chain.py
```

预期(本轮 2026-11-16 01:22 复跑实测):退出码 0,末尾打印 `CHAIN_RC 0 signals 27 scores 9 index 135 notify_calls 0`(`signals 27` / `notify_calls 0` 是当轮屏幕原样,`scores 9` / `index 135` 取自同轮断言结果);日志里 `查询到 27 个信号(追买=3, 卖=1, 追止损卖=20, 波段持有=3)`,`dry-run:跳过实际发送 + 不更新 signal_notified.json`。
日期要换成你要接管的业务日(本例 `20261113` 是本轮恢复集的业务日)。

失败怎么办:报 `overview.json 不存在` / `signal_stats.json 不存在` 是**预期警告**(这两个的文件本体都不在恢复集,见 §9 第 8、10 条),链会走降级路径继续跑;只要 `CHAIN_RC 0` 且信号数 > 0 就算过。若 `notify_calls > 0` ⇒ **立刻停**,说明打桩没生效,不许继续。

### 4.10 接管耗时账(实测)

| 步骤 | 秒 | 备注 |
| --- | --- | --- |
| gz sha256 校验 | 0.2 | |
| 解压三小库 | 1.3 | 各 0.4~0.5 秒 |
| 三小库校验(sha+integrity+行数) | 9.2 | |
| 状态包校验+解压+逐文件核 | 0.4 | 1491 个文件 |
| **public_fund 拉取** | **1332.1** | 平均约 0.65 MB/s,是主要瓶颈 |
| **public_fund 校验** | **115.2** | md5+integrity+全表 |
| 建隔离环境 | 4.7 | |
| 状态只读核验 | 0.1 | |
| 业务链+断言 | 0.2 | |
| **合计(干净路径)** | **1463.4 = 24.4 分钟** | 含返工的全部运行 1742.7 秒,不计入 |

**未纳入这些数字的**:人工决策、找密钥、落位到生产路径、停/起云端 systemd(§4.0)、云上 DNS/证书/Worker 部署、站点静态数据重建、通知外发通道打通。真接管要在这 24.4 分钟上**再加人工作业时间**。

---

## 5. 验证清单(五条全绿才算接管成功)

| # | 检查 | 命令 | 本轮实测结果 |
| --- | --- | --- | --- |
| 1 | 四库完整性 | `sqlite3 <库> "PRAGMA integrity_check;"` × 4 | 全 `ok`(sentiment / etf_national_team / stock_daily / public_fund) |
| 2 | 状态集 sha | 逐文件 sha256 对比内层清单 | 1491/1491 一致,缺失 0 |
| 3 | 业务链断言 | §4.9 `run_business_chain.py` | rc=0;27 信号(追买3/卖1/追止损卖20/波段持有3);score_daily 9 行全有限值(无 NaN);index_daily 135 行收盘全非空 |
| 4 | 通知**未补发** | 打桩计数 + 通知状态文件只读核对 | notify 调用 0 次、SMTP 尝试 0 次;`alert_digest` 队列 8 条未动、`warning_buffer` 0 条、`last_sent_day=2026-11-14` |
| 5 | 站点数据就绪度 | 看 `static-site/data/` 有没有 `overview.json` 等 | **没有本体,只有证据**:集合里有发布回执(登记 `overview.json` 3,246,238 字节 / `a-stock-1y.json` 758,176 字节及其 sha256),但**静态数据文件本体不在集合内**,要等采集链重出或从 R2/staticdata 副本取(见 §9 第 8 条) |

补充断言(建议一起看,命令照抄,换成你的业务日):

```bash
cd ~/trade-standby/restore-drills/<目录>/dbs
sqlite3 sentiment.db "SELECT COUNT(*) FROM score_daily WHERE date='20261113';
                      SELECT signal, COUNT(*) FROM signal_daily WHERE date='20261113' GROUP BY signal;
                      SELECT COUNT(*) FROM index_daily WHERE date='20261113';"
```

本轮实测:`9`;`buy_special|3`(追买)、`sell|1`(卖)、`sell_stop_loss|20`(追止损卖)、`band_hold|3`(波段持有),合计 27;`135`。冻结历史键数 28,641(见 §4.6)。

---

## 6. 停止备用同步(需要时)

现装两个 launchd 任务(本轮实测 `launchctl list | grep -i standby` 两条都在,`last exit code` 都是 0):

| 标签 | 作用 | 实测调度 |
| --- | --- | --- |
| `com.trade.standby-sync` | 每天主同步 | `launchctl print` 里 `"Hour" => 1` / `"Minute" => 0` ⇒ **01:00 CST** |
| `com.trade.standby-sync-catchup` | 开机/每小时补跑(今日已成功则静默) | `run interval = 3600 seconds`;实测 01:38:33 触发并打印「今日已成功,补偿入口静默退出」 |

### 6.1 查

```bash
launchctl list | grep -i standby
launchctl print gui/$(id -u)/com.trade.standby-sync | sed -n '/event triggers/,/}/p'   # 看 Hour/Minute
launchctl print gui/$(id -u)/com.trade.standby-sync-catchup | grep -E "state|run interval|last exit"
pgrep -fl standby_sync      # 有在跑的实例会列出来;本轮实测无输出(退出码 1)
```

### 6.2 停(不碰云端,纯本机)

```bash
launchctl bootout gui/$(id -u)/com.trade.standby-sync
launchctl bootout gui/$(id -u)/com.trade.standby-sync-catchup
```

本轮用同域假任务(一个 `/bin/echo` 的临时 LaunchAgent)实测了这套命令:先 `launchctl bootstrap gui/501 <plist>` 装载成功,再 `launchctl bootout gui/501 <label>` 返回 0,`launchctl print` 变成
`Could not find service "..." in domain for user gui: 501`;假任务文件已删除。

验证点:
- `launchctl print gui/$(id -u)/<标签>` 报 `Could not find service` ⇒ 已卸下。
- `pgrep -fl standby_sync` 无输出 ⇒ 没有实例在跑。
- 再跑 §3.6 的 `status`,`last_success_ts` 不再前进。
- **保留版本**:`ls ~/trade-standby/archive/versions/` 仍在,`latest_verified` 指向不变(停同步不影响已存版本)。

> 说明:`bootout` 会向正在跑的实例发终止信号。中途被杀是安全的——同步是"先下到 staging → 校验 → 固化版本目录 → 原子换 symlink",被杀最多留个 staging 残留,下次运行只清自己登记的 `staging-*`。实在想稳,先 `pgrep` 确认没在跑再 bootout。

### 6.3 要不要用户拍板

不需要。纯本机、只停调度、不动云端、不动已存版本。

---

## 7. 回切(本机 → 云端)

> 全章需用户拍板。**严禁双写**:本机没停写之前,不许让云端恢复写库。

1. **确认云端故障解除**,但**先别起云端任务**。
2. 做数据对账:本机接管期间产生的增量 vs 云端最后一笔。区间 = 云端 `db_cutoff` 之后 ~ 本机停写时点。
3. 停本机:按 §6.2 两个 `bootout`,记下本机停写时点。
4. 把增量按既有采集/发布链补进云端(**不手工拼 SQL 猜口径**)。大 JSON 用既有入口 `scripts/restore-large-json.sh`。
5. 云端自检:`PRAGMA integrity_check` = `ok` + 关键表行数 + 最新业务日期已前进到回切日。
6. 按 §4.0 记录的那份 `frozen-timers-*.txt` 逐个起回来:

```bash
# 清单存在本机(§4.0 第 1 条),通过标准输入喂给云上 xargs,一条条 systemctl start
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'sudo xargs systemctl start' \
  < ~/trade-standby/frozen-timers-*.txt
```

(也可以直接 `sudo systemctl start 'trade-*.timer'` 全起,但会一并起那些本来就没开的;按清单起更稳。)

验证:`systemctl list-timers --all --no-pager | grep -c 'trade-.*\.timer'` ⇒ 期望回到 **45**(本轮云端只读实测的当前值);等一整轮跑批,看业务日期连续推进 ≥ 1 个交易日;线上三查(主链 commit / 数据层字段 / 前端展示)齐。
7. 缺口如实写进交接记录(`db_cutoff` → 回切日),**不许重写时间戳伪装连续**。

未实测项(诚实标注):第 2、4、5、6 步都要真写云端生产库/timer,本轮按任务边界没执行;命令形态与 unit 名来自云端只读实核。

---

## 8. 回滚(接管不成 / 接管后撤回)

### 8.1 卸载调度

```bash
launchctl bootout gui/$(id -u)/com.trade.standby-sync
launchctl bootout gui/$(id -u)/com.trade.standby-sync-catchup
rm -f ~/Library/LaunchAgents/com.trade.standby-sync.plist \
      ~/Library/LaunchAgents/com.trade.standby-sync-catchup.plist
```

### 8.2 重装调度(这次装的是**已安装副本**,时点 01:00)

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.trade.standby-sync.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.trade.standby-sync-catchup.plist
launchctl print gui/$(id -u)/com.trade.standby-sync | sed -n '/event triggers/,/}/p'   # 期望 Hour=1 Minute=0
```

> ⚠️ 已知漂移(本轮发现,未在本任务修):仓库里的主 plist **模板**还写着 `00:30`,而**已安装副本**是 **01:00**——已安装副本的注释明确写了「用户 2026-11-15 拍板 01:00,替代早期模板示例 00:30」。结论:01:00 是**有效决定**,00:30 只是模板没跟上。重装**必须用 `~/Library/LaunchAgents/` 下的已安装副本**,别用仓库模板覆盖;模板对齐另派任务处理。

### 8.3 恢复配置 / 保留旧版本

- 配置:`.env` 与 `config/*.json` 都在 `~/trade-standby` 之外的原位置(开发树),回滚不需要搬。
- 版本:`archive/versions/` **只增不删**,`latest_verified` 永不删;保留策略是日保 7 + 最近 4 个 ISO 周各 1 + 至少 2 份已验证版本(`retention --dry-run` 可预览,本轮实测"保留 1 个、拟删 0 个")。
- 删任何东西前按项目铁律先备份并验可恢复;验收目录 `restore-drills/20261115T154720Z/`(7.3G)建议保留到 **2026-11-22** 供复查。

---

## 9. 已知缺口与未决载荷(不许用 `complete=true` 掩盖)

集合清单里 `complete=true` 只表示"**清单登记的东西**齐了",下面这些是**已声明不捕获 / 不在清单**的东西:

| # | 缺什么 | 量级/证据 | 处置 |
| --- | --- | --- | --- |
| 1 | `public_fund` 公募库 | 独立链:gz 863,305,551 B → 解压 3,175,059,456 B,22 表,约 22 分钟 | 按 §4.7 单独拉;信号链不需要它 |
| 2 | `.r2-protected/payloads` | 1.21GB / 1737 个内容寻址载荷(云上试跑实测) | **声明排除**:confirmed 载荷与 R2 当前对象同内容,nav_bucket 旧版可由 public_fund.db 再生;未决锚点载荷另立归档任务 |
| 3 | `signal_kelly_trades.json` | 32MB,2026-09-12 后未更新 | **待拍板**(疑已被新链路替代) |
| 4 | `daily-k.parquet` | 181MB,超单文件 64MB 捕获预算 | **待拍板**(2026-10-08 后未更新) |
| 5 | `baostock_logs` | 6.9MB / 67 文件 | **待拍板**(采集分块诊断日志,无恢复语义) |
| 6 | 3 个可重建静态参考 | `sw_components.json` 52KB / `stock_codes.json` 55KB / `trade_dates.txt` 79KB | 从源重建,不占恢复集 |
| 7 | `news_digest` 新闻归档 | 约 1.5MB / 65 文件 | 已有 R2 `news-digest` 通道 + staticdata 双副本,不重复进集合 |
| 8 | 站点已发布静态数据**本体** | 集合里只有发布回执(280 个 `ops_delivery/publication/*` 文件,每个约 1KB,记录对象名/sha256/字节数,如 `overview.json` 3,246,238 字节);`overview.json`/`a-stock-*.json` 等**内容本身不在集合** | 采集链重出,或从 R2 `staticdata` 副本取;只跑信号链时前端展示拿不到 |
| 9 | 通知密钥四件 | `email.json` / `feishu.json` / `telegram.json` / `subscriptions.json`(另有 `sub_pwd.json` / `brief_push.json`) | 见下面「从哪里取」 |
| 10 | `signal_stats.json` | 不在状态集(本轮核对状态包内无此文件) | 信号链走降级路径(不影响信号产出,影响统计展示) |

### 9.1 通知密钥从哪里取、谁有权

- 位置:云端 `/home/ubuntu/code/trade-data-signal/config/`(本轮只读实测:6 个真件都在,权限 `-rw-------`,属主 `ubuntu`)。仓库里只有 `*.example` 模板,真件**不在 git**。
- 取法(需用户点头,写明"取哪几个、给谁"):
  ```bash
  scp -i ~/tdsignal.pem \
    ubuntu@122.51.111.173:/home/ubuntu/code/trade-data-signal/config/{email,feishu,telegram,subscriptions}.json \
    /Users/linhuichen/code/trade/config/
  chmod 600 /Users/linhuichen/code/trade/config/*.json
  ```
- 谁有权:只有持有 `~/tdsignal.pem` 且能 `ssh ubuntu@122.51.111.173` 的人(= 你本人)。**不要**把它们塞进恢复集合或任何 git 仓。
- 没有这些文件,信号还能算出来,但**发不出去**(邮件/飞书/Telegram 全断),这是设计上的安全默认。

---

## 10. 每月 / 跨年维护

### 10.1 交易日历(最容易忘、后果最阴)

**为什么要管**:判龄读的是**备用机自己仓库**的 `data/trade_dates.txt`,云上每天刷新的是云上那份,本机不会自动跟。文件过期后判龄退化成自然日,周末/节假会误报"恢复点过期"。

**做法(每月 1 日 + 跨年前各做一次)**:

```bash
cd /Users/linhuichen/code/trade
tail -1 data/trade_dates.txt        # 先看覆盖到哪天
.venv/bin/python3 - <<'PY'
from app.calendar import refresh_trade_dates
d = refresh_trade_dates()
print("count", len(d), "min", min(d), "max", max(d))
PY
tail -1 data/trade_dates.txt        # 再看一次,期望 max 前进
```

本轮实测:隔离副本里跑刷新,得到 `count 8797 min 19901219 max 20261231` —— 也就是说 **akshare 这个源当前也只给到 2026-12-31**。所以:
- 现在(2026-11)覆盖够用,`status` 正常出"1 个交易日"。
- **跨年后(2027-01-01 起)如果刷新结果仍止于 20261231,就说明上游没给次年数据**:此时要么把次年交易日手工补进文件,要么接受"日历不可用回退自然日"的偏响告警(周末可能误报 severe)。**别把误报当真实故障去查数据**。
- 另一条稳的路:从云端把当天那份拷过来(云上由采集链每天刷):
  ```bash
  scp -i ~/tdsignal.pem ubuntu@122.51.111.173:/home/ubuntu/code/trade-data/data/trade_dates.txt \
      /Users/linhuichen/code/trade/data/trade_dates.txt
  ```
  (只读拷贝,不改云端;本轮未执行,留给下次维护时用。)

### 10.2 磁盘余量

```bash
df -h /System/Volumes/Data | tail -1     # 本轮 41Gi 可用
du -sh ~/trade-standby/archive ~/trade-standby/restore-drills
/Users/linhuichen/code/trade/.venv/bin/python3 /Users/linhuichen/code/trade/scripts/standby_sync.py \
  --root /Users/linhuichen/trade-standby --repo-dir /Users/linhuichen/code/trade retention --dry-run
# 本轮:保留 1、拟删 0
```

余量低于 10GiB 就先清演练目录(按"先备份后删除"铁律,演练目录本身就是临时产物,可直接删)。

### 10.3 版本保留复查

`archive/versions/` 每多一个版本约 207MiB(`du -sh` 实测;4 个压缩包合计 217,259,895 字节);默认日保 7 + 周保 4,`latest_verified` 永不删。看到"拟删"超过 2 个,先确认 `latest_verified` 与至少 2 份已验证版本还在,再让它删。

### 10.4 每月顺手核一遍

```bash
launchctl list | grep -i standby                      # 两个任务在不在
launchctl print gui/$(id -u)/com.trade.standby-sync | sed -n '/event triggers/,/}/p'   # 还是 01:00 吗
tail -5 ~/trade-standby/logs/standby_sync_$(date +%Y%m%d).log
```

---

## 11. 证据与记录位置

| 内容 | 路径 |
| --- | --- |
| 首次同步证据(清单/耗时/sha/版本目录) | `/tmp/standby-first-sync-evidence/` |
| 云端开开关 + 成套捕获证据 | `/tmp/cloud-capture-enable-evidence/` |
| 完整隔离恢复演练证据包 | `/tmp/restore-drill-evidence/`(含 `drill-20261115T154720Z/evidence/`、报告 `restore-drill-report.md`、脚本 `restore-drill.sh`) |
| 演练产物(7.3G,建议留到 2026-11-22) | `~/trade-standby/restore-drills/20261115T154720Z/` |
| 本机已固化版本 | `~/trade-standby/archive/versions/2026-11-13-364b4665cd4242c89779f321-8b0a4852b9/`(`verify_record.json` 记 2026-11-15 23:05:21 验证通过,28.6 秒) |
| 同步日志 | `~/trade-standby/logs/standby_sync_YYYYMMDD.log` + `launchd.{out,err}.log` + `catchup.{out,err}.log` |
| 同步状态 | `~/trade-standby/state/standby_sync_state.json` |

**下次演练该更新的数字**(照这张表对):
1. RTO 合计秒数与 public_fund 两段耗时(对应 §4.10 表);
2. 恢复集版本号 / 业务日 / 4 个包字节与 sha(对应 §4.3 表);
3. 状态集文件数(现 1491)与字节(现 16,723,023);
4. 四库 integrity 与关键行数(score_daily 38856 / signal_daily 72140 / etf_daily 1528786 / baostock_daily_raw 427096 / public_fund 22 表);
5. 业务链信号数(现 27:追买 3、卖 1、追止损卖 20、波段持有 3)与评分行数(9)、指数行数(135);
6. 恢复点年龄与缺口交易日数;
7. 磁盘余量与各目录占用。

---

## 12. 命令实测状态总表

> ✅ = 本轮实跑过;🔍 = 云端/本机只读实核;📄 = 读源码/帮助核实;⛔ = 本轮不可测(写明原因)。

| 命令 | 用途 | 状态 | 结果 |
| --- | --- | --- | --- |
| `sysctl -n hw.model` / `uname -m` / `sw_vers` / `date +%Z%z` | 认机器身份 | ✅ | MacBookAir10,1 / arm64 / 14.4.1(23E224)/ CST+0800 |
| `df -h /System/Volumes/Data` | 看空间 | ✅ | 41Gi 可用(91% 已用) |
| `standby_sync.py status` | 判能不能接管 | ✅ | 0.45 秒;版本 2026-11-13-364b…;恢复点年龄 1 个交易日 |
| `standby_sync.py sync --dry-run` | 演练同步 | ✅ | 2 秒;「远端无新集合…dry-run: 无新集合, 不写状态」rc=0 |
| `standby_sync.py verify` | 复验版本 | ✅ | 11 秒;`PASS (files=4)` rc=0 |
| `standby_sync.py retention --dry-run` | 看保留计划 | ✅ | 保留 1、拟删 0 |
| `launchctl list \| grep -i standby` | 看任务在不在 | ✅ | 两条,exit code 0/0 |
| `launchctl print gui/$UID/com.trade.standby-sync` | 看调度时点 | ✅ | `"Hour" => 1` / `"Minute" => 0` |
| `launchctl print …-catchup` | 看补跑周期 | ✅ | `run interval = 3600 seconds` |
| `launchctl bootstrap gui/$UID <plist>` | 装任务 | ✅(假任务实测) | rc=0,print 可见 |
| `launchctl bootout gui/$UID/<label>` | 停任务 | ✅(假任务实测) | rc=0;之后 print 报 `Could not find service` |
| `pgrep -fl standby_sync` | 查有无实例 | ✅ | 无输出(退出码 1) |
| `shasum -a 256 backup/state_20261115.tar.gz` | 验状态包 | ✅ | `628fed47…bec` 与清单一致 |
| `tar -tzf … \| wc -l` | 数状态包条目 | ✅ | 1530(含 39 个目录项;清单文件 1491) |
| `sqlite3 <库> "PRAGMA integrity_check;"` | 验库 | ✅ | 三库 ok(sentiment 2.81 秒);public_fund 见演练证据 ok |
| `sqlite3 <库> "SELECT COUNT(*) FROM …"` | 对行数 | ✅ | 38856 / 72140 / 1528786 / 427096 全对 |
| `upload_r2.py download-db sentiment <dir>` | 拉小库 | ✅ | 59,286,140 B(gz)→ 236,056,576 B(.db),rc=0 |
| `docs/scripts/restore_r2_db_backup.py --name public_fund --out-dir <dir>` | 流式拉大库 | 📄(本轮未重跑;演练报告有实测) | 参数表已核;演练实测 1332.1 秒 / 3,175,059,456 B / 22 表 / integrity ok |
| §4.9 打桩业务链 `run_business_chain.py` | 验信号链 | ✅(本轮复跑) | rc=0;27 信号;notify 0;SMTP 0 |
| `ssh … systemctl list-timers` | 看云端任务 | 🔍 | 45 个 `trade-*.timer` |
| `systemctl cat "trade-*.timer"` | 验证通配符可用 | 🔍 | 展开 45 个 unit 文件 |
| `systemctl show -p TimeoutStartUSec trade-backup-db.service` | 核备份超时 | 🔍 | `3h 30min` |
| `systemctl is-active …timer` | 核在跑 | 🔍 | `trade-backup-db.timer` / `trade-update-all.timer` 均 `active` |
| `systemctl stop/start 'trade-*.timer'` | 冻结/恢复云端 | ⛔ | 会停生产,本轮只做只读核;通配展开已证有效 |
| 云端改库/改名/删 WAL、`download-db` 落位到生产路径 | 回滚生产库 | ⛔ | 写生产,需用户拍板;本轮不执行 |
| `launchctl bootout` 真任务 | 停真同步 | ⛔ | 会停掉每日同步;用假任务证明了同一命令的语义 |
| 业务链之外的采集/发布链 | 接管后的持续生产 | ⛔ | 本轮只验代表链(信号链);采集/发布链未在隔离环境跑过,接管时要逐段起、逐段验 |

---

## 13. 与其它文档的关系

- DB 灾备的权威细节(保留层级、周/月归档、public_fund 特殊口径)见 `docs/backup-restore.md`。
- 同步工具的安装/参数/通知语义见 `ops/standby/README.md`。
- 本手册只讲"接管这一刻照着敲什么、敲完看什么、缺什么"。三者有冲突时:数据口径以 `docs/backup-restore.md` 为准,同步行为以 `scripts/standby_sync.py` 实际代码为准,流程以本手册为准。
