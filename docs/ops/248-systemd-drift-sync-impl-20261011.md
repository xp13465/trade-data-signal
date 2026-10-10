# #248 systemd unit 漂移仓库侧同步 — 实施报告

- 日期:2026-10-11 | 分支:`feat/248-systemd-drift-sync` | 类型:仓库侧同步(不触云上)
- 关联:#238 OOM 加固(残留项「repo 内 2 份 unit 快照过期未同步」)、`scripts/cloud_unit_patrol.sh`、`main-merge.sh` 闸门 7.8

## 1. 背景与定性

- 云上 `trade-cloud-unit-patrol.timer` 每日 08:27 跑 `scripts/cloud_unit_patrol.sh` → `systemd_timeout_gradient_audit.py --check-snapshot`,把云上 `/etc/systemd/system/trade-*.{service,timer}` 与仓库快照 `docs/deploy/systemd-units-cloud-snapshot.txt` 逐字段全量比对;漂移即 `notify --severe`(去重 6h)。
- 差异 = `trade-fapi-daily.service` 三字段:`MemoryHigh=1.5G` / `MemoryMax=2G` / `MemorySwapMax=512M` —— **云上有、仓库两副本无**(逐日升级,今天 08:27 将 days=3 critical)。
- **定性:云上是对的** —— #238 OOM 加固(2026-10-09 07:13-07:24,9/9 PASS,有意为之);**仓库两份副本过期**。故只改仓库、**不触云上**。

## 2. 权威值双源交叉核(一致 PASS)

- **源 A — 云上实值(只读)**:
  `ssh -i /Users/linhuichen/tdsignal.pem -4 -o ConnectTimeout=10 ... ubuntu@122.51.111.173 'timeout 10 systemctl cat trade-fapi-daily.service'`
  输出 `[Service]` 段 `TimeoutStartSec=0` 之后三行:`MemoryHigh=1.5G` / `MemoryMax=2G` / `MemorySwapMax=512M`(真文件 `cat` 19 行,逐字节)。
- **源 B — #238 加固报告**:`docs/ops/fapi-daily-oom-host-hardening-20261009.md`(`MemoryHigh=1.5G` / `MemoryMax=2G`;`MemorySwapMax=512M` 于 07:24 补,`systemctl show` 复读 `MemorySwapMax=536870912`)+ `...-verify-20261009.md`(`/etc/systemd/system/trade-fapi-daily.service:15:MemoryHigh=1.5G` / `:16:MemoryMax=2G`)。
- **结论:双源一致,取值 `1.5G` / `2G` / `512M`**(格式/单位/位置逐字节照文件现有行文)。

## 3. 四者比对关系与改法

- 四者:`doc §2 生成源`(`docs/deploy/systemd-units-20260912.md`,`gen_systemd_units.py` 的解析源)· `仓库快照`(`systemd-units-cloud-snapshot.txt`,`@@@FILE:` 云上固化 dump,权威真值清单)· `云上实值`(`/etc/systemd/system/trade-*.{service,timer}`)。
- **闸门 7.8**(`main-merge.sh` L374-386):`--dump <快照> --check-doc` ⇒ 断言「doc §2 **==** 快照」。
- **patrol**(`cloud_unit_patrol.sh`):`--units-dir /etc/systemd/system --snapshot <快照> --check-snapshot` ⇒ 断言「云上 **==** 快照」。
- ⇒ 要让闸门绿 **且** patrol rc=0,**doc §2 与快照都必须 == 云上实值** ⇒ **两份一起改**(只改一份两边总有一个红)。
- **改法(改动最小化)**:在两文件 `trade-fapi-daily.service` 块的 `TimeoutStartSec=0` 之后、`StandardOutput=...` 之前插入三行(与云上同位、同格式)。共 **2 文件 × +3 行**,不动其它任何行。

## 4. 机检证据(全 PASS)

