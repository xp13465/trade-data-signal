# R2 上传 REPO 缺省回退闸 · 调研与方案（2026-08-22）

> 任务：upload_r2.py 加闸拦「不带 REPO 手动跑」，但不打断现有定时链；区分「design 合法回退」与「真踩雷」；给回归点。
> 结论先行：**21 个命令分 4 类，C 类 11 个数据上传命令在 REPO 缺省时拒绝（exit 3），B 类 3 个 lab/trade_sim 白名单放行，D 类 purge-low-freq 警告放行，A 类 6 个与 REPO 无关直接放行；配套 7 个 shell 脚本补 `export REPO GIT_REPO`（对齐 intraday_snapshot.sh/gold_night.sh 先例）。**

## 1. 根因（一行）

`scripts/upload_r2.py`：
- **L28** `ROOT = Path(__file__).resolve().parent.parent` —— `.resolve()` 解析符号链接，而 `trade-data/scripts -> trade/scripts` 是 symlink（实测 `ls -la /Users/linhuichen/code/trade-data/`），所以 **ROOT 恒等于 trade**，无论从哪边路径调用；
- **L33** `STATIC_DIR = Path(os.environ.get("REPO", str(ROOT))) / "static-site"` —— 只有环境里**真的有 REPO** 才读 trade-data 侧；
- 终端手动裸跑 `python scripts/upload_r2.py upload-intraday` 时 REPO 不在 env → STATIC_DIR 回退 `trade/static-site`（旧库快照）→ 把旧数据盖到 R2 线上。

对照：`gen_schedule_stats.py L29` 用的是 `Path(__file__).parent.parent`（absolute 不解析 symlink）+ 显式注释"不用 .resolve()"——项目里已有正确先例，upload_r2.py 的 resolve() 是偏差源。

## 2. 命令分类总表（dispatch 全部 21 个分支，L478 起）

| 类 | 命令 | 是否依赖 STATIC_DIR/REPO | 缺省 REPO 时处置 |
|---|---|---|---|
| A 与 REPO 无关（6） | `list` / `upload <local> <key>` / `upload-claude-backup` / `download-db` / `delete` / `clean-data-backup` | 否（读显式路径或私有桶固定 key） | 放行 |
| B design 合法回退（3） | `upload-lab` / `upload-trade-sim` / `upload-trade-sim-json` | 是，但生成器按 `__file__` 写 trade 树，trade-data 侧天然缺/滞后 | 放行 + stderr 提示（白名单） |
| C 数据上传高危（11） | `upload-index` / `upload-industry` / `upload-public-fund` / `upload-offshore-fund` / `upload-fund-score` / `upload-etf-score` / `upload-data-large` / `upload-all-data` / `upload-intraday` / `upload-data-files` / `upload-db` | 是 | **exit 3 拒绝 + 打印正确跑法** |
| D 扫描类（1） | `purge-low-freq` | 只扫 STATIC_DIR/data 算 purge 集，不上传内容 | 警告放行 |

B 类合法回退证据：`upload_r2.py` 约 L255-258（cmd_upload_lab exists() 回退）、L440-445（trade_sim HTML）、L466-468（trade_sim JSON）；`update_lab.sh L243-262` rsync trade-data→trade 补偿注释原文："upload_r2.py 的 ROOT 用 Path.resolve() 解析符号链接到 trade/……rsync 同步确保 upload_r2 读到最新数据"。

## 3. 调用方清单与 REPO 状态矩阵

**launchd 环境（全绿，不受闸影响）**：全部 com.trade.* plist 均注入 `REPO=/Users/linhuichen/code/trade-data`（实测 PlistBuddy 打印 com.trade.update-all EnvironmentVariables：REPO/GIT_REPO/PURGE_SECRET/PATH 四项齐全；gold-night/lab-auto/pf-score-daily/pf-score-weekly 同）。env 经 bash 链继承到所有子孙进程。

