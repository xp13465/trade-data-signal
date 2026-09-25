# 大 JSON 移出 staticdata 备份 git + 走 R2 私有桶备份(2026-09-25)

> feat 分支: `feat/large-json-r2-core`。§23.5 四件套: 本报告本体 + 生成/配套脚本(见「改了什么」) + 复现段(见「怎么复现」) + 配套 commit(feat 分支全部改动)。

## 1. 背景(已取证)

- 云上 9-25 18:13 staticdata 异步备份首跑结果: `skip_oversize`,45 文件 / 357,535,930 字节,
  撞了「变更文件总字节 >300MB」阈值,跳过 commit 只做磁盘留档 + 发 severe 告警。
- 原因是 staticdata 备份仓库(`trade-data-signal-staticdata`,远端 `git@github.com:xp13465/trade-data-signal-staticdata.git`)
  跟踪着 **7 个 >20MB 的 JSON(共 ~320MB)**,天天变、天天进 delta;仓库 `.git` 已 3.3G,
  worktree 8G(data/ 2.1G),`.gitignore` 已被它自己跟踪,备份脚本 `git add -A`。
- 实时口径(本任务实施时扫描,与 9-25 首跑略有差异——accum_nav_map.json 当前 19.4MB<20MB 不在清单,
  trade_sim/trade_sim_cgb_idx_full.json 20.19MB 进入清单):
  | 路径(相对仓库根) | 完整字节 |
  |---|---|
  | data/signal_kelly_trades_sdc.json | 78,351,370 |
  | data/signal_kelly_trades.json | 78,296,778 |
  | data/offshore_fund_performance.json | 40,531,280 |
  | data/offshore_fund_purchase_status.json | 34,272,288 |
  | data/offshore_fund_risk_indicator.json | 22,394,747 |
  | data/offshore_fund_fee_detail.json | 21,713,076 |
  | data/trade_sim/trade_sim_cgb_idx_full.json | 20,187,149 |
- ⚠ 20MB 阈值是**实时判定**(按磁盘当前大小),不硬编码 7 个:**accum_nav_map.json 在 20MB 阈值上下浮动**——9-25 首跑 26.2MB(任务背景),实施时 18.5MB,复制进 /tmp 克隆的 git 版本 26MB(2026-09-22 快照)。async 实测在 /tmp 克隆上它重新跨界被自动纳入第 8 项并上传(见 §5 复现 async 输出),证明动态清单正确处理阈值跨界文件,无需改代码。

## 2. 冻结接口(主控定,实施不改)

- `THRESHOLD = 20_000_000` 字节(20MB)。口径 = **文件完整大小**,不是 diff 大小。
- 排除对象 = staticdata 备份仓库里 `data/` 下 **>THRESHOLD 且被 git 跟踪**的文件。
- R2 私有桶 = `signal-backup`(`upload_r2.BACKUP_BUCKET`),新前缀 `large-json/`。
- key 格式 = `large-json/<YYYY-MM-DD>/<相对 data/ 的路径>.gz`
  - 例: `data/signal_kelly_trades.json` → `large-json/2026-09-25/signal_kelly_trades.json.gz`
  - 例: `data/signal_kelly_trades_parts/t2025.json` → `large-json/2026-09-25/signal_kelly_trades_parts/t2025.json.gz`
- 保留 = 日档 14 天 + 周档(周日那份)8 周 + 月档(每月 1 号那份)12 个月。复用 `upload_r2.py` 里 DB 备份已有的滚动保留实现。
- 索引文件路径 = `docs/large-json-backup-manifest.md`,由上传脚本自动生成(不手工维护)。

## 3. 改了什么(交付物 A-F)

| # | 文件 | 改动 |
|---|---|---|
| A | `scripts/staticdata_backup_async.sh` | 积压阈值 300MB→500MB(L179 判定 + L20/L146/L183/L185 注释文案);修正 L33-36 pipefail 注释最后一句不实描述(原"其余均为 echo 纯日志管道,无误伤"→ 实为 4 处非 echo:rsync DB(L118)/rsync JSON(L136)/git add(L151,PIPESTATUS[0] 判定)/git commit(L191));新增 step3.5「大 JSON 排除 + R2 上传」(git 步骤之前,失败置 STATICDATA_FAIL=1 不阻塞后续) |
| B | `scripts/large_json_excludes.py`(新) | 排除规则单一源: 默认模式维护 staticdata `.gitignore` 受管区块(`# >>> large-json auto-generated >>>`/`# <<< ... <<<`,幂等,精确路径 `/data/...` 锚定仓库根);`--print` 输出待上传清单(相对 data/ 路径 + 字节数,tab 分隔);`--check` 机检 tracked 大文件(有则非零退出) |
| C | `scripts/upload_r2.py` | 新增子命令 `upload-large-json`(注册进 `_A_CLASS` L46 + `__main__` 分发 + 用法串): gzip 上传 `large-json/<日期>/<相对data路径>.gz`(幂等:s3_head ETag==内容 md5 跳过 PUT);`_prune_large_json` 分层滚动清理(日14天+周周日8周+月1号12月,复用 `_list_keys`/`_prune_layer` 删除模式);自动重写 `docs/large-json-backup-manifest.md` |
| D | `scripts/staticdata_backup_async.sh`(接链) | step3.5: 先 `large_json_excludes.py --repo`(区块最新),再 `upload_r2.py upload-large-json`(R2 私有桶备份),各带失败判定置 STATICDATA_FAIL=1 进心跳与严重告警 |
| E | `scripts/migrate_large_json_out_of_git.sh`(新) | 一次性迁移(幂等): 硬顺序①先上传(R2 副本齐全 + manifest 已生成)→②再 `git rm --cached -- data/<path>`(磁盘文件保留,绝不删);任一步失败中止不摘 git;结尾只打印人工 commit+push 步骤,脚本不代做;`--dry-run` 只打印不执行 |
| F | `scripts/check_large_json_excluded.py`(新) + `scripts/deploy.sh` | 机检: 包装 `large_json_excludes.py --check`,有漏网 tracked 大文件 FAIL;挂 deploy.sh 1.2.5 段(同 check_task_state/check_fade_keys 待遇,FAIL 阻断上线) |
| G | `docs/ops/large-json-out-of-git-20260925.md`(本报告) | §23.5 四件套 |

