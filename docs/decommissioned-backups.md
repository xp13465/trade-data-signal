# 退役归档清单:本地杂物清理 + R2 归档通路(decommissioned-backups.md)

> 2026-09-03 一次性收尾:本地 data/ 大件/historical .bak 清理,数据本体进 R2 私有桶
> `signal-backup` 的 `decommissioned/` 前缀长期留存,git 只留本 manifest + 恢复脚本,
> 大文件不进 git 本体。
> 相关脚本:`scripts/upload_r2.py`(上传,活脚本被生产/手动引用)/
> `scripts/restore-r2-backup.sh`(一键恢复)。

---

## 一、归档明细

| 原文件路径(清理前) | R2 key(signal-backup/decommissioned/) | 上传日期 | 原始体积 | 内容说明(为什么留) |
| --- | --- | --- | --- | --- |
| `data/etf_national_team.db.bak-backfill-20260728-232308` | `etf_national_team.db.bak-backfill-20260728-232308.gz` | 2026-09-03 | 38,793,216 B (~37MB),gzip 后 10,968,910 B | 2026-07-28 ETF 国家队库按 db.bak 备份(backfill 前快照),历史快照还原用 |
| `data/` 下 4 个 .bak(见下表明细) | `decommissioned-small-baks-20260903.tar.gz` | 2026-09-03 | 4 文件合计 42,807 B,tar.gz 后 11,259 B | 历史 .bak 打包归档(alert 状态/日报/新闻 digest 旧版快照) |

### tar.gz 包内明细(4 个小 .bak)

| 包内文件 | 原始体积 | 内容说明 |
| --- | --- | --- |
| `alert_state.json.bak-68c51a59-20260804-234731` | 2,222 B | 2026-08-04 alert 状态快照(告警去重状态旧版) |
| `alert_state.json.bak-fix-20260814-191445` | 13,331 B | 2026-08-14 alert 状态修复版快照 |
| `daily_brief.json.bak-20260814-legacy` | 4,432 B | 2026-08-14 前 legacy 日报格式备份 |
| `news_digest.json.bak-rewash-html-20260816-161103` | 22,822 B | 2026-08-16 新闻 digest HTML 重洗后备份 |

### 无备份直接删(0 字节空文件 + 空目录)

| 路径 | 体积 | 说明 |
| --- | --- | --- |
| `data/board_concept.db` | 0 B | sqlite 空文件,无内容不备份 |
| `data/fund.db` | 0 B | sqlite 空文件,无内容不备份 |
| `data/.tickertmp/bn_headers.txt` | 0 B | 分时采集临时文件,运行期自建 |
| `data/.tickertmp/cc_headers.txt` | 0 B | 分时采集临时文件,运行期自建 |
| `docs/_test` | — | 空测试目录,无内容 |

> 备注:`data/.tickertmp/` 为运行期临时目录,清理后由采集脚本自动重建,不影响功能。

---

## 二、恢复

从 R2 私有桶 `signal-backup` 的 `decommissioned/` 前缀一键还原(本地清理前的原文件名):

```bash
cd /Users/linhuichen/code/trade
# 单文件 db(37M 那个 → 还原 data/etf_national_team.db.bak-backfill-20260728-232308)
bash scripts/restore-r2-backup.sh etf_national_team.db.bak-backfill-20260728-232308.gz

# tar.gz 包 → 先还原成 .tar,再解包出 4 个 .bak
bash scripts/restore-r2-backup.sh decommissioned-small-baks-20260903.tar.gz
tar -xf data/decommissioned-small-baks-20260903.tar -C data
```

**手动 gunzip 恢复**(不经脚本,纯 s3 拉取 + 解压):

```bash
# 需要 R2 凭证,走 upload_r2.py 的 list 查 key 后手动 GET(或直接复用上脚本)
python3 scripts/upload_r2.py list decommissioned/ signal-backup   # 查现有归档 key
# 下载可用 restore-r2-backup.sh(curl/s3_request 均可),再 gunzip:
#   gunzip <下载文件全路径>
```

---

## 三、复现

- **generated**:2026-09-03(北京时间)(R2 上传时刻 11:35Z / 11:37Z,可经 `list` 反查)
- **用到的命令**(上传时的原始命令,原样可重跑):

```bash
# ① 37M etf db 归档(gzip 压缩上传,key 带日期可反查)
python3 scripts/upload_r2.py upload-decommissioned data/etf_national_team.db.bak-backfill-20260728-232308 etf_national_team.db.bak-backfill-20260728-232308.gz

# ② 4 个小 .bak 打 tar.gz 归档
tar -czf /tmp/decommissioned-small-baks-20260903.tar.gz -C data alert_state.json.bak-68c51a59-20260804-234731 alert_state.json.bak-fix-20260814-191445 daily_brief.json.bak-20260814-legacy news_digest.json.bak-rewash-html-20260816-161103
python3 scripts/upload_r2.py upload-decommissioned /tmp/decommissioned-small-baks-20260903.tar.gz decommissioned-small-baks-20260903.tar.gz
rm -f /tmp/decommissioned-small-baks-20260903.tar.gz   # 临时包装完即删,R2 是权威

# ③ 验证列表
python3 scripts/upload_r2.py list decommissioned/ signal-backup
```

- **输入依赖**:`data/etf_national_team.db.bak-backfill-20260728-232308`(已清理,重建需从 R2 还原)/
  `data/` 下 4 个 .bak(已清理,同上)/ R2 凭证 `.env`(`R2_BACKUP_BUCKET` 默认 `signal-backup`)
- **关键口径一句话**:`upload-r2` 双子模式——`<local>` 以 `.gz`/`.tar.gz` 结尾视为已压缩直传(不再二次 gzip),否则 gzip 压缩上传;R2 key 一律 `decommissioned/` 前缀(独立前缀,不受 `_prune_r2_backup` 的 backup//weekly//monthly 滚动清理影响,长期留存)
- **上游 `scripts/upload_r2.py` 是活脚本**(生产/手动引用,不只 manifest 调它,故不加副本);`scripts/restore-r2-backup.sh` 是恢复入口,与本文档同步维护