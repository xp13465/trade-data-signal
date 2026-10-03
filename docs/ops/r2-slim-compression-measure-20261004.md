# R2 signal-backup 瘦身压缩率实测 + 现状修正(2026-10-04)

> 任务书(主控 2026-10-03)要求:实测 mac-backups/2026-10-01 那 10.171 GiB 的压缩率,量出「压缩后保留一份异地归档再删原件」的达标数字。
> **实测核心结论:mac-backups 已于 2026-10-02 从 R2 恢复+删除(R2 前缀已空,HEAD 404 实证),本机原件 86 文件 10.171 GiB 全量对账 86/86 PASS。任务前提已变,但用户拍板方向(压缩后异地归档+删原件)在当前现状下正确落点 = 压缩本机原件放 R2 异地归档,再删本机原件。**
> 达标数字:zstd -19 整包 **2.122 GiB**(回 10 GiB 线内但余量紧);页级去重+zstd 只需 **0.228 GiB**(终极方案)。
> 本报告全部数字可复现(§复现命令);只读调研,零删除/零上传/零修改。

## ① 现状修正(2026-10-03/04 实测,R2 上 mac-backups 已不存在)

- 10-02 已有 agent 执行完整流程(docs/ops/r2-mac-backups-restore-20261002.md):取回本机 → md5+size 对账 86/86 PASS → 逐 key 删 R2(仅此 86 个)→ 删后确认前缀空。
- 本次交叉验证(2026-10-03):List signal-backup 全量 59,770 对象 / 4.820 GiB,**无 mac-backups 前缀**;HEAD `mac-backups/2026-10-01/{etf_20260718,sentiment_20260718,etf_20260911}.db` 均 **404**。
- 本机原件核实:`~/code/trade-data/data/mac-backups-20261001/` = 86 文件 / 10,920,869,888 B = 10.171 GiB,本次重算 **md5+size 对账锚点日志 86/86 match,missing=0 mismatch=0**。
- 10-02 容量报告(r2-backup-bucket-capacity-20261002.md)发布于恢复执行前,其「17.115 GiB」现状数字已过时。

## ② 今日两桶基线(2026-10-03 实测 List 全量)

| 桶 | 对象数 | 字节 | GiB |
|---|---|---|---|
| 主站桶 signal-data | 31,476 | 3,028,738,202 | 2.821 |
| 备份桶 signal-backup | 59,770 | 5,175,923,847 | 4.820 |
| 合计 | 91,246 | 8,204,662,049 | **7.641** |

- 备份桶构成:large-json 59,362(0.820)+ pre-upload/20261003 277(0.705)+ backup 54(2.596)+ weekly 8 + monthly 8 + claude-backup 59 + decommissioned 2。
- **两桶合计 7.641 GiB 已在 10 GiB 免费线内,余量 2.359 GiB。** 免费额度无需救急;但「本机 10.171 GiB 原件是唯一副本、R2 无异地」这一状态应尽快补异地归档(本机单点故障即丢 07-18~09-11 全部历史)。

## ③ 清单盘面(86 对象构成)

- etf_national_team:44 个 .db,20260718~20260911,合计 5.565 GiB,相邻日平均增量 4.3 MB(0.7%);
- sentiment:41 个 .db + 1 个 .db-shm,20260718~20260911,合计 4.606 GiB,相邻日平均增量 1.1 MB(0.1%);
- **SQLite 页面级重复率极高(每日增量 ≤0.7%),跨文件去重是最大杠杆**。单文件压缩(backup/ 前缀 .gz ≈ 30-38% 保留率)浪费了这天量冗余。
- 部分日期在 R2 另有第二份(backup/ 09-04~09-11 30 天滚动、weekly 09-07/14/21/28、monthly 07-21/08-03/09-01),但属临时窗口,10-11 前后 backup 滚动清掉 09-04~09-11,不可依赖。
- 全部 85 个 .db 的 SQLite page_size 均 = 4096(header 实测),页级去重按 4KB 分页假设成立。

## ④ 压缩率实测(核心;整包 = 10.171 GiB / 10,920,869,888 B)

| 方案 | 压缩后字节 | GiB | 保留率 | 压缩率 | 耗时 | 两桶合计(基线 7.641+包) | 10 GiB 线 |
|---|---|---|---|---|---|---|---|
| 原始整包(现状,本机) | 10,920,869,888 | 10.171 | 100% | 0% | — | 7.641(包未上传) | 免费内但无异地 |
| gzip -9 整包 | 3,132,484,902 | **2.917** | 28.7% | 71.3% | 9:17 | 10.558 | ✗ 超 0.558 |
| **zstd -19 整包**(T4) | 2,278,227,979 | **2.122** | 20.8% | 79.2% | 22:19 | **9.763** | ✓ 余 0.237(偏紧) |
| 页级去重(唯一页集合) | 1,746,536,956 | **1.627** | 14.9% | 85.1% | ~2 分钟 | 9.268 | ✓ 余 0.732(需专用工具) |
| **页级去重 + zstd -19** | 243,010,132 | **0.228** | 2.1% | **97.9%** | ~5 分钟 | **7.869** | ✓✓ 余 2.131(需专用工具) |