## 4. 关键设计决策(单一源 + 迁移后防断链)

- **备份对象清单权威 = .gitignore 受管区块,不是动态 tracked 扫描**。`large_json_excludes.py` 默认模式
  重写区块 = 「当前 tracked >20MB」∪「区块已有且磁盘仍存在」。理由: `git rm --cached` 只移出 git index
  (磁盘文件保留), 若备份清单只看 tracked, 迁移后清单变空 → **R2 备份断链**;区块合并保留既有项,
  迁移后仍持续每日备份, 直到文件从磁盘消失。
- **排除行用精确路径**(`/data/signal_kelly_trades.json` 前导斜杠锚定仓库根), 不用 `signal_*` 宽通配防误伤。
  实测: 磁盘 data/ 下 >20MB 的 8 个文件里, `industry-all-concepts.json`(32.5MB)被既有 `industry-*` 通配
  排除(走 R2 公开桶 industry/ 前缀分发, 不属于 large-json 私有桶备份对象)——精确路径区块天然不误伤它。
- **幂等上传**: `gzip.compress` 固定 mtime, 同内容 → 同 gzip 字节 → 同 md5; `s3_head` 比 ETag
  (单 PUT ETag=内容 md5), 内容没变跳过 PUT。
- **滚动保留复用 DB 备份分层模式**: `_list_keys` 列取 + `_prune_layer` 逐 key DELETE 同构;
  large-json 日期在 key 的目录前缀(`large-json/YYYY-MM-DD/...`), 故不能直接复用 `_prune_layer` 正则,
  写 `_prune_large_json` 按目录分层(日=最近14天整目录, 周=最近8个存在周日目录, 月=最近12个存在1号目录),
  任一目录被任一层保留 = 整目录 key 保留。

## 5. 怎么复现(测试路径,全部在 /tmp 克隆 + 测试 key,不碰生产)

### 5.1 造 /tmp 克隆仓库
```bash
rm -rf /tmp/largejson-test-staticdata
git clone --filter=blob:none --sparse --no-checkout git@github.com:xp13465/trade-data-signal-staticdata.git /tmp/largejson-test-staticdata
cd /tmp/largejson-test-staticdata && git sparse-checkout set --no-cone \
  "/.gitignore" "/data/signal_kelly_trades.json" "/data/signal_kelly_trades_sdc.json" \
  "/data/offshore_fund_performance.json" "/data/offshore_fund_purchase_status.json" \
  "/data/offshore_fund_risk_indicator.json" "/data/offshore_fund_fee_detail.json" \
  "/data/trade_sim/trade_sim_cgb_idx_full.json"
git checkout
```
> 只拉 7 个 >20MB 大文件 + .gitignore(~320MB blob), 不拉全 worktree 2.1G。

### 5.2 排除规则单一源三模式
```bash
PY=/Users/linhuichen/code/trade/.venv/bin/python
# 默认模式: 维护 .gitignore 受管区块(幂等)
$PY /Users/linhuichen/code/trade/scripts/large_json_excludes.py --repo /tmp/largejson-test-staticdata
# --print: 输出待上传清单(相对 data/ 路径 + 字节数)
$PY /Users/linhuichen/code/trade/scripts/large_json_excludes.py --print --repo /tmp/largejson-test-staticdata
# --check: 迁移前应 FAIL(7 个 tracked 大文件)
$PY /Users/linhuichen/code/trade/scripts/large_json_excludes.py --check --repo /tmp/largejson-test-staticdata; echo "exit=$?"
```

