> 归档自 /tmp/383-retire-report-20261127.md,2026-11-27;原始路径为临时文件,本副本为持久归档

# #383 C 阶段报告:C 根旧 sentiment.db 退役(2026-11-27)

## 1. 指纹记录(删除前,云上 /home/ubuntu/code/trade-data-signal/data/;2026-11-27 21:36-21:38 CST)
| 文件 | md5 | size(B) | mtime |
|---|---|---|---|
| sentiment.db | 7ae8ba7f203b7661a06b793f9f1bb864 | 232124416 | 2026-10-28 21:38:34.059645051 +0800 |
| sentiment.db-wal | d41d8cd98f00b204e9800998ecf8427e | 0 | 2026-10-28 21:40:00.807722144 +0800 |
| sentiment.db-shm | b7c14ec6110fa820ca6b65f5aec85911 | 32768 | 2026-11-26 21:15:01.338224946 +0800 |

- 删除前 lsof：无进程持有（`lsof_rc=1`, 21:35:52；删除前 22:31 又核一次仍空）。
- sqlite3 只读（`file:...?mode=ro&immutable=1`，python3 sqlite3，云上无 sqlite3 CLI）：
  - 表 18 个：alert_log, board_daily, collect_log, daily_metric, futures_accuracy, futures_ih_detail_acc, futures_position, history_overwrite_audit, index_daily, industry_width_daily, intraday_amount_history, intraday_snapshot, manual_entry, score_daily, signal_daily, signal_intraday_log, sqlite_sequence, users
  - daily_metric: COUNT(*)=235250, MAX(date)=20261028
  - 其它抽查：signal_daily=71884, score_daily=38726, index_daily=496957, board_daily=0
  - PRAGMA quick_check = ok；page_count=56671, page_size=4096

## 2. 备份证据
- 云上打包：`tar czf /tmp/c-root-sentiment-db-20261127.tar.gz sentiment.db sentiment.db-wal sentiment.db-shm`
  → 58,120,849 B，md5 `0e99d043c554e83689addd1adabeb6b8`，`tar tzvf` 三件在包内。
- 拉回 mac 副本：scp → `/Users/linhuichen/code/trade-data-archive/c-root-sentiment-db-20261127.tar.gz`（58,120,849 B，md5 同上，逐位一致）。
- 上传 R2 私有桶（既有工具链 `scripts/upload_r2.py upload-decommissioned`，凭据从 .env 读，未进命令行）：
  - **key：`signal-backup2/decommissioned/c-root-sentiment-db-20261127.tar.gz`**（58,120,849 B 直传，私有退役前缀，不受滚动清理）
  - 上传日志：`✓ c-root-sentiment-db-20261127.tar.gz (56758KB(已压缩直传)) -> signal-backup2/decommissioned/...`（21:47:19 CST）
  - 云上无 .env（无 R2 凭据），故备份路线 = 云上打包 → scp 回 mac → mac 侧 upload_r2 上传。

## 3. 核验可恢复证据（实测,不是"应该有"）
- 用既有恢复脚本 `bash scripts/restore-r2-backup.sh --bucket signal-backup2 --out-dir /tmp/restore-383 c-root-sentiment-db-20261127.tar.gz`：
  - 输出：`✓ 命中桶 signal-backup2 | 还原 58120849B(网络) → /tmp/restore-383/c-root-sentiment-db-20261127.tar (232161280B)`（22:23 CST，网络实拉 58,120,849B，与上传尺寸一致）
- 解包 + md5 逐位对比（恢复副本 vs 第 1 步指纹）：
  | 文件 | 恢复副本 md5 | 源 md5 | 一致 |
  |---|---|---|---|
  | sentiment.db | 7ae8ba7f203b7661a06b793f9f1bb864 | 7ae8ba7f203b7661a06b793f9f1bb864 | ✅ |
  | sentiment.db-wal | d41d8cd98f00b204e9800998ecf8427e | d41d8cd98f00b204e9800998ecf8427e | ✅ |
  | sentiment.db-shm | b7c14ec6110fa820ca6b65f5aec85911 | b7c14ec6110fa820ca6b65f5aec85911 | ✅ |
  - size 三件也逐位一致（232124416 / 0 / 32768）；MISSING=0、漂移=0。