- 单文件小样本(85.7MB sentiment_20260718):gzip -9 → 24.9MB(29.1% 保留)、zstd -19 → 19.1MB(22.3%)。
- 页级去重明细:etf 总页 1,458,782 → 唯一 120,133(8.2%)= 0.458 GiB;sentiment 总页 1,207,438 → 唯一 306,353(25.4%)= 1.169 GiB;合计唯一页 1.627 GiB;唯一页再 zstd -19 → etf 0.064 GiB + sentiment 0.164 GiB = **0.228 GiB**。
- **达标答案:zstd -19 整包 2.122 GiB 已能回 10 GiB 线内(合计 9.763),但余量仅 0.237 GiB**——上传压缩包时若桶内恰有当日增量(pre-upload/backup)可能擦线。**终极方案 = 页级去重+zstd 0.228 GiB,余量 2.13 GiB,推荐。**
- gzip -9 整包 2.917 GiB **不达标**(超 0.558 GiB),不可作异地归档方案。
- zstd --ultra -22 --long=31 大窗口档**运行失败(exit 144,211MB 处终止,无报错)**,未测出数字,标注 UNVERIFIED;且 zstd -19 已默认启用 --long=27(128MB 窗口),大窗口边际收益有限,不再重跑。

## ⑤ 策略对照表(每行两桶合计,基线今日实测 7.641 GiB)

| 方案 | 动作 | 两桶合计 | 10 GiB 线 | 数据安全 | 本机占用 | 实施成本 |
|---|---|---|---|---|---|---|
| S1 原样(现状) | 什么都不做 | 7.641 GiB | ✓(免费内) | ⚠️ 唯一副本在本机,R2 无异地 | 10.171 GiB | 0 |
| S2a 压缩归档 gzip -9 + 删本机 | 传 2.917 GiB 包,删本机 | 10.558 GiB | ✗ | ✓ 异地可恢复 | 0 | 低 | 
| **S2b 压缩归档 zstd -19 + 删本机** | 传 2.122 GiB 包,删本机 | **9.763 GiB** | ✓(余 0.237) | ✓ 异地可恢复 | 0 | 低(一行命令) |
| **S2c 页级去重+zstd + 删本机** | 传 0.228 GiB 包,删本机 | **7.869 GiB** | ✓✓(余 2.131) | ✓ 异地可恢复 | 0 | 中(需专用工具) |
| S3a 每库只留最新,不压缩 | 保留 2 文件 0.295 GiB,删 84 | 7.936 GiB | ✓ | ✗ 丢 84 份历史 | ≈0.295 GiB | 低 |
| S3b 每库留最新+gzip | 保留 2 文件压缩 ~0.1 GiB | ~7.74 GiB | ✓ | ✗ 丢历史 | ≈0.1 GiB | 低 |

- **推荐 S2c(页级去重+zstd,终极完整)**,若不想写专用工具则 S2b(zstd -19 整包,一行命令、达标但余量紧)。
- S3 丢 84 份历史快照,除非确认无回滚需求,不作为主推。

## ⑥ 执行步骤草案(只出草案,本报告未执行;实施 agent 可照此落地)

### S2b(zstd -19 整包,最简单)
1. 生成 manifest:`mac-backups-manifest.txt`(86 行 key|size|md5,取自锚点日志),打进包内并记录包 SHA256 —— 解压后对账不依赖 /tmp 日志。
2. 打包(流程本次已实测):`zstd -19 -T4 -c <源目录> > mac-backups-2026-10-01.tar.zst`(源含 manifest)。
3. 上传 R2:PUT `signal-backup/mac-backups/archive/mac-backups-2026-10-01.tar.zst`(>100MB 走 upload_r2 multipart)。
4. 回读验证(唯一删除前提):GET 该包 → `zstd -d` 解压 → 86 文件与锚点日志**逐文件 md5+size 对账 86/86 PASS**;并交叉 `tar -tf` 成员数 == 86(+manifest)。
5. 删本机原件:`rm -rf ~/code/trade-data/data/mac-backups-20261001/`(PASS 后)。
6. 回退:GET 包 → zstd -d → 恢复 86 文件,一键可逆。

