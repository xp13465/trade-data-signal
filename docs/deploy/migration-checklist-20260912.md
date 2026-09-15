# 云上部署迁移清单(2026-09-12)

> 配套:资源实测 `resource-benchmark-20260912.md`(磁盘/内存数据)。
> 目标:把 trade 项目从 macOS 本机迁到阿里云轻量服务器,照着本清单逐步做。

## 0. 买机(已定结论)

- 阿里云轻量 · **通用型 2核4G** · **40G SSD**(磁盘治理后够用)· 镜像 **Ubuntu 22.04 LTS** · 地域华东(上海)或华南(深圳)
- 若只能 2核2G:内存贴线,必须做 §5 加 swap 兜底,否则峰值 OOM

## 1. 单仓部署(省一半磁盘,实测关键)

本地 `trade-data` 的代码目录(app/config/scripts 等 5 个)是 **symlink 双份双写**,才搞出 32G 占用。云上**只部署一份**:

- `git clone` 主仓 + 数据仓各一份,**不要复刻本地的 symlink 双树结构**
- 代码一份、数据产物一份,天然比本地省一半

## 2. 依赖安装

- Ubuntu 装 Python 3 + pip,按 requirements 装 pandas/baostock/akshare/playwright 等
- ⚠️ 完整依赖清单待精确盘点(以 requirements.txt 或逐脚本 import 为准)

## 3. 备份治理(⚠️ 最大风险,必做,不做 40G 一个月打满)

现状:备份 604M/天(双仓各存一份),占磁盘 41%。目标改「**单仓 + 保留 7 天**」,稳态降到 2.1G。

- 改 `backup_db.sh`:**保留天数参数化**(默认 7 天),只备一份(不再双仓各存)
- 加 cron 定期清理 N 天前的旧备份

## 4. 定时任务 launchd → systemd/cron(主要迁移工作量)

- `launchctl list | grep trade` 列出所有 plist,**逐个**迁到 systemd timer 或 cron
- 盘后定时任务时点(迁移后保持):15:35 / 16:00 / 17:50 / 20:35 / 22:00
- ⚠️ 完整 plist 清单待精确盘点(含 backfill/采集/export/deploy/daily_brief 等)
- macOS 专属 `pmset`/`caffeinate`(防睡眠)在 Linux 不需要——服务器不会睡眠,直接删

## 5. 加 swap(若 2G 内存)

实测 4 并行 pipeline 峰值 ≈ 1.7G。2G 内存贴线,加 2-4G swap 文件兜底(峰值不够时 swap 顶,慢但不 OOM)。

- `fallocate`/`dd` 建 swapfile → `mkswap` → `swapon` → 写进 /etc/fstab

## 6. 定期清日志

`trade-data/data/logs` 只涨不跌(近 7 天就涨了 227M)。加 cron 每周删 N 天前旧日志。

## 7. 代理配置(GitHub push + R2 上传)

国内服务器这两处必须走代理:

- GitHub push:`git config --global http.proxy http://...`(本机已有经验,dns-hijack-hosts 根治同源)
- R2 上传:服务器挂代理走海外出口,或走已有的 **CF Workers 中转**绕开直连

## 8. macOS 专属工具替换

- `qrcode` 用 framework python 跑的 → Linux 换普通 python 生成
- `magick`(ImageMagick 生成 ico/透明化)→ Linux 装 imagemagick 或去掉
- 其余 macOS-only 工具逐一排查替换

## 9. 迁移后验证

- 跑一遍关键任务(采集 → export → 上传 R2),核对数据产物与线上一致
- `curl` 验线上 JSON/R2 产物更新到位

## 待精确盘点项(服务器到手前派 researcher 补齐)

1. 完整 Python 依赖清单(requirements)
2. 完整 launchd plist 清单(所有定时任务)
3. 备份脚本当前逻辑细节(改保留天数前先读)
