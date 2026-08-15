# 子 agent 快速上手引导（agent-quickstart.md）

> **目的**：子 agent fresh context 接到任务后，按本文档快速进入状态，**不重新调研架构/流程**。
> 本文档是各类任务的**总览引导 + step-by-step**。数据上线详细见 [docs/data-deploy-quickstart.md](data-deploy-quickstart.md)（数据产物改动走那里，本文只引用不重复）。
> 深度架构文档：[docs/site-deployment.md](site-deployment.md)（站点架构+从零重建）、[docs/r2-deployment.md](r2-deployment.md)（R2 数据层）、[docs/smoke-checklist.md](smoke-checklist.md)（P0 主功能回归清单）。
>
> 最后更新：2026-08-16（补 §F 回测/挖掘基线= v1.1.0 基准 + 报告落档四件套 git ls-files 验收 + 汇报在跑 agent 数先核对 + 禁止用 Explore 派只读任务 + 非交易日不触发/不补发）。硬规范见 `CLAUDE.md`，本文只摘任务执行相关要点，约束引用章节号不重述全文。

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
7. **派数据重跑/回测任务前先核对当前页面默认筛选/基准真值**（§18 L31）：不沿用旧报告基准。派单前 grep 当前页面 `_kellyDefaultFilters()` / `_kellyComboPresets`（默认键集/组合宏定义），基准写进 prompt 时标注"来源=当前页面 lab.js Lxxxx 核验"；发现基准过时立即 SendMessage 同步在跑 agent（避免全量重跑）。
8. **需求叫停/改口径先复述"删到什么粒度/保留什么档"**（§18 L30）：用户叫停某功能（如"每日池+买全部没意义"）≠删整个链路，执行前 git show 原实现，列"删除清单+保留清单"确认，不把同链路可保留档（每日池+top-K）一起删；口径类改动后自验关键展示值（K 档切换最大持仓应恒定）。
9. **口径/基准切换先派影响面审计**（§18 E25）：列"会反转/数值变化/自愈"三类再全面修正，不建立在错误口径上继续固化。
10. **回测/挖掘第一件事=确认基线落在 v1.1.0 基准**（§18 L39，2026-08-15 立）：默认前提 = AI宏 5+3+1 = 基础5[n2NovSpecialIndustry/excludeSpecialBear/janMidRating/janMidSpecial/k2c5HkChase]+核心3[r7MayReinforced/excludeAuxCross/greedy15]+1类回测剔除(_bt_in_universe)= 8键+1类(总数9)；组合=每日资金池+K1+G用13万 P≤3d 可操作口径(裸G不是基准)。测非基准口径必须显式声明"非 v1.1.0 基准口径"+说明为何测+结论标注口径差异,不作主推结论。能复现基准基线才往下(如 G 基线 = +202,508/155.78% 且 K2C5 默认开)。
11. **报告落档必走四件套 + git ls-files 验收**（§18 L34，§23.5）：报告本体+生成脚本+##复现段(脚本路径/输入依赖/重跑命令/数据日期/口径一句话)+配套 commit 同批;commit 前 `git ls-files` 确认三件套均已 tracked,缺=验收不过。活脚本写指向不复制,死脚本副本放报告同目录 scripts/。
12. **禁止用内置 Explore agent 派只读/搜索任务**（§18 L35，2026-08-15）：Explore 内置 model=claude-opus-5 不在代理白名单→绕过白名单按 v4-pro 计费(12次~45万tokens泄漏)。只读定位/搜索/结构任务一律派 researcher。

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

- **curl 带认证头诊断禁止 -v/-i**：`curl -sv -H "Authorization: Bearer <token>"` 会把 token 值打印进输出泄漏到会话（2026-08-10 DB Release agent 泄漏 GITHUB_TOKEN 教训，§18 教训 22）。用 `curl -sS -w '%{http_code}'` 或只打 body；token 从 `.env` 读不硬编码不 echo。
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
- **需求先拆解再派 agent（防误派方向）**：接"分析/建议+新增视图"类核心需求，先列需求拆解清单（要回答什么问题+要新增什么视图+用哪份数据回测）再派 agent；不把相关增量功能当核心需求实施（2026-08-11 误派 J1/J2 当核心需求教训，核心需求实为降亏组合建议+全信号表，§18 教训24）。
- **数值/算法口径改动必同步全站公示点**：修一个数值要 grep 全站同一数值所有出现处（purpose-notes.js+app.js/lab.js 算法公示文案）同步改，不只 tooltip/实施点（§18 教训25 §21 复发）。
- **收益率"虚高"标注先算峰值持仓/本金倍数**（§18 L32）：A/F 持仓10-15万=10-15倍单次本金=可操作非虚高；G/H/I 持仓136万=136倍本金=不可操作，"虚高"的是净盈亏金额。"虚高"只用于口径放大数值（每笔1万=虚假杠杆），不用于"高收益但可操作"；top1-G 这类推荐标签需附可操作性校验（≤20倍本金）。
- **汇报"在跑N个agent"先逐个核对完成通知**（§18 L36）：收到完成通知=已完成立即移出在跑,别把已完成/已收通知的还当在跑(用户:"并行在跑的可没4个")。
- **非交易日不触发/不补发**（§18 L37/L38）：AI预测触发源脚本(run_daily_brief.sh)必带交易日判断(复用 trade/app/calendar.py is_trading_day,比 plist Weekday 准);信号邮件/backfill 补发前判断交易日,非交易日不补发不发买卖点信号。

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
- **产出文档**：`docs/kelly/mining/kelly-loss-mining-v3.md`（v3 决策树挖掘）、`docs/kelly/mining/kelly-loss-mining-methods.md`（方法论调研）。

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

