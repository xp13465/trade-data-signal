# 大 JSON 守卫下沉单一源 + 第二个提交入口补守卫(feat/large-json-guard-sync, 2026-09-26)

## 一、背景与两个缺口

staticdata 备份 git 仓库有两个 commit 入口:
- ① `scripts/staticdata_backup_async.sh`(deploy 后触发,**有**守卫)
- ② `scripts/staticdata_sync.sh`(intraday 每 ~30min / fetch-news ~45min / daily-brief 每天,**无**守卫)

今天实测两端 staticdata 磁盘 >20MB 文件 9 个、全部 untracked+ignored、待提交 0 条,暴露面为 0,
但根因未消:
- **缺口 A**:已跟踪文件涨过 20MB(那 8 个迁移文件**全部**是这么来的)→ `.gitignore` 对**已跟踪**
  文件无效 → async 有守卫会跳过,而 sync 会 `git add -A` → commit → push **全程静默**。
- **缺口 B**:`large_json_excludes.py` default_mode 的 `desired = set(tracked) | set(existing)`,
  **不收未跟踪新文件** → 新 >20MB 文件被 `git add -A` 暂存后,`.gitignore` 移除不掉已暂存项 →
  一直挂待提交区,sync 下一轮就提交了。

## 二、改动清单(5 项,3 文件)

| 文件 | 改动 |
|---|---|
| `scripts/large_json_excludes.py` | ① default_mode 的 desired 加第三项:磁盘 data/ 下未跟踪且未被 ignore 的 >THRESHOLD 文件(`git ls-files --others --exclude-standard -- data/`);同时把 async 写死的两个积压阈值下沉为单一源 `BACKLOG_FILE_COUNT=5000` / `BACKLOG_BYTES_THRESHOLD=500_000_000`。② 新增 `--check-staged` 模式(rc 0=干净 1=超阈值 2=内部错误),判定口径与 async 原内联守卫逐项一致,输出一行 `文件数=N 字节=B 超阈值=0|1 原因=<空|backlog|largejson>`,只读不写 |
| `scripts/staticdata_sync.sh` | ③ commit 前三段式:先刷 .gitignore 受管区块(必须在 git add 前)→ `git add -A` 判退出码(原 `\|\| true` 静默吞失败,改 async C-2 同款)→ `--check-staged`(rc=1 跳过 commit/push + notify 告警 dedup-key `staticdata_sync_oversize_skip` 6h;rc=2 置 SYNC_FAIL 继续 commit);退出码仍恒 0;NONBLOCK 路径未动 |
| `scripts/staticdata_backup_async.sh` | ④ 原内联守卫(L201-232 逐文件 wc 循环)改调 `--check-staged`,心跳 `_N`/`_BYTES` 从守卫输出解析、判定期限外为 0 不留空;⑤ 三处 `"${_NOTIFY_DRY[@]}"` 改 `"${_NOTIFY_DRY[@]+"${_NOTIFY_DRY[@]}"}"` 修 mac bash 3.2 + set -u 下空数组 unbound → 三处 notify 静默丢失 bug |

## 三、守卫判定口径(before/after 逐项等价)

| 判定项 | 改前(内联) | 改后(--check-staged) | 等价 |
|---|---|---|---|
| 清单来源 | `git diff --cached --name-only --diff-filter=d` | 同 | ✓ |
| 排除已暂存删除 D | 小写 d 排除 | 同(注释标了"别改回去",对应 2026-09-26 P1 自锁修复) | ✓ |
| 文件数 >5000 | `_N>5000` → oversize, reason=backlog(短路跳过 wc) | `n>BACKLOG_FILE_COUNT(5000)` → 同 | ✓ |
| 单文件 >20MB | `_sz>_LJE_THRESHOLD` → reason=largejson | `sz>THRESHOLD(20e6)` → 同 | ✓ |
| 变更总字节 >500MB | `_BYTES>500000000` → reason=backlog(未置 largejson 时) | `total_bytes>BACKLOG_BYTES_THRESHOLD` → 同 | ✓ |
| 原因优先级 | 文件数→backlog;largejson 优先于总字节 backlog | 同 | ✓ |
| 跳过 commit 分支 | `_OVERSIZE=1` → severe notify + 仅磁盘留档 | rc=1 → 同分支 | ✓ |
| 判定脚本异常 | THRESHOLD import 失败 → STATICDATA_FAIL=1,守卫失效但继续 commit | rc=2 → STATICDATA_FAIL=1,继续 commit | ✓ |
| 心跳 `_N`/`_BYTES` | 计算值 | 从守卫输出解析(值一致);rc=2 兜底另算 | ✓ |
| `[变更量]` 日志行 | `文件数=N 字节=B 超阈值=0/1 原因=...` | 同信息量(原因空显示 `原因=`) | ✓ |