## 4. 回读抽查（恢复副本上再跑）
- 表 18 个；daily_metric COUNT(*)=235250、MAX(date)=20261028；quick_check=ok；signal_daily=71884、score_daily=38726、index_daily=496957 — 与第 1 步逐项一致。

## 5. 删除清单 + 时间
- 时间：**2026-11-27 22:31:40 CST**（在 21:55-22:05 窗口之外；rm 前 lsof 再核无持有）
- 删除三件（云上 `/home/ubuntu/code/trade-data-signal/data/`）：sentiment.db、sentiment.db-wal、sentiment.db-shm
- 删后复核：`ls | grep -i sentiment` 0 条残留；顺带清理本次云上临时包 `/tmp/c-root-sentiment-db-20261127.tar.gz`（R2 + mac 各有一份副本）。

## 6. 云上释放空间
- 本任务对象合计：232,124,416（db）+ 32,768（shm）+ 0（wal）= **232,157,184 B ≈ 221.4 MiB**；另清理云上临时 tar 58,120,849 B（≈55.4 MiB）→ 本任务总释放 ≈ **290,278,033 B ≈ 276.8 MiB**。
- df 观测（/home/ubuntu avail）：删前 18,823,315,456 B → 删后 19,060,510,720 B（+237,195,264 B，含并发任务同时段波动；清临时包后 19,110,989,824 B）。

## 7. 恢复路径（§25④）
- 从 **R2 私有桶 `signal-backup2`，key `decommissioned/c-root-sentiment-db-20261127.tar.gz`** 取回，放回云上 `/home/ubuntu/code/trade-data-signal/data/`：
  ```
  # 在 mac 仓根执行（凭证走 .env）
  bash scripts/restore-r2-backup.sh --bucket signal-backup2 --out-dir /tmp/restore c-root-sentiment-db-20261127.tar.gz
  tar xf /tmp/restore/c-root-sentiment-db-20261127.tar -C /tmp/restore/extract   # 得三件原文件
  scp -i ~/tdsignal.pem /tmp/restore/extract/sentiment.db* ubuntu@122.51.111.173:/home/ubuntu/code/trade-data-signal/data/
  ```
  备用副本：mac `/Users/linhuichen/code/trade-data-archive/c-root-sentiment-db-20261127.tar.gz`（同 md5）。
- 注意：该库为 C 根旧库（读方已收敛 D 树，#383），恢复仅作历史取证用。

## 8. 边界维度清单（七轴,§5.8①③实施关出口）
| 维 | 测/不测 | 理由+来源 |
|---|---|---|
| 输入域（文件三件 md5/size） | 测 | 任务书步骤 1/3，三件全量 md5 对账 |
| 状态组合（lsof 持有 vs 空闲） | 测 | 任务书硬约束"删除前 lsof 再核"，两次核空 |
| 时序（删除窗口 21:55-22:05） | 测 | 删除实际 22:31:40，避开窗口 |
| 上下游依赖（读者是否已切 D 树） | 测（沿用上轮） | tester 上轮已核 brief_ledger 读 D 树，本任务复测 mtime 未变 |
| 极端值（0 字节 wal / 32KB shm） | 测 | 三件全备全核，wal 0 字节也纳入 |
| 回退路径（R2 恢复） | 测 | 实际从 R2 拉回并 md5 全等 + 数据可读 |
| 并发与重入（删除时其他任务写该库） | 不测 | 该库已无读者（lsof 空 + mtime 停 11-26），无并发写路径 |