## 大文件派单定位锚点表（P0-4，2026-08-15 补）

> 派单/prompt 时主控给「符号+行号」锚点,子 agent 用 `grep -n "符号" 文件` 直达,不整文件从头读(尤其 app.js/lab.js 1.3MB)。**行号会漂移,以 grep 实时为准**,本表给"原子符号"作稳定锚。改完大文件新增关键函数后回填本表。

### static-site/app.js
| 关键符号 | 定位说明（grep -n 该符号） |
|---|---|
| `_dayItems` / `_posCapKeptMap` / `_posCapSortedFn` | 首页 AI 建议 top-K 候选构建(~L2271) |
| `function fetchJSON` | 前端数据拉取统一入口(~L4475) |
| `_bt_late` | 首页盘后迟到信号判定标记(§21) |
| `_isAiFadeHit` | 首页 AI 降亏点击命中判定 |
| `_kellyDefaultFilters`(lab.js) | 凯利默认过滤组合,§21 公示必对真值 |

### static-site/lab.js
| 关键符号 | 定位说明 |
|---|---|
| `_kellyDefaultFilters` | 凯利默认过滤~L7253(§21/§23.6 对真值用) |
| `_kellyComboPresets` | 凯利组合预设 |
| `_kellyRecomputeTrade` | 凯利交易重算~L6995(L19 前端重算对齐后端用) |
| `_kellyComputeStats` | 凯利统计~L7128 |
| `_labBuildMarkData` / `renderLabChart` | 策略实验室图表渲染~L309/L355 |

### 后端锚点
| 关键符号 | 定位说明 |
|---|---|
| `scripts/export.py` | 数据产物生成,改 key 字段(量子top1/stable_top1)§22 校验用 |
| `scripts/signal_stats.py` | 信号统计(引用 backtest_strategies.py) |
| `app/queries.py` `_bt_in_universe` | 首页从回测侧读入样标记(§23.6 ③) |
| `config/universe_rules.yaml` | 入样宇宙规则单一事实源(§23.6 ①) |
| `static-site/purpose-notes.js` | 算法公示文案,§21/§23.6 ② 必改点 |

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

## H. 降亏挖掘/回测任务快速上手

> 完整文献/方法论/方案引导沉淀见 **`docs/kelly/mining/kelly-mining-literature.md`**（本文只给"直接做对"的 step + 坑速查，细节链接到文献文档）。数据源 `static-site/data/signal_kelly_trades.json`（33MB，44,832 笔去重），基准 PF≈1.285。

### 这类任务直接做对 step

1. **先读前几轮报告 + 现有 toggle 口径**：v1→v4 报告 + `docs/kelly/toggle/kelly-loss-reduction-toggle-plan.md`/`-toggle-v2-plan.md`（现有 toggle 口径）+ memory `kelly-loss-toggle-ratio-standard.md`（比值>2 硬口径）。看 v3 §7.4 / v4 §7.4"已验证方法清单"防重复挖。
2. **识别数据维度盲区**：对比数据源全部字段 vs 历轮实际挖过的字段。历轮最大发现来自盲区（market_state 已注入部署版但从未挖过）。未覆盖字段=优先挖掘目标。
3. **换方法换数据源不轻断"不可改善"**：一个算法挖不出≠无标志，换方法/换数据源/换关联维度验证后再下结论。
4. **候选清单 + 比值口径 >2 过滤**：比值=降亏%/损盈%（=Lift-1），>2 满意 >3 更佳；低比值保留备选迭代淘汰；排除会"砍牛利润"的标志（如 low 评级 -810k）。
5. **回测验证 + 4 窗口稳定性 + 叠加边际**：y1/y3/y10/all，比值>2 + maxSh<0.60 + neg 年占比 + 逐年表现（防 5 月 shift 过拟合）；净影响必须为正；**且必须算叠加现有 toggle 的边际贡献**——standalone 比值高≠推荐，被现有 toggle 完全覆盖时边际=0 不推荐（如第三轮 A1/A2/A3 比值 4-10 但边际=0；A45 叠加边际 +107k 才推荐；现有 toggle 已砍 87.9% 亏损时新候选只在残余 12% 里再砍 ~1pp，§18 经验③）。
6. **产出数据报告供用户选**：候选表格（降亏%/损盈%/比值/净影响/逐年稳定性/推荐度），用户 veto/增删，不替用户硬选。
7. **算法/逻辑改动上线遵守 §21**：grep `purpose-notes.js` + app.js/lab.js 算法公示文案同步更新（prompt 要列具体 grep 动作+文件名，不能只引章节号）。