### S2c(页级去重+zstd,终极;需专用工具,本次已实测其下限数字)
1. 分页去重工具(新增 scripts/ 下):对每个 .db 按 4096B 分页(SQLite page_size 已验证 4096)→ sha256 去重 → 存「唯一页 bin」+「per-file 页索引」(每页 4B uint32,86 文件 × 约 15 万页 × 4B ≈ **12 MB**,可忽略)。
2. 唯一页 bin 分库(etf / sentiment)以 zstd -19 压缩;索引 + manifest + 解压重建脚本同包上传 R2。
3. 回读验证:GET 包 → 重建 86 文件 → 逐文件 md5+size 对账锚点日志 86/86 PASS。
4. 重建逻辑:per-file 页索引 → 从唯一页 bin 对应页位取回按序写文件,即逐位还原(唯一页集 + 页序列索引完整,重建=原文件)。
5. 删本机原件 + 回退同 S2b。

**对账口径**:86/86 逐文件 md5+size 全比对(非抽样),锚点 = /tmp/mac_backups_upload_log_20261001.txt(10-01 上传时本地 md5)。服务端侧可加 HEAD 校验包长度;分片上传的 ETag 非 md5,以回读对账为准。

## ⑦ 成本标注(本次调研,2026-10-03/04)

- **Class A**(ListObjectsV2,$4.50/百万,免费 100 万/月):主桶 32 + 备份桶全量 60 + mac-backups prefix×2 + pre-upload×1 + backup/weekly/monthly/decommissioned×4 = **99 次 ≈ $0.00045**。
- **Class B**(HEAD,免费 1000 万/月):5 次(mac-backups 3 次 404 + backup 前缀 2 次 200),可忽略。
- **GET/PUT:0 次**(本机原件就地压缩,未下载/未上传——比任务书预想省掉全部 GET,R2 侧已无对象)。
- 均在当月免费额度内,零账单影响。

## ⑧ 诚实标注

1. 任务书背景「mac-backups 10.171 GiB 在 R2」已过时(10-02 恢复+删除),本报告以今日实测 7.641 GiB 为基线。
2. **zstd --ultra -22 --long=31 未测出数字(exit 144 终止),标注 UNVERIFIED**;zstd -19 已默认 long=27,预期大窗口提升有限,不以 0.8-1.3 GiB 预期入表,实际数字如下表所示。
3. 页级去重 0.228 GiB 为「唯一页集合」内容大小;工程落地需额外 per-file 页索引(~12MB)与重建脚本,合计包体 ~0.25 GiB,不影响达标结论。页级去重按「内容层下界」诚实标注:它证明 10.171 GiB 的真实内容远小于整包压缩,但需要专用工具实现(非 gzip/zstd 命令行可得)。
4. 页级去重统计按 4096B 分页,85/85 .db header 实测 page_size=4096,假设成立;短尾页(文件尾 <4096B)按实读处理,影响可忽略。
5. backup/ 前缀 09-04~09-11 第二份为 30 天滚动窗口,10-11 前后自动清除,勿依赖。
6. 本次只读,未执行任何删除/上传/修改;S2/S3 均待用户拍板后由实施 agent 执行。

## 复现命令(全部原始输出落 /tmp)

```bash
# ① List 备份桶全量(60 calls): 确认无 mac-backups 前缀, 当前 4.820 GiB
/Users/linhuichen/code/trade/.venv/bin/python docs/scripts/r2_bucket_stats.py --bucket signal-backup
# ② HEAD 交叉验证 mac-backups key = 404: /tmp/r2slim_head.py
# ③ 本机原件全量对账 86/86(md5+size vs 锚点日志): /tmp/r2slim_verify.py
# ④ 打包 + 压缩: /tmp/mac_backups_20261001_raw.tar(10,920,969,896 B 源)
tar -cf /tmp/mac_backups_20261001_raw.tar -C /Users/linhuichen/code/trade-data/data mac-backups-20261001
time gzip -9 -c /tmp/mac_backups_20261001_raw.tar > /tmp/mac_backups_20261001.tar.gz      # 3,132,484,902 B / 9:17
time zstd -19 -T4 -c /tmp/mac_backups_20261001_raw.tar > /tmp/mac_backups_20261001.tar.zst # 2,278,227,979 B / 22:19
# (zstd --ultra -22 --long=31 运行 exit 144 失败, 无数字)
# ⑤ 页级去重统计 + 唯一页 zstd: /tmp/r2slim_pagededup.py → etf 120,133 页 / sentiment 306,353 页
#    唯一页 zstd: etf 68,282,496 B / sentiment 175,727,636 B = 合计 243,010,132 B
# ⑥ 基线: docs/scripts/r2_bucket_stats.py --bucket signal-data → 2.821 GiB
```

## 参考
- docs/ops/r2-backup-bucket-capacity-20261002.md(背景,现状数字已过时)
- docs/ops/r2-mac-backups-restore-20261002.md(10-02 恢复+删除执行)
- docs/ops/holiday-window-housekeeping-execution-20261001.md(10-01 家清上传)
- 本机原件:`~/code/trade-data/data/mac-backups-20261001/`(86 文件 10.171 GiB)
- 锚点日志:`/tmp/mac_backups_upload_log_20261001.txt`
