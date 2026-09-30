# 云服务器磁盘清理结果(2026-09-30,低风险档 ≈6G)

> 云机 122.51.111.173。依据诊断报告 `docs/ops/cloud-disk-usage-20260930.md` + 用户 2026-09-30 拍板「低风险档」授权 6 类白名单执行。全程不碰 git(.git/不做 gc)、不 kill 进程、不碰核心数据。

## 1. 一句话结论
6 类白名单全部清理完成:**52G 已用 → 45G,可用 4.7G → 13G,占用率 92% → 79%,实际回收 ≈7.0G**(backups 4.0G + .bak 1.05G + /tmp 0.85G + apt 0.19G + journal 0.4G + npm 1.7G 计)。git 零污染(status 空),核心 DB(public_fund/sentiment/etf)+ staticdata 9 目录 31239 数据本体零触碰。

## 2. 清理前后 df -h 对照
| 指标 | 清理前(2026-09-30 23:26) | 清理后(2026-09-30 23:5x) |
|---|---|---|
| `/` 总 | 59G | 59G |
| 已用 | 52G | **45G** |
| 可用 | 4.7G | **13G** |
| 占用率 | 92% | **79%** |
| /home | 41G | 35G |
| /tmp | 861M | 15M |
| /var | 2.0G | 1.5G |
| /usr | 3.6G | 3.6G(未动) |
| /swapfile | 4.1G | 4.1G(未动) |

## 3. 逐项「预期 vs 实收」表
| # | 项 | 预期(报告) | 实收(本次实测) | 操作与证据 |
|---|---|---|---|---|
| A1 | 主库 trade-data-signal/data/backups 清 >7天 | ≈4.0G(22份) | **4001923072B ≈4.0G(22份)** | `find backups -maxdepth 1 -name "*_*.db" -mtime +7 -delete`;剩 16 份(09-23~09-30,2.9G);`git ls-files --error-unmatch data/backups/`=未跟踪 |
| A2 | 历史 .bak 双副本 | ≈1.05G(6文件:主库+镜像各3大db) | **1095802880B ≈1.05G(6文件)** | 删主库+镜像各 3 个:etf_national_team.db.bak-accumnav-20260916/lof-20260915-144248/sentiment.db.bak-spikefix-20260915_101316;删前 lsof 无占用 |
| A3 | /tmp 历史产物 | ≈0.74G | **861M→15M ≈0.85G(207文件+4目录+16root文件)** | mtime<09-28 23:27 且非 lock/migrate_126/近48h/系统目录;probe 4 目录(kelly_trades_probe/sdc/tr_verify_ndo/sdc)整删;16 个 root 属主历史文件(604KB)sudo 删 |
| A4 | apt cache | 0.19G | **186M→28K ≈0.19G** | `sudo apt-get clean` |
| A5 | journald 限容 | ≈0.46G(656M→200M) | **656M→256M 回收≈0.4G** | journald.conf 设 `SystemMaxUse=200M`(确认单行);`systemctl restart systemd-journald` + `journalctl --vacuum-size=200M`;vacuum 后 256M,配置生效后 systemd 后续自动收敛到 200M |
| A6 | npm 缓存 | ≈1.9G | **_cacache 1.7G→0,npm 目录→243M** | `npm cache clean --force` + `npm cache verify`;npm 10.9.8 可用性验证通过 |

## 4. 保留项(硬约束,原样保留)
- 主库 backups 最近 7 天 16 份(09-23~09-30,2.9G)
- `/tmp` 全部 `*.lock`(含 trade_deploy.lock,20个)、`/tmp/migrate_126_*.log`(2个)、近 48h 内改动的文件(43个)、selfheal_review(09-24,报告未枚举,保守保留)、__pycache__/node-compile-cache/systemd-private-*/snap-private-tmp 等系统目录
- staticdata 仓 data/ 9 目录 31239 数据本体、db 3 大库、_backup_126(3.2G)、swapfile(4.1G)、.git 内容(不做 git gc)