### 5.3 上传 + 迁移(私有桶测试 key `large-json/_test/` 或正式 large-json 前缀,跑完可 delete)
```bash
# 1) 上传(不摘 git): R2 私有桶 signal-backup large-json/<今天>/... + manifest
STATICDATA_REPO=/tmp/largejson-test-staticdata $PY /Users/linhuichen/code/trade/scripts/upload_r2.py upload-large-json
# 2) 确认 R2 副本: upload_r2.py list large-json/ signal-backup
$PY /Users/linhuichen/code/trade/scripts/upload_r2.py list "large-json/2026-09-25/" signal-backup
# 3) 迁移(dry-run 先看)
bash /Users/linhuichen/code/trade/scripts/migrate_large_json_out_of_git.sh --dry-run  # 需 env
STATICDATA_REPO=/tmp/largejson-test-staticdata GIT_REPO=/Users/linhuichen/code/trade \
  bash /Users/linhuichen/code/trade/scripts/migrate_large_json_out_of_git.sh
# 4) 迁移后机检: --check 应 PASS; git ls-files 无大文件; 磁盘文件仍在
$PY /Users/linhuichen/code/trade/scripts/check_large_json_excluded.py --staticdata-repo /tmp/largejson-test-staticdata; echo "exit=$?"
git -C /tmp/largejson-test-staticdata ls-files | wc -l
ls -la /tmp/largejson-test-staticdata/data/signal_kelly_trades.json   # 磁盘保留
# 5) 幂等重跑迁移: 清单空 → 提示无需迁移
STATICDATA_REPO=/tmp/largejson-test-staticdata GIT_REPO=/Users/linhuichen/code/trade \
  bash /Users/linhuichen/code/trade/scripts/migrate_large_json_out_of_git.sh
```

### 5.4 接链测试(不真发邮件/不碰生产 staticdata)
```bash
STATICDATA_REPO=/tmp/largejson-test-staticdata STATICDATA_BACKUP_NOTIFY_DRY_RUN=1 \
  bash /Users/linhuichen/code/trade/scripts/staticdata_backup_async.sh test-trigger
# 日志尾部应见 step3.5a/step3.5b; 心跳 $REPO/data/staticdata_backup_heartbeat.json 有最新 ok
```
> 实测(2026-09-25): step3.5a ✓ / step3.5b ✓ / 上传 8/8(7 个实时清单 + accum_nav_map.json 在 /tmp 克隆为 26MB
> git 版本而跨界自动纳入)——动态清单行为符合预期;测试 key 跑完已全部 `delete` 清理(large-json/ 前缀归 0)。

### 5.5 语法检查
```bash
bash -n scripts/staticdata_backup_async.sh scripts/migrate_large_json_out_of_git.sh scripts/deploy.sh
$PY -m py_compile scripts/large_json_excludes.py scripts/check_large_json_excluded.py scripts/upload_r2.py
```

## 6. 回滚办法

- 代码层: 本 feat 不 push main; 若 merge 后需回滚, 主控 `main-merge.sh` 反向 merge 或 revert
  `feat/large-json-r2-core` 的 commit(改动集中在 A/C/F: async 阈值与 step3.5、upload_r2 新命令、
  deploy.sh 1.2.5 闸门)。回滚后 deploy.sh 闸门消失, staticdata 恢复原备份方式。
- 数据层(迁移后回滚): 人工在 staticdata 仓库执行 `git add data/<path>` 把大文件重新纳入 git
  (remove 掉 .gitignore 区块内对应行或 `git add -f`), commit + push;R2 large-json/ 副本不受影响
  (可留作历史归档)。
- R2 层: 备份副本是每日 gzip 快照, 无恢复时需要直接下载:
  `upload_r2.py download` 不支持 arbitrary key, 可用 `list` + 手动 GET 或直接 s3 CLI 读。

## 7. 操作序列(merge 后必读,⚠ 顺序硬约束)

1. 本 feat 代码经内审 PASS 后, 由主控 `main-merge.sh` 合并上线(agent 只推 feat 分支)。
2. **上线后立即在本机 + 云上跑迁移脚本**(migrate_large_json_out_of_git.sh, 本机可先跑,
   云上 `${GIT_REPO}-staticdata` clone 同样处理或 `git pull` 同步远端):
   硬顺序先上传确认副本齐全, 再 rm --cached, 人工 commit + push。
3. **在下一次 deploy 前完成迁移**——否则 deploy.sh 1.2.5 闸门 check_large_json_excluded 会
   FAIL 阻断上线(这正是闸门目的: 强制迁移完成, 防 .git 继续膨胀)。
4. 之后 async 每日: step3.5 维护区块 + 上传 R2 持续备份; 若新出现 >20MB tracked 文件,
   `--check` 会 FAIL 提醒再跑一次迁移脚本。

## 复现段

- 本报告所有「改了什么」对应 commit 均在本 feat 分支 `feat/large-json-r2-core`(agent 只 commit+push feat,
  merge 由主控走 main-merge.sh)。复现本报告结论 = 按 §5 在 /tmp 克隆上跑三模式 + 上传 + 迁移 +
  机检, 全部 PASS 即复现。
- 遗留风险: 迁移脚本不代 commit/push(冻结接口要求留给人), 故迁移后 staticdata 远端 git 历史缺
  「rm --cached」档, 需人工执行 §5.3 步骤 3 的 commit+push 补上。