### 常见坑速查（§18 教训链接）

- **比值口径**：比值=降亏%/损盈%（Lift-1），不是降亏%单看；>2 才满意 >3 更佳（memory `kelly-loss-toggle-ratio-standard.md`，§18）
- **稀疏样本**：小样本（n<30）无统计意义，需标注"仅供参考"不进三档推荐；4-itemset n 60-200 有过拟合风险（§18 教训，v4 §7.3）
- **market_state 盲区**：v3/v4 用 19 字段版无该字段，部署版已注入但从未挖过——先核对字段覆盖再动手（§18 教训 8/9/13 模式：验证数据产物层再下结论）
- **不轻断"不可改善"**："无/0/不可改善"类结论必须换方法换数据源验证（同花顺能搜到算法匹配不到的 ETF，持仓重叠 vs 成分重叠），§18 教训 13
- **前端重算对齐后端**：前端 replay/recompute 须逐字段对比后端 JSON，不只 summary；取一个 signal JSON 前端重放后逐字段对比（§18 教训 19，memory `frontend-replay-align-backend`）
- **数据一致性**：算法改动重跑数据产物时列全部依赖清单，重跑+同步 static-site+R2 三步完整（§22 + §18）
- **收益口径**：return_pct_max_holding 是唯一随窗口累积指标（非 total_return，固定金额非复利），年化>100% 或负值要警觉口径定义（§18 教训 14）

---

## I. 飞书 hooks/抄送类任务（0 token 抄送，§18 经验① 2d1b9206e）

> 做"自动抄送会话/消息到飞书群"或"外部消息→主控"链路，先看本节的 0 token 方案，别用 cron 轮询/子agent 转发（占主会话上下文+不实时）。

### 0 token 抄送：hooks 层实现（直接做对 step）

1. `.claude/settings.json` 挂两个 hook（项目级，对主会话+子agent 都生效）：
   - `UserPromptSubmit` → `python3 scripts/feishu_chat_hook.py user`（抄用户输入）
   - `Stop` → `python3 scripts/feishu_chat_hook.py assistant`（抄 assistant 回复）
2. 脚本内：user 模式读 stdin 的 prompt；assistant 模式读 `transcript_path` 最后一条 assistant 文本（env 里取）。调 `notify.send_feishu`（复用 notify.py 密钥，不硬编码）。
3. **全程不经过 LLM = 0 token**；任何异常 `exit 0` 不阻塞 Claude Code。
4. 指纹文件 + flock 去重，防 Stop 多次触发重复抄送（hook 每回复可能触发多次）。
5. 自验：发一条真实消息看开发群收到；查指纹文件 mtime 有记录 = 已生效。

### 两个必踩坑

- **项目级 hook 对子 agent 同样触发**：子 agent 在同一项目目录跑也加载 UserPromptSubmit/Stop，子 agent 收到的任务 prompt 会被当"用户输入"抄送（用户会发现"子agent的输入也当成我的输入抄送"）。做"处理用户输入"的 hook/脚本必须区分主会话 vs 子 agent（如 transcript_path 判断），上线后主动验证子 agent 场景不误触发（§18 教训27）。
- **判断"已生效"看运行证据非推断**：别凭"还差用户确认才生效"推断。查指纹/日志文件 mtime（如 `/tmp/feishu_hook_sent.txt` 有运行记录）+ 实际发送记录 + curl 线上（§18 教训26）。

### 外部消息→主控（listener 自动处理，02bd47f8f）

listener 收到需求**自动 落盘 `data/feishu_requests/` + 进 TASKS 待办 + notify 即时回执**，主控只消费落盘文件、零轮询。凡是"外部消息→主控"链路尽量这样做，不要主控 1min 轮询。

### 通知架构方向（§18 经验②③）

- 子agent 中间层转发不可行（1 分钟轮询=每天 1440 次模型回合，物理跟不上+token爆炸）。
- 本版 claude 2.1.224 有 `TaskCompleted` hook（后台任务完成时确定性触发），是 cron 兜底轮询之外的可能替代方向（待验证）。

---

*本文档是子 agent 快速上手的总览引导。发现新坑/新任务类型请补充（落档防重犯，§19 自我成长机制）。硬规范以 `CLAUDE.md` 为准，本文只摘任务执行相关要点。*
