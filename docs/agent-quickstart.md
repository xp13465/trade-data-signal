# 子 agent 快速上手引导（agent-quickstart.md）

> **目的**：子 agent fresh context 接到任务后，按本文档快速进入状态，**不重新调研架构/流程**。
> 本文档是各类任务的**总览引导 + step-by-step**。数据上线详细见 [docs/data-deploy-quickstart.md](data-deploy-quickstart.md)（数据产物改动走那里，本文只引用不重复）。
> 深度架构文档：[docs/site-deployment.md](site-deployment.md)（站点架构+从零重建）、[docs/r2-deployment.md](r2-deployment.md)（R2 数据层）、[docs/smoke-checklist.md](smoke-checklist.md)（P0 主功能回归清单）。
>
> 最后更新：2026-08-08。硬规范见 `CLAUDE.md`，本文只摘任务执行相关要点，约束引用章节号不重述全文。

---

## 0. 第一动作：判断任务类型

接到任务**先判断属于哪类**，跳到对应章节照做。不确定时按"最接近"归类，并先读 [§1 工作模式](#1-子-agent-工作模式所有任务通用)。

| 任务特征 | 类型 | 跳到 |
|---|---|---|
| 改 `scripts/export*.py` / 生成 `static-site/data/*.json` / upload_r2 / 数据字段/新增品种 | 数据产物改动上线 | [§A](#a-数据产物改动上线) |
| 改 `static-site/app.js` / `lab.js` / `common.js` / `style.css` / `lab.css` / `index.html` | 前端代码改动上线 | [§B](#b-前端代码改动上线) |
| 改 `worker/`（CF Workers 路由/headers/_headers） | Worker 代码改动上线 | [§B 末尾](#worker-代码) |
| 改 `app/*.py`（FastAPI 后端）/ `scripts/*.py`（非 export） | 后端代码改动上线 | [§C](#c-后端代码改动上线) |
| 跑采集脚本 / 加定时任务 / 源切换 | 采集任务 | [§D](#d-采集任务) |
| 验证功能是否真上线 / 验数据层 | 上线验证 | [§E](#e-上线验证) |
| 定位根因 / 查证 / 方案分析 / 盘点（只读不改） | 调研任务 | [§F](#f-调研任务) |
| 读写 `data/sentiment.db` / `etf_national_team.db` / 迁移 DB / 建表 | DB 操作 | [§G](#g-db-操作) |

---

## 1. 子 agent 工作模式（所有任务通用）

不论什么任务，先遵守以下工作模式（CLAUDE.md §2/§11/§13）：

1. **进度文件**：`/tmp/agent-progress-<你的名字>.md`，**每步立即 echo 回写**（每个 grep/Edit/Read 都回写，不是每大步骤）。主控靠这个查进度，不依赖 jsonl（大）/通知（会丢）。
2. **完成时两个动作**：`SendMessage to: 'main', summary: '<10字内>', message: '<结论摘要+关键验收点>'` **+** 进度文件末尾写 `## DONE <总结>`。两件事都做（通知丢失率高，进度文件 DONE 是证据）。
3. **`run_in_background: true`**：你是被主控 background 派出的，不要阻塞。
4. **模型只文本，不支持图片**（§13）：禁止 Read 截图/图片/视觉对比，触发 API 400 终止。需视觉验证用文字+ASCII 示意图，或让用户自己看。
5. **不 `git add` 根 `data/`**（§8）：`data/sentiment.db`/`etf_national_team.db`/`signal_stats.json` 等保持本地 untracked，commit 时只 add 你改的具体文件，不用 `git add .` / `git add -A`。
6. **commit message 末尾加** `Co-Authored-By: Claude <noreply@anthropic.com>`。
7. **push feat 普通推送，不 force-with-lease**（§8）：non-fast-forward 优先 `git fetch + git rebase origin/main + 重试 push`；rebase 失败 `git rebase --abort` 退出等人工，不强推。
8. **避开定时任务时点 push main**（§14）：盘后 `15:35 / 16:00 / 17:50 / 20:35 / 22:00` 不推 main（撞 intraday-snapshot/update-all 互相覆盖事故）；盘中 `09:30-15:30` 不跑全量 export+deploy；安全窗口 `23:00+` 或午休 `11:30-13:00`。
9. **不问 yes/no**：自己定，连轴转。只在真·方向分叉（A/B/C 选型）才给主控选项附推荐。

---

## A. 数据产物改动上线

> **详细步骤见 [docs/data-deploy-quickstart.md](data-deploy-quickstart.md)**（a0a2e9c03 维护）。本节只给概要 + 关键坑。

### 核心认知（先记住）

- **数据 JSON 走 R2，不进 git**。`static-site/data/` 已 `.gitignore`（catch-all `static-site/data/*` + `!feed.xml`），167 个 JSON 文件里**只有 `feed.xml` 被 git 跟踪**（`git ls-files static-site/data/` 返回 1 个）。R2（`ssd.fx8.store` 公开桶）是线上数据**唯一来源**，前端 `/data/*.json` 经 Worker `/data/` rewrite 路由到 R2 binding 直读。
- **`git ls-files` 返回空 ≠ 文件不存在**：R2 迁移后数据文件 gitignored，文件在磁盘/R2 有，只是不在 git。别因为 `git ls-files` 空就以为文件丢失。
- **export 路径不同步陷阱**（§9 衍生）：export.py 若在 `trade-data/` 跑会写 `trade-data/static-site/data/`，但 deploy.sh 从 `trade/static-site/data/` 推。export 后**必须 cp 或确认 rsync 同步**两路径，否则推旧版。

### 上线流程（概要）

1. 改 export 脚本（如 `scripts/export_*.py`）。
2. 跑 export 生成 JSON（cwd 注意 §9：读 DB 用 `trade-data/`，但写 JSON 输出路径要同步回 `trade/`）。
3. 跑 `upload_r2.py` 推 R2（按类别选命令，见下表）。**新类别优先按前缀建独立命令，不依赖 1MB 阈值**（§8.1）。
4. purge cache（Worker `/api/purge-cache` 或等 CF edge 刷新；CF Static Assets 无视 Cache-Control 靠部署自动 purge，R2 走 Worker 代理的需主动 purge）。
   - **purge_cache 必分批**（§18 经验① ea64df512）：一次性发 400+ keys 致 CF Worker CPU/wall time 超限 -> 500 error。每批 30 keys（PURGE_BATCH_SIZE，20-50 安全区间）+ 批间 sleep 0.5s 避 CF 限流。`upload_r2.py` 已内置分批逻辑，手动 purge 也须分批。
5. curl 3 域名 + R2 直链验证数据层（见 [§E](#e-上线验证)）。

### upload_r2.py 命令速查

| 命令 | 作用 | R2 前缀 |
|---|---|---|
| `upload-lab` | lab/*.json | lab/ |
| `upload-trade-sim` | trade_sim_*.html | trade_sim/ |
| `upload-trade-sim-json`（或 `-json` 子命令） | trade_sim stats/full json | trade_sim_data/ |
| `upload-index` | data/index/*.json | index/ |
| `upload-industry` | data/industry-* | industry/ |
| `upload-public-fund` | data/public_fund*.json | public_fund/ |
| `upload-offshore-fund` | data/offshore_fund*.json | offshore_fund/ |
| `upload-data-large` | data/ 顶层 >1MB .json | data/（exclude industry-/public_fund 防双副本） |
| `upload-all-data` | data/ 全量小 .json | data/（阶段1a 双写） |
| `upload-db` | 每日 DB 备份推 signal-backup 私有桶 | backup/ |
| `download-db <name>` | 下载最新备份（解压后 .db 路径到 stdout） | - |

> 走 R2 的判定（§8.1，按数据类别不按单文件大小）：全量品种多 / 有大 range 历史序列（`-all/-5y/-3y` 单文件 >1MB）/ 类别整体大。走 CF Workers Static Assets 的小文件：单文件 <100KB 且类别总量 <5MB 的状态/监控小文件。

### 前端读 R2 的两种模式

- **大 range 历史序列** `-(all|5y|3y).json$`：前端 `dataUrl` 走 R2 `data/` 前缀（`ssd.fx8.store/data/`）。
- **其他 R2 类别**（industry/index/trade_sim/public_fund）：前端用硬编码 `https://ssd.fx8.store/{prefix}/` URL。

---

## B. 前端代码改动上线

> 改 `static-site/app.js` / `lab.js` / `common.js` / `style.css` / `lab.css` / `index.html` 后，**三步缺一不可**（§9），否则用户拿不到新代码。

### 三步（缺一不可）

```bash
cd /Users/linhuichen/code/trade

# 1. build_min.py：terser minify app.js/lab.js/common.js + rcssmin style.css/lab.css
#    生成 *.min.js + *.min.css（不生成 source map 防泄露源码）。幂等可重复。
python scripts/build_min.py

# 2. bump_asset_version.py：给 index.html 的 CSS/JS 引用注入 ?v=<md5前8位>，破浏览器/CDN缓存
python scripts/bump_asset_version.py

# 3. bump sw.js CACHE_VERSION：手动改 static-site/sw.js 第 17 行的 CACHE_VERSION 字符串
#    格式 v<N>-<YYYYMMDD>-<a序号>，如 v6-20260809-a59 -> v6-20260809-a60
#    否则旧 Service Worker CacheFirst 缓存旧 app.min.js，用户硬刷后退回旧数据
```

**为什么三步都要**：
- 只跑 build_min 不 bump 版本号：浏览器/CDN 缓存旧 `app.min.js?v=旧hash`，拿不到新版。
- 只 bump 版本号不 bump sw.js：旧 Service Worker CacheFirst 拦截，根本不 fetch 新版。
- build_min 失败 deploy.sh 会兜底补跑（L170-176），但版本号 + sw.js 必须手动。

### 验证 min 版上线（§9 关键坑）

**用字符串 grep，不用变量名**：terser mangle 会重命名 `let` 局部变量（如 `_compBarsHtml` 被 mangle 消失）。grep 验 min 版上线用 **class 名 / 中文字符串**（如 `kst-comp-fill` / `分项构成` / `优秀`），不要用变量名。

```bash
# 验 min 版含你的改动（用你改动的 class 名/中文字符串）
grep -c "你的class名或中文字符串" static-site/app.min.js
# 验版本号已 bump
grep "CACHE_VERSION" static-site/sw.js
```

### push 上线

```bash
git add static-site/app.min.js static-site/app.js static-site/sw.js static-site/index.html  # 只 add 你改的 + 生成的 min 文件
git commit -m "描述

Co-Authored-By: Claude <noreply@anthropic.com>"
git push origin feat/你的分支    # push feat 触发 CF deploy; 普通推送不 force
```

push feat:main 触发 GH Actions `deploy-cf.yml` 自动 deploy 到 CF Workers（ss.fx8.store）。需同步 main 则 `git push origin feat/xxx:main`（避开定时任务时点 §14）。

### app.js em dash 编辑坑

`app.js` 含 em dash（`—` U+2014，非 ASCII `-`）。Edit / `str.replace` 用 `-` 匹配会失败，改用 regex 或粘贴 `—` 字符。

### Worker 代码

改 `worker/`（CF Workers 路由 / `headers.js` / `_headers`）后：push main 触发 CF deploy。`_headers`（CSP/HSTS/nosniff/X-Frame/Permissions-Policy）只在 `ss.fx8.store`（CF Workers 主站）生效，`s.sugas.site`/maozi.io（MaoziYun）`_headers` 不生效（自带 HSTS + meta referrer 兜底）。

---

## C. 后端代码改动上线

> 改 `app/*.py`（FastAPI）/ `scripts/*.py`（非 export 类）。

1. 改代码。
2. 本地验证（§9 本地开发）：
   ```bash
   cd /Users/linhuichen/code/trade-data && /Users/linhuichen/code/trade/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
   # ⚠️ cwd 必须是 trade-data/（非 trade/），让 app/db.py 的 .absolute() 读最新主库
   ```
3. `git add app/your_file.py` + commit（末尾 Co-Authored-By）+ push feat:main。
4. 线上是静态站（CF Workers Static Assets），后端 FastAPI 主要本地/采集用。确认改动是否影响线上数据产物（若 export 脚本读了你改的后端逻辑，跑 [§A](#a-数据产物改动上线) 重新生成数据）。

---

## D. 采集任务

> 跑采集脚本 / 加定时任务 / 源切换。**生产稳定性 P0**（§14），撞车会致线上数据覆盖事故/DB锁。

### 跑前必查：launchd 定时任务清单

```bash
launchctl list | grep trade          # 查活跃任务 + PID
ls ~/Library/LaunchAgents/ | grep trade   # 查 plist 文件
# 看具体时点：
for f in ~/Library/LaunchAgents/com.trade.*.plist; do echo "=== $(basename $f) ==="; grep -A4 "StartCalendarInterval" "$f" 2>/dev/null; done
```

**核心冲突时点（盘后，不推 main 不写 DB 不跑采集）**：
- `15:35` / `16:00` / `17:50`（update-all 全量采集+评分+export+deploy）
- `20:35`（intraday-snapshot 盘后收尾推 main）
- `22:00`（部分 backfill）
- 盘中 `09:30-15:30`：intraday-snapshot 每 10 分钟推 `intraday_snapshot.json` 到 main（时点 `:25/:35/:45/:55/:05/:15`），不跑全量 export+deploy

**安全窗口**：`23:00+`（无推 main/评分/采集任务，除周日 3:17 weekly + 5:00 us-stock-morning 不写 public_fund.db）。大型实施任务放此窗口。

### 采集脚本不并发

采集脚本并发 = 撞 progress + 限流空转。`update_all` 有 `fcntl.flock --nb` 进程互斥（重复跑自动跳过）。新采集任务不要和现有任务并发跑同一源/同一 DB。

### 源切换触发条件

- **指数多源补采**：step2 采后校验 10 核心 A 股指数，缺则 baostock（8/10）-> 腾讯（兜底 kc50）补采。东财 2 源被封弃用。
- **行业换源**：东财封 IP -> 同花顺/新浪。触发=再出现行业抓不到（滞后/缺失非 T+1）。
- **分时多源批量**：同花顺批量 10 + 东财 push2delay2 = 3 请求，降 75% 并发（根治腾讯 WAF 频率风控）。

---

## E. 上线验证

> **核心铁律：验数据层，非验代码在 main**（§8）。代码在 main + 版本号上线 ≠ 功能生效。说"已上线"前必须 curl JSON 验数据层。

### 3 域名 + R2 直链

| 域名 | 类型 | 说明 |
|---|---|---|
| `https://ss.fx8.store/` | CF Workers 主站 | `server: cloudflare`，push main 自动 deploy，支持 br 压缩，`_headers` 生效。**首选验证** |
| `https://sss.sugas.site/` | GH Pages 备站 | `xp13465/trade-data-signal` 仓库 |
| `https://s.sugas.site/` | MaoziYun 备站 | **有 300MB 总大小限制**，超了拒绝部署一直 404（曾 531MB 超 300MB 自 21:35 停止拉取） |
| `https://ssd.fx8.store/` | R2 直链 | 大 JSON（5MB+ `*-all/5y/3y.json`）走这里，`ss.fx8.store` 对大 JSON 返回 404 |

**3 域名任一验证到新版即算上线 OK，不卡单域名 404**（教训：曾整晚死磕 s.sugas.site 404 忘 ss.fx8.store/sss.sugas.site 已上线）。

### 验证方法

```bash
# 1. 验代码版本号上线（CSS/JS ?v= hash）
curl -s https://ss.fx8.store/ | grep -o 'app.min.js?v=[a-f0-9]*'

# 2. 验数据层（关键！curl JSON 验字段有值，非验代码在 main）
curl -s https://ss.fx8.store/data/overview.json | python3 -c "import sys,json;d=json.load(sys.stdin);print('字段值:', d.get('你改的字段'))"
# 大 JSON 走 R2 直链
curl -s https://ssd.fx8.store/data/index-all.json | head -c 200

# 3. 验 sw.js CACHE_VERSION
curl -s https://ss.fx8.store/sw.js | grep CACHE_VERSION
```

**判断"功能生效"标准**（§8 教训）：
- 代码在 main + 版本号上线 ≠ 功能生效。
- 必须 curl JSON 验数据层：字段有值 / 无旧字段残留（如旧版 `signals_today` 还有 `s.sentiment_cyb`）。
- 让用户确认显示（模型只文本看不了 UI）。

### 大 JSON 走 R2 直链

`ss.fx8.store` 对 5MB+ 大 JSON（`*-all/5y/3y.json`）返回 404（CF Workers Static Assets 限制），前端 `dataUrl` 走 R2 直链 `ssd.fx8.store/data/`。验证大文件上线 curl `ssd.fx8.store` 或 `sss.sugas.site`，**非 `ss.fx8.store`**。

---

## F. 调研任务

> 只读不改。定位根因 / 查证 / 方案分析 / 盘点。产出结论 + 证据（grep/SQL/读代码结果），主控验收。

### 调研准则（§18 教训精华）

1. **下结论前验证数据产物层**：不只看代码逻辑分支，**查 R2 旧版 vs 新版字段值差异**。教训：调研说"signal-tier 没铺到 hoverpop 用老逻辑"，实际前端已用新逻辑，真因是数据产物不一致（R2 index-all 旧 `'none'` vs overview 新 `null`）。
2. **调研先对准 UI 位置**：用户说"X 不见了"，先 grep 渲染层（显示层），确认显示层无问题再查生成层。教训：用户说"走势卡相关 etf 后面至今盈亏不见了"，调研去查生成逻辑 `queries.py etf_since_return` 而非显示层 `etf-tag-pnl` 渲染，方向偏差。
3. **"无/0/不可改善"结论换方法/换数据源验证**：不只验证当前算法覆盖范围，要换方法（第三方平台如同花顺概念搜索）+ 考虑不同关联维度（持仓重叠 vs 成分重叠）。教训：调研断"全市场 0 只量子 ETF/不可改善"，但用户用同花顺搜到多个相关 ETF，真因是算法只看成分股直接重叠不看 ETF 持仓重叠。
4. **调研结论里列"已验证哪些方法/数据源"**：便于主控判断充分性。
5. **改体系遍历所有分支**：改动一个灯/样式体系时，grep 所有 `return {cls:` 确认无过时拦截分支，不只改主路径。教训：信号灯统一配色时漏了 `if(track_low_confidence) return 灰蓝虚线` 拦截分支。
6. **"X 分钟更新"查 launchd plist 非脚本文件头注释**：注释易过时。

### 调研方法

```bash
# grep 代码（用 rg 更快）
rg "关键词" --type py -l          # 找哪些 py 文件含关键词
rg "关键词" static-site/*.js -n   # 前端代码定位行号

# 查数据产物
python3 -c "import json;d=json.load(open('static-site/data/xxx.json'));print(json.dumps(d,ensure_ascii=False,indent=2)[:500])"

# 查 R2 线上版 vs 本地版差异
curl -s https://ssd.fx8.store/data/xxx.json | python3 -c "import sys,json;print(json.load(sys.stdin))"
```

### 调研产出格式

```
结论：<一句话>
证据：
- grep/file:line <具体行号> <关键代码>
- SQL/数据：<查询结果>
已验证方法/数据源：<列出，便于判断充分性>
风险/未覆盖：<诚实标注>
```

---

## G. DB 操作

> 读写 `data/sentiment.db` / `etf_national_team.db` / 迁移 DB / 建表。

### 铁律

1. **不 `git add` 根 `data/`**（§8/§10）：`data/sentiment.db`（80MB）+ `etf_national_team.db` 曾进 git，2026-07-14 已 `git rm --cached` 移出，现 untracked。commit 时只 add 具体代码文件。
2. **绝不 `git restore data/sentiment.db` / `git checkout -- data/sentiment.db`**（若不慎重新 add）。
3. **不 checkout main 避免碰 DB**（§10）：DB untracked 后 checkout 不再碰 DB，但**同步 main 用 `git push origin feat/xxx:main` 或 `git fetch origin && git reset`，非 `git checkout main && merge --ff-only`**（中间态 checkout 仍 track DB 的分支会复现事故）。
4. **cwd 影响 DB 读取**（§9）：`app/db.py` 的 `.absolute()` 解析依赖 cwd。uvicorn 跑后端用 `trade-data/`（读最新主库 inode 237343239），非 `trade/`（滞后镜像 inode 238648312，仅 deploy.sh rsync 时同步）。
5. **export.py sys.path 根因**（§9 衍生）：`export.py` L38-39 `sys.path.insert(0, trade/)` 致 import app 读镜像非主库。DB UPDATE 须同时写主库+镜像，跳过 rsync 避免旧版覆盖新版。

### DB 备份

- 每天 3:17 `com.trade.self-backup`（launchd）备份 memory + CLAUDE.md + NOTES/TASKS 到 `~/.claude/backups/daily/`（保留 30 天）。
- R2 `signal-backup` 私有桶：DB gz 分层（backup/30 天 + weekly/28 天 + monthly/365 天）。`upload_r2.py upload-db` 推，`download-db <name>` 下载恢复。

---

## 常见坑速查（§18 精华，子 agent 易犯）

### 路径 / 仓库混淆

- **`trade` vs `trade-data`**：`trade` 是主 git 仓库（代码 + deploy.sh 推 git）；`trade-data` 是采集工作区（DB 主库 + launchd 写入 + uvicorn 跑后端）。`trade-data/app` 是 symlink 指向 `trade/app`，代码不变。**读 DB 用 trade-data/，推 git 用 trade/**。
- **export 输出路径不同步**（§9 衍生）：export 在 trade-data/ 跑写 `trade-data/static-site/data/`，deploy.sh 从 `trade/static-site/data/` 推。export 后必须 cp 或确认 rsync 同步。
- **agent 误报 trade/trade-data 混淆**：关键结论（路径/文件数类）主控会 §0 验，别把 trade-data 的文件数报成 trade 的。

### git / 数据

- **`git ls-files` 返回空 ≠ 文件不存在**：R2 迁移后 `static-site/data/` gitignored，文件在磁盘/R2 有，只是不在 git。别因 `git ls-files` 空以为丢失。
- **CF Static Assets 旧快照 vs R2 新版**：`ss.fx8.store` 可能是 CF 旧快照（edge cache），`ssd.fx8.store` 是 R2 新版。数据层验证优先 curl R2 直链。
- **`.gz` 断定不严谨**：别凭 memory 断 `.gz` 是否生成/前端是否 fetch。`fetchJSON` 已全跳 `.gz`（`tryGz=false`），本地/R2 保留 `.gz` 不删，前端只是不 fetch。断定前验证。

### 上线 / 时段

- **盘中（09:30-15:30）不跑全量 export+deploy**：全量 deploy 会 `git add` 通配带入旧 `intraday_snapshot.json` 覆盖线上实时版（事故根因）。盘中只跑 intraday-snapshot 定时任务。deploy.sh L37-49 内置时段闸门拒跑（force 可绕过）。
- **盘后定时任务时点不推 main**：`15:35 / 16:00 / 17:50 / 20:35 / 22:00`，撞 intraday-snapshot/update-all 推 main = 互相覆盖事故。安全窗口 `23:00+`。
- **改 app.js 必 bump sw.js CACHE_VERSION**：否则旧 Service Worker CacheFirst 缓存旧 `app.min.js`，用户硬刷后退回旧数据。三步（build_min + bump_asset_version + bump sw.js）缺一不可。
- **min 版 JS 验证用字符串非变量名**：terser mangle 重命名 `let` 局部变量，grep 用 class 名/中文字符串（`kst-comp-fill`/`分项构成`）非变量名（`_compBarsHtml` 会消失）。

### 调研 / 理解

- **调研下结论前验证数据产物层**：不只看代码逻辑，查 R2 旧版 vs 新版字段值。调研结论"没铺到/老逻辑"类要 grep 验证再报。
- **调研先对准 UI 位置**：用户说"X 不见了"先查渲染层，确认显示层无问题再查生成层。
- **"无/0/不可改善"结论换方法换数据源**：不只验证当前算法范围，考虑第三方平台 + 不同关联维度（持仓重叠 vs 成分重叠）。
- **改体系遍历所有分支**：grep 所有 `return`/分支，不只改主路径。
- **"X 分钟更新"查 launchd plist 非脚本注释**：注释易过时。
- **commit 时间戳 ≠ 触发时点**：commit 时间戳是 deploy 完成打标签非任务触发。判断任务是否跑看 launchd log 文件存在性，非 commit 时间。

### git 操作

- **切分支/checkout 前 CronList + 查后台 agent**：cherry-pick 撞冲突 + 干扰后台 agent 改同文件。切分支前确认无后台 agent 在改文件。
- **归档 done 前 `git show <commit>` 核对**：不凭 commit 标题/摘要臆断完成内容（标题可能只说大方向，body 才说具体做了/没做）。
- **force-with-lease 是最后手段**：non-ff 优先 `git fetch + rebase origin/main + 重试`，rebase 失败 abort 等人工。agent 不擅自强推，尤其推 main。

### 通知 / 协作

- **SendMessage 丢失率高**：完成时 SendMessage to 'main' + 进度文件 `## DONE` 两件事都做。主控有 cron 兜底查进度文件，但别依赖通知单渠道。
- **worktree isolation SendMessage 不送达**：worktree sidechain agent SendMessage queued success 但不送达主控 session（harness 限制），必配 cron 兜底。
- **中途改口径停旧派新**：主控改口径/方向会停旧 agent 派新 agent 带全新规格。子 agent 收到"非用户确认"系统提示拒绝大重构是正常的（SendMessage resume 触发），改派新 agent 初始 prompt 绕过。

### 前端轮询 / 定时器自愈（§18 经验⑤ d2a97108b）

实现定时轮询类前端机制（如分时图 1min 刷新）时，5 个自愈要素缺一不可：

1. **fetch 加 AbortController 超时**（8s）：防 await 永不返回卡死定时器链。
2. **inflight 去重 Map + 兜底清理**（15s）：防卡死 finally 不触发毒化后续请求。
3. **失败不永久停，改降频兜底重试**（6次失败 -> 5min 降频，7x24 自愈）：网络恢复自动恢复 1min。
4. **心跳唤起**（overview 3min 轮询检查 intraday 定时器是否丢失，丢失则重启）：防定时器被异常杀死后永久死亡。
5. **visibilitychange 切回前台清 in-flight**：防后台 Promise 毒化前台请求。

### 数据挖掘 / 多特征组合优化（§18 经验⑥ 7ada31c57）

多特征组合优化场景（降亏标志/参数寻优/规则发现），用决策树找高纯度叶节点，非人工穷举：

- **手写 CART 决策树 + beam search 子群发现 + 关联规则 + 多维交叉**：超越人工 2 特征穷举（最高比值 2.52），找到 78 个比值>3 标志（单标志最高 10.06）。
- **关键**：决策树叶节点纯度 = 标志有效性（高纯度亏损叶 = 高比值降亏标志）。
- **产出文档**：`docs/kelly-loss-mining-v3.md`（v3 决策树挖掘）、`docs/kelly-loss-mining-methods.md`（方法论调研）。

---

## 关键文件 / 脚本速查表

| 路径 | 作用 |
|---|---|
| `CLAUDE.md` | 硬规范（§8 上线/§9 单版前端/§14 生产稳定/§15 回归/§18 过错防重犯）|
| `scripts/build_min.py` | terser minify app/lab/common.js + rcssmin style/lab.css |
| `scripts/bump_asset_version.py` | index.html 注入 `?v=<md5前8位>` 破缓存 |
| `scripts/deploy.sh` | 全量 deploy：export.py + build_min + upload_r2 + git push（cwd=trade/）|
| `scripts/upload_r2.py` | R2 上传（按前缀命令 + 1MB 阈值兜底）|
| `static-site/sw.js` | Service Worker，L17 `CACHE_VERSION` 改完 app.js 必 bump |
| `static-site/app.js` / `lab.js` / `common.js` | 前端源码（保留供开发，min 版上线引用）|
| `static-site/index.html` | 引用 `*.min.js?v=hash`，bump_asset_version 改这里 |
| `static-site/data/` | 数据 JSON（gitignored 走 R2，仅 feed.xml tracked）|
| `data/sentiment.db` | 主 DB（untracked，cwd trade-data/ 读主库）|
| `docs/site-deployment.md` | 站点架构 + 从零重建 |
| `docs/r2-deployment.md` | R2 数据层架构 + 灾备 |
| `docs/smoke-checklist.md` | P0 主功能回归清单（reviewer agent 读取执行）|
| `docs/data-deploy-quickstart.md` | 数据产物改动上线详细（a0a2e9c03 维护）|
| `~/Library/LaunchAgents/com.trade.*.plist` | launchd 定时任务时点定义 |

---

## 本地开发环境

```bash
# 前端（python http server，看静态页）
python -m http.server -d static-site

# 后端（uvicorn，cwd 必须是 trade-data/ 读主库）
cd /Users/linhuichen/code/trade-data && /Users/linhuichen/code/trade/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
# 调试加 --reload
```

- **默认皮肤红金中国风**（非浅色），首次访问 localStorage 空时回退 redgold。
- **单版前端铁律**（§9）：前端源码统一在 `static-site/`，`web/` 已删不再双写。`app/main.py` 挂载 `static-site/` 到根 `/`，`/api/*` 读 DB 不变。

---

*本文档是子 agent 快速上手的总览引导。发现新坑/新任务类型请补充（落档防重犯，§19 自我成长机制）。硬规范以 `CLAUDE.md` 为准，本文只摘任务执行相关要点。*