差异注记:改后日志原因为空时显示 `原因=`(任务口径"空"),原为 `原因=无`,信息量等价。

## 四、性能实测(③ 新增段落的耗时,生产 staticdata 仓库读组件)

| 组件 | 实测 | 说明 |
|---|---|---|
| `git ls-files` 全仓 | **0.020s** | 3.2G / 30995 文件,读 index 文件,不慢 |
| `git ls-files --others --exclude-standard -- data/` | **0.075s** | 未跟踪候选 0(p9 个大文件均已 ignore) |
| stat 全仓 data/ tracked | **0.128s** | >20MB tracked = 0(迁移完成) |
| `git diff --cached --name-only --diff-filter=d` | **0.015s** | 待提交 0 |

**结论:sync 每次(含 intraday 每 ~30min)新增守卫总耗时 ≈ 0.25s,远低于 2s 门槛,无需优化。**
"3.2G/32k 文件逐个 stat"的担心不成立——`git ls-files` 只读 index 文件,untracked 扫描限定 `data/`。
留优化建议兜底:若未来 data/ 目录文件数爆炸,可给大文件清单缓存 md5 于仓库外(如 /tmp)避免重复 ls-files,
但当前 hot path 不需。

## 五、自验命令(复现段)

```bash
# ① D 自锁回归:已提交 >20MB 文件被 git rm --cached(磁盘仍在)→ --check-staged 必须 rc=0
git reset -q --hard HEAD && git add data/big.json && git commit -qm add
git rm --cached -q data/big.json
STATICDATA_REPO=/tmp/xxx python3 scripts/large_json_excludes.py --check-staged; echo rc=$?   # rc=0

# ② 单文件 >20MB 未迁移已暂存 → rc=1 原因=largejson
dd if=/dev/zero of=data/big.json bs=1024 count=21000 && git add data/big.json
STATICDATA_REPO=/tmp/xxx python3 scripts/large_json_excludes.py --check-staged; echo rc=$?   # rc=1

# ③ 新未跟踪 >20MB → 进 .gitignore 区块,add -A 后不在暂存清单(缺口 B 闭环)
dd if=/dev/zero of=data/huge_new.json bs=1024 count=21000
python3 scripts/large_json_excludes.py --repo /tmp/xxx          # 区块应含 /data/huge_new.json
git add -A && git diff --cached --name-only                      # 不得含 huge_new.json

# ④ 文件数>5000 → rc=1 原因=backlog;总字节>500MB → rc=1 原因=backlog(见报告正文)
# ⑤ _NOTIFY_DRY 空/非空 bash3.2 两情形:见 /tmp/test_notify_dry_idiom.sh
# ⑥ check_large_json_excluded.py 不回归:
python3 scripts/check_large_json_excluded.py                              # 本机 rc=0
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cd /home/ubuntu/code/trade-data-signal && .venv/bin/python scripts/check_large_json_excluded.py --staticdata-repo /home/ubuntu/code/trade-data-signal-staticdata'  # 云上 rc=0

# ⑦ sync/async 集成(不写生产,临时仓三件套:/tmp/ljgsync-app + bare origin + staticdata 克隆):
#   - sync 无大文件 → 正常 commit+push
#   - sync 已跟踪文件涨>20MB → 跳过 commit + 告警 + exit 恒 0
#   - async clean → commit + 心跳 files/bytes 有值
#   - async oversize → 跳过 commit + 心跳 skip_oversize + severe notify
```

## 六、遗留事项(需主控/用户拍板)

1. **R2 测试误传对象**:async 集成测试跑 step3.5b(`upload_r2.py upload-large-json`)时,把
   20MB 零文件 `small.json` 传到了**真实**私有桶 `signal-backup/large-json/2026-09-26/small.json.gz`
   (gzip 后约 0B,内容为零字节,无数据泄漏)。删除命令被 auto 分类器拦(生产桶删除需用户确认)。
   建议:用户确认后 `python scripts/upload_r2.py delete "large-json/2026-09-26/small.json.gz" signal-backup`;
   不删也可,日档 14 天后自动过期,但保留会占 2026-09-26 一日档位。
2. 测试期 async 重写过 `docs/large-json-backup-manifest.md`,已 `git checkout --` 还原,工作区干净。