| # | 调用方 | 触发的命令 | REPO 保障 | 手动裸跑危害 |
|---|---|---|---|---|
| 1 | intraday_snapshot.sh（盘中哨兵） | upload-index / upload-intraday / upload-data-files(schedule_stats) | plist 注入 + 脚本 L25-28 **自 export**（双保险） | 有闸后被拒=修复目标 |
| 2 | gold_night.sh（夜间） | upload-data-large / global-* | plist + L20-22 **自 export** | 同上 |
| 3 | update_all.sh（17:50） | upload-etf-score / offshore-fund / fund-score + deploy all | 仅 plist 注入（**不 export**） | 无害：L147/L169/L181 三命令前各有 `rsync $REPO/.../etf_score_list_* 等 → trade/static-site/data/` 补偿，读 trade 侧内容一致 |
| 4 | deploy.sh（update_all O1 L104 / pipeline.sh L71 / etf_national_team_backfill L95 / lhb_backfill L105 / futures_backfill L95 / public_fund_{quarterly,daily,full}.sh / 主控 merge 后手动） | run_r2_upload ×11 + purge-low-freq | 仅 plist 链注入（**不 export**） | 无害：L241-249 先全量 `rsync -a --checksum $REPO/static-site/data/ → $GIT_REPO/static-site/data/` 再上传 |
| 5 | **push_schedule_stats.sh** | upload-data-files(schedule_stats.json) | 仅上游链注入（**不 export**） | **真实危害**：L44 `SRC="$REPO/static-site/data/schedule_stats.json"` 校验 trade-data 侧存在性，但子进程无 REPO 实际上传 trade 侧旧 stats（gen_schedule_stats.py L31 只写 `$REPO/static-site/data/`，无任何 rsync 补偿） |
| 6 | **backup_db.sh** | upload-db | **不 export** | **真实危害**：cmd_upload_db 内部 `repo=os.environ.get("REPO", ROOT)` → 备份 trade/data 旧库副本进私有桶（恢复演练会拿到旧库；非线上覆盖，中低危） |
| 7 | update_lab.sh（lab-auto） | upload-lab / trade-sim-json / lab_*.json | 仅 plist 注入 | 无害：launchd 下走 B 类 design 回退；手动裸跑 L247-262 rsync 补偿 |
| 8 | pf_score_daily.sh / pf_score_weekly.sh（16:00/周日） | upload-fund-score | 硬编码赋值**不 export** | 无害：上传前有 `rsync fund_score* → trade` 补偿 |
| 9 | verify_backup.sh | download-db（只读下载） | 无关 | 无 |
| 10 | backup_claude_self.sh | upload-claude-backup（显式路径） | 无关 | 无 |
| 11 | overfit_monitor.py（独立打点） | upload-data-large 子进程 | **force_env 强制覆盖**（L1393-1399，注释点名此陷阱） | 无 |
| 12 | fetch_news.py | upload-data-files(news_digest…) | force_env（L706-708） | 无 |
| 13 | gen_daily_brief.py | upload-data-files(daily_brief*) | force_env（L2860-2872） | 无 |
| 14 | static-site/export.py 末尾自动 R2 | ×7 命令 | 显式 `env={**os.environ,"REPO":str(ROOT)}`（L1232-1234）；ROOT=`Path(__file__).absolute().parent.parent` 不解 symlink → 写哪边上哪传，自洽 | 无 |
| 15 | app/collector/intraday_snapshot.py L1947-1960 | `upload <local> <key>` 显式本地路径 | A 类无关 | 无 |

**不带 REPO 高危调用方计数**：shell 脚本层不 export REPO 共 **7 个**（update_all/deploy/backup_db/push_schedule_stats/update_lab/pf_score_daily/pf_score_weekly），其中 **5 个有 rsync 补偿无害化**，**2 个真实危害**（push_schedule_stats.sh、backup_db.sh）；另加「任意单命令终端直调」这一裸跑形态（upload-intraday 盘后/upload-index/upload-all-data 单独直调均无补偿）。main-merge.sh 不调 deploy（仅 build_min/bump/check_version_progress，grep 证实）；self-heal plist 只跑 self_heal.sh 不碰 deploy。