| # | 检查 | 命令 | 结果 |
|---|---|---|---|
| a | **闸门 7.8 实际机检**(读自 `main-merge.sh` L382-384) | `python3 scripts/systemd_timeout_gradient_audit.py --dump docs/deploy/systemd-units-cloud-snapshot.txt --check-doc` | **rc=0**(82 unit 逐字段全量比对通过) |
| b | **patrol 比对本地复刻**(拉云上 82 unit 到 `/tmp/cloudunits` 再跑) | `python3 scripts/systemd_timeout_gradient_audit.py --units-dir /tmp/cloudunits --snapshot docs/deploy/systemd-units-cloud-snapshot.txt --check-snapshot` | **rc=0**(云上 unit 与仓库快照一致,82 unit) |
| c | **字节比对** snapshot fapi-daily 块 vs 云上真文件 | `diff /tmp/cloud_fapi_raw.txt /tmp/snap_fapi_block.txt` | **rc=0**(19 行逐字节一致) |
| d | **patrol 自检模式** | `bash scripts/cloud_unit_patrol_selftest.sh` | **PASS=8 FAIL=0** |
| e | **systemd 相关 pytest** | `.venv/bin/python -m pytest -q scripts/tests/test_223_timeout_gradient_copy.py scripts/tests/test_196_patrol_visibility_20261005.py` | **46 passed** |

- (b) 即巡逻器将看到的比对:云上 == 快照 ⇒ patrol rc=0。
- (a)+(b) 合起来:doc §2 == 快照 == 云上实值 三源闭合。

## 5. diff 摘要

```
docs/deploy/systemd-units-20260912.md          +3 行(L418-420)
docs/deploy/systemd-units-cloud-snapshot.txt   +3 行(L202-204)
```
- 新增行(两文件同):`MemoryHigh=1.5G` / `MemoryMax=2G` / `MemorySwapMax=512M`
- `git status --porcelain`:仅上述 2 文件(`M`),无无关脏文件。

## 6. 举一反三(§23.3)

- **同数据源/同组件消费点清单**:仓库内该 unit 副本仅 2 份(`grep -rln trade-fapi-daily.service docs/deploy/ scripts/` 只命中这两份 + 一个无关提及)→ **已全覆盖**。
- **生成源联动**:`gen_systemd_units.py` 直接复制 doc §2 的 ini 块 ⇒ 重跑生成器会带上内存三行,**不再回退**旧值。
- **待办对账**:pending-index #238 明列残留「repo 内 2 份 unit 快照过期未同步」= **本任务**,已消。
- 其余 40 个 `trade-*.service` 无内存限制属 #238 的另一独立残留(待评估),非本任务范围。

## 7. 复现命令

```bash
# 权威值(云上只读)
ssh -i /Users/linhuichen/tdsignal.pem -4 -o ConnectTimeout=10 -o ServerAliveInterval=5 \
    -o ServerAliveCountMax=3 ubuntu@122.51.111.173 'timeout 10 systemctl cat trade-fapi-daily.service'

# 闸门 7.8
python3 scripts/systemd_timeout_gradient_audit.py --dump docs/deploy/systemd-units-cloud-snapshot.txt --check-doc

# patrol 比对(拉云上 units 后本地复刻)
ssh -i /Users/linhuichen/tdsignal.pem -4 ... ubuntu@122.51.111.173 \
    'timeout 20 sh -c "cd /etc/systemd/system && tar -cf - trade-*.service trade-*.timer"' | tar -C /tmp/cloudunits -xf -
python3 scripts/systemd_timeout_gradient_audit.py --units-dir /tmp/cloudunits \
    --snapshot docs/deploy/systemd-units-cloud-snapshot.txt --check-snapshot

# 自检
bash scripts/cloud_unit_patrol_selftest.sh
.venv/bin/python -m pytest -q scripts/tests/test_223_timeout_gradient_copy.py scripts/tests/test_196_patrol_visibility_20261005.py
```

## 8. 未触云上声明

全程 ssh **只读**(`systemctl cat` / `cat` / `tar` 拉取);**未写任何云上文件、未 start/restart/enable/disable 任何 unit**。云上 unit 与 timer 状态原封不动。