## 5. 跳过项与原因
| 项 | 状态 | 原因 |
|---|---|---|
| 3 个小 json .bak(主库+镜像各3:board_etf_map.json.bak-lof-20260915-151804/signal_kelly_etf_freeze.json.bak-refreeze-20260918/sw_components.json.bak-29ind-20260915,共约 13M) | **保留,标注** | 诊断报告 §3.1 只枚举 3 个大 db .bak 为本授权项,未枚举小 json .bak;按任务「报告没写清路径的项→不凭猜删,核实不了就跳过并标注」原则保留,待主控/用户确认后可再删 |
| /tmp/selfheal_review(129KB,09-24) | **保留,标注** | 诊断报告 A3 未明确枚举该目录;保守处理,重启即清 |
| _backup_126_staticdata_before_migrate(3.2G) | 跳过 | 用户拍板档 B2,需 #126 迁移收口验证通过后由主控另行授权 |
| swapfile 4.1G→1G(≈3.0G) | 跳过 | 拍板档 B1,swapoff 重建有短暂内存压力窗口,未授权 |
| git gc(.git garbage 580M+455M+tmp_pack 340M≈1.3G) | 跳过 | 硬约束「不碰 .git/不做 git gc」,另一 agent 任务 |
| 镜像 trade-data/data/logs(97M/2088文件) | 跳过 | 拍板档 A6 项建议,本次授权清单未含,留待后续 |

## 6. 过程硬约束自检
- ✅ 只删 6 类白名单对象,未对任何未枚举目录 `rm -rf`(probe 4 目录均在报告 A3 明确枚举范围内)
- ✅ 未碰 public_fund.db(三仓)/staticdata data 9 目录/任何 .git 内容/内核/系统包/源码
- ✅ 未 kill 进程;删除前 lsof 确认 backups/.bak/tmp-root 文件无进程占用
- ✅ 删除后 `cd trade-data-signal && git status --porcelain` 为空=未删到 tracked 文件
- ✅ 核心 DB 存在性复核:public_fund.db 2.66G / etf_national_team.db 254M / sentiment.db 133M 均在,staticdata data 本体完好
- ✅ 未 add/commit/checkout/branch/push git
- ✅ sudo 可用(apt/journald 正常执行,未跳过)

## 7. 复现段(全部可重跑,ssh -i ~/tdsignal.pem ubuntu@122.51.111.173)
```bash
# A1 主库 backups >7天
find /home/ubuntu/code/trade-data-signal/data/backups -maxdepth 1 -name "*_*.db" -mtime +7 -exec du -cb {} + | tail -1   # 4001923072B
find /home/ubuntu/code/trade-data-signal/data/backups -maxdepth 1 -name "*_*.db" -mtime +7 -delete
ls /home/ubuntu/code/trade-data-signal/data/backups | wc -l   # 16(保留09-23~09-30)
du -shx /home/ubuntu/code/trade-data-signal/data/backups    # 2.9G

# A2 历史 .bak 双副本(主库+镜像各3大db)
rm -f <主库|镜像>/data/etf_national_team.db.bak-accumnav-20260916 \
      <主库|镜像>/data/etf_national_team.db.bak-lof-20260915-144248 \
      <主库|镜像>/data/sentiment.db.bak-spikefix-20260915_101316

# A3 /tmp(先列清单核对,再删)
find /tmp -maxdepth 1 -type f ! -newermt "2026-09-28 23:27" | grep -vE "\.lock$|migrate_126_" | xargs stat -c %s | awk '{s+=$1}END{print s}'   # 528874356B
rm -rf /tmp/kelly_trades_probe_parts /tmp/kelly_trades_sdc_probe_parts /tmp/tr_verify_ndo_parts /tmp/tr_verify_sdc_parts
cat <清单> | xargs rm -f
sudo rm -f /tmp/tmp.ogOMTbe3I1 /tmp/bak-trade-*.service /tmp/{cpuidle_support,disable_rt_runtime_share,fundnav_probe,net_affinity,nv_gpu_conf,setRps,set_xps,sgdaemon,tlinux_xps,virtio_blk_affinity}.log
du -sh /tmp   # 15M

# A4 apt
sudo apt-get clean && du -sh /var/cache/apt   # 28K

# A5 journald
sudo sed -i "s/^#SystemMaxUse=.*/SystemMaxUse=200M/" /etc/systemd/journald.conf
sudo systemctl restart systemd-journald && sudo journalctl --vacuum-size=200M
journalctl --disk-usage   # 256M(配置生效后收敛到200M)

# A6 npm
npm cache clean --force && npm cache verify && npm --version   # 10.9.8
du -sh /home/ubuntu/.npm   # 243M

# 收尾校验
cd /home/ubuntu/code/trade-data-signal && git status --porcelain   # 空
df -h /   # 45G/13G/79%
```