## 4. 方案对比（含否决理由）

| 方案 | 内容 | 否决/采纳理由 |
|---|---|---|
| 1 全命令死闸 | 缺 REPO 一律拒 | **否决**：误伤 B 类 design 合法回退（lab-auto 定时链 REPO=trade-data 时 trade-data/lab 缺失也靠回退）+ export.py 显式 trade 上传语义 |
| 2 全放行仅告警 | notify 提醒 | **否决**：告警滞后，盘后旧数据已盖上线（本次事故即此类） |
| 3 改 STATIC_DIR 派生逻辑（resolve→absolute 或默认 trade-data） | 动 L28/L33 本体 | **否决**：结构性改动波及全部 15 类调用方与 21 命令，回归面不可控（方案4 教训） |
| **4 分级闸（推荐）** | 区分「显式 vs 缺省」两态 + 命令分类处置 | 采纳：显式态零行为变化（launchd/force_env/export.py 全不动），只拦真正危险的「缺省+C类」组合 |

## 5. 推荐方案伪代码

```python
# upload_r2.py 模块顶部，必须在 load_env()（现 L146）之前捕获，
# 防 .env setdefault 污染判定（加注释钉死顺序）
_RAW_REPO = os.environ.get("REPO")            # 原始 env
REPO_EXPLICIT = bool(_RAW_REPO)

STATIC_DIR = Path(_RAW_REPO or str(ROOT)) / "static-site"

# B 类白名单：生成器按 __file__ 写 trade 树，trade-data 侧天然缺/滞后（update_lab.sh rsync 补偿）
_TRADE_FALLBACK_OK = {"upload-lab", "upload-trade-sim", "upload-trade-sim-json"}
_A_CLASS = {"list", "upload", "upload-claude-backup", "download-db", "delete", "clean-data-backup"}

def guard_repo_default(cmd: str) -> None:
    """REPO 缺省（手动裸跑）分级闸；dispatch 层 cmd 解析后立即调用。"""
    if REPO_EXPLICIT:
        return                                  # 显式态：launchd/force_env/export.py，信任调用方
    if cmd in _A_CLASS:
        return
    if cmd in _TRADE_FALLBACK_OK:
        print(f"ℹ REPO 未设，{cmd} 按 design 回退 trade 树产物", file=sys.stderr)
        return
    if cmd == "purge-low-freq":
        print("⚠ REPO 未设：purge 集合按 trade 侧扫描，可能与 trade-data 有差异", file=sys.stderr)
        return
    print(f"✗ REPO 未设：STATIC_DIR 将回退 {ROOT}/static-site（trade 旧库快照），"
          f"拒绝上传 {cmd}（防旧数据盖线上，intraday 事故同类）\n"
          f"  正确跑法：REPO=/Users/linhuichen/code/trade-data python scripts/upload_r2.py {cmd}",
          file=sys.stderr)
    sys.exit(3)
```

配套（根治面补完）：7 个不 export 的脚本补 `export REPO GIT_REPO` 一行（对齐 intraday_snapshot.sh L27-28 / gold_night.sh L22 先例）：update_all.sh / deploy.sh / backup_db.sh / push_schedule_stats.sh / update_lab.sh / pf_score_daily.sh / pf_score_weekly.sh。语义变化诚实标注：export 化后这些链的上传源从 trade 变 trade-data——两者已被前置 rsync 同步，内容一致，且与 deploy.sh L128 注释声明的预期（STATIC_DIR=trade-data 上传）对齐。

worktree 边界：`.claude/worktrees/*/scripts/upload_r2.py` 的 ROOT 是 worktree 树，「缺省+非白名单一律拒」天然覆盖（worktree static-site 空/旧，拒了才对）。

监控联动：exit 3 属预期拦截，monitor_72h/schedule_monitor 会因「未上传」触发 stale 告警——这是想要的信号（说明有人还在裸跑），不是误报。

## 6. 回归场景清单（12 条）

1. 定时链全绿：17:50 update-all / 盘中 intraday / lab-auto / pf-score-daily / 20:40 daily-brief / gold-night / backfill 系各跑一轮，grep 当日日志无 exit 3、upload 全成功
2. 手动 `bash scripts/deploy.sh`（无 REPO）：export 化后 12 个命令正常，curl R2 `data/overview.json` date == 最新交易日
3. 直跑 `python static-site/export.py`（EXPORT_SKIP_R2 不设）：末尾 7 个自动上传成功（显式 REPO=str(ROOT) 不受闸）
4. 手动 update_lab.sh：upload-lab 白名单放行 + rsync 补偿仍在
5. 裸跑拒绝验证：`unset REPO` 后 `upload-intraday`（盘后）/ `upload-index` / `upload-db` → exit 3；`upload-lab` → 放行+提示
6. 带 REPO 放行：`REPO=/Users/linhuichen/code/trade-data … upload-intraday` → 正常上传
7. intraday_snapshot.py 的 `upload <local> <key>` 路径无 REPO 仍放行（盘中 sentiment 5 ranges 上传不断）
8. backup_db.sh（export 化后）upload-db 备份读 trade-data/data 新库
9. force_env 三处（fetch_news/gen_daily_brief/overfit_monitor）子进程不受影响
10. §22 一致性：上线后 curl R2 `data/intraday_snapshot.json` collected_at 新鲜 + `data/schedule_stats.json` 为当日版
11. monitor_72h 表现确认：拦截事件产生 stale 告警可接受，不误报为脚本崩溃
12. 版本冻结核对（§23.7）：launchd 定时链行为零变化（plist 本就注入同值 REPO），变化仅在「手动裸跑」这一非生产形态——属 bug 修复非功能调整

## 7. 已验证方法/数据源清单

- 读 upload_r2.py 全量（L20-50 头部/L250-270 lab 回退/L360-480 trade_sim 回退+dispatch）
- grep 全仓 `upload_r2.py` 调用点（15 类调用方逐一读上下文）
- launchd plist 逐个 PlistBuddy 打印 ProgramArguments + EnvironmentVariables（update-all/gold-night/lab-auto/pf-score-daily/pf-score-weekly/self-heal）
- `ls -la /Users/linhuichen/code/trade-data/` 证实 scripts/export.py symlink 结构
- deploy.sh/update_all.sh/update_lab.sh/push_schedule_stats.sh/backup_db.sh/gold_night.sh/intraday_snapshot.sh/pf_score_daily.sh 逐个读 REPO 行与 rsync 补偿行
- main-merge.sh grep 证实不调 deploy

## 复现

- 脚本：纯调研无新脚本；核验命令如下（一行可跑）
- 输入依赖：`scripts/upload_r2.py`、`~/Library/LaunchAgents/com.trade.*.plist`、`ls -la /Users/linhuichen/code/trade-data/`
- 复现命令：
  - `grep -n "resolve()\|REPO" scripts/upload_r2.py | head` （根因两行：L28 resolve / L33 STATIC_DIR）
  - `grep -rn "upload_r2.py" scripts/ app/ static-site/export.py --include='*.py' --include='*.sh' | grep -v Binary`
  - `/usr/libexec/PlistBuddy -c 'Print :EnvironmentVariables' ~/Library/LaunchAgents/com.trade.update-all.plist`
  - 裸跑复现（勿在盘后真实执行 C 类！仅 list 安全）：`env -u REPO python scripts/upload_r2.py list`
- 数据截止：2026-08-22 代码 HEAD（feat/home-sim-backtest e647ca417 之后工作区）
- 关键口径一句话：REPO「显式」（launchd 注入/force_env/脚本自 export）= 读 trade-data 侧；「缺省」（终端裸跑）= STATIC_DIR 回退 trade 侧旧库快照 = 本次加闸对